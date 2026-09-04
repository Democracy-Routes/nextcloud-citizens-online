# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting a message in a participant's Nextcloud bell.

Until this existed, nobody was ever told about an assembly. `participant_view`
is pull-only: you found out you were in a deliberation by opening the app and
noticing. That works for a demo and not for fifty people on a Thursday.

How it works, and why it looks the way it does:

* AppAPI exposes `POST /ocs/v1.php/apps/app_api/api/v1/notification`, and its
  controller reads the recipient out of the ExApp's **own auth header** rather
  than a path parameter. So the supported way to notify somebody is to
  impersonate them and create a notification "for yourself". `nc_py_api` wraps
  exactly this as `notifications.create`.
* Authentication is the app's own secret. No administrator rights, no user
  password, no email server — which is the whole reason this is possible today.
* `set_user()` **must** come before `create()`: the call is gated on a
  capability that is only advertised in a user context, and without one it
  raises before any HTTP request is made.
* This module builds its **own** client. Re-using `TalkAdapter`'s cached one
  would leave that adapter impersonating whichever participant we notified last,
  and every later Talk call would run as the wrong person.

`set_user()` re-fetches the server's capabilities, so each recipient costs about
two round-trips. That is why sending is driven from a job rather than from the
request that presses the button.
"""

from __future__ import annotations

import structlog
from nc_py_api import NextcloudApp

from citizens_online.config import get_settings

log = structlog.get_logger(__name__)

# Where the notification takes them. AppAPI serves an ExApp's own page here, and
# `overwrite.cli.url` is set on this instance, so the absolute form resolves.
APP_PAGE = "/index.php/apps/app_api/embedded/citizens_online/citizens_online"


def app_link() -> str:
    base = (get_settings().nextcloud_url or "").rstrip("/")
    return f"{base}{APP_PAGE}" if base else ""


def _client() -> NextcloudApp:
    """A client of our own. Never share this with the Talk adapter."""
    return NextcloudApp()


def notify(nc: NextcloudApp, user_id: str, subject: str, message: str, link: str = "") -> bool:
    """Raise one notification. Returns whether it landed.

    A failure for one person must not abandon the rest of the guest list, so
    this reports rather than raises.
    """
    try:
        nc.set_user(user_id)
        nc.notifications.create(subject, message, link=link)
        return True
    except Exception as exc:
        log.warning("notification_failed", user=user_id, error=str(exc)[:200])
        return False


def invite_text(session_name: str, rounds: int, language: str) -> tuple[str, str]:
    """What the invitation says.

    Deliberately concrete about the two things a participant needs to decide
    whether to take part: that it is recorded, and that they can read the
    details before agreeing to anything.
    """
    subject = f"You have been invited to “{session_name}”"
    message = (
        f"A deliberation with {rounds} round{'s' if rounds != 1 else ''}. "
        "It is recorded and AI-assisted — open Citizens Online to read exactly "
        "what that means and to accept or decline."
    )
    return subject, message
