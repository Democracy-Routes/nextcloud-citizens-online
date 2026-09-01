# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The boundary between the deliberation engine and the infrastructure it runs on.

Nothing under `citizens_online/core/` imports Nextcloud. It talks to these
Protocols instead, so the same engine can later drive a different meeting
backend (the standalone LiveKit path in `PLAN.md` Part C) and so tests can run
against `infra/fake/` with no server at all.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Attendee:
    """A participant as the meeting backend sees them."""

    attendee_id: int
    actor_id: str
    display_name: str = ""
    participant_type: int = 3
    in_call: int = 0
    permissions: int = 0
    session_ids: list[str] = field(default_factory=list)


@dataclass
class MeetingRoom:
    """A conversation created by the backend."""

    token: str
    name: str = ""
    parent_token: str = ""


class MeetingProvider(Protocol):
    """Rooms, membership, messages and audio permissions.

    The engine decides *who meets whom and for how long*; the provider only
    executes it.
    """

    def create_conversation(self, name: str, public: bool = False) -> MeetingRoom: ...

    def delete_conversation(self, token: str) -> None: ...

    def add_participants(self, token: str, user_ids: list[str]) -> list[str]: ...

    def list_participants(self, token: str) -> list[Attendee]: ...

    def call_participants(self, token: str) -> list[Attendee]: ...

    def create_breakout_rooms(
        self, parent_token: str, amount: int, attendee_map: dict[int, int]
    ) -> list[MeetingRoom]:
        """Configure `amount` rooms and place attendees. Returns the child rooms
        in index order — never including the parent."""

    def reorganize_breakout_rooms(self, parent_token: str, attendee_map: dict[int, int]) -> None: ...

    def start_breakout_rooms(self, parent_token: str) -> None: ...

    def stop_breakout_rooms(self, parent_token: str) -> None: ...

    def remove_breakout_rooms(self, parent_token: str) -> None: ...

    def broadcast(self, parent_token: str, message: str) -> None: ...

    def send_message(self, token: str, message: str, silent: bool = False) -> None: ...

    def set_audio_permission(self, token: str, attendee_id: int, allowed: bool) -> None: ...

    def remove_attendee(self, token: str, attendee_id: int) -> None: ...

    def enable_bot(self, token: str) -> bool:
        """Enable this app's facilitator bot in one conversation. Talk does not
        inherit bots into breakout rooms, so the engine calls this per room."""


class AgentProvider(Protocol):
    """A text model. Any OpenAI-compatible endpoint."""

    def phrase(self, system_prompt: str, user_prompt: str, timeout: float) -> str:
        """Return the message to post, or an empty string for 'say nothing'."""


class TranscriptionProvider(Protocol):
    """Turns an audio file into normalized segments."""

    def transcribe_file(self, path, mime_type: str, language: str): ...
