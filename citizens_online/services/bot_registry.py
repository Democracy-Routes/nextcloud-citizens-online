# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the app learns its own Talk bot id.

Talk assigns bot ids at install time and only reveals them through a
conversation the caller moderates, so the id is discovered lazily the first
time a session has a parent conversation, then cached for the process.
"""

from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

_bot_id: int | None = None


def cached_bot_id() -> int | None:
    return _bot_id


def discover_bot_id(nc, token: str) -> int | None:
    """Ask a conversation which bots it knows, and remember ours."""
    global _bot_id
    if _bot_id is not None:
        return _bot_id
    from citizens_online.infra.nextcloud.bot import bot_id_for_conversation

    _bot_id = bot_id_for_conversation(nc, token)
    if _bot_id:
        log.info("talk_bot_id_discovered", bot_id=_bot_id)
    return _bot_id


def set_bot_id(value: int | None) -> None:
    global _bot_id
    _bot_id = value
