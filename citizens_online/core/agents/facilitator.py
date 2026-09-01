# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facilitator's words.

The division of labour is deliberate (spec §14):

* the **engine** decides that something should be said, on what grounds, and
  writes the audit row with the rule, threshold and observed value;
* the **model** decides only how to phrase it;
* the **bot** delivers it.

The owner's decision for this build is that the model always phrases — there is
no templated fallback. The consequence is handled honestly: an intent that
cannot be phrased within its deadline is **dropped and logged as `missed`**,
never delayed. A "two minutes remain" that arrives with forty seconds left
would be worse than silence.
"""

import json
import time

import httpx

from citizens_online.core.speaking.policies import Intent
from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = """You are the facilitator of one small group in an online citizens' assembly.

You will be given a FACT SHEET describing something the facilitation engine has already decided to \
raise. **The decision to speak has already been made — do not second-guess it.** Your only job is to \
phrase it as a short message to the group.

Rules:
- Reply with the message text only. No preamble, no quotes, no markdown headings, no emoji.
- One or two sentences, at most 40 words. Plain, warm, neutral.
- Never invent facts, numbers or names beyond the fact sheet.
- Never take a side on the topic being discussed and never summarise their views.
- When the fact sheet names a person who has been dominating, address the group's balance rather \
than scolding the person.
- When the fact sheet names a person who has not spoken, invite them gently and leave them free to \
decline.
- Reply with exactly NO_REPLY only if the fact sheet is empty or self-contradictory. A fact sheet \
about speaking balance or remaining time always warrants a message.
- Write in {language}."""

KIND_BRIEFS = {
    "time_600": "Ten minutes remain in this round.",
    "time_300": "Five minutes remain in this round.",
    "time_120": "Two minutes remain in this round. It is a good moment to look for one point of "
    "agreement or to name what is still unresolved.",
    "share_warn": "One participant, {name}, has used about {share_percent}% of the group's speaking "
    "time so far. Encourage a more even balance without naming anyone as at fault.",
    "share_strong": "One participant, {name}, has used about {share_percent}% of the group's "
    "speaking time. Ask the group to make space for the other voices, and invite {name} to bring "
    "their current point to a close.",
    "silent_participant": "{name} has not spoken yet in this round. Invite them to contribute if "
    "they would like to, making clear they are free to pass.",
    "round_started": "The round has just started. Welcome the group in one sentence and state the "
    "question they are discussing: {question}",
    "round_ending": "The round has ended. Thank the group and tell them they will be taken back "
    "automatically.",
}


class FacilitatorAgent:
    """Turns an `Intent` into a sentence, or into nothing at all."""

    def __init__(self, base_url: str, api_key: str, model: str, language: str = "en"):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.language = language or "en"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def _brief(self, intent: Intent) -> str:
        template = KIND_BRIEFS.get(intent.kind, "")
        facts = dict(intent.facts)
        facts.setdefault("name", intent.subject_name)
        try:
            return template.format(**facts)
        except KeyError:
            return template

    def phrase(self, intent: Intent) -> tuple[str, dict]:
        """Return `(message, telemetry)`. An empty message means "say nothing"."""
        started = time.monotonic()
        telemetry = {
            "agent_type": "facilitator",
            "provider": "openai_compatible",
            "model": self.model,
            "intent_json": json.dumps(
                {
                    "kind": intent.kind,
                    "rule": intent.rule,
                    "threshold": intent.threshold,
                    "observed": intent.observed,
                    "facts": intent.facts,
                }
            ),
            "status": "sent",
            "output": "",
            "error": "",
            "latency_ms": 0,
        }
        if not self.configured:
            telemetry["status"] = "error"
            telemetry["error"] = "no language model configured"
            return "", telemetry

        brief = self._brief(intent)
        if not brief:
            telemetry["status"] = "no_reply"
            return "", telemetry

        system = SYSTEM_PROMPT.format(language=_language_name(self.language))
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": "FACT SHEET:\n" + brief},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 160,
                },
                timeout=httpx.Timeout(intent.deadline, connect=min(10.0, intent.deadline)),
            )
        except httpx.HTTPError as exc:
            # Deliberately dropped, not retried into irrelevance.
            telemetry["status"] = "missed"
            telemetry["error"] = f"{type(exc).__name__}: {exc}"[:300]
            telemetry["latency_ms"] = int((time.monotonic() - started) * 1000)
            log.warning("facilitator_missed", kind=intent.kind, error=telemetry["error"][:120])
            return "", telemetry

        telemetry["latency_ms"] = int((time.monotonic() - started) * 1000)
        if response.status_code != 200:
            telemetry["status"] = "error"
            telemetry["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
            return "", telemetry
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            telemetry["status"] = "error"
            telemetry["error"] = f"unexpected payload: {exc}"[:200]
            return "", telemetry

        message = _clean(content)
        if not message or message.upper().startswith("NO_REPLY"):
            telemetry["status"] = "no_reply"
            return "", telemetry
        telemetry["output"] = message
        return message, telemetry


def _clean(text: str) -> str:
    text = (text or "").strip()
    # models occasionally wrap a one-liner in quotes or a code fence
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.removeprefix("text").strip()
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text.strip()[:600]


LANGUAGE_NAMES = {
    "en": "English",
    "it": "Italian",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "nl": "Dutch",
    "pt": "Portuguese",
}


def _language_name(code: str) -> str:
    return LANGUAGE_NAMES.get((code or "en").lower(), "English")
