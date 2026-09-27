"""Human event-level annotation contracts and split-leakage checks.

This module defines schemas only. It does not populate labels and does not
infer canonical events from the current report dataset.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventAnnotationLabel(str, Enum):
    EVENT_MATCH = "EVENT_MATCH"
    EVENT_NOT_MATCH = "EVENT_NOT_MATCH"
    UNCERTAIN = "UNCERTAIN"


EventAnnotationSplit = Literal["train", "validation", "test"]


class EventPairAnnotation(BaseModel):
    """One human judgment about whether two event candidates match."""

    model_config = ConfigDict(extra="forbid")

    event_a_id: str = Field(min_length=1)
    event_b_id: str = Field(min_length=1)
    label: EventAnnotationLabel
    annotator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    timestamp: datetime
    canonical_event_id: str | None = Field(default=None, min_length=1)
    split: EventAnnotationSplit | None = None
    report_ids_a: list[str] = Field(default_factory=list)
    report_ids_b: list[str] = Field(default_factory=list)
    event_definition_hash_a: str | None = Field(default=None, min_length=1)
    event_definition_hash_b: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> "EventPairAnnotation":
        if self.event_a_id == self.event_b_id:
            raise ValueError("an event cannot be annotated against itself")
        return self


class ReportEventAnnotation(BaseModel):
    """Optional report-to-event review record for future annotation rounds."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    label: Literal["ASSIGNED", "NOT_ASSIGNED", "UNCERTAIN"]
    annotator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    timestamp: datetime
    canonical_event_id: str | None = Field(default=None, min_length=1)
    split: EventAnnotationSplit | None = None


class EventAnnotationValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_annotation_keys: list[str] = Field(default_factory=list)
    contradictory_pair_keys: list[str] = Field(default_factory=list)


class EventLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    canonical_event_ids_across_splits: list[str] = Field(default_factory=list)
    event_ids_across_splits: list[str] = Field(default_factory=list)
    report_ids_across_splits: list[str] = Field(default_factory=list)
    near_identical_event_definitions: list[str] = Field(default_factory=list)
    repeated_event_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _pair_key(record: EventPairAnnotation) -> str:
    return "::".join(sorted((record.event_a_id, record.event_b_id)))


def validate_event_annotations(
    records: Sequence[EventPairAnnotation],
) -> EventAnnotationValidationReport:
    """Detect malformed, duplicate, and contradictory human annotations."""

    errors: list[str] = []
    warnings: list[str] = []
    seen_keys: dict[tuple[str, str, str], EventPairAnnotation] = {}
    labels_by_pair: defaultdict[str, set[EventAnnotationLabel]] = defaultdict(set)
    duplicate_keys: set[str] = set()
    contradictory: set[str] = set()
    for record in records:
        pair_key = _pair_key(record)
        labels_by_pair[pair_key].add(record.label)
        annotation_key = (pair_key, record.annotator_id, record.timestamp.isoformat())
        if annotation_key in seen_keys:
            duplicate_keys.add("::".join(annotation_key))
        seen_keys[annotation_key] = record
    for pair_key, labels in labels_by_pair.items():
        substantive = labels - {EventAnnotationLabel.UNCERTAIN}
        if len(substantive) > 1:
            contradictory.add(pair_key)
    if duplicate_keys:
        errors.append("duplicate event annotation keys exist")
    if contradictory:
        errors.append("contradictory labels exist for an event pair")
    if records and not any(record.split for record in records):
        warnings.append("EVENT_GROUPED_SPLIT_UNAVAILABLE: no split assignments supplied")
    return EventAnnotationValidationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        duplicate_annotation_keys=sorted(duplicate_keys),
        contradictory_pair_keys=sorted(contradictory),
    )


def validate_event_annotation_leakage(
    records: Sequence[EventPairAnnotation],
) -> EventLeakageReport:
    """Ensure underlying events and report evidence do not cross splits."""

    canonical_locations: defaultdict[str, set[str]] = defaultdict(set)
    event_locations: defaultdict[str, set[str]] = defaultdict(set)
    report_locations: defaultdict[str, set[str]] = defaultdict(set)
    definition_locations: defaultdict[str, set[str]] = defaultdict(set)
    event_counts: defaultdict[str, int] = defaultdict(int)
    for record in records:
        if record.split is None:
            continue
        split = record.split
        event_counts[record.event_a_id] += 1
        event_counts[record.event_b_id] += 1
        event_locations[record.event_a_id].add(split)
        event_locations[record.event_b_id].add(split)
        for event_id in (record.event_a_id, record.event_b_id):
            if record.canonical_event_id:
                canonical_locations[record.canonical_event_id].add(split)
        for report_id in record.report_ids_a + record.report_ids_b:
            report_locations[report_id].add(split)
        for definition_hash in (
            record.event_definition_hash_a,
            record.event_definition_hash_b,
        ):
            if definition_hash:
                definition_locations[definition_hash].add(split)

    canonical_leaks = sorted(key for key, value in canonical_locations.items() if len(value) > 1)
    event_leaks = sorted(key for key, value in event_locations.items() if len(value) > 1)
    report_leaks = sorted(key for key, value in report_locations.items() if len(value) > 1)
    definition_leaks = sorted(key for key, value in definition_locations.items() if len(value) > 1)
    repeated_events = sorted(key for key, count in event_counts.items() if count > 1)
    errors: list[str] = []
    if canonical_leaks:
        errors.append("same canonical event appears in multiple splits")
    if event_leaks:
        errors.append("same event ID appears in multiple splits")
    if report_leaks:
        errors.append("same report appears in multiple splits")
    if definition_leaks:
        errors.append("near-identical event definitions appear in multiple splits")
    return EventLeakageReport(
        valid=not errors,
        canonical_event_ids_across_splits=canonical_leaks,
        event_ids_across_splits=event_leaks,
        report_ids_across_splits=report_leaks,
        near_identical_event_definitions=definition_leaks,
        repeated_event_ids=repeated_events,
        errors=errors,
    )


__all__ = [
    "EventAnnotationLabel",
    "EventAnnotationSplit",
    "EventAnnotationValidationReport",
    "EventLeakageReport",
    "EventPairAnnotation",
    "ReportEventAnnotation",
    "validate_event_annotation_leakage",
    "validate_event_annotations",
]
