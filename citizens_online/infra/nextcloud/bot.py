# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facilitator's voice in Talk.

The bot is only a mouthpiece (spec §14): it carries messages the engine has
already decided to send, and it never holds workflow state. Incoming webhooks
are used for two things — knowing when the bot was added to a room, and folding
chat contributions into the transcript so a deliberation held in text is still
analysable.
"""

import hashlib
import hmac

from nc_py_api import NextcloudApp
from nc_py_api.talk_bot import AsyncTalkBot, TalkBot, get_bot_secret

from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

BOT_ROUTE = "/api/v1/integrations/talk/bot"
BOT_NAME = "Citizens Online"
BOT_DESCRIPTION = (
    "Keeps time and speaking balance in a Citizens Online deliberation, and relays "
    "the facilitator's messages into each breakout room."
)

# Two views of the same bot. AppAPI hands the enable/disable handler an async
# client, so registration goes through the async one; the engine tick runs in a
# worker thread and posts through the sync one.
FACILITATOR_BOT = AsyncTalkBot(BOT_ROUTE, BOT_NAME, BOT_DESCRIPTION)
_SYNC_BOT = TalkBot(BOT_ROUTE, BOT_NAME, BOT_DESCRIPTION)


def verify_signature(random_header: str, signature_header: str, body: bytes) -> bool:
    """Talk signs every webhook: HMAC-SHA256 of (random + body) with the shared
    secret. nc_py_api's own dependency only parses the body, so the check lives
    here — an unauthenticated PUBLIC route must not trust its input."""
    secret = get_bot_secret(BOT_ROUTE)
    if not secret or not random_header or not signature_header:
        return False
    if isinstance(secret, str):
        secret = secret.encode()
    expected = hmac.new(secret, random_header.encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.lower())


def bot_id_for_conversation(nc: NextcloudApp, token: str) -> int | None:
    """Our bot's numeric id, as Talk knows it in this conversation.

    Talk assigns bot ids at install time; the ExApp only learns its own id by
    asking a conversation it is a moderator of. Cached by the caller.
    """
    try:
        bots = nc.ocs("GET", f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}")
    except Exception as exc:
        log.warning("bot_lookup_failed", token=token, error=str(exc)[:200])
        return None
    for bot in bots or []:
        if (bot.get("name") or "") == BOT_NAME:
            return int(bot["id"])
    return None


def send(token: str, message: str, silent: bool = False) -> bool:
    """Post one message into a conversation as the bot.

    Never raises: a facilitator message that cannot be delivered must not take
    the round down with it.
    """
    try:
        # reply_to_message is positional in nc_py_api; 0 means 'not a reply'
        _SYNC_BOT.send_message(message, 0, silent, token)
        return True
    except Exception as exc:
        log.warning("bot_send_failed", token=token, error=str(exc)[:200])
        return False
