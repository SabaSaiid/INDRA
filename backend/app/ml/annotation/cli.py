"""Small local terminal interface for human duplicate-pair review."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app.ml.data.annotations import AnnotationRecord, AnnotationStore
from app.ml.data.candidate_pairs import (
    CandidatePairRecord,
    LocalReportRecord,
    load_candidate_pairs,
    load_local_reports,
)
from app.ml.data.duplicate_pairs import DuplicatePairLabel


def format_pair_for_review(
    candidate: CandidatePairRecord,
    reports: Mapping[str, LocalReportRecord],
    *,
    show_model_score: bool = False,
) -> str:
    """Render review evidence without presenting any model result as truth."""

    def render_report(label: str, report_id: str) -> list[str]:
        report = reports.get(report_id)
        if report is None:
            return [f"{label}: MISSING REPORT CONTENT ({report_id})"]
        return [
            f"{label}: {report_id}",
            f"  text: {report.text}",
            f"  timestamp: {report.occurred_at.isoformat() if report.occurred_at else 'UNKNOWN'}",
            f"  location: {report.latitude}, {report.longitude}",
            f"  source: {report.source_type or 'UNKNOWN'}",
            f"  source_metadata: {json.dumps(report.source_metadata, ensure_ascii=False, sort_keys=True)}",
        ]

    lines = [
        f"PAIR FOR HUMAN REVIEW: {candidate.pair_id}",
        "STATUS: CANDIDATE_FOR_REVIEW",
        *render_report("REPORT A", candidate.report_a_id),
        *render_report("REPORT B", candidate.report_b_id),
        f"distance_km: {candidate.distance_km:.6f}",
        f"time_delta_seconds: {candidate.time_delta_seconds:.6f}",
        f"text_summary: {json.dumps(candidate.text_summary, sort_keys=True)}",
    ]
    if show_model_score and candidate.candidate_score is not None:
        lines.append(f"MODEL SCORE — NOT GROUND TRUTH: {candidate.candidate_score:.6f}")
    return "\n".join(lines)


def run_annotation_cli(
    candidates: Sequence[CandidatePairRecord],
    reports: Mapping[str, LocalReportRecord],
    store: AnnotationStore,
    *,
    annotator_id: str,
    seed: int = 42,
    show_model_score: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> list[AnnotationRecord]:
    """Review candidates in a fixed-seed randomized order and append annotations."""

    if not annotator_id.strip():
        raise ValueError("annotator_id is required")
    ordered = list(candidates)
    random.Random(seed).shuffle(ordered)
    existing = store.load()
    existing_keys = {
        (tuple(sorted((item.report_a_id, item.report_b_id))), item.annotator_id)
        for item in existing
    }
    created: list[AnnotationRecord] = []
    for candidate in ordered:
        key = (tuple(sorted((candidate.report_a_id, candidate.report_b_id))), annotator_id)
        if key in existing_keys:
            continue
        output_fn(format_pair_for_review(candidate, reports, show_model_score=show_model_score))
        output_fn("[ DUPLICATE ] [ NOT_DUPLICATE ] [ UNCERTAIN ]")
        choice = input_fn("label: ").strip().upper().replace(" ", "_")
        label_map = {
            "DUPLICATE": DuplicatePairLabel.DUPLICATE,
            "NOT_DUPLICATE": DuplicatePairLabel.NOT_DUPLICATE,
            "UNCERTAIN": DuplicatePairLabel.UNCERTAIN,
            "D": DuplicatePairLabel.DUPLICATE,
            "N": DuplicatePairLabel.NOT_DUPLICATE,
            "U": DuplicatePairLabel.UNCERTAIN,
        }
        if choice not in label_map:
            raise ValueError("label must be DUPLICATE, NOT_DUPLICATE, or UNCERTAIN")
        reason = input_fn("annotation reason: ").strip()
        if not reason:
            raise ValueError("annotation reason is required")
        annotation = AnnotationRecord(
            pair_id=candidate.pair_id,
            report_a_id=candidate.report_a_id,
            report_b_id=candidate.report_b_id,
            label=label_map[choice],
            annotator_id=annotator_id,
            annotation_timestamp=datetime.now(timezone.utc),
            annotation_reason=reason,
            event_id_when_known=candidate.event_id_when_known,
            incident_id_when_known=candidate.incident_id_when_known,
        )
        store.append(annotation)
        existing_keys.add(key)
        created.append(annotation)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Local INDRA duplicate-pair annotation interface")
    parser.add_argument("--candidates", type=Path, required=True, help="local candidate JSONL")
    parser.add_argument("--reports", type=Path, required=True, help="local report JSON/JSONL/CSV")
    parser.add_argument("--annotations", type=Path, required=True, help="local append-only annotation JSONL")
    parser.add_argument("--annotator-id", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--show-model-score", action="store_true")
    args = parser.parse_args()
    reports = {report.report_id: report for report in load_local_reports(args.reports)}
    created = run_annotation_cli(
        load_candidate_pairs(args.candidates),
        reports,
        AnnotationStore(args.annotations),
        annotator_id=args.annotator_id,
        seed=args.seed,
        show_model_score=args.show_model_score,
    )
    print(f"appended_annotations={len(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
