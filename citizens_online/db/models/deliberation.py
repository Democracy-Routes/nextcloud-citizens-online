# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deliberation itself: sessions, rounds, participants and Talk rooms.

A *session* is one online assembly. It owns *rounds* (a question plus a
duration) and *participants* (references to Nextcloud users — never a copy of
the user database). Each round is executed in *rooms*, which are real Nextcloud
Talk breakout rooms of the session's parent conversation.
"""

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citizens_online.db.models.base import Base, TZDateTime, new_uuid, utcnow

SESSION_STATUSES = ("DRAFT", "READY", "ACTIVE", "PROCESSING", "REVIEW", "COMPLETE")
ROUND_STATUSES = ("NOT_STARTED", "ACTIVE", "ENDED", "PROCESSING", "READY_FOR_REVIEW")
PARTICIPANT_ROLES = ("participant", "moderator", "observer")


class Session(Base):
    """One online deliberation."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", index=True)
    created_by: Mapped[str] = mapped_column(String(64), index=True)
    # extra instructions appended to the analysis prompt for this session only
    analysis_instructions: Mapped[str] = mapped_column(Text, default="")
    # Talk conversation that owns the breakout rooms. Talk caps breakout rooms
    # at 20 per parent, so a large assembly gets several parents; rooms carry
    # their own parent_token and the engine hides the split.
    parent_token: Mapped[str] = mapped_column(String(64), default="")
    rooms_per_round: Mapped[int] = mapped_column(Integer, default=2)
    # facilitator configuration
    facilitator_enabled: Mapped[bool] = mapped_column(default=True)
    speaking_policy: Mapped[str] = mapped_column(String(24), default="soft_balanced")
    policy_preset: Mapped[str] = mapped_column(String(12), default="gentle")
    moderation_enabled: Mapped[bool] = mapped_column(default=True)
    capture_enabled: Mapped[bool] = mapped_column(default=True)
    audio_retention_days: Mapped[int] = mapped_column(Integer, default=0)
    # frozen once the session is closed, so what participants read cannot change
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    final_report_json: Mapped[str] = mapped_column(Text, default="")
    final_report_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    report_published_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    audio_purged_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    rounds: Mapped[list["Round"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Round.position"
    )
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=20)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED", index=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # the authoritative clock: survives a restart, so the engine re-arms timers
    deadline_at: Mapped[datetime | None] = mapped_column(TZDateTime(), index=True)
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    session: Mapped[Session] = relationship(back_populates="rounds")
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="round", cascade="all, delete-orphan", order_by="Room.number"
    )


class Participant(Base):
    """A Nextcloud user taking part. Only a reference is stored, never a copy."""

    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("session_id", "nc_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    nc_user_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default="participant")
    # the Nextcloud group they were imported from, if any. A snapshot: group
    # membership is not re-read, because consent and recordings attach to the
    # person, not to whoever happens to be in a group on the day.
    added_via_group: Mapped[str] = mapped_column(String(64), default="")
    # when this person was told the assembly exists; None means never
    invited_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # what this person agreed to, and when — see services/consent.py
    consent_json: Mapped[str] = mapped_column(Text, default="{}")
    consent_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    session: Mapped[Session] = relationship(back_populates="participants")


class Room(Base):
    """A Talk breakout room for one round."""

    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("round_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120), default="")
    # Talk conversation tokens: the breakout room and the parent it belongs to
    talk_token: Mapped[str] = mapped_column(String(64), default="", index=True)
    parent_token: Mapped[str] = mapped_column(String(64), default="")
    bot_enabled: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="PLANNED")
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    round: Mapped[Round] = relationship(back_populates="rooms")
    members: Mapped[list["RoomMember"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("round_id", "participant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    # Talk's own attendee id inside the breakout room, needed for permissions
    attendee_id: Mapped[int | None] = mapped_column(Integer)

    room: Mapped[Room] = relationship(back_populates="members")


class SpeakingMetric(Base):
    """Per participant, per round: measured from audio activity, never from
    transcript word counts."""

    __tablename__ = "speaking_metrics"
    __table_args__ = (UniqueConstraint("round_id", "participant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    speaking_ms: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    longest_turn_ms: Mapped[int] = mapped_column(Integer, default=0)
    current_turn_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_spoke_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class ModerationEvent(Base):
    """Every consequential automated decision, with the rule that produced it."""

    __tablename__ = "moderation_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"))
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(12), default="low")
    rule: Mapped[str] = mapped_column(String(64), default="")
    threshold: Mapped[float | None] = mapped_column(Float)
    observed: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    automatic: Mapped[bool] = mapped_column(default=True)
    action: Mapped[str] = mapped_column(String(32), default="none")
    message: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class AgentEvent(Base):
    """One LLM call: what it was asked, what came back, what it cost."""

    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"))
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    agent_type: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    intent_json: Mapped[str] = mapped_column(Text, default="{}")
    output: Mapped[str] = mapped_column(Text, default="")
    # sent | no_reply | missed | error — "missed" means the model did not answer
    # before the intent's deadline and the message was deliberately dropped
    status: Mapped[str] = mapped_column(String(12), default="sent", index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
