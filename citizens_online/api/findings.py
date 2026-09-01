# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reviewing what the AI drafted.

Findings are drafts until a human says otherwise. An edit never overwrites the
model's original output — `original_json` keeps it for audit.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import Finding, Room
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import get_db, get_read_db
from citizens_online.security.identity import CurrentUser
from citizens_online.services import deliberation as delib
from citizens_online.services import settings as settings_svc
from citizens_online.services.audit import record_audit_event
from citizens_online.services.jobs import enqueue_job
from citizens_online.services.report import _evidence_for

router = APIRouter(tags=["findings"])
DB = Annotated[DbSession, Depends(get_db)]
ReadDB = Annotated[DbSession, Depends(get_read_db)]

VALID_STATUSES = ("DRAFT", "APPROVED", "REJECTED", "EDITED_AND_APPROVED")


def _payload(db: DbSession, finding: Finding, room_numbers: dict) -> dict:
    return {
        "id": finding.id,
        "scope": finding.scope,
        "type": finding.type,
        "title": finding.title,
        "summary": finding.summary,
        "support": finding.support,
        "status": finding.status,
        "room_number": room_numbers.get(finding.room_id or ""),
        "mentioned_room_count": finding.mentioned_room_count,
        "ai_model": finding.ai_model,
        "evidence_removed": finding.evidence_removed_at is not None,
        "evidence": _evidence_for(db, finding),
        "reviewed_by": finding.reviewed_by,
    }


@router.get("/rounds/{round_id}/findings")
def round_findings(round_id: str, db: ReadDB, user: CurrentUser):
    round_obj = delib.get_owned_round(db, round_id, user)
    room_numbers = {r.id: r.number for r in round_obj.rooms}
    findings = list(
        db.execute(select(Finding).where(Finding.round_id == round_id)).scalars()
    )
    return {
        "round": delib.round_payload(round_obj),
        "cross_room": [
            _payload(db, f, room_numbers) for f in findings if f.scope == "round"
        ],
        "rooms": [
            {
                "id": room.id,
                "number": room.number,
                "summary": room.analysis_summary,
                "findings": [
                    _payload(db, f, room_numbers)
                    for f in findings
                    if f.scope == "room" and f.room_id == room.id
                ],
            }
            for room in sorted(round_obj.rooms, key=lambda r: r.number)
        ],
    }


@router.put("/findings/{finding_id}")
def update_finding(finding_id: str, payload: dict, db: DB, user: CurrentUser):
    """PUT, not PATCH: the AppAPI proxy forwards no PATCH at all."""
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    delib.get_owned_session(db, finding.session_id, user)
    edited = False
    for field in ("title", "summary"):
        if payload.get(field) is not None and payload[field] != getattr(finding, field):
            setattr(finding, field, str(payload[field])[:2000])
            edited = True
    status = payload.get("status")
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status")
        finding.status = "EDITED_AND_APPROVED" if (edited and status == "APPROVED") else status
        finding.reviewed_by = user
        finding.reviewed_at = utcnow()
    elif edited:
        finding.status = "EDITED_AND_APPROVED" if finding.status in ("APPROVED", "EDITED_AND_APPROVED") else finding.status
        finding.reviewed_by = user
        finding.reviewed_at = utcnow()
    record_audit_event(
        db, "finding_reviewed", "finding", finding.id, user,
        {"status": finding.status, "edited": edited},
    )
    room_numbers = {}
    if finding.room_id:
        room = db.get(Room, finding.room_id)
        if room:
            room_numbers[room.id] = room.number
    return _payload(db, finding, room_numbers)


@router.post("/rounds/{round_id}/analyze")
def analyze(round_id: str, db: DB, user: CurrentUser, payload: dict | None = None):
    """Re-run the analysis for a finished round."""
    round_obj = delib.get_owned_round(db, round_id, user)
    snap = settings_svc.snapshot()
    if not snap["llm_enabled"] or not snap["llm_model"]:
        raise HTTPException(status_code=409, detail="No analysis model is configured")
    queued = 0
    for room in round_obj.rooms:
        enqueue_job(db, "ANALYZE_ROOM", {"room_id": room.id})
        queued += 1
    record_audit_event(db, "analysis_requested", "round", round_obj.id, user, {"rooms": queued})
    return {"queued": queued}
