# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The room endpoints' input handling.

Both took a raw dict before, so `{"rooms": 500}` happily created five hundred
room rows — a plan Talk can never execute, discovered only at start_round in
front of a waiting assembly — and a malformed move body raised KeyError, which
FastAPI turns into a 500 rather than a 422.
"""

import pytest

from citizens_online.infra.nextcloud.talk_adapter import MAX_BREAKOUT_ROOMS_PER_PARENT


def _make_session(client, rooms=2, people=4):
    response = client.post(
        "/api/v1/sessions",
        json={"name": "Test assembly", "rooms_per_round": rooms},
    )
    assert response.status_code == 201, response.text
    session = response.json()
    client.post(
        f"/api/v1/sessions/{session['id']}/rounds",
        json={"title": "Round 1", "question": "Why?", "duration_minutes": 10},
    )
    client.post(
        f"/api/v1/sessions/{session['id']}/participants",
        json={
            "participants": [
                {"nc_user_id": f"co{i + 1}", "display_name": f"P{i + 1}"} for i in range(people)
            ]
        },
    )
    detail = client.get(f"/api/v1/sessions/{session['id']}").json()
    return session["id"], detail["rounds"][0]["id"]


def test_randomize_accepts_an_explicit_count(client):
    _, round_id = _make_session(client)
    response = client.post(f"/api/v1/rounds/{round_id}/rooms/randomize", json={"rooms": 3})
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_randomize_falls_back_to_the_session_default(client):
    _, round_id = _make_session(client, rooms=2)
    response = client.post(f"/api/v1/rounds/{round_id}/rooms/randomize", json={})
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.parametrize("count", [0, -1, MAX_BREAKOUT_ROOMS_PER_PARENT + 1, 500])
def test_randomize_refuses_a_count_talk_could_never_honour(client, count):
    _, round_id = _make_session(client)
    response = client.post(f"/api/v1/rounds/{round_id}/rooms/randomize", json={"rooms": count})
    assert response.status_code == 422
    # and nothing was created
    assert client.get(f"/api/v1/rounds/{round_id}/rooms").json() == []


def test_randomize_allows_talks_maximum(client):
    _, round_id = _make_session(client, people=40)
    response = client.post(
        f"/api/v1/rounds/{round_id}/rooms/randomize",
        json={"rooms": MAX_BREAKOUT_ROOMS_PER_PARENT},
    )
    assert response.status_code == 200
    assert len(response.json()) == MAX_BREAKOUT_ROOMS_PER_PARENT


def test_move_rejects_a_malformed_body_with_422_not_500(client):
    _, round_id = _make_session(client)
    client.post(f"/api/v1/rounds/{round_id}/rooms/randomize", json={})
    response = client.post(f"/api/v1/rounds/{round_id}/rooms/move", json={"participant_id": "x"})
    assert response.status_code == 422


def test_move_relocates_the_participant(client):
    session_id, round_id = _make_session(client)
    rooms = client.post(f"/api/v1/rounds/{round_id}/rooms/randomize", json={"rooms": 2}).json()
    source = next(r for r in rooms if r["members"])
    target = next(r for r in rooms if r["id"] != source["id"])
    participant_id = source["members"][0]["participant_id"]

    response = client.post(
        f"/api/v1/rounds/{round_id}/rooms/move",
        json={"participant_id": participant_id, "room_id": target["id"]},
    )
    assert response.status_code == 200
    moved = next(r for r in response.json() if r["id"] == target["id"])
    assert participant_id in [m["participant_id"] for m in moved["members"]]


def test_rooms_of_another_organizer_are_not_reachable(client):
    _, round_id = _make_session(client)
    response = client.get(
        f"/api/v1/rounds/{round_id}/rooms", headers={"X-Test-User": "somebody-else"}
    )
    assert response.status_code == 404
