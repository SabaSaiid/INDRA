"""Local NLP corpus enrollment and deterministic annotation queues.

This module performs no inference and imports no classifier implementation.  It
only reads explicitly supplied local files, preserves source text, validates
the corpus, protects the sealed historical final test, and creates a queue with
no event labels.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.config import local_only_path
from app.ml.data.nlp_annotations import (
    MODEL_SUGGESTION_BANNER,
    PROTECTED_REPORTS_PATH,
    PROTECTED_V1_ARTIFACT_PATH,
    PROTECTED_V2_ARTIFACT_PATH,
    PROTECTED_V2_RECEIPT_PATH,
    PROTECTED_V2_SPLIT_PATH,
    NLPLanguage,
    NLPSourceReport,
    ProtectedNLPFinalTestIndex,
    assert_protected_nlp_assets_immutable,
    exact_text_sha256,
    normalize_text_for_leakage,
    normalized_text_sha256,
)
from app.ml.data.registry import DatasetProvenance, hash_dataset_path

NLP_CORPUS_SCHEMA_VERSION = "raw-nlp-report-v1"
NLP_CORPUS_SOURCE_MANIFEST_VERSION = "nlp-corpus-source-manifest-v1"
NLP_CORPUS_VALIDATION_VERSION = "nlp-corpus-validation-v1"
NLP_CORPUS_ENROLLMENT_VERSION = "nlp-corpus-enrollment-v1"
NLP_ANNOTATION_QUEUE_VERSION = "nlp-annotation-queue-v1"
NLP_ANNOTATION_QUEUE_REPORT_VERSION = "nlp-annotation-queue-report-v1"

SOURCE_MANIFEST_FILE = "source_manifest.json"
VALIDATION_REPORT_FILE = "corpus_validation_report.json"
NORMALIZED_CORPUS_FILE = "records.jsonl"
ENROLLMENT_MANIFEST_FILE = "enrollment_manifest.json"
ANNOTATION_QUEUE_FILE = "annotation_queue.json"
ANNOTATION_QUEUE_REPORT_FILE = "annotation_queue_report.json"

_SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "report_id": ("report_id", "id"),
    "text": ("text", "original_text"),
    "observed_at": ("observed_at",),
    "submitted_at": ("submitted_at",),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng"),
    "source_type": ("source_type",),
    "source_id": ("source_id",),
    "event_id": ("event_id", "event_id_if_known"),
    "incident_id": ("incident_id", "incident_id_if_known"),
    "source_report_family": ("source_report_family", "report_family_id"),
    "language": ("language", "language_hint", "lang"),
}

_LANGUAGE_ALIASES = {
    "en": NLPLanguage.ENGLISH,
    "english": NLPLanguage.ENGLISH,
    "hi": NLPLanguage.HINDI,
    "hindi": NLPLanguage.HINDI,
    "hinglish": NLPLanguage.HINGLISH,
    "other": NLPLanguage.OTHER,
    "unknown": NLPLanguage.UNKNOWN,
}


class CorpusValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CorpusGroupingStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    GROUPING_NOT_AVAILABLE = "GROUPING_NOT_AVAILABLE"


class NLPQueueSamplingStrategy(str, Enum):
    RANDOM = "RANDOM"
    LANGUAGE_BALANCED = "LANGUAGE_BALANCED"
    GROUP_BALANCED = "GROUP_BALANCED"
    SOURCE_BALANCED = "SOURCE_BALANCED"
    UNCERTAINTY_REVIEW = "UNCERTAINTY_REVIEW"
    MODEL_ERROR_REVIEW = "MODEL_ERROR_REVIEW"


class NLPAnnotationQueueStatus(str, Enum):
    UNANNOTATED = "UNANNOTATED"
    IN_REVIEW = "IN_REVIEW"
    LABELED = "LABELED"
    UNCERTAIN = "UNCERTAIN"
    ADJUDICATION_REQUIRED = "ADJUDICATION_REQUIRED"
    RELEASED = "RELEASED"


class RawNLPReportProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_classification: DatasetProvenance
    source_row_number: int = Field(ge=1)


class RawNLPReport(BaseModel):
    """One valid normalized record with immutable original text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["raw-nlp-report-v1"] = NLP_CORPUS_SCHEMA_VERSION
    report_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    observed_at: datetime | None = None
    submitted_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    source_type: str | None = Field(default=None, min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    event_id: str | None = Field(default=None, min_length=1)
    incident_id: str | None = Field(default=None, min_length=1)
    source_report_family: str | None = Field(default=None, min_length=1)
    language: NLPLanguage
    original_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: RawNLPReportProvenance

    @model_validator(mode="after")
    def validate_preserved_record(self) -> RawNLPReport:
        if self.text != self.original_text:
            raise ValueError("text must be the exact preserved original_text")
        if not self.original_text.strip():
            raise ValueError("original_text cannot be empty or whitespace")
        expected_normalized = normalize_text_for_leakage(self.original_text)
        if self.normalized_text != expected_normalized:
            raise ValueError("normalized_text is not deterministically derived")
        if self.original_text_sha256 != exact_text_sha256(self.original_text):
            raise ValueError("original_text_sha256 does not match original_text")
        if self.normalized_text_sha256 != exact_text_sha256(self.normalized_text):
            raise ValueError("normalized_text_sha256 does not match normalized_text")
        for name in ("observed_at", "submitted_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must include a timezone")
        if (self.latitude is None) is not (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class NLPCorpusSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal["nlp-corpus-source-manifest-v1"] = (
        NLP_CORPUS_SOURCE_MANIFEST_VERSION
    )
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    source_description: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_classification: DatasetProvenance
    creation_timestamp: datetime
    input_format: Literal["CSV", "JSON", "JSONL", "PARQUET"]

    @field_validator("creation_timestamp")
    @classmethod
    def creation_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        return value


class CorpusValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: Literal["ERROR", "WARNING"]
    message: str = Field(min_length=1)
    row_number: int | None = Field(default=None, ge=1)
    report_id: str | None = None
    raw_record_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    details: dict[str, Any] = Field(default_factory=dict)


class FinalTestOverlapRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_identifier: str = Field(min_length=1)
    row_number: int = Field(ge=1)
    original_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    match_types: tuple[Literal["EXACT", "NORMALIZED"], ...] = Field(min_length=1)


class CorpusDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    earliest: datetime | None = None
    latest: datetime | None = None


class NLPCorpusValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["nlp-corpus-validation-v1"] = NLP_CORPUS_VALIDATION_VERSION
    generated_at: datetime
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CorpusValidationStatus
    valid: bool
    input_record_count: int = Field(ge=0)
    normalized_record_count: int = Field(ge=0)
    missing_report_id_count: int = Field(ge=0)
    missing_text_count: int = Field(ge=0)
    empty_text_count: int = Field(ge=0)
    duplicate_report_ids: tuple[str, ...] = ()
    exact_duplicate_text_hashes: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    normalized_duplicate_text_hashes: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    invalid_timestamp_count: int = Field(ge=0)
    invalid_coordinate_count: int = Field(ge=0)
    encoding_problem_count: int = Field(ge=0)
    invalid_language_count: int = Field(ge=0)
    inconsistent_group_identifier_count: int = Field(ge=0)
    final_test_overlap: tuple[FinalTestOverlapRecord, ...] = ()
    grouping_status: CorpusGroupingStatus
    grouped_count: int = Field(ge=0)
    ungrouped_count: int = Field(ge=0)
    language_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    date_range: CorpusDateRange = Field(default_factory=CorpusDateRange)
    issues: tuple[CorpusValidationIssue, ...] = ()

    @model_validator(mode="after")
    def validation_status_is_coherent(self) -> NLPCorpusValidationReport:
        errors = [item for item in self.issues if item.severity == "ERROR"]
        if self.valid != (self.status is CorpusValidationStatus.PASS):
            raise ValueError("valid and status disagree")
        if self.valid and errors:
            raise ValueError("a valid corpus cannot contain ERROR issues")
        if not self.valid and not errors:
            raise ValueError("an invalid corpus must contain an ERROR issue")
        if self.final_test_overlap and not any(
            item.code == "FINAL_TEST_OVERLAP_DETECTED" for item in self.issues
        ):
            raise ValueError("final-test overlap requires its fail-closed issue code")
        return self


class NLPCorpusEnrollmentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enrollment_version: Literal["nlp-corpus-enrollment-v1"] = (
        NLP_CORPUS_ENROLLMENT_VERSION
    )
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    creation_timestamp: datetime
    source_manifest_file: Literal["source_manifest.json"] = SOURCE_MANIFEST_FILE
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_file: Literal["corpus_validation_report.json"] = (
        VALIDATION_REPORT_FILE
    )
    validation_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_corpus_file: Literal["records.jsonl"] | None = None
    normalized_corpus_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    record_count: int = Field(ge=0)
    validation_status: CorpusValidationStatus
    annotation_readiness: Literal["READY", "BLOCKED"]
    automatic_label_generation: Literal["NONE"] = "NONE"
    model_invocation: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def readiness_is_fail_closed(self) -> NLPCorpusEnrollmentManifest:
        ready = self.annotation_readiness == "READY"
        if ready != (self.validation_status is CorpusValidationStatus.PASS):
            raise ValueError("annotation readiness must follow validation status")
        if ready and (
            self.normalized_corpus_file is None
            or self.normalized_corpus_hash is None
            or self.record_count < 1
        ):
            raise ValueError("ready enrollment requires a non-empty normalized corpus")
        if not ready and (
            self.normalized_corpus_file is not None
            or self.normalized_corpus_hash is not None
        ):
            raise ValueError("blocked enrollment cannot publish a normalized corpus")
        return self


class NLPCorpusEnrollmentResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    enrollment_directory: Path
    source_manifest_path: Path
    validation_report_path: Path
    normalized_corpus_path: Path | None = None
    enrollment_manifest_path: Path
    source_manifest: NLPCorpusSourceManifest
    validation_report: NLPCorpusValidationReport
    enrollment_manifest: NLPCorpusEnrollmentManifest


class LoadedNLPCorpus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    enrollment_directory: Path
    source_manifest_path: Path
    validation_report_path: Path
    normalized_corpus_path: Path
    source_manifest: NLPCorpusSourceManifest
    validation_report: NLPCorpusValidationReport
    enrollment_manifest: NLPCorpusEnrollmentManifest
    reports: tuple[RawNLPReport, ...]


class NLPQueueGroupingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str | None = None
    incident_id: str | None = None
    source_report_family: str | None = None
    supplied_grouping_keys: tuple[str, ...] = ()
    component_group_id: str | None = None
    grouping_status: Literal["GROUPED", "GROUPING_NOT_AVAILABLE"]


class NLPAnnotationQueueItem(BaseModel):
    """A priority record.  There is deliberately no event-label field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: str = Field(pattern=r"^nlpq-[0-9a-f]{24}$")
    report_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: NLPLanguage
    grouping_metadata: NLPQueueGroupingMetadata
    annotation_status: Literal[NLPAnnotationQueueStatus.UNANNOTATED] = (
        NLPAnnotationQueueStatus.UNANNOTATED
    )
    priority_rank: int = Field(ge=1)
    priority_selected: bool
    source_type: str | None = None
    source_id: str | None = None


class NLPAnnotationQueue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_version: Literal["nlp-annotation-queue-v1"] = NLP_ANNOTATION_QUEUE_VERSION
    created_at: datetime
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampling_strategy: NLPQueueSamplingStrategy
    seed: int
    selection_parameters: dict[str, Any] = Field(default_factory=dict)
    blind_annotation: bool = True
    model_assistance_shown: bool = False
    assistance_banner: Literal["MODEL SUGGESTION — NOT GROUND TRUTH"] | None = None
    underlying_distribution_unchanged: Literal[True] = True
    automatic_labels: Literal["NONE"] = "NONE"
    items: tuple[NLPAnnotationQueueItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def queue_is_coherent_and_unlabelled(self) -> NLPAnnotationQueue:
        if self.blind_annotation and self.model_assistance_shown:
            raise ValueError("blind annotation cannot show model assistance")
        if self.model_assistance_shown:
            if self.assistance_banner != MODEL_SUGGESTION_BANNER:
                raise ValueError("assisted mode requires the non-ground-truth banner")
        elif self.assistance_banner is not None:
            raise ValueError("blind/default queues cannot contain an assistance banner")
        if len({item.queue_id for item in self.items}) != len(self.items):
            raise ValueError("queue IDs must be unique")
        if len({item.report_id for item in self.items}) != len(self.items):
            raise ValueError("queue report IDs must be unique")
        if [item.priority_rank for item in self.items] != list(
            range(1, len(self.items) + 1)
        ):
            raise ValueError("priority ranks must be contiguous and ordered")
        expected_identity = {(self.dataset_id, self.dataset_version)}
        actual_identity = {
            (item.dataset_id, item.dataset_version) for item in self.items
        }
        if actual_identity != expected_identity:
            raise ValueError("queue items must match the queue dataset identity")
        return self


class NLPAnnotationQueueReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["nlp-annotation-queue-report-v1"] = (
        NLP_ANNOTATION_QUEUE_REPORT_VERSION
    )
    generated_at: datetime
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    queue_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_reports: int = Field(ge=0)
    english_count: int = Field(ge=0)
    hindi_count: int = Field(ge=0)
    hinglish_count: int = Field(ge=0)
    other_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    grouped_count: int = Field(ge=0)
    ungrouped_count: int = Field(ge=0)
    source_counts: dict[str, int] = Field(default_factory=dict)
    date_range: CorpusDateRange = Field(default_factory=CorpusDateRange)
    duplicate_report_id_count: int = Field(ge=0)
    exact_duplicate_text_count: int = Field(ge=0)
    normalized_duplicate_text_count: int = Field(ge=0)
    empty_text_count: int = Field(ge=0)
    sampling_strategy: NLPQueueSamplingStrategy
    seed: int
    selection_parameters: dict[str, Any] = Field(default_factory=dict)
    blind_annotation: bool
    model_assistance_shown: bool
    automatic_labels: Literal["NONE"] = "NONE"


class NLPAnnotationQueueResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    output_directory: Path
    queue_path: Path
    report_path: Path
    queue: NLPAnnotationQueue
    report: NLPAnnotationQueueReport


class NLPAnnotationQueueStatusEvent(BaseModel):
    """Append-only workflow state; it intentionally carries no event label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(pattern=r"^nlpq-event-[0-9a-f]{24}$")
    queue_id: str = Field(pattern=r"^nlpq-[0-9a-f]{24}$")
    report_id: str = Field(min_length=1)
    previous_status: NLPAnnotationQueueStatus
    annotation_status: NLPAnnotationQueueStatus
    actor_id: str = Field(min_length=1)
    timestamp: datetime
    reason: str = Field(min_length=1)
    annotation_reference: str | None = Field(default=None, min_length=1)
    adjudication_id: str | None = Field(default=None, min_length=1)
    released_dataset_version: str | None = Field(default=None, min_length=1)

    @field_validator("actor_id", "reason")
    @classmethod
    def human_fields_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("queue status actor and reason cannot be blank")
        return value.strip()

    @field_validator("timestamp")
    @classmethod
    def status_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("queue status timestamp must include a timezone")
        return value


_ALLOWED_QUEUE_TRANSITIONS: dict[
    NLPAnnotationQueueStatus,
    frozenset[NLPAnnotationQueueStatus],
] = {
    NLPAnnotationQueueStatus.UNANNOTATED: frozenset(
        {NLPAnnotationQueueStatus.IN_REVIEW}
    ),
    NLPAnnotationQueueStatus.IN_REVIEW: frozenset(
        {
            NLPAnnotationQueueStatus.LABELED,
            NLPAnnotationQueueStatus.UNCERTAIN,
            NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED,
        }
    ),
    NLPAnnotationQueueStatus.LABELED: frozenset(
        {
            NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED,
            NLPAnnotationQueueStatus.RELEASED,
        }
    ),
    NLPAnnotationQueueStatus.UNCERTAIN: frozenset(
        {NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED}
    ),
    NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED: frozenset(
        {
            NLPAnnotationQueueStatus.LABELED,
            NLPAnnotationQueueStatus.UNCERTAIN,
            NLPAnnotationQueueStatus.RELEASED,
        }
    ),
    NLPAnnotationQueueStatus.RELEASED: frozenset(),
}


def queue_statuses(
    queue: NLPAnnotationQueue,
    events: Sequence[NLPAnnotationQueueStatusEvent],
) -> dict[str, NLPAnnotationQueueStatus]:
    """Validate an event stream and return the effective status per report."""

    item_by_report = {item.report_id: item for item in queue.items}
    item_by_queue = {item.queue_id: item for item in queue.items}
    statuses = {
        item.report_id: NLPAnnotationQueueStatus(item.annotation_status)
        for item in queue.items
    }
    event_ids: set[str] = set()
    for event in events:
        if event.event_id in event_ids:
            raise ValueError(f"duplicate queue status event: {event.event_id}")
        event_ids.add(event.event_id)
        item = item_by_report.get(event.report_id)
        if item is None or item_by_queue.get(event.queue_id) != item:
            raise ValueError("queue status event references an unknown queue item")
        current = statuses[event.report_id]
        if event.previous_status is not current:
            raise ValueError(
                "queue status event previous_status does not match current state"
            )
        if event.annotation_status not in _ALLOWED_QUEUE_TRANSITIONS[current]:
            raise ValueError(
                f"invalid queue status transition: {current.value} -> "
                f"{event.annotation_status.value}"
            )
        if event.annotation_status in {
            NLPAnnotationQueueStatus.LABELED,
            NLPAnnotationQueueStatus.UNCERTAIN,
            NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED,
        } and not (event.annotation_reference or event.adjudication_id):
            raise ValueError(
                "annotation/adjudication queue states require an evidence reference"
            )
        if event.annotation_status is NLPAnnotationQueueStatus.RELEASED and (
            not event.adjudication_id or not event.released_dataset_version
        ):
            raise ValueError(
                "RELEASED requires explicit adjudication and dataset-version evidence"
            )
        statuses[event.report_id] = event.annotation_status
    return statuses


def create_queue_status_event(
    queue: NLPAnnotationQueue,
    existing_events: Sequence[NLPAnnotationQueueStatusEvent],
    *,
    report_id: str,
    annotation_status: NLPAnnotationQueueStatus,
    actor_id: str,
    reason: str,
    timestamp: datetime | None = None,
    annotation_reference: str | None = None,
    adjudication_id: str | None = None,
    released_dataset_version: str | None = None,
) -> NLPAnnotationQueueStatusEvent:
    """Create one deterministic event after validating the full prior stream."""

    statuses = queue_statuses(queue, existing_events)
    item_by_report = {item.report_id: item for item in queue.items}
    if report_id not in item_by_report:
        raise ValueError(f"unknown queue report_id: {report_id}")
    selected_timestamp = timestamp or datetime.now(timezone.utc)
    payload = {
        "queue_id": item_by_report[report_id].queue_id,
        "report_id": report_id,
        "previous_status": statuses[report_id].value,
        "annotation_status": annotation_status.value,
        "actor_id": actor_id.strip(),
        "timestamp": selected_timestamp.isoformat(),
        "reason": reason.strip(),
        "annotation_reference": annotation_reference,
        "adjudication_id": adjudication_id,
        "released_dataset_version": released_dataset_version,
    }
    event = NLPAnnotationQueueStatusEvent(
        event_id="nlpq-event-" + _canonical_sha256(payload)[:24],
        **payload,
    )
    queue_statuses(queue, [*existing_events, event])
    return event


class NLPAnnotationQueueStatusStore:
    """Append-only local JSONL event store for queue workflow state."""

    def __init__(self, path: Path | str) -> None:
        selected = local_only_path(
            path,
            description="NLP queue status paths",
        ).resolve()
        protected = {
            path.resolve()
            for path in (
                PROTECTED_REPORTS_PATH,
                PROTECTED_V1_ARTIFACT_PATH,
                PROTECTED_V2_ARTIFACT_PATH,
                PROTECTED_V2_SPLIT_PATH,
                PROTECTED_V2_RECEIPT_PATH,
            )
        }
        if selected in protected:
            raise ValueError("queue status output cannot target a protected NLP file")
        self.path = selected

    def load(self) -> list[NLPAnnotationQueueStatusEvent]:
        if not self.path.exists():
            return []
        events: list[NLPAnnotationQueueStatusEvent] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8", errors="strict").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                events.append(NLPAnnotationQueueStatusEvent.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"invalid queue status event at line {line_number}: {error}"
                ) from error
        return events

    def append(
        self,
        queue: NLPAnnotationQueue,
        event: NLPAnnotationQueueStatusEvent,
    ) -> None:
        existing = self.load()
        if any(item.event_id == event.event_id for item in existing):
            raise ValueError(f"queue status event already exists: {event.event_id}")
        queue_statuses(queue, [*existing, event])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")


@dataclass(frozen=True)
class _SourceReadResult:
    rows: tuple[tuple[int, Mapping[str, Any]], ...]
    issues: tuple[CorpusValidationIssue, ...]
    input_record_count: int


@dataclass(frozen=True)
class _TextEvidence:
    row_number: int
    record_identifier: str
    raw_record_hash: str | None
    original_hash: str
    normalized_hash: str


def _validate_safe_identifier(name: str, value: str) -> str:
    selected = value.strip()
    if (
        not selected
        or not selected[0].isalnum()
        or any(character not in _SAFE_ID_CHARS for character in selected)
    ):
        raise ValueError(f"{name} is not a safe local identifier")
    if selected.endswith(".") or selected.split(".", maxsplit=1)[0].upper() in (
        _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError(f"{name} is a reserved local path name")
    return selected


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _model_json_bytes(model: BaseModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe_raw(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite numeric values are invalid")
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe_raw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe_raw(item) for item in value]
    raise TypeError(f"unsupported local record value type: {type(value).__name__}")


def _issue(
    code: str,
    message: str,
    *,
    severity: Literal["ERROR", "WARNING"] = "ERROR",
    row_number: int | None = None,
    report_id: str | None = None,
    raw_record_hash: str | None = None,
    details: dict[str, Any] | None = None,
) -> CorpusValidationIssue:
    return CorpusValidationIssue(
        code=code,
        severity=severity,
        message=message,
        row_number=row_number,
        report_id=report_id,
        raw_record_hash=raw_record_hash,
        details=details or {},
    )


def _read_utf8(path: Path) -> tuple[str | None, CorpusValidationIssue | None]:
    try:
        return path.read_text(encoding="utf-8", errors="strict"), None
    except UnicodeError as error:
        return None, _issue(
            "ENCODING_ERROR",
            f"source is not valid UTF-8: {error}",
        )


def _read_source_rows(path: Path) -> _SourceReadResult:
    suffix = path.suffix.casefold()
    issues: list[CorpusValidationIssue] = []
    rows: list[tuple[int, Mapping[str, Any]]] = []
    input_record_count = 0
    if suffix in {".csv", ".json", ".jsonl"}:
        text, encoding_issue = _read_utf8(path)
        if encoding_issue is not None:
            return _SourceReadResult((), (encoding_issue,), 0)
        assert text is not None
        try:
            if suffix == ".csv":
                reader = csv.DictReader(io.StringIO(text, newline=""))
                fieldnames = reader.fieldnames or []
                if not fieldnames:
                    issues.append(_issue("SOURCE_PARSE_ERROR", "CSV header is missing"))
                elif len(fieldnames) != len(set(fieldnames)):
                    issues.append(
                        _issue("SOURCE_PARSE_ERROR", "CSV contains duplicate headers")
                    )
                for row_number, row in enumerate(reader, start=1):
                    input_record_count += 1
                    rows.append((row_number, row))
            elif suffix == ".json":
                payload = json.loads(text)
                payload_rows = (
                    payload.get("reports") if isinstance(payload, dict) else payload
                )
                if not isinstance(payload_rows, list):
                    issues.append(
                        _issue(
                            "SOURCE_PARSE_ERROR",
                            "JSON must be a list or contain a reports list",
                        )
                    )
                else:
                    input_record_count = len(payload_rows)
                    for row_number, row in enumerate(payload_rows, start=1):
                        if not isinstance(row, Mapping):
                            issues.append(
                                _issue(
                                    "SOURCE_RECORD_NOT_OBJECT",
                                    "source record is not an object",
                                    row_number=row_number,
                                )
                            )
                        else:
                            rows.append((row_number, row))
            else:
                for physical_line, line in enumerate(text.splitlines(), start=1):
                    if not line.strip():
                        continue
                    input_record_count += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as error:
                        issues.append(
                            _issue(
                                "SOURCE_PARSE_ERROR",
                                f"invalid JSONL record: {error}",
                                row_number=physical_line,
                            )
                        )
                        continue
                    if not isinstance(row, Mapping):
                        issues.append(
                            _issue(
                                "SOURCE_RECORD_NOT_OBJECT",
                                "source record is not an object",
                                row_number=physical_line,
                            )
                        )
                    else:
                        rows.append((physical_line, row))
        except (csv.Error, json.JSONDecodeError) as error:
            issues.append(_issue("SOURCE_PARSE_ERROR", str(error)))
    elif suffix in {".parquet", ".pq"}:
        try:
            from pyarrow import (  # type: ignore[import-not-found]
                ArrowException,
                parquet,
            )
        except ImportError:
            issues.append(
                _issue(
                    "PARQUET_SUPPORT_UNAVAILABLE",
                    "Parquet requires the optional local pyarrow dependency",
                )
            )
        else:
            try:
                payload_rows = parquet.read_table(path).to_pylist()
            except (ArrowException, OSError, TypeError, ValueError) as error:
                issues.append(
                    _issue(
                        "SOURCE_PARSE_ERROR",
                        f"invalid local Parquet source: {type(error).__name__}: {error}",
                    )
                )
            else:
                input_record_count = len(payload_rows)
                for row_number, row in enumerate(payload_rows, start=1):
                    if not isinstance(row, Mapping):
                        issues.append(
                            _issue(
                                "SOURCE_RECORD_NOT_OBJECT",
                                "Parquet row is not an object",
                                row_number=row_number,
                            )
                        )
                    else:
                        rows.append((row_number, row))
    else:
        raise ValueError("local NLP corpus must be CSV, JSON, JSONL, or Parquet")
    return _SourceReadResult(tuple(rows), tuple(issues), input_record_count)


def _value_is_present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _extract_value(
    row: Mapping[str, Any],
    field: str,
    *,
    row_number: int,
    issues: list[CorpusValidationIssue],
) -> Any:
    aliases = _FIELD_ALIASES[field]
    supplied = [(name, row[name]) for name in aliases if name in row]
    present = [(name, value) for name, value in supplied if _value_is_present(value)]
    if len(present) > 1:
        try:
            canonical_values = {
                _canonical_sha256(_json_safe_raw(value)) for _, value in present
            }
        except (TypeError, UnicodeError, ValueError):
            canonical_values = {repr(value) for _, value in present}
        if len(canonical_values) > 1:
            issues.append(
                _issue(
                    "AMBIGUOUS_FIELD_MAPPING",
                    f"conflicting aliases supplied for {field}",
                    row_number=row_number,
                    details={"aliases": [name for name, _ in present]},
                )
            )
    if present:
        return present[0][1]
    if supplied:
        return supplied[0][1]
    return None


def _optional_string(
    value: Any,
    field: str,
    *,
    row_number: int,
    report_id: str | None,
    issues: list[CorpusValidationIssue],
) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="strict")
        except UnicodeError as error:
            issues.append(
                _issue(
                    "ENCODING_ERROR",
                    f"{field} is not valid UTF-8: {error}",
                    row_number=row_number,
                    report_id=report_id,
                )
            )
            return None
    if not isinstance(value, str):
        issues.append(
            _issue(
                "INVALID_FIELD_TYPE",
                f"{field} must be a string when supplied",
                row_number=row_number,
                report_id=report_id,
                details={"field": field, "type": type(value).__name__},
            )
        )
        return None
    return value.strip() or None


def _parse_timestamp(
    value: Any,
    field: str,
    *,
    row_number: int,
    report_id: str | None,
    issues: list[CorpusValidationIssue],
) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            candidate = value.strip()
            if candidate.endswith(("Z", "z")):
                candidate = candidate[:-1] + "+00:00"
            parsed = datetime.fromisoformat(candidate)
        else:
            raise TypeError("timestamp must be an ISO-8601 string or datetime")
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return parsed
    except (TypeError, ValueError) as error:
        issues.append(
            _issue(
                "INVALID_TIMESTAMP",
                f"invalid {field}: {error}",
                row_number=row_number,
                report_id=report_id,
                details={"field": field},
            )
        )
        return None


def _parse_coordinate(
    value: Any,
    field: Literal["latitude", "longitude"],
    *,
    row_number: int,
    report_id: str | None,
    issues: list[CorpusValidationIssue],
) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not a coordinate")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("coordinate must be finite")
        lower, upper = (-90.0, 90.0) if field == "latitude" else (-180.0, 180.0)
        if not lower <= parsed <= upper:
            raise ValueError(f"coordinate must be in [{lower}, {upper}]")
        return parsed
    except (TypeError, ValueError) as error:
        issues.append(
            _issue(
                "INVALID_COORDINATE",
                f"invalid {field}: {error}",
                row_number=row_number,
                report_id=report_id,
                details={"field": field},
            )
        )
        return None


def _parse_language(
    value: Any,
    *,
    row_number: int,
    report_id: str | None,
    issues: list[CorpusValidationIssue],
) -> NLPLanguage:
    if value is None or (isinstance(value, str) and not value.strip()):
        return NLPLanguage.UNKNOWN
    if isinstance(value, NLPLanguage):
        return value
    if not isinstance(value, str):
        issues.append(
            _issue(
                "INVALID_LANGUAGE",
                "language must be English, Hindi, Hinglish, Other, or Unknown",
                row_number=row_number,
                report_id=report_id,
            )
        )
        return NLPLanguage.UNKNOWN
    normalized = value.strip().casefold()
    language = _LANGUAGE_ALIASES.get(normalized)
    if language is None:
        issues.append(
            _issue(
                "INVALID_LANGUAGE",
                f"unsupported supplied language value: {value!r}",
                row_number=row_number,
                report_id=report_id,
            )
        )
        return NLPLanguage.UNKNOWN
    return language


def _source_key(report: RawNLPReport) -> str:
    return f"{report.source_type or 'UNKNOWN'}::{report.source_id or 'UNKNOWN'}"


def _date_range(reports: Sequence[RawNLPReport]) -> CorpusDateRange:
    values = sorted(
        value
        for report in reports
        for value in (report.observed_at, report.submitted_at)
        if value is not None
    )
    return CorpusDateRange(
        earliest=values[0] if values else None,
        latest=values[-1] if values else None,
    )


def _grouping_status(reports: Sequence[RawNLPReport]) -> CorpusGroupingStatus:
    grouped = sum(
        bool(report.event_id or report.incident_id or report.source_report_family)
        for report in reports
    )
    if grouped == 0:
        return CorpusGroupingStatus.GROUPING_NOT_AVAILABLE
    if grouped == len(reports):
        return CorpusGroupingStatus.COMPLETE
    return CorpusGroupingStatus.PARTIAL


def _inconsistent_group_issues(
    reports: Sequence[RawNLPReport],
) -> list[CorpusValidationIssue]:
    fields = ("event_id", "incident_id", "source_report_family")
    issues: list[CorpusValidationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for anchor_field in fields:
        for related_field in fields:
            if anchor_field == related_field:
                continue
            mappings: defaultdict[str, set[str]] = defaultdict(set)
            report_ids: defaultdict[str, set[str]] = defaultdict(set)
            for report in reports:
                anchor = getattr(report, anchor_field)
                related = getattr(report, related_field)
                if anchor and related:
                    mappings[anchor].add(related)
                    report_ids[anchor].add(report.report_id)
            for anchor, related_values in sorted(mappings.items()):
                if len(related_values) < 2:
                    continue
                identity = (anchor_field, anchor, related_field)
                if identity in seen:
                    continue
                seen.add(identity)
                issues.append(
                    _issue(
                        "INCONSISTENT_GROUP_IDENTIFIERS",
                        f"{anchor_field} maps to multiple {related_field} values",
                        details={
                            "anchor_field": anchor_field,
                            "anchor_value": anchor,
                            "related_field": related_field,
                            "related_values": sorted(related_values),
                            "report_ids": sorted(report_ids[anchor]),
                        },
                    )
                )
    return issues


def _normalize_rows(
    read_result: _SourceReadResult,
    manifest: NLPCorpusSourceManifest,
    protected_index: ProtectedNLPFinalTestIndex,
) -> tuple[
    tuple[RawNLPReport, ...],
    tuple[_TextEvidence, ...],
    tuple[CorpusValidationIssue, ...],
]:
    reports: list[RawNLPReport] = []
    text_evidence: list[_TextEvidence] = []
    report_id_evidence: defaultdict[str, list[int]] = defaultdict(list)
    issues = list(read_result.issues)
    for row_number, row in read_result.rows:
        row_issues: list[CorpusValidationIssue] = []
        try:
            safe_raw = _json_safe_raw(row)
            raw_record_hash = _canonical_sha256(safe_raw)
        except UnicodeError as error:
            raw_record_hash = None
            row_issues.append(
                _issue(
                    "ENCODING_ERROR",
                    f"record contains invalid UTF-8 bytes: {error}",
                    row_number=row_number,
                )
            )
        except (TypeError, ValueError) as error:
            raw_record_hash = None
            row_issues.append(
                _issue(
                    "INVALID_RECORD_VALUE",
                    str(error),
                    row_number=row_number,
                )
            )

        report_id_value = _extract_value(
            row,
            "report_id",
            row_number=row_number,
            issues=row_issues,
        )
        report_id: str | None
        if report_id_value is None:
            report_id = None
            row_issues.append(
                _issue(
                    "MISSING_REPORT_ID",
                    "report_id is required",
                    row_number=row_number,
                    raw_record_hash=raw_record_hash,
                )
            )
        elif not isinstance(report_id_value, str):
            report_id = None
            row_issues.append(
                _issue(
                    "INVALID_FIELD_TYPE",
                    "report_id must be a string",
                    row_number=row_number,
                    raw_record_hash=raw_record_hash,
                    details={"field": "report_id"},
                )
            )
        else:
            report_id = report_id_value.strip()
            if not report_id:
                row_issues.append(
                    _issue(
                        "MISSING_REPORT_ID",
                        "report_id cannot be empty",
                        row_number=row_number,
                        raw_record_hash=raw_record_hash,
                    )
                )
            else:
                report_id_evidence[report_id].append(row_number)

        text_value = _extract_value(
            row,
            "text",
            row_number=row_number,
            issues=row_issues,
        )
        original_text: str | None = None
        if text_value is None:
            row_issues.append(
                _issue(
                    "MISSING_TEXT",
                    "text is required",
                    row_number=row_number,
                    report_id=report_id,
                    raw_record_hash=raw_record_hash,
                )
            )
        elif isinstance(text_value, bytes):
            try:
                original_text = text_value.decode("utf-8", errors="strict")
            except UnicodeError as error:
                row_issues.append(
                    _issue(
                        "ENCODING_ERROR",
                        f"text is not valid UTF-8: {error}",
                        row_number=row_number,
                        report_id=report_id,
                        raw_record_hash=raw_record_hash,
                    )
                )
        elif not isinstance(text_value, str):
            row_issues.append(
                _issue(
                    "INVALID_FIELD_TYPE",
                    "text must be a string",
                    row_number=row_number,
                    report_id=report_id,
                    raw_record_hash=raw_record_hash,
                    details={"field": "text"},
                )
            )
        else:
            original_text = text_value
        if original_text is not None and not original_text.strip():
            row_issues.append(
                _issue(
                    "EMPTY_TEXT",
                    "text cannot be empty or whitespace",
                    row_number=row_number,
                    report_id=report_id,
                    raw_record_hash=raw_record_hash,
                )
            )
        if original_text is not None and original_text.strip():
            original_hash = exact_text_sha256(original_text)
            normalized_hash = normalized_text_sha256(original_text)
            text_evidence.append(
                _TextEvidence(
                    row_number=row_number,
                    record_identifier=report_id or f"<row:{row_number}>",
                    raw_record_hash=raw_record_hash,
                    original_hash=original_hash,
                    normalized_hash=normalized_hash,
                )
            )

        observed_at = _parse_timestamp(
            _extract_value(
                row,
                "observed_at",
                row_number=row_number,
                issues=row_issues,
            ),
            "observed_at",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        submitted_at = _parse_timestamp(
            _extract_value(
                row,
                "submitted_at",
                row_number=row_number,
                issues=row_issues,
            ),
            "submitted_at",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        latitude_value = _extract_value(
            row,
            "latitude",
            row_number=row_number,
            issues=row_issues,
        )
        longitude_value = _extract_value(
            row,
            "longitude",
            row_number=row_number,
            issues=row_issues,
        )
        latitude = _parse_coordinate(
            latitude_value,
            "latitude",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        longitude = _parse_coordinate(
            longitude_value,
            "longitude",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        latitude_supplied = _value_is_present(latitude_value)
        longitude_supplied = _value_is_present(longitude_value)
        if latitude_supplied != longitude_supplied:
            row_issues.append(
                _issue(
                    "INVALID_COORDINATE",
                    "latitude and longitude must be supplied together",
                    row_number=row_number,
                    report_id=report_id,
                    raw_record_hash=raw_record_hash,
                    details={"field": "coordinate_pair"},
                )
            )

        source_type = _optional_string(
            _extract_value(
                row,
                "source_type",
                row_number=row_number,
                issues=row_issues,
            ),
            "source_type",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        source_id = _optional_string(
            _extract_value(
                row,
                "source_id",
                row_number=row_number,
                issues=row_issues,
            ),
            "source_id",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        event_id = _optional_string(
            _extract_value(
                row,
                "event_id",
                row_number=row_number,
                issues=row_issues,
            ),
            "event_id",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        incident_id = _optional_string(
            _extract_value(
                row,
                "incident_id",
                row_number=row_number,
                issues=row_issues,
            ),
            "incident_id",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        source_report_family = _optional_string(
            _extract_value(
                row,
                "source_report_family",
                row_number=row_number,
                issues=row_issues,
            ),
            "source_report_family",
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )
        language = _parse_language(
            _extract_value(
                row,
                "language",
                row_number=row_number,
                issues=row_issues,
            ),
            row_number=row_number,
            report_id=report_id,
            issues=row_issues,
        )

        issues.extend(row_issues)
        if any(item.severity == "ERROR" for item in row_issues):
            continue
        assert report_id is not None
        assert original_text is not None
        assert raw_record_hash is not None
        normalized_text = normalize_text_for_leakage(original_text)
        reports.append(
            RawNLPReport(
                report_id=report_id,
                text=original_text,
                original_text=original_text,
                normalized_text=normalized_text,
                observed_at=observed_at,
                submitted_at=submitted_at,
                latitude=latitude,
                longitude=longitude,
                source_type=source_type,
                source_id=source_id,
                event_id=event_id,
                incident_id=incident_id,
                source_report_family=source_report_family,
                language=language,
                original_text_sha256=exact_text_sha256(original_text),
                normalized_text_sha256=exact_text_sha256(normalized_text),
                raw_record_hash=raw_record_hash,
                provenance=RawNLPReportProvenance(
                    dataset_id=manifest.dataset_id,
                    dataset_version=manifest.dataset_version,
                    local_path=manifest.local_path,
                    source_content_hash=manifest.content_hash,
                    provenance_classification=manifest.provenance_classification,
                    source_row_number=row_number,
                ),
            )
        )

    for report_id, row_numbers in sorted(report_id_evidence.items()):
        if len(row_numbers) > 1:
            issues.append(
                _issue(
                    "DUPLICATE_REPORT_ID",
                    f"duplicate report_id: {report_id}",
                    report_id=report_id,
                    details={"row_numbers": row_numbers},
                )
            )

    for hash_name, attribute, code in (
        ("exact", "original_hash", "EXACT_DUPLICATE_TEXT"),
        ("normalized", "normalized_hash", "NORMALIZED_DUPLICATE_TEXT"),
    ):
        groups: defaultdict[str, list[_TextEvidence]] = defaultdict(list)
        for evidence in text_evidence:
            groups[getattr(evidence, attribute)].append(evidence)
        for digest, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            issues.append(
                _issue(
                    code,
                    f"{hash_name} duplicate text detected",
                    details={
                        "text_hash": digest,
                        "report_ids": sorted(
                            member.record_identifier for member in members
                        ),
                        "row_numbers": sorted(member.row_number for member in members),
                    },
                )
            )

    overlaps: list[_TextEvidence] = []
    for evidence in text_evidence:
        if (
            evidence.original_hash in protected_index.exact_text_hashes
            or evidence.normalized_hash in protected_index.normalized_text_hashes
        ):
            overlaps.append(evidence)
    if overlaps:
        issues.append(
            _issue(
                "FINAL_TEST_OVERLAP_DETECTED",
                "incoming corpus overlaps the sealed 90-row final test",
                details={
                    "record_identifiers": sorted(
                        item.record_identifier for item in overlaps
                    ),
                    "original_text_sha256": sorted(
                        {item.original_hash for item in overlaps}
                    ),
                    "normalized_text_sha256": sorted(
                        {item.normalized_hash for item in overlaps}
                    ),
                },
            )
        )
    issues.extend(_inconsistent_group_issues(reports))
    if read_result.input_record_count == 0:
        issues.append(_issue("CORPUS_EMPTY", "source contains no report records"))
    return tuple(reports), tuple(text_evidence), tuple(issues)


def _duplicates_from_issues(
    issues: Sequence[CorpusValidationIssue],
    code: str,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for item in issues:
        if item.code != code:
            continue
        digest = item.details.get("text_hash")
        identifiers = item.details.get("report_ids")
        if isinstance(digest, str) and isinstance(identifiers, list):
            result[digest] = tuple(str(value) for value in identifiers)
    return dict(sorted(result.items()))


def _count_issue(issues: Sequence[CorpusValidationIssue], *codes: str) -> int:
    selected = set(codes)
    return sum(item.code in selected for item in issues)


def _build_validation_report(
    manifest: NLPCorpusSourceManifest,
    source_manifest_hash: str,
    read_result: _SourceReadResult,
    reports: Sequence[RawNLPReport],
    text_evidence: Sequence[_TextEvidence],
    issues: Sequence[CorpusValidationIssue],
) -> NLPCorpusValidationReport:
    errors = [item for item in issues if item.severity == "ERROR"]
    status = CorpusValidationStatus.FAIL if errors else CorpusValidationStatus.PASS
    duplicate_ids = tuple(
        sorted(
            item.report_id
            for item in issues
            if item.code == "DUPLICATE_REPORT_ID" and item.report_id is not None
        )
    )
    exact_duplicates = _duplicates_from_issues(issues, "EXACT_DUPLICATE_TEXT")
    normalized_duplicates = _duplicates_from_issues(
        issues,
        "NORMALIZED_DUPLICATE_TEXT",
    )
    final_overlap: list[FinalTestOverlapRecord] = []
    protected_index = assert_protected_nlp_assets_immutable()
    for evidence in text_evidence:
        match_types: list[Literal["EXACT", "NORMALIZED"]] = []
        if evidence.original_hash in protected_index.exact_text_hashes:
            match_types.append("EXACT")
        if evidence.normalized_hash in protected_index.normalized_text_hashes:
            match_types.append("NORMALIZED")
        if match_types:
            final_overlap.append(
                FinalTestOverlapRecord(
                    record_identifier=evidence.record_identifier,
                    row_number=evidence.row_number,
                    original_text_sha256=evidence.original_hash,
                    normalized_text_sha256=evidence.normalized_hash,
                    match_types=tuple(match_types),
                )
            )
    grouped_count = sum(
        bool(report.event_id or report.incident_id or report.source_report_family)
        for report in reports
    )
    language_counts = Counter(report.language.value for report in reports)
    source_counts = Counter(_source_key(report) for report in reports)
    return NLPCorpusValidationReport(
        generated_at=manifest.creation_timestamp,
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        source_manifest_hash=source_manifest_hash,
        source_content_hash=manifest.content_hash,
        status=status,
        valid=status is CorpusValidationStatus.PASS,
        input_record_count=read_result.input_record_count,
        normalized_record_count=len(reports),
        missing_report_id_count=_count_issue(issues, "MISSING_REPORT_ID"),
        missing_text_count=_count_issue(issues, "MISSING_TEXT"),
        empty_text_count=_count_issue(issues, "EMPTY_TEXT"),
        duplicate_report_ids=duplicate_ids,
        exact_duplicate_text_hashes=exact_duplicates,
        normalized_duplicate_text_hashes=normalized_duplicates,
        invalid_timestamp_count=_count_issue(issues, "INVALID_TIMESTAMP"),
        invalid_coordinate_count=_count_issue(issues, "INVALID_COORDINATE"),
        encoding_problem_count=_count_issue(issues, "ENCODING_ERROR"),
        invalid_language_count=_count_issue(issues, "INVALID_LANGUAGE"),
        inconsistent_group_identifier_count=_count_issue(
            issues,
            "INCONSISTENT_GROUP_IDENTIFIERS",
        ),
        final_test_overlap=tuple(
            sorted(final_overlap, key=lambda item: item.record_identifier)
        ),
        grouping_status=_grouping_status(reports),
        grouped_count=grouped_count,
        ungrouped_count=len(reports) - grouped_count,
        language_counts={
            language.value: language_counts.get(language.value, 0)
            for language in NLPLanguage
        },
        source_counts=dict(sorted(source_counts.items())),
        date_range=_date_range(reports),
        issues=tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.severity,
                    item.code,
                    item.row_number or 0,
                    item.report_id or "",
                    item.message,
                ),
            )
        ),
    )


def _normalized_jsonl_bytes(reports: Sequence[RawNLPReport]) -> bytes:
    lines = [
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for report in sorted(reports, key=lambda item: item.report_id)
    ]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def enroll_local_nlp_corpus(
    source_path: Path | str,
    *,
    dataset_id: str,
    dataset_version: str,
    source_description: str,
    provenance_classification: DatasetProvenance,
    output_directory: Path | str,
    creation_timestamp: datetime | None = None,
) -> NLPCorpusEnrollmentResult:
    """Enroll one explicit local file and publish evidence even when it fails."""

    selected_id = _validate_safe_identifier("dataset_id", dataset_id)
    selected_version = _validate_safe_identifier("dataset_version", dataset_version)
    if not source_description.strip():
        raise ValueError("source_description is required")
    timestamp = creation_timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("creation_timestamp must include a timezone")
    source = local_only_path(
        source_path,
        description="NLP corpus source paths",
    ).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"local NLP corpus does not exist: {source}")
    suffix_to_format = {
        ".csv": "CSV",
        ".json": "JSON",
        ".jsonl": "JSONL",
        ".parquet": "PARQUET",
        ".pq": "PARQUET",
    }
    source_format = suffix_to_format.get(source.suffix.casefold())
    if source_format is None:
        raise ValueError("local NLP corpus must be CSV, JSON, JSONL, or Parquet")
    source_hash = hash_dataset_path(source).content_sha256
    source_manifest = NLPCorpusSourceManifest(
        dataset_id=selected_id,
        dataset_version=selected_version,
        source_description=source_description.strip(),
        local_path=str(source),
        content_hash=source_hash,
        provenance_classification=provenance_classification,
        creation_timestamp=timestamp,
        input_format=source_format,
    )
    source_manifest_bytes = _model_json_bytes(source_manifest)
    source_manifest_hash = hashlib.sha256(source_manifest_bytes).hexdigest()
    protected_index = assert_protected_nlp_assets_immutable()
    read_result = _read_source_rows(source)
    reports, text_evidence, initial_issues = _normalize_rows(
        read_result,
        source_manifest,
        protected_index,
    )
    issues = list(initial_issues)
    if provenance_classification is DatasetProvenance.PROVENANCE_UNKNOWN:
        issues.append(
            _issue(
                "PROVENANCE_UNKNOWN",
                "provenance remains unknown and cannot be approved for training",
                severity="WARNING",
            )
        )
    if (
        reports
        and _grouping_status(reports) is CorpusGroupingStatus.GROUPING_NOT_AVAILABLE
    ):
        issues.append(
            _issue(
                "GROUPING_NOT_AVAILABLE",
                "no event, incident, or source-family identifiers were supplied",
                severity="WARNING",
            )
        )
    validation = _build_validation_report(
        source_manifest,
        source_manifest_hash,
        read_result,
        reports,
        text_evidence,
        issues,
    )
    validation_bytes = _model_json_bytes(validation)
    validation_hash = hashlib.sha256(validation_bytes).hexdigest()

    root = local_only_path(
        output_directory,
        description="NLP corpus enrollment paths",
    ).resolve()
    enrollment_directory = root / selected_id / selected_version
    if enrollment_directory.exists():
        raise FileExistsError(
            "corpus enrollment versions are immutable and already exist: "
            f"{enrollment_directory}"
        )
    enrollment_directory.mkdir(parents=True, exist_ok=False)
    source_manifest_path = enrollment_directory / SOURCE_MANIFEST_FILE
    validation_path = enrollment_directory / VALIDATION_REPORT_FILE
    normalized_path: Path | None = None
    source_manifest_path.write_bytes(source_manifest_bytes)
    validation_path.write_bytes(validation_bytes)

    normalized_hash: str | None = None
    normalized_file: Literal["records.jsonl"] | None = None
    if validation.valid:
        normalized_bytes = _normalized_jsonl_bytes(reports)
        normalized_hash = hashlib.sha256(normalized_bytes).hexdigest()
        normalized_file = NORMALIZED_CORPUS_FILE
        normalized_path = enrollment_directory / NORMALIZED_CORPUS_FILE
        normalized_path.write_bytes(normalized_bytes)
    enrollment_manifest = NLPCorpusEnrollmentManifest(
        dataset_id=selected_id,
        dataset_version=selected_version,
        creation_timestamp=timestamp,
        source_manifest_hash=source_manifest_hash,
        validation_report_hash=validation_hash,
        normalized_corpus_file=normalized_file,
        normalized_corpus_hash=normalized_hash,
        record_count=len(reports) if validation.valid else 0,
        validation_status=validation.status,
        annotation_readiness="READY" if validation.valid else "BLOCKED",
    )
    enrollment_manifest_path = enrollment_directory / ENROLLMENT_MANIFEST_FILE
    enrollment_manifest_path.write_bytes(_model_json_bytes(enrollment_manifest))
    return NLPCorpusEnrollmentResult(
        enrollment_directory=enrollment_directory,
        source_manifest_path=source_manifest_path,
        validation_report_path=validation_path,
        normalized_corpus_path=normalized_path,
        enrollment_manifest_path=enrollment_manifest_path,
        source_manifest=source_manifest,
        validation_report=validation,
        enrollment_manifest=enrollment_manifest,
    )


def load_enrolled_nlp_corpus(
    enrollment_directory: Path | str,
) -> LoadedNLPCorpus:
    """Load a READY enrollment only after rechecking every evidence binding."""

    root = local_only_path(
        enrollment_directory,
        description="NLP corpus enrollment paths",
    ).resolve()
    enrollment_path = root / ENROLLMENT_MANIFEST_FILE
    source_manifest_path = root / SOURCE_MANIFEST_FILE
    validation_path = root / VALIDATION_REPORT_FILE
    for path in (enrollment_path, source_manifest_path, validation_path):
        if not path.is_file():
            raise ValueError(f"corpus enrollment evidence is missing: {path.name}")
    enrollment = NLPCorpusEnrollmentManifest.model_validate_json(
        enrollment_path.read_text(encoding="utf-8", errors="strict")
    )
    source_manifest = NLPCorpusSourceManifest.model_validate_json(
        source_manifest_path.read_text(encoding="utf-8", errors="strict")
    )
    validation = NLPCorpusValidationReport.model_validate_json(
        validation_path.read_text(encoding="utf-8", errors="strict")
    )
    if enrollment.annotation_readiness != "READY" or not validation.valid:
        raise ValueError("corpus validation failed; annotation queue is blocked")
    if _file_sha256(source_manifest_path) != enrollment.source_manifest_hash:
        raise ValueError("source manifest hash mismatch")
    if _file_sha256(validation_path) != enrollment.validation_report_hash:
        raise ValueError("corpus validation report hash mismatch")
    if validation.source_manifest_hash != enrollment.source_manifest_hash:
        raise ValueError("validation report is not bound to the source manifest")
    identities = {
        (enrollment.dataset_id, enrollment.dataset_version),
        (source_manifest.dataset_id, source_manifest.dataset_version),
        (validation.dataset_id, validation.dataset_version),
    }
    if len(identities) != 1:
        raise ValueError("corpus enrollment dataset identity mismatch")
    if enrollment.normalized_corpus_file is None:
        raise ValueError("ready corpus is missing normalized corpus metadata")
    normalized_path = root / enrollment.normalized_corpus_file
    if not normalized_path.is_file():
        raise ValueError("normalized corpus file is missing")
    if _file_sha256(normalized_path) != enrollment.normalized_corpus_hash:
        raise ValueError("normalized corpus hash mismatch")
    source_path = local_only_path(
        source_manifest.local_path,
        description="NLP corpus source paths",
    )
    if not source_path.is_file():
        raise ValueError("enrolled source file is no longer available")
    if hash_dataset_path(source_path).content_sha256 != source_manifest.content_hash:
        raise ValueError("enrolled source content hash changed")
    reports: list[RawNLPReport] = []
    for line_number, line in enumerate(
        normalized_path.read_text(encoding="utf-8", errors="strict").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            reports.append(RawNLPReport.model_validate_json(line))
        except Exception as error:
            raise ValueError(
                f"invalid normalized corpus record at line {line_number}: {error}"
            ) from error
    if len(reports) != enrollment.record_count:
        raise ValueError("normalized corpus record count mismatch")
    if len({item.report_id for item in reports}) != len(reports):
        raise ValueError("normalized corpus contains duplicate report IDs")
    assert_protected_nlp_assets_immutable()
    return LoadedNLPCorpus(
        enrollment_directory=root,
        source_manifest_path=source_manifest_path,
        validation_report_path=validation_path,
        normalized_corpus_path=normalized_path,
        source_manifest=source_manifest,
        validation_report=validation,
        enrollment_manifest=enrollment,
        reports=tuple(reports),
    )


class _DisjointSet:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        self.parent[second] = first


def _grouping_metadata(
    reports: Sequence[RawNLPReport],
) -> dict[str, NLPQueueGroupingMetadata]:
    sets = _DisjointSet([item.report_id for item in reports])
    owners: dict[str, str] = {}
    direct_keys: dict[str, tuple[str, ...]] = {}
    for report in sorted(reports, key=lambda item: item.report_id):
        keys = tuple(
            sorted(
                key
                for key in (
                    f"event:{report.event_id}" if report.event_id else None,
                    f"incident:{report.incident_id}" if report.incident_id else None,
                    (
                        f"source_family:{report.source_report_family}"
                        if report.source_report_family
                        else None
                    ),
                )
                if key is not None
            )
        )
        direct_keys[report.report_id] = keys
        for key in keys:
            if key in owners:
                sets.union(report.report_id, owners[key])
            else:
                owners[key] = report.report_id
    members: defaultdict[str, list[RawNLPReport]] = defaultdict(list)
    for report in reports:
        members[sets.find(report.report_id)].append(report)
    result: dict[str, NLPQueueGroupingMetadata] = {}
    for component in members.values():
        component_keys = tuple(
            sorted(
                {key for report in component for key in direct_keys[report.report_id]}
            )
        )
        group_id = (
            "nlp-group-" + _canonical_sha256(component_keys)[:20]
            if component_keys
            else None
        )
        for report in component:
            result[report.report_id] = NLPQueueGroupingMetadata(
                event_id=report.event_id,
                incident_id=report.incident_id,
                source_report_family=report.source_report_family,
                supplied_grouping_keys=direct_keys[report.report_id],
                component_group_id=group_id,
                grouping_status=(
                    "GROUPED"
                    if direct_keys[report.report_id]
                    else "GROUPING_NOT_AVAILABLE"
                ),
            )
    return result


def _seeded_order(
    report_ids: Sequence[str],
    *,
    seed: int,
    namespace: str,
) -> list[str]:
    return sorted(
        report_ids,
        key=lambda report_id: (
            hashlib.sha256(f"{namespace}:{seed}:{report_id}".encode()).hexdigest(),
            report_id,
        ),
    )


def _balanced_order(
    buckets: Mapping[str, Sequence[str]],
    *,
    seed: int,
    namespace: str,
) -> list[str]:
    ordered = {
        key: _seeded_order(
            list(values),
            seed=seed,
            namespace=f"{namespace}:{key}",
        )
        for key, values in sorted(buckets.items())
    }
    result: list[str] = []
    offset = 0
    while True:
        added = False
        for key in sorted(ordered):
            if offset < len(ordered[key]):
                result.append(ordered[key][offset])
                added = True
        if not added:
            break
        offset += 1
    return result


def _priority_order(
    reports: Sequence[RawNLPReport],
    grouping: Mapping[str, NLPQueueGroupingMetadata],
    *,
    strategy: NLPQueueSamplingStrategy,
    seed: int,
    review_report_ids: Sequence[str],
) -> list[str]:
    report_ids = [item.report_id for item in reports]
    if strategy is NLPQueueSamplingStrategy.RANDOM:
        return _seeded_order(report_ids, seed=seed, namespace=strategy.value)
    if strategy is NLPQueueSamplingStrategy.LANGUAGE_BALANCED:
        buckets: defaultdict[str, list[str]] = defaultdict(list)
        for report in reports:
            buckets[report.language.value].append(report.report_id)
        return _balanced_order(buckets, seed=seed, namespace=strategy.value)
    if strategy is NLPQueueSamplingStrategy.GROUP_BALANCED:
        buckets = defaultdict(list)
        for report in reports:
            metadata = grouping[report.report_id]
            key = metadata.component_group_id or f"ungrouped:{report.report_id}"
            buckets[key].append(report.report_id)
        return _balanced_order(buckets, seed=seed, namespace=strategy.value)
    if strategy is NLPQueueSamplingStrategy.SOURCE_BALANCED:
        buckets = defaultdict(list)
        for report in reports:
            buckets[_source_key(report)].append(report.report_id)
        return _balanced_order(buckets, seed=seed, namespace=strategy.value)
    selected = set(review_report_ids)
    unknown = sorted(selected - set(report_ids))
    if unknown:
        raise ValueError(f"review priority references unknown report IDs: {unknown}")
    if not selected:
        raise ValueError(f"{strategy.value} requires explicit local review_report_ids")
    first = _seeded_order(
        list(selected),
        seed=seed,
        namespace=f"{strategy.value}:selected",
    )
    remaining = _seeded_order(
        [report_id for report_id in report_ids if report_id not in selected],
        seed=seed,
        namespace=f"{strategy.value}:remaining",
    )
    return first + remaining


def build_nlp_annotation_queue(
    corpus: LoadedNLPCorpus,
    *,
    sampling_strategy: NLPQueueSamplingStrategy,
    seed: int,
    priority_count: int | None = None,
    review_report_ids: Sequence[str] = (),
    created_at: datetime | None = None,
    blind_annotation: bool = True,
    model_assistance_shown: bool = False,
) -> NLPAnnotationQueue:
    """Create a full-population queue; sampling changes priority only."""

    timestamp = created_at or corpus.source_manifest.creation_timestamp
    if timestamp.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    if not corpus.reports:
        raise ValueError("cannot queue an empty corpus")
    if (
        sampling_strategy
        not in {
            NLPQueueSamplingStrategy.UNCERTAINTY_REVIEW,
            NLPQueueSamplingStrategy.MODEL_ERROR_REVIEW,
        }
        and review_report_ids
    ):
        raise ValueError("review_report_ids are only valid for review strategies")
    if blind_annotation and model_assistance_shown:
        raise ValueError("blind annotation cannot show model assistance")
    selected_count = len(corpus.reports) if priority_count is None else priority_count
    if selected_count < 1 or selected_count > len(corpus.reports):
        raise ValueError("priority_count must be between 1 and the corpus size")
    grouping = _grouping_metadata(corpus.reports)
    ordered_ids = _priority_order(
        corpus.reports,
        grouping,
        strategy=sampling_strategy,
        seed=seed,
        review_report_ids=review_report_ids,
    )
    report_by_id = {item.report_id: item for item in corpus.reports}
    items: list[NLPAnnotationQueueItem] = []
    for rank, report_id in enumerate(ordered_ids, start=1):
        report = report_by_id[report_id]
        queue_id = (
            "nlpq-"
            + _canonical_sha256(
                {
                    "dataset_id": corpus.source_manifest.dataset_id,
                    "dataset_version": corpus.source_manifest.dataset_version,
                    "report_id": report.report_id,
                    "text_hash": report.original_text_sha256,
                }
            )[:24]
        )
        items.append(
            NLPAnnotationQueueItem(
                queue_id=queue_id,
                report_id=report.report_id,
                dataset_id=corpus.source_manifest.dataset_id,
                dataset_version=corpus.source_manifest.dataset_version,
                text_hash=report.original_text_sha256,
                language=report.language,
                grouping_metadata=grouping[report.report_id],
                priority_rank=rank,
                priority_selected=rank <= selected_count,
                source_type=report.source_type,
                source_id=report.source_id,
            )
        )
    selection_parameters: dict[str, Any] = {
        "priority_count": selected_count,
        "population_count": len(corpus.reports),
        "review_report_ids": sorted(set(review_report_ids)),
        "priority_only": True,
    }
    return NLPAnnotationQueue(
        created_at=timestamp,
        dataset_id=corpus.source_manifest.dataset_id,
        dataset_version=corpus.source_manifest.dataset_version,
        source_manifest_hash=corpus.enrollment_manifest.source_manifest_hash,
        validation_report_hash=corpus.enrollment_manifest.validation_report_hash,
        normalized_corpus_hash=(
            corpus.enrollment_manifest.normalized_corpus_hash or ""
        ),
        sampling_strategy=sampling_strategy,
        seed=seed,
        selection_parameters=selection_parameters,
        blind_annotation=blind_annotation,
        model_assistance_shown=model_assistance_shown,
        assistance_banner=(MODEL_SUGGESTION_BANNER if model_assistance_shown else None),
        items=tuple(items),
    )


def write_nlp_annotation_queue(
    corpus: LoadedNLPCorpus,
    *,
    output_directory: Path | str,
    sampling_strategy: NLPQueueSamplingStrategy,
    seed: int,
    priority_count: int | None = None,
    review_report_ids: Sequence[str] = (),
    created_at: datetime | None = None,
    blind_annotation: bool = True,
    model_assistance_shown: bool = False,
) -> NLPAnnotationQueueResult:
    """Publish an immutable queue and its pre-annotation distribution report."""

    queue = build_nlp_annotation_queue(
        corpus,
        sampling_strategy=sampling_strategy,
        seed=seed,
        priority_count=priority_count,
        review_report_ids=review_report_ids,
        created_at=created_at,
        blind_annotation=blind_annotation,
        model_assistance_shown=model_assistance_shown,
    )
    root = local_only_path(
        output_directory,
        description="NLP annotation queue paths",
    ).resolve()
    if root.exists():
        raise FileExistsError(f"annotation queue output already exists: {root}")
    queue_bytes = _model_json_bytes(queue)
    queue_hash = hashlib.sha256(queue_bytes).hexdigest()
    validation = corpus.validation_report
    languages = Counter(item.language for item in corpus.reports)
    report = NLPAnnotationQueueReport(
        generated_at=queue.created_at,
        dataset_id=queue.dataset_id,
        dataset_version=queue.dataset_version,
        queue_hash=queue_hash,
        total_reports=len(queue.items),
        english_count=languages.get(NLPLanguage.ENGLISH, 0),
        hindi_count=languages.get(NLPLanguage.HINDI, 0),
        hinglish_count=languages.get(NLPLanguage.HINGLISH, 0),
        other_count=languages.get(NLPLanguage.OTHER, 0),
        unknown_count=languages.get(NLPLanguage.UNKNOWN, 0),
        grouped_count=validation.grouped_count,
        ungrouped_count=validation.ungrouped_count,
        source_counts=validation.source_counts,
        date_range=validation.date_range,
        duplicate_report_id_count=len(validation.duplicate_report_ids),
        exact_duplicate_text_count=len(validation.exact_duplicate_text_hashes),
        normalized_duplicate_text_count=len(
            validation.normalized_duplicate_text_hashes
        ),
        empty_text_count=validation.empty_text_count,
        sampling_strategy=queue.sampling_strategy,
        seed=queue.seed,
        selection_parameters=queue.selection_parameters,
        blind_annotation=queue.blind_annotation,
        model_assistance_shown=queue.model_assistance_shown,
    )
    root.mkdir(parents=True, exist_ok=False)
    queue_path = root / ANNOTATION_QUEUE_FILE
    report_path = root / ANNOTATION_QUEUE_REPORT_FILE
    queue_path.write_bytes(queue_bytes)
    report_path.write_bytes(_model_json_bytes(report))
    return NLPAnnotationQueueResult(
        output_directory=root,
        queue_path=queue_path,
        report_path=report_path,
        queue=queue,
        report=report,
    )


def load_nlp_annotation_queue(path: Path | str) -> NLPAnnotationQueue:
    selected = local_only_path(
        path,
        description="NLP annotation queue paths",
    )
    return NLPAnnotationQueue.model_validate_json(
        selected.read_text(encoding="utf-8", errors="strict")
    )


def raw_nlp_reports_to_annotation_sources(
    reports: Sequence[RawNLPReport],
) -> tuple[NLPSourceReport, ...]:
    """Adapt enrolled records to the Phase 15 human annotation contract."""

    result: list[NLPSourceReport] = []
    for report in reports:
        source_dataset_id = (
            f"{report.provenance.dataset_id}:{report.provenance.dataset_version}"
        )
        result.append(
            NLPSourceReport(
                report_id=report.report_id,
                text=report.original_text,
                source_metadata_if_available={
                    "observed_at": (
                        report.observed_at.isoformat() if report.observed_at else None
                    ),
                    "submitted_at": (
                        report.submitted_at.isoformat() if report.submitted_at else None
                    ),
                    "latitude": report.latitude,
                    "longitude": report.longitude,
                    "source_type": report.source_type,
                    "source_id": report.source_id,
                    "raw_record_hash": report.raw_record_hash,
                    "original_text_sha256": report.original_text_sha256,
                    "normalized_text_sha256": report.normalized_text_sha256,
                    "provenance": report.provenance.model_dump(mode="json"),
                },
                language_hint=report.language,
                event_id_if_known=report.event_id,
                incident_id_if_known=report.incident_id,
                source_report_family=report.source_report_family,
                source_dataset_id=source_dataset_id,
            )
        )
    return tuple(result)


__all__ = [
    "ANNOTATION_QUEUE_FILE",
    "ANNOTATION_QUEUE_REPORT_FILE",
    "ENROLLMENT_MANIFEST_FILE",
    "NORMALIZED_CORPUS_FILE",
    "SOURCE_MANIFEST_FILE",
    "VALIDATION_REPORT_FILE",
    "CorpusDateRange",
    "CorpusGroupingStatus",
    "CorpusValidationIssue",
    "CorpusValidationStatus",
    "FinalTestOverlapRecord",
    "LoadedNLPCorpus",
    "NLPAnnotationQueue",
    "NLPAnnotationQueueItem",
    "NLPAnnotationQueueReport",
    "NLPAnnotationQueueResult",
    "NLPAnnotationQueueStatus",
    "NLPAnnotationQueueStatusEvent",
    "NLPAnnotationQueueStatusStore",
    "NLPCorpusEnrollmentManifest",
    "NLPCorpusEnrollmentResult",
    "NLPCorpusSourceManifest",
    "NLPCorpusValidationReport",
    "NLPQueueGroupingMetadata",
    "NLPQueueSamplingStrategy",
    "RawNLPReport",
    "RawNLPReportProvenance",
    "build_nlp_annotation_queue",
    "create_queue_status_event",
    "enroll_local_nlp_corpus",
    "load_enrolled_nlp_corpus",
    "load_nlp_annotation_queue",
    "queue_statuses",
    "raw_nlp_reports_to_annotation_sources",
    "write_nlp_annotation_queue",
]
