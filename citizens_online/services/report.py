# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report: what the assembly produced, and where every claim came from.

Two rules shape this module, both inherited from the in-person app because they
are what make an AI-assisted civic output defensible:

* an approved finding and an AI draft are never presented as the same thing;
* every finding carries the passages it rests on — speaker, timestamp, exact
  words — so a reader can check it rather than trust it (spec §17).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from citizens_online.db.models import (
    Finding,
    FindingEvidence,
    Room,
    Round,
    Session,
    TranscriptSegment,
)

METHODOLOGY_NOTE = (
    "Findings were drafted by an AI model from the transcripts of each breakout room and "
    "reviewed by a human organizer before publication. Each finding cites the passages it "
    "rests on. Counts such as “raised in N rooms” are computed from those citations, not "
    "asserted by the model. Rooms are discussion groups, not votes: nothing here should be "
    "read as a measure of how many participants support a position."
)

LIVE_TRANSCRIPT_NOTE = (
    " Some transcripts are live captions rather than a final pass over the recorded audio, "
    "and may contain recognition errors."
)

TYPE_ORDER = (
    "proposal",
    "agreement",
    "disagreement",
    "concern",
    "question",
    "minority_position",
    "new_idea",
)
TYPE_LABELS = {
    "proposal": "Proposals",
    "agreement": "Points of agreement",
    "disagreement": "Points of disagreement",
    "concern": "Concerns",
    "question": "Open questions",
    "minority_position": "Minority positions",
    "new_idea": "New ideas",
}
TYPE_LABELS_SINGULAR = {
    "proposal": "Proposal",
    "agreement": "Agreement",
    "disagreement": "Disagreement",
    "concern": "Concern",
    "question": "Question",
    "minority_position": "Minority position",
    "new_idea": "New idea",
}
APPROVED = ("APPROVED", "EDITED_AND_APPROVED")


def _timestamp(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def group_findings_by_type(findings: list[dict]) -> list[tuple[str, str, list[dict]]]:
    grouped = []
    for type_name in TYPE_ORDER:
        items = [f for f in findings if f["type"] == type_name]
        if items:
            grouped.append((type_name, TYPE_LABELS[type_name], items))
    return grouped


def _evidence_for(db: DbSession, finding: Finding) -> list[dict]:
    segment_ids = [link.transcript_segment_id for link in finding.evidence]
    if not segment_ids:
        return []
    segments = db.execute(
        select(TranscriptSegment).where(TranscriptSegment.id.in_(segment_ids))
    ).scalars()
    return [
        {
            "speaker": s.speaker_label or "Unattributed",
            "start": s.start_seconds,
            "timestamp": _timestamp(s.start_seconds),
            "text": s.text,
            "origin": s.origin,
        }
        for s in sorted(segments, key=lambda s: s.start_seconds)
    ]


def _finding_payload(db: DbSession, finding: Finding, room_numbers: dict[str, int]) -> dict:
    return {
        "id": finding.id,
        "type": finding.type,
        "title": finding.title,
        "summary": finding.summary,
        "support": finding.support,
        "status": finding.status,
        "is_draft": finding.status == "DRAFT",
        "room_number": room_numbers.get(finding.room_id or ""),
        "mentioned_room_count": finding.mentioned_room_count,
        "evidence_removed": finding.evidence_removed_at is not None,
        "evidence": _evidence_for(db, finding),
    }


def _has_live_transcript(db: DbSession, session_obj: Session) -> bool:
    from citizens_online.db.models import Recording, Transcript

    row = db.execute(
        select(Transcript)
        .join(Recording, Transcript.recording_id == Recording.id)
        .where(Recording.session_id == session_obj.id, Transcript.source == "live")
    ).scalars().first()
    return row is not None


def build_report(db: DbSession, session_obj: Session, include_drafts: bool = False) -> dict:
    room_numbers = {
        r.id: r.number
        for r in db.execute(select(Room).where(Room.session_id == session_obj.id)).scalars()
    }
    rounds_payload = []
    for round_obj in sorted(session_obj.rounds, key=lambda r: r.position):
        findings = list(
            db.execute(select(Finding).where(Finding.round_id == round_obj.id)).scalars()
        )
        if not include_drafts:
            findings = [f for f in findings if f.status in APPROVED]
        cross = [
            _finding_payload(db, f, room_numbers) for f in findings if f.scope == "round"
        ]
        rooms = []
        for room in sorted(round_obj.rooms, key=lambda r: r.number):
            room_findings = [
                _finding_payload(db, f, room_numbers)
                for f in findings
                if f.scope == "room" and f.room_id == room.id
            ]
            rooms.append(
                {
                    "room_number": room.number,
                    "summary": room.analysis_summary,
                    "findings": room_findings,
                }
            )
        rounds_payload.append(
            {
                "position": round_obj.position,
                "title": round_obj.title,
                "question": round_obj.question,
                "status": round_obj.status,
                "summary": round_obj.analysis_summary,
                "cross_room": cross,
                "rooms": rooms,
            }
        )

    method = (
        "Participants discussed in Nextcloud Talk breakout rooms. Each participant's own "
        "browser recorded their microphone, so every transcript line is attributed to the "
        "person who spoke it."
    )
    note = METHODOLOGY_NOTE
    if _has_live_transcript(db, session_obj):
        note += LIVE_TRANSCRIPT_NOTE

    return {
        "session": {
            "name": session_obj.name,
            "description": session_obj.description,
            "language": session_obj.language,
            "status": session_obj.status,
            "participants": len(session_obj.participants),
            "rooms": session_obj.rooms_per_round,
        },
        "method": method,
        "methodology_note": note,
        "include_drafts": include_drafts,
        "is_final": session_obj.closed_at is not None,
        "closed_at": session_obj.closed_at.isoformat() if session_obj.closed_at else None,
        "published_at": session_obj.report_published_at.isoformat()
        if session_obj.report_published_at
        else None,
        "generated_at": datetime.now().astimezone().isoformat(),
        "rounds": rounds_payload,
    }


def _markdown_finding(finding: dict, cross: bool) -> list[str]:
    lines = [f"**{finding['title']}**"]
    if finding["is_draft"]:
        lines[0] += "  _(AI draft, not approved)_"
    if finding["summary"]:
        lines.append("")
        lines.append(finding["summary"])
    if cross and finding.get("mentioned_room_count"):
        lines.append("")
        lines.append(f"_Raised in {finding['mentioned_room_count']} room(s)._")
    if finding["evidence"]:
        lines.append("")
        for item in finding["evidence"][:6]:
            lines.append(f"> {item['speaker']} ({item['timestamp']}): {item['text']}")
    elif finding["evidence_removed"]:
        lines.append("")
        lines.append("_The supporting transcript has since been deleted._")
    lines.append("")
    return lines


def render_markdown(report: dict) -> str:
    out = [f"# {report['session']['name']}", ""]
    if report["session"]["description"]:
        out += [report["session"]["description"], ""]
    out += [
        f"_{report['session']['participants']} participants · "
        f"{'final' if report['is_final'] else 'interim'} report_",
        "",
        report["method"],
        "",
    ]
    for round_data in report["rounds"]:
        out.append(f"## Round {round_data['position']} — {round_data['title']}")
        if round_data["question"]:
            out += ["", f"**{round_data['question']}**"]
        if round_data["summary"]:
            out += ["", round_data["summary"]]
        out.append("")
        if round_data["cross_room"]:
            out.append("### Across all rooms")
            out.append("")
            for _type_name, label, items in group_findings_by_type(round_data["cross_room"]):
                out.append(f"#### {label}")
                out.append("")
                for finding in items:
                    out += _markdown_finding(finding, cross=True)
        for room in round_data["rooms"]:
            if not room["findings"] and not room["summary"]:
                continue
            out.append(f"### Room {room['room_number']}")
            out.append("")
            if room["summary"]:
                out += [room["summary"], ""]
            for _type_name, label, items in group_findings_by_type(room["findings"]):
                out.append(f"#### {label}")
                out.append("")
                for finding in items:
                    out += _markdown_finding(finding, cross=False)
    out += ["---", "", report["methodology_note"], ""]
    return "\n".join(out)


def freeze(db: DbSession, session_obj: Session) -> dict:
    """Snapshot the report so reopening a session cannot change what people
    have already read."""
    import json

    from citizens_online.db.models.base import utcnow

    report = build_report(db, session_obj, include_drafts=False)
    session_obj.final_report_json = json.dumps(report)
    session_obj.final_report_at = utcnow()
    return report


__all__ = [
    "APPROVED",
    "TYPE_LABELS",
    "TYPE_LABELS_SINGULAR",
    "build_report",
    "freeze",
    "group_findings_by_type",
    "render_markdown",
    "FindingEvidence",
    "Round",
]
