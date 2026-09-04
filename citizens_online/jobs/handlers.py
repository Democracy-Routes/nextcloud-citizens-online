# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What happens after a round ends.

The chain is: assemble each participant's audio → transcribe it → analyse each
room → cluster the round. Every handler is idempotent (it checks the state it
expects at the top and returns quietly if the work is already done), and every
one commits before making a network call, because holding the write lock across
an HTTP round-trip is how this codebase's predecessor produced "database is
locked" errors during a live assembly.

Nothing here is allowed to take the deliberation down with it: a failed
transcription or a missing model leaves the recording marked and the round
reviewable, never stuck.
"""

import json

from sqlalchemy import select

from citizens_online.db.models import Recording, Room, Round, Transcript
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import session_scope
from citizens_online.logging_setup import get_logger
from citizens_online.services import analysis as analysis_svc
from citizens_online.services import settings as settings_svc
from citizens_online.services import transcripts as transcripts_svc
from citizens_online.services.audio import AudioAssemblyError, StorageFullError, assemble_recording
from citizens_online.services.jobs import enqueue_job
from citizens_online.services.recording_states import transition
from citizens_online.storage.paths import live_caption_path

log = get_logger(__name__)


class PermanentJobError(Exception):
    """Do not retry: the input is wrong, not the moment."""


def _commit_failure_state(session, recording: Recording, state: str, code: str) -> None:
    """Persist the failure before re-raising — otherwise the runner's rollback
    discards it and the recording spins forever."""
    session.rollback()
    fresh = session.get(Recording, recording.id)
    if fresh is not None:
        fresh.error_code = code
        try:
            transition(fresh, state)
        except Exception:
            fresh.state = state
        session.commit()


def handle_assemble_audio(payload: dict) -> None:
    recording_id = payload["recording_id"]
    with session_scope() as db:
        recording = db.get(Recording, recording_id)
        if recording is None:
            return
        if recording.state != "ASSEMBLING":
            return  # already done, or moved on
        try:
            assemble_recording(db, recording)
        except StorageFullError:
            _commit_failure_state(db, recording, "ASSEMBLING", "STORAGE_FULL")
            raise  # retryable: disk may free up
        except AudioAssemblyError as exc:
            _commit_failure_state(db, recording, "AUDIO_INVALID", exc.code)
            raise PermanentJobError(str(exc)) from exc
    _maybe_enqueue_transcription(recording_id)


def _maybe_enqueue_transcription(recording_id: str) -> None:
    snap = settings_svc.snapshot()
    with session_scope() as db:
        recording = db.get(Recording, recording_id)
        if recording is None or recording.state != "AUDIO_READY":
            return
        if snap["stt_batch_enabled"] and snap["stt_provider"] not in ("none", "", "vosk"):
            enqueue_job(db, "TRANSCRIBE_FINAL", {"recording_id": recording_id})
        elif snap["stt_batch_enabled"] and snap["stt_provider"] == "vosk":
            enqueue_job(db, "TRANSCRIBE_FINAL", {"recording_id": recording_id})
        else:
            # no batch engine: keep whatever the live captions produced
            enqueue_job(db, "TRANSCRIBE_FROM_LIVE", {"recording_id": recording_id})


def handle_transcribe_final(payload: dict) -> None:
    """A more accurate pass over the captured audio, replacing the live text."""
    recording_id = payload["recording_id"]
    snap = settings_svc.snapshot()
    with session_scope() as db:
        recording = db.get(Recording, recording_id)
        if recording is None or recording.state not in ("AUDIO_READY", "TRANSCRIPTION_FAILED"):
            return
        if not recording.canonical_audio_path:
            return
        transition(recording, "TRANSCRIBING")
        session_language = recording.session.language
        from citizens_online.config import get_settings

        audio_path = get_settings().app_persistent_storage / recording.canonical_audio_path
        mime = recording.mime_type
        db.commit()  # release the write lock before the provider call

        try:
            normalized = _run_batch_provider(snap, audio_path, mime, session_language)
        except Exception as exc:
            log.warning("batch_transcription_failed", recording_id=recording_id, error=str(exc)[:300])
            _commit_failure_state(db, recording, "TRANSCRIPTION_FAILED", "STT_FAILED")
            # fall back to the live captions rather than losing the round
            with session_scope() as db2:
                enqueue_job(db2, "TRANSCRIBE_FROM_LIVE", {"recording_id": recording_id})
            return

        fresh = db.get(Recording, recording_id)
        transcripts_svc.store_transcript(db, fresh, normalized, origin="postcall")
        transition(fresh, "TRANSCRIBED")
    _maybe_enqueue_room_analysis(recording_id)


def _run_batch_provider(snap: dict, path, mime: str, language: str):
    provider = snap["stt_provider"]
    if provider == "vosk":
        from citizens_online.providers.transcription import vosk

        return vosk.transcribe_file(
            api_key="",
            path=path,
            mime_type=mime,
            language=language,
            model=settings_svc.vosk_model_for(snap, language),
            base_url=snap["vosk_url"],
        )
    if provider == "whisper":
        from citizens_online.providers.transcription import whisper

        return whisper.transcribe_file(
            api_key=snap.get("stt_api_key", ""),
            path=path,
            mime_type=mime,
            language=language,
            base_url=snap["whisper_base_url"],
        )
    if provider == "mistral":
        from citizens_online.providers.transcription import mistral

        return mistral.transcribe_file(
            api_key=snap.get("stt_api_key", ""), path=path, mime_type=mime, language=language
        )
    raise PermanentJobError(f"No batch transcription provider configured ({provider!r})")


def handle_transcribe_from_live(payload: dict) -> None:
    """Promote the live captions to the transcript of record."""
    recording_id = payload["recording_id"]
    with session_scope() as db:
        recording = db.get(Recording, recording_id)
        if recording is None:
            return
        existing = db.execute(
            select(Transcript).where(Transcript.recording_id == recording.id)
        ).scalar_one_or_none()
        if existing is not None and existing.source == "final":
            return  # a better transcript already exists
        from citizens_online.config import get_settings

        path = live_caption_path(
            get_settings().app_persistent_storage, recording.session_id, recording.id
        )
        if not path.exists():
            if recording.state in ("AUDIO_READY", "TRANSCRIPTION_FAILED"):
                recording.error_code = recording.error_code or "LIVE_CAPTIONS_MISSING"
            return
        try:
            data = json.loads(path.read_text())
        except Exception:
            recording.error_code = "LIVE_CAPTIONS_UNREADABLE"
            return
        normalized = transcripts_svc.transcript_from_live_captions(data)
        if not normalized.segments:
            recording.error_code = "LIVE_CAPTIONS_EMPTY"
            return
        transcripts_svc.store_transcript(db, recording, normalized, origin="live")
        if recording.state in ("AUDIO_READY", "TRANSCRIBING", "TRANSCRIPTION_FAILED"):
            try:
                transition(recording, "TRANSCRIBED")
            except Exception:
                recording.state = "TRANSCRIBED"
    _maybe_enqueue_room_analysis(recording_id)


def _maybe_enqueue_room_analysis(recording_id: str) -> None:
    with session_scope() as db:
        recording = db.get(Recording, recording_id)
        if recording is None:
            return
        enqueue_job(db, "ANALYZE_ROOM", {"room_id": recording.room_id})


def handle_analyze_room(payload: dict) -> None:
    room_id = payload["room_id"]
    snap = settings_svc.snapshot()
    if not analysis_svc.analysis_ready(snap):
        log.info("analysis_skipped_no_model", room_id=room_id)
        _maybe_finish_round_for_room(room_id)
        return
    store = settings_svc.default_store()  # built before the transaction opens
    with session_scope() as db:
        room = db.get(Room, room_id)
        if room is None:
            return
        try:
            analysis_svc.analyze_room(db, store, room)
        except analysis_svc.AnalysisError as exc:
            log.warning("room_analysis_failed", room_id=room_id, error=str(exc)[:300])
            if getattr(exc, "permanent", False):
                raise PermanentJobError(str(exc)) from exc
            raise
    _maybe_finish_round_for_room(room_id)


def _maybe_finish_round_for_room(room_id: str) -> None:
    """Cluster the round once every room that could produce findings has."""
    with session_scope() as db:
        room = db.get(Room, room_id)
        if room is None:
            return
        round_obj = db.get(Round, room.round_id)
        if round_obj is None or round_obj.status not in ("PROCESSING", "ENDED"):
            return
        pending = db.execute(
            select(Recording).where(
                Recording.round_id == round_obj.id,
                Recording.state.in_(
                    ("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING", "TRANSCRIBING")
                ),
            )
        ).scalars().first()
        if pending is not None:
            return
        # de-dupe: one clustering job per round
        from citizens_online.db.models import AppJob

        existing = db.execute(
            select(AppJob).where(
                AppJob.type == "ANALYZE_ROUND",
                AppJob.state.in_(("QUEUED", "RUNNING", "RETRY")),
            )
        ).scalars().all()
        payload = json.dumps({"round_id": round_obj.id})
        if any(j.payload_json == payload for j in existing):
            return
        enqueue_job(db, "ANALYZE_ROUND", {"round_id": round_obj.id})


def handle_analyze_round(payload: dict) -> None:
    round_id = payload["round_id"]
    snap = settings_svc.snapshot()
    store = settings_svc.default_store()  # built before the transaction opens
    with session_scope() as db:
        round_obj = db.get(Round, round_id)
        if round_obj is None:
            return
        if analysis_svc.analysis_ready(snap):
            try:
                analysis_svc.analyze_round(db, store, round_obj)
            except analysis_svc.AnalysisError as exc:
                log.warning("round_analysis_failed", round_id=round_id, error=str(exc)[:300])
        fresh = db.get(Round, round_id)
        fresh.status = "READY_FOR_REVIEW"
        session_obj = fresh.session
        if all(r.status in ("READY_FOR_REVIEW", "ENDED") for r in session_obj.rounds):
            session_obj.status = "REVIEW"


def handle_finalize_round(payload: dict) -> None:
    """Right after a round ends: fold in the chat, then wait for the audio."""
    round_id = payload["round_id"]
    snap = settings_svc.snapshot()
    from citizens_online.services import chat_import

    try:
        chat_import.import_round_chat(round_id, snap["talk_service_user"])
    except Exception:
        log.warning("chat_import_failed", round_id=round_id, exc_info=True)
    with session_scope() as db:
        round_obj = db.get(Round, round_id)
        if round_obj is None:
            return
        pending = db.execute(
            select(Recording).where(
                Recording.round_id == round_id,
                Recording.state.in_(("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS")),
            )
        ).scalars().all()
        for recording in pending:
            # a browser that never called complete() still has usable chunks
            if recording.received_chunks:
                recording.total_chunks = recording.total_chunks or recording.received_chunks
                try:
                    transition(recording, "ASSEMBLING")
                    enqueue_job(db, "ASSEMBLE_AUDIO", {"recording_id": recording.id})
                except Exception:
                    recording.error_code = "INCOMPLETE_AT_ROUND_END"
        rooms = list(db.execute(select(Room).where(Room.round_id == round_id)).scalars())
    for room in rooms:
        with session_scope() as db:
            enqueue_job(db, "ANALYZE_ROOM", {"room_id": room.id})



def handle_invite_participants(payload: dict) -> None:
    """Tell people the assembly exists.

    A job rather than part of the request: notifying somebody means impersonating
    them, and each impersonation re-fetches the server capabilities, so fifty
    participants is roughly a hundred round-trips — far too long to hold a
    browser on.
    """
    from citizens_online.db.models import Participant, Session
    from citizens_online.services import notifications

    session_id = payload["session_id"]
    force = bool(payload.get("force"))

    with session_scope() as db:
        session_obj = db.get(Session, session_id)
        if session_obj is None:
            return
        targets = [
            (p.id, p.nc_user_id)
            for p in session_obj.participants
            if force or p.invited_at is None
        ]
        subject, message = notifications.invite_text(
            session_obj.name, len(session_obj.rounds), session_obj.language
        )
    if not targets:
        return

    link = notifications.app_link()
    nc = notifications._client()
    delivered = []
    for participant_id, user_id in targets:
        if notifications.notify(nc, user_id, subject, message, link=link):
            delivered.append(participant_id)

    # Only people who were actually reached are marked invited, so a failure is
    # retried by the next press of the button rather than silently swallowed.
    if delivered:
        with session_scope() as db:
            for participant_id in delivered:
                person = db.get(Participant, participant_id)
                if person is not None:
                    person.invited_at = utcnow()
    log.info(
        "participants_invited",
        session_id=session_id,
        delivered=len(delivered),
        attempted=len(targets),
    )


HANDLERS = {
    "ASSEMBLE_AUDIO": handle_assemble_audio,
    "TRANSCRIBE_FINAL": handle_transcribe_final,
    "TRANSCRIBE_FROM_LIVE": handle_transcribe_from_live,
    "ANALYZE_ROOM": handle_analyze_room,
    "ANALYZE_ROUND": handle_analyze_round,
    "FINALIZE_ROUND": handle_finalize_round,
    "INVITE_PARTICIPANTS": handle_invite_participants,
}
