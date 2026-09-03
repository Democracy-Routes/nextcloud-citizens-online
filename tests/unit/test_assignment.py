# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Room assignment — the planning layer, which never talks to Talk.

These are the first tests this subsystem has had, and they exist because three
of the bugs they cover failed *silently*: the organizer saw a success toast and
a wrong result. In particular `RoomMember.attendee_id` identifies a person in
the *parent* Talk conversation, so it survives any reshuffle; discarding it made
`remix` skip exactly the people who had just been moved.
"""

import pytest
from fastapi import HTTPException

from citizens_online.db.models import Participant, Room, RoomMember, Round
from citizens_online.services import deliberation as delib


def _sizes(round_obj):
    return sorted(len(room.members) for room in round_obj.rooms)


def test_even_split_sizes_differ_by_at_most_one(db, make_session):
    with db() as s:
        _, (round_id,) = make_session(s, rooms=3, people=7)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj)
        assert _sizes(round_obj) == [2, 2, 3]


def test_everyone_is_placed_exactly_once(db, make_session):
    with db() as s:
        _, (round_id,) = make_session(s, rooms=3, people=10)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj)
        placed = [m.participant_id for room in round_obj.rooms for m in room.members]
        assert len(placed) == 10
        assert len(set(placed)) == 10


def test_observers_are_not_placed(db, make_session):
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=2, people=4)
        s.add(
            Participant(
                session_id=session_id, nc_user_id="watcher", display_name="W", role="observer"
            )
        )
        s.flush()
        round_obj = s.get(Round, round_id)
        s.expire(round_obj.session, ["participants"])
        delib.assign_randomly(s, round_obj)
        placed = {m.participant_id for room in round_obj.rooms for m in room.members}
        watcher = next(p for p in round_obj.session.participants if p.role == "observer")
        assert watcher.id not in placed
        assert len(placed) == 4


# ----------------------------------------------------------------- ensure_rooms


def test_ensure_rooms_grows_and_numbers_contiguously(db, make_session):
    with db() as s:
        _, (round_id,) = make_session(s)
        round_obj = s.get(Round, round_id)
        rooms = delib.ensure_rooms(s, round_obj, 4)
        assert [r.number for r in rooms] == [1, 2, 3, 4]


def test_ensure_rooms_shrinks_planned_rooms(db, make_session):
    """The old implementation only ever grew, so a surplus room survived, was
    created in Talk, and counted against Talk's limit of 20."""
    with db() as s:
        _, (round_id,) = make_session(s)
        round_obj = s.get(Round, round_id)
        delib.ensure_rooms(s, round_obj, 5)
        rooms = delib.ensure_rooms(s, round_obj, 3)
        assert [r.number for r in rooms] == [1, 2, 3]
        assert s.query(Room).filter(Room.round_id == round_id).count() == 3


def test_ensure_rooms_refuses_to_delete_a_room_open_in_talk(db, make_session):
    with db() as s:
        _, (round_id,) = make_session(s)
        round_obj = s.get(Round, round_id)
        delib.ensure_rooms(s, round_obj, 3)
        live = next(r for r in round_obj.rooms if r.number == 3)
        live.talk_token = "tok3"
        s.flush()
        with pytest.raises(HTTPException) as excinfo:
            delib.ensure_rooms(s, round_obj, 2)
        assert excinfo.value.status_code == 409
        assert s.query(Room).filter(Room.round_id == round_id).count() == 3


def test_shrinking_removes_the_memberships_too(db, make_session):
    with db() as s:
        _, (round_id,) = make_session(s, rooms=4, people=8)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj, 4)
        delib.assign_randomly(s, round_obj, 2)
        assert s.query(RoomMember).filter(RoomMember.round_id == round_id).count() == 8
        assert {r.number for r in round_obj.rooms} == {1, 2}


# ------------------------------------------------- the attendee-id regressions


def _seed_attendee_ids(s, round_obj, start=100):
    members = s.query(RoomMember).filter(RoomMember.round_id == round_obj.id).all()
    for offset, member in enumerate(members):
        member.attendee_id = start + offset
    s.flush()
    return {m.participant_id: m.attendee_id for m in members}


def test_attendee_id_survives_a_move(db, make_session):
    """Moving between breakout rooms does not change who you are in the parent
    conversation, so the id must not be cleared — clearing it excluded exactly
    the person just moved from the next remix."""
    with db() as s:
        _, (round_id,) = make_session(s, rooms=2, people=4)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj)
        before = _seed_attendee_ids(s, round_obj)

        member = s.query(RoomMember).filter(RoomMember.round_id == round_id).first()
        target = next(r for r in round_obj.rooms if r.id != member.room_id)
        delib.move_participant(s, round_obj, member.participant_id, target.id)

        moved = (
            s.query(RoomMember)
            .filter(
                RoomMember.round_id == round_id,
                RoomMember.participant_id == member.participant_id,
            )
            .one()
        )
        assert moved.room_id == target.id
        assert moved.attendee_id == before[member.participant_id]


def test_attendee_ids_survive_a_re_randomize(db, make_session):
    """Re-randomizing a live round used to wipe every id, after which remix
    found an empty map and reported '0 moved' with no error."""
    with db() as s:
        _, (round_id,) = make_session(s, rooms=2, people=6)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj)
        before = _seed_attendee_ids(s, round_obj)

        delib.assign_randomly(s, round_obj)

        after = {
            m.participant_id: m.attendee_id
            for m in s.query(RoomMember).filter(RoomMember.round_id == round_id)
        }
        assert after == before


def test_attendee_ids_survive_copy_previous(db, make_session):
    with db() as s:
        _, (first_id, second_id) = make_session(s, rooms=2, people=6, rounds=2)
        first = s.get(Round, first_id)
        delib.assign_randomly(s, first)
        before = _seed_attendee_ids(s, first)

        second = s.get(Round, second_id)
        delib.copy_previous_assignment(s, second)

        after = {
            m.participant_id: m.attendee_id
            for m in s.query(RoomMember).filter(RoomMember.round_id == second_id)
        }
        assert after == before


def test_copy_previous_reuses_the_previous_room_count_and_grouping(db, make_session):
    with db() as s:
        _, (first_id, second_id) = make_session(s, rooms=2, people=6, rounds=2)
        first = s.get(Round, first_id)
        delib.assign_randomly(s, first, 3)
        grouping = {
            room.number: {m.participant_id for m in room.members} for room in first.rooms
        }

        second = s.get(Round, second_id)
        delib.copy_previous_assignment(s, second)

        assert {
            room.number: {m.participant_id for m in room.members} for room in second.rooms
        } == grouping


def test_move_into_another_rounds_room_is_refused(db, make_session):
    with db() as s:
        _, (first_id, second_id) = make_session(s, rooms=2, people=4, rounds=2)
        first = s.get(Round, first_id)
        second = s.get(Round, second_id)
        delib.assign_randomly(s, first)
        delib.assign_randomly(s, second)
        stranger = second.rooms[0]
        member = s.query(RoomMember).filter(RoomMember.round_id == first_id).first()
        with pytest.raises(HTTPException) as excinfo:
            delib.move_participant(s, first, member.participant_id, stranger.id)
        assert excinfo.value.status_code == 404
