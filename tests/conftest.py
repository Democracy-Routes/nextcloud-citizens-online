# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from citizens_online.config import get_settings
from citizens_online.db.migrate import run_migrations
from citizens_online.db.models import Participant, Round, Session
from citizens_online.db.session import configure_database, session_scope, sqlite_url
from citizens_online.main import create_app
from citizens_online.security.identity import get_current_user_id
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


@pytest.fixture
def client(settings_env):
    """App without AppAPI signature auth; identity comes from the X-Test-User
    header (default 'tester') so ownership rules can be exercised."""
    app = create_app(with_auth=False)

    def fake_user(request: Request) -> str:
        return request.headers.get("x-test-user", "tester")

    app.dependency_overrides[get_current_user_id] = fake_user
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
