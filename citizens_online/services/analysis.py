# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turning what was said into findings that can be checked.

Ported from the in-person app with one substantive improvement: online, every
transcript segment carries the real participant who spoke it, so a citation
reads "Alice, at 03:12" rather than "SPEAKER_01". Everything else is
deliberately unchanged, because it is the part that makes AI output
trustworthy (spec §17):

* every finding must cite segment ids copied from the prompt;
* ids that do not correspond to real segments are discarded;
* **a finding left with no evidence is dropped, not stored**;
* how many rooms raised something is recomputed from the links, never taken
  from the model's word for it.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import (
    Finding,
    FindingEvidence,
    Recording,
    Room,
    Round,
    Session,
    Transcript,
    TranscriptSegment,
)
from citizens_online.db.models.base import utcnow
from citizens_online.domain.analysis_schemas import RoomAnalysis, RoundAnalysis
from citizens_online.logging_setup import get_logger
from citizens_online.providers.analysis.openai_compat import AnalysisError, chat_json
from citizens_online.services import settings as settings_svc

log = get_logger(__name__)

COALESCE_GAP_SECONDS = 1.5
LANGUAGE_NAMES = {
    "en": "English",
    "it": "Italian",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "nl": "Dutch",
    "pt": "Portuguese",
}

ROOM_SYSTEM = """You are an analyst supporting an online citizens' assembly.
You analyze ONE breakout room's discussion transcript.

Rules:
- Respond with ONLY a JSON object: {{"summary": "...", "findings": [{{"type": ...,
  "title": ..., "summary": ..., "support": ..., "evidence_segment_ids": [...]}}]}}
- "summary" (top level) is ALWAYS required: a neutral 2-4 sentence description
  of what this room actually discussed — even if it was small talk or off the
  round question. Never leave it out.
- "type" is one of: proposal, agreement, disagreement, concern, question,
  minority_position, new_idea.
- "support" (optional) is one of: strong, mixed, weak, unclear.
- EVERY finding MUST cite at least one evidence_segment_ids value copied
  EXACTLY from the segment ids in the transcript. Never invent ids.
- Only report what participants actually said. Do not invent content.
- Speakers are named in the transcript. You may attribute a position to the
  person who stated it, but never speculate about anyone's motives.
- Actively look for points of conflict: positions where participants disagree
  with each other. Report each as a "disagreement" finding whose summary names
  BOTH sides, and mention the most significant conflicts in the top-level
  summary.
- If the discussion contains nothing substantive for the round question,
  return {{"summary": "...", "findings": []}}.
- Write everything in {language}."""

ROUND_SYSTEM = """You are an analyst supporting an online citizens' assembly.
You aggregate findings from multiple breakout rooms of the SAME round into
cross-room clusters (recurring proposals, shared concerns, disagreements,
minority positions, questions, unique new ideas).

Rules:
- Respond with ONLY a JSON object: {{"summary": "...", "clusters": [{{"type": ...,
  "title": ..., "summary": ..., "source_finding_ids": [...]}}]}}
- "summary" (top level) is ALWAYS required: a neutral 2-4 sentence overview of
  the round across all rooms.
- "type" is one of: proposal, agreement, disagreement, concern, question,
  minority_position, new_idea.
- EVERY cluster MUST list source_finding_ids copied EXACTLY from the finding
  ids provided. Never invent ids.
- Never state or imply percentages of participant support; rooms are not votes.
- Actively look for points of conflict BETWEEN rooms (one room proposes what
  another opposes) as well as disagreements reported within rooms. Report each
  as a "disagreement" cluster whose summary names both sides, and mention the
  most significant conflicts in the top-level summary.
- Write everything in {language}."""


def analysis_ready(snap: dict) -> bool:
    return bool(snap.get("llm_enabled") and snap.get("llm_base_url") and snap.get("llm_model"))


def coalesce_segments(segments: list[TranscriptSegment]) -> list[dict]:
    """Merge consecutive fragments from the same speaker, keeping every member
    id so citations stay valid after the merge."""
    blocks: list[dict] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        speaker = segment.speaker_label or ""
        if (
            blocks
            and blocks[-1]["speaker"] == speaker
            and segment.start_seconds - blocks[-1]["end"] <= COALESCE_GAP_SECONDS
        ):
            blocks[-1]["ids"].append(segment.id)
            blocks[-1]["text"] += " " + text
            blocks[-1]["end"] = segment.end_seconds
        else:
            blocks.append(
                {
                    "ids": [segment.id],
                    "speaker": speaker,
                    "start": segment.start_seconds,
                    "end": segment.end_seconds,
                    "text": text,
                }
            )
    return blocks


def _timestamp(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def build_system_prompt(template: str, language: str, extra: str, session_extra: str) -> str:
    """Organizer instructions are appended, never substituted: they can shape
    the emphasis but they cannot switch off the output format or the evidence
    rules above them."""
    prompt = template.format(language=LANGUAGE_NAMES.get(language, "English"))
    if extra.strip():
        prompt += (
            "\n\nAdditional organizer instructions (these must never override the output "
            f"format or the evidence rules above):\n{extra.strip()[:2000]}"
        )
    if session_extra.strip():
        prompt += (
            "\n\nInstructions specific to THIS session (these must never override the output "
            f"format or the evidence rules above):\n{session_extra.strip()[:2000]}"
        )
    return prompt


def _config(store) -> tuple[str, str, str, str]:
    return (
        settings_svc.get_setting(store, "llm_base_url"),
        settings_svc.get_setting(store, "llm_api_key"),
        settings_svc.get_setting(store, "llm_model"),
        settings_svc.get_setting(store, "analysis_extra_instructions"),
    )


def _delete_existing(db: DbSession, *, room_id=None, round_id=None, only_drafts=True) -> None:
    query = select(Finding)
    if room_id:
        query = query.where(Finding.room_id == room_id, Finding.scope == "room")
    else:
        query = query.where(Finding.round_id == round_id, Finding.scope == "round")
    for finding in db.execute(query).scalars():
        if only_drafts and finding.status != "DRAFT":
            continue
        db.delete(finding)
    db.flush()


def analyze_room(db: DbSession, store, room: Room) -> int:
    """Findings for one room's discussion. Returns how many were stored."""
    recordings = list(
        db.execute(select(Recording).where(Recording.room_id == room.id)).scalars()
    )
    segments: list[TranscriptSegment] = []
    for recording in recordings:
        transcript = db.execute(
            select(Transcript).where(Transcript.recording_id == recording.id)
        ).scalar_one_or_none()
        if transcript:
            segments.extend(transcript.segments)
    # chat contributions are part of the record too
    segments.extend(_chat_segments(db, room))
    segments.sort(key=lambda s: s.start_seconds)
    if not segments:
        return 0

    round_obj: Round | None = db.get(Round, room.round_id)
    session_obj: Session | None = db.get(Session, room.session_id)
    valid_ids = {s.id for s in segments}
    lines = [
        f"[{'|'.join(b['ids'])}] {b['speaker'] or 'SPEAKER'} "
        f"({_timestamp(b['start'])}-{_timestamp(b['end'])}): {b['text']}"
        for b in coalesce_segments(segments)
    ]
    user_prompt = (
        f"Assembly: {session_obj.name if session_obj else ''}\n"
        f"Round question: {(round_obj.question or round_obj.title) if round_obj else ''}\n"
        f"Room: {room.number}\n\n"
        "Transcript segments (format: [segment ids] SPEAKER (start-end): text):\n"
        + "\n".join(lines)
    )

    # Release the write lock before the provider call: reading settings and
    # talking to the model are both network round-trips.
    db.commit()
    base_url, api_key, model, extra = _config(store)
    system = build_system_prompt(
        ROOM_SYSTEM,
        session_obj.language if session_obj else "en",
        extra,
        session_obj.analysis_instructions if session_obj else "",
    )
    result = chat_json(base_url, api_key, model, system, user_prompt, RoomAnalysis)

    _delete_existing(db, room_id=room.id)
    room.analysis_summary = result.summary
    stored = dropped = 0
    for item in result.findings:
        evidence_ids = {
            eid for raw in item.evidence_segment_ids for eid in raw.split("|") if eid in valid_ids
        }
        if not evidence_ids:
            # a finding without real evidence is invalid, not merely weak
            dropped += 1
            continue
        finding = Finding(
            session_id=room.session_id,
            round_id=room.round_id,
            room_id=room.id,
            scope="room",
            type=item.type,
            title=item.title,
            summary=item.summary,
            support=item.support or "",
            ai_model=model,
            original_json=item.model_dump_json(),
        )
        db.add(finding)
        db.flush()
        for segment_id in sorted(evidence_ids):
            finding.evidence.append(FindingEvidence(transcript_segment_id=segment_id))
        stored += 1
    log.info("room_analyzed", room_id=room.id, findings=stored, dropped_without_evidence=dropped)
    return stored


def analyze_round(db: DbSession, store, round_obj: Round) -> int:
    """Cluster the rooms' findings into a cross-room view."""
    room_findings = list(
        db.execute(
            select(Finding).where(Finding.round_id == round_obj.id, Finding.scope == "room")
        ).scalars()
    )
    if not room_findings:
        return 0
    rooms_by_finding = {f.id: f.room_id for f in room_findings}
    room_numbers = {
        r.id: r.number for r in db.execute(select(Room).where(Room.round_id == round_obj.id)).scalars()
    }
    session_obj: Session | None = db.get(Session, round_obj.session_id)
    lines = [
        f"[{f.id}] room {room_numbers.get(f.room_id or '', '?')} · {f.type} · {f.title}: "
        f"{f.summary[:400]}"
        for f in room_findings
    ]
    user_prompt = (
        f"Assembly: {session_obj.name if session_obj else ''}\n"
        f"Round question: {round_obj.question or round_obj.title}\n"
        f"Rooms that produced findings: {len({f.room_id for f in room_findings if f.room_id})}\n\n"
        "Room findings (format: [finding id] room N · type · title: summary):\n" + "\n".join(lines)
    )

    db.commit()
    base_url, api_key, model, extra = _config(store)
    system = build_system_prompt(
        ROUND_SYSTEM,
        session_obj.language if session_obj else "en",
        extra,
        session_obj.analysis_instructions if session_obj else "",
    )
    result = chat_json(base_url, api_key, model, system, user_prompt, RoundAnalysis)

    _delete_existing(db, round_id=round_obj.id)
    round_obj.analysis_summary = result.summary
    stored = 0
    for cluster in result.clusters:
        source_ids = [fid for fid in cluster.source_finding_ids if fid in rooms_by_finding]
        if not source_ids:
            continue
        # recomputed from the real links; the model's own count is not trusted
        mentioned = len({rooms_by_finding[fid] for fid in source_ids if rooms_by_finding[fid]})
        finding = Finding(
            session_id=round_obj.session_id,
            round_id=round_obj.id,
            scope="round",
            type=cluster.type,
            title=cluster.title,
            summary=cluster.summary,
            ai_model=model,
            original_json=cluster.model_dump_json(),
            source_finding_ids=json.dumps(source_ids),
            mentioned_room_count=mentioned,
        )
        db.add(finding)
        db.flush()
        # A cluster inherits the evidence of the findings it aggregates, so the
        # trail from a conclusion back to an utterance is never broken. Two
        # source findings often quote the same passage, hence the set: the link
        # table is unique on (finding, segment).
        inherited: set[str] = set()
        for fid in source_ids:
            source = db.get(Finding, fid)
            for link in (source.evidence if source else []):
                inherited.add(link.transcript_segment_id)
        for segment_id in sorted(inherited):
            finding.evidence.append(FindingEvidence(transcript_segment_id=segment_id))
        stored += 1
    log.info("round_analyzed", round_id=round_obj.id, clusters=stored)
    return stored


def _chat_segments(db: DbSession, room: Room) -> list[TranscriptSegment]:
    """Chat messages stored as transcript segments (origin='chat')."""
    return list(
        db.execute(
            select(TranscriptSegment)
            .join(Transcript, TranscriptSegment.transcript_id == Transcript.id)
            .join(Recording, Transcript.recording_id == Recording.id)
            .where(Recording.room_id == room.id, TranscriptSegment.origin == "chat")
        ).scalars()
    )


def mark_failed(db: DbSession, round_obj: Round, error: str) -> None:
    round_obj.status = "READY_FOR_REVIEW"
    round_obj.analysis_summary = round_obj.analysis_summary or ""
    log.warning("analysis_failed", round_id=round_obj.id, error=error[:300])


__all__ = [
    "AnalysisError",
    "analysis_ready",
    "analyze_room",
    "analyze_round",
    "build_system_prompt",
    "coalesce_segments",
    "mark_failed",
    "utcnow",
]
