# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The heartbeat of a running deliberation.

Every few seconds, for each active round: refresh the clock, evaluate the
speaking policy per room, let the facilitator phrase whatever the policy raised,
and end the round when its deadline passes.

The tick is deliberately dumb and restartable. All authority lives in the
database — `Round.deadline_at` is the clock, `moderation_events` is the record
of what has already been said — so a restart mid-round picks up exactly where
it left off instead of repeating itself or losing the round.
"""

import time

from sqlalchemy import select

from citizens_online.core.agents.facilitator import FacilitatorAgent
from citizens_online.core.engine import rounds as engine_rounds
from citizens_online.core.speaking import policies
from citizens_online.db.models import AgentEvent, ModerationEvent, Round, SpeakingMetric
from citizens_online.db.models.base import utcnow
from citizens_online.db.session import session_scope
from citizens_online.infra.nextcloud import bot as bot_module
from citizens_online.logging_setup import get_logger
from citizens_online.services import settings as settings_svc

log = get_logger(__name__)

TICK_INTERVAL_SECONDS = 5.0

# One in-flight model request per room, and never more than this many rooms at
# once, so a slow endpoint cannot pile up work across a large assembly.
MAX_CONCURRENT_PHRASINGS = 4


def _sent_keys(db, round_id: str) -> set[str]:
    """Intents already voiced in this round, so nothing is said twice."""
    rows = db.execute(
        select(ModerationEvent.rule, ModerationEvent.room_id, ModerationEvent.participant_id,
               ModerationEvent.type)
        .where(ModerationEvent.round_id == round_id)
    ).all()
    return {f"{round_id}:{room}:{kind}:{participant or '-'}" for rule, room, participant, kind in rows}


def _metrics_for(db, round_obj: Round) -> dict[str, SpeakingMetric]:
    return {
        m.participant_id: m
        for m in db.execute(
            select(SpeakingMetric).where(SpeakingMetric.round_id == round_obj.id)
        ).scalars()
    }


def run_tick() -> int:
    """One pass over every active round. Returns how many messages were sent."""
    now = utcnow()
    # 1. Read the world and decide, holding the database only briefly.
    plans: list[tuple[str, list[policies.Intent]]] = []
    expired: list[str] = []
    snap = settings_svc.snapshot()
    with session_scope() as db:
        active = list(
            db.execute(select(Round).where(Round.status == "ACTIVE")).scalars()
        )
        for round_obj in active:
            if round_obj.deadline_at and round_obj.deadline_at <= now:
                expired.append(round_obj.id)
                continue
            session_obj = round_obj.session
            if not session_obj.facilitator_enabled or not snap["facilitator_enabled"]:
                continue
            metrics = _metrics_for(db, round_obj)
            people = {p.id: p for p in session_obj.participants}
            already = _sent_keys(db, round_obj.id)
            elapsed = int((now - round_obj.started_at).total_seconds()) if round_obj.started_at else 0
            remaining = int((round_obj.deadline_at - now).total_seconds()) if round_obj.deadline_at else None
            intents: list[policies.Intent] = []
            for room in round_obj.rooms:
                if not room.talk_token or room.status != "OPEN":
                    continue
                members = []
                for member in room.members:
                    person = people.get(member.participant_id)
                    metric = metrics.get(member.participant_id)
                    members.append(
                        {
                            "participant_id": member.participant_id,
                            "display_name": person.display_name if person else "",
                            "speaking_ms": metric.speaking_ms if metric else 0,
                            "current_turn_ms": metric.current_turn_ms if metric else 0,
                        }
                    )
                intents.extend(
                    policies.evaluate_room(
                        round_id=round_obj.id,
                        room_id=room.id,
                        room_token=room.talk_token,
                        members=members,
                        remaining_seconds=remaining,
                        elapsed_seconds=elapsed,
                        policy=session_obj.speaking_policy,
                        preset_name=session_obj.policy_preset or snap["policy_preset"],
                        already_sent=already,
                    )
                )
            if intents:
                plans.append((session_obj.language, intents))

    # 2. Phrase and deliver outside the transaction: these are network calls,
    #    and holding the write lock across them is the mistake this codebase
    #    has made three times before.
    sent = 0
    if plans:
        agent = FacilitatorAgent(
            base_url=snap["llm_base_url"],
            api_key=snap["llm_api_key"],
            model=snap["llm_model"],
        )
        delivered: list[tuple[policies.Intent, str, dict]] = []
        budget = MAX_CONCURRENT_PHRASINGS
        for language, intents in plans:
            agent.language = language
            # one message per room per tick: merge by taking the most urgent
            by_room: dict[str, policies.Intent] = {}
            for intent in intents:
                order = {"time": 0, "share": 1, "content": 2}
                current = by_room.get(intent.room_id)
                if current is None or order[intent.category] < order[current.category]:
                    by_room[intent.room_id] = intent
            for intent in by_room.values():
                if budget <= 0:
                    break
                budget -= 1
                message, telemetry = agent.phrase(intent)
                if message and bot_module.send(intent.room_token, message):
                    sent += 1
                elif message:
                    telemetry["status"] = "missed"
                    telemetry["error"] = "bot delivery failed"
                delivered.append((intent, message, telemetry))

        # 3. Record what happened — including what was deliberately not said.
        with session_scope() as db:
            for intent, message, telemetry in delivered:
                round_obj = db.get(Round, intent.round_id)
                if round_obj is None:
                    continue
                db.add(
                    AgentEvent(
                        session_id=round_obj.session_id,
                        round_id=intent.round_id,
                        room_id=intent.room_id,
                        agent_type="facilitator",
                        provider=telemetry["provider"],
                        model=telemetry["model"],
                        intent_json=telemetry["intent_json"],
                        output=telemetry["output"],
                        status=telemetry["status"],
                        latency_ms=telemetry["latency_ms"],
                        error=telemetry["error"],
                    )
                )
                if telemetry["status"] == "sent":
                    db.add(
                        ModerationEvent(
                            session_id=round_obj.session_id,
                            round_id=intent.round_id,
                            room_id=intent.room_id,
                            participant_id=intent.subject_participant_id,
                            type=intent.kind,
                            severity="info",
                            rule=intent.rule,
                            threshold=intent.threshold,
                            observed=intent.observed,
                            automatic=True,
                            action="facilitator_message",
                            message=message,
                        )
                    )

    # 4. Rounds whose clock ran out.
    for round_id in expired:
        try:
            with session_scope() as db:
                round_obj = db.get(Round, round_id)
                if round_obj is None or round_obj.status != "ACTIVE":
                    continue
                engine_rounds.end_round(
                    db,
                    round_obj,
                    actor="engine",
                    service_user=snap["talk_service_user"],
                    reason="deadline",
                )
        except Exception:
            log.error("round_auto_end_failed", round_id=round_id, exc_info=True)

    return sent


def tick_if_due(last_tick: float) -> float:
    """Called from the job runner loop; returns the new `last_tick`."""
    now = time.monotonic()
    if now - last_tick < TICK_INTERVAL_SECONDS:
        return last_tick
    try:
        run_tick()
    except Exception:
        log.error("engine_tick_failed", exc_info=True)
    return now
