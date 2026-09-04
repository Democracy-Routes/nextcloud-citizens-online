# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking people up, and the rules Nextcloud imposes on it.

Before this existed, a participant was whatever string the organizer typed. A
typo produced a row that looked correct in the table and was then silently
absent from Talk when the round started — the only trace being a warning in the
server log. Every test here guards some part of "the name is real".
"""


def _session(client):
    response = client.post("/api/v1/sessions", json={"name": "Assembly"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ------------------------------------------------------------------- search


def test_search_returns_users_and_groups(client):
    body = client.get("/api/v1/directory/search", params={"q": "co1"}).json()
    sources = {r["source"] for r in body["results"]}
    assert "users" in sources
    assert any(r["id"] == "co1" for r in body["results"])

    body = client.get("/api/v1/directory/search", params={"q": "testers"}).json()
    assert any(r["source"] == "groups" and r["id"] == "testers" for r in body["results"])


def test_search_uses_the_real_display_name(client):
    body = client.get("/api/v1/directory/search", params={"q": "co2"}).json()
    match = next(r for r in body["results"] if r["id"] == "co2")
    assert match["label"] == "Test Participant 2"


def test_an_empty_query_asks_nextcloud_nothing(client, nc):
    body = client.get("/api/v1/directory/search", params={"q": "   "}).json()
    assert body["results"] == []
    assert nc.calls == []


def test_the_organizer_can_find_themselves(client):
    """Nextcloud excludes you from your own autocomplete results, so an organizer
    who wants to take part would otherwise be unable to add themselves."""
    body = client.get("/api/v1/directory/search", params={"q": "tester"}).json()
    me = next(r for r in body["results"] if r["id"] == "tester")
    assert me["label"].endswith("(you)")
    assert body["results"][0]["id"] == "tester"


def test_self_is_not_injected_into_an_unrelated_search(client):
    body = client.get("/api/v1/directory/search", params={"q": "co3"}).json()
    assert all(r["id"] != "tester" for r in body["results"])


# ------------------------------------------------- adding individual people


def test_unknown_accounts_are_reported_and_not_stored(client):
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": u} for u in ("co1", "co2", "nobody")]},
    ).json()

    assert [p["nc_user_id"] for p in body["added"]] == ["co1", "co2"]
    assert body["unknown"] == ["nobody"]

    stored = client.get(f"/api/v1/sessions/{session_id}/participants").json()
    assert {p["nc_user_id"] for p in stored} == {"co1", "co2"}


def test_the_display_name_comes_from_nextcloud_not_the_client(client):
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": "co1", "display_name": "Whatever I Like"}]},
    ).json()
    assert body["added"][0]["display_name"] == "Test Participant 1"


def test_adding_the_same_person_twice_is_harmless(client):
    session_id = _session(client)
    payload = {"participants": [{"nc_user_id": "co1"}]}
    client.post(f"/api/v1/sessions/{session_id}/participants", json=payload)
    body = client.post(f"/api/v1/sessions/{session_id}/participants", json=payload).json()
    assert body["added"] == []
    assert len(client.get(f"/api/v1/sessions/{session_id}/participants").json()) == 1


# -------------------------------------------------------------- groups


def test_a_group_is_imported_with_real_names_and_tagged(client):
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group",
        json={"group_id": "testers"},
    ).json()

    assert body["members"] == 3
    assert {p["nc_user_id"] for p in body["added"]} == {"co1", "co2", "co3"}
    assert all(p["added_via_group"] == "testers" for p in body["added"])
    assert body["added"][0]["display_name"].startswith("Test Participant")


def test_a_group_you_do_not_administer_explains_itself(client):
    session_id = _session(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group",
        json={"group_id": "secret-group"},
    )
    assert response.status_code == 403
    assert "sub-admin" in response.json()["detail"]
    assert client.get(f"/api/v1/sessions/{session_id}/participants").json() == []


def test_an_unknown_group_is_a_404(client):
    session_id = _session(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group",
        json={"group_id": "no-such-group"},
    )
    assert response.status_code == 404


def test_resync_adds_newcomers(client, nc):
    session_id = _session(client)
    client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group", json={"group_id": "testers"}
    )
    nc.groups["testers"].append("co4")

    body = client.post(
        f"/api/v1/sessions/{session_id}/participants/resync-group", json={"group_id": "testers"}
    ).json()

    assert [p["nc_user_id"] for p in body["added"]] == ["co4"]
    assert body["departed"] == []


def test_resync_reports_departures_but_keeps_them(client, nc):
    """Someone who left the group may already have consented and been recorded;
    removing them is the organizer's decision, not a side effect of a re-sync."""
    session_id = _session(client)
    client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group", json={"group_id": "testers"}
    )
    nc.groups["testers"].remove("co3")

    body = client.post(
        f"/api/v1/sessions/{session_id}/participants/resync-group", json={"group_id": "testers"}
    ).json()

    assert [p["nc_user_id"] for p in body["departed"]] == ["co3"]
    stored = client.get(f"/api/v1/sessions/{session_id}/participants").json()
    assert "co3" in {p["nc_user_id"] for p in stored}


def test_someone_added_by_hand_is_never_reported_as_departed(client, nc):
    session_id = _session(client)
    client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": "co9"}]},
    )
    client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group", json={"group_id": "testers"}
    )
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants/resync-group", json={"group_id": "testers"}
    ).json()
    assert body["departed"] == []


def test_another_organizers_session_is_not_reachable(client):
    session_id = _session(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/participants/from-group",
        json={"group_id": "testers"},
        headers={"X-Test-User": "somebody-else"},
    )
    assert response.status_code == 404


# ------------------------------------------------------- bulk paste batching


def test_a_pasted_list_is_resolved_in_few_round_trips(client, nc):
    """Fifty names used to mean fifty calls to Nextcloud. They share a prefix, so
    one lookup answers for all of them."""
    session_id = _session(client)
    names = [f"co{i}" for i in range(1, 41)]
    nc.calls.clear()

    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": u} for u in names]},
    ).json()

    assert len(body["added"]) == 40
    assert body["unknown"] == []
    lookups = [c for c in nc.calls if "autocomplete" in c[1]]
    assert len(lookups) <= 3, f"expected a handful of lookups, made {len(lookups)}"


def test_batching_still_reports_a_name_that_does_not_exist(client):
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": u} for u in ("co1", "co2", "conot", "zzz")]},
    ).json()
    assert sorted(p["nc_user_id"] for p in body["added"]) == ["co1", "co2"]
    assert sorted(body["unknown"]) == ["conot", "zzz"]


def test_a_truncated_batch_still_finds_a_real_account(client, nc, monkeypatch):
    """If a prefix has more matches than the batch limit, the per-name fallback
    has to catch what the batch missed — otherwise a real account is reported as
    unknown, which is the exact failure this feature exists to prevent."""
    from citizens_online.services import directory as directory_svc

    monkeypatch.setattr(directory_svc, "BATCH_LIMIT", 1)
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": u} for u in ("co1", "co7", "co8")]},
    ).json()
    assert sorted(p["nc_user_id"] for p in body["added"]) == ["co1", "co7", "co8"]
    assert body["unknown"] == []


def test_the_pasted_order_is_preserved(client):
    session_id = _session(client)
    body = client.post(
        f"/api/v1/sessions/{session_id}/participants",
        json={"participants": [{"nc_user_id": u} for u in ("co3", "co1", "co2")]},
    ).json()
    assert [p["nc_user_id"] for p in body["added"]] == ["co3", "co1", "co2"]
