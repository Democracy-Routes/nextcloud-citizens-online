# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storing transcripts, from whichever source produced them.

Three sources feed the same table, and every segment records which one it was:

* `live`     — Vosk captions produced while the round was running;
* `postcall` — a more accurate pass over the captured audio, replacing `live`;
* `chat`     — messages typed in the breakout room, which are part of the
  deliberation too and make the analysis testable with no audio at all.

Because each browser captures one person, the speaker is known for every
segment rather than inferred.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import (
    Participant,
    Recording,
    Room,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from citizens_online.logging_setup import get_logger
from citizens_online.providers.transcription.base import NormalizedTranscript
from citizens_online.storage.paths import transcripts_dir

log = get_logger(__name__)

TRAILING_SEGMENT_SECONDS = 2.0


def store_transcript(
    db: DbSession,
    recording: Recording,
    normalized: NormalizedTranscript,
    origin: str = "live",
) -> Transcript:
    participant = db.get(Participant, recording.participant_id)
    speaker = participant.display_name if participant else ""

    existing = db.execute(
        select(Transcript).where(Transcript.recording_id == recording.id)
    ).scalar_one_or_none()
    if existing is not None:
        # findings that quoted the old segments must not silently lose their
        # quotes; mark them instead
        mark_evidence_removed(db, existing)
        db.delete(existing)
        db.flush()

    from citizens_online.config import get_settings

    root = get_settings().app_persistent_storage
    raw_dir = transcripts_dir(root) / recording.session_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{recording.id}.raw.json"
    try:
        raw_path.write_text(json.dumps(normalized.raw)[:8_000_000])
    except Exception:
        log.warning("transcript_raw_write_failed", recording_id=recording.id)

    transcript = Transcript(
        recording_id=recording.id,
        provider=normalized.provider,
        model=normalized.model,
        language=normalized.language,
        source="final" if origin == "postcall" else "live",
        raw_response_path=str(raw_path.relative_to(root)),
    )
    db.add(transcript)
    db.flush()

    for index, segment in enumerate(normalized.segments):
        row = TranscriptSegment(
            transcript_id=transcript.id,
            sequence=index,
            # the speaker is the person whose microphone this was
            speaker_label=speaker,
            participant_id=recording.participant_id,
            nc_user_id=participant.nc_user_id if participant else "",
            origin=origin,
            start_seconds=segment.start,
            end_seconds=segment.end,
            text=segment.text,
        )
        db.add(row)
        db.flush()
        for word_index, word in enumerate(segment.words or []):
            db.add(
                TranscriptWord(
                    segment_id=row.id,
                    sequence=word_index,
                    text=word.text[:200],
                    start_seconds=word.start,
                    end_seconds=word.end,
                )
            )
    db.flush()
    log.info(
        "transcript_stored",
        recording_id=recording.id,
        origin=origin,
        segments=len(normalized.segments),
    )
    return transcript


def mark_evidence_removed(db: DbSession, transcript: Transcript) -> None:
    from citizens_online.db.models import Finding, FindingEvidence
    from citizens_online.db.models.base import utcnow

    segment_ids = [s.id for s in transcript.segments]
    if not segment_ids:
        return
    findings = db.execute(
        select(Finding)
        .join(FindingEvidence, FindingEvidence.finding_id == Finding.id)
        .where(FindingEvidence.transcript_segment_id.in_(segment_ids))
    ).scalars()
    for finding in set(findings):
        finding.evidence_removed_at = utcnow()


def transcript_from_live_captions(data: dict) -> NormalizedTranscript:
    """A persisted caption session, in the same shape a provider would return."""
    from citizens_online.providers.transcription.base import NormalizedSegment, NormalizedWord

    lines = [line for line in (data.get("lines") or []) if (line.get("text") or "").strip()]
    segments = []
    for index, line in enumerate(lines):
        start = float(line.get("t") or 0.0)
        end = line.get("end")
        if end is None or float(end) <= start:
            end = (
                float(lines[index + 1].get("t"))
                if index + 1 < len(lines)
                else start + TRAILING_SEGMENT_SECONDS
            )
        segments.append(
            NormalizedSegment(
                speaker=line.get("speaker") or "",
                start=start,
                end=float(end),
                text=(line.get("text") or "").strip(),
                words=[
                    NormalizedWord(
                        text=(w.get("text") or "")[:200],
                        start=float(w.get("start") or 0.0),
                        end=float(w.get("end") or 0.0),
                    )
                    for w in (line.get("words") or [])
                ],
            )
        )
    return NormalizedTranscript(
        provider=data.get("provider", "live"),
        model=data.get("model", ""),
        language=data.get("language", ""),
        segments=segments,
        raw=data,
    )


def room_transcript_payload(db: DbSession, room: Room) -> dict:
    """Everything said in one room, in time order, with speakers."""
    recordings = list(
        db.execute(select(Recording).where(Recording.room_id == room.id)).scalars()
    )
    rows: list[dict] = []
    for recording in recordings:
        transcript = db.execute(
            select(Transcript).where(Transcript.recording_id == recording.id)
        ).scalar_one_or_none()
        if not transcript:
            continue
        for segment in transcript.segments:
            rows.append(
                {
                    "id": segment.id,
                    "speaker": segment.speaker_label,
                    "nc_user_id": segment.nc_user_id,
                    "start": segment.start_seconds,
                    "end": segment.end_seconds,
                    "text": segment.text,
                    "origin": segment.origin,
                }
            )
    rows.sort(key=lambda r: r["start"])
    return {"room_id": room.id, "room_number": room.number, "segments": rows}
