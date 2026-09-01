#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create a ready-to-run demo session so testing starts at the interesting part.

    docker exec -e PYTHONPATH=/app -i nc_app_citizens_online python3 - < scripts/seed-demo.py

Creates a session owned by `admin`, with two rounds and the test participants
already added. It does not start a round: that is the first thing to click.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
os.environ.setdefault("APP_PERSISTENT_STORAGE", "/data")

from citizens_online.db.session import configure_database, session_scope, sqlite_url  # noqa: E402
from citizens_online.services import deliberation as delib  # noqa: E402
from citizens_online.storage.paths import db_path  # noqa: E402

OWNER = os.environ.get("SEED_OWNER", "admin")
PARTICIPANTS = os.environ.get("SEED_PARTICIPANTS", "co1,co2,co3,co4,co5,co6").split(",")

configure_database(sqlite_url(db_path(Path("/data"))))

with session_scope() as db:
    session = delib.create_session(
        db,
        OWNER,
        {
            "name": "Urban mobility — demo assembly",
            "description": (
                "A short demonstration deliberation: two rounds, two breakout rooms, "
                "with the facilitator keeping time and speaking balance."
            ),
            "language": "en",
            "rooms_per_round": 2,
            "policy_preset": "gentle",
            "rounds": [
                {
                    "title": "Round 1 — the problem",
                    "question": "What is the most important mobility problem where you live?",
                    "duration_minutes": 10,
                },
                {
                    "title": "Round 2 — what to do",
                    "question": "Which single change would you prioritise, and what would it cost?",
                    "duration_minutes": 10,
                },
            ],
        },
    )
    delib.add_participants(
        db,
        session,
        [{"nc_user_id": uid.strip(), "display_name": uid.strip()} for uid in PARTICIPANTS if uid.strip()],
        OWNER,
    )
    db.flush()
    print(f"session   {session.id}")
    print(f"owner     {OWNER}")
    print(f"people    {len(session.participants)}")
    for r in session.rounds:
        print(f"round     {r.position}. {r.title} ({r.duration_minutes} min)  id={r.id}")
