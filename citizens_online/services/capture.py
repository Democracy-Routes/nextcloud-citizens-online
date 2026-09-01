# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-participant audio capture.

The in-person sibling of this app records one microphone per *table*. Online,
each participant's own browser records *them*, which is what makes every
transcript line carry a real name instead of an anonymous speaker label — no
acoustic diarization anywhere (spec §11).

The upload protocol is Citizens' and is deliberately unchanged: chunks are
hashed and stored locally before any upload is attempted, duplicates are
acknowledged rather than rejected, and a recording is only assembled once every
sequence has arrived. The network is never allowed to be the reason audio is
lost.
"""

import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import (
    AudioChunk,
    CaptureSession,
    Participant,
    Recording,
    Room,
    RoomMember,
    Round,
)
from citizens_online.db.models.base import utcnow
from citizens_online.logging_setup import get_logger
from citizens_online.services.jobs import enqueue_job
from citizens_online.services.recording_states import transition
from citizens_online.storage.paths import chunk_path, recording_dir
from citizens_online.storage.space import require_room

log = get_logger(__name__)

MAX_CHUNK_BYTES = 5 * 1024 * 1024
LAST_SEEN_RESOLUTION = 15.0

# States a recording may be replaced from, if a participant starts again.
RERECORDABLE_STATES = ("CREATED", "AUDIO_INVALID", "UPLOAD_INCOMPLETE")
HEALTHY_STATES = (
    "RECORDING",
    "FINALIZING",
    "WAITING_FOR_CHUNKS",
    "ASSEMBLING",
    "AUDIO_READY",
    "TRANSCRIBING",
    "TRANSCRIBED",
    "ANALYZING",
    "READY_FOR_REVIEW",
    "REVIEWED",
)


def get_or_create_capture_session(db: DbSession, participant: Participant) -> CaptureSession:
    obj = db.execute(
        select(CaptureSession).where(CaptureSession.participant_id == participant.id)
    ).scalar_one_or_none()
    if obj is None:
        obj = CaptureSession(
            session_id=participant.session_id,
            participant_id=participant.id,
            nc_user_id=participant.nc_user_id,
            last_seen_at=utcnow(),
        )
        db.add(obj)
        db.flush()
    return obj


def start_recording(
    db: DbSession, participant: Participant, round_obj: Round, mime_type: str
) -> Recording:
    """Begin capturing this participant for this round."""
    if round_obj.session_id != participant.session_id:
        raise HTTPException(status_code=404, detail="Round not found")
    if round_obj.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="This round is not running")
    if round_obj.session.closed_at:
        raise HTTPException(status_code=409, detail="This session is closed")
    if not round_obj.session.capture_enabled:
        raise HTTPException(status_code=409, detail="Capture is disabled for this session")

    member = db.execute(
        select(RoomMember).where(
            RoomMember.round_id == round_obj.id, RoomMember.participant_id == participant.id
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=409, detail="You are not assigned to a room in this round")
    room: Room | None = db.get(Room, member.room_id)
    if room is None:
        raise HTTPException(status_code=409, detail="Room not found")

    existing = list(
        db.execute(
            select(Recording).where(
                Recording.round_id == round_obj.id, Recording.participant_id == participant.id
            )
        ).scalars()
    )
    healthy = [r for r in existing if r.state in HEALTHY_STATES]
    if healthy:
        # A reconnecting browser must be able to keep contributing rather than
        # be locked out for the rest of the round, so this is a new attempt
        # instead of a 409 — unlike the in-person app, where a second recording
        # for the same table would be a duplicate of the same microphone.
        latest = healthy[-1]
        if latest.state in ("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS"):
            return latest

    capture_session = get_or_create_capture_session(db, participant)
    recording = Recording(
        session_id=participant.session_id,
        round_id=round_obj.id,
        room_id=room.id,
        participant_id=participant.id,
        attempt=len(existing) + 1,
        capture_session_id=capture_session.id,
        mime_type=(mime_type or "")[:80],
        started_at=utcnow(),
    )
    db.add(recording)
    db.flush()
    transition(recording, "RECORDING")
    log.info(
        "capture_started",
        recording_id=recording.id,
        round_id=round_obj.id,
        participant=participant.nc_user_id,
        attempt=recording.attempt,
    )
    return recording


def get_own_recording(db: DbSession, participant: Participant, recording_id: str) -> Recording:
    """The only authorization gate on the capture endpoints.

    A participant may only ever touch their own recording. Getting this wrong
    would let one person read another's live captions.
    """
    recording = db.get(Recording, recording_id)
    if recording is None or recording.participant_id != participant.id:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def receive_chunk(
    db: DbSession, recording: Recording, sequence_number: int, client_sha256: str, data: bytes
) -> dict:
    if recording.state == "UPLOAD_INCOMPLETE":
        # giving up on an upload is reversible: a late browser may still finish
        transition(recording, "WAITING_FOR_CHUNKS")
    if recording.state not in ("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS"):
        raise HTTPException(status_code=409, detail=f"Recording is {recording.state}")
    if not data:
        raise HTTPException(status_code=400, detail="Empty chunk")
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Chunk too large")
    if hashlib.sha256(data).hexdigest() != (client_sha256 or "").lower():
        raise HTTPException(status_code=400, detail="Checksum mismatch")

    existing = db.execute(
        select(AudioChunk).where(
            AudioChunk.recording_id == recording.id,
            AudioChunk.sequence_number == sequence_number,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.sha256 == client_sha256.lower():
            # idempotent: a retried upload is an acknowledgement, not an error
            return {"acknowledged": True, "duplicate": True, "sequence_number": sequence_number}
        raise HTTPException(status_code=409, detail="Sequence already stored with different content")

    from citizens_online.config import get_settings

    root = get_settings().app_persistent_storage
    require_room(root, len(data), context="chunk_upload")
    directory = recording_dir(
        root, recording.session_id, recording.round_id, recording.room_id, recording.id
    )
    path = chunk_path(directory, sequence_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    db.add(
        AudioChunk(
            recording_id=recording.id,
            sequence_number=sequence_number,
            sha256=client_sha256.lower(),
            size_bytes=len(data),
            path=str(path.relative_to(root)),
        )
    )
    recording.received_chunks += 1
    return {"acknowledged": True, "duplicate": False, "sequence_number": sequence_number}


def missing_sequences(db: DbSession, recording: Recording) -> list[int]:
    if recording.total_chunks is None:
        return []
    stored = {
        row[0]
        for row in db.execute(
            select(AudioChunk.sequence_number).where(AudioChunk.recording_id == recording.id)
        ).all()
    }
    return sorted(set(range(recording.total_chunks)) - stored)


def complete_recording(db: DbSession, recording: Recording, total_chunks: int) -> dict:
    if recording.state == "RECORDING":
        transition(recording, "FINALIZING")
    elif recording.state == "UPLOAD_INCOMPLETE":
        transition(recording, "WAITING_FOR_CHUNKS")
    elif recording.state not in ("FINALIZING", "WAITING_FOR_CHUNKS"):
        raise HTTPException(status_code=409, detail=f"Recording is {recording.state}")

    recording.total_chunks = total_chunks
    recording.ended_at = recording.ended_at or utcnow()
    missing = missing_sequences(db, recording)
    if missing:
        if recording.state != "WAITING_FOR_CHUNKS":
            transition(recording, "WAITING_FOR_CHUNKS")
        return {"state": recording.state, "missing_sequences": missing}
    transition(recording, "ASSEMBLING")
    enqueue_job(db, "ASSEMBLE_AUDIO", {"recording_id": recording.id})
    return {"state": recording.state, "missing_sequences": []}


def recording_status(db: DbSession, recording: Recording) -> dict:
    data = {
        "recording_id": recording.id,
        "state": recording.state,
        "received_chunks": recording.received_chunks,
        "total_chunks": recording.total_chunks,
        "error_code": recording.error_code,
        "duration_seconds": recording.duration_seconds,
    }
    if recording.state in ("WAITING_FOR_CHUNKS", "UPLOAD_INCOMPLETE"):
        data["missing_sequences"] = missing_sequences(db, recording)
    return data


def record_heartbeat(db: DbSession, participant: Participant, payload: dict) -> None:
    import json

    obj = get_or_create_capture_session(db, participant)
    now = utcnow()
    if obj.last_seen_at is None or (now - obj.last_seen_at).total_seconds() >= LAST_SEEN_RESOLUTION:
        obj.last_seen_at = now
    obj.last_status_json = json.dumps(payload)[:4000]
    obj.last_status_at = now
