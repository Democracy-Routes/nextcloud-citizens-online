# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The participant's own view of the deliberation."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.session import get_db, get_read_db
from citizens_online.security.identity import CurrentUser
from citizens_online.services import participation
from citizens_online.services.audit import record_audit_event

router = APIRouter(prefix="/me", tags=["participant"])
DB = Annotated[DbSession, Depends(get_db)]
ReadDB = Annotated[DbSession, Depends(get_read_db)]


@router.get("/session")
def my_session(db: ReadDB, user: CurrentUser):
    """One poll drives the whole participant screen."""
    return participation.participant_view(db, user)


@router.post("/consent")
def consent(payload: dict, db: DB, user: CurrentUser):
    state = participation.current_participation(db, user)
    if state is None:
        return {"accepted": False, "reason": "not a participant"}
    result = participation.record_consent(db, state["participant"], bool(payload.get("accepted")))
    record_audit_event(
        db, "consent_recorded", "participant", state["participant"].id, user,
        {"accepted": result["accepted"]},
    )
    return result
