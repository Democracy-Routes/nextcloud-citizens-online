# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time-based work the event-driven queue cannot express.

Two things are true only after a while: an upload that has stopped making
progress, and audio that has outlived its retention. Both are checked on a
fixed interval, each guarded so one failure cannot silence the other.
"""

from datetime import timedelta

from sqlalchemy import select

from citizens_online.db.models import Recording, Session
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import session_scope
from citizens_online.logging_setup import get_logger
from citizens_online.services import settings as settings_svc
from citizens_online.services.audit import record_audit_event
from citizens_online.services.recording_states import transition

log = get_logger(__name__)

SWEEP_INTERVAL_SECONDS = 60.0
STALLED_UPLOAD_MINUTES = 10


def sweep_stalled_uploads() -> int:
    """A browser that stopped uploading is marked, reversibly: if it comes back
    the chunks are still accepted and the recording resumes."""
    cutoff = utcnow() - timedelta(minutes=STALLED_UPLOAD_MINUTES)
    stalled = 0
    with session_scope() as db:
        rows = db.execute(
            select(Recording).where(
                Recording.state.in_(("WAITING_FOR_CHUNKS", "RECORDING", "FINALIZING")),
                Recording.updated_at < cutoff,
            )
        ).scalars().all()
        for recording in rows:
            recording.error_code = "UPLOAD_TIMED_OUT"
            try:
                transition(recording, "UPLOAD_INCOMPLETE")
            except Exception:
                recording.state = "UPLOAD_INCOMPLETE"
            stalled += 1
            log.info("upload_abandoned", recording_id=recording.id)
    return stalled


def sweep_expired_audio() -> int:
    """Delete the audio, keep the record of the deliberation, log the purge."""
    # read config OUTSIDE any transaction: it is an OCS call to Nextcloud
    default_days = settings_svc.snapshot()["audio_retention_days"]
    purged = 0
    with session_scope() as db:
        sessions = db.execute(
            select(Session).where(Session.closed_at.isnot(None), Session.audio_purged_at.is_(None))
        ).scalars().all()
        for session_obj in sessions:
            days = session_obj.audio_retention_days or default_days
            if days <= 0 or not session_obj.closed_at:
                continue
            if utcnow() - session_obj.closed_at < timedelta(days=days):
                continue
            freed = _purge_audio(db, session_obj)
            session_obj.audio_purged_at = utcnow()
            record_audit_event(
                db, "audio_retention_purge", "session", session_obj.id, "system",
                {"recordings": freed, "retention_days": days},
            )
            purged += freed
    return purged


def _purge_audio(db, session_obj: Session) -> int:
    from citizens_online.config import get_settings

    root = get_settings().app_persistent_storage
    count = 0
    for recording in db.execute(
        select(Recording).where(
            Recording.session_id == session_obj.id, Recording.audio_deleted_at.is_(None)
        )
    ).scalars():
        if recording.canonical_audio_path:
            path = root / recording.canonical_audio_path
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("audio_purge_failed", recording_id=recording.id)
                continue
        recording.audio_deleted_at = utcnow()
        recording.canonical_audio_path = ""
        count += 1
    return count


def run_sweeps() -> None:
    for name, fn in (("stalled_uploads", sweep_stalled_uploads), ("expired_audio", sweep_expired_audio)):
        try:
            fn()
        except Exception:
            log.error("sweep_failed", sweep=name, exc_info=True)
