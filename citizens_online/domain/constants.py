# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Values the API is allowed to accept.

These exist so a request can be refused at the edge instead of being stored and
then quietly ignored deeper down. An unrecognised language used to reach the
speech engine and the Vosk model lookup verbatim, and an unrecognised
facilitation preset silently fell back to `gentle` — both of which produce a
session that behaves differently from what it says it is.

`tests/unit/test_constants.py` asserts these stay in step with the richer
mappings that consume them (`services.analysis.LANGUAGE_NAMES` and
`core.speaking.policies.PRESETS`), so adding one there without adding it here is
a test failure rather than a silent divergence.
"""

from typing import Literal

SUPPORTED_LANGUAGES = ("en", "it", "de", "fr", "es", "nl", "pt")
POLICY_PRESETS = ("gentle", "strict")
SPEAKING_POLICIES = ("soft_balanced", "none")

Language = Literal["en", "it", "de", "fr", "es", "nl", "pt"]
PolicyPreset = Literal["gentle", "strict"]
SpeakingPolicy = Literal["soft_balanced", "none"]
