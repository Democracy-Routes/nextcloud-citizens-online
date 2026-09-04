# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report — the app's only outward-facing artefact, previously untested.

It describes a deliberation to people who were not in the room, so the things
worth pinning are the ones where a quiet mistake would misrepresent what
happened: that unapproved AI drafts stay out unless asked for, that findings are
attributed to the right room, and that the room count is what actually ran
rather than what was configured.
"""

from citizens_online.db.models import Round, Session
from citizens_online.services import deliberation as delib
from citizens_online.services import report as report_svc


def _built(db, make_session, make_rooms, make_finding, **kw):
    """A session with two rooms and findings, and its report."""
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=2, people=4)
        round_obj = s.get(Round, round_id)
        rooms = make_rooms(s, round_obj, 2)
        make_finding(
            s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
            title="Room one says", **kw,
        )
        make_finding(
            s, session_id=session_id, round_id=round_id, room_id=rooms[1].id,
            title="Room two says", **kw,
        )
        make_finding(
            s, session_id=session_id, round_id=round_id, scope="round",
            title="Across the rooms", **kw,
        )
        return report_svc.build_report(s, s.get(Session, session_id)), session_id, rooms


def test_approved_findings_reach_the_report(db, make_session, make_rooms, make_finding):
    report, _, _ = _built(db, make_session, make_rooms, make_finding)
    rounds = report["rounds"]
    assert [f["title"] for f in rounds[0]["cross_room"]] == ["Across the rooms"]
    assert [r["findings"][0]["title"] for r in rounds[0]["rooms"]] == [
        "Room one says",
        "Room two says",
    ]


def test_drafts_are_withheld_unless_asked_for(db, make_session, make_rooms, make_finding):
    """An unreviewed AI draft in a published report would be presented as though
    a human had stood behind it."""
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=1, people=2)
        round_obj = s.get(Round, round_id)
        rooms = make_rooms(s, round_obj, 1)
        make_finding(s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
                     title="Reviewed", status="APPROVED")
        make_finding(s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
                     title="Unreviewed", status="DRAFT")
        session_obj = s.get(Session, session_id)

        public = report_svc.build_report(s, session_obj)
        assert [f["title"] for f in public["rounds"][0]["rooms"][0]["findings"]] == ["Reviewed"]

        internal = report_svc.build_report(s, session_obj, include_drafts=True)
        titles = [f["title"] for f in internal["rounds"][0]["rooms"][0]["findings"]]
        assert sorted(titles) == ["Reviewed", "Unreviewed"]
        drafts = [f for f in internal["rounds"][0]["rooms"][0]["findings"] if f["is_draft"]]
        assert [f["title"] for f in drafts] == ["Unreviewed"]


def test_edited_and_approved_counts_as_approved(db, make_session, make_rooms, make_finding):
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=1, people=2)
        rooms = make_rooms(s, s.get(Round, round_id), 1)
        make_finding(s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
                     title="Reworded by a human", status="EDITED_AND_APPROVED")
        report = report_svc.build_report(s, s.get(Session, session_id))
        assert [f["title"] for f in report["rounds"][0]["rooms"][0]["findings"]] == [
            "Reworded by a human"
        ]


def test_room_numbers_survive_repeating_across_rounds(db, make_session, make_rooms, make_finding):
    """Every round has a Room 1, so attribution has to key on the room's id, not
    its number — otherwise a finding lands under the wrong round's room."""
    with db() as s:
        session_id, (first_id, second_id) = make_session(s, rooms=2, people=4, rounds=2)
        first_rooms = make_rooms(s, s.get(Round, first_id), 2)
        second_rooms = make_rooms(s, s.get(Round, second_id), 2)
        make_finding(s, session_id=session_id, round_id=first_id, room_id=first_rooms[1].id,
                     title="From round 1 room 2")
        make_finding(s, session_id=session_id, round_id=second_id, room_id=second_rooms[0].id,
                     title="From round 2 room 1")
        report = report_svc.build_report(s, s.get(Session, session_id))

    by_round = {r["position"]: r for r in report["rounds"]}
    r1 = [f for room in by_round[1]["rooms"] for f in room["findings"]]
    r2 = [f for room in by_round[2]["rooms"] for f in room["findings"]]
    assert [(f["title"], f["room_number"]) for f in r1] == [("From round 1 room 2", 2)]
    assert [(f["title"], f["room_number"]) for f in r2] == [("From round 2 room 1", 1)]


def test_the_room_count_is_what_ran_not_what_was_configured(db, make_session, make_rooms):
    """`rooms_per_round` is only a default for the next distribution; a report
    that quotes it can describe an assembly that never happened."""
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=2, people=6)
        round_obj = s.get(Round, round_id)
        delib.assign_randomly(s, round_obj, 3)  # three rooms actually ran
        session_obj = s.get(Session, session_id)
        assert session_obj.rooms_per_round == 2
        report = report_svc.build_report(s, session_obj)
    assert report["session"]["rooms"] == 3


def test_a_session_with_no_rooms_reports_zero(db, make_session):
    with db() as s:
        session_id, _ = make_session(s, people=2)
        report = report_svc.build_report(s, s.get(Session, session_id))
    assert report["session"]["rooms"] == 0


def test_markdown_renders_the_approved_findings(db, make_session, make_rooms, make_finding):
    report, _, _ = _built(db, make_session, make_rooms, make_finding)
    text = report_svc.render_markdown(report)
    assert "Test assembly" in text
    assert "Across the rooms" in text
    assert "Room one says" in text
    assert text.startswith("#")


def test_pdf_renders(db, make_session, make_rooms, make_finding):
    from citizens_online.services.report_pdf import render_pdf

    report, _, _ = _built(db, make_session, make_rooms, make_finding)
    blob = render_pdf(report)
    assert blob[:4] == b"%PDF"
    assert len(blob) > 1000


def test_freeze_stores_the_report_on_the_session(db, make_session, make_rooms, make_finding):
    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=1, people=2)
        rooms = make_rooms(s, s.get(Round, round_id), 1)
        make_finding(s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
                     title="Kept for the record")
        session_obj = s.get(Session, session_id)
        frozen = report_svc.freeze(s, session_obj)
        assert frozen["session"]["name"] == "Test assembly"

    import json

    with db() as s:
        stored = json.loads(s.get(Session, session_id).final_report_json)
    assert stored["rounds"][0]["rooms"][0]["findings"][0]["title"] == "Kept for the record"


def test_every_valid_finding_type_survives_rendering(db, make_session, make_rooms, make_finding):
    """`group_findings_by_type` renders only the types it knows, and
    `build_report` does not check them — so a type that exists in the model but
    not in the render order would vanish from the report while still sitting in
    the JSON."""
    from citizens_online.db.models.findings import FINDING_TYPES

    with db() as s:
        session_id, (round_id,) = make_session(s, rooms=1, people=2)
        rooms = make_rooms(s, s.get(Round, round_id), 1)
        for kind in FINDING_TYPES:
            make_finding(
                s, session_id=session_id, round_id=round_id, room_id=rooms[0].id,
                title=f"A {kind} finding", kind=kind,
            )
        report = report_svc.build_report(s, s.get(Session, session_id))

    text = report_svc.render_markdown(report)
    missing = [k for k in FINDING_TYPES if f"A {k} finding" not in text]
    assert missing == [], f"these finding types never reach the report: {missing}"
