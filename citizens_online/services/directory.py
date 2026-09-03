# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one place that asks Nextcloud who its users and groups are.

Every call here is made **as the organizer**, never as the service user, so the
server's own visibility rules apply: an administrator sees everyone, an ordinary
organizer sees what sharing settings allow them to see. That is deliberate — a
deliberation tool should not become a way to enumerate an instance's accounts.

Two behaviours of Nextcloud shape this module:

* `core/autocomplete/get` is available to any logged-in user, but asking it for
  users and groups in the same call returns **only the groups** — and nothing at
  all when no group matches. Verified against Talk 24 / Nextcloud 34, so the two
  kinds are fetched separately and merged here.
* That endpoint also **excludes the caller from their own results**. An organizer
  who wants to take part must still be findable, so `search` puts them back.
* Group *membership* is not readable by an ordinary user at all — the
  provisioning API answers 403 unless you are an administrator or a sub-admin of
  that group. `group_members` therefore fails with an explanation rather than
  pretending the group is empty.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException
from nc_py_api import NextcloudApp

log = structlog.get_logger(__name__)

# The share type has to live in the path: nc_py_api does not expand a list in
# `params` into the repeated `shareTypes[]=` form Nextcloud expects.
AUTOCOMPLETE = "/ocs/v2.php/core/autocomplete/get?shareTypes%5B%5D={share_type}"
GROUP_MEMBERS = "/ocs/v1.php/cloud/groups/{group_id}/users/details"

# A paste of more than this is a spreadsheet, not a guest list, and each entry
# costs one round-trip to Nextcloud.
MAX_RESOLVE = 100

SHARE_TYPE_USER = 0
SHARE_TYPE_GROUP = 1


def _autocomplete(nc: NextcloudApp, query: str, limit: int, share_type: int) -> list[dict]:
    try:
        data = nc.ocs(
            "GET",
            AUTOCOMPLETE.format(share_type=share_type),
            params={
                "search": query,
                "itemType": "call",
                "itemId": "new",
                "limit": limit,
            },
        )
    except Exception as exc:
        log.warning("directory_search_failed", query=query[:40], error=str(exc)[:200])
        raise HTTPException(
            status_code=503, detail="Could not reach Nextcloud's user directory"
        ) from exc
    return list(data or [])


def search(nc: NextcloudApp, query: str, limit: int = 15) -> list[dict]:
    """Users and groups matching `query`, as this organizer is allowed to see them."""
    query = query.strip()
    if not query:
        return []
    # Groups first: there are far fewer of them, and one of them standing for
    # thirty people should not be pushed off the end of the list by the people.
    raw = _autocomplete(nc, query, limit, SHARE_TYPE_GROUP) + _autocomplete(
        nc, query, limit, SHARE_TYPE_USER
    )
    results = [
        {
            "id": entry.get("id", ""),
            "label": entry.get("label") or entry.get("id", ""),
            "source": "groups" if entry.get("source") == "groups" else "users",
        }
        for entry in raw
        if entry.get("id")
    ][:limit]
    return _with_self(nc, query, results)


def _with_self(nc: NextcloudApp, query: str, results: list[dict]) -> list[dict]:
    """Nextcloud never returns you to yourself; an organizer taking part needs to
    be able to find their own account."""
    me = nc.user
    if not me or any(r["id"] == me and r["source"] == "users" for r in results):
        return results
    label = _display_name(nc, me) or me
    if query.lower() in me.lower() or query.lower() in label.lower():
        results.insert(0, {"id": me, "label": f"{label} (you)", "source": "users"})
    return results


def _display_name(nc: NextcloudApp, uid: str) -> str:
    try:
        data = nc.ocs("GET", "/ocs/v1.php/cloud/user")
        if data.get("id") == uid:
            return data.get("displayname") or data.get("display-name") or ""
    except Exception as exc:  # a missing display name is not worth failing over
        log.warning("directory_self_lookup_failed", error=str(exc)[:200])
    return ""


def resolve_users(nc: NextcloudApp, ids: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map account ids to real display names, and report the ones that do not exist.

    An exact-name search still matches even where the administrator has disabled
    user enumeration, so pasted lists keep working on a locked-down instance —
    only browsing the dropdown degrades there.
    """
    found: dict[str, str] = {}
    unknown: list[str] = []
    me = nc.user
    for uid in ids[:MAX_RESOLVE]:
        uid = uid.strip()
        if not uid or uid in found or uid in unknown:
            continue
        if uid == me:
            found[uid] = _display_name(nc, uid) or uid
            continue
        match = next(
            (
                e
                for e in _autocomplete(nc, uid, 10, SHARE_TYPE_USER)
                if e.get("id") == uid and e.get("source") != "groups"
            ),
            None,
        )
        if match is None:
            unknown.append(uid)
        else:
            found[uid] = match.get("label") or uid
    return found, unknown


def group_members(nc: NextcloudApp, group_id: str) -> list[tuple[str, str]]:
    """Every member of a group, with display names, in one call.

    Requires the organizer to be an administrator or a sub-admin of the group —
    Nextcloud does not let anyone else read group membership.
    """
    try:
        data = nc.ocs("GET", GROUP_MEMBERS.format(group_id=group_id))
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status == 403:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"You need to be an administrator, or a sub-admin of “{group_id}”, to add "
                    "the whole group. You can still add its members individually."
                ),
            ) from exc
        if status == 404:
            raise HTTPException(status_code=404, detail=f"No group named “{group_id}”") from exc
        log.warning("directory_group_failed", group=group_id[:40], error=str(exc)[:200])
        raise HTTPException(
            status_code=503, detail="Could not read the group from Nextcloud"
        ) from exc

    users = (data or {}).get("users") or {}
    out = []
    for uid, details in users.items():
        name = ""
        if isinstance(details, dict):
            name = details.get("displayname") or details.get("display-name") or ""
        out.append((uid, name or uid))
    return sorted(out)
