# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Callbacks from other systems.

These routes are PUBLIC in the AppAPI sense — they carry no Nextcloud session —
so each one authenticates itself. The Talk bot webhook is verified against the
signature Talk computes with the bot's shared secret; nothing else is trusted.
"""

from fastapi import APIRouter, Header, Request, Response

from citizens_online.infra.nextcloud.bot import verify_signature
from citizens_online.logging_setup import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

MAX_BODY_BYTES = 256_000


@router.post("/talk/bot")
async def talk_bot_webhook(
    request: Request,
    x_nextcloud_talk_random: str = Header(default=""),
    x_nextcloud_talk_signature: str = Header(default=""),
):
    """Talk tells the bot what happened in a conversation.

    The bot is a mouthpiece, not an authority: nothing here changes the state of
    a deliberation. Chat contributions are gathered when the round ends
    (`services/chat_import.py`), which keeps this handler cheap and idempotent.
    """
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=413)
    if not verify_signature(x_nextcloud_talk_random, x_nextcloud_talk_signature, body):
        log.warning("bot_webhook_rejected", reason="bad_signature")
        return Response(status_code=401)

    try:
        import json

        activity = json.loads(body)
    except ValueError:
        return Response(status_code=400)

    kind = activity.get("type", "")
    target = (activity.get("target") or {}).get("id", "")
    if kind in ("Join", "Leave"):
        log.info("bot_membership_changed", type=kind, conversation=target)
    # Everything else is acknowledged and ignored on purpose.
    return Response(status_code=200)


@router.get("/health")
def integrations_health():
    """Reachability probe for the callback surface, with no authentication and
    nothing revealed."""
    return {"ok": True}
