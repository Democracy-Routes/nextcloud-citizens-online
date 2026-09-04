# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: sessions, rounds, participants."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from citizens_online.core.engine import rounds as engine_rounds
from citizens_online.db.session import get_db
from citizens_online.domain.constants import Language, PolicyPreset, SpeakingPolicy
from citizens_online.security.identity import CurrentNc, CurrentUser
from citizens_online.services import deliberation as delib
from citizens_online.services import directory as directory_svc
from citizens_online.services import settings as settings_svc
from citizens_online.services.audit import record_audit_event
from citizens_online.services.jobs import enqueue_job

log = structlog.get_logger(__name__)

router = APIRouter(tags=["sessions"])
DB = Annotated[DbSession, Depends(get_db)]


class RoundIn(BaseModel):
    title: str = Field(default="", max_length=200)
    question: str = Field(default="", max_length=4000)
    duration_minutes: int = Field(default=20, ge=1, le=480)


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    language: Language = "en"
    rooms_per_round: int = Field(default=2, ge=1, le=20)
    analysis_instructions: str = Field(default="", max_length=4000)
    facilitator_enabled: bool = True
    moderation_enabled: bool = True
    capture_enabled: bool = True
    policy_preset: PolicyPreset = "gentle"
    audio_retention_days: int = Field(default=0, ge=0, le=3650)
    rounds: list[RoundIn] = Field(default_factory=list)


class SessionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    language: Language | None = None
    rooms_per_round: int | None = Field(default=None, ge=1, le=20)
    analysis_instructions: str | None = Field(default=None, max_length=4000)
    facilitator_enabled: bool | None = None
    moderation_enabled: bool | None = None
    capture_enabled: bool | None = None
    policy_preset: PolicyPreset | None = None
    speaking_policy: SpeakingPolicy | None = None
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)


class ParticipantIn(BaseModel):
    nc_user_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=120)
    role: str = Field(default="participant", max_length=16)


class ParticipantsIn(BaseModel):
    participants: list[ParticipantIn]


class GroupIn(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)


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
    was_named = obj.name
    delib.update_session(db, obj, payload.model_dump(exclude_none=True), user)
    if obj.name != was_named and obj.parent_token:
        # Otherwise the Talk conversation keeps the name it was created with for
        # ever, and participants see a room that no longer matches the session.
        from citizens_online.infra.nextcloud.talk_adapter import TalkAdapter, TalkError

        try:
            snap = settings_svc.snapshot()
            TalkAdapter(service_user=snap["talk_service_user"]).rename_conversation(
                obj.parent_token, obj.name
            )
        except TalkError as exc:
            # The rename is cosmetic; refusing the whole edit over it would be worse.
            log.warning("talk_rename_failed", session_id=obj.id, error=str(exc)[:200])
    return delib.session_payload(db, obj, detail=True)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: DB, user: CurrentUser):
    obj = delib.get_owned_session(db, session_id, user)
    token = obj.parent_token
    record_audit_event(db, "session_deleted", "session", obj.id, user, {"name": obj.name})
    db.delete(obj)
    if token:
        # Deleting the session used to leave its Talk conversation and every
        # breakout room behind for ever: a headless room named after an assembly
        # whose transcripts, findings and report have all just been cascaded
        # away. Breakout rooms go first — they are children of the parent, and
        # removing the parent alone can strand them.
        from citizens_online.infra.nextcloud.talk_adapter import TalkAdapter, TalkError

        talk = TalkAdapter(service_user=settings_svc.snapshot()["talk_service_user"])
        for step, action in (("breakouts", talk.remove_breakout_rooms), ("room", talk.delete_conversation)):
            try:
                action(token)
            except TalkError as exc:
                # The database row is already gone; a Talk failure must not turn
                # a successful delete into a 500.
                log.warning("talk_cleanup_failed", step=step, token=token, error=str(exc)[:200])


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
def add_participants(
    session_id: str, payload: ParticipantsIn, db: DB, user: CurrentUser, nc: CurrentNc
):
    """Add people, after checking each one is a real account.

    Partial success on purpose: one mistyped name in a pasted list of fifty
    should not reject the other forty-nine. The display name always comes from
    Nextcloud, never from the client.
    """
    obj = delib.get_owned_session(db, session_id, user)
    requested = [p.nc_user_id for p in payload.participants]
    roles = {p.nc_user_id: p.role for p in payload.participants}
    found, unknown = directory_svc.resolve_users(nc, requested)
    created = delib.add_participants(
        db,
        obj,
        [
            {"nc_user_id": uid, "display_name": name, "role": roles.get(uid, "participant")}
            for uid, name in found.items()
        ],
        user,
    )
    return {
        "added": [delib.participant_payload(p) for p in created],
        "unknown": unknown,
    }


@router.post("/sessions/{session_id}/participants/from-group", status_code=201)
def add_participants_from_group(
    session_id: str, payload: GroupIn, db: DB, user: CurrentUser, nc: CurrentNc
):
    """Import a Nextcloud group's members as a one-time snapshot."""
    obj = delib.get_owned_session(db, session_id, user)
    members = directory_svc.group_members(nc, payload.group_id)
    created = delib.add_participants(
        db,
        obj,
        [
            {"nc_user_id": uid, "display_name": name, "added_via_group": payload.group_id}
            for uid, name in members
        ],
        user,
    )
    return {
        "added": [delib.participant_payload(p) for p in created],
        "group_id": payload.group_id,
        "members": len(members),
    }


@router.post("/sessions/{session_id}/participants/resync-group")
def resync_group(session_id: str, payload: GroupIn, db: DB, user: CurrentUser, nc: CurrentNc):
    """Pick up people who joined the group since it was imported.

    Never removes anybody: someone who has left the group may already have
    consented, spoken and been recorded in this session, and that is the
    organizer's call to undo, not ours.
    """
    obj = delib.get_owned_session(db, session_id, user)
    members = directory_svc.group_members(nc, payload.group_id)
    member_ids = {uid for uid, _ in members}
    created = delib.add_participants(
        db,
        obj,
        [
            {"nc_user_id": uid, "display_name": name, "added_via_group": payload.group_id}
            for uid, name in members
        ],
        user,
    )
    departed = [
        delib.participant_payload(p)
        for p in obj.participants
        if p.added_via_group == payload.group_id and p.nc_user_id not in member_ids
    ]
    return {
        "added": [delib.participant_payload(p) for p in created],
        "departed": departed,
        "group_id": payload.group_id,
        "members": len(members),
    }


class InviteIn(BaseModel):
    # Re-inviting reaches people who were told once and never responded; without
    # it, pressing the button twice notifies nobody a second time.
    force: bool = False


@router.post("/sessions/{session_id}/participants/invite")
def invite_participants(session_id: str, db: DB, user: CurrentUser, payload: InviteIn | None = None):
    """Tell participants the assembly exists.

    Queued rather than sent inline: each recipient costs about two round-trips
    to Nextcloud, so a fifty-person guest list would hold the browser for the
    better part of a minute.
    """
    obj = delib.get_owned_session(db, session_id, user)
    force = bool(payload and payload.force)
    pending = [p for p in obj.participants if force or p.invited_at is None]
    if not pending:
        return {"queued": 0, "reason": "everyone has already been invited"}
    enqueue_job(db, "INVITE_PARTICIPANTS", {"session_id": obj.id, "force": force})
    record_audit_event(
        db, "participants_invited", "session", obj.id, user, {"count": len(pending)}
    )
    return {"queued": len(pending)}


@router.delete("/participants/{participant_id}", status_code=204)
def delete_participant(participant_id: str, db: DB, user: CurrentUser):
    from citizens_online.db.models import Participant

    obj = db.get(Participant, participant_id)
    if obj is not None:
        delib.get_owned_session(db, obj.session_id, user)
        db.delete(obj)
