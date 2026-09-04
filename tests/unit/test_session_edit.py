# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Editing a session, and the values it will accept.

`update_session` had no lifecycle guard at all — a session mid-round, or a
closed one, accepted every field — and neither `language` nor `policy_preset`
was checked against the values that actually mean something further down. A bad
language reached the speech engine and the Vosk model lookup verbatim; a bad
preset silently became `gentle`. Both produced a session that behaved
differently from what its own record said.
"""

import pytest

from citizens_online.core.speaking.policies import PRESETS
from citizens_online.domain.constants import (
    POLICY_PRESETS,
    SPEAKING_POLICIES,
    SUPPORTED_LANGUAGES,
)
from citizens_online.services.analysis import LANGUAGE_NAMES


def _session(client, **extra):
    body = {"name": "Assembly", "rounds": [{"title": "R1", "duration_minutes": 10}], **extra}
    response = client.post("/api/v1/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------ the constants stay in step


def test_supported_languages_match_the_analysis_map():
    """Adding a language in one place and not the other is a test failure, not a
    silently unusable option."""
    assert set(SUPPORTED_LANGUAGES) == set(LANGUAGE_NAMES)


def test_policy_presets_match_the_speaking_policies():
    assert set(POLICY_PRESETS) == set(PRESETS)


# ------------------------------------------------------------- what is accepted


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_every_supported_language_is_accepted(client, language):
    session = _session(client)
    r = client.put(f"/api/v1/sessions/{session['id']}", json={"language": language})
    assert r.status_code == 200
    assert r.json()["language"] == language


@pytest.mark.parametrize("bad", ["klingon", "EN", "", "en-GB", "xx"])
def test_an_unknown_language_is_refused(client, bad):
    session = _session(client)
    r = client.put(f"/api/v1/sessions/{session['id']}", json={"language": bad})
    assert r.status_code == 422
    assert client.get(f"/api/v1/sessions/{session['id']}").json()["language"] == "en"


def test_an_unknown_policy_preset_is_refused(client):
    session = _session(client)
    r = client.put(f"/api/v1/sessions/{session['id']}", json={"policy_preset": "brutal"})
    assert r.status_code == 422


def test_an_unknown_language_is_refused_at_creation_too(client):
    r = client.post("/api/v1/sessions", json={"name": "X", "language": "klingon"})
    assert r.status_code == 422


@pytest.mark.parametrize("policy", SPEAKING_POLICIES)
def test_speaking_policy_round_trips(client, policy):
    """It was writable but missing from the payload, so a form could set it and
    never read it back."""
    session = _session(client)
    r = client.put(f"/api/v1/sessions/{session['id']}", json={"speaking_policy": policy})
    assert r.status_code == 200
    assert r.json()["speaking_policy"] == policy
    assert client.get(f"/api/v1/sessions/{session['id']}").json()["speaking_policy"] == policy


# ------------------------------------------------------- the lifecycle guard


def _make_round_active(db, session_id):
    from citizens_online.db.models import Round

    with db() as s:
        round_obj = s.query(Round).filter(Round.session_id == session_id).first()
        round_obj.status = "ACTIVE"


def test_edits_are_refused_while_a_round_is_running(client, db):
    session = _session(client)
    _make_round_active(db, session["id"])

    r = client.put(f"/api/v1/sessions/{session['id']}", json={"name": "Renamed"})
    assert r.status_code == 409
    assert "running" in r.json()["detail"]
    assert client.get(f"/api/v1/sessions/{session['id']}").json()["name"] == "Assembly"


def test_edits_resume_once_the_round_is_over(client, db):
    from citizens_online.db.models import Round

    session = _session(client)
    _make_round_active(db, session["id"])
    assert client.put(f"/api/v1/sessions/{session['id']}", json={"name": "X"}).status_code == 409

    with db() as s:
        s.query(Round).filter(Round.session_id == session["id"]).first().status = "ENDED"

    r = client.put(f"/api/v1/sessions/{session['id']}", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"


# --------------------------------------------------------------- audit trail


def test_the_audit_event_records_which_fields_changed(client, db):
    """It used to log an empty payload — that a session was edited, never what."""
    import json

    from citizens_online.db.models import AuditEvent

    session = _session(client)
    client.put(
        f"/api/v1/sessions/{session['id']}",
        json={"name": "Renamed", "language": "it", "description": "Assembly"},
    )
    with db() as s:
        event = (
            s.query(AuditEvent)
            .filter(AuditEvent.event == "session_updated")
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        changed = json.loads(event.data_json)["changed"]
    assert set(changed) == {"name", "language", "description"}


def test_an_unchanged_field_is_not_reported_as_changed(client, db):
    import json

    from citizens_online.db.models import AuditEvent

    session = _session(client)
    client.put(f"/api/v1/sessions/{session['id']}", json={"name": "Assembly"})
    with db() as s:
        event = (
            s.query(AuditEvent)
            .filter(AuditEvent.event == "session_updated")
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        assert json.loads(event.data_json)["changed"] == []
