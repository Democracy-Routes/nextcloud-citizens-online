# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Speaking-time policy: the deterministic half of facilitation.

The engine decides *whether* something should be said and on what grounds; the
language model only decides *how to say it* (`core/agents/facilitator.py`).
Keeping the decision here is what makes every intervention auditable — each one
carries the rule, the threshold and the observed value (spec §28) — and what
keeps time management working when the model is slow.

Thresholds are the tuned presets from the Democracy Routes speaking-balance
moderator (`services/dr-video/server/moderation.js:88-110`), carried over.
"""

from dataclasses import dataclass, field

PRESETS = {
    "gentle": {
        "warn_share": 0.45,
        "strong_share": 0.58,
        "warn_streak_ms": 75_000,
        "strong_streak_ms": 120_000,
        "minimum_speech_ms": 90_000,
        "silent_after_ms": 300_000,
    },
    "strict": {
        "warn_share": 0.40,
        "strong_share": 0.52,
        "warn_streak_ms": 60_000,
        "strong_streak_ms": 90_000,
        "minimum_speech_ms": 70_000,
        "silent_after_ms": 240_000,
    },
}

# How long before the deadline the room is reminded, in seconds.
TIME_MARKS = (600, 300, 120)

# An intent that cannot be phrased within this many seconds is dropped, not
# delayed: "two minutes remain" arriving with forty seconds left is worse than
# silence.
DEADLINE_SECONDS = {"time": 15.0, "share": 20.0, "content": 45.0}


@dataclass
class Intent:
    """A decision the facilitator should voice."""

    kind: str
    room_id: str
    room_token: str
    round_id: str
    subject_participant_id: str | None = None
    subject_name: str = ""
    rule: str = ""
    threshold: float | None = None
    observed: float | None = None
    facts: dict = field(default_factory=dict)
    category: str = "content"

    @property
    def deadline(self) -> float:
        return DEADLINE_SECONDS.get(self.category, 45.0)

    def dedupe_key(self) -> str:
        return f"{self.round_id}:{self.room_id}:{self.kind}:{self.subject_participant_id or '-'}"


def preset(name: str) -> dict:
    return PRESETS.get(name, PRESETS["gentle"])


def evaluate_room(
    *,
    round_id: str,
    room_id: str,
    room_token: str,
    members: list[dict],
    remaining_seconds: int | None,
    elapsed_seconds: int,
    policy: str = "soft_balanced",
    preset_name: str = "gentle",
    already_sent: set[str] | None = None,
) -> list[Intent]:
    """Decide what, if anything, the facilitator should say in this room now.

    `members` are dicts with participant_id, display_name, speaking_ms,
    current_turn_ms and last_spoke_at_ms_ago (as produced by the metrics
    service). Returns at most a couple of intents; the caller merges them into
    one message so a room never receives two notes at once.
    """
    already_sent = already_sent or set()
    cfg = preset(preset_name)
    intents: list[Intent] = []

    # --- the clock: deterministic, and the one thing that must never slip ---
    if remaining_seconds is not None:
        for mark in TIME_MARKS:
            if remaining_seconds <= mark:
                intent = Intent(
                    kind=f"time_{mark}",
                    room_id=room_id,
                    room_token=room_token,
                    round_id=round_id,
                    rule="time_remaining",
                    threshold=float(mark),
                    observed=float(remaining_seconds),
                    category="time",
                    facts={"minutes_left": max(1, round(remaining_seconds / 60))},
                )
                if intent.dedupe_key() not in already_sent:
                    intents.append(intent)
                break

    if policy == "none" or not members:
        return intents

    total_ms = sum(m.get("speaking_ms", 0) for m in members)
    if total_ms >= cfg["minimum_speech_ms"]:
        # --- share: is one voice taking the room? ---
        loudest = max(members, key=lambda m: m.get("speaking_ms", 0))
        share = loudest.get("speaking_ms", 0) / total_ms if total_ms else 0.0
        streak = loudest.get("current_turn_ms", 0)
        kind = None
        if share >= cfg["strong_share"] or streak >= cfg["strong_streak_ms"]:
            kind, threshold = "share_strong", cfg["strong_share"]
        elif share >= cfg["warn_share"] or streak >= cfg["warn_streak_ms"]:
            kind, threshold = "share_warn", cfg["warn_share"]
        if kind:
            intent = Intent(
                kind=kind,
                room_id=room_id,
                room_token=room_token,
                round_id=round_id,
                subject_participant_id=loudest["participant_id"],
                subject_name=loudest.get("display_name", ""),
                rule="maximum_speaking_share",
                threshold=threshold,
                observed=round(share, 3),
                category="share",
                facts={"share_percent": round(share * 100), "name": loudest.get("display_name", "")},
            )
            if intent.dedupe_key() not in already_sent:
                intents.append(intent)

        # --- silence: is someone being left out? ---
        silent = [
            m
            for m in members
            if m.get("speaking_ms", 0) == 0 and elapsed_seconds * 1000 >= cfg["silent_after_ms"]
        ]
        if silent and len(silent) < len(members):
            person = silent[0]
            intent = Intent(
                kind="silent_participant",
                room_id=room_id,
                room_token=room_token,
                round_id=round_id,
                subject_participant_id=person["participant_id"],
                subject_name=person.get("display_name", ""),
                rule="participant_has_not_spoken",
                threshold=cfg["silent_after_ms"] / 1000,
                observed=float(elapsed_seconds),
                category="content",
                facts={"name": person.get("display_name", "")},
            )
            if intent.dedupe_key() not in already_sent:
                intents.append(intent)

    return intents
