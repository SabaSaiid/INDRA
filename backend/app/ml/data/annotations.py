"""Append-only human annotation records and quality-control reporting."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.ml.config import local_only_path
from app.ml.data.candidate_pairs import CandidatePairRecord, LocalReportRecord, canonical_pair_key
from app.ml.data.duplicate_pairs import DuplicatePairLabel


class AnnotationRecord(BaseModel):
    """One independent human annotation; records are never overwritten."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(default_factory=lambda: f"annotation-{uuid4()}", min_length=1)
    pair_id: str = Field(min_length=1)
    report_a_id: str = Field(min_length=1)
    report_b_id: str = Field(min_length=1)
    label: DuplicatePairLabel
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    annotation_reason: str = Field(min_length=1)
    event_id_when_known: str | None = None
    incident_id_when_known: str | None = None
    notes: str | None = None


class AnnotationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    total_pairs: int = 0
    annotated_pairs: int = 0
    duplicate_labels: int = 0
    non_duplicate_labels: int = 0
    uncertain_labels: int = 0
    annotator_counts: dict[str, int] = Field(default_factory=dict)
    agreement_status: str = "DATA_UNAVAILABLE"
    agreement_rate: float | None = None
    repeated_annotation_pairs: int = 0
    disagreement_pairs: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnnotationStore:
    """Local JSONL append-only store for independent annotations."""

    def __init__(self, path: Path) -> None:
        self.path = local_only_path(path, description="annotation paths")

    def load(self) -> list[AnnotationRecord]:
        if not self.path.exists():
            return []
        records: list[AnnotationRecord] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(AnnotationRecord.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"invalid annotation at line {line_number}: {error}") from error
        return records

    def append(self, annotation: AnnotationRecord) -> None:
        existing = self.load()
        if any(item.annotation_id == annotation.annotation_id for item in existing):
            raise ValueError(f"annotation_id already exists: {annotation.annotation_id}")
        annotation_key = (*canonical_pair_key(annotation.report_a_id, annotation.report_b_id), annotation.annotator_id)
        if any(
            (*canonical_pair_key(item.report_a_id, item.report_b_id), item.annotator_id) == annotation_key
            for item in existing
        ):
            raise ValueError("same annotator has already annotated this unordered pair")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(annotation.model_dump_json() + "\n")


def annotation_from_candidate(
    candidate: CandidatePairRecord,
    *,
    label: DuplicatePairLabel,
    annotator_id: str,
    annotation_reason: str,
    timestamp: datetime | None = None,
    notes: str | None = None,
) -> AnnotationRecord:
    return AnnotationRecord(
        pair_id=candidate.pair_id,
        report_a_id=candidate.report_a_id,
        report_b_id=candidate.report_b_id,
        label=label,
        annotator_id=annotator_id,
        annotation_timestamp=timestamp or datetime.now(timezone.utc),
        annotation_reason=annotation_reason,
        event_id_when_known=candidate.event_id_when_known,
        incident_id_when_known=candidate.incident_id_when_known,
        notes=notes,
    )


def validate_annotation_quality(
    annotations: Sequence[AnnotationRecord],
    candidates: Sequence[CandidatePairRecord],
    reports: Mapping[str, LocalReportRecord],
) -> AnnotationQualityReport:
    """Validate annotation integrity and calculate available agreement only."""

    errors: list[str] = []
    warnings: list[str] = []
    candidate_by_id = {candidate.pair_id: candidate for candidate in candidates}
    seen_annotation_ids: set[str] = set()
    seen_annotator_pairs: set[tuple[str, str, str]] = set()
    pair_annotations: dict[tuple[str, str], list[AnnotationRecord]] = defaultdict(list)
    annotator_counts: Counter[str] = Counter()

    for annotation in annotations:
        if annotation.annotation_id in seen_annotation_ids:
            errors.append(f"duplicate annotation_id: {annotation.annotation_id}")
        seen_annotation_ids.add(annotation.annotation_id)
        if not annotation.annotator_id.strip():
            errors.append(f"missing annotator: {annotation.annotation_id}")
        try:
            pair_key = canonical_pair_key(annotation.report_a_id, annotation.report_b_id)
        except ValueError as error:
            errors.append(f"invalid self-pair {annotation.annotation_id}: {error}")
            continue
        annotator_pair_key = (*pair_key, annotation.annotator_id)
        if annotator_pair_key in seen_annotator_pairs:
            errors.append(f"duplicate annotation for pair and annotator: {annotation.annotation_id}")
        seen_annotator_pairs.add(annotator_pair_key)
        pair_annotations[pair_key].append(annotation)
        annotator_counts[annotation.annotator_id] += 1
        candidate = candidate_by_id.get(annotation.pair_id)
        if candidate is None:
            errors.append(f"invalid pair_id: {annotation.pair_id}")
        elif canonical_pair_key(candidate.report_a_id, candidate.report_b_id) != pair_key:
            errors.append(f"pair_id does not match report IDs: {annotation.annotation_id}")
        for report_id in pair_key:
            if report_id not in reports:
                errors.append(f"missing report content: {report_id}")
        for report_id in pair_key:
            report = reports.get(report_id)
            if report is not None and report.occurred_at is None:
                warnings.append(f"missing report timestamp: {report_id}")
            if report is not None and (report.latitude is None or report.longitude is None):
                warnings.append(f"missing report coordinates: {report_id}")

    repeated_pairs = [items for items in pair_annotations.values() if len(items) >= 2]
    disagreement_pairs = sum(1 for items in repeated_pairs if len({item.label for item in items}) > 1)
    if not repeated_pairs:
        agreement_status = "DATA_UNAVAILABLE"
        agreement_rate = None
        warnings.append("No repeated annotations are available for agreement calculation.")
    else:
        agreement_status = "DATA_AVAILABLE"
        agreement_rate = (len(repeated_pairs) - disagreement_pairs) / len(repeated_pairs)

    return AnnotationQualityReport(
        valid=not errors,
        total_pairs=len(candidates),
        annotated_pairs=len(pair_annotations),
        duplicate_labels=sum(annotation.label is DuplicatePairLabel.DUPLICATE for annotation in annotations),
        non_duplicate_labels=sum(annotation.label is DuplicatePairLabel.NOT_DUPLICATE for annotation in annotations),
        uncertain_labels=sum(annotation.label is DuplicatePairLabel.UNCERTAIN for annotation in annotations),
        annotator_counts=dict(sorted(annotator_counts.items())),
        agreement_status=agreement_status,
        agreement_rate=agreement_rate,
        repeated_annotation_pairs=len(repeated_pairs),
        disagreement_pairs=disagreement_pairs,
        errors=errors,
        warnings=sorted(set(warnings)),
    )
