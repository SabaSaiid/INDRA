"""Strict schema and validation helpers for human-reviewed duplicate pairs.

The module intentionally contains no production labels. It defines the
dataset contract that a future annotation import must satisfy.
"""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Literal, Mapping, Sequence
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DuplicatePairLabel(str, Enum):
    DUPLICATE = "DUPLICATE"
    NOT_DUPLICATE = "NOT_DUPLICATE"
    UNCERTAIN = "UNCERTAIN"


DuplicatePairSplit = Literal["train", "validation", "test"]


class DuplicatePairRecord(BaseModel):
    """One human annotation for an unordered report pair."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(min_length=1)
    report_a_id: str | UUID
    report_b_id: str | UUID
    label: DuplicatePairLabel
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    annotation_reason: str = Field(min_length=1)
    label_provenance: str = Field(min_length=1)
    # The *_when_known names are canonical; short aliases are accepted for
    # importers that already expose event_id/incident_id fields.
    event_id_when_known: str | None = Field(default=None, min_length=1)
    incident_id_when_known: str | None = Field(default=None, min_length=1)
    event_id: str | None = Field(default=None, min_length=1)
    incident_id: str | None = Field(default=None, min_length=1)
    text_relationship: Literal["same", "paraphrase", "unrelated", "unknown"] = "unknown"
    temporal_relationship: str | None = None
    geographic_relationship: str | None = None
    time_delta_seconds: float | None = Field(default=None, ge=0.0)
    distance_km: float | None = Field(default=None, ge=0.0)
    latitude_a: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude_a: float | None = Field(default=None, ge=-180.0, le=180.0)
    latitude_b: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude_b: float | None = Field(default=None, ge=-180.0, le=180.0)
    source_relationship: str | None = None
    split: DuplicatePairSplit | None = None
    # Optional immutable report context used by governed local evaluation
    # datasets. Human-annotation records may omit these fields.
    text_a: str | None = Field(default=None, min_length=1)
    text_b: str | None = Field(default=None, min_length=1)
    occurred_at_a: datetime | None = None
    occurred_at_b: datetime | None = None
    language: str | None = Field(default=None, min_length=1)
    event_type_a: str | None = Field(default=None, min_length=1)
    event_type_b: str | None = Field(default=None, min_length=1)
    source_type_a: str | None = Field(default=None, min_length=1)
    source_type_b: str | None = Field(default=None, min_length=1)
    incident_a_id: str | None = Field(default=None, min_length=1)
    incident_b_id: str | None = Field(default=None, min_length=1)
    scenario_type: str | None = Field(default=None, min_length=1)
    scenario_family: str | None = Field(default=None, min_length=1)
    split_group_id: str | None = Field(default=None, min_length=1)
    parameter_combination_id: str | None = Field(default=None, min_length=1)
    synthetic_generator_version: str | None = Field(default=None, min_length=1)
    synthetic_generator_seed: int | None = None

    @model_validator(mode="after")
    def report_ids_are_present(self) -> "DuplicatePairRecord":
        if not str(self.report_a_id).strip() or not str(self.report_b_id).strip():
            raise ValueError("report IDs are required")
        paired_fields = (
            (self.text_a, self.text_b, "report texts"),
            (self.occurred_at_a, self.occurred_at_b, "occurrence timestamps"),
            (self.event_type_a, self.event_type_b, "event types"),
            (self.source_type_a, self.source_type_b, "source types"),
            (self.incident_a_id, self.incident_b_id, "incident identifiers"),
        )
        for left, right, description in paired_fields:
            if (left is None) != (right is None):
                raise ValueError(f"{description} must be supplied as a complete pair")
        for value in (self.occurred_at_a, self.occurred_at_b):
            if value is not None and value.tzinfo is None:
                raise ValueError("occurrence timestamps must include a timezone")
        return self


class DuplicatePairValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_pair_ids: list[str] = Field(default_factory=list)
    reversed_pair_ids: list[str] = Field(default_factory=list)
    contradictory_pair_keys: list[str] = Field(default_factory=list)
    duplicate_annotations: list[str] = Field(default_factory=list)
    leakage_groups: list[str] = Field(default_factory=list)


def _pair_key(record: DuplicatePairRecord) -> tuple[str, str]:
    return tuple(sorted((str(record.report_a_id), str(record.report_b_id))))


def validate_duplicate_pairs(
    records: Sequence[DuplicatePairRecord],
    *,
    assignments: Mapping[str, DuplicatePairSplit] | None = None,
) -> DuplicatePairValidationReport:
    """Validate identity, annotations, coordinates, and split leakage."""

    errors: list[str] = []
    warnings: list[str] = []
    pair_ids: dict[str, DuplicatePairRecord] = {}
    pair_keys: dict[tuple[str, str], list[DuplicatePairRecord]] = {}
    duplicate_pair_ids: list[str] = []
    reversed_pair_ids: list[str] = []
    contradictory: list[str] = []
    duplicate_annotations: list[str] = []
    leakage_groups: list[str] = []

    for record in records:
        if record.report_a_id == record.report_b_id:
            errors.append(f"self-pair is not allowed: {record.pair_id}")
        if record.pair_id in pair_ids:
            duplicate_pair_ids.append(record.pair_id)
        else:
            pair_ids[record.pair_id] = record
        key = _pair_key(record)
        pair_keys.setdefault(key, []).append(record)
        coordinates = (record.latitude_a, record.longitude_a, record.latitude_b, record.longitude_b)
        if any(value is not None for value in coordinates) and any(value is None for value in coordinates):
            errors.append(f"incomplete coordinate set: {record.pair_id}")
        if any(value is not None and not isfinite(value) for value in coordinates):
            errors.append(f"non-finite coordinate: {record.pair_id}")

    for key, annotations in pair_keys.items():
        if len(annotations) <= 1:
            continue
        if len({record.label for record in annotations}) > 1:
            contradictory.append(f"{key[0]}::{key[1]}")
        for record in annotations:
            if sum(other.annotator_id == record.annotator_id for other in annotations) > 1:
                duplicate_annotations.append(f"{key[0]}::{key[1]}::{record.annotator_id}")
            if str(record.report_a_id) == key[1] and str(record.report_b_id) == key[0]:
                reversed_pair_ids.append(record.pair_id)

    if duplicate_pair_ids:
        errors.append("duplicate pair_id values: " + ", ".join(sorted(set(duplicate_pair_ids))))
    if reversed_pair_ids:
        errors.append("reversed report pairs are duplicated: " + ", ".join(sorted(set(reversed_pair_ids))))
    if duplicate_annotations:
        errors.append("duplicate annotations for the same pair and annotator")
    if contradictory:
        errors.append("contradictory labels exist for the same unordered pair")

    split_map = dict(assignments or {})
    if not split_map and any(record.split is not None for record in records):
        split_map = {record.pair_id: record.split for record in records if record.split is not None}
    if split_map:
        groups: dict[tuple[str, str], set[str]] = {}
        for record in records:
            split = split_map.get(record.pair_id)
            group_value = (
                record.event_id_when_known
                or record.event_id
                or record.incident_id_when_known
                or record.incident_id
            )
            if split is None or group_value is None:
                continue
            group_field = (
                "event_id"
                if record.event_id_when_known or record.event_id
                else "incident_id"
            )
            groups.setdefault((group_field, group_value), set()).add(split)
        for group, splits in groups.items():
            if len(splits) > 1:
                leakage_groups.append(f"{group[0]}:{group[1]}")
                errors.append(f"group leakage spans multiple dataset splits: {group[0]}:{group[1]}")
                warnings.append("DATASET_LEAKAGE_DETECTED")
    elif records:
        warnings.append(
            "GROUPED_SPLIT_UNAVAILABLE: no complete event_id_when_known or "
            "incident_id_when_known grouping key"
        )

    return DuplicatePairValidationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        duplicate_pair_ids=sorted(set(duplicate_pair_ids)),
        reversed_pair_ids=sorted(set(reversed_pair_ids)),
        contradictory_pair_keys=sorted(set(contradictory)),
        duplicate_annotations=sorted(set(duplicate_annotations)),
        leakage_groups=sorted(set(leakage_groups)),
    )
