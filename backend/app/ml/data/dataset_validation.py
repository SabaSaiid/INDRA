"""Cross-component local dataset validation and machine-readable readiness reports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ml.config import local_only_path
from app.ml.contracts import WeatherObservation
from app.ml.data.anomaly_annotations import (
    AnomalyAnnotation,
    validate_anomaly_annotations,
)
from app.ml.data.duplicate_pairs import (
    DuplicatePairLabel,
    DuplicatePairRecord,
    validate_duplicate_pairs,
)
from app.ml.data.event_annotations import (
    EventPairAnnotation,
    ReportEventAnnotation,
    validate_event_annotations,
)
from app.ml.data.fake_report_annotations import (
    FakeReportAnnotation,
    FakeReportLabel,
    validate_fake_report_annotations,
)
from app.ml.data.image_annotations import (
    ImageAnnotation,
    validate_image_annotations,
)
from app.ml.data.registry import (
    USE_TO_SPLIT,
    AnomalyDataRole,
    DatasetClassification,
    DatasetComponent,
    DatasetFormat,
    DatasetRegistryRecord,
    DatasetStatus,
    DatasetUse,
    find_dataset,
    hash_dataset_path,
    load_dataset_registry,
    resolve_registry_path,
    save_dataset_registry,
)


class ValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ValidationCheck(ValidationModel):
    code: str = Field(min_length=1)
    status: CheckStatus
    required: bool = True
    details: list[str] = Field(default_factory=list)


class DatasetLeakageReport(ValidationModel):
    exact_duplicate_leakage: ValidationCheck
    near_duplicate_leakage: ValidationCheck
    group_leakage: ValidationCheck
    temporal_leakage: ValidationCheck
    label_leakage: ValidationCheck
    cross_split_overlap: ValidationCheck
    overall_status: CheckStatus


class RegisteredDatasetValidationReport(ValidationModel):
    report_version: Literal["dataset-validation-report-v1"] = (
        "dataset-validation-report-v1"
    )
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    component: DatasetComponent
    local_path: str
    format: DatasetFormat
    registered_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_matches_registry: bool
    valid: bool
    validation_status: Literal["VALID", "INVALID"]
    checks: list[ValidationCheck] = Field(default_factory=list)
    leakage: DatasetLeakageReport
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    row_or_image_count: int = Field(ge=0)
    label_count: int = Field(ge=0)
    label_distribution: dict[str, int] = Field(default_factory=dict)
    split_counts: dict[str, int] = Field(default_factory=dict)
    split_label_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    grouping_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    component_readiness: dict[str, Any] = Field(default_factory=dict)
    approval_blockers: dict[str, list[str]] = Field(default_factory=dict)


class RegisteredNLPRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    event_type: Literal[
        "URBAN_FLOOD",
        "RIVER_BREACH",
        "CLOUDBURST",
        "CYCLONE_INUNDATION",
        "NOT_RELEVANT",
    ]
    language: str = Field(min_length=1)
    split: Literal["train", "validation", "test"]


class RegisteredEventPair(EventPairAnnotation):
    event_type_a: str | None = None
    event_type_b: str | None = None


class RegisteredReportEvent(ReportEventAnnotation):
    event_type: str | None = None


class RegisteredImageAnnotation(ImageAnnotation):
    image_path: str | None = None


class RegisteredWeatherObservation(WeatherObservation):
    split: Literal["train", "validation", "test"]
    domain_label: str | None = None


@dataclass
class _LoadedDataset:
    rows: list[dict[str, Any]] = field(default_factory=list)
    image_paths: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _ParsedDataset:
    records: list[Any] = field(default_factory=list)
    row_indexes: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validation_report_sha256(report: RegisteredDatasetValidationReport) -> str:
    return hashlib.sha256(_canonical_json(report.model_dump(mode="json"))).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _strict_text(path: Path) -> str:
    text = path.read_bytes().decode("utf-8", errors="strict")
    if "\ufffd" in text:
        raise UnicodeError("replacement character found in decoded dataset")
    return text


def _rows_from_file(path: Path, dataset_format: DatasetFormat) -> list[dict[str, Any]]:
    if dataset_format is DatasetFormat.CSV:
        rows = list(csv.DictReader(io.StringIO(_strict_text(path))))
    elif dataset_format is DatasetFormat.JSON:
        payload = json.loads(_strict_text(path))
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            payload = payload["records"]
        if not isinstance(payload, list):
            raise ValueError(
                "JSON dataset must be a list or an object with a records list"
            )
        rows = payload
    elif dataset_format is DatasetFormat.JSONL:
        rows = []
        for line_number, line in enumerate(_strict_text(path).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid JSONL at line {line_number}: {error}"
                ) from error
    elif dataset_format is DatasetFormat.PARQUET:
        try:
            from pyarrow import parquet
        except ImportError as error:
            raise ValueError("PARQUET_SUPPORT_UNAVAILABLE") from error
        rows = parquet.read_table(path).to_pylist()
    else:
        raise ValueError(f"format {dataset_format.value} is not a structured row file")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("every structured dataset row must be an object")
    return [dict(row) for row in rows]


def _load_dataset(path: Path, record: DatasetRegistryRecord) -> _LoadedDataset:
    loaded = _LoadedDataset()
    try:
        if record.format in {
            DatasetFormat.CSV,
            DatasetFormat.JSON,
            DatasetFormat.JSONL,
            DatasetFormat.PARQUET,
        }:
            loaded.rows = _rows_from_file(path, record.format)
        elif record.format is DatasetFormat.DIRECTORY:
            if not path.is_dir():
                raise ValueError("DIRECTORY dataset path is not a directory")
            if record.component is DatasetComponent.IMAGE:
                loaded.image_paths = sorted(
                    (
                        item
                        for item in path.rglob("*")
                        if item.is_file()
                        and item.suffix.casefold() in {".jpg", ".jpeg", ".png"}
                    ),
                    key=lambda item: item.relative_to(path).as_posix(),
                )
                metadata = [
                    candidate
                    for candidate in (
                        path / "annotations.jsonl",
                        path / "annotations.json",
                        path / "annotations.csv",
                    )
                    if candidate.is_file()
                ]
                if len(metadata) != 1:
                    raise ValueError(
                        "image directory requires exactly one annotations.jsonl, "
                        "annotations.json, or annotations.csv"
                    )
                metadata_format = {
                    ".jsonl": DatasetFormat.JSONL,
                    ".json": DatasetFormat.JSON,
                    ".csv": DatasetFormat.CSV,
                }[metadata[0].suffix.casefold()]
                loaded.rows = _rows_from_file(metadata[0], metadata_format)
            else:
                shard_formats = {
                    ".csv": DatasetFormat.CSV,
                    ".json": DatasetFormat.JSON,
                    ".jsonl": DatasetFormat.JSONL,
                    ".parquet": DatasetFormat.PARQUET,
                }
                directory_files = sorted(
                    (item for item in path.rglob("*") if item.is_file()),
                    key=lambda item: item.relative_to(path).as_posix(),
                )
                shards = sorted(
                    (
                        item
                        for item in directory_files
                        if item.suffix.casefold() in shard_formats
                    ),
                    key=lambda item: item.relative_to(path).as_posix(),
                )
                if not shards:
                    raise ValueError(
                        "structured directory contains no CSV, JSON, JSONL, or Parquet shards"
                    )
                ignored = [
                    item.relative_to(path).as_posix()
                    for item in directory_files
                    if item.suffix.casefold() not in shard_formats
                ]
                if ignored:
                    loaded.warnings.append(
                        "non-tabular directory members are hash-bound but not parsed: "
                        + ", ".join(ignored)
                    )
                for shard in shards:
                    loaded.rows.extend(
                        _rows_from_file(shard, shard_formats[shard.suffix.casefold()])
                    )
        elif record.format in {DatasetFormat.JPEG, DatasetFormat.PNG}:
            loaded.image_paths = [path]
            loaded.errors.append("single image has no annotation manifest")
        elif record.format is DatasetFormat.ZIP:
            loaded.errors.append(
                "archives must be safely extracted to a local directory before validation"
            )
        else:
            loaded.errors.append(f"unsupported dataset format: {record.format.value}")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        loaded.errors.append(f"dataset load failed: {type(error).__name__}: {error}")
    return loaded


def _adapt_nlp_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["record_id"] = payload.get("record_id") or payload.get("id")
    payload["language"] = payload.get("language") or payload.get("lang")
    return payload


def _parse_rows(
    record: DatasetRegistryRecord,
    rows: list[dict[str, Any]],
) -> _ParsedDataset:
    result = _ParsedDataset()
    for index, row in enumerate(rows, start=1):
        try:
            payload = dict(row)
            if record.split_field != "split":
                registered_split = payload.get(record.split_field)
                canonical_split = payload.get("split")
                if (
                    canonical_split not in (None, "")
                    and registered_split not in (None, "")
                    and canonical_split != registered_split
                ):
                    raise ValueError(
                        "canonical split and registered split_field disagree"
                    )
                payload["split"] = canonical_split or registered_split
                payload.pop(record.split_field, None)
            if record.component is DatasetComponent.NLP:
                parsed = RegisteredNLPRecord.model_validate(_adapt_nlp_row(payload))
            elif record.component is DatasetComponent.DUPLICATE:
                parsed = DuplicatePairRecord.model_validate(payload)
            elif record.component is DatasetComponent.EVENT:
                if "event_a_id" in payload or "event_b_id" in payload:
                    parsed = RegisteredEventPair.model_validate(payload)
                else:
                    parsed = RegisteredReportEvent.model_validate(payload)
            elif record.component is DatasetComponent.CREDIBILITY:
                parsed = FakeReportAnnotation.model_validate(payload)
            elif record.component is DatasetComponent.IMAGE:
                parsed = RegisteredImageAnnotation.model_validate(payload)
            elif record.component is DatasetComponent.ANOMALY:
                if record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE:
                    parsed = RegisteredWeatherObservation.model_validate(payload)
                else:
                    parsed = AnomalyAnnotation.model_validate(payload)
            else:
                raise ValueError(f"unsupported component: {record.component.value}")
            result.records.append(parsed)
            result.row_indexes.append(index - 1)
        except (ValidationError, ValueError) as error:
            result.errors.append(f"row {index}: {error}")
    return result


def _split_value(item: Any) -> str | None:
    split = getattr(item, "split", None)
    return split.value if isinstance(split, Enum) else split


def _labels(item: Any, component: DatasetComponent) -> list[str]:
    if component is DatasetComponent.NLP:
        return [item.event_type]
    if component is DatasetComponent.ANOMALY and isinstance(
        item, RegisteredWeatherObservation
    ):
        return [item.domain_label] if item.domain_label else []
    if component in {
        DatasetComponent.DUPLICATE,
        DatasetComponent.EVENT,
        DatasetComponent.CREDIBILITY,
        DatasetComponent.ANOMALY,
    }:
        label = getattr(item, "label", None)
        return [label.value if isinstance(label, Enum) else str(label)] if label else []
    if component is DatasetComponent.IMAGE:
        return [label.value for label in item.labels]
    return []


def _common_value_checks(
    rows: list[dict[str, Any]],
    record: DatasetRegistryRecord,
) -> tuple[list[str], ValidationCheck, ValidationCheck, ValidationCheck]:
    null_errors: list[str] = []
    coordinate_errors: list[str] = []
    timestamp_errors: list[str] = []
    coordinate_pairs = (
        ("latitude", "longitude"),
        ("reported_latitude", "reported_longitude"),
        ("latitude_a", "longitude_a"),
        ("latitude_b", "longitude_b"),
    )
    timestamp_fields = {
        "annotation_timestamp",
        "timestamp",
        "reported_at",
        "observed_at",
        "observed_start_at",
        "observed_end_at",
    }
    if record.time_field:
        timestamp_fields.add(record.time_field)

    def is_nullish(value: Any) -> bool:
        return (
            value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, (list, tuple, dict, set)) and not value)
        )

    def required_fields(row: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
        split = (record.split_field,)
        if record.component is DatasetComponent.NLP:
            return (
                ("record_id", "id"),
                ("text",),
                ("event_type",),
                ("language", "lang"),
                split,
            )
        if record.component is DatasetComponent.DUPLICATE:
            return (
                ("pair_id",),
                ("report_a_id",),
                ("report_b_id",),
                ("label",),
                ("annotator_id",),
                ("annotation_timestamp",),
                ("annotation_reason",),
                ("label_provenance",),
                split,
            )
        if record.component is DatasetComponent.EVENT:
            identities = (
                (("event_a_id",), ("event_b_id",))
                if "event_a_id" in row or "event_b_id" in row
                else (("report_id",), ("event_id",))
            )
            return (
                *identities,
                ("label",),
                ("annotator_id",),
                ("reason",),
                ("timestamp",),
                split,
            )
        if record.component is DatasetComponent.CREDIBILITY:
            return (
                ("report_id",),
                ("label",),
                ("annotator_id",),
                ("annotation_timestamp",),
                ("reason",),
                split,
            )
        if record.component is DatasetComponent.IMAGE:
            return (
                ("image_id",),
                ("labels",),
                ("annotator_id",),
                ("annotation_timestamp",),
                ("reason",),
                ("byte_sha256",),
                ("width",),
                ("height",),
                ("detected_format",),
                split,
            )
        if record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE:
            return (
                ("observation_id",),
                ("station_id",),
                ("observed_at",),
                split,
            )
        return (
            ("target_id",),
            ("station_id",),
            ("observation_ids",),
            ("scope",),
            ("label",),
            ("annotator_id",),
            ("annotation_timestamp",),
            ("reason",),
            split,
        )

    timestamps_present = False
    for index, row in enumerate(rows, start=1):
        for alternatives in required_fields(row):
            if not any(
                name in row and not is_nullish(row.get(name)) for name in alternatives
            ):
                null_errors.append(
                    f"row {index}: required value missing for {' or '.join(alternatives)}"
                )
        for latitude_name, longitude_name in coordinate_pairs:
            if latitude_name not in row and longitude_name not in row:
                continue
            latitude = row.get(latitude_name)
            longitude = row.get(longitude_name)
            if latitude in (None, "") and longitude in (None, ""):
                continue
            try:
                latitude_value = float(latitude)
                longitude_value = float(longitude)
                if not (
                    math.isfinite(latitude_value)
                    and math.isfinite(longitude_value)
                    and -90.0 <= latitude_value <= 90.0
                    and -180.0 <= longitude_value <= 180.0
                ):
                    raise ValueError
            except (TypeError, ValueError):
                coordinate_errors.append(
                    f"row {index}: invalid {latitude_name}/{longitude_name}"
                )
        for field_name in sorted(timestamp_fields & row.keys()):
            value = row.get(field_name)
            if is_nullish(value):
                if field_name == record.time_field:
                    timestamp_errors.append(
                        f"row {index}: missing registered time field {field_name}"
                    )
                continue
            timestamps_present = True
            try:
                if isinstance(value, datetime):
                    parsed = value
                elif isinstance(value, str) and value.strip():
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                else:
                    raise ValueError
                if parsed.tzinfo is None:
                    raise ValueError
            except (TypeError, ValueError):
                timestamp_errors.append(
                    f"row {index}: invalid or timezone-naive {field_name}"
                )
    null_check = _check(
        "NULL_AND_REQUIRED_VALUES",
        CheckStatus.FAIL if null_errors else CheckStatus.PASS,
        null_errors,
    )
    coordinate_check = _check(
        "COORDINATE_VALIDITY",
        CheckStatus.FAIL if coordinate_errors else CheckStatus.PASS,
        coordinate_errors,
        required=any(
            any(name in row for name in pair)
            for row in rows
            for pair in coordinate_pairs
        ),
    )
    timestamp_check = _check(
        "TIMESTAMP_VALIDITY",
        CheckStatus.FAIL if timestamp_errors else CheckStatus.PASS,
        timestamp_errors,
        required=record.time_field is not None or timestamps_present,
    )
    return (
        null_errors + coordinate_errors + timestamp_errors,
        null_check,
        coordinate_check,
        timestamp_check,
    )


def _identity(item: Any, component: DatasetComponent) -> str:
    if component is DatasetComponent.NLP:
        return item.record_id
    if component is DatasetComponent.DUPLICATE:
        return "::".join(sorted((str(item.report_a_id), str(item.report_b_id))))
    if component is DatasetComponent.EVENT:
        if isinstance(item, EventPairAnnotation):
            return "::".join(sorted((item.event_a_id, item.event_b_id)))
        return f"{item.report_id}::{item.event_id}"
    if component is DatasetComponent.CREDIBILITY:
        return item.report_id
    if component is DatasetComponent.IMAGE:
        return item.image_id
    if component is DatasetComponent.ANOMALY:
        return getattr(item, "target_id", getattr(item, "observation_id", ""))
    return ""


def _text(item: Any, component: DatasetComponent) -> str | None:
    if component is DatasetComponent.NLP:
        return item.text
    if component is DatasetComponent.CREDIBILITY:
        return item.report_text
    return None


def _group_value(
    row: dict[str, Any],
    grouping_field: str | None,
) -> str | None:
    if not grouping_field:
        return None
    value = row.get(grouping_field)
    return str(value).strip() if value is not None and str(value).strip() else None


def _check(
    code: str,
    status: CheckStatus,
    details: list[str] | None = None,
    *,
    required: bool = True,
) -> ValidationCheck:
    return ValidationCheck(
        code=code,
        status=status,
        required=required,
        details=details or [],
    )


def _near_text_leaks(records: list[Any], component: DatasetComponent) -> list[str]:
    values = [
        (_identity(item, component), _split_value(item), _normalize_text(value))
        for item in records
        if (value := _text(item, component)) and _split_value(item)
    ]
    if len(values) > 5_000:
        return ["NEAR_DUPLICATE_SCAN_LIMIT_EXCEEDED"]
    matches: set[str] = set()
    for index, (left_id, left_split, left_text) in enumerate(values):
        for right_id, right_split, right_text in values[index + 1 :]:
            if left_split == right_split or left_text == right_text:
                continue
            if SequenceMatcher(None, left_text, right_text).ratio() >= 0.95:
                matches.add("::".join(sorted((left_id, right_id))))
    return sorted(matches)


def _image_near_leaks(records: list[RegisteredImageAnnotation]) -> list[str]:
    values = [
        (item.image_id, item.split, item.perceptual_similarity_hash)
        for item in records
        if item.split and item.perceptual_similarity_hash
    ]
    matches: set[str] = set()
    for index, (left_id, left_split, left_hash) in enumerate(values):
        for right_id, right_split, right_hash in values[index + 1 :]:
            if left_split == right_split or len(left_hash) != len(right_hash):
                continue
            distance = (int(left_hash, 16) ^ int(right_hash, 16)).bit_count()
            if distance <= 5:
                matches.add("::".join(sorted((left_id, right_id))))
    return sorted(matches)


def _leakage_report(
    registry_record: DatasetRegistryRecord,
    rows: list[dict[str, Any]],
    records: list[Any],
) -> DatasetLeakageReport:
    split_locations: defaultdict[str, set[str]] = defaultdict(set)
    content_locations: defaultdict[str, set[str]] = defaultdict(set)
    # Track complete label sets per identity.  Counting individual labels as
    # alternatives incorrectly marks every legitimate multi-label image as a
    # conflict.
    label_locations: defaultdict[str, set[tuple[str, ...]]] = defaultdict(set)
    group_locations: defaultdict[str, set[str]] = defaultdict(set)
    missing_groups = 0
    for row, item in zip(rows, records):
        split = _split_value(item)
        identity = _identity(item, registry_record.component)
        labels = _labels(item, registry_record.component)
        if split:
            split_locations[identity].add(split)
            text = _text(item, registry_record.component)
            content_key = _normalize_text(text) if text else identity
            if registry_record.component is DatasetComponent.IMAGE:
                content_key = item.byte_sha256.casefold()
            content_locations[content_key].add(split)
        if labels:
            label_locations[identity].add(tuple(sorted(labels)))
        group = _group_value(row, registry_record.grouping_field)
        if group and split:
            group_locations[group].add(split)
        elif registry_record.grouping_field:
            missing_groups += 1

    exact_leaks = sorted(
        key for key, splits in content_locations.items() if key and len(splits) > 1
    )
    identity_leaks = sorted(
        key for key, splits in split_locations.items() if key and len(splits) > 1
    )
    label_conflicts = sorted(
        key for key, labels in label_locations.items() if key and len(labels) > 1
    )
    group_leaks = sorted(
        key for key, splits in group_locations.items() if len(splits) > 1
    )

    exact = _check(
        "EXACT_DUPLICATE_LEAKAGE",
        CheckStatus.FAIL if exact_leaks else CheckStatus.PASS,
        exact_leaks,
    )
    cross_split = _check(
        "CROSS_SPLIT_OVERLAP",
        CheckStatus.FAIL if identity_leaks else CheckStatus.PASS,
        identity_leaks,
    )
    label = _check(
        "LABEL_LEAKAGE",
        CheckStatus.FAIL if label_conflicts else CheckStatus.PASS,
        label_conflicts,
    )

    if not registry_record.grouping_field:
        group = _check(
            "GROUP_LEAKAGE",
            CheckStatus.INSUFFICIENT_EVIDENCE,
            ["grouping_field is not registered"],
        )
    elif missing_groups:
        group = _check(
            "GROUP_LEAKAGE",
            CheckStatus.INSUFFICIENT_EVIDENCE,
            [f"{missing_groups} rows have no grouping value"],
        )
    else:
        group = _check(
            "GROUP_LEAKAGE",
            CheckStatus.FAIL if group_leaks else CheckStatus.PASS,
            group_leaks,
        )

    if registry_record.component in {
        DatasetComponent.NLP,
        DatasetComponent.CREDIBILITY,
    }:
        text_coverage = sum(
            bool(_text(item, registry_record.component)) and bool(_split_value(item))
            for item in records
        )
        near_matches = _near_text_leaks(records, registry_record.component)
        if text_coverage != len(records):
            near = _check(
                "NEAR_DUPLICATE_LEAKAGE",
                CheckStatus.INSUFFICIENT_EVIDENCE,
                [
                    (
                        "complete text and split coverage is required; "
                        f"available={text_coverage}, records={len(records)}"
                    )
                ],
            )
        elif near_matches == ["NEAR_DUPLICATE_SCAN_LIMIT_EXCEEDED"]:
            near = _check(
                "NEAR_DUPLICATE_LEAKAGE",
                CheckStatus.INSUFFICIENT_EVIDENCE,
                near_matches,
            )
        else:
            near = _check(
                "NEAR_DUPLICATE_LEAKAGE",
                CheckStatus.FAIL if near_matches else CheckStatus.PASS,
                near_matches,
            )
    elif registry_record.component is DatasetComponent.IMAGE:
        image_records = [
            item for item in records if isinstance(item, RegisteredImageAnnotation)
        ]
        if image_records and all(
            item.perceptual_similarity_hash for item in image_records
        ):
            near_matches = _image_near_leaks(image_records)
            near = _check(
                "NEAR_DUPLICATE_LEAKAGE",
                CheckStatus.FAIL if near_matches else CheckStatus.PASS,
                near_matches,
            )
        else:
            near = _check(
                "NEAR_DUPLICATE_LEAKAGE",
                CheckStatus.INSUFFICIENT_EVIDENCE,
                ["complete perceptual hashes are unavailable"],
                required=False,
            )
    else:
        near = _check(
            "NEAR_DUPLICATE_LEAKAGE",
            CheckStatus.INSUFFICIENT_EVIDENCE,
            ["near-duplicate detection is not supported for this schema"],
            required=False,
        )

    if registry_record.component is DatasetComponent.ANOMALY:
        timestamped: defaultdict[str, list[datetime]] = defaultdict(list)
        for item in records:
            split = _split_value(item)
            timestamp = getattr(item, "observed_at", None) or getattr(
                item, "observed_start_at", None
            )
            if split and timestamp:
                timestamped[split].append(timestamp)
        if not all(timestamped[name] for name in ("train", "validation", "test")):
            temporal = _check(
                "TEMPORAL_LEAKAGE",
                CheckStatus.INSUFFICIENT_EVIDENCE,
                ["all three splits require timestamps"],
            )
        else:
            overlaps = []
            if max(timestamped["train"]) >= min(timestamped["validation"]):
                overlaps.append("training period overlaps/follows validation")
            if max(timestamped["validation"]) >= min(timestamped["test"]):
                overlaps.append("validation period overlaps/follows test")
            temporal = _check(
                "TEMPORAL_LEAKAGE",
                CheckStatus.FAIL if overlaps else CheckStatus.PASS,
                overlaps,
            )
    else:
        temporal = _check(
            "TEMPORAL_LEAKAGE",
            CheckStatus.INSUFFICIENT_EVIDENCE,
            ["temporal ordering is not a required split rule for this component"],
            required=False,
        )

    checks = (exact, near, group, temporal, label, cross_split)
    required = [item for item in checks if item.required]
    overall = (
        CheckStatus.FAIL
        if any(item.status is CheckStatus.FAIL for item in required)
        else CheckStatus.INSUFFICIENT_EVIDENCE
        if any(item.status is CheckStatus.INSUFFICIENT_EVIDENCE for item in required)
        else CheckStatus.PASS
    )
    return DatasetLeakageReport(
        exact_duplicate_leakage=exact,
        near_duplicate_leakage=near,
        group_leakage=group,
        temporal_leakage=temporal,
        label_leakage=label,
        cross_split_overlap=cross_split,
        overall_status=overall,
    )


def _validate_images(
    dataset_root: Path,
    image_paths: list[Path],
    records: list[RegisteredImageAnnotation],
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    corrupt: list[str] = []
    resolutions: Counter[str] = Counter()
    ids: dict[str, Path] = {}
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    details: dict[Path, tuple[str, int, int, str]] = {}
    try:
        from PIL import Image
    except ImportError:
        return ["Pillow is required for image integrity validation"], {}

    for path in image_paths:
        relative = (
            path.relative_to(dataset_root).as_posix()
            if dataset_root.is_dir()
            else path.name
        )
        try:
            digest = _file_sha256(path)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.load()
                width, height = image.size
                image_format = image.format or "UNKNOWN"
            details[path] = (digest, width, height, image_format)
            resolutions[f"{width}x{height}"] += 1
            hashes[digest].append(relative)
            for key in {relative, path.name, path.stem}:
                if key in ids and ids[key] != path:
                    errors.append(f"ambiguous image identity: {key}")
                ids[key] = path
        except Exception as error:  # noqa: BLE001 - image decoders raise varied errors
            corrupt.append(relative)
            errors.append(f"corrupt image {relative}: {type(error).__name__}: {error}")

    missing: list[str] = []
    for annotation in records:
        key = annotation.image_path or annotation.image_id
        path = ids.get(key)
        if path is None:
            missing.append(annotation.image_id)
            continue
        digest, width, height, image_format = details[path]
        if digest.casefold() != annotation.byte_sha256.casefold():
            errors.append(f"image hash mismatch: {annotation.image_id}")
        if (width, height) != (annotation.width, annotation.height):
            errors.append(f"image dimension mismatch: {annotation.image_id}")
        if image_format != annotation.detected_format:
            errors.append(f"image format mismatch: {annotation.image_id}")
    if missing:
        errors.append("missing image files: " + ", ".join(sorted(set(missing))))
    duplicate_hashes = {
        digest: sorted(paths)
        for digest, paths in sorted(hashes.items())
        if len(paths) > 1
    }
    if duplicate_hashes:
        errors.append("duplicate image content hashes found")
    return errors, {
        "image_count": len(image_paths),
        "corrupt_images": sorted(corrupt),
        "duplicate_hashes": duplicate_hashes,
        "resolution_distribution": dict(sorted(resolutions.items())),
    }


def _validate_phase15_nlp_release_evidence(
    registry_record: DatasetRegistryRecord,
    dataset_path: Path,
    records: list[RegisteredNLPRecord],
) -> tuple[list[str], dict[str, Any]]:
    """Bind Phase 15 rows to their immutable manifest and leakage evidence."""

    from app.ml.data.nlp_dataset import (
        HUMAN_LABEL_SOURCE,
        NLP_DATASET_SCHEMA_VERSION,
        NLPDatasetLeakageReport,
        NLPDatasetVersionManifest,
    )

    if registry_record.schema_version != NLP_DATASET_SCHEMA_VERSION:
        return [], {}
    errors: list[str] = []
    metadata = registry_record.metadata
    required_metadata = (
        "manifest_path",
        "manifest_sha256",
        "leakage_report_path",
        "leakage_report_sha256",
        "dataset_hash",
        "source_manifest_hash",
    )
    missing = [name for name in required_metadata if not metadata.get(name)]
    if missing:
        return ["Phase 15 release evidence is missing: " + ", ".join(missing)], {
            "phase15_release_evidence": "MISSING"
        }

    def evidence_path(value: Any) -> Path:
        selected = local_only_path(value, description="NLP release evidence paths")
        if not selected.is_absolute():
            selected = dataset_path.parent / selected
        return selected.resolve()

    try:
        manifest_path = evidence_path(metadata["manifest_path"])
        leakage_path = evidence_path(metadata["leakage_report_path"])
        if not manifest_path.is_file():
            errors.append("Phase 15 dataset manifest is missing")
        if not leakage_path.is_file():
            errors.append("Phase 15 leakage report is missing")
        if errors:
            return errors, {"phase15_release_evidence": "MISSING"}
        manifest_hash = _file_sha256(manifest_path)
        leakage_hash = _file_sha256(leakage_path)
        if manifest_hash != metadata["manifest_sha256"]:
            errors.append("Phase 15 dataset manifest hash mismatch")
        if leakage_hash != metadata["leakage_report_sha256"]:
            errors.append("Phase 15 leakage report hash mismatch")
        manifest = NLPDatasetVersionManifest.model_validate_json(
            _strict_text(manifest_path)
        )
        leakage = NLPDatasetLeakageReport.model_validate_json(
            _strict_text(leakage_path)
        )
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        errors.append(
            f"Phase 15 release evidence is invalid: {type(error).__name__}: {error}"
        )
        return errors, {"phase15_release_evidence": "INVALID"}

    bindings = (
        (manifest.dataset_id == registry_record.dataset_id, "dataset ID"),
        (
            manifest.dataset_version == registry_record.dataset_version,
            "dataset version",
        ),
        (manifest.content_hash == registry_record.content_sha256, "content hash"),
        (manifest.dataset_hash == registry_record.content_sha256, "dataset hash"),
        (
            manifest.dataset_hash == metadata["dataset_hash"],
            "registered dataset hash",
        ),
        (
            manifest.source_manifest_hash == metadata["source_manifest_hash"],
            "source manifest hash",
        ),
        (manifest.dataset_schema_version == registry_record.schema_version, "schema"),
        (
            manifest.label_schema_version == registry_record.label_schema_version,
            "label schema",
        ),
        (manifest.record_count == len(records), "record count"),
        (
            manifest.leakage_report_hash == metadata["leakage_report_sha256"],
            "leakage report hash",
        ),
        (manifest.leakage_status == leakage.overall_status, "leakage status"),
    )
    errors.extend(
        f"Phase 15 manifest {description} binding mismatch"
        for matches, description in bindings
        if not matches
    )
    if manifest.human_ground_truth is not True:
        errors.append("Phase 15 manifest does not attest human ground truth")
    if manifest.automatic_label_generation != "NONE":
        errors.append("Phase 15 manifest permits automatic label generation")
    if leakage.overall_status == "FAIL" or leakage.protected_final_test_overlap:
        errors.append("Phase 15 release leakage evidence failed")
    grouped_rows = sum(bool(getattr(item, "group_id", None)) for item in records)
    expected_grouping_coverage = grouped_rows / len(records) if records else 0.0
    if abs(manifest.grouping_coverage - expected_grouping_coverage) > 1e-12:
        errors.append("Phase 15 manifest grouping coverage does not match dataset rows")
    if manifest.uncertainty_count != len(manifest.excluded_uncertain_report_ids):
        errors.append("Phase 15 manifest uncertainty count is inconsistent")

    source_manifest_path_value = metadata.get("source_manifest_path")
    source_manifest_sha256 = metadata.get("source_manifest_sha256")
    if source_manifest_path_value is not None or source_manifest_sha256 is not None:
        if not source_manifest_path_value or not source_manifest_sha256:
            errors.append("Phase 16 source manifest evidence is incomplete")
        else:
            try:
                source_manifest_path = evidence_path(source_manifest_path_value)
                if not source_manifest_path.is_file():
                    errors.append("Phase 16 source manifest is missing")
                else:
                    actual_source_manifest_hash = _file_sha256(source_manifest_path)
                    if actual_source_manifest_hash != source_manifest_sha256:
                        errors.append("Phase 16 source manifest hash mismatch")
                    if actual_source_manifest_hash != manifest.source_manifest_hash:
                        errors.append("Phase 16 manifest source binding mismatch")
                    from app.ml.data.nlp_corpus import NLPCorpusSourceManifest

                    source_manifest = NLPCorpusSourceManifest.model_validate_json(
                        _strict_text(source_manifest_path)
                    )
                    if (
                        source_manifest.provenance_classification
                        is not registry_record.provenance
                    ):
                        errors.append(
                            "Phase 16 source-manifest provenance does not match registry"
                        )
                    enrolled_source_path = local_only_path(
                        source_manifest.local_path,
                        description="NLP corpus source paths",
                    )
                    if not enrolled_source_path.is_file():
                        errors.append("Phase 16 enrolled source is missing")
                    elif (
                        hash_dataset_path(enrolled_source_path).content_sha256
                        != source_manifest.content_hash
                    ):
                        errors.append("Phase 16 enrolled source content hash mismatch")
            except (OSError, UnicodeError, ValueError, ValidationError) as error:
                errors.append(
                    "Phase 16 source manifest evidence is invalid: "
                    f"{type(error).__name__}: {error}"
                )

    missing_row_evidence = sorted(
        item.record_id
        for item in records
        if getattr(item, "human_adjudicated", None) is not True
        or getattr(item, "label_provenance", None) != HUMAN_LABEL_SOURCE
        or not getattr(item, "annotation_ids", None)
        or not getattr(item, "annotator_ids", None)
        or not getattr(item, "adjudication_id", None)
        or not getattr(item, "adjudicator_id", None)
    )
    if missing_row_evidence:
        errors.append(
            "Phase 15 rows lack explicit human adjudication evidence: "
            + ", ".join(missing_row_evidence)
        )

    label_counts = Counter(item.event_type for item in records)
    language_counts = Counter(item.language for item in records)
    expected_labels = {key: label_counts.get(key, 0) for key in manifest.label_counts}
    expected_languages = {
        key: language_counts.get(key, 0) for key in manifest.language_counts
    }
    if manifest.label_counts != expected_labels:
        errors.append("Phase 15 manifest label counts do not match dataset rows")
    if manifest.language_counts != expected_languages:
        errors.append("Phase 15 manifest language counts do not match dataset rows")

    independent_ids = set(manifest.independent_test_dataset_ids)
    test_source_ids = {
        getattr(item, "source_dataset_id", None)
        for item in records
        if _split_value(item) == "test"
    }
    development_source_ids = {
        getattr(item, "source_dataset_id", None)
        for item in records
        if _split_value(item) in {"train", "validation"}
    }
    if any(value is None or value not in independent_ids for value in test_source_ids):
        errors.append("Phase 15 test rows lack an independent source-dataset binding")
    if independent_ids & development_source_ids:
        errors.append("Phase 15 independent test source appears in development rows")

    return errors, {
        "phase15_release_evidence": "VALID" if not errors else "INVALID",
        "manifest_sha256": metadata["manifest_sha256"],
        "leakage_report_sha256": metadata["leakage_report_sha256"],
        "dataset_hash": manifest.dataset_hash,
        "source_manifest_hash": manifest.source_manifest_hash,
        "grouping_coverage": manifest.grouping_coverage,
        "uncertainty_count": manifest.uncertainty_count,
        "human_adjudication_row_coverage": (
            (len(records) - len(missing_row_evidence)) / len(records)
            if records
            else 0.0
        ),
        "independent_test_dataset_ids": sorted(independent_ids),
    }


def _validate_synthetic_nlp_release_evidence(
    registry_record: DatasetRegistryRecord,
    records: list[RegisteredNLPRecord],
    registry_path: Path | str,
) -> tuple[list[str], dict[str, Any]]:
    """Verify Phase 17 synthetic evidence and every registry-bound hash."""

    synthetic_schema = "synthetic-nlp-report-dataset-v1"
    if registry_record.schema_version != synthetic_schema:
        return [], {}

    from app.ml.data.synthetic_nlp.validation import SyntheticNLPDatasetReport

    errors: list[str] = []
    metadata = registry_record.metadata
    required_metadata = (
        "dataset_hash",
        "generator_version",
        "scenario_version",
        "template_version",
        "split_version",
        "seed",
        "quality_report_path",
        "quality_report_sha256",
        "manifest_path",
        "manifest_sha256",
        "scenario_metadata_path",
        "scenario_metadata_sha256",
    )
    missing = [name for name in required_metadata if metadata.get(name) in (None, "")]
    if missing:
        errors.append(
            "synthetic NLP registry metadata is incomplete: " + ", ".join(missing)
        )
        return errors, {"synthetic_release_evidence": "INVALID"}

    if registry_record.provenance.value != "PROJECT_AUTHORED":
        errors.append("synthetic NLP provenance must be PROJECT_AUTHORED")
    if (
        registry_record.data_classification
        is not DatasetClassification.DEVELOPMENT_ONLY
    ):
        errors.append("synthetic NLP data must remain DEVELOPMENT_ONLY")
    if registry_record.human_adjudicated:
        errors.append("synthetic NLP data cannot claim human adjudication")
    if registry_record.label_source != "PROJECT_GENERATED_SYNTHETIC":
        errors.append("synthetic NLP label source is invalid")
    if metadata.get("synthetic") is not True:
        errors.append("synthetic NLP registry marker is missing")
    if metadata.get("production_validation") != "NOT_PRODUCTION_VALIDATION":
        errors.append("synthetic NLP data cannot claim production validation")

    evidence: dict[str, Path] = {}
    for name in ("quality_report", "manifest", "scenario_metadata"):
        path = resolve_registry_path(str(metadata[f"{name}_path"]), registry_path)
        expected_hash = str(metadata[f"{name}_sha256"])
        if not path.is_file():
            errors.append(f"synthetic NLP {name} evidence is missing")
            continue
        if _file_sha256(path) != expected_hash:
            errors.append(f"synthetic NLP {name} evidence hash mismatch")
            continue
        evidence[name] = path

    if "quality_report" not in evidence or "manifest" not in evidence:
        return errors, {"synthetic_release_evidence": "INVALID"}

    try:
        report = SyntheticNLPDatasetReport.model_validate_json(
            evidence["quality_report"].read_text(encoding="utf-8", errors="strict")
        )
        manifest = json.loads(
            evidence["manifest"].read_text(encoding="utf-8", errors="strict")
        )
        if not isinstance(manifest, dict):
            raise TypeError("manifest must be a JSON object")
    except (OSError, UnicodeError, TypeError, ValueError, ValidationError) as error:
        errors.append(
            f"synthetic NLP evidence is invalid: {type(error).__name__}: {error}"
        )
        return errors, {"synthetic_release_evidence": "INVALID"}

    class_counts = Counter(item.event_type for item in records)
    language_counts = Counter(item.language for item in records)
    split_counts = Counter(_split_value(item) for item in records)
    expected_bindings = (
        (report.valid is True, "quality report is not valid"),
        (
            report.dataset_hash == registry_record.content_sha256,
            "quality report dataset hash mismatch",
        ),
        (
            report.scenario_metadata_hash == metadata["scenario_metadata_sha256"],
            "quality report scenario hash mismatch",
        ),
        (
            metadata["dataset_hash"] == registry_record.content_sha256,
            "registry dataset hash metadata mismatch",
        ),
        (
            report.generator_version == metadata["generator_version"]
            and report.scenario_version == metadata["scenario_version"]
            and report.template_version == metadata["template_version"]
            and report.split_version == metadata["split_version"]
            and report.seed == metadata["seed"],
            "quality report generator configuration mismatch",
        ),
        (
            report.provenance == "PROJECT_AUTHORED"
            and report.classification == "SYNTHETIC / DEVELOPMENT_ONLY"
            and report.production_validation == "NOT_PRODUCTION_VALIDATION",
            "quality report governance mismatch",
        ),
        (report.total_rows == len(records), "quality report row count mismatch"),
        (
            report.rows_per_class == dict(class_counts),
            "quality report class counts mismatch",
        ),
        (
            report.rows_per_language == dict(language_counts),
            "quality report language counts mismatch",
        ),
        (
            report.rows_per_split == dict(split_counts),
            "quality report split counts mismatch",
        ),
        (
            report.leakage_results.status == "PASS",
            "synthetic leakage evidence did not pass",
        ),
        (
            not any(report.duplicate_counts.values()),
            "synthetic quality report contains duplicates",
        ),
        (
            report.label_consistency_failures == 0
            and report.scenario_binding_failures == 0,
            "synthetic scenario or label binding failed",
        ),
        (
            manifest.get("dataset_id") == registry_record.dataset_id
            and manifest.get("dataset_version") == registry_record.dataset_version,
            "synthetic manifest identity mismatch",
        ),
        (
            manifest.get("dataset_sha256") == registry_record.content_sha256,
            "synthetic manifest dataset hash mismatch",
        ),
        (
            manifest.get("generator_version") == metadata["generator_version"]
            and manifest.get("scenario_version") == metadata["scenario_version"]
            and manifest.get("template_version") == metadata["template_version"]
            and manifest.get("split_version") == metadata["split_version"]
            and manifest.get("seed") == metadata["seed"]
            and manifest.get("total_rows") == len(records),
            "synthetic manifest generator configuration mismatch",
        ),
        (
            manifest.get("quality_report_sha256") == metadata["quality_report_sha256"],
            "synthetic manifest quality-report hash mismatch",
        ),
        (
            manifest.get("scenario_metadata_sha256")
            == metadata["scenario_metadata_sha256"],
            "synthetic manifest scenario hash mismatch",
        ),
        (
            manifest.get("provenance") == "PROJECT_AUTHORED"
            and manifest.get("data_kind") == "SYNTHETIC"
            and manifest.get("classification") == "DEVELOPMENT_ONLY",
            "synthetic manifest governance mismatch",
        ),
        (
            manifest.get("production_validation") == "NOT_PRODUCTION_VALIDATION",
            "synthetic manifest production claim is invalid",
        ),
        (
            manifest.get("models_trained") == []
            and manifest.get("pretrained_models") == []
            and manifest.get("open_weight_models") == []
            and manifest.get("external_apis") == []
            and manifest.get("network_access") is False,
            "synthetic manifest model/network policy mismatch",
        ),
    )
    errors.extend(message for passed, message in expected_bindings if not passed)
    return errors, {
        "synthetic_release_evidence": "VALID" if not errors else "INVALID",
        "synthetic_quality_report_sha256": metadata["quality_report_sha256"],
        "synthetic_manifest_sha256": metadata["manifest_sha256"],
        "synthetic_scenario_metadata_sha256": metadata["scenario_metadata_sha256"],
        "synthetic_near_duplicate_method": report.leakage_results.method,
        "synthetic_leakage_status": report.leakage_results.status,
        "synthetic_hard_negative_rows": report.hard_negative_rows,
        "synthetic_evidence_scope": "DEVELOPMENT_ONLY",
    }


def _component_quality(
    registry_record: DatasetRegistryRecord,
    dataset_path: Path,
    loaded: _LoadedDataset,
    parsed: _ParsedDataset,
    registry_path: Path | str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    records = parsed.records
    component = registry_record.component
    if component is DatasetComponent.NLP:
        ids = [item.record_id for item in records]
        duplicate_ids = sorted(key for key, count in Counter(ids).items() if count > 1)
        text_labels: defaultdict[str, set[str]] = defaultdict(set)
        text_ids: defaultdict[str, list[str]] = defaultdict(list)
        for item in records:
            normalized = _normalize_text(item.text)
            text_labels[normalized].add(item.event_type)
            text_ids[normalized].append(item.record_id)
        conflicts = sorted(
            key for key, labels in text_labels.items() if len(labels) > 1
        )
        duplicate_texts = sorted(
            sorted(ids) for ids in text_ids.values() if len(ids) > 1
        )
        if duplicate_ids:
            errors.append("duplicate NLP record identifiers")
        if conflicts:
            errors.append("normalized NLP text has contradictory labels")
        class_counts = Counter(item.event_type for item in records)
        language_counts = Counter(item.language for item in records)
        split_counts = Counter(_split_value(item) for item in records)
        subgroup_sizes = Counter(
            f"{_split_value(item)}::{item.language}" for item in records
        )
        readiness = {
            "class_counts": dict(sorted(class_counts.items())),
            "language_counts": dict(sorted(language_counts.items())),
            "train_validation_test_counts": dict(sorted(split_counts.items())),
            "subgroup_sizes": dict(sorted(subgroup_sizes.items())),
            "duplicate_texts": duplicate_texts,
            "label_conflicts": conflicts,
        }
        phase15_errors, phase15_readiness = _validate_phase15_nlp_release_evidence(
            registry_record,
            dataset_path,
            records,
        )
        errors.extend(phase15_errors)
        readiness.update(phase15_readiness)
        synthetic_errors, synthetic_readiness = (
            _validate_synthetic_nlp_release_evidence(
                registry_record,
                records,
                registry_path,
            )
        )
        errors.extend(synthetic_errors)
        readiness.update(synthetic_readiness)
    elif component is DatasetComponent.DUPLICATE:
        quality = validate_duplicate_pairs(records)
        errors.extend(quality.errors)
        warnings.extend(quality.warnings)
        label_counts = Counter(item.label.value for item in records)
        grouped = sum(
            bool(
                item.event_id_when_known
                or item.event_id
                or item.incident_id_when_known
                or item.incident_id
            )
            for item in records
        )
        readiness = {
            "pair_count": len(records),
            "label_counts": dict(sorted(label_counts.items())),
            "duplicate_count": label_counts[DuplicatePairLabel.DUPLICATE.value],
            "non_duplicate_count": label_counts[DuplicatePairLabel.NOT_DUPLICATE.value],
            "uncertain_count": label_counts[DuplicatePairLabel.UNCERTAIN.value],
            "event_or_incident_grouping_coverage": grouped / len(records)
            if records
            else 0.0,
            "reversed_pair_conflicts": quality.reversed_pair_ids,
            "contradictory_pair_keys": quality.contradictory_pair_keys,
        }
    elif component is DatasetComponent.EVENT:
        pair_records = [
            item for item in records if isinstance(item, EventPairAnnotation)
        ]
        event_quality = None
        if pair_records:
            event_quality = validate_event_annotations(pair_records)
            errors.extend(event_quality.errors)
            warnings.extend(event_quality.warnings)
        event_ids: set[str] = set()
        reports_per_event: Counter[str] = Counter()
        event_types: Counter[str] = Counter()
        for item in records:
            if isinstance(item, RegisteredEventPair):
                event_ids.update((item.event_a_id, item.event_b_id))
                reports_per_event[item.event_a_id] += len(item.report_ids_a)
                reports_per_event[item.event_b_id] += len(item.report_ids_b)
                for value in (item.event_type_a, item.event_type_b):
                    if value:
                        event_types[value] += 1
            else:
                event_ids.add(item.event_id)
                reports_per_event[item.event_id] += 1
                if item.event_type:
                    event_types[item.event_type] += 1
        grouped = sum(
            bool(getattr(item, "canonical_event_id", None)) for item in records
        )
        readiness = {
            "event_count": len(event_ids),
            "reports_per_event": dict(sorted(reports_per_event.items())),
            "event_type_coverage": dict(sorted(event_types.items())),
            "grouping_coverage": grouped / len(records) if records else 0.0,
            "contradictory_pair_keys": (
                event_quality.contradictory_pair_keys if event_quality else []
            ),
        }
    elif component is DatasetComponent.CREDIBILITY:
        quality = validate_fake_report_annotations(records)
        errors.extend(quality.errors)
        warnings.extend(quality.warnings)
        unresolved = len(quality.disagreement_report_ids)
        readiness = {
            "label_counts": quality.label_counts,
            "authentic_count": quality.label_counts.get(
                FakeReportLabel.AUTHENTIC.value, 0
            ),
            "misleading_count": quality.label_counts.get(
                FakeReportLabel.MISLEADING.value, 0
            ),
            "uncertain_count": quality.label_counts.get(
                FakeReportLabel.UNCERTAIN.value, 0
            ),
            "annotator_counts": quality.annotator_counts,
            "adjudication_coverage": (
                (quality.repeated_report_count - unresolved)
                / quality.repeated_report_count
                if quality.repeated_report_count
                else None
            ),
        }
    elif component is DatasetComponent.IMAGE:
        image_records = [
            item for item in records if isinstance(item, RegisteredImageAnnotation)
        ]
        quality = validate_image_annotations(image_records)
        errors.extend(quality.errors)
        warnings.extend(quality.warnings)
        image_errors, image_metrics = _validate_images(
            dataset_path,
            loaded.image_paths,
            image_records,
        )
        errors.extend(image_errors)
        grouping_fields = ("event_id", "incident_id", "report_id", "capture_session_id")
        grouped = sum(
            any(getattr(item, name) for name in grouping_fields)
            for item in image_records
        )
        readiness = {
            **image_metrics,
            "class_multilabel_frequency": quality.label_counts,
            "grouping_coverage": grouped / len(image_records) if image_records else 0.0,
        }
    else:
        if registry_record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE:
            station_counts = Counter(item.station_id for item in records)
            timestamps = sorted(
                item.observed_at for item in records if item.observed_at
            )
            intervals = [
                (right - left).total_seconds()
                for left, right in pairwise(timestamps)
                if right > left
            ]
            missing = sum(
                item.rainfall_mm is None and item.river_level_m is None
                for item in records
            )
            non_finite = [
                item.observation_id
                for item in records
                if any(
                    value is not None and not math.isfinite(value)
                    for value in (item.rainfall_mm, item.river_level_m)
                )
            ]
            negative = [
                item.observation_id
                for item in records
                if item.rainfall_mm is not None and item.rainfall_mm < 0
            ]
            if non_finite:
                errors.append("non-finite anomaly baseline measurements")
            if negative:
                errors.append("negative rainfall measurements")
            readiness = {
                "stations": dict(sorted(station_counts.items())),
                "observation_count": len(records),
                "time_span": {
                    "start": timestamps[0].isoformat() if timestamps else None,
                    "end": timestamps[-1].isoformat() if timestamps else None,
                },
                "sampling_density_median_seconds": median(intervals)
                if intervals
                else None,
                "missingness_count": missing,
                "domain_labels": dict(
                    sorted(
                        Counter(
                            item.domain_label for item in records if item.domain_label
                        ).items()
                    )
                ),
                "temporal_coverage": len(set(timestamps)),
            }
        else:
            quality = validate_anomaly_annotations(records)
            errors.extend(quality.errors)
            warnings.extend(quality.warnings)
            stations = Counter(item.station_id for item in records)
            starts = sorted(
                item.observed_start_at for item in records if item.observed_start_at
            )
            ends = sorted(
                item.observed_end_at for item in records if item.observed_end_at
            )
            readiness = {
                "stations": dict(sorted(stations.items())),
                "observation_count": sum(len(item.observation_ids) for item in records),
                "time_span": {
                    "start": starts[0].isoformat() if starts else None,
                    "end": ends[-1].isoformat() if ends else None,
                },
                "sampling_density_median_seconds": None,
                "missingness_count": None,
                "domain_labels": quality.domain_counts,
                "temporal_coverage": len(starts),
            }
    return sorted(set(errors)), sorted(set(warnings)), readiness


def _approval_blockers(
    record: DatasetRegistryRecord,
    valid: bool,
    leakage: DatasetLeakageReport,
    split_counts: dict[str, int],
    split_label_counts: dict[str, dict[str, int]],
    records: list[Any],
    grouping_coverage: float | None,
    readiness: dict[str, Any],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for use in DatasetUse:
        split = USE_TO_SPLIT[use]
        blockers: list[str] = []
        if not valid:
            blockers.append("DATASET_INVALID")
        if leakage.overall_status is not CheckStatus.PASS:
            blockers.append(f"LEAKAGE_{leakage.overall_status.value}")
        if split_counts.get(split, 0) == 0:
            blockers.append(f"{split.upper()}_SPLIT_MISSING")
        labels = {
            label: count
            for label, count in split_label_counts.get(split, {}).items()
            if label not in {"UNCERTAIN", "None"}
        }
        unsupervised_anomaly = (
            record.component is DatasetComponent.ANOMALY
            and record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE
        )
        minimum_per_label = 2 if use is DatasetUse.TRAINING else 1
        if not unsupervised_anomaly and (
            len(labels) < 2
            or any(count < minimum_per_label for count in labels.values())
        ):
            blockers.append("INSUFFICIENT_LABELS")
        if record.provenance.value == "PROVENANCE_UNKNOWN":
            blockers.append("PROVENANCE_UNKNOWN")
        if record.data_classification is DatasetClassification.DEVELOPMENT_ONLY:
            blockers.append("DEVELOPMENT_ONLY_DATASET")
        if record.data_classification is DatasetClassification.TEST_FIXTURE_ONLY:
            blockers.append("TEST_FIXTURE_ONLY_DATASET")
        if (
            use is DatasetUse.TRAINING
            and record.data_classification is DatasetClassification.PRODUCTION_TEST
        ):
            blockers.append("PRODUCTION_TEST_DATA_CANNOT_BE_TRAINING_DATA")
        if grouping_coverage is None or grouping_coverage < 1.0:
            blockers.append("GROUPING_METADATA_INCOMPLETE")

        if record.component is DatasetComponent.NLP:
            prohibited_sources = (
                "MODEL",
                "MATCHER",
                "HEURISTIC",
                "RULE",
                "DETECTOR",
                "GENERATED",
                "RANDOM",
                "KEYWORD",
                "LLM",
            )
            if not record.human_adjudicated:
                blockers.append("HUMAN_ADJUDICATION_REQUIRED")
            if record.label_source == "PROJECT_GENERATED_SYNTHETIC":
                blockers.append("SYNTHETIC_LABELS_DEVELOPMENT_ONLY")
            elif any(
                token in record.label_source.upper() for token in prohibited_sources
            ):
                blockers.append("MODEL_GENERATED_LABELS_PROHIBITED")
            language_counts = Counter(
                item.language for item in records if _split_value(item) == split
            )
            if len(language_counts) < 2:
                blockers.append("MULTILINGUAL_COVERAGE_INSUFFICIENT")
            if use is DatasetUse.TRAINING and (
                split_counts.get("validation", 0) == 0
                or split_counts.get("test", 0) == 0
            ):
                blockers.append("INDEPENDENT_VALIDATION_AND_TEST_REQUIRED")
        elif record.component in {
            DatasetComponent.DUPLICATE,
            DatasetComponent.EVENT,
            DatasetComponent.CREDIBILITY,
            DatasetComponent.IMAGE,
        }:
            prohibited_sources = (
                "MODEL",
                "MATCHER",
                "HEURISTIC",
                "RULE",
                "DETECTOR",
                "GENERATED",
            )
            if not record.human_adjudicated:
                blockers.append("HUMAN_ADJUDICATION_REQUIRED")
            if any(
                token in record.label_source.upper() for token in prohibited_sources
            ):
                blockers.append("MODEL_GENERATED_LABELS_PROHIBITED")
        elif record.component is DatasetComponent.ANOMALY:
            if record.anomaly_data_role is None:
                blockers.append("ANOMALY_DATA_ROLE_REQUIRED")
            elif (
                record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE
                and use in {DatasetUse.VALIDATION, DatasetUse.TEST}
            ):
                blockers.append("UNSUPERVISED_BASELINE_NOT_EVALUATION_GROUND_TRUTH")
            elif (
                record.anomaly_data_role is AnomalyDataRole.SUPERVISED_EVALUATION
                and not record.human_adjudicated
            ):
                blockers.append("HUMAN_ANOMALY_LABELS_REQUIRED")

        if record.component is DatasetComponent.IMAGE:
            if readiness.get("image_count", 0) == 0:
                blockers.append("REAL_IMAGE_FILES_REQUIRED")
            if readiness.get("corrupt_images"):
                blockers.append("CORRUPT_IMAGES_PRESENT")
        result[use.value] = sorted(set(blockers))
    return result


def validate_dataset_record(
    record: DatasetRegistryRecord,
    *,
    registry_path: Path | str,
    generated_at: datetime | None = None,
) -> RegisteredDatasetValidationReport:
    """Validate one registered local dataset without changing registry state."""

    timestamp = generated_at or datetime.now(timezone.utc)
    dataset_path = resolve_registry_path(record.local_path, registry_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        hash_result = hash_dataset_path(dataset_path)
        actual_hash = hash_result.content_sha256
        file_integrity = _check("FILE_INTEGRITY", CheckStatus.PASS)
    except Exception as error:  # noqa: BLE001 - any integrity failure invalidates data
        actual_hash = "0" * 64
        errors.append(f"file integrity failed: {type(error).__name__}: {error}")
        file_integrity = _check("FILE_INTEGRITY", CheckStatus.FAIL, list(errors))
    hash_matches = actual_hash == record.content_sha256
    hash_check = _check(
        "CONTENT_HASH",
        CheckStatus.PASS if hash_matches else CheckStatus.FAIL,
        [] if hash_matches else ["registered content hash does not match local data"],
    )
    if not hash_matches:
        errors.append("DATASET_HASH_MISMATCH")

    loaded = (
        _load_dataset(dataset_path, record)
        if actual_hash != "0" * 64
        else _LoadedDataset()
    )
    errors.extend(loaded.errors)
    warnings.extend(loaded.warnings)
    encoding_check = _check(
        "ENCODING_AND_UNICODE",
        CheckStatus.FAIL
        if any("Unicode" in item or "decode" in item for item in loaded.errors)
        else CheckStatus.PASS,
        [item for item in loaded.errors if "Unicode" in item or "decode" in item],
    )
    parsed = _parse_rows(record, loaded.rows)
    errors.extend(parsed.errors)
    schema_check = _check(
        "SCHEMA_AND_REQUIRED_FIELDS",
        CheckStatus.FAIL if parsed.errors or not parsed.records else CheckStatus.PASS,
        parsed.errors
        or ([] if parsed.records else ["dataset contains no valid records"]),
    )
    quality_errors, quality_warnings, readiness = _component_quality(
        record,
        dataset_path,
        loaded,
        parsed,
        registry_path,
    )
    errors.extend(quality_errors)
    warnings.extend(quality_warnings)
    (
        common_errors,
        null_check,
        coordinate_check,
        timestamp_check,
    ) = _common_value_checks(
        loaded.rows,
        record,
    )
    errors.extend(common_errors)

    raw_duplicates: defaultdict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(loaded.rows, start=1):
        raw_duplicates[hashlib.sha256(_canonical_json(row)).hexdigest()].append(index)
    duplicate_rows = [
        indexes for indexes in raw_duplicates.values() if len(indexes) > 1
    ]
    if duplicate_rows:
        errors.append("exact duplicate rows found")
    duplicate_check = _check(
        "DUPLICATE_RECORDS",
        CheckStatus.FAIL if duplicate_rows else CheckStatus.PASS,
        [str(value) for value in duplicate_rows],
    )

    records = parsed.records
    label_distribution: Counter[str] = Counter(
        label for item in records for label in _labels(item, record.component)
    )
    split_counts: Counter[str] = Counter(
        split for item in records if (split := _split_value(item))
    )
    split_label_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for item in records:
        split = _split_value(item)
        if split:
            split_label_counts[split].update(_labels(item, record.component))

    grouping_values = [_group_value(row, record.grouping_field) for row in loaded.rows]
    grouping_coverage = (
        sum(value is not None for value in grouping_values) / len(grouping_values)
        if record.grouping_field and grouping_values
        else None
    )
    group_check = _check(
        "GROUP_IDENTIFIERS",
        CheckStatus.PASS
        if grouping_coverage == 1.0
        else CheckStatus.INSUFFICIENT_EVIDENCE,
        []
        if grouping_coverage == 1.0
        else ["complete registered grouping identifiers are unavailable"],
    )
    unsupervised_anomaly = (
        record.component is DatasetComponent.ANOMALY
        and record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE
    )
    label_check = _check(
        "LABEL_DISTRIBUTION",
        CheckStatus.PASS
        if label_distribution or unsupervised_anomaly
        else CheckStatus.FAIL,
        (
            ["labels are intentionally optional for an unsupervised baseline"]
            if unsupervised_anomaly and not label_distribution
            else []
            if label_distribution
            else ["no labels were parsed"]
        ),
        required=not unsupervised_anomaly,
    )
    if not label_distribution and not unsupervised_anomaly:
        errors.append("labels are missing")

    duplicate_image_hashes = (
        readiness.get("duplicate_hashes", {})
        if record.component is DatasetComponent.IMAGE
        else {}
    )
    duplicate_image_check = _check(
        "DUPLICATE_IMAGES",
        CheckStatus.FAIL if duplicate_image_hashes else CheckStatus.PASS,
        sorted(duplicate_image_hashes),
        required=record.component is DatasetComponent.IMAGE,
    )
    contradiction_keys = [
        *readiness.get("label_conflicts", []),
        *readiness.get("contradictory_pair_keys", []),
    ]
    contradiction_check = _check(
        "CONTRADICTORY_LABELS",
        CheckStatus.FAIL if contradiction_keys else CheckStatus.PASS,
        sorted(set(contradiction_keys)),
    )

    aligned_rows = [loaded.rows[index] for index in parsed.row_indexes]
    leakage = _leakage_report(
        record,
        aligned_rows,
        records,
    )
    if readiness.get("synthetic_release_evidence") == "VALID":
        synthetic_near_duplicate = _check(
            "NEAR_DUPLICATE_LEAKAGE",
            CheckStatus.PASS,
            ["verified by hash-bound Phase 17 scalable synthetic leakage report"],
        )
        required_leakage_checks = (
            leakage.exact_duplicate_leakage,
            synthetic_near_duplicate,
            leakage.group_leakage,
            leakage.label_leakage,
            leakage.cross_split_overlap,
        )
        synthetic_overall = (
            CheckStatus.FAIL
            if any(item.status is CheckStatus.FAIL for item in required_leakage_checks)
            else CheckStatus.INSUFFICIENT_EVIDENCE
            if any(
                item.status is CheckStatus.INSUFFICIENT_EVIDENCE
                for item in required_leakage_checks
            )
            else CheckStatus.PASS
        )
        leakage = leakage.model_copy(
            update={
                "near_duplicate_leakage": synthetic_near_duplicate,
                "overall_status": synthetic_overall,
            }
        )
    if leakage.overall_status is CheckStatus.FAIL:
        errors.append("dataset leakage checks failed")

    checks = [
        file_integrity,
        hash_check,
        encoding_check,
        schema_check,
        null_check,
        duplicate_check,
        duplicate_image_check,
        contradiction_check,
        coordinate_check,
        timestamp_check,
        group_check,
        label_check,
    ]
    valid = not errors and all(
        check.status is not CheckStatus.FAIL for check in checks if check.required
    )
    split_counts_dict = {
        name: split_counts.get(name, 0) for name in ("train", "validation", "test")
    }
    split_label_counts_dict = {
        name: dict(sorted(split_label_counts[name].items()))
        for name in ("train", "validation", "test")
    }
    blockers = _approval_blockers(
        record,
        valid,
        leakage,
        split_counts_dict,
        split_label_counts_dict,
        records,
        grouping_coverage,
        readiness,
    )
    row_or_image_count = (
        len(loaded.image_paths)
        if record.component is DatasetComponent.IMAGE
        else len(loaded.rows)
    )
    return RegisteredDatasetValidationReport(
        generated_at=timestamp,
        dataset_id=record.dataset_id,
        dataset_version=record.dataset_version,
        component=record.component,
        local_path=record.local_path,
        format=record.format,
        registered_content_sha256=record.content_sha256,
        content_sha256=actual_hash,
        hash_matches_registry=hash_matches,
        valid=valid,
        validation_status="VALID" if valid else "INVALID",
        checks=checks,
        leakage=leakage,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        row_or_image_count=row_or_image_count,
        label_count=sum(label_distribution.values()),
        label_distribution=dict(sorted(label_distribution.items())),
        split_counts=split_counts_dict,
        split_label_counts=split_label_counts_dict,
        grouping_coverage=grouping_coverage,
        component_readiness=readiness,
        approval_blockers=blockers,
    )


def write_validation_report(
    report: RegisteredDatasetValidationReport,
    path: Path | str,
) -> str:
    selected = local_only_path(path, description="dataset validation reports")
    selected.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump_json(indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=selected.parent,
        prefix=selected.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    temporary.replace(selected)
    return _file_sha256(selected)


def validate_registered_dataset(
    dataset_id: str,
    *,
    registry_path: Path | str,
    dataset_version: str | None = None,
    report_path: Path | str | None = None,
    generated_at: datetime | None = None,
) -> RegisteredDatasetValidationReport:
    """Validate, write a report, and invalidate all earlier approvals."""

    registry = load_dataset_registry(registry_path)
    record = find_dataset(registry, dataset_id, dataset_version)
    report = validate_dataset_record(
        record,
        registry_path=registry_path,
        generated_at=generated_at,
    )
    registry_file = local_only_path(
        registry_path, description="dataset registries"
    ).resolve()
    selected_report_path = local_only_path(
        report_path
        or registry_file.parent
        / "reports"
        / f"{record.dataset_id}-{record.dataset_version}.validation.json",
        description="dataset validation reports",
    ).resolve()
    report_hash = write_validation_report(report, selected_report_path)
    try:
        stored_report_path = selected_report_path.relative_to(
            registry_file.parent
        ).as_posix()
    except ValueError:
        stored_report_path = str(selected_report_path)
    updated = record.model_copy(
        update={
            "status": DatasetStatus.VALID if report.valid else DatasetStatus.INVALID,
            "row_or_image_count": report.row_or_image_count,
            "label_count": report.label_count,
            "validation_report_path": stored_report_path,
            "validation_report_sha256": report_hash,
            "approvals": [],
        }
    )
    entries = [
        updated
        if (item.dataset_id, item.dataset_version)
        == (record.dataset_id, record.dataset_version)
        else item
        for item in registry.entries
    ]
    save_dataset_registry(
        registry.model_copy(update={"entries": entries}),
        registry_path,
        modified_at=generated_at,
    )
    return report


def materialize_explicit_splits(
    dataset_id: str,
    output_directory: Path | str,
    *,
    registry_path: Path | str,
    dataset_version: str | None = None,
) -> dict[str, Path]:
    """Write existing explicit assignments only; never create a random row split."""

    registry = load_dataset_registry(registry_path)
    record = find_dataset(registry, dataset_id, dataset_version)
    report = validate_dataset_record(record, registry_path=registry_path)
    if not report.valid or report.leakage.overall_status is not CheckStatus.PASS:
        raise ValueError(
            "dataset must be valid and leakage PASS before split materialization"
        )
    source = resolve_registry_path(record.local_path, registry_path)
    loaded = _load_dataset(source, record)
    if loaded.errors:
        raise ValueError("dataset could not be loaded: " + "; ".join(loaded.errors))
    buckets: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for row in loaded.rows:
        split = row.get(record.split_field)
        if split not in buckets:
            raise ValueError("every row requires an explicit valid split assignment")
        buckets[split].append(row)
    target = local_only_path(
        output_directory,
        description="dataset split output directories",
    ).resolve()
    target.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for split, rows in buckets.items():
        path = target / f"{record.dataset_id}.{split}.jsonl"
        if path.exists():
            raise ValueError(f"split output already exists: {path}")
        ordered = sorted(rows, key=lambda row: _canonical_json(row))
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            for row in ordered:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        outputs[split] = path
    return outputs


__all__ = [
    "CheckStatus",
    "DatasetLeakageReport",
    "RegisteredDatasetValidationReport",
    "ValidationCheck",
    "materialize_explicit_splits",
    "validate_dataset_record",
    "validate_registered_dataset",
    "validation_report_sha256",
    "write_validation_report",
]
