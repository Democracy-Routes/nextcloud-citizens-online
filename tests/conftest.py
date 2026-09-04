# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from citizens_online.config import get_settings
from citizens_online.db.migrate import run_migrations
from citizens_online.db.models import Finding, Participant, Room, Round, Session
from citizens_online.db.session import configure_database, session_scope, sqlite_url
from citizens_online.main import create_app
from citizens_online.security.identity import get_current_nc, get_current_user_id
from citizens_online.storage.paths import db_path, ensure_storage_layout


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    """Point the app at a temporary storage dir and return fresh settings."""
    monkeypatch.setenv("APP_ID", "citizens_online")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("NEXTCLOUD_URL", "http://nextcloud.test")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setenv("CO_DEV", "0")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


class NextcloudError(Exception):
    """Shaped like nc_py_api's exception: the code reads `.status_code`."""

    def __init__(self, status_code: int, reason: str = ""):
        super().__init__(f"[{status_code}] {reason}")
        self.status_code = status_code
        self.reason = reason


class FakeNc:
    """A Nextcloud that answers directory questions from a dict.

    Mirrors the two behaviours the real server has that the code must handle:
    autocomplete never returns the caller to themselves, and group membership is
    refused unless you administer the group.
    """

    def __init__(self, user="tester"):
        self.user = user
        self.display_names = {f"co{i}": f"Test Participant {i}" for i in range(1, 51)}
        self.display_names[user] = "The Organizer"
        self.groups: dict[str, list[str]] = {"testers": ["co1", "co2", "co3"]}
        self.forbidden_groups: set[str] = {"secret-group"}
        self.calls: list[tuple[str, str]] = []

    def ocs(self, method, path, params=None, **kwargs):
        self.calls.append((method, path))
        if "/core/autocomplete/get" in path:
            # the real server takes one shareTypes[] value per call; asking for
            # both at once returns only the groups
            share_type = 1 if path.endswith("=1") else 0
            return self._autocomplete(params or {}, share_type)
        if path.endswith("/cloud/user"):
            return {"id": self.user, "displayname": self.display_names.get(self.user, self.user)}
        if "/cloud/groups/" in path and path.endswith("/users/details"):
            return self._group(path.split("/cloud/groups/")[1].rsplit("/users/details", 1)[0])
        raise NextcloudError(404, f"unmapped path {path}")

    def _autocomplete(self, params, share_type):
        needle = str(params.get("search", "")).lower()
        share_types = [share_type]
        out = []
        if 0 in share_types:
            out += [
                {"id": uid, "label": name, "source": "users"}
                for uid, name in sorted(self.display_names.items())
                # the real server excludes the caller from their own results
                if uid != self.user and (needle in uid.lower() or needle in name.lower())
            ]
        if 1 in share_types:
            out += [
                {"id": gid, "label": gid, "source": "groups"}
                for gid in sorted(self.groups)
                if needle in gid.lower()
            ]
        return out[: int(params.get("limit", 15))]

    def _group(self, group_id):
        if group_id in self.forbidden_groups:
            raise NextcloudError(403, "Logged in account must be at least a sub admin")
        if group_id not in self.groups:
            raise NextcloudError(404, "group not found")
        return {
            "users": {
                uid: {"id": uid, "displayname": self.display_names.get(uid, uid)}
                for uid in self.groups[group_id]
            }
        }


@pytest.fixture
def nc():
    """The fake Nextcloud the `client` fixture hands to the routes."""
    return FakeNc()


@pytest.fixture
def client(settings_env, nc):
    """App without AppAPI signature auth; identity comes from the X-Test-User
    header (default 'tester') so ownership rules can be exercised, and directory
    lookups go to the `nc` fixture rather than a real server."""
    app = create_app(with_auth=False)

    def fake_user(request: Request) -> str:
        return request.headers.get("x-test-user", "tester")

    app.dependency_overrides[get_current_user_id] = fake_user
    app.dependency_overrides[get_current_nc] = lambda: nc
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(tmp_path):
    """A migrated, empty database, rebound for this test.

    `configure_database` rebinds module globals and has no teardown, so tests
    that set it up inline leak an engine pointed at a previous tmp_path into
    whatever runs next. Going through this fixture keeps each test on its own
    file. Yields the `session_scope` contextmanager itself, since that is how
    the application code opens a transaction.
    """
    root = tmp_path / "storage"
    ensure_storage_layout(root)
    url = sqlite_url(db_path(root))
    configure_database(url)
    run_migrations(url)
    return session_scope


@pytest.fixture
def make_session():
    """Factory for a session with rounds and participants, for assignment tests.

    A fixture rather than a plain import: there is no `tests/__init__.py`, so the
    test modules are not a package and cannot import from conftest directly.
    """
    return _make_session


def _make_session(db_session, *, rooms=2, people=6, owner="tester", rounds=1):
    """A session with rounds and participants.

    Returns (session_id, [round_id, ...]) rather than live objects: every test
    here reopens its own transaction, and detached instances would be a trap.
    """
    session = Session(name="Test assembly", created_by=owner, rooms_per_round=rooms)
    db_session.add(session)
    db_session.flush()
    round_ids = []
    for position in range(1, rounds + 1):
        round_obj = Round(session_id=session.id, position=position, title=f"Round {position}")
        db_session.add(round_obj)
        db_session.flush()
        round_ids.append(round_obj.id)
    for index in range(people):
        db_session.add(
            Participant(
                session_id=session.id,
                nc_user_id=f"co{index + 1}",
                display_name=f"Test Participant {index + 1}",
            )
        )
    db_session.flush()
    return session.id, round_ids


@pytest.fixture
def make_finding():
    """Factory for findings, for the report tests."""
    return _make_finding


def _make_finding(
    db_session,
    *,
    session_id,
    round_id,
    scope="room",
    room_id=None,
    status="APPROVED",
    title="A finding",
    summary="What people said.",
    kind="agreement",
):
    finding = Finding(
        session_id=session_id,
        round_id=round_id,
        room_id=room_id,
        scope=scope,
        type=kind,
        title=title,
        summary=summary,
        status=status,
    )
    db_session.add(finding)
    db_session.flush()
    return finding


@pytest.fixture
def make_rooms():
    """Rooms for a round, without going through assignment."""
    return _make_rooms


def _make_rooms(db_session, round_obj, count=2):
    rooms = []
    for number in range(1, count + 1):
        room = Room(
            round_id=round_obj.id,
            session_id=round_obj.session_id,
            number=number,
            label=f"Room {number}",
        )
        db_session.add(room)
        rooms.append(room)
    db_session.flush()
    db_session.expire(round_obj, ["rooms"])
    return rooms
