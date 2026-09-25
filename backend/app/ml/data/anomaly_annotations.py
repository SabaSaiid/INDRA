"""Human anomaly annotations and leakage-safe temporal/station split tools."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import local_only_path
from app.ml.contracts import (
    AnomalyDomain,
    AnomalyScope,
    AnomalyType,
    WeatherObservation,
)


class AnomalyAnnotationLabel(str, Enum):
    ANOMALY = "ANOMALY"
    NORMAL = "NORMAL"
    UNCERTAIN = "UNCERTAIN"


AnomalySplit = Literal["train", "validation", "test"]
ANOMALY_ANNOTATION_SCHEMA_VERSION = "anomaly-annotations-v1"


class AnomalyAnnotation(BaseModel):
    """One immutable human judgment for a point or time window."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(
        default_factory=lambda: f"anomaly-annotation-{uuid4()}", min_length=1
    )
    target_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    observation_ids: list[str] = Field(min_length=1)
    scope: AnomalyScope
    label: AnomalyAnnotationLabel
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    reason: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    event_context: dict[str, Any] = Field(default_factory=dict)
    anomaly_type: AnomalyType | None = None
    anomaly_domain: AnomalyDomain | None = None
    observed_start_at: datetime | None = None
    observed_end_at: datetime | None = None
    split: AnomalySplit | None = None
    schema_version: Literal["anomaly-annotations-v1"] = (
        ANOMALY_ANNOTATION_SCHEMA_VERSION
    )

    @model_validator(mode="after")
    def validate_judgment(self) -> AnomalyAnnotation:
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("observation_ids must be unique")
        if (
            self.observed_start_at
            and self.observed_end_at
            and self.observed_start_at > self.observed_end_at
        ):
            raise ValueError("observed_start_at cannot follow observed_end_at")
        if self.label is AnomalyAnnotationLabel.ANOMALY:
            if self.anomaly_domain is None:
                raise ValueError(
                    "ANOMALY annotations require a resolved or UNCERTAIN domain"
                )
        elif self.label is AnomalyAnnotationLabel.NORMAL and (
            self.anomaly_type is not None or self.anomaly_domain is not None
        ):
            raise ValueError("NORMAL annotations cannot carry anomaly type/domain")
        return self


class AnomalyAnnotationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    annotation_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    label_counts: dict[str, int] = Field(default_factory=dict)
    domain_counts: dict[str, int] = Field(default_factory=dict)
    annotator_counts: dict[str, int] = Field(default_factory=dict)
    agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"]
    agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    repeated_target_count: int = Field(default=0, ge=0)
    disagreement_target_ids: list[str] = Field(default_factory=list)
    duplicate_annotation_ids: list[str] = Field(default_factory=list)
    repeated_annotator_targets: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TemporalObservationSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["TEMPORAL_SPLIT_AVAILABLE", "INSUFFICIENT_DATA"]
    train: list[WeatherObservation] = Field(default_factory=list)
    validation: list[WeatherObservation] = Field(default_factory=list)
    test: list[WeatherObservation] = Field(default_factory=list)
    train_end_at: datetime | None = None
    validation_end_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class TemporalLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    train_latest: datetime | None = None
    validation_earliest: datetime | None = None
    validation_latest: datetime | None = None
    test_earliest: datetime | None = None
    errors: list[str] = Field(default_factory=list)


class StationSplitLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    station_count: int = Field(ge=0)
    observations_per_station: dict[str, int] = Field(default_factory=dict)
    train_stations: list[str] = Field(default_factory=list)
    validation_stations: list[str] = Field(default_factory=list)
    test_stations: list[str] = Field(default_factory=list)
    train_validation_overlap: list[str] = Field(default_factory=list)
    train_test_overlap: list[str] = Field(default_factory=list)
    validation_test_overlap: list[str] = Field(default_factory=list)
    station_disjoint_required: bool
    errors: list[str] = Field(default_factory=list)


class AnomalyAnnotationStore:
    """Append-only JSONL storage; original human judgments are never replaced."""

    def __init__(self, path: Path) -> None:
        self.path = local_only_path(path, description="annotation paths")

    def load(self) -> list[AnomalyAnnotation]:
        if not self.path.exists():
            return []
        records: list[AnomalyAnnotation] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                records.append(AnomalyAnnotation.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"invalid anomaly annotation at line {line_number}: {error}"
                ) from error
        return records

    def append(self, annotation: AnomalyAnnotation) -> None:
        existing = self.load()
        if any(item.annotation_id == annotation.annotation_id for item in existing):
            raise ValueError(
                f"annotation_id already exists: {annotation.annotation_id}"
            )
        if any(
            item.target_id == annotation.target_id
            and item.annotator_id == annotation.annotator_id
            for item in existing
        ):
            raise ValueError("the same annotator has already annotated this target")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(annotation.model_dump_json() + "\n")


def validate_anomaly_annotations(
    annotations: Sequence[AnomalyAnnotation],
    *,
    available_observation_ids: set[str] | None = None,
) -> AnomalyAnnotationQualityReport:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_annotator_targets: set[tuple[str, str]] = set()
    duplicate_ids: set[str] = set()
    repeated_annotator_targets: set[str] = set()
    by_target: defaultdict[str, list[AnomalyAnnotation]] = defaultdict(list)
    label_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    annotator_counts: Counter[str] = Counter()
    for annotation in annotations:
        if annotation.annotation_id in seen_ids:
            duplicate_ids.add(annotation.annotation_id)
        seen_ids.add(annotation.annotation_id)
        key = (annotation.target_id, annotation.annotator_id)
        if key in seen_annotator_targets:
            repeated_annotator_targets.add("::".join(key))
        seen_annotator_targets.add(key)
        by_target[annotation.target_id].append(annotation)
        label_counts[annotation.label.value] += 1
        if annotation.anomaly_domain is not None:
            domain_counts[annotation.anomaly_domain.value] += 1
        annotator_counts[annotation.annotator_id] += 1
        if available_observation_ids is not None:
            missing = set(annotation.observation_ids) - available_observation_ids
            if missing:
                errors.append(
                    f"missing observations for {annotation.annotation_id}: {sorted(missing)}"
                )
    if duplicate_ids:
        errors.append("duplicate annotation IDs exist")
    if repeated_annotator_targets:
        errors.append("the same annotator annotated a target more than once")
    repeated = {
        target: items
        for target, items in by_target.items()
        if len({item.annotator_id for item in items}) >= 2
    }
    disagreements = sorted(
        target
        for target, items in repeated.items()
        if len({(item.label, item.anomaly_type, item.anomaly_domain) for item in items})
        > 1
    )
    if repeated:
        agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"] = (
            "DATA_AVAILABLE"
        )
        agreement_rate = (len(repeated) - len(disagreements)) / len(repeated)
    else:
        agreement_status = "DATA_UNAVAILABLE"
        agreement_rate = None
        warnings.append(
            "No target has independent repeated annotations; agreement was not calculated."
        )
    warnings.extend(
        f"unresolved disagreement remains UNCERTAIN: {target}"
        for target in disagreements
    )
    return AnomalyAnnotationQualityReport(
        valid=not errors,
        annotation_count=len(annotations),
        target_count=len(by_target),
        label_counts=dict(sorted(label_counts.items())),
        domain_counts=dict(sorted(domain_counts.items())),
        annotator_counts=dict(sorted(annotator_counts.items())),
        agreement_status=agreement_status,
        agreement_rate=agreement_rate,
        repeated_target_count=len(repeated),
        disagreement_target_ids=disagreements,
        duplicate_annotation_ids=sorted(duplicate_ids),
        repeated_annotator_targets=sorted(repeated_annotator_targets),
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )


def temporal_observation_split(
    observations: Sequence[WeatherObservation],
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
    minimum_observations: int = 6,
) -> TemporalObservationSplit:
    """Split ordered timestamps into earlier/middle/latest periods, never random."""

    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(value <= 0.0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("temporal split fractions must be positive and sum to one")
    if len(observations) < minimum_observations:
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=[
                f"Only {len(observations)} observations are available; at least {minimum_observations} are required."
            ],
        )
    if any(item.observed_at is None for item in observations):
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=["Temporal splitting requires every observation timestamp."],
        )
    station_counts = Counter(item.station_id for item in observations)
    insufficient_stations = {
        station_id: count
        for station_id, count in station_counts.items()
        if count < minimum_observations
    }
    if insufficient_stations:
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=[
                (
                    "Each station requires sufficient temporal coverage; "
                    f"insufficient counts={dict(sorted(insufficient_stations.items()))}."
                )
            ],
        )
    timestamps = [item.observed_at for item in observations]
    if any(right < left for left, right in pairwise(timestamps)):
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=["Input is not chronological; rows were not reordered."],
        )
    by_timestamp: defaultdict[datetime, list[WeatherObservation]] = defaultdict(list)
    for observation in observations:
        by_timestamp[observation.observed_at].append(observation)
    ordered_times = sorted(by_timestamp)
    if len(ordered_times) < 3:
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=["At least three distinct timestamps are required."],
        )
    count = len(ordered_times)
    train_end = max(1, round(count * train_fraction))
    validation_count = max(1, round(count * validation_fraction))
    if train_end + validation_count >= count:
        validation_count = max(1, count - train_end - 1)
    validation_end = train_end + validation_count
    if validation_end >= count:
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=["Temporal coverage cannot populate three ordered periods."],
        )
    train_times = ordered_times[:train_end]
    validation_times = ordered_times[train_end:validation_end]
    test_times = ordered_times[validation_end:]

    def records(times: Sequence[datetime]) -> list[WeatherObservation]:
        return [item for timestamp in times for item in by_timestamp[timestamp]]

    train_records = records(train_times)
    validation_records = records(validation_times)
    test_records = records(test_times)
    split_station_sets = (
        {item.station_id for item in train_records},
        {item.station_id for item in validation_records},
        {item.station_id for item in test_records},
    )
    stations_without_all_periods = sorted(
        station_id
        for station_id in station_counts
        if any(station_id not in station_set for station_set in split_station_sets)
    )
    if stations_without_all_periods:
        return TemporalObservationSplit(
            status="INSUFFICIENT_DATA",
            warnings=[
                "Stations lack observations in all three ordered periods: "
                + ", ".join(stations_without_all_periods)
            ],
        )
    return TemporalObservationSplit(
        status="TEMPORAL_SPLIT_AVAILABLE",
        train=train_records,
        validation=validation_records,
        test=test_records,
        train_end_at=train_times[-1],
        validation_end_at=validation_times[-1],
    )


def validate_temporal_leakage(
    train: Sequence[WeatherObservation],
    validation: Sequence[WeatherObservation],
    test: Sequence[WeatherObservation],
) -> TemporalLeakageReport:
    def times(items: Sequence[WeatherObservation]) -> list[datetime]:
        return [item.observed_at for item in items if item.observed_at is not None]

    train_times, validation_times, test_times = (
        times(train),
        times(validation),
        times(test),
    )
    errors: list[str] = []
    if not train_times or not validation_times or not test_times:
        errors.append("train, validation, and test periods must all contain timestamps")
    else:
        if max(train_times) >= min(validation_times):
            errors.append("training period overlaps or follows validation period")
        if max(validation_times) >= min(test_times):
            errors.append("validation period overlaps or follows test period")
    return TemporalLeakageReport(
        valid=not errors,
        train_latest=max(train_times) if train_times else None,
        validation_earliest=min(validation_times) if validation_times else None,
        validation_latest=max(validation_times) if validation_times else None,
        test_earliest=min(test_times) if test_times else None,
        errors=errors,
    )


def validate_station_group_leakage(
    train: Sequence[WeatherObservation],
    validation: Sequence[WeatherObservation],
    test: Sequence[WeatherObservation],
    *,
    require_disjoint_stations: bool,
) -> StationSplitLeakageReport:
    train_stations = {item.station_id for item in train}
    validation_stations = {item.station_id for item in validation}
    test_stations = {item.station_id for item in test}
    all_observations = [*train, *validation, *test]
    counts = Counter(item.station_id for item in all_observations)
    train_validation = sorted(train_stations & validation_stations)
    train_test = sorted(train_stations & test_stations)
    validation_test = sorted(validation_stations & test_stations)
    errors: list[str] = []
    if require_disjoint_stations and any(
        (train_validation, train_test, validation_test)
    ):
        errors.append("station-disjoint evaluation contains station overlap")
    return StationSplitLeakageReport(
        valid=not errors,
        station_count=len(counts),
        observations_per_station=dict(sorted(counts.items())),
        train_stations=sorted(train_stations),
        validation_stations=sorted(validation_stations),
        test_stations=sorted(test_stations),
        train_validation_overlap=train_validation,
        train_test_overlap=train_test,
        validation_test_overlap=validation_test,
        station_disjoint_required=require_disjoint_stations,
        errors=errors,
    )


__all__ = [
    "ANOMALY_ANNOTATION_SCHEMA_VERSION",
    "AnomalyAnnotation",
    "AnomalyAnnotationLabel",
    "AnomalyAnnotationQualityReport",
    "AnomalyAnnotationStore",
    "StationSplitLeakageReport",
    "TemporalLeakageReport",
    "TemporalObservationSplit",
    "temporal_observation_split",
    "validate_anomaly_annotations",
    "validate_station_group_leakage",
    "validate_temporal_leakage",
]
