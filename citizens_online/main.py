# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Citizens Online ExApp entry point."""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from nc_py_api import AsyncNextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers
from starlette.staticfiles import StaticFiles
from structlog.contextvars import bind_contextvars, clear_contextvars

from citizens_online.api.admin import router as admin_router
from citizens_online.api.capture import router as capture_router
from citizens_online.api.directory import router as directory_router
from citizens_online.api.findings import router as findings_router
from citizens_online.api.integrations import router as integrations_router
from citizens_online.api.me import router as me_router
from citizens_online.api.reports import router as reports_router
from citizens_online.api.rooms import router as rooms_router
from citizens_online.api.sessions import router as sessions_router
from citizens_online.api.system import router as system_router
from citizens_online.config import get_settings
from citizens_online.db.migrate import run_migrations
from citizens_online.db.session import configure_database, sqlite_url
from citizens_online.infra.nextcloud.bot import FACILITATOR_BOT
from citizens_online.jobs.runner import run_forever as jobs_run_forever
from citizens_online.logging_setup import get_logger, setup_logging
from citizens_online.services.audit import record_audit_event_standalone
from citizens_online.services.live_captions import LIVE_CAPTIONS
from citizens_online.storage.paths import db_path, ensure_storage_layout

log = get_logger(__name__)


class _RevalidatedStatic(StaticFiles):
    """Static assets that the browser must revalidate.

    AppAPI's proxy stamps `Cache-Control: private, max-age=3600` on any
    non-JSON response that sets none of its own, and the UI bundle is served
    from a URL that never changes. Without this, every deploy could serve the
    PREVIOUS build for an hour with no way for the browser to know.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    try:
        if enabled:
            await nc.ui.top_menu.register("citizens_online", "Citizens Online", "img/app.svg")
            # NC appends .js/.css to registered resource paths — pass them without extension
            await nc.ui.resources.set_script("top_menu", "citizens_online", "js/citizens-online-main")
            await nc.ui.resources.set_style("top_menu", "citizens_online", "css/citizens-online-main")
            record_audit_event_standalone("app_enabled")
            log.info("app_enabled")
        else:
            record_audit_event_standalone("app_disabled")
            log.info("app_disabled")
        # The facilitator bot registers/unregisters with Talk alongside the app.
        await FACILITATOR_BOT.enabled_handler(enabled, nc)
    except Exception as exc:
        log.error("enabled_handler_failed", enabled=enabled, exc_info=True)
        return str(exc)
    return ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_storage_layout(settings.app_persistent_storage)
    setup_logging(settings)
    # a deployment missing these starts up looking healthy while Talk calls and
    # at-rest encryption are quietly broken — say so loudly
    missing = settings.missing_required()
    if missing and not settings.auth_disabled():
        log.error("missing_required_environment", variables=missing)
    configure_database(sqlite_url(db_path(settings.app_persistent_storage)))
    run_migrations(sqlite_url(db_path(settings.app_persistent_storage)))
    # static dirs are mounted in create_app instead, with cache headers
    set_handlers(app, enabled_handler, map_app_static=False)
    stop_event = asyncio.Event()
    jobs_task = asyncio.create_task(jobs_run_forever(stop_event))
    LIVE_CAPTIONS.set_loop(asyncio.get_running_loop())
    log.info("app_started", version=settings.app_version, storage=str(settings.app_persistent_storage))
    yield
    stop_event.set()
    await LIVE_CAPTIONS.shutdown()
    await jobs_task
    log.info("app_stopping")


def create_app(with_auth: bool = True) -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    if with_auth:
        app.add_middleware(AppAPIAuthMiddleware)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        if request.url.path == "/heartbeat":
            return await call_next(request)
        clear_contextvars()
        bind_contextvars(request_id=uuid.uuid4().hex[:12])
        started = time.monotonic()
        response = await call_next(request)
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return response

    app.include_router(system_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(rooms_router, prefix="/api/v1")
    app.include_router(capture_router, prefix="/api/v1")
    app.include_router(findings_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(directory_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(integrations_router, prefix="/api/v1")

    root = Path(__file__).resolve().parent.parent
    # We mount these ourselves (set_handlers is told map_app_static=False) so
    # they carry a Cache-Control — see _RevalidatedStatic.
    for name in ("js", "css", "img", "l10n"):
        directory = root / name
        if directory.is_dir():
            app.mount(f"/{name}", _RevalidatedStatic(directory=directory), name=name)
    return app


_settings = get_settings()
_auth_disabled = _settings.auth_disabled()
if _settings.co_insecure_no_auth and not _auth_disabled:
    # a stray env var must never open up a real deployment
    log.error(
        "insecure_no_auth_ignored",
        reason="CO_INSECURE_NO_AUTH is only honored against a local Nextcloud",
        nextcloud_url=_settings.nextcloud_url,
    )
elif _auth_disabled:
    log.warning("AUTH DISABLED (CO_INSECURE_NO_AUTH) — browser-test mode only")
APP = create_app(with_auth=not _auth_disabled)


if __name__ == "__main__":
    run_app("citizens_online.main:APP", log_level="info")
