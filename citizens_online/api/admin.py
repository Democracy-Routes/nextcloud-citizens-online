# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrator settings.

The AppAPI ADMIN route regex is one line of defence; this module is the second.
It fails closed: if the group check cannot be made, nobody is an administrator.
"""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from nc_py_api import NextcloudApp
from nc_py_api.ex_app import nc_app

from citizens_online.logging_setup import get_logger
from citizens_online.security.identity import CurrentUser
from citizens_online.services import settings as settings_svc

log = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(nc: Annotated[NextcloudApp, Depends(nc_app)]) -> str:
    """`nc.users.get_user()` returns 401 for an ExApp, so the current user's
    groups come from OCS instead. Any failure is a refusal, never a pass."""
    user = nc.user
    if not user:
        raise HTTPException(status_code=401, detail="No authenticated Nextcloud user")
    try:
        data = nc.ocs("GET", "/ocs/v1.php/cloud/user")
        groups = data.get("groups") or []
    except Exception as exc:
        log.warning("admin_check_failed", user=user, error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Could not verify administrator rights") from exc
    if "admin" not in groups:
        raise HTTPException(status_code=403, detail="Administrator rights required")
    return user


AdminUser = Annotated[str, Depends(require_admin)]


def _store(nc: Annotated[NextcloudApp, Depends(nc_app)]) -> settings_svc.AppConfigStore:
    return settings_svc.AppConfigStore(nc)


Store = Annotated[settings_svc.AppConfigStore, Depends(_store)]


@router.get("/ping")
def ping(user: AdminUser):
    return {"ok": True, "user": user}


@router.get("/providers")
def get_providers(store: Store, user: AdminUser):
    return settings_svc.providers_summary(store)


@router.put("/providers")
def put_providers(payload: dict, store: Store, user: AdminUser):
    changed = settings_svc.set_settings(store, payload)
    log.info("settings_updated", user=user, fields=changed)  # names only, never values
    return settings_svc.providers_summary(store)


@router.post("/providers/test")
def test_provider(payload: dict, store: Store, user: AdminUser):
    """Try the configured endpoints and say plainly what happened."""
    target = payload.get("target", "llm")
    if target == "llm":
        base = payload.get("base_url") or settings_svc.get_setting(store, "llm_base_url")
        key = payload.get("api_key") or settings_svc.get_setting(store, "llm_api_key")
        model = payload.get("model") or settings_svc.get_setting(store, "llm_model")
        if not base or not model:
            return {"ok": False, "message": "Set a base URL and a model first."}
        try:
            r = httpx.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                    "max_tokens": 20,
                    "temperature": 0,
                },
                timeout=httpx.Timeout(60, connect=15),
            )
        except httpx.HTTPError as exc:
            return {"ok": False, "message": f"Could not reach the endpoint: {type(exc).__name__}"}
        if r.status_code != 200:
            return {"ok": False, "message": f"HTTP {r.status_code}: {r.text[:160]}"}
        try:
            content = r.json()["choices"][0]["message"]["content"].strip()[:60]
        except Exception:
            return {"ok": False, "message": "The endpoint answered in an unexpected shape."}
        return {"ok": True, "message": f"{model} answered: {content}"}

    if target == "vosk":
        url = payload.get("url") or settings_svc.get_setting(store, "vosk_url")
        if not url:
            return {"ok": False, "message": "Set the Vosk server URL first."}
        try:
            import asyncio

            import websockets

            async def probe():
                async with websockets.connect(url, open_timeout=10) as ws:
                    await ws.send('{"config": {"sample_rate": 16000}}')
                    await ws.send(b"\x00\x00" * 1600)
                    await ws.send('{"eof" : 1}')
                    return await asyncio.wait_for(ws.recv(), timeout=15)

            answer = asyncio.run(probe())
            return {"ok": True, "message": f"Vosk answered: {str(answer)[:80]}"}
        except Exception as exc:
            return {"ok": False, "message": f"Could not reach Vosk: {type(exc).__name__}: {exc}"[:200]}

    return {"ok": False, "message": f"Unknown target {target!r}"}
