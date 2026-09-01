# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-participant capture sessions, recordings and audio chunks.

Online, one browser records one person, so a recording is keyed to a
participant rather than to a table, and the speaker of every resulting
transcript segment is known rather than inferred.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citizens_online.db.models.base import Base, TZDateTime, new_uuid, utcnow

RECORDING_STATES = (
    "CREATED",
    "RECORDING",
    "FINALIZING",
    "WAITING_FOR_CHUNKS",
    "ASSEMBLING",
    "AUDIO_READY",
    "TRANSCRIBING",
    "TRANSCRIBED",
    "ANALYZING",
    "READY_FOR_REVIEW",
    "REVIEWED",
    # error states
    "UPLOAD_INCOMPLETE",
    "AUDIO_INVALID",
    "TRANSCRIPTION_FAILED",
    "ANALYSIS_FAILED",
)


class CaptureSession(Base):
    """A participant's browser capturing their own microphone for one round.

    Replaces Citizens' invite-based recorder session: identity comes from the
    authenticated Nextcloud user, so there is no bearer token to mint.
    """

    __tablename__ = "capture_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    nc_user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # latest browser-reported health (heartbeat payload), for the live dashboard
    last_status_json: Mapped[str] = mapped_column(Text, default="{}")
    last_status_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("round_id", "participant_id", "attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    # a participant who reconnects mid-round gets a second recording rather
    # than a 409, so a dropped connection never costs the rest of the round
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    capture_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("capture_sessions.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    mime_type: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    total_chunks: Mapped[int | None] = mapped_column(Integer)
    received_chunks: Mapped[int] = mapped_column(Integer, default=0)
    canonical_audio_path: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float | None] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64), default="")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    audio_deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["AudioChunk"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan", order_by="AudioChunk.sequence_number"
    )


class AudioChunk(Base):
    __tablename__ = "audio_chunks"
    __table_args__ = (UniqueConstraint("recording_id", "sequence_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    recording_id: Mapped[str] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    recording: Mapped[Recording] = relationship(back_populates="chunks")
