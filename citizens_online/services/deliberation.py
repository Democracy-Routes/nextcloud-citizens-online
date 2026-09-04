# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sessions, rounds, participants and room assignment.

Pure database work: nothing here talks to Talk. Executing an assignment against
real breakout rooms is the engine's job (`core/engine/rounds.py`), which keeps
this module testable without a server.
"""

import random
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import (
    Participant,
    Room,
    RoomMember,
    Round,
    Session,
    SpeakingMetric,
)
from citizens_online.db.models.base import utcnow
from citizens_online.logging_setup import get_logger
from citizens_online.services.audit import record_audit_event

log = get_logger(__name__)


# --------------------------------------------------------------- ownership

def get_owned_session(db: DbSession, session_id: str, user: str) -> Session:
    """404, never 403: an organizer must not be able to discover that another
    organizer's session exists by probing ids."""
    obj = db.get(Session, session_id)
    if obj is None or obj.created_by != user:
        raise HTTPException(status_code=404, detail="Session not found")
    return obj


def get_owned_round(db: DbSession, round_id: str, user: str) -> Round:
    obj = db.get(Round, round_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Round not found")
    get_owned_session(db, obj.session_id, user)
    return obj


def participant_for(db: DbSession, session_id: str, nc_user_id: str) -> Participant | None:
    return db.execute(
        select(Participant).where(
            Participant.session_id == session_id, Participant.nc_user_id == nc_user_id
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------- sessions

def create_session(db: DbSession, user: str, data: dict) -> Session:
    obj = Session(
        name=data["name"][:200],
        description=data.get("description", "")[:5000],
        language=data.get("language", "en")[:10],
        created_by=user,
        rooms_per_round=max(1, min(int(data.get("rooms_per_round", 2)), 20)),
        analysis_instructions=data.get("analysis_instructions", "")[:4000],
        facilitator_enabled=bool(data.get("facilitator_enabled", True)),
        moderation_enabled=bool(data.get("moderation_enabled", True)),
        capture_enabled=bool(data.get("capture_enabled", True)),
        policy_preset=data.get("policy_preset", "gentle")[:12],
        audio_retention_days=int(data.get("audio_retention_days", 0)),
    )
    db.add(obj)
    db.flush()
    for index, r in enumerate(data.get("rounds") or []):
        add_round(db, obj, r, position=index + 1)
    db.expire(obj, ["rounds"])
    record_audit_event(db, "session_created", "session", obj.id, user, {"name": obj.name})
    return obj


def list_sessions(db: DbSession, user: str) -> list[Session]:
    return list(
        db.execute(
            select(Session).where(Session.created_by == user).order_by(Session.created_at.desc())
        ).scalars()
    )


def update_session(db: DbSession, obj: Session, data: dict, user: str) -> Session:
    """Edit a session. Refused outright while a round is running.

    Almost every field here is read live by something: the tick re-reads the
    facilitation policy on every pass, transcription picks its speech model from
    `language`, and `rooms_per_round` decides how many rooms the next
    distribution builds. Changing any of that underneath a running round leaves
    a session whose record disagrees with what actually happened, so the whole
    form closes for the duration rather than field by field.
    """
    active = next((r for r in obj.rounds if r.status == "ACTIVE"), None)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Round {active.position} is running. End it before changing the session — "
                "these settings shape how the round is transcribed and facilitated."
            ),
        )

    changed: list[str] = []

    def _set(field: str, value) -> None:
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)

    for field in (
        "name",
        "description",
        "language",
        "analysis_instructions",
        "policy_preset",
        "speaking_policy",
    ):
        if data.get(field) is not None:
            _set(field, str(data[field]))
    for field in ("facilitator_enabled", "moderation_enabled", "capture_enabled"):
        if data.get(field) is not None:
            _set(field, bool(data[field]))
    if data.get("rooms_per_round"):
        _set("rooms_per_round", max(1, min(int(data["rooms_per_round"]), 20)))
    if data.get("audio_retention_days") is not None:
        _set("audio_retention_days", int(data["audio_retention_days"]))

    # Record *what* moved, not merely that something did: the previous version
    # logged an empty payload, which left the audit trail unable to answer the
    # only question anyone asks of it.
    record_audit_event(db, "session_updated", "session", obj.id, user, {"changed": changed})
    return obj


def session_payload(db: DbSession, obj: Session, detail: bool = False) -> dict:
    data = {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "language": obj.language,
        "status": obj.status,
        "rooms_per_round": obj.rooms_per_round,
        "speaking_policy": obj.speaking_policy,
        "parent_token": obj.parent_token,
        "facilitator_enabled": obj.facilitator_enabled,
        "moderation_enabled": obj.moderation_enabled,
        "capture_enabled": obj.capture_enabled,
        "policy_preset": obj.policy_preset,
        "analysis_instructions": obj.analysis_instructions,
        "audio_retention_days": obj.audio_retention_days,
        "closed_at": obj.closed_at.isoformat() if obj.closed_at else None,
        "report_published_at": obj.report_published_at.isoformat()
        if obj.report_published_at
        else None,
        "created_at": obj.created_at.isoformat(),
        "participant_count": len(obj.participants),
        "round_count": len(obj.rounds),
    }
    if detail:
        data["rounds"] = [round_payload(r) for r in obj.rounds]
        data["participants"] = [participant_payload(p) for p in obj.participants]
    return data


# ------------------------------------------------------------------ rounds

def add_round(db: DbSession, session_obj: Session, data: dict, position: int | None = None) -> Round:
    if position is None:
        position = (max((r.position for r in session_obj.rounds), default=0)) + 1
    obj = Round(
        session_id=session_obj.id,
        position=position,
        title=(data.get("title") or f"Round {position}")[:200],
        question=(data.get("question") or "")[:4000],
        duration_minutes=max(1, min(int(data.get("duration_minutes", 20)), 480)),
    )
    db.add(obj)
    db.flush()
    return obj


def update_round(db: DbSession, obj: Round, data: dict) -> Round:
    if obj.status == "ACTIVE" and "duration_minutes" in data and data["duration_minutes"]:
        # extending a live round moves the deadline rather than resetting it
        obj.duration_minutes = max(1, min(int(data["duration_minutes"]), 480))
        if obj.started_at:
            from datetime import timedelta

            obj.deadline_at = obj.started_at + timedelta(minutes=obj.duration_minutes)
    else:
        for field in ("title", "question"):
            if data.get(field) is not None:
                setattr(obj, field, str(data[field]))
        if data.get("duration_minutes"):
            obj.duration_minutes = max(1, min(int(data["duration_minutes"]), 480))
    if data.get("position"):
        obj.position = int(data["position"])
    return obj


def round_payload(obj: Round) -> dict:
    return {
        "id": obj.id,
        "session_id": obj.session_id,
        "position": obj.position,
        "title": obj.title,
        "question": obj.question,
        "duration_minutes": obj.duration_minutes,
        "status": obj.status,
        "started_at": obj.started_at.isoformat() if obj.started_at else None,
        "ended_at": obj.ended_at.isoformat() if obj.ended_at else None,
        "deadline_at": obj.deadline_at.isoformat() if obj.deadline_at else None,
        "summary": obj.analysis_summary,
        "room_count": len(obj.rooms),
    }


def remaining_seconds(obj: Round, now: datetime | None = None) -> int | None:
    if obj.status != "ACTIVE" or not obj.deadline_at:
        return None
    return max(0, int((obj.deadline_at - (now or utcnow())).total_seconds()))


# ------------------------------------------------------------ participants

def add_participants(
    db: DbSession, session_obj: Session, entries: list[dict], user: str
) -> list[Participant]:
    """Add people who have already been checked against Nextcloud.

    Callers must resolve ids through `services.directory` first: a name that is
    not a real account looks perfectly fine in this table and then silently fails
    to appear in Talk when the round starts.
    """
    existing = {p.nc_user_id for p in session_obj.participants}
    created = []
    for entry in entries:
        uid = (entry.get("nc_user_id") or "").strip()
        if not uid or uid in existing:
            continue
        obj = Participant(
            session_id=session_obj.id,
            nc_user_id=uid[:64],
            display_name=(entry.get("display_name") or uid)[:120],
            role=entry.get("role", "participant"),
            added_via_group=(entry.get("added_via_group") or "")[:64],
        )
        db.add(obj)
        existing.add(uid)
        created.append(obj)
    db.flush()
    if created:
        # rows were created with a foreign key rather than appended to the
        # collection, so the already-loaded relationship must be refreshed —
        # otherwise the caller sees a session with no participants
        db.expire(session_obj, ["participants"])
        record_audit_event(
            db, "participants_added", "session", session_obj.id, user, {"count": len(created)}
        )
    return created


def participant_payload(obj: Participant) -> dict:
    return {
        "id": obj.id,
        "nc_user_id": obj.nc_user_id,
        "display_name": obj.display_name,
        "role": obj.role,
        "added_via_group": obj.added_via_group,
        "consented": obj.consent_at is not None,
        "consent_at": obj.consent_at.isoformat() if obj.consent_at else None,
    }


# ------------------------------------------------------------- assignment

def ensure_rooms(db: DbSession, round_obj: Round, count: int) -> list[Room]:
    """Rooms are planned rows until the engine gives them Talk tokens.

    Grows *and* shrinks: the room count changes whenever the organizer edits it,
    and a surplus room left behind is not harmless — it is still created in Talk
    and still counts against Talk's limit of 20 per conversation. A room that
    already exists in Talk is never deleted here; dismantling a live round is the
    engine's job, not the planner's.
    """
    rooms = list(round_obj.rooms)
    surplus = [r for r in rooms if r.number > count]
    live = [r for r in surplus if r.talk_token]
    if live:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Room {live[0].number} is already open in Talk; end the round before "
                "reducing the number of rooms"
            ),
        )
    if surplus:
        for room in surplus:
            db.delete(room)  # room_members cascades
        rooms = [r for r in rooms if r.number <= count]
        db.flush()
        db.expire(round_obj, ["rooms"])
    created = False
    for number in range(len(rooms) + 1, count + 1):
        room = Room(
            round_id=round_obj.id,
            session_id=round_obj.session_id,
            number=number,
            label=f"Room {number}",
        )
        db.add(room)
        rooms.append(room)
        created = True
    db.flush()
    if created:
        # the relationship was loaded before these rows existed; without this
        # the caller sees an empty room list and divides by zero
        db.expire(round_obj, ["rooms"])
    return sorted(rooms, key=lambda r: r.number)


def assign_randomly(db: DbSession, round_obj: Round, room_count: int | None = None) -> list[Room]:
    """Even, shuffled distribution. Deliberately deterministic in shape (sizes
    differ by at most one) and random in membership."""
    session_obj = round_obj.session
    count = room_count or session_obj.rooms_per_round
    rooms = ensure_rooms(db, round_obj, max(1, count))
    people = [p for p in session_obj.participants if p.role != "observer"]
    if not rooms:
        raise HTTPException(status_code=500, detail="No rooms could be created")
    random.shuffle(people)
    known = _replace_members(db, round_obj)
    for index, person in enumerate(people):
        room = rooms[index % len(rooms)]
        db.add(
            RoomMember(
                round_id=round_obj.id,
                room_id=room.id,
                participant_id=person.id,
                attendee_id=known.get(person.id),
            )
        )
    db.flush()
    log.info("rooms_assigned", round_id=round_obj.id, rooms=len(rooms), participants=len(people))
    return rooms


def copy_previous_assignment(db: DbSession, round_obj: Round) -> list[Room]:
    previous = db.execute(
        select(Round)
        .where(Round.session_id == round_obj.session_id, Round.position < round_obj.position)
        .order_by(Round.position.desc())
    ).scalars().first()
    if previous is None:
        return assign_randomly(db, round_obj)
    rooms = ensure_rooms(db, round_obj, max(1, len(previous.rooms)))
    by_number = {r.number: r for r in rooms}
    known = _replace_members(db, round_obj)
    for old_room in previous.rooms:
        target = by_number.get(old_room.number)
        if target is None:
            continue
        for member in old_room.members:
            db.add(
                RoomMember(
                    round_id=round_obj.id,
                    room_id=target.id,
                    participant_id=member.participant_id,
                    # the same person in the same parent conversation, so the
                    # previous round already knows their attendee id
                    attendee_id=member.attendee_id or known.get(member.participant_id),
                )
            )
    db.flush()
    return rooms


def move_participant(db: DbSession, round_obj: Round, participant_id: str, to_room_id: str) -> None:
    member = db.execute(
        select(RoomMember).where(
            RoomMember.round_id == round_obj.id, RoomMember.participant_id == participant_id
        )
    ).scalar_one_or_none()
    room = db.get(Room, to_room_id)
    if room is None or room.round_id != round_obj.id:
        raise HTTPException(status_code=404, detail="Room not found")
    if member is None:
        db.add(RoomMember(round_id=round_obj.id, room_id=to_room_id, participant_id=participant_id))
    else:
        # attendee_id is the person's id in the parent conversation, not in a
        # breakout room, so moving between rooms does not invalidate it. Clearing
        # it here used to exclude exactly the person just moved from the remix.
        member.room_id = to_room_id
    db.flush()


def _replace_members(db: DbSession, round_obj: Round) -> dict[str, int]:
    """Assignment is replaced wholesale, never merged: a half-applied plan is
    worse than a new one.

    Returns the attendee ids it is about to discard, keyed by participant, so the
    caller can carry them onto the new rows. `RoomMember.attendee_id` identifies
    the person in the *parent* conversation — Talk resolves a breakout attendee
    map against the parent's participants — so it survives any reshuffle and must
    not be thrown away with the old plan. Losing it silently disables remix.
    """
    known: dict[str, int] = {}
    for member in db.execute(
        select(RoomMember).where(RoomMember.round_id == round_obj.id)
    ).scalars():
        if member.attendee_id:
            known[member.participant_id] = member.attendee_id
        db.delete(member)
    db.flush()
    return known


def rooms_payload(db: DbSession, round_obj: Round) -> list[dict]:
    people = {p.id: p for p in round_obj.session.participants}
    metrics = {
        m.participant_id: m
        for m in db.execute(
            select(SpeakingMetric).where(SpeakingMetric.round_id == round_obj.id)
        ).scalars()
    }
    out = []
    for room in sorted(round_obj.rooms, key=lambda r: r.number):
        room_total = sum(
            metrics[m.participant_id].speaking_ms
            for m in room.members
            if m.participant_id in metrics
        )
        members = []
        for member in room.members:
            person = people.get(member.participant_id)
            metric = metrics.get(member.participant_id)
            members.append(
                {
                    "participant_id": member.participant_id,
                    "nc_user_id": person.nc_user_id if person else "",
                    "display_name": person.display_name if person else "",
                    "attendee_id": member.attendee_id,
                    "speaking_ms": metric.speaking_ms if metric else 0,
                    "share": round(metric.speaking_ms / room_total, 3)
                    if metric and room_total
                    else 0.0,
                    "turn_count": metric.turn_count if metric else 0,
                    "last_spoke_at": metric.last_spoke_at.isoformat()
                    if metric and metric.last_spoke_at
                    else None,
                }
            )
        members.sort(key=lambda m: -m["speaking_ms"])
        out.append(
            {
                "id": room.id,
                "number": room.number,
                "label": room.label,
                "talk_token": room.talk_token,
                "bot_enabled": room.bot_enabled,
                "status": room.status,
                "summary": room.analysis_summary,
                "speaking_ms": room_total,
                "members": members,
            }
        )
    return out
