# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chat is part of the deliberation.

People contribute by typing as well as by speaking — links, corrections, the
point they did not want to interrupt for. Folding the room's chat into the
transcript means the analysis sees the whole discussion, and it makes the
pipeline demonstrable even with no microphone at all.

Each room's chat becomes one synthetic recording per author, so the existing
transcript model (one recording = one person) still holds and every chat line
carries the same evidence-linkable segment id as a spoken one.
"""

from sqlalchemy import select

from citizens_online.db.models import (
    Participant,
    Recording,
    Room,
    Round,
    Transcript,
    TranscriptSegment,
)
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import session_scope
from citizens_online.infra.nextcloud.talk_adapter import TalkAdapter, TalkError
from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

# Talk system messages (joins, calls, bot notices) are not contributions.
SKIPPED_MESSAGE_TYPES = {"system", "command"}


def import_round_chat(round_id: str, service_user: str) -> int:
    """Read each room's chat and store real messages as transcript segments."""
    with session_scope() as db:
        round_obj = db.get(Round, round_id)
        if round_obj is None:
            return 0
        rooms = [r for r in round_obj.rooms if r.talk_token]
        people = {p.nc_user_id: p for p in round_obj.session.participants}
        started = round_obj.started_at
        room_tokens = [(r.id, r.talk_token) for r in rooms]
    if not room_tokens:
        return 0

    talk = TalkAdapter(service_user=service_user)
    imported = 0
    for room_id, token in room_tokens:
        try:
            messages = talk.read_messages(token, last_known_id=0, limit=200)
        except TalkError as exc:
            log.warning("chat_read_failed", room=token, error=str(exc)[:200])
            continue
        # Talk returns newest first
        messages = sorted(messages, key=lambda m: m.get("timestamp", 0))
        by_author: dict[str, list[dict]] = {}
        for message in messages:
            if message.get("systemMessage"):
                continue
            if message.get("messageType") in SKIPPED_MESSAGE_TYPES:
                continue
            if message.get("actorType") != "users":
                continue  # bots and guests are not participants
            text = (message.get("message") or "").strip()
            if not text or text.startswith("{"):
                continue
            by_author.setdefault(message["actorId"], []).append(message)

        with session_scope() as db:
            room: Room | None = db.get(Room, room_id)
            if room is None:
                continue
            round_obj = db.get(Round, round_id)
            started = round_obj.started_at if round_obj else None
            people = {p.nc_user_id: p for p in room.round.session.participants}
            for actor_id, author_messages in by_author.items():
                participant: Participant | None = people.get(actor_id)
                if participant is None:
                    continue
                imported += _store_chat_for(db, room, participant, author_messages, started)
    if imported:
        log.info("chat_imported", round_id=round_id, segments=imported)
    return imported


def _store_chat_for(db, room: Room, participant: Participant, messages: list[dict], started) -> int:
    """One synthetic recording per author per room, replaced on re-import."""
    recording = db.execute(
        select(Recording).where(
            Recording.room_id == room.id,
            Recording.participant_id == participant.id,
            Recording.mime_type == "text/chat",
        )
    ).scalar_one_or_none()
    if recording is None:
        recording = Recording(
            session_id=room.session_id,
            round_id=room.round_id,
            room_id=room.id,
            participant_id=participant.id,
            attempt=900,  # kept clear of real capture attempts
            mime_type="text/chat",
            state="TRANSCRIBED",
            started_at=started or utcnow(),
        )
        db.add(recording)
        db.flush()

    existing = db.execute(
        select(Transcript).where(Transcript.recording_id == recording.id)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.flush()

    transcript = Transcript(
        recording_id=recording.id,
        provider="talk_chat",
        model="",
        language=room.round.session.language,
        source="live",
    )
    db.add(transcript)
    db.flush()

    base = started.timestamp() if started else (messages[0].get("timestamp") or 0)
    stored = 0
    for index, message in enumerate(messages):
        offset = max(0.0, float(message.get("timestamp", base)) - float(base))
        db.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                sequence=index,
                speaker_label=participant.display_name,
                participant_id=participant.id,
                nc_user_id=participant.nc_user_id,
                origin="chat",
                start_seconds=offset,
                end_seconds=offset,
                text=(message.get("message") or "")[:4000],
            )
        )
        stored += 1
    db.flush()
    return stored
