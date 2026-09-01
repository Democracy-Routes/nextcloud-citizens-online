# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting and ending a round.

This is where the deliberation design meets the meeting backend: the engine has
already decided who is in which room, and this module makes Talk execute it.

Every transition is persisted before the next one is attempted, so a restart
mid-round resumes rather than losing the round (spec §5, §39.15). The
authoritative clock is `Round.deadline_at` in the database — not a timer in
memory, and never the client's clock.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import Room, RoomMember, Round, Session
from citizens_online.db.models.base import utcnow
from citizens_online.infra.nextcloud.talk_adapter import (
    MAX_BREAKOUT_ROOMS_PER_PARENT,
    TalkAdapter,
    TalkError,
)
from citizens_online.logging_setup import get_logger
from citizens_online.services import bot_registry, deliberation as delib
from citizens_online.services.audit import record_audit_event
from citizens_online.services.jobs import enqueue_job

log = get_logger(__name__)


def _adapter(service_user: str, bot_id: int | None = None) -> TalkAdapter:
    return TalkAdapter(service_user=service_user, bot_id=bot_id)


def ensure_parent_conversation(db: DbSession, session_obj: Session, talk: TalkAdapter) -> str:
    """The session's Talk conversation, created on first use."""
    if session_obj.parent_token:
        return session_obj.parent_token
    room = talk.create_conversation(f"{session_obj.name}")
    session_obj.parent_token = room.token
    db.flush()
    try:
        talk.set_description(
            room.token,
            "Citizens Online deliberation. Breakout rooms open and close automatically.",
        )
    except TalkError:
        pass
    record_audit_event(
        db, "conversation_created", "session", session_obj.id, session_obj.created_by,
        {"token": room.token},
    )
    return room.token


def sync_participants(db: DbSession, session_obj: Session, talk: TalkAdapter) -> dict[str, int]:
    """Make sure every participant is in the parent conversation, and return
    `nc_user_id -> attendeeId` as Talk sees it there."""
    token = session_obj.parent_token
    present = {a.actor_id: a for a in talk.list_participants(token)}
    missing = [p.nc_user_id for p in session_obj.participants if p.nc_user_id not in present]
    if missing:
        talk.add_participants(token, missing)
        present = {a.actor_id: a for a in talk.list_participants(token)}
    return {uid: a.attendee_id for uid, a in present.items()}


def start_round(db: DbSession, round_obj: Round, actor: str, service_user: str,
                bot_id: int | None = None) -> dict:
    """Open the rooms and start the clock.

    Order matters and every step is idempotent, because this can be retried
    after a failure halfway through.
    """
    session_obj = round_obj.session
    if round_obj.status == "ACTIVE":
        return {"already_active": True, "round": delib.round_payload(round_obj)}
    if session_obj.closed_at:
        raise HTTPException(status_code=409, detail="This session is closed")

    other_active = db.execute(
        select(Round).where(
            Round.session_id == session_obj.id, Round.status == "ACTIVE", Round.id != round_obj.id
        )
    ).scalars().first()
    if other_active:
        raise HTTPException(
            status_code=409, detail=f"Round {other_active.position} is still running"
        )

    rooms = sorted(round_obj.rooms, key=lambda r: r.number)
    if not rooms or not any(r.members for r in rooms):
        delib.assign_randomly(db, round_obj)
        rooms = sorted(round_obj.rooms, key=lambda r: r.number)
    if len(rooms) > MAX_BREAKOUT_ROOMS_PER_PARENT:
        # PLAN.md §7: several parent conversations. Not needed below 20 rooms,
        # and refusing loudly beats half-creating an assembly.
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(rooms)} rooms exceed Talk's limit of {MAX_BREAKOUT_ROOMS_PER_PARENT} per "
                "conversation; multi-parent sessions are not implemented yet"
            ),
        )

    talk = _adapter(service_user, bot_id)
    ensure_parent_conversation(db, session_obj, talk)
    if session_obj.facilitator_enabled and not bot_id:
        # Talk only reveals a bot's id through a conversation we moderate
        bot_id = bot_registry.discover_bot_id(talk.nc, session_obj.parent_token)
        talk.bot_id = bot_id
    attendee_by_user = sync_participants(db, session_obj, talk)

    # attendeeId -> room index, in the room order we asked for
    attendee_map: dict[int, int] = {}
    people = {p.id: p for p in session_obj.participants}
    for index, room in enumerate(rooms):
        for member in room.members:
            person = people.get(member.participant_id)
            if not person:
                continue
            attendee_id = attendee_by_user.get(person.nc_user_id)
            if attendee_id:
                attendee_map[attendee_id] = index
                member.attendee_id = attendee_id
    if not attendee_map:
        raise HTTPException(
            status_code=400, detail="No participants could be matched to Talk attendees"
        )

    created = talk.create_breakout_rooms(session_obj.parent_token, len(rooms), attendee_map)
    for room, meeting_room in zip(rooms, created, strict=False):
        room.talk_token = meeting_room.token
        room.parent_token = session_obj.parent_token
        room.status = "OPEN"
    db.flush()

    talk.start_breakout_rooms(session_obj.parent_token)

    # Talk does not inherit bots into breakout rooms — enable per room.
    if session_obj.facilitator_enabled and bot_id:
        for room in rooms:
            if room.talk_token:
                room.bot_enabled = talk.enable_bot(room.talk_token)
    db.flush()

    now = utcnow()
    round_obj.status = "ACTIVE"
    round_obj.started_at = now
    round_obj.deadline_at = now + timedelta(minutes=round_obj.duration_minutes)
    if session_obj.status in ("DRAFT", "READY"):
        session_obj.status = "ACTIVE"
    record_audit_event(
        db, "round_started", "round", round_obj.id, actor,
        {"rooms": len(rooms), "participants": len(attendee_map),
         "deadline_at": round_obj.deadline_at.isoformat()},
    )
    log.info("round_started", round_id=round_obj.id, rooms=len(rooms))
    return {
        "round": delib.round_payload(round_obj),
        "rooms": [{"number": r.number, "talk_token": r.talk_token} for r in rooms],
        "parent_token": session_obj.parent_token,
    }


def end_round(db: DbSession, round_obj: Round, actor: str, service_user: str,
              reason: str = "manual") -> dict:
    """Close the rooms, stop capture, queue the analysis."""
    if round_obj.status not in ("ACTIVE",):
        return {"round": delib.round_payload(round_obj), "already_ended": True}
    session_obj = round_obj.session
    talk = _adapter(service_user)

    # Stop breakouts first: participants return to the parent conversation and
    # stop talking, which is what makes the captures final.
    if session_obj.parent_token:
        try:
            talk.stop_breakout_rooms(session_obj.parent_token)
        except TalkError as exc:
            # A Talk outage must not strand the round in ACTIVE forever.
            log.warning("stop_breakouts_failed", round_id=round_obj.id, error=str(exc)[:200])

    now = utcnow()
    round_obj.status = "PROCESSING"
    round_obj.ended_at = now
    round_obj.deadline_at = None
    for room in round_obj.rooms:
        room.status = "CLOSED"
    enqueue_job(db, "FINALIZE_ROUND", {"round_id": round_obj.id})
    record_audit_event(db, "round_ended", "round", round_obj.id, actor, {"reason": reason})
    log.info("round_ended", round_id=round_obj.id, reason=reason)
    return {"round": delib.round_payload(round_obj)}


def remix(db: DbSession, round_obj: Round, actor: str, service_user: str) -> dict:
    """Apply the current assignment to a running round (spec §21).

    Used when an organizer moves people while the round is live; the full
    embedding-based remix arrives in 0.2.
    """
    session_obj = round_obj.session
    if round_obj.status != "ACTIVE" or not session_obj.parent_token:
        raise HTTPException(status_code=409, detail="Round is not running")
    talk = _adapter(service_user)
    rooms = sorted(round_obj.rooms, key=lambda r: r.number)
    attendee_map = {}
    for index, room in enumerate(rooms):
        for member in room.members:
            if member.attendee_id:
                attendee_map[member.attendee_id] = index
    if attendee_map:
        talk.reorganize_breakout_rooms(session_obj.parent_token, attendee_map)
    record_audit_event(db, "round_remixed", "round", round_obj.id, actor, {"moved": len(attendee_map)})
    return {"moved": len(attendee_map)}


def room_for_participant(db: DbSession, round_obj: Round, participant_id: str) -> Room | None:
    member = db.execute(
        select(RoomMember).where(
            RoomMember.round_id == round_obj.id, RoomMember.participant_id == participant_id
        )
    ).scalar_one_or_none()
    return db.get(Room, member.room_id) if member else None
