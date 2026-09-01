# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The participant's own microphone.

These endpoints are authenticated as a normal Nextcloud user — the participant
themselves — and every one of them is scoped to that person's own recording.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession
from starlette.concurrency import run_in_threadpool

from citizens_online.db.session import get_db, get_read_db, session_scope
from citizens_online.security.identity import CurrentUser
from citizens_online.services import capture as capture_svc
from citizens_online.services import settings as settings_svc
from citizens_online.services.live_captions import LIVE_CAPTIONS
from citizens_online.services.participation import current_participation, require_participant

router = APIRouter(prefix="/capture", tags=["capture"])
DB = Annotated[DbSession, Depends(get_db)]
ReadDB = Annotated[DbSession, Depends(get_read_db)]


class StartIn(BaseModel):
    round_id: str = Field(min_length=1, max_length=36)
    mime_type: str = Field(min_length=1, max_length=80)


class CompleteIn(BaseModel):
    total_chunks: int = Field(ge=1, le=100000)


@router.post("/start", status_code=201)
def start(payload: StartIn, db: DB, user: CurrentUser):
    from citizens_online.db.models import Round

    round_obj = db.get(Round, payload.round_id)
    if round_obj is None:
        raise HTTPException(status_code=404, detail="Round not found")
    participant = require_participant(db, round_obj.session_id, user)
    recording = capture_svc.start_recording(db, participant, round_obj, payload.mime_type)
    return {"recording_id": recording.id, "state": recording.state}


@router.post("/{recording_id}/chunks/{sequence_number}")
async def upload_chunk(
    recording_id: str,
    sequence_number: int,
    request: Request,
    x_chunk_sha256: Annotated[str, Header()] = "",
):
    """Store one audio chunk.

    The shape of this handler is load-bearing and copied deliberately from the
    in-person app: the body is read *before* any database work, and everything
    blocking runs in a threadpool, because holding SQLite's single write slot
    across a body read wedged the app under concurrent uploads.
    """
    if not x_chunk_sha256:
        raise HTTPException(status_code=400, detail="Missing X-Chunk-SHA256")
    if sequence_number < 0 or sequence_number > 100000:
        raise HTTPException(status_code=400, detail="Invalid sequence number")
    body = await request.body()

    def _persist() -> tuple[dict, str, str, str]:
        # read caption config before opening the transaction: it is an OCS call
        snap = settings_svc.snapshot()
        with session_scope() as db:
            user = request.headers.get("x-test-user") or _user_from_request(request)
            recording_id_out = recording_id
            from citizens_online.db.models import Recording

            recording = db.get(Recording, recording_id_out)
            if recording is None:
                raise HTTPException(status_code=404, detail="Recording not found")
            participant = require_participant(db, recording.session_id, user)
            recording = capture_svc.get_own_recording(db, participant, recording_id_out)
            result = capture_svc.receive_chunk(
                db, recording, sequence_number, x_chunk_sha256, body
            )
            return result, recording.id, participant.display_name, recording.session.language

    result, rec_id, speaker, language = await run_in_threadpool(_persist)
    if not result.get("duplicate"):
        snap = settings_svc.snapshot()
        LIVE_CAPTIONS.feed(
            rec_id,
            body,
            {
                "enabled": snap["stt_live_enabled"] and snap["stt_provider"] != "none",
                "provider": snap["stt_provider"],
                "api_key": "",
                "model": snap["vosk_live_model"],
                "endpoint": snap["vosk_url"],
                "language_models": snap["vosk_language_models"],
            },
            language,
            speaker_name=speaker,
        )
    return result


def _user_from_request(request: Request) -> str:
    """Identity as AppAPI supplies it, without a FastAPI dependency.

    A dependency would resolve before the body is read, which is exactly the
    ordering this endpoint must avoid.
    """
    import base64

    header = request.headers.get("authorization-app-api", "")
    if not header:
        raise HTTPException(status_code=401, detail="No authenticated Nextcloud user")
    try:
        return base64.b64decode(header).decode().split(":", 1)[0]
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Bad AppAPI authorization") from exc


@router.post("/{recording_id}/complete")
def complete(recording_id: str, payload: CompleteIn, db: DB, user: CurrentUser):
    from citizens_online.db.models import Recording

    recording = db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    participant = require_participant(db, recording.session_id, user)
    recording = capture_svc.get_own_recording(db, participant, recording_id)
    result = capture_svc.complete_recording(db, recording, payload.total_chunks)
    if not result["missing_sequences"]:
        LIVE_CAPTIONS.finish(recording.id)
    return result


@router.get("/{recording_id}")
def status(recording_id: str, db: ReadDB, user: CurrentUser):
    from citizens_online.db.models import Recording

    recording = db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    participant = require_participant(db, recording.session_id, user)
    recording = capture_svc.get_own_recording(db, participant, recording_id)
    return capture_svc.recording_status(db, recording)


@router.get("/{recording_id}/live")
def live(recording_id: str, db: ReadDB, user: CurrentUser):
    """The participant's own live captions. Read-only session: caption polling
    is most of the traffic and must never take the write lock."""
    from citizens_online.db.models import Recording

    recording = db.get(Recording, recording_id)
    if recording is None:
        return {"active": False, "lines": []}
    participant = require_participant(db, recording.session_id, user)
    capture_svc.get_own_recording(db, participant, recording_id)
    data = LIVE_CAPTIONS.status(recording_id)
    data["speaking"] = LIVE_CAPTIONS.speaking(recording_id)
    return data


@router.post("/heartbeat")
def heartbeat(payload: dict, db: DB, user: CurrentUser):
    state = current_participation(db, user)
    if state is None:
        return {"ok": False}
    capture_svc.record_heartbeat(db, state["participant"], payload)
    return {"ok": True}
