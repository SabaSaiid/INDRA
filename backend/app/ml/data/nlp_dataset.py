"""Human-adjudicated NLP dataset grouping, leakage, and release contracts.

This module never derives a label.  A released label must be present in an
explicit human adjudication decision that references the immutable source
annotations.  Dataset versions are registered as candidates; validation and
approval remain separate Phase 13 operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.config import local_only_path
from app.ml.data.nlp_annotations import (
    ANNOTATION_GUIDE_VERSION,
    ANNOTATION_SCHEMA_VERSION,
    NLPAdjudicationDecision,
    NLPAnnotationState,
    NLPEventLabel,
    NLPHumanAnnotation,
    NLPLanguage,
    NLPSourceReport,
    ProtectedNLPFinalTestIndex,
    assert_no_protected_final_test_text,
    assert_protected_nlp_assets_immutable,
    exact_text_sha256,
    normalize_text_for_leakage,
    normalized_text_sha256,
    validate_nlp_annotation_quality,
)
from app.ml.data.registry import (
    DatasetClassification,
    DatasetComponent,
    DatasetFormat,
    DatasetProvenance,
    DatasetRegistryRecord,
    hash_dataset_path,
    register_dataset,
)

NLP_DATASET_SCHEMA_VERSION = "nlp-human-adjudicated-dataset-v1"
NLP_LABEL_SCHEMA_VERSION = "nlp-event-taxonomy-v1"
NLP_DATASET_MANIFEST_VERSION = "nlp-dataset-manifest-v1"
NLP_GROUPING_STRATEGY = (
    "connected components over event_id_if_known, incident_id_if_known, "
    "and source_report_family; unavailable identifiers remain ungrouped"
)
HUMAN_LABEL_SOURCE = "EXPLICIT_HUMAN_ADJUDICATION"

_SAFE_RELEASE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class NLPDatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class NLPResolvedAnnotation(BaseModel):
    """One explicitly adjudicated report before split assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1)
    label: NLPEventLabel
    language: NLPLanguage
    source_metadata_if_available: dict[str, Any] = Field(default_factory=dict)
    event_id_if_known: str | None = Field(default=None, min_length=1)
    incident_id_if_known: str | None = Field(default=None, min_length=1)
    source_report_family: str | None = Field(default=None, min_length=1)
    source_dataset_id: str | None = Field(default=None, min_length=1)
    annotation_ids: tuple[str, ...] = Field(min_length=1)
    annotator_ids: tuple[str, ...] = Field(min_length=1)
    adjudication_id: str = Field(min_length=1)
    adjudicator_id: str = Field(min_length=1)
    adjudication_timestamp: datetime
    adjudication_reason: str = Field(min_length=1)
    assistance_shown_in_source_annotations: bool = False
    group_id: str | None = Field(default=None, min_length=1)
    grouping_keys: tuple[str, ...] = ()

    @model_validator(mode="after")
    def resolved_record_is_human_and_exact(self) -> NLPResolvedAnnotation:
        if self.text_hash != exact_text_sha256(self.text):
            raise ValueError("resolved text_hash does not match exact text")
        if self.adjudication_timestamp.tzinfo is None:
            raise ValueError("adjudication_timestamp must include a timezone")
        if len(self.annotation_ids) != len(set(self.annotation_ids)):
            raise ValueError("resolved annotation_ids must be unique")
        if len(self.annotator_ids) != len(set(self.annotator_ids)):
            raise ValueError("resolved annotator_ids must be unique")
        return self

    @property
    def split_assignment_key(self) -> str:
        return self.group_id or f"ungrouped-report:{self.report_id}"


class NLPResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[NLPResolvedAnnotation, ...] = ()
    excluded_uncertain_report_ids: tuple[str, ...] = ()
    source_report_count: int = Field(ge=0)
    explicit_adjudication_count: int = Field(ge=0)


class NLPGroupingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["COMPLETE", "PARTIAL", "DATA_UNAVAILABLE"]
    strategy: Literal[
        "connected components over event_id_if_known, incident_id_if_known, and source_report_family; unavailable identifiers remain ungrouped"
    ] = NLP_GROUPING_STRATEGY
    records: tuple[NLPResolvedAnnotation, ...] = ()
    group_count: int = Field(ge=0)
    grouped_report_count: int = Field(ge=0)
    ungrouped_report_ids: tuple[str, ...] = ()


class NLPGroupingPlanEntry(BaseModel):
    """Human-reviewed unit to which exactly one split must be assigned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    split_assignment_key: str = Field(min_length=1)
    group_id: str | None = Field(default=None, min_length=1)
    report_ids: tuple[str, ...] = Field(min_length=1)
    event_ids: tuple[str, ...] = ()
    incident_ids: tuple[str, ...] = ()
    source_report_families: tuple[str, ...] = ()
    source_dataset_ids: tuple[str, ...] = ()
    split: NLPDatasetSplit | None = None


class NLPGroupingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_version: Literal["nlp-grouping-plan-v1"] = "nlp-grouping-plan-v1"
    grouping_status: Literal["COMPLETE", "PARTIAL", "DATA_UNAVAILABLE"]
    grouping_strategy: Literal[
        "connected components over event_id_if_known, incident_id_if_known, and source_report_family; unavailable identifiers remain ungrouped"
    ] = NLP_GROUPING_STRATEGY
    automatic_split_assignment: Literal["NONE"] = "NONE"
    entries: tuple[NLPGroupingPlanEntry, ...] = ()


class NLPDatasetRecord(BaseModel):
    """Registry-compatible released row with auditable human provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_type: NLPEventLabel
    language: NLPLanguage
    split: NLPDatasetSplit
    group_id: str | None = Field(default=None, min_length=1)
    grouping_keys: tuple[str, ...] = ()
    event_id_if_known: str | None = Field(default=None, min_length=1)
    incident_id_if_known: str | None = Field(default=None, min_length=1)
    source_report_family: str | None = Field(default=None, min_length=1)
    source_dataset_id: str | None = Field(default=None, min_length=1)
    source_metadata_if_available: dict[str, Any] = Field(default_factory=dict)
    annotation_ids: tuple[str, ...] = Field(min_length=1)
    annotator_ids: tuple[str, ...] = Field(min_length=1)
    adjudication_id: str = Field(min_length=1)
    adjudicator_id: str = Field(min_length=1)
    adjudication_timestamp: datetime
    adjudication_reason: str = Field(min_length=1)
    label_provenance: Literal["EXPLICIT_HUMAN_ADJUDICATION"] = HUMAN_LABEL_SOURCE
    human_adjudicated: Literal[True] = True
    assistance_shown_in_source_annotations: bool = False

    @model_validator(mode="after")
    def released_row_is_exact(self) -> NLPDatasetRecord:
        if self.text_hash != exact_text_sha256(self.text):
            raise ValueError("released text_hash does not match exact text")
        if self.adjudication_timestamp.tzinfo is None:
            raise ValueError("adjudication_timestamp must include a timezone")
        return self


class NLPDatasetLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["nlp-dataset-leakage-v1"] = "nlp-dataset-leakage-v1"
    generated_at: datetime
    overall_status: Literal["PASS", "FAIL", "INSUFFICIENT_EVIDENCE"]
    valid: bool
    record_ids_across_splits: tuple[str, ...] = ()
    group_ids_across_splits: tuple[str, ...] = ()
    event_ids_across_splits: tuple[str, ...] = ()
    incident_ids_across_splits: tuple[str, ...] = ()
    source_families_across_splits: tuple[str, ...] = ()
    exact_texts_across_splits: tuple[str, ...] = ()
    normalized_texts_across_splits: tuple[str, ...] = ()
    near_duplicate_pairs_across_splits: tuple[str, ...] = ()
    protected_final_test_overlap: tuple[str, ...] = ()
    missing_group_report_ids: tuple[str, ...] = ()
    near_duplicate_scan: Literal["COMPLETE", "DATA_UNAVAILABLE"]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class NLPDatasetVersionManifest(BaseModel):
    """Immutable evidence accompanying every released annotation dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal["nlp-dataset-manifest-v1"] = (
        NLP_DATASET_MANIFEST_VERSION
    )
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_schema_version: Literal["nlp-human-annotation-v1"] = (
        ANNOTATION_SCHEMA_VERSION
    )
    guide_version: Literal["nlp-annotation-guide-v1"] = ANNOTATION_GUIDE_VERSION
    dataset_schema_version: Literal["nlp-human-adjudicated-dataset-v1"] = (
        NLP_DATASET_SCHEMA_VERSION
    )
    label_schema_version: Literal["nlp-event-taxonomy-v1"] = (
        NLP_LABEL_SCHEMA_VERSION
    )
    annotator_count: int = Field(ge=0)
    adjudicator_count: int = Field(ge=0)
    label_counts: dict[str, int] = Field(default_factory=dict)
    language_counts: dict[str, int] = Field(default_factory=dict)
    grouping_strategy: Literal[
        "connected components over event_id_if_known, incident_id_if_known, and source_report_family; unavailable identifiers remain ungrouped"
    ] = NLP_GROUPING_STRATEGY
    grouping_status: Literal["COMPLETE", "PARTIAL", "DATA_UNAVAILABLE"]
    grouping_coverage: float = Field(ge=0.0, le=1.0)
    creation_timestamp: datetime
    record_count: int = Field(ge=0)
    split_definition: str = Field(min_length=1)
    split_counts: dict[str, int] = Field(default_factory=dict)
    independent_test_dataset_ids: tuple[str, ...] = ()
    excluded_uncertain_report_ids: tuple[str, ...] = ()
    uncertainty_count: int = Field(ge=0)
    model_assisted_annotation_count: int = Field(ge=0)
    human_ground_truth: Literal[True] = True
    automatic_label_generation: Literal["NONE"] = "NONE"
    protected_final_test_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    leakage_status: Literal["PASS", "INSUFFICIENT_EVIDENCE"]
    leakage_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("creation_timestamp")
    @classmethod
    def creation_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def release_hashes_and_counts_are_coherent(self) -> NLPDatasetVersionManifest:
        if self.dataset_hash != self.content_hash:
            raise ValueError("dataset_hash must equal content_hash")
        if self.uncertainty_count != len(self.excluded_uncertain_report_ids):
            raise ValueError(
                "uncertainty_count must match excluded_uncertain_report_ids"
            )
        return self


class NLPDatasetRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    dataset_path: Path
    manifest_path: Path
    leakage_report_path: Path
    manifest: NLPDatasetVersionManifest
    leakage: NLPDatasetLeakageReport
    registry_record: DatasetRegistryRecord


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_evidence_sha256(
    reports: Sequence[NLPSourceReport],
    annotations: Sequence[NLPHumanAnnotation],
    adjudications: Sequence[NLPAdjudicationDecision],
) -> str:
    payload = {
        "reports": [
            item.model_dump(mode="json")
            for item in sorted(reports, key=lambda value: value.report_id)
        ],
        "annotations": [
            item.model_dump(mode="json")
            for item in sorted(annotations, key=lambda value: value.annotation_id)
        ],
        "adjudications": [
            item.model_dump(mode="json")
            for item in sorted(
                adjudications,
                key=lambda value: value.adjudication_id,
            )
        ],
    }
    return _canonical_sha256(payload)


def resolve_nlp_adjudications(
    reports: Sequence[NLPSourceReport],
    annotations: Sequence[NLPHumanAnnotation],
    adjudications: Sequence[NLPAdjudicationDecision],
    *,
    protected_index: ProtectedNLPFinalTestIndex | None = None,
) -> NLPResolutionResult:
    """Resolve only explicit human decisions; matching votes are not consensus."""

    assert_no_protected_final_test_text(
        reports,
        protected_index=protected_index,
    )
    quality = validate_nlp_annotation_quality(
        annotations,
        reports,
        adjudications=adjudications,
    )
    if not quality.valid:
        raise ValueError("annotation quality validation failed: " + "; ".join(quality.errors))

    report_by_id = {item.report_id: item for item in reports}
    if len(report_by_id) != len(reports):
        raise ValueError("source report IDs must be unique")
    annotations_by_report: defaultdict[str, list[NLPHumanAnnotation]] = defaultdict(list)
    for annotation in annotations:
        annotations_by_report[annotation.report_id].append(annotation)
    decisions_by_report: dict[str, NLPAdjudicationDecision] = {}
    for decision in adjudications:
        if decision.report_id in decisions_by_report:
            raise ValueError(
                f"multiple explicit adjudications for report: {decision.report_id}"
            )
        decisions_by_report[decision.report_id] = decision
    unknown_decisions = sorted(set(decisions_by_report) - set(report_by_id))
    if unknown_decisions:
        raise ValueError(f"adjudications reference unknown reports: {unknown_decisions}")

    resolved: list[NLPResolvedAnnotation] = []
    uncertain: list[str] = []
    for report in sorted(reports, key=lambda value: value.report_id):
        report_annotations = annotations_by_report.get(report.report_id, [])
        if not report_annotations:
            raise ValueError(
                f"report has no human annotation: {report.report_id}"
            )
        decision = decisions_by_report.get(report.report_id)
        if decision is None:
            raise ValueError(
                f"report has no explicit adjudication: {report.report_id}"
            )
        actual_annotation_ids = {
            item.annotation_id for item in report_annotations
        }
        if set(decision.annotation_ids) != actual_annotation_ids:
            raise ValueError(
                "adjudication must reference every source annotation for report: "
                f"{report.report_id}"
            )
        expected_metadata = (
            report.event_id_if_known,
            report.incident_id_if_known,
            report.source_report_family,
            report.source_dataset_id,
        )
        for annotation in report_annotations:
            annotation_metadata = (
                annotation.event_id_if_known,
                annotation.incident_id_if_known,
                annotation.source_report_family,
                annotation.source_dataset_id,
            )
            if annotation_metadata != expected_metadata:
                raise ValueError(
                    "annotation grouping/source metadata differs from source report: "
                    f"{annotation.annotation_id}"
                )
            if (
                annotation.source_metadata_if_available
                != report.source_metadata_if_available
            ):
                raise ValueError(
                    "annotation source metadata differs from source report: "
                    f"{annotation.annotation_id}"
                )
        if decision.final_state is NLPAnnotationState.UNCERTAIN:
            uncertain.append(report.report_id)
            continue
        if decision.final_label is None:
            raise ValueError("labeled adjudication is missing final_label")
        languages = {item.language for item in report_annotations}
        if len(languages) != 1:
            raise ValueError(
                "human annotators disagree on language; explicit correction is required: "
                f"{report.report_id}"
            )
        resolved.append(
            NLPResolvedAnnotation(
                report_id=report.report_id,
                text_hash=exact_text_sha256(report.text),
                text=report.text,
                label=decision.final_label,
                language=next(iter(languages)),
                source_metadata_if_available=report.source_metadata_if_available,
                event_id_if_known=report.event_id_if_known,
                incident_id_if_known=report.incident_id_if_known,
                source_report_family=report.source_report_family,
                source_dataset_id=report.source_dataset_id,
                annotation_ids=tuple(sorted(actual_annotation_ids)),
                annotator_ids=tuple(
                    sorted({item.annotator_id for item in report_annotations})
                ),
                adjudication_id=decision.adjudication_id,
                adjudicator_id=decision.adjudicator_id,
                adjudication_timestamp=decision.timestamp,
                adjudication_reason=decision.reason,
                assistance_shown_in_source_annotations=any(
                    item.assistance_shown for item in report_annotations
                ),
            )
        )
    return NLPResolutionResult(
        records=tuple(resolved),
        excluded_uncertain_report_ids=tuple(sorted(uncertain)),
        source_report_count=len(reports),
        explicit_adjudication_count=len(adjudications),
    )


class _DisjointSet:
    def __init__(self, names: Sequence[str]) -> None:
        self.parent = {name: name for name in names}

    def find(self, name: str) -> str:
        parent = self.parent[name]
        if parent != name:
            self.parent[name] = self.find(parent)
        return self.parent[name]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        self.parent[high] = low


def _grouping_keys(record: NLPResolvedAnnotation) -> tuple[str, ...]:
    values = (
        ("event", record.event_id_if_known),
        ("incident", record.incident_id_if_known),
        ("source-family", record.source_report_family),
    )
    return tuple(
        f"{prefix}:{value}"
        for prefix, value in values
        if value is not None
    )


def group_nlp_records(
    records: Sequence[NLPResolvedAnnotation],
) -> NLPGroupingResult:
    """Build transitive groups from all available human/source identifiers."""

    ordered = sorted(records, key=lambda value: value.report_id)
    if not ordered:
        return NLPGroupingResult(
            status="DATA_UNAVAILABLE",
            group_count=0,
            grouped_report_count=0,
        )
    report_ids = [item.report_id for item in ordered]
    if len(report_ids) != len(set(report_ids)):
        raise ValueError("resolved report IDs must be unique")
    sets = _DisjointSet(report_ids)
    first_report_by_key: dict[str, str] = {}
    keys_by_report: dict[str, tuple[str, ...]] = {}
    for record in ordered:
        keys = _grouping_keys(record)
        keys_by_report[record.report_id] = keys
        for key in keys:
            previous = first_report_by_key.setdefault(key, record.report_id)
            sets.union(previous, record.report_id)

    members_by_root: defaultdict[str, list[NLPResolvedAnnotation]] = defaultdict(list)
    for record in ordered:
        members_by_root[sets.find(record.report_id)].append(record)

    group_id_by_report: dict[str, str] = {}
    group_count = 0
    for members in members_by_root.values():
        all_keys = sorted(
            {
                key
                for member in members
                for key in keys_by_report[member.report_id]
            }
        )
        if not all_keys:
            continue
        group_count += 1
        group_id = "nlp-group-" + _canonical_sha256(all_keys)[:20]
        for member in members:
            group_id_by_report[member.report_id] = group_id

    grouped: list[NLPResolvedAnnotation] = []
    ungrouped: list[str] = []
    for record in ordered:
        group_id = group_id_by_report.get(record.report_id)
        if group_id is None:
            ungrouped.append(record.report_id)
        component_members = members_by_root[sets.find(record.report_id)]
        component_keys = tuple(
            sorted(
                {
                    key
                    for member in component_members
                    for key in keys_by_report[member.report_id]
                }
            )
        )
        grouped.append(
            record.model_copy(
                update={
                    "group_id": group_id,
                    "grouping_keys": component_keys,
                }
            )
        )
    status: Literal["COMPLETE", "PARTIAL", "DATA_UNAVAILABLE"]
    if len(ungrouped) == len(grouped):
        status = "DATA_UNAVAILABLE"
    elif ungrouped:
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    return NLPGroupingResult(
        status=status,
        records=tuple(grouped),
        group_count=group_count,
        grouped_report_count=len(grouped) - len(ungrouped),
        ungrouped_report_ids=tuple(ungrouped),
    )


def build_nlp_grouping_plan(grouping: NLPGroupingResult) -> NLPGroupingPlan:
    """Expose complete groups for explicit split assignment without assigning one."""

    records_by_key: defaultdict[str, list[NLPResolvedAnnotation]] = defaultdict(list)
    for record in grouping.records:
        records_by_key[record.split_assignment_key].append(record)
    entries: list[NLPGroupingPlanEntry] = []
    for key, records in sorted(records_by_key.items()):
        entries.append(
            NLPGroupingPlanEntry(
                split_assignment_key=key,
                group_id=records[0].group_id,
                report_ids=tuple(sorted(item.report_id for item in records)),
                event_ids=tuple(
                    sorted(
                        {
                            item.event_id_if_known
                            for item in records
                            if item.event_id_if_known
                        }
                    )
                ),
                incident_ids=tuple(
                    sorted(
                        {
                            item.incident_id_if_known
                            for item in records
                            if item.incident_id_if_known
                        }
                    )
                ),
                source_report_families=tuple(
                    sorted(
                        {
                            item.source_report_family
                            for item in records
                            if item.source_report_family
                        }
                    )
                ),
                source_dataset_ids=tuple(
                    sorted(
                        {
                            item.source_dataset_id
                            for item in records
                            if item.source_dataset_id
                        }
                    )
                ),
            )
        )
    return NLPGroupingPlan(
        grouping_status=grouping.status,
        entries=tuple(entries),
    )


def materialize_nlp_dataset_records(
    grouping: NLPGroupingResult,
    *,
    split_assignments_by_group: Mapping[str, NLPDatasetSplit | str],
    independent_test_dataset_ids: Sequence[str] = (),
) -> tuple[NLPDatasetRecord, ...]:
    """Apply explicit group-level splits; no record-level fallback is used."""

    assignments: dict[str, NLPDatasetSplit] = {}
    for key, value in split_assignments_by_group.items():
        if not str(key).strip():
            raise ValueError("split assignment keys cannot be blank")
        assignments[str(key)] = NLPDatasetSplit(value)
    required_keys = {item.split_assignment_key for item in grouping.records}
    missing = sorted(required_keys - set(assignments))
    extra = sorted(set(assignments) - required_keys)
    if missing or extra:
        raise ValueError(
            f"split assignments must exactly cover groups; missing={missing}, extra={extra}"
        )

    independent_ids = {
        str(value).strip() for value in independent_test_dataset_ids if str(value).strip()
    }
    result: list[NLPDatasetRecord] = []
    for record in grouping.records:
        split = assignments[record.split_assignment_key]
        if split is NLPDatasetSplit.TEST:
            if (
                record.source_dataset_id is None
                or record.source_dataset_id not in independent_ids
            ):
                raise ValueError(
                    "test rows require an explicitly named independent source dataset: "
                    f"{record.report_id}"
                )
        elif record.source_dataset_id in independent_ids:
            raise ValueError(
                "an independent test source cannot also supply train/validation rows: "
                f"{record.report_id}"
            )
        result.append(
            NLPDatasetRecord(
                record_id=record.report_id,
                text=record.text,
                text_hash=record.text_hash,
                event_type=record.label,
                language=record.language,
                split=split,
                group_id=record.group_id,
                grouping_keys=record.grouping_keys,
                event_id_if_known=record.event_id_if_known,
                incident_id_if_known=record.incident_id_if_known,
                source_report_family=record.source_report_family,
                source_dataset_id=record.source_dataset_id,
                source_metadata_if_available=record.source_metadata_if_available,
                annotation_ids=record.annotation_ids,
                annotator_ids=record.annotator_ids,
                adjudication_id=record.adjudication_id,
                adjudicator_id=record.adjudicator_id,
                adjudication_timestamp=record.adjudication_timestamp,
                adjudication_reason=record.adjudication_reason,
                assistance_shown_in_source_annotations=(
                    record.assistance_shown_in_source_annotations
                ),
            )
        )
    test_source_ids = {
        item.source_dataset_id
        for item in result
        if item.split is NLPDatasetSplit.TEST
    }
    non_test_source_ids = {
        item.source_dataset_id
        for item in result
        if item.split is not NLPDatasetSplit.TEST
    }
    overlap = sorted(
        str(value)
        for value in test_source_ids & non_test_source_ids
        if value is not None
    )
    if overlap:
        raise ValueError(f"source datasets cross test boundary: {overlap}")
    if independent_ids and not test_source_ids:
        raise ValueError("independent test dataset IDs were supplied but no test rows exist")
    return tuple(sorted(result, key=lambda value: value.record_id))


def _values_across_splits(
    records: Sequence[NLPDatasetRecord],
    value_getter,
) -> tuple[str, ...]:
    locations: defaultdict[str, set[NLPDatasetSplit]] = defaultdict(set)
    for record in records:
        value = value_getter(record)
        if value:
            locations[str(value)].add(record.split)
    return tuple(sorted(value for value, splits in locations.items() if len(splits) > 1))


def validate_nlp_dataset_leakage(
    records: Sequence[NLPDatasetRecord],
    *,
    protected_index: ProtectedNLPFinalTestIndex | None = None,
    near_duplicate_threshold: float = 0.95,
    maximum_near_duplicate_records: int = 5_000,
    generated_at: datetime | None = None,
) -> NLPDatasetLeakageReport:
    """Check IDs, groups, text variants, and the sealed historical final test."""

    if not 0.0 < near_duplicate_threshold <= 1.0:
        raise ValueError("near_duplicate_threshold must be in (0, 1]")
    index = protected_index or assert_protected_nlp_assets_immutable()
    record_id_leaks = _values_across_splits(records, lambda item: item.record_id)
    group_leaks = _values_across_splits(records, lambda item: item.group_id)
    event_leaks = _values_across_splits(
        records,
        lambda item: item.event_id_if_known,
    )
    incident_leaks = _values_across_splits(
        records,
        lambda item: item.incident_id_if_known,
    )
    family_leaks = _values_across_splits(
        records,
        lambda item: item.source_report_family,
    )
    exact_leaks = _values_across_splits(records, lambda item: item.text_hash)
    normalized_leaks = _values_across_splits(
        records,
        lambda item: normalized_text_sha256(item.text),
    )
    protected_overlap = tuple(
        sorted(
            item.record_id
            for item in records
            if item.text_hash in index.exact_text_hashes
            or normalized_text_sha256(item.text) in index.normalized_text_hashes
        )
    )
    missing_groups = tuple(
        sorted(item.record_id for item in records if item.group_id is None)
    )

    near_pairs: set[str] = set()
    warnings: list[str] = []
    if len(records) > maximum_near_duplicate_records:
        near_status: Literal["COMPLETE", "DATA_UNAVAILABLE"] = "DATA_UNAVAILABLE"
        warnings.append(
            "near-duplicate scan limit exceeded; approval must remain fail-closed"
        )
    else:
        near_status = "COMPLETE"
        normalized = [
            (item, normalize_text_for_leakage(item.text)) for item in records
        ]
        for index_position, (left, left_text) in enumerate(normalized):
            for right, right_text in normalized[index_position + 1 :]:
                if left.split is right.split or left_text == right_text:
                    continue
                if (
                    SequenceMatcher(None, left_text, right_text).ratio()
                    >= near_duplicate_threshold
                ):
                    near_pairs.add("::".join(sorted((left.record_id, right.record_id))))

    errors: list[str] = []
    categories = (
        (record_id_leaks, "record IDs cross splits"),
        (group_leaks, "group IDs cross splits"),
        (event_leaks, "event IDs cross splits"),
        (incident_leaks, "incident IDs cross splits"),
        (family_leaks, "source report families cross splits"),
        (exact_leaks, "exact text crosses splits"),
        (normalized_leaks, "normalized text crosses splits"),
        (near_pairs, "near-duplicate text crosses splits"),
        (protected_overlap, "records overlap the sealed historical final test"),
    )
    errors.extend(message for values, message in categories if values)
    if errors:
        status: Literal["PASS", "FAIL", "INSUFFICIENT_EVIDENCE"] = "FAIL"
    elif missing_groups or near_status == "DATA_UNAVAILABLE":
        status = "INSUFFICIENT_EVIDENCE"
        if missing_groups:
            warnings.append("grouping metadata is incomplete")
    else:
        status = "PASS"
    return NLPDatasetLeakageReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        overall_status=status,
        valid=status == "PASS",
        record_ids_across_splits=record_id_leaks,
        group_ids_across_splits=group_leaks,
        event_ids_across_splits=event_leaks,
        incident_ids_across_splits=incident_leaks,
        source_families_across_splits=family_leaks,
        exact_texts_across_splits=exact_leaks,
        normalized_texts_across_splits=normalized_leaks,
        near_duplicate_pairs_across_splits=tuple(sorted(near_pairs)),
        protected_final_test_overlap=protected_overlap,
        missing_group_report_ids=missing_groups,
        near_duplicate_scan=near_status,
        errors=tuple(sorted(errors)),
        warnings=tuple(sorted(warnings)),
    )


def _jsonl_bytes(records: Sequence[NLPDatasetRecord]) -> bytes:
    lines = [
        json.dumps(
            item.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in sorted(records, key=lambda value: value.record_id)
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def release_nlp_annotation_dataset(
    reports: Sequence[NLPSourceReport],
    annotations: Sequence[NLPHumanAnnotation],
    adjudications: Sequence[NLPAdjudicationDecision],
    *,
    dataset_id: str,
    dataset_version: str,
    output_directory: Path | str,
    registry_path: Path | str,
    split_assignments_by_group: Mapping[str, NLPDatasetSplit | str],
    independent_test_dataset_ids: Sequence[str] = (),
    provenance: DatasetProvenance,
    source_description: str,
    license_or_usage_note: str,
    creation_timestamp: datetime | None = None,
    source_manifest_path: Path | str | None = None,
    source_manifest_hash: str | None = None,
) -> NLPDatasetRelease:
    """Write and register a new immutable candidate dataset version."""

    for name, value in (("dataset_id", dataset_id), ("dataset_version", dataset_version)):
        if not _SAFE_RELEASE_IDENTIFIER.fullmatch(value):
            raise ValueError(f"{name} is not a safe release identifier")
    if provenance is DatasetProvenance.PROVENANCE_UNKNOWN:
        raise ValueError("released annotation datasets require known provenance")
    if not source_description.strip() or not license_or_usage_note.strip():
        raise ValueError("source description and usage note are required")
    timestamp = creation_timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("creation_timestamp must include a timezone")
    selected_source_manifest_path: Path | None = None
    if source_manifest_path is not None:
        selected_source_manifest_path = local_only_path(
            source_manifest_path,
            description="NLP source manifest paths",
        ).resolve()
        if not selected_source_manifest_path.is_file():
            raise ValueError("NLP source manifest evidence is missing")
        actual_source_manifest_hash = hashlib.sha256(
            selected_source_manifest_path.read_bytes()
        ).hexdigest()
        if (
            source_manifest_hash is not None
            and source_manifest_hash != actual_source_manifest_hash
        ):
            raise ValueError("NLP source manifest hash mismatch")
        from app.ml.data.nlp_corpus import NLPCorpusSourceManifest

        source_manifest = NLPCorpusSourceManifest.model_validate_json(
            selected_source_manifest_path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        )
        if source_manifest.provenance_classification is not provenance:
            raise ValueError("release provenance differs from the source manifest")
        enrolled_source_path = local_only_path(
            source_manifest.local_path,
            description="NLP corpus source paths",
        )
        if not enrolled_source_path.is_file():
            raise ValueError("enrolled NLP source is no longer available")
        if (
            hash_dataset_path(enrolled_source_path).content_sha256
            != source_manifest.content_hash
        ):
            raise ValueError("enrolled NLP source content hash changed")
        source_manifest_hash = actual_source_manifest_hash
    elif source_manifest_hash is not None:
        raise ValueError("source_manifest_hash requires source_manifest_path")

    protected_index = assert_protected_nlp_assets_immutable()
    resolution = resolve_nlp_adjudications(
        reports,
        annotations,
        adjudications,
        protected_index=protected_index,
    )
    if not resolution.records:
        raise ValueError("no labeled, explicitly adjudicated records are releasable")
    grouping = group_nlp_records(resolution.records)
    dataset_records = materialize_nlp_dataset_records(
        grouping,
        split_assignments_by_group=split_assignments_by_group,
        independent_test_dataset_ids=independent_test_dataset_ids,
    )
    leakage = validate_nlp_dataset_leakage(
        dataset_records,
        protected_index=protected_index,
        generated_at=timestamp,
    )
    if leakage.overall_status == "FAIL":
        raise ValueError("dataset leakage validation failed: " + "; ".join(leakage.errors))

    root = local_only_path(
        output_directory,
        description="NLP dataset release paths",
    ).resolve()
    release_directory = root / dataset_id / dataset_version
    if release_directory.exists():
        raise FileExistsError(
            "dataset release versions are immutable and already exist: "
            f"{release_directory}"
        )
    release_directory.mkdir(parents=True, exist_ok=False)
    dataset_path = release_directory / "records.jsonl"
    leakage_path = release_directory / "leakage_report.json"
    manifest_path = release_directory / "manifest.json"

    dataset_path.write_bytes(_jsonl_bytes(dataset_records))
    content_hash = hash_dataset_path(dataset_path).content_sha256
    leakage_bytes = (leakage.model_dump_json(indent=2) + "\n").encode("utf-8")
    leakage_path.write_bytes(leakage_bytes)
    leakage_hash = hashlib.sha256(leakage_bytes).hexdigest()
    label_counts = Counter(item.event_type.value for item in dataset_records)
    language_counts = Counter(item.language.value for item in dataset_records)
    split_counts = Counter(item.split.value for item in dataset_records)
    source_hash = _source_evidence_sha256(reports, annotations, adjudications)
    bound_source_manifest_hash = source_manifest_hash or source_hash
    grouping_coverage = (
        grouping.grouped_report_count / len(grouping.records)
        if grouping.records
        else 0.0
    )
    manifest = NLPDatasetVersionManifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        content_hash=content_hash,
        dataset_hash=content_hash,
        source_hash=source_hash,
        source_manifest_hash=bound_source_manifest_hash,
        annotator_count=len({item.annotator_id for item in annotations}),
        adjudicator_count=len({item.adjudicator_id for item in adjudications}),
        label_counts={
            label.value: label_counts.get(label.value, 0) for label in NLPEventLabel
        },
        language_counts={
            language.value: language_counts.get(language.value, 0)
            for language in NLPLanguage
        },
        grouping_status=grouping.status,
        grouping_coverage=grouping_coverage,
        creation_timestamp=timestamp,
        record_count=len(dataset_records),
        split_definition=(
            "explicit assignment of complete connected groups; test rows only from "
            "explicitly identified independent source datasets"
        ),
        split_counts={
            split.value: split_counts.get(split.value, 0) for split in NLPDatasetSplit
        },
        independent_test_dataset_ids=tuple(
            sorted(
                {
                    str(value).strip()
                    for value in independent_test_dataset_ids
                    if str(value).strip()
                }
            )
        ),
        excluded_uncertain_report_ids=resolution.excluded_uncertain_report_ids,
        uncertainty_count=len(resolution.excluded_uncertain_report_ids),
        model_assisted_annotation_count=sum(
            item.assistance_shown for item in annotations
        ),
        protected_final_test_sha256=protected_index.final_test_sha256,
        leakage_status=leakage.overall_status,
        leakage_report_hash=leakage_hash,
    )
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    registry_record = DatasetRegistryRecord(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        component=DatasetComponent.NLP,
        local_path=str(dataset_path),
        format=DatasetFormat.JSONL,
        content_sha256=content_hash,
        schema_version=NLP_DATASET_SCHEMA_VERSION,
        label_schema_version=NLP_LABEL_SCHEMA_VERSION,
        creation_timestamp=timestamp,
        source_description=source_description.strip(),
        provenance=provenance,
        license_or_usage_note=license_or_usage_note.strip(),
        grouping_field="group_id",
        split_field="split",
        label_count=len(dataset_records),
        row_or_image_count=len(dataset_records),
        data_classification=DatasetClassification.CANDIDATE_DATA,
        human_adjudicated=True,
        label_source=HUMAN_LABEL_SOURCE,
        metadata={
            "manifest_path": str(manifest_path),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "leakage_report_path": str(leakage_path),
            "leakage_report_sha256": leakage_hash,
            "dataset_hash": content_hash,
            "source_manifest_hash": bound_source_manifest_hash,
            "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
            "guide_version": ANNOTATION_GUIDE_VERSION,
            "grouping_status": grouping.status,
            "excluded_uncertain_report_ids": list(
                resolution.excluded_uncertain_report_ids
            ),
            "independent_test_dataset_ids": list(
                manifest.independent_test_dataset_ids
            ),
            "protected_final_test_sha256": protected_index.final_test_sha256,
            "automatic_label_generation": "NONE",
        },
    )
    if selected_source_manifest_path is not None:
        registry_record = registry_record.model_copy(
            update={
                "metadata": {
                    **registry_record.metadata,
                    "source_manifest_path": str(selected_source_manifest_path),
                    "source_manifest_sha256": bound_source_manifest_hash,
                }
            }
        )
    register_dataset(
        registry_record,
        registry_path=registry_path,
        replace_existing=False,
        modified_at=timestamp,
    )
    return NLPDatasetRelease(
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        leakage_report_path=leakage_path,
        manifest=manifest,
        leakage=leakage,
        registry_record=registry_record,
    )


__all__ = [
    "HUMAN_LABEL_SOURCE",
    "NLP_DATASET_MANIFEST_VERSION",
    "NLP_DATASET_SCHEMA_VERSION",
    "NLP_GROUPING_STRATEGY",
    "NLP_LABEL_SCHEMA_VERSION",
    "NLPDatasetLeakageReport",
    "NLPDatasetRecord",
    "NLPDatasetRelease",
    "NLPDatasetSplit",
    "NLPDatasetVersionManifest",
    "NLPGroupingPlan",
    "NLPGroupingPlanEntry",
    "NLPGroupingResult",
    "NLPResolutionResult",
    "NLPResolvedAnnotation",
    "build_nlp_grouping_plan",
    "group_nlp_records",
    "materialize_nlp_dataset_records",
    "release_nlp_annotation_dataset",
    "resolve_nlp_adjudications",
    "validate_nlp_dataset_leakage",
]
