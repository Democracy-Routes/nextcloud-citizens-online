# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the current user should be looking at.

A participant never navigates the app: their screen follows the deliberation
(spec §23). This module answers "what is happening to me right now" in one
query, which is all the participant view polls.
"""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import Participant, Recording, Room, RoomMember, Round, Session
from citizens_online.db.models.base import utcnow
from citizens_online.services import deliberation as delib
from citizens_online.services import settings as settings_svc


def require_participant(db: DbSession, session_id: str, user: str) -> Participant:
    obj = db.execute(
        select(Participant).where(
            Participant.session_id == session_id, Participant.nc_user_id == user
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="You are not a participant in this session")
    return obj


def current_participation(db: DbSession, user: str) -> dict | None:
    """The most relevant session this user is a participant in.

    Prefers a session with a running round; otherwise the most recent one that
    has not been closed.
    """
    rows = list(
        db.execute(select(Participant).where(Participant.nc_user_id == user)).scalars()
    )
    if not rows:
        return None
    best: tuple[int, Participant, Session, Round | None] | None = None
    for participant in rows:
        session_obj = db.get(Session, participant.session_id)
        if session_obj is None:
            continue
        active = next((r for r in session_obj.rounds if r.status == "ACTIVE"), None)
        if active:
            rank = 0
        elif session_obj.closed_at is None:
            rank = 1
        else:
            rank = 2
        if best is None or rank < best[0]:
            best = (rank, participant, session_obj, active)
    if best is None:
        return None
    _, participant, session_obj, active_round = best
    return {"participant": participant, "session": session_obj, "round": active_round}


def participant_view(db: DbSession, user: str) -> dict:
    """Everything the participant screen needs, in one poll."""
    state = current_participation(db, user)
    handling = settings_svc.data_handling_summary()
    if state is None:
        return {"state": "none", "data_handling": handling}

    participant: Participant = state["participant"]
    session_obj: Session = state["session"]
    round_obj: Round | None = state["round"]

    payload = {
        "state": "waiting",
        "data_handling": handling,
        "consent_required": participant.consent_at is None,
        "session": {
            "id": session_obj.id,
            "name": session_obj.name,
            "description": session_obj.description,
            "language": session_obj.language,
            "status": session_obj.status,
            "capture_enabled": session_obj.capture_enabled,
            "closed": session_obj.closed_at is not None,
            "report_published": session_obj.report_published_at is not None,
        },
        "participant": {
            "id": participant.id,
            "display_name": participant.display_name,
            "role": participant.role,
            "consent_at": participant.consent_at.isoformat() if participant.consent_at else None,
        },
        "round": None,
        "room": None,
        "recording": None,
    }

    if participant.consent_at is None:
        payload["state"] = "consent"
        return payload

    if round_obj is None:
        payload["state"] = "published" if session_obj.report_published_at else "waiting"
        return payload

    payload["round"] = delib.round_payload(round_obj)
    payload["round"]["remaining_seconds"] = delib.remaining_seconds(round_obj)

    member = db.execute(
        select(RoomMember).where(
            RoomMember.round_id == round_obj.id, RoomMember.participant_id == participant.id
        )
    ).scalar_one_or_none()
    if member is None:
        payload["state"] = "unassigned"
        return payload

    room: Room | None = db.get(Room, member.room_id)
    if room is None or not room.talk_token:
        payload["state"] = "waiting"
        return payload

    payload["room"] = {
        "id": room.id,
        "number": room.number,
        "label": room.label,
        "talk_token": room.talk_token,
        # Talk moves the participant into their breakout room automatically,
        # so the link points at the conversation and Talk does the rest.
        "talk_url": f"/index.php/call/{room.talk_token}",
        "members": [
            {
                "display_name": p.display_name,
                "nc_user_id": p.nc_user_id,
            }
            for p in _room_people(db, room)
        ],
    }
    payload["state"] = "in_round"

    recording = db.execute(
        select(Recording)
        .where(
            Recording.round_id == round_obj.id,
            Recording.participant_id == participant.id,
            Recording.state.in_(("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS")),
        )
        .order_by(Recording.created_at.desc())
    ).scalars().first()
    if recording is not None:
        payload["recording"] = {"id": recording.id, "state": recording.state}
    return payload


def _room_people(db: DbSession, room: Room) -> list[Participant]:
    ids = [m.participant_id for m in room.members]
    if not ids:
        return []
    return list(db.execute(select(Participant).where(Participant.id.in_(ids))).scalars())


def record_consent(db: DbSession, participant: Participant, accepted: bool) -> dict:
    """Store what this person was told, not merely that they clicked."""
    handling = settings_svc.data_handling_summary()
    if not accepted:
        participant.consent_at = None
        participant.consent_json = json.dumps({"accepted": False, "at": utcnow().isoformat()})
        participant.role = "observer"
        return {"accepted": False}
    participant.consent_at = utcnow()
    participant.consent_json = json.dumps(
        {"accepted": True, "at": participant.consent_at.isoformat(), "data_handling": handling}
    )
    if participant.role == "observer":
        participant.role = "participant"
    return {"accepted": True, "at": participant.consent_at.isoformat()}
