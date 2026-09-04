# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrator settings, stored in Nextcloud's AppConfig.

Secrets live in Nextcloud (flagged `sensitive`), never in this app's database
and never in the repository. Reads are OCS round-trips, so hot paths take a
short-lived cached snapshot instead — and no read may happen inside an open
database transaction (see `tests/unit/test_no_config_reads_in_transaction.py`).
"""

import ipaddress
import time
from typing import Protocol
from urllib.parse import urlparse

from citizens_online.logging_setup import get_logger

log = get_logger(__name__)

# Keys stored encrypted by Nextcloud and never returned to the browser.
KEY_FIELDS = ("llm_api_key", "stt_api_key")

DEFAULTS: dict[str, str] = {
    # --- speech to text (live captions + final transcript) ---
    "stt_provider": "vosk",          # vosk | whisper | mistral | deepgram | none
    "stt_live_enabled": "1",
    "stt_batch_enabled": "1",
    "vosk_url": "ws://citizens-vosk:2700",
    "vosk_language_models": "en=/models/vosk-model-small-en-us-0.15,it=/models/vosk-model-small-it-0.22",
    "vosk_live_model": "",
    "vosk_batch_model": "",
    "whisper_base_url": "",
    "whisper_batch_model": "whisper-1",
    "mistral_batch_model": "voxtral-mini-latest",
    "mistral_live_url": "wss://api.mistral.ai/v1/audio/transcriptions/realtime",
    "mistral_live_model": "voxtral-mini-transcribe-realtime-2602",
    # --- the language model behind the facilitator and the analysis ---
    "llm_base_url": "https://ollama.com/v1",
    "llm_model": "glm-5.2:cloud",
    "llm_enabled": "1",
    "analysis_extra_instructions": "",
    # --- facilitation ---
    "facilitator_enabled": "1",
    "policy_preset": "gentle",
    "moderation_enabled": "1",
    # --- housekeeping ---
    "organization_name": "",
    "audio_retention_days": "0",
    "talk_service_user": "citizens-online",
}

# Endpoints that decide whether audio/text leaves the building.
HOSTED_STT = {"deepgram", "mistral"}

_SNAPSHOT_TTL = 30.0
_snapshot: tuple[float, dict] | None = None


class ConfigStore(Protocol):
    def get_value(self, key: str) -> str | None: ...

    def get_values(self, keys: list[str]) -> dict[str, str]: ...

    def set_value(self, key: str, value: str, sensitive: bool = False) -> None: ...

    def delete_value(self, key: str) -> None: ...


class AppConfigStore:
    """Nextcloud AppConfigEx-backed store (values scoped to this ExApp)."""

    def __init__(self, nc):
        self._nc = nc

    def get_value(self, key: str) -> str | None:
        return self._nc.appconfig_ex.get_value(key)

    def get_values(self, keys: list[str]) -> dict[str, str]:
        """One round-trip for the whole snapshot instead of one per key.

        The engine ticks every five seconds; fifteen separate OCS calls per
        refresh was most of this app's chatter with Nextcloud.
        """
        try:
            records = self._nc.appconfig_ex.get_values(keys)
        except Exception as exc:
            log.warning("settings_bulk_read_failed", error=str(exc)[:200])
            return {}
        return {r.key: r.value for r in records if r.value is not None}

    def set_value(self, key: str, value: str, sensitive: bool = False) -> None:
        self._nc.appconfig_ex.set_value(key, value, sensitive=sensitive)

    def delete_value(self, key: str) -> None:
        self._nc.appconfig_ex.delete(key)


_background_store: AppConfigStore | None = None


def default_store() -> AppConfigStore:
    """Store for non-request contexts (jobs, the engine tick).

    Built once and reused: every new nc_py_api client fetches
    /cloud/capabilities, which doubles the round-trips on the tick path.
    """
    global _background_store
    if _background_store is None:
        from nc_py_api import NextcloudApp

        _background_store = AppConfigStore(NextcloudApp())
    return _background_store


def get_setting(store: ConfigStore, key: str) -> str:
    try:
        value = store.get_value(key)
    except Exception as exc:
        log.warning("setting_read_failed", key=key, error=str(exc)[:200])
        value = None
    if value is None or value == "":
        return DEFAULTS.get(key, "")
    return value


def set_settings(store: ConfigStore, values: dict[str, str]) -> list[str]:
    """Write settings; returns the names that changed — never the values."""
    changed = []
    for key, value in values.items():
        if key not in DEFAULTS and key not in KEY_FIELDS:
            continue
        sensitive = key in KEY_FIELDS
        if sensitive and value == "":
            # an empty secret means "forget it", not "store an empty string"
            store.delete_value(key)
        else:
            store.set_value(key, str(value), sensitive=sensitive)
        changed.append(key)
    invalidate_snapshot()
    return changed


def key_hint(store: ConfigStore, key: str) -> str:
    value = ""
    try:
        value = store.get_value(key) or ""
    except Exception:
        pass
    return f"…{value[-4:]}" if len(value) >= 8 else ("…" if value else "")


def invalidate_snapshot() -> None:
    global _snapshot
    _snapshot = None


def snapshot() -> dict:
    """Everything the hot paths need, refreshed at most every 30 seconds."""
    global _snapshot
    now = time.monotonic()
    if _snapshot and now - _snapshot[0] < _SNAPSHOT_TTL:
        return _snapshot[1]
    wanted = [
        "stt_provider", "stt_live_enabled", "stt_batch_enabled", "vosk_url",
        "vosk_language_models", "vosk_live_model", "whisper_base_url",
        "llm_base_url", "llm_model", "llm_enabled", "llm_api_key", "stt_api_key",
        "facilitator_enabled", "policy_preset", "moderation_enabled",
        "talk_service_user", "audio_retention_days",
    ]
    store = default_store()
    raw = store.get_values(wanted)

    def value(key: str) -> str:
        got = raw.get(key)
        return got if got not in (None, "") else DEFAULTS.get(key, "")

    data = {key: value(key) for key in wanted}
    for flag in (
        "stt_live_enabled", "stt_batch_enabled", "llm_enabled",
        "facilitator_enabled", "moderation_enabled",
    ):
        data[flag] = data[flag] == "1"
    try:
        data["audio_retention_days"] = int(data["audio_retention_days"] or 0)
    except ValueError:
        data["audio_retention_days"] = 0
    _snapshot = (now, data)
    return data


def vosk_model_for(store_or_snapshot, language: str) -> str:
    """Server-side model path for a language, from `vosk_language_models`
    (`en=/models/...,it=/models/...`). Empty means "the server's default"."""
    raw = (
        store_or_snapshot.get("vosk_language_models", "")
        if isinstance(store_or_snapshot, dict)
        else get_setting(store_or_snapshot, "vosk_language_models")
    )
    for pair in raw.split(","):
        if "=" in pair:
            lang, path = pair.split("=", 1)
            if lang.strip().lower() == (language or "en").lower():
                return path.strip()
    return ""


def _is_local_endpoint(url: str) -> bool:
    if not url:
        return True
    host = (urlparse(url).hostname or "").lower()
    if not host or host in ("localhost", "127.0.0.1", "::1") or "." not in host:
        return True
    if host.endswith((".local", ".internal", ".home.arpa")):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False


def stt_is_hosted(snap: dict) -> bool:
    provider = snap.get("stt_provider", "")
    if provider in HOSTED_STT:
        return True
    if provider == "vosk":
        return not _is_local_endpoint(snap.get("vosk_url", ""))
    if provider == "whisper":
        return not _is_local_endpoint(snap.get("whisper_base_url", ""))
    return provider not in ("none", "")


def data_handling_summary() -> dict:
    """What a participant is told before anything is recorded.

    Generated from the live configuration so the consent notice cannot drift
    away from what the app actually does (spec §27).
    """
    try:
        snap = snapshot()
        return {
            "stt_provider": snap["stt_provider"],
            "stt_enabled": snap["stt_provider"] not in ("none", ""),
            "stt_hosted": stt_is_hosted(snap),
            "analysis_enabled": snap["llm_enabled"],
            "analysis_hosted": snap["llm_enabled"] and not _is_local_endpoint(snap["llm_base_url"]),
            "analysis_endpoint_host": urlparse(snap["llm_base_url"]).hostname or "",
            "facilitator_enabled": snap["facilitator_enabled"],
            # No "moderation_enabled" here on purpose. The setting exists and
            # defaults to on, but nothing in this app classifies transcripts for
            # abusive language — core/agents/moderation.py was planned and never
            # written. A consent notice must not describe processing that does
            # not happen, so the claim is withheld until the feature exists.
            "audio_retention_days": snap["audio_retention_days"],
        }
    except Exception:
        # say nothing rather than something reassuring and wrong
        log.warning("data_handling_summary_failed", exc_info=True)
        return {}


def providers_summary(store: ConfigStore) -> dict:
    """Admin view: every setting, with secrets reduced to a hint."""
    out = {k: get_setting(store, k) for k in DEFAULTS}
    for key in KEY_FIELDS:
        out[key + "_hint"] = key_hint(store, key)
        out[key + "_set"] = bool(key_hint(store, key))
    return out
