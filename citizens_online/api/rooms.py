# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Room assignment and the live moderator dashboard."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import AgentEvent, ModerationEvent, Recording
from citizens_online.db.session import get_db, get_read_db
from citizens_online.infra.nextcloud.talk_adapter import MAX_BREAKOUT_ROOMS_PER_PARENT
from citizens_online.security.identity import CurrentUser
from citizens_online.services import deliberation as delib
from citizens_online.services import settings as settings_svc
from citizens_online.services.live_captions import LIVE_CAPTIONS

router = APIRouter(tags=["rooms"])
DB = Annotated[DbSession, Depends(get_db)]
ReadDB = Annotated[DbSession, Depends(get_read_db)]


class RandomizeIn(BaseModel):
    # Bounded by Talk's own ceiling rather than an arbitrary number, so an
    # impossible plan is refused here instead of at start_round, in front of a
    # waiting assembly.
    rooms: int | None = Field(default=None, ge=1, le=MAX_BREAKOUT_ROOMS_PER_PARENT)


class MoveIn(BaseModel):
    participant_id: str = Field(min_length=1, max_length=36)
    room_id: str = Field(min_length=1, max_length=36)


@router.get("/rounds/{round_id}/rooms")
def list_rooms(round_id: str, db: ReadDB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    return delib.rooms_payload(db, obj)


@router.post("/rounds/{round_id}/rooms/randomize")
def randomize(round_id: str, db: DB, user: CurrentUser, payload: RandomizeIn | None = None):
    obj = delib.get_owned_round(db, round_id, user)
    delib.assign_randomly(db, obj, payload.rooms if payload else None)
    return delib.rooms_payload(db, obj)


@router.post("/rounds/{round_id}/rooms/copy-previous")
def copy_previous(round_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    delib.copy_previous_assignment(db, obj)
    return delib.rooms_payload(db, obj)


@router.post("/rounds/{round_id}/rooms/move")
def move(round_id: str, payload: MoveIn, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    delib.move_participant(db, obj, payload.participant_id, payload.room_id)
    return delib.rooms_payload(db, obj)


@router.post("/rooms/{room_id}/message")
def message_room(room_id: str, payload: dict, db: DB, user: CurrentUser):
    """Let a human moderator speak into one room, through the same bot."""
    from citizens_online.db.models import Room
    from citizens_online.infra.nextcloud import bot as bot_module

    room = db.get(Room, room_id)
    if room is None:
        return {"sent": False, "reason": "room not found"}
    delib.get_owned_session(db, room.session_id, user)
    text = (payload.get("message") or "").strip()[:2000]
    if not text or not room.talk_token:
        return {"sent": False, "reason": "no message or room is not open"}
    sent = bot_module.send(room.talk_token, text)
    db.add(
        ModerationEvent(
            session_id=room.session_id,
            round_id=room.round_id,
            room_id=room.id,
            type="moderator_message",
            severity="info",
            rule="human_moderator",
            automatic=False,
            action="facilitator_message",
            message=text,
            reviewed_by=user,
        )
    )
    return {"sent": sent}


@router.get("/rounds/{round_id}/monitor")
def monitor(round_id: str, db: ReadDB, user: CurrentUser):
    """Everything the Live tab shows, in one poll."""
    obj = delib.get_owned_round(db, round_id, user)
    rooms = delib.rooms_payload(db, obj)

    # live speaking figures come from the in-memory meters, which are ahead of
    # what has been flushed to the database
    recordings = {
        r.participant_id: r
        for r in db.execute(
            select(Recording).where(
                Recording.round_id == obj.id,
                Recording.state.in_(("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS")),
            )
        ).scalars()
    }
    for room in rooms:
        for member in room["members"]:
            recording = recordings.get(member["participant_id"])
            member["capturing"] = recording is not None
            if recording is not None:
                live = LIVE_CAPTIONS.speaking(recording.id)
                if live:
                    member["speaking_ms"] = max(member["speaking_ms"], live["speaking_ms"])
                    member["speaking_now"] = live["speaking"]
        total = sum(m["speaking_ms"] for m in room["members"]) or 0
        room["speaking_ms"] = total
        for member in room["members"]:
            member["share"] = round(member["speaking_ms"] / total, 3) if total else 0.0
        room["members"].sort(key=lambda m: -m["speaking_ms"])

    alerts = [
        {
            "id": e.id,
            "type": e.type,
            "severity": e.severity,
            "rule": e.rule,
            "threshold": e.threshold,
            "observed": e.observed,
            "message": e.message,
            "room_id": e.room_id,
            "participant_id": e.participant_id,
            "automatic": e.automatic,
            "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
            "created_at": e.created_at.isoformat(),
        }
        for e in db.execute(
            select(ModerationEvent)
            .where(ModerationEvent.round_id == obj.id)
            .order_by(ModerationEvent.created_at.desc())
            .limit(50)
        ).scalars()
    ]
    agent_misses = db.execute(
        select(AgentEvent).where(AgentEvent.round_id == obj.id, AgentEvent.status == "missed")
    ).scalars().all()
    snap = settings_svc.snapshot()
    return {
        "round": delib.round_payload(obj),
        "remaining_seconds": delib.remaining_seconds(obj),
        "rooms": rooms,
        "alerts": alerts,
        "parent_token": obj.session.parent_token,
        "facilitator": {
            "enabled": obj.session.facilitator_enabled and snap["facilitator_enabled"],
            "configured": bool(snap["llm_model"] and snap["llm_base_url"]),
            "missed": len(agent_misses),
            # the honest indicator: the model is configured but not answering
            "degraded": len(agent_misses) > 0,
        },
        "capture": {
            "enabled": obj.session.capture_enabled,
            "active": len(recordings),
        },
    }


@router.get("/rooms/{room_id}/transcript")
def room_transcript(room_id: str, db: ReadDB, user: CurrentUser):
    from citizens_online.db.models import Room
    from citizens_online.services.transcripts import room_transcript_payload

    room = db.get(Room, room_id)
    if room is None:
        return {"segments": []}
    delib.get_owned_session(db, room.session_id, user)
    return room_transcript_payload(db, room)
