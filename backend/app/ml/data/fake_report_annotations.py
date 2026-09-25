"""Append-only human annotation workflow for credibility-risk research."""

from __future__ import annotations

import random
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import local_only_path

from app.ml.contracts import CredibilityPrediction, ReportInput


class FakeReportLabel(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    MISLEADING = "MISLEADING"
    UNCERTAIN = "UNCERTAIN"


FakeReportSplit = Literal["train", "validation", "test"]
RULE_EVIDENCE_DISCLAIMER = "MODEL/RULE EVIDENCE — NOT GROUND TRUTH"


class AnnotationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    provenance: str = Field(min_length=1)


class FakeReportAnnotation(BaseModel):
    """One immutable human judgment; UNCERTAIN remains a valid final input."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(default_factory=lambda: f"fake-annotation-{uuid4()}", min_length=1)
    report_id: str = Field(min_length=1)
    label: FakeReportLabel
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    reason: str = Field(min_length=1)
    evidence: list[AnnotationEvidence] = Field(default_factory=list)
    canonical_event_id: str | None = Field(default=None, min_length=1)
    incident_id: str | None = Field(default=None, min_length=1)
    report_family_id: str | None = Field(default=None, min_length=1)
    report_text: str | None = None
    reported_latitude: float | None = None
    reported_longitude: float | None = None
    reported_at: datetime | None = None
    split: FakeReportSplit | None = None
    blinded: bool = True
    displayed_rule_score: float | None = Field(default=None, ge=0.0, le=1.0)
    score_disclaimer: Literal["MODEL/RULE EVIDENCE — NOT GROUND TRUTH"] | None = None
    taxonomy_version: str = "fake-report-taxonomy-v1"

    @model_validator(mode="after")
    def validate_blinding(self) -> "FakeReportAnnotation":
        if self.blinded and self.displayed_rule_score is not None:
            raise ValueError("blinded annotation cannot contain a displayed rule score")
        if self.displayed_rule_score is not None and self.score_disclaimer != RULE_EVIDENCE_DISCLAIMER:
            raise ValueError("displayed score requires the NOT GROUND TRUTH disclaimer")
        if self.score_disclaimer is not None and self.displayed_rule_score is None:
            raise ValueError("score disclaimer is only valid when a score is displayed")
        return self


class FakeAnnotationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    annotation_count: int = Field(ge=0)
    report_count: int = Field(ge=0)
    annotator_counts: dict[str, int] = Field(default_factory=dict)
    label_counts: dict[str, int] = Field(default_factory=dict)
    agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"]
    agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    repeated_report_count: int = Field(default=0, ge=0)
    disagreement_report_ids: list[str] = Field(default_factory=list)
    duplicate_annotation_ids: list[str] = Field(default_factory=list)
    duplicate_report_annotators: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FakeReportAdjudicationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    annotations: list[FakeReportAnnotation] = Field(min_length=1)
    disagreement: bool
    status: Literal["UNRESOLVED", "ADJUDICATED"] = "UNRESOLVED"
    adjudicated_label: FakeReportLabel | None = None
    adjudicator_id: str | None = None
    adjudication_timestamp: datetime | None = None
    adjudication_reason: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "FakeReportAdjudicationCase":
        if self.status == "ADJUDICATED":
            if not all(
                (
                    self.adjudicated_label,
                    self.adjudicator_id,
                    self.adjudication_timestamp,
                    self.adjudication_reason,
                )
            ):
                raise ValueError("adjudicated cases require label, adjudicator, timestamp, and reason")
        elif any(
            value is not None
            for value in (
                self.adjudicated_label,
                self.adjudicator_id,
                self.adjudication_timestamp,
                self.adjudication_reason,
            )
        ):
            raise ValueError("unresolved cases cannot carry adjudication fields")
        return self

    @property
    def effective_label(self) -> FakeReportLabel:
        return self.adjudicated_label or FakeReportLabel.UNCERTAIN


class FakeReportLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    report_ids_across_splits: list[str] = Field(default_factory=list)
    canonical_events_across_splits: list[str] = Field(default_factory=list)
    incidents_across_splits: list[str] = Field(default_factory=list)
    report_families_across_splits: list[str] = Field(default_factory=list)
    exact_texts_across_splits: list[str] = Field(default_factory=list)
    near_identical_text_pairs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FakeGroupedSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["GROUPED_SPLIT_AVAILABLE", "GROUPED_SPLIT_UNAVAILABLE"]
    group_field: str | None = None
    train: list[FakeReportAnnotation] = Field(default_factory=list)
    validation: list[FakeReportAnnotation] = Field(default_factory=list)
    test: list[FakeReportAnnotation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FakeAnnotationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    text: str
    rule_score: float | None = None
    rule_evidence: list[Any] = Field(default_factory=list)
    banner: str | None = None
    blinded: bool


class FakeReportAnnotationStore:
    """JSONL append-only store; existing records are never replaced."""

    def __init__(self, path: Path) -> None:
        self.path = local_only_path(path, description="annotation paths")

    def load(self) -> list[FakeReportAnnotation]:
        if not self.path.exists():
            return []
        result: list[FakeReportAnnotation] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                result.append(FakeReportAnnotation.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"invalid fake-report annotation at line {line_number}: {error}") from error
        return result

    def append(self, annotation: FakeReportAnnotation) -> None:
        existing = self.load()
        if any(item.annotation_id == annotation.annotation_id for item in existing):
            raise ValueError(f"annotation_id already exists: {annotation.annotation_id}")
        if any(
            item.report_id == annotation.report_id and item.annotator_id == annotation.annotator_id
            for item in existing
        ):
            raise ValueError("same annotator has already annotated this report")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(annotation.model_dump_json() + "\n")


def build_fake_annotation_view(
    report: ReportInput,
    prediction: CredibilityPrediction | None = None,
    *,
    blinded: bool = True,
) -> FakeAnnotationView:
    if blinded or prediction is None:
        return FakeAnnotationView(
            report_id=str(report.report_id),
            text=report.text,
            blinded=True,
        )
    return FakeAnnotationView(
        report_id=str(report.report_id),
        text=report.text,
        rule_score=prediction.risk_score,
        rule_evidence=[
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in prediction.evidence
        ],
        banner=RULE_EVIDENCE_DISCLAIMER,
        blinded=False,
    )


def validate_fake_report_annotations(
    annotations: Sequence[FakeReportAnnotation],
    *,
    available_report_ids: set[str] | None = None,
    adjudications: Sequence[FakeReportAdjudicationCase] | None = None,
) -> FakeAnnotationQualityReport:
    errors: list[str] = []
    warnings: list[str] = []
    annotation_ids: set[str] = set()
    report_annotators: set[tuple[str, str]] = set()
    duplicate_ids: set[str] = set()
    duplicate_report_annotators: set[str] = set()
    by_report: defaultdict[str, list[FakeReportAnnotation]] = defaultdict(list)
    annotator_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    for annotation in annotations:
        if annotation.annotation_id in annotation_ids:
            duplicate_ids.add(annotation.annotation_id)
        annotation_ids.add(annotation.annotation_id)
        key = (annotation.report_id, annotation.annotator_id)
        if key in report_annotators:
            duplicate_report_annotators.add("::".join(key))
        report_annotators.add(key)
        by_report[annotation.report_id].append(annotation)
        annotator_counts[annotation.annotator_id] += 1
        label_counts[annotation.label.value] += 1
        if available_report_ids is not None and annotation.report_id not in available_report_ids:
            errors.append(f"missing report data: {annotation.report_id}")
        coordinates = (annotation.reported_latitude, annotation.reported_longitude)
        if any(value is not None for value in coordinates):
            if any(value is None for value in coordinates):
                errors.append(f"incomplete coordinates: {annotation.annotation_id}")
            elif not (
                -90.0 <= annotation.reported_latitude <= 90.0
                and -180.0 <= annotation.reported_longitude <= 180.0
            ):
                errors.append(f"invalid coordinates: {annotation.annotation_id}")
        if annotation.reported_at and annotation.reported_at.year < 1970:
            errors.append(f"invalid timestamp: {annotation.annotation_id}")
    if duplicate_ids:
        errors.append("duplicate annotation IDs exist")
    if duplicate_report_annotators:
        errors.append("same annotator annotated the same report more than once")

    repeated = {report_id: items for report_id, items in by_report.items() if len(items) >= 2}
    disagreements = sorted(
        report_id for report_id, items in repeated.items()
        if len({item.label for item in items}) > 1
    )
    if repeated:
        agreement_status = "DATA_AVAILABLE"
        agreement_rate = (len(repeated) - len(disagreements)) / len(repeated)
    else:
        agreement_status = "DATA_UNAVAILABLE"
        agreement_rate = None
        warnings.append("No repeated annotations are available for inter-annotator agreement.")

    adjudication_by_report = {
        item.report_id: item for item in (adjudications or [])
    }
    for report_id in disagreements:
        case = adjudication_by_report.get(report_id)
        if case is None or case.status != "ADJUDICATED":
            warnings.append(f"unresolved annotation disagreement: {report_id}")
    return FakeAnnotationQualityReport(
        valid=not errors,
        annotation_count=len(annotations),
        report_count=len(by_report),
        annotator_counts=dict(sorted(annotator_counts.items())),
        label_counts=dict(sorted(label_counts.items())),
        agreement_status=agreement_status,
        agreement_rate=agreement_rate,
        repeated_report_count=len(repeated),
        disagreement_report_ids=disagreements,
        duplicate_annotation_ids=sorted(duplicate_ids),
        duplicate_report_annotators=sorted(duplicate_report_annotators),
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )


def build_fake_adjudication_case(
    annotations: Sequence[FakeReportAnnotation],
) -> FakeReportAdjudicationCase:
    if not annotations:
        raise ValueError("at least one annotation is required")
    report_ids = {item.report_id for item in annotations}
    if len(report_ids) != 1:
        raise ValueError("annotations must refer to one report")
    labels = {item.label for item in annotations}
    return FakeReportAdjudicationCase(
        report_id=annotations[0].report_id,
        annotations=sorted(
            annotations,
            key=lambda item: (item.annotation_timestamp, item.annotation_id),
        ),
        disagreement=len(labels) > 1,
    )


def adjudicate_fake_report(
    case: FakeReportAdjudicationCase,
    *,
    label: FakeReportLabel,
    adjudicator_id: str,
    reason: str,
    timestamp: datetime | None = None,
) -> FakeReportAdjudicationCase:
    if not adjudicator_id.strip() or not reason.strip():
        raise ValueError("adjudicator_id and reason are required")
    return case.model_copy(
        update={
            "status": "ADJUDICATED",
            "adjudicated_label": label,
            "adjudicator_id": adjudicator_id,
            "adjudication_timestamp": timestamp or datetime.now(timezone.utc),
            "adjudication_reason": reason,
        }
    )


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def validate_fake_report_leakage(
    annotations: Sequence[FakeReportAnnotation],
    *,
    near_identical_threshold: float = 0.95,
) -> FakeReportLeakageReport:
    if not 0.0 < near_identical_threshold <= 1.0:
        raise ValueError("near_identical_threshold must be in (0, 1]")
    locations: dict[str, defaultdict[str, set[str]]] = {
        "report": defaultdict(set),
        "canonical_event": defaultdict(set),
        "incident": defaultdict(set),
        "report_family": defaultdict(set),
        "text": defaultdict(set),
    }
    for annotation in annotations:
        if annotation.split is None:
            continue
        locations["report"][annotation.report_id].add(annotation.split)
        if annotation.canonical_event_id:
            locations["canonical_event"][annotation.canonical_event_id].add(annotation.split)
        if annotation.incident_id:
            locations["incident"][annotation.incident_id].add(annotation.split)
        if annotation.report_family_id:
            locations["report_family"][annotation.report_family_id].add(annotation.split)
        if annotation.report_text:
            locations["text"][_normalize_text(annotation.report_text)].add(annotation.split)

    def leaks(name: str) -> list[str]:
        return sorted(key for key, splits in locations[name].items() if len(splits) > 1)

    report_leaks = leaks("report")
    event_leaks = leaks("canonical_event")
    incident_leaks = leaks("incident")
    family_leaks = leaks("report_family")
    text_leaks = leaks("text")
    text_records = [
        (annotation.report_id, annotation.split, _normalize_text(annotation.report_text))
        for annotation in annotations
        if annotation.split is not None and annotation.report_text
    ]
    near_identical_pairs: set[str] = set()
    for index, (left_id, left_split, left_text) in enumerate(text_records):
        for right_id, right_split, right_text in text_records[index + 1:]:
            if left_split == right_split or left_text == right_text:
                continue
            if SequenceMatcher(None, left_text, right_text).ratio() >= near_identical_threshold:
                near_identical_pairs.add("::".join(sorted((left_id, right_id))))
    errors = []
    if report_leaks:
        errors.append("same report appears in multiple splits")
    if event_leaks:
        errors.append("same canonical event appears in multiple splits")
    if incident_leaks:
        errors.append("same incident appears in multiple splits")
    if family_leaks:
        errors.append("same report family appears in multiple splits")
    if text_leaks:
        errors.append("exact normalized report text appears in multiple splits")
    if near_identical_pairs:
        errors.append("near-identical report text appears in multiple splits")
    return FakeReportLeakageReport(
        valid=not errors,
        report_ids_across_splits=report_leaks,
        canonical_events_across_splits=event_leaks,
        incidents_across_splits=incident_leaks,
        report_families_across_splits=family_leaks,
        exact_texts_across_splits=text_leaks,
        near_identical_text_pairs=sorted(near_identical_pairs),
        errors=errors,
    )


def grouped_fake_report_split(
    annotations: Sequence[FakeReportAnnotation],
    *,
    seed: int = 42,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> FakeGroupedSplit:
    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(value <= 0.0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("split fractions must be positive and sum to one")
    if not annotations:
        return FakeGroupedSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=["No annotations were supplied."],
        )
    group_field = next(
        (
            field
            for field in ("canonical_event_id", "incident_id", "report_family_id")
            if all(getattr(item, field) for item in annotations)
        ),
        None,
    )
    if group_field is None:
        return FakeGroupedSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=[
                "Every annotation requires a canonical event, incident, or report-family key for grouped splitting."
            ],
        )
    groups: defaultdict[str, list[FakeReportAnnotation]] = defaultdict(list)
    for annotation in annotations:
        groups[str(getattr(annotation, group_field))].append(annotation)
    names = sorted(groups)
    random.Random(seed).shuffle(names)
    count = len(names)
    train_end = max(1, round(count * train_fraction))
    validation_count = max(1, round(count * validation_fraction)) if count >= 3 else 0
    if train_end + validation_count >= count:
        validation_count = max(0, count - train_end - 1)
    validation_end = train_end + validation_count
    buckets: dict[str, list[FakeReportAnnotation]] = {"train": [], "validation": [], "test": []}
    for index, name in enumerate(names):
        split: FakeReportSplit = "train" if index < train_end else "validation" if index < validation_end else "test"
        buckets[split].extend(item.model_copy(update={"split": split}) for item in groups[name])
    return FakeGroupedSplit(
        status="GROUPED_SPLIT_AVAILABLE",
        group_field=group_field,
        train=buckets["train"],
        validation=buckets["validation"],
        test=buckets["test"],
        warnings=(
            ["Fewer than three groups are available; one or more buckets may be empty."]
            if count < 3
            else []
        ),
    )


__all__ = [
    "AnnotationEvidence",
    "FakeAnnotationQualityReport",
    "FakeAnnotationView",
    "FakeGroupedSplit",
    "FakeReportAdjudicationCase",
    "FakeReportAnnotation",
    "FakeReportAnnotationStore",
    "FakeReportLabel",
    "FakeReportLeakageReport",
    "RULE_EVIDENCE_DISCLAIMER",
    "adjudicate_fake_report",
    "build_fake_adjudication_case",
    "build_fake_annotation_view",
    "grouped_fake_report_split",
    "validate_fake_report_annotations",
    "validate_fake_report_leakage",
]
