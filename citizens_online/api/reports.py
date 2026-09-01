# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report output and session lifecycle."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session as DbSession

from citizens_online.api.downloads import NO_STORE, download_headers
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import get_db, get_read_db
from citizens_online.security.identity import CurrentUser
from citizens_online.services import deliberation as delib
from citizens_online.services import report as report_svc
from citizens_online.services import settings as settings_svc
from citizens_online.services.audit import record_audit_event

router = APIRouter(tags=["reports"])
DB = Annotated[DbSession, Depends(get_db)]
ReadDB = Annotated[DbSession, Depends(get_read_db)]


def _report_for(db, session_obj, include_drafts: bool) -> dict:
    if session_obj.final_report_json and not include_drafts:
        try:
            return json.loads(session_obj.final_report_json)
        except ValueError:
            pass
    return report_svc.build_report(db, session_obj, include_drafts=include_drafts)


@router.get("/sessions/{session_id}/report")
def report(session_id: str, db: ReadDB, user: CurrentUser, include_drafts: bool = False):
    session_obj = delib.get_owned_session(db, session_id, user)
    return _report_for(db, session_obj, include_drafts)


@router.get("/sessions/{session_id}/report.md")
def report_markdown(session_id: str, db: ReadDB, user: CurrentUser, include_drafts: bool = False):
    session_obj = delib.get_owned_session(db, session_id, user)
    text = report_svc.render_markdown(_report_for(db, session_obj, include_drafts))
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers=download_headers(f"{session_obj.name[:60]}.md"),
    )


@router.get("/sessions/{session_id}/report.pdf")
def report_pdf(session_id: str, db: ReadDB, user: CurrentUser, include_drafts: bool = False):
    from citizens_online.services.report_pdf import render_pdf

    session_obj = delib.get_owned_session(db, session_id, user)
    data = _report_for(db, session_obj, include_drafts)
    organization = settings_svc.get_setting(settings_svc.default_store(), "organization_name")
    pdf = render_pdf(data, logo_path=None, organization_name=organization)
    return Response(
        content=pdf, media_type="application/pdf",
        headers=download_headers(f"{session_obj.name[:60]}.pdf"),
    )


@router.get("/sessions/{session_id}/report.json")
def report_json(session_id: str, db: ReadDB, user: CurrentUser, include_drafts: bool = False):
    session_obj = delib.get_owned_session(db, session_id, user)
    data = _report_for(db, session_obj, include_drafts)
    return Response(
        content=json.dumps(data, indent=2), media_type="application/json",
        headers={**download_headers(f"{session_obj.name[:60]}.json"), "Cache-Control": NO_STORE},
    )


@router.post("/sessions/{session_id}/close")
def close_session(session_id: str, db: DB, user: CurrentUser):
    """Freeze the report: reopening must not change what people already read."""
    session_obj = delib.get_owned_session(db, session_id, user)
    session_obj.closed_at = session_obj.closed_at or utcnow()
    session_obj.status = "COMPLETE"
    report_svc.freeze(db, session_obj)
    record_audit_event(db, "session_closed", "session", session_obj.id, user, {})
    return {"closed_at": session_obj.closed_at.isoformat()}


@router.delete("/sessions/{session_id}/close")
def reopen_session(session_id: str, db: DB, user: CurrentUser):
    session_obj = delib.get_owned_session(db, session_id, user)
    session_obj.closed_at = None
    session_obj.status = "REVIEW"
    record_audit_event(db, "session_reopened", "session", session_obj.id, user, {})
    return {"reopened": True}


@router.post("/sessions/{session_id}/report/publish")
def publish(session_id: str, db: DB, user: CurrentUser):
    session_obj = delib.get_owned_session(db, session_id, user)
    report_svc.freeze(db, session_obj)
    session_obj.report_published_at = utcnow()
    record_audit_event(db, "report_published", "session", session_obj.id, user, {})
    return {"published_at": session_obj.report_published_at.isoformat()}


@router.delete("/sessions/{session_id}/report/publish")
def unpublish(session_id: str, db: DB, user: CurrentUser):
    session_obj = delib.get_owned_session(db, session_id, user)
    session_obj.report_published_at = None
    record_audit_event(db, "report_unpublished", "session", session_obj.id, user, {})
    return {"published": False}
