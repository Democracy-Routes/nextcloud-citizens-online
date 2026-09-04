# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telling participants the assembly exists.

Before this, `participant_view` was pull-only: you discovered you were in a
deliberation by opening the app and noticing. These tests pin the two rules that
matter — nobody is notified twice by accident, and somebody the server refused
to notify is not recorded as invited.
"""

import json

import pytest

from citizens_online.db.models import Participant
from citizens_online.jobs import handlers
from citizens_online.services import notifications


class _Outbox(list):
    """Notifications that were "sent", plus the users the server should refuse."""

    def __init__(self):
        super().__init__()
        self.refuse: set[str] = set()


@pytest.fixture
def sent(monkeypatch):
    """Capture notifications instead of sending them, and let a test make one fail."""
    outbox = _Outbox()

    def fake_notify(nc, user_id, subject, message, link=""):
        if user_id in outbox.refuse:
            return False
        outbox.append((user_id, subject))
        return True

    monkeypatch.setattr(notifications, "notify", fake_notify)
    monkeypatch.setattr(notifications, "_client", lambda: object())
    return outbox


def _session_with(client, people=("co1", "co2", "co3")):
    session = client.post(
        "/api/v1/sessions",
        json={"name": "Assembly", "rounds": [{"title": "R1", "duration_minutes": 10}]},
    ).json()
    client.post(
        f"/api/v1/sessions/{session['id']}/participants",
        json={"participants": [{"nc_user_id": u} for u in people]},
    )
    return session["id"]


def test_invite_queues_everyone_not_yet_invited(client):
    session_id = _session_with(client)
    body = client.post(f"/api/v1/sessions/{session_id}/participants/invite", json={}).json()
    assert body["queued"] == 3


def test_the_job_notifies_and_records_who_was_reached(client, db, sent):
    session_id = _session_with(client)
    client.post(f"/api/v1/sessions/{session_id}/participants/invite", json={})

    handlers.handle_invite_participants({"session_id": session_id})

    assert sorted(u for u, _ in sent) == ["co1", "co2", "co3"]
    assert all("Assembly" in subject for _, subject in sent)
    with db() as s:
        assert all(p.invited_at is not None for p in s.query(Participant))


def test_somebody_the_server_refused_is_not_marked_invited(client, db, sent):
    """Otherwise a transient failure silently costs that person their invitation
    for ever, because the next press skips anyone already marked."""
    session_id = _session_with(client)
    sent.refuse.add("co2")

    handlers.handle_invite_participants({"session_id": session_id})

    with db() as s:
        by_user = {p.nc_user_id: p.invited_at for p in s.query(Participant)}
    assert by_user["co1"] is not None
    assert by_user["co3"] is not None
    assert by_user["co2"] is None


def test_a_second_invite_reaches_only_the_people_who_were_missed(client, db, sent):
    session_id = _session_with(client)
    sent.refuse.add("co2")
    handlers.handle_invite_participants({"session_id": session_id})
    sent.clear()
    sent.refuse.clear()

    body = client.post(f"/api/v1/sessions/{session_id}/participants/invite", json={}).json()
    assert body["queued"] == 1
    handlers.handle_invite_participants({"session_id": session_id})
    assert [u for u, _ in sent] == ["co2"]


def test_nobody_is_notified_twice_without_force(client, sent):
    session_id = _session_with(client)
    handlers.handle_invite_participants({"session_id": session_id})
    sent.clear()

    body = client.post(f"/api/v1/sessions/{session_id}/participants/invite", json={}).json()
    assert body["queued"] == 0
    assert "already" in body["reason"]
    handlers.handle_invite_participants({"session_id": session_id})
    assert sent == []


def test_force_reminds_everyone(client, sent):
    session_id = _session_with(client)
    handlers.handle_invite_participants({"session_id": session_id})
    sent.clear()

    body = client.post(
        f"/api/v1/sessions/{session_id}/participants/invite", json={"force": True}
    ).json()
    assert body["queued"] == 3
    handlers.handle_invite_participants({"session_id": session_id, "force": True})
    assert sorted(u for u, _ in sent) == ["co1", "co2", "co3"]


def test_invited_at_is_reported_to_the_organizer(client, sent):
    session_id = _session_with(client, people=("co1",))
    handlers.handle_invite_participants({"session_id": session_id})
    person = client.get(f"/api/v1/sessions/{session_id}/participants").json()[0]
    assert person["invited_at"] is not None


def test_another_organizers_session_cannot_be_invited(client):
    session_id = _session_with(client)
    r = client.post(
        f"/api/v1/sessions/{session_id}/participants/invite",
        json={},
        headers={"X-Test-User": "somebody-else"},
    )
    assert r.status_code == 404


def test_the_audit_trail_records_the_invitation(client, db):
    from citizens_online.db.models import AuditEvent

    session_id = _session_with(client)
    client.post(f"/api/v1/sessions/{session_id}/participants/invite", json={})
    with db() as s:
        event = s.query(AuditEvent).filter(AuditEvent.event == "participants_invited").one()
        assert json.loads(event.data_json)["count"] == 3
