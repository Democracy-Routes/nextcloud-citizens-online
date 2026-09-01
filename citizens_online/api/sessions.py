# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: sessions, rounds, participants."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from citizens_online.core.engine import rounds as engine_rounds
from citizens_online.db.session import get_db
from citizens_online.security.identity import CurrentUser
from citizens_online.services import deliberation as delib
from citizens_online.services import settings as settings_svc
from citizens_online.services.audit import record_audit_event

router = APIRouter(tags=["sessions"])
DB = Annotated[DbSession, Depends(get_db)]


class RoundIn(BaseModel):
    title: str = Field(default="", max_length=200)
    question: str = Field(default="", max_length=4000)
    duration_minutes: int = Field(default=20, ge=1, le=480)


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    language: str = Field(default="en", max_length=10)
    rooms_per_round: int = Field(default=2, ge=1, le=20)
    analysis_instructions: str = Field(default="", max_length=4000)
    facilitator_enabled: bool = True
    moderation_enabled: bool = True
    capture_enabled: bool = True
    policy_preset: str = Field(default="gentle", max_length=12)
    audio_retention_days: int = Field(default=0, ge=0, le=3650)
    rounds: list[RoundIn] = Field(default_factory=list)


class SessionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    language: str | None = Field(default=None, max_length=10)
    rooms_per_round: int | None = Field(default=None, ge=1, le=20)
    analysis_instructions: str | None = Field(default=None, max_length=4000)
    facilitator_enabled: bool | None = None
    moderation_enabled: bool | None = None
    capture_enabled: bool | None = None
    policy_preset: str | None = Field(default=None, max_length=12)
    speaking_policy: str | None = Field(default=None, max_length=24)
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)


class ParticipantIn(BaseModel):
    nc_user_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=120)
    role: str = Field(default="participant", max_length=16)


class ParticipantsIn(BaseModel):
    participants: list[ParticipantIn]


# ---------------------------------------------------------------- sessions

@router.get("/sessions")
def list_sessions(db: DB, user: CurrentUser):
    return [delib.session_payload(db, s) for s in delib.list_sessions(db, user)]


@router.post("/sessions", status_code=201)
def create_session(payload: SessionCreate, db: DB, user: CurrentUser):
    obj = delib.create_session(db, user, payload.model_dump())
    return delib.session_payload(db, obj, detail=True)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    return delib.session_payload(db, obj, detail=True)


@router.put("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdate, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    delib.update_session(db, obj, payload.model_dump(exclude_none=True), user)
    return delib.session_payload(db, obj, detail=True)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    record_audit_event(db, "session_deleted", "session", obj.id, user, {"name": obj.name})
    db.delete(obj)


# ------------------------------------------------------------------ rounds

@router.post("/sessions/{session_id}/rounds", status_code=201)
def add_round(session_id: str, payload: RoundIn, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    return delib.round_payload(delib.add_round(db, obj, payload.model_dump()))


@router.put("/rounds/{round_id}")
def update_round(round_id: str, payload: dict, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    return delib.round_payload(delib.update_round(db, obj, payload))


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(round_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    db.delete(obj)


@router.post("/rounds/{round_id}/start")
def start_round(round_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    snap = settings_svc.snapshot()
    from citizens_online.services.bot_registry import cached_bot_id

    return engine_rounds.start_round(
        db, obj, actor=user, service_user=snap["talk_service_user"], bot_id=cached_bot_id()
    )


@router.post("/rounds/{round_id}/end")
def end_round(round_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    snap = settings_svc.snapshot()
    return engine_rounds.end_round(db, obj, actor=user, service_user=snap["talk_service_user"])


@router.post("/rounds/{round_id}/extend")
def extend_round(round_id: str, payload: dict, db: DB, user: CurrentUser):
    """Push the deadline out by N minutes without restarting the round."""
    from datetime import timedelta

    obj = delib.get_owned_round(db, round_id, user)
    minutes = max(1, min(int(payload.get("minutes", 5)), 240))
    if obj.deadline_at:
        obj.deadline_at = obj.deadline_at + timedelta(minutes=minutes)
        obj.duration_minutes += minutes
    record_audit_event(db, "round_extended", "round", obj.id, user, {"minutes": minutes})
    return delib.round_payload(obj)


@router.post("/rounds/{round_id}/remix")
def remix_round(round_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_round(db, round_id, user)
    snap = settings_svc.snapshot()
    return engine_rounds.remix(db, obj, actor=user, service_user=snap["talk_service_user"])


# ------------------------------------------------------------ participants

@router.get("/sessions/{session_id}/participants")
def list_participants(session_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    return [delib.participant_payload(p) for p in obj.participants]


@router.post("/sessions/{session_id}/participants", status_code=201)
def add_participants(session_id: str, payload: ParticipantsIn, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    created = delib.add_participants(
        db, obj, [p.model_dump() for p in payload.participants], user
    )
    return [delib.participant_payload(p) for p in created]


@router.delete("/participants/{participant_id}", status_code=204)
def delete_participant(participant_id: str, db: DB, user: CurrentUser):
    from citizens_online.db.models import Participant

    obj = db.get(Participant, participant_id)
    if obj is not None:
        delib.get_owned_session(db, obj.session_id, user)
        db.delete(obj)
