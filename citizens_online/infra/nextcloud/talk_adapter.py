# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one place that speaks Nextcloud Talk.

Every Talk call in the application goes through here (spec §8). The adapter
acts as a dedicated service user which owns — and is therefore moderator of —
every conversation it creates.

Endpoint behaviour verified against Talk 24.0.4 on 2026-08-31; see
`docs/spike-results.md`. Two findings shape this file:

* `POST /breakout-rooms/{token}` returns the child rooms **and the parent**.
  Children are identified by `objectType == "room"` and `objectId == parent`,
  never by position in the array.
* Bots are **not** inherited into breakout rooms. Each room needs its own
  `POST /bot/{token}/{botId}` after it is created, and again after a remix.
"""

import json

from nc_py_api import NextcloudApp

from citizens_online.infra.ports import Attendee, MeetingRoom
from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

SPREED = "/ocs/v2.php/apps/spreed/api"

# Talk attendee permission bits (Talk constants).
PERMISSION_CUSTOM = 1
PERMISSION_PUBLISH_AUDIO = 16

# Talk conversation types.
ROOM_TYPE_GROUP = 2
ROOM_TYPE_PUBLIC = 3

# Talk refuses more than this many breakout rooms per parent conversation.
MAX_BREAKOUT_ROOMS_PER_PARENT = 20

BREAKOUT_MODE_MANUAL = 2


class TalkError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class TalkAdapter:
    """Implements `MeetingProvider` against Nextcloud Talk."""

    def __init__(self, service_user: str, bot_id: int | None = None):
        self.service_user = service_user
        self.bot_id = bot_id
        self._nc: NextcloudApp | None = None

    @property
    def nc(self) -> NextcloudApp:
        # Built once and reused: nc_py_api fetches /cloud/capabilities on every
        # new instance, which doubles the round-trips on hot paths.
        if self._nc is None:
            nc = NextcloudApp()
            nc.set_user(self.service_user)
            self._nc = nc
        return self._nc

    def _ocs(self, method: str, path: str, params: dict | None = None):
        try:
            return self.nc.ocs(method, SPREED + path, params=params or {})
        except Exception as exc:  # nc_py_api raises its own error types
            status = getattr(exc, "status_code", None) or getattr(exc, "reason", None)
            raise TalkError(f"{method} {path} failed: {type(exc).__name__}: {exc}", status) from exc

    # ---------------------------------------------------------------- rooms

    def create_conversation(self, name: str, public: bool = False) -> MeetingRoom:
        data = self._ocs(
            "POST",
            "/v4/room",
            {"roomType": ROOM_TYPE_PUBLIC if public else ROOM_TYPE_GROUP, "roomName": name[:255]},
        )
        room = MeetingRoom(token=data["token"], name=data.get("displayName", name))
        log.info("talk_conversation_created", token=room.token, name=name)
        return room

    def delete_conversation(self, token: str) -> None:
        self._ocs("DELETE", f"/v4/room/{token}")
        log.info("talk_conversation_deleted", token=token)

    def rename_conversation(self, token: str, name: str) -> None:
        self._ocs("PUT", f"/v4/room/{token}", {"roomName": name[:255]})

    def set_description(self, token: str, description: str) -> None:
        self._ocs("PUT", f"/v4/room/{token}/description", {"description": description[:2000]})

    # --------------------------------------------------------- participants

    def add_participants(self, token: str, user_ids: list[str]) -> list[str]:
        added = []
        for uid in user_ids:
            try:
                self._ocs(
                    "POST", f"/v4/room/{token}/participants", {"newParticipant": uid, "source": "users"}
                )
                added.append(uid)
            except TalkError as exc:
                # one unknown user must not abort the whole assembly
                log.warning("talk_add_participant_failed", token=token, user=uid, error=str(exc)[:200])
        return added

    def _attendees(self, raw) -> list[Attendee]:
        out = []
        for p in raw or []:
            out.append(
                Attendee(
                    attendee_id=int(p.get("attendeeId", 0)),
                    actor_id=p.get("actorId", ""),
                    display_name=p.get("displayName", ""),
                    participant_type=int(p.get("participantType", 3)),
                    in_call=int(p.get("inCall", 0)),
                    permissions=int(p.get("permissions", 0)),
                    session_ids=list(p.get("sessionIds") or []),
                )
            )
        return out

    def list_participants(self, token: str) -> list[Attendee]:
        return self._attendees(self._ocs("GET", f"/v4/room/{token}/participants"))

    def call_participants(self, token: str) -> list[Attendee]:
        """Who is actually in the call right now (not merely a member)."""
        return self._attendees(self._ocs("GET", f"/v4/call/{token}"))

    def remove_attendee(self, token: str, attendee_id: int) -> None:
        self._ocs("DELETE", f"/v4/room/{token}/attendees", {"attendeeId": attendee_id})

    def promote_moderator(self, token: str, attendee_id: int) -> None:
        self._ocs("POST", f"/v4/room/{token}/moderators", {"attendeeId": attendee_id})

    def set_audio_permission(self, token: str, attendee_id: int, allowed: bool) -> None:
        """Grant or revoke PUBLISH_AUDIO for one attendee.

        Talk needs the CUSTOM bit set for per-attendee permissions to apply at
        all, so a revoke sends `set` with only CUSTOM, and a grant sends `add`.
        """
        if allowed:
            self._ocs(
                "PUT",
                f"/v4/room/{token}/attendees/permissions",
                {"attendeeId": attendee_id, "method": "add", "permissions": PERMISSION_PUBLISH_AUDIO},
            )
        else:
            self._ocs(
                "PUT",
                f"/v4/room/{token}/attendees/permissions",
                {
                    "attendeeId": attendee_id,
                    "method": "remove",
                    "permissions": PERMISSION_PUBLISH_AUDIO,
                },
            )
        log.info("talk_audio_permission", token=token, attendee_id=attendee_id, allowed=allowed)

    # ------------------------------------------------------ breakout rooms

    def create_breakout_rooms(
        self, parent_token: str, amount: int, attendee_map: dict[int, int]
    ) -> list[MeetingRoom]:
        if amount > MAX_BREAKOUT_ROOMS_PER_PARENT:
            raise TalkError(
                f"Talk allows at most {MAX_BREAKOUT_ROOMS_PER_PARENT} breakout rooms per "
                f"conversation; the engine must split {amount} rooms across several parents"
            )
        payload = {
            "mode": BREAKOUT_MODE_MANUAL,
            "amount": amount,
            "attendeeMap": json.dumps({str(k): int(v) for k, v in attendee_map.items()}),
        }
        data = self._ocs("POST", f"/v1/breakout-rooms/{parent_token}", payload)
        # The response contains the parent as well; identify children properly.
        children = [
            r
            for r in (data or [])
            if r.get("objectType") == "room" and r.get("objectId") == parent_token
        ]
        rooms = [
            MeetingRoom(token=r["token"], name=r.get("displayName", ""), parent_token=parent_token)
            for r in children
        ]
        if len(rooms) != amount:
            log.warning(
                "talk_breakout_count_mismatch", expected=amount, got=len(rooms), parent=parent_token
            )
        log.info("talk_breakouts_created", parent=parent_token, rooms=[r.token for r in rooms])
        return rooms

    def reorganize_breakout_rooms(self, parent_token: str, attendee_map: dict[int, int]) -> None:
        self._ocs(
            "POST",
            f"/v1/breakout-rooms/{parent_token}/attendees",
            {"attendeeMap": json.dumps({str(k): int(v) for k, v in attendee_map.items()})},
        )
        log.info("talk_breakouts_reorganized", parent=parent_token, moved=len(attendee_map))

    def start_breakout_rooms(self, parent_token: str) -> None:
        self._ocs("POST", f"/v1/breakout-rooms/{parent_token}/rooms")
        log.info("talk_breakouts_started", parent=parent_token)

    def stop_breakout_rooms(self, parent_token: str) -> None:
        self._ocs("DELETE", f"/v1/breakout-rooms/{parent_token}/rooms")
        log.info("talk_breakouts_stopped", parent=parent_token)

    def remove_breakout_rooms(self, parent_token: str) -> None:
        self._ocs("DELETE", f"/v1/breakout-rooms/{parent_token}")
        log.info("talk_breakouts_removed", parent=parent_token)

    # ------------------------------------------------------------ messages

    def broadcast(self, parent_token: str, message: str) -> None:
        self._ocs("POST", f"/v1/breakout-rooms/{parent_token}/broadcast", {"message": message[:32000]})

    def send_message(self, token: str, message: str, silent: bool = False) -> None:
        self._ocs(
            "POST",
            f"/v1/chat/{token}",
            {"message": message[:32000], "silent": "true" if silent else "false"},
        )

    def read_messages(self, token: str, last_known_id: int = 0, limit: int = 100) -> list[dict]:
        """History since `last_known_id`. Used to fold chat contributions into
        the transcript, so a deliberation held in text is still analysable."""
        try:
            data = self._ocs(
                "GET",
                f"/v1/chat/{token}",
                {
                    "lookIntoFuture": 0,
                    "limit": limit,
                    "lastKnownMessageId": last_known_id,
                    "setReadMarker": 0,
                },
            )
        except TalkError:
            return []
        return list(data or [])

    # ----------------------------------------------------------------- bot

    def enable_bot(self, token: str) -> bool:
        """Talk does not inherit bots into breakout rooms — enable per room."""
        if not self.bot_id:
            return False
        try:
            self._ocs("POST", f"/v1/bot/{token}/{self.bot_id}")
            return True
        except TalkError as exc:
            log.warning("talk_enable_bot_failed", token=token, bot_id=self.bot_id, error=str(exc)[:200])
            return False

    def list_bots(self, token: str) -> list[dict]:
        try:
            return list(self._ocs("GET", f"/v1/bot/{token}") or [])
        except TalkError:
            return []
