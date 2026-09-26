"""Deterministic project-authored temporal-window generator for Phase 23.

The detector-facing records contain only approved station observations:
timestamps, rainfall, and optional river level.  Scenario identity, grouping
families, and ground truth are written to a physically separate stream.
Labels are derived from the explicit scenario specification below and never
from either the statistical baseline or a learned detector.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.contracts import AnomalyDomain, AnomalyScope, AnomalyType
from app.ml.data.anomaly_annotations import AnomalyAnnotation, AnomalyAnnotationLabel
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    AnomalyDataRole,
    DatasetClassification,
    DatasetComponent,
    DatasetFormat,
    DatasetProvenance,
    DatasetRegistryRecord,
    DatasetStatus,
    hash_dataset_path,
    register_dataset,
)
from app.ml.data.dataset_validation import validate_registered_dataset


GENERATOR_VERSION = "synthetic-anomaly-generator-v1"
DATASET_ID = "indra-synthetic-anomaly-v1"
DATASET_VERSION = "1.0.0"
SCHEMA_VERSION = "synthetic-anomaly-window-dataset-v1"
LABEL_SCHEMA_VERSION = "anomaly-annotations-v1"
DEFAULT_SEED = 230023
WINDOW_LENGTH = 24
SPLITS = ("train", "validation", "test")
SPLIT_BASES = {
    "train": datetime(2010, 1, 1, tzinfo=timezone.utc),
    "validation": datetime(2030, 1, 1, tzinfo=timezone.utc),
    "test": datetime(2040, 1, 1, tzinfo=timezone.utc),
}

SCENARIO_FAMILIES = (
    "NORMAL_BASELINE",
    "LEGITIMATE_EXTREME_RAINFALL",
    "RAINFALL_VALUE_OUTLIER",
    "RAINFALL_RATE_CHANGE",
    "PERSISTENT_RAINFALL_DEVIATION",
    "LEGITIMATE_RIVER_LEVEL_EXTREME",
    "RIVER_LEVEL_CHANGE_ANOMALY",
    "SENSOR_STUCK",
    "SENSOR_DISCONTINUITY",
    "MISSINGNESS_BURST",
    "TIMESTAMP_IRREGULARITY",
    "COMBINED_DATA_QUALITY_FAILURE",
    "ABRUPT_LEGITIMATE_WEATHER_TRANSITION",
    "ISOLATED_LARGE_LEGITIMATE_MEASUREMENT",
    "NORMAL_HEAVY_RAIN_SEQUENCE",
    "BENIGN_MISSING_DATA",
)

WEATHER_SCENARIOS = frozenset(
    {
        "RAINFALL_VALUE_OUTLIER",
        "RAINFALL_RATE_CHANGE",
        "PERSISTENT_RAINFALL_DEVIATION",
        "RIVER_LEVEL_CHANGE_ANOMALY",
    }
)
DATA_QUALITY_SCENARIOS = frozenset(
    {
        "SENSOR_STUCK",
        "SENSOR_DISCONTINUITY",
        "MISSINGNESS_BURST",
        "TIMESTAMP_IRREGULARITY",
        "COMBINED_DATA_QUALITY_FAILURE",
    }
)

HARD_NEGATIVE_BY_SCENARIO: dict[str, tuple[str, ...]] = {
    "LEGITIMATE_EXTREME_RAINFALL": ("LEGITIMATE_EXTREME_RAINFALL",),
    "LEGITIMATE_RIVER_LEVEL_EXTREME": ("LEGITIMATE_EXTREME_RIVER_LEVEL",),
    "ABRUPT_LEGITIMATE_WEATHER_TRANSITION": (
        "ABRUPT_BUT_LEGITIMATE_WEATHER_TRANSITION",
    ),
    "ISOLATED_LARGE_LEGITIMATE_MEASUREMENT": (
        "ISOLATED_LARGE_BUT_LEGITIMATE_MEASUREMENT",
    ),
    "NORMAL_HEAVY_RAIN_SEQUENCE": ("NORMAL_HEAVY_RAIN_SEQUENCE",),
    "BENIGN_MISSING_DATA": ("MISSING_DATA_WITHOUT_BEHAVIORAL_ANOMALY",),
}


class SyntheticAnomalyGeneratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = DEFAULT_SEED
    train_count: int = Field(default=70_000, gt=0)
    validation_count: int = Field(default=15_000, gt=0)
    test_count: int = Field(default=15_000, gt=0)
    window_length: Literal[24] = WINDOW_LENGTH
    station_count_per_split: int = Field(default=32, ge=8)
    station_family_count_per_split: int = Field(default=8, ge=4)
    temporal_family_count_per_split: int = Field(default=8, ge=4)
    parameter_family_count_per_split: int = Field(default=8, ge=4)

    @property
    def split_counts(self) -> dict[str, int]:
        return {
            "train": self.train_count,
            "validation": self.validation_count,
            "test": self.test_count,
        }

    @property
    def dataset_size(self) -> int:
        return sum(self.split_counts.values())


class SyntheticAnomalyModelRecord(BaseModel):
    """The complete detector-visible input; hidden labels are forbidden here."""

    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    timestamps: list[datetime] = Field(min_length=WINDOW_LENGTH, max_length=WINDOW_LENGTH)
    rainfall_mm: list[float | None] = Field(
        min_length=WINDOW_LENGTH,
        max_length=WINDOW_LENGTH,
    )
    river_level_m: list[float | None] = Field(
        min_length=WINDOW_LENGTH,
        max_length=WINDOW_LENGTH,
    )
    split: Literal["train", "validation", "test"]
    window_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observations(self) -> "SyntheticAnomalyModelRecord":
        if any(right <= left for left, right in zip(self.timestamps, self.timestamps[1:])):
            raise ValueError("timestamps must be strictly increasing")
        values = [*self.rainfall_mm, *self.river_level_m]
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("present measurements must be finite")
        return self


class SyntheticAnomalyMetadata(BaseModel):
    """Generator-only truth.  This object is never accepted by feature code."""

    model_config = ConfigDict(extra="forbid")

    window_id: str
    scenario_id: str
    scenario_family: str
    station_family: str
    temporal_pattern_family: str
    anomaly_parameter_family: str
    parameter_combination_id: str
    trajectory_family: str
    trajectory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_quality_anomaly: bool
    weather_behavior_anomaly: bool
    overall_anomaly: bool
    anomaly_type: str | None
    anomaly_domain: str | None
    hard_negative_categories: list[str] = Field(default_factory=list)
    label_derivation: Literal["EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY"] = (
        "EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY"
    )
    generator_seed: int
    generator_version: Literal["synthetic-anomaly-generator-v1"] = GENERATOR_VERSION
    split: Literal["train", "validation", "test"]
    generation_parameters: dict[str, float | int | bool | str]

    @model_validator(mode="after")
    def validate_domains(self) -> "SyntheticAnomalyMetadata":
        if self.overall_anomaly != (
            self.data_quality_anomaly or self.weather_behavior_anomaly
        ):
            raise ValueError("overall anomaly must be the union of the two domains")
        if self.data_quality_anomaly and self.weather_behavior_anomaly:
            raise ValueError("Phase 23 scenarios keep anomaly domains distinguishable")
        if self.overall_anomaly and not self.anomaly_domain:
            raise ValueError("anomalies require a domain")
        if not self.overall_anomaly and (
            self.anomaly_type is not None or self.anomaly_domain is not None
        ):
            raise ValueError("normal scenarios cannot carry anomaly type/domain")
        return self


class SyntheticAnomalyDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    output_directory: Path
    manifest_path: Path
    quality_report_path: Path
    annotations_path: Path
    model_input_paths: dict[str, Path]
    hidden_metadata_paths: dict[str, Path]
    dataset_sha256: str
    split_sha256: dict[str, str]
    split_counts: dict[str, int]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_sha256() -> str:
    return _file_sha256(Path(__file__).resolve())


def _round_values(values: np.ndarray) -> list[float]:
    return [round(float(value), 6) for value in values]


def _longest_identical_run(values: list[float | None]) -> int:
    best = current = 0
    previous: float | None | object = object()
    for value in values:
        if value is not None and value == previous:
            current += 1
        elif value is not None:
            current = 1
        else:
            current = 0
        best = max(best, current)
        previous = value
    return best


def _scenario_truth(scenario: str) -> tuple[bool, bool, str | None, str | None]:
    if scenario in WEATHER_SCENARIOS:
        anomaly_type = {
            "RAINFALL_VALUE_OUTLIER": AnomalyType.VALUE_OUTLIER.value,
            "RAINFALL_RATE_CHANGE": AnomalyType.RATE_OF_CHANGE.value,
            "PERSISTENT_RAINFALL_DEVIATION": AnomalyType.PERSISTENT_DEVIATION.value,
            "RIVER_LEVEL_CHANGE_ANOMALY": AnomalyType.RATE_OF_CHANGE.value,
        }[scenario]
        return False, True, anomaly_type, AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY.value
    if scenario in DATA_QUALITY_SCENARIOS:
        anomaly_type = {
            "SENSOR_STUCK": AnomalyType.PERSISTENT_DEVIATION.value,
            "SENSOR_DISCONTINUITY": AnomalyType.RATE_OF_CHANGE.value,
            "MISSINGNESS_BURST": AnomalyType.MISSINGNESS_PATTERN.value,
            "TIMESTAMP_IRREGULARITY": AnomalyType.RATE_OF_CHANGE.value,
            "COMBINED_DATA_QUALITY_FAILURE": AnomalyType.VALUE_OUTLIER.value,
        }[scenario]
        return True, False, anomaly_type, AnomalyDomain.DATA_QUALITY_ANOMALY.value
    return False, False, None, None


def _window_payload(
    split: str,
    index: int,
    config: SyntheticAnomalyGeneratorConfig,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scenario_index = index % len(SCENARIO_FAMILIES)
    scenario = SCENARIO_FAMILIES[scenario_index]
    split_code = {"train": 11, "validation": 23, "test": 37}[split]
    split_variant = {"train": 0, "validation": 1, "test": 2}[split]
    row_seed = config.seed * 1_000_003 + split_code * 10_000_019 + index * 97
    rng = np.random.default_rng(row_seed)
    scenario_block = index // len(SCENARIO_FAMILIES)
    station_number = (
        index * 7 + scenario_block * 13 + split_code
    ) % config.station_count_per_split
    station_family_number = station_number % config.station_family_count_per_split
    temporal_number = (index // len(SCENARIO_FAMILIES)) % config.temporal_family_count_per_split
    parameter_number = (
        index // (len(SCENARIO_FAMILIES) * config.temporal_family_count_per_split)
    ) % config.parameter_family_count_per_split
    station_id = _sha256_bytes(
        f"station:{split}:{station_number}:{config.seed}".encode("utf-8")
    )[:16]
    station_id = f"station-{station_id}"
    station_family = f"{split}-station-family-{station_family_number:02d}"
    temporal_family = f"{split}-temporal-family-{temporal_number:02d}"
    parameter_family = f"{split}-parameter-family-{parameter_number:02d}"
    parameter_combination = (
        f"{split}-combination-{scenario_index:02d}-{station_family_number:02d}-"
        f"{temporal_number:02d}-{parameter_number:02d}"
    )
    trajectory_family = (
        f"{split}-trajectory-{scenario_index:02d}-{station_family_number:02d}-"
        f"{temporal_number:02d}"
    )

    x = np.arange(config.window_length, dtype=np.float64)
    phase = (station_number % 12) / 12.0 * 2.0 * np.pi + split_variant * 0.17
    temporal_period = {"train": 24.0, "validation": 26.0, "test": 22.0}[split]
    rain_center = 4.0 + (station_family_number % 5) * 1.8 + split_variant * 0.45
    rain = (
        rain_center
        + 2.2 * np.sin((x / temporal_period) * 2.0 * np.pi + phase)
        + rng.normal(
            0.0,
            0.7 + parameter_number * 0.025 + split_variant * 0.04,
            config.window_length,
        )
    )
    rain = np.maximum(rain, 0.0)
    river_available = station_number % 4 != 0
    river_center = 0.8 + (station_family_number % 4) * 0.28 + split_variant * 0.06
    river = (
        river_center
        + 0.08 * np.sin((x / temporal_period) * 2.0 * np.pi + phase / 2.0)
        + np.cumsum(rng.normal(0.0, 0.009, config.window_length))
    )
    river = np.maximum(river, 0.05)
    cadence_families = {
        "train": (45, 50, 60, 65, 75, 80, 90, 105),
        "validation": (48, 52, 58, 68, 72, 82, 88, 100),
        "test": (42, 47, 55, 62, 70, 85, 95, 110),
    }
    nominal_interval_minutes = cadence_families[split][temporal_number]
    intervals_minutes = np.full(
        config.window_length - 1,
        nominal_interval_minutes,
        dtype=np.int64,
    )
    rainfall_values: list[float | None]
    river_values: list[float | None]

    if scenario == "LEGITIMATE_EXTREME_RAINFALL":
        rain = 72.0 + 11.0 * np.sin(x / 4.0 + phase) + rng.normal(0.0, 2.2, 24)
        rain = np.maximum(rain, 35.0)
        river = 3.2 + 0.025 * x + rng.normal(0.0, 0.025, 24)
        river_available = True
    elif scenario == "RAINFALL_VALUE_OUTLIER":
        rain[-1] = float(
            np.median(rain[:-4])
            + 62.0
            + parameter_number * 2.0
            + split_variant * 3.0
        )
    elif scenario == "RAINFALL_RATE_CHANGE":
        rain[-2] = max(0.0, rain[-3] + 3.0)
        rain[-1] = rain[-2] + 38.0 + parameter_number + split_variant * 2.0
    elif scenario == "PERSISTENT_RAINFALL_DEVIATION":
        rain[-6:] += 27.0 + parameter_number * 0.8 + split_variant * 1.5
    elif scenario == "LEGITIMATE_RIVER_LEVEL_EXTREME":
        river_available = True
        river = 8.5 + 0.018 * x + 0.11 * np.sin(x / 3.5 + phase)
        rain = 18.0 + 2.5 * np.sin(x / 4.0 + phase) + rng.normal(0.0, 0.8, 24)
    elif scenario == "RIVER_LEVEL_CHANGE_ANOMALY":
        river_available = True
        river[-2] += 0.35
        river[-1] = river[-2] + 3.1 + parameter_number * 0.08 + split_variant * 0.18
    elif scenario == "SENSOR_STUCK":
        rain[-9:] = rain[-9]
        if river_available:
            river[-9:] = river[-9]
    elif scenario == "SENSOR_DISCONTINUITY":
        rain[-4] = rain[-5] + 74.0 + parameter_number
        rain[-3] = max(0.0, rain[-5] - 1.0)
        rain[-2] = rain[-5] + 0.4
        rain[-1] = rain[-5] - 0.2
    elif scenario == "TIMESTAMP_IRREGULARITY":
        intervals_minutes[10] = 15
        intervals_minutes[11] = 285
    elif scenario == "COMBINED_DATA_QUALITY_FAILURE":
        intervals_minutes[8] = 300
        rain[-1] = -5.0 - parameter_number
        if river_available:
            river[-7:] = river[-7]
    elif scenario == "ABRUPT_LEGITIMATE_WEATHER_TRANSITION":
        river_available = True
        ramp = np.linspace(0.0, 31.0 + parameter_number, 8)
        rain[-8:] += ramp
        river[-8:] += ramp * 0.045
    elif scenario == "ISOLATED_LARGE_LEGITIMATE_MEASUREMENT":
        spike = 38.0 + parameter_number
        for position in (4, 10, 16, 23):
            rain[position] += spike + rng.normal(0.0, 1.0)
    elif scenario == "NORMAL_HEAVY_RAIN_SEQUENCE":
        rain = 38.0 + 5.5 * np.sin(x / 4.2 + phase) + rng.normal(0.0, 1.2, 24)
        rain = np.maximum(rain, 20.0)
        river_available = True
        river = 2.2 + 0.018 * x + rng.normal(0.0, 0.018, 24)

    rainfall_values = _round_values(rain)
    river_values = _round_values(river) if river_available else [None] * 24
    if scenario == "MISSINGNESS_BURST":
        for position in range(19, 24):
            rainfall_values[position] = None
            river_values[position] = None
    elif scenario == "BENIGN_MISSING_DATA":
        for position in (5, 14):
            rainfall_values[position] = None
            river_values[position] = None

    start = SPLIT_BASES[split] + timedelta(
        days=index // 24,
        hours=int(rng.integers(0, 24)),
        minutes=15 * int(rng.integers(0, 4)),
    )
    timestamps = [start]
    for interval in intervals_minutes:
        timestamps.append(timestamps[-1] + timedelta(minutes=int(interval)))
    timestamp_values = [value.isoformat().replace("+00:00", "Z") for value in timestamps]
    id_digest = _sha256_bytes(
        f"{split}:{index}:{config.seed}:{scenario}".encode("utf-8")
    )[:14]
    window_id = f"synanomaly-{split}-{index:06d}-{id_digest}"
    visible = {
        "window_id": window_id,
        "station_id": station_id,
        "timestamps": timestamp_values,
        "rainfall_mm": rainfall_values,
        "river_level_m": river_values,
        "split": split,
    }
    visible["window_sha256"] = _sha256_bytes(_canonical_json(visible))
    trajectory_payload = {
        "intervals_minutes": intervals_minutes.tolist(),
        "rainfall_mm": rainfall_values,
        "river_level_m": river_values,
    }
    trajectory_hash = _sha256_bytes(_canonical_json(trajectory_payload))
    data_quality, weather, anomaly_type, anomaly_domain = _scenario_truth(scenario)
    hard_negatives = list(HARD_NEGATIVE_BY_SCENARIO.get(scenario, ()))
    if weather:
        hard_negatives.append("BEHAVIORAL_ANOMALY_WITHOUT_DATA_QUALITY_FAILURE")
    if data_quality:
        hard_negatives.append("DATA_QUALITY_FAILURE_WITHOUT_WEATHER_ANOMALY")
    metadata = {
        "window_id": window_id,
        "scenario_id": f"scenario-{scenario_index:02d}-{id_digest}",
        "scenario_family": scenario,
        "station_family": station_family,
        "temporal_pattern_family": temporal_family,
        "anomaly_parameter_family": parameter_family,
        "parameter_combination_id": parameter_combination,
        "trajectory_family": trajectory_family,
        "trajectory_sha256": trajectory_hash,
        "data_quality_anomaly": data_quality,
        "weather_behavior_anomaly": weather,
        "overall_anomaly": data_quality or weather,
        "anomaly_type": anomaly_type,
        "anomaly_domain": anomaly_domain,
        "hard_negative_categories": hard_negatives,
        "label_derivation": "EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY",
        "generator_seed": row_seed,
        "generator_version": GENERATOR_VERSION,
        "split": split,
        "generation_parameters": {
            "rain_center": round(rain_center, 6),
            "river_center": round(river_center, 6),
            "river_available": river_available,
            "phase": round(phase, 6),
            "station_profile": station_family_number,
            "temporal_profile": temporal_number,
            "parameter_profile": parameter_number,
            "split_holdout_variant": split_variant,
            "temporal_period_hours": temporal_period,
            "nominal_interval_minutes": nominal_interval_minutes,
            "stuck_run_rainfall": _longest_identical_run(rainfall_values),
        },
    }
    annotation = AnomalyAnnotation(
        annotation_id=f"annotation-{window_id}",
        target_id=window_id,
        station_id=station_id,
        observation_ids=[f"{window_id}-observation-023"],
        scope=AnomalyScope.WINDOW_ANOMALY,
        label=(
            AnomalyAnnotationLabel.ANOMALY
            if data_quality or weather
            else AnomalyAnnotationLabel.NORMAL
        ),
        annotator_id=GENERATOR_VERSION,
        annotation_timestamp=datetime(2050, 1, 1, tzinfo=timezone.utc),
        reason="Ground truth is defined by the explicit project-authored scenario.",
        evidence=["EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY"],
        anomaly_type=AnomalyType(anomaly_type) if anomaly_type else None,
        anomaly_domain=AnomalyDomain(anomaly_domain) if anomaly_domain else None,
        observed_start_at=timestamps[0],
        observed_end_at=timestamps[-1],
        split=split,
    ).model_dump(mode="json")
    return visible, metadata, annotation


def build_synthetic_window(
    split: Literal["train", "validation", "test"],
    index: int,
    config: SyntheticAnomalyGeneratorConfig | None = None,
) -> tuple[SyntheticAnomalyModelRecord, SyntheticAnomalyMetadata, AnomalyAnnotation]:
    """Build and validate one record; useful for deterministic tests/replay."""

    selected = config or SyntheticAnomalyGeneratorConfig()
    visible, metadata, annotation = _window_payload(split, index, selected)
    return (
        SyntheticAnomalyModelRecord.model_validate(visible),
        SyntheticAnomalyMetadata.model_validate(metadata),
        AnomalyAnnotation.model_validate(annotation),
    )


def _json_line(value: dict[str, Any]) -> str:
    return _canonical_json(value).decode("utf-8") + "\n"


def _relative_to_registry(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path.resolve(), registry_path.resolve().parent)).as_posix()


def _register_generated_dataset(
    output_directory: Path,
    manifest: dict[str, Any],
    quality: dict[str, Any],
    *,
    registry_path: Path,
) -> None:
    annotations_path = output_directory / "annotations.jsonl"
    content_hash = hash_dataset_path(annotations_path).content_sha256
    record = DatasetRegistryRecord(
        dataset_id=DATASET_ID,
        dataset_version=DATASET_VERSION,
        component=DatasetComponent.ANOMALY,
        local_path=_relative_to_registry(annotations_path, registry_path),
        format=DatasetFormat.JSONL,
        content_sha256=content_hash,
        schema_version=SCHEMA_VERSION,
        label_schema_version=LABEL_SCHEMA_VERSION,
        creation_timestamp=datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc),
        source_description=(
            "Reproducible project-authored rainfall and optional river-level "
            "temporal windows with scenario-derived hidden ground truth."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development validation only; not field or "
            "production-performance evidence."
        ),
        grouping_field="station_id",
        time_field="observed_start_at",
        split_field="split",
        label_count=manifest["label_distribution"]["OVERALL_ANOMALY"],
        row_or_image_count=manifest["window_count"],
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_AUTHORED_SYNTHETIC_SCENARIO_IDENTITY",
        anomaly_data_role=AnomalyDataRole.SUPERVISED_EVALUATION,
        metadata={
            "synthetic": True,
            "project_authored": True,
            "production_validation": "NOT_VALIDATED",
            "dataset_hash": manifest["dataset_sha256"],
            "split_hashes": manifest["split_sha256"],
            "generator_version": GENERATOR_VERSION,
            "seed": manifest["seed"],
            "manifest_path": _relative_to_registry(
                output_directory / "manifest.json", registry_path
            ),
            "manifest_sha256": _file_sha256(output_directory / "manifest.json"),
            "quality_report_path": _relative_to_registry(
                output_directory / "quality_report.json", registry_path
            ),
            "quality_report_sha256": _file_sha256(
                output_directory / "quality_report.json"
            ),
            "hidden_metadata_isolated": quality["hidden_metadata_isolation"][
                "physically_separate"
            ],
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
        },
    )
    register_dataset(
        record,
        registry_path=registry_path,
        replace_existing=True,
        modified_at=datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc),
    )
    report = validate_registered_dataset(
        DATASET_ID,
        dataset_version=DATASET_VERSION,
        registry_path=registry_path,
        generated_at=datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc),
    )
    if not report.valid or report.leakage.overall_status != "PASS":
        raise RuntimeError(
            "generated anomaly dataset failed common registry validation: "
            + "; ".join(report.errors)
        )


def generate_synthetic_anomaly_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticAnomalyGeneratorConfig | None = None,
    registry_path: Path | str | None = None,
    register: bool = True,
) -> SyntheticAnomalyDataset:
    """Generate an immutable deterministic dataset and all quality evidence."""

    selected = config or SyntheticAnomalyGeneratorConfig()
    output = Path(output_directory).resolve()
    if output.exists():
        raise FileExistsError(f"synthetic anomaly dataset already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    )
    model_dir = staging / "model_inputs"
    hidden_dir = staging / "hidden_generator_metadata"
    model_dir.mkdir()
    hidden_dir.mkdir()

    split_counts: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    split_labels: defaultdict[str, Counter[str]] = defaultdict(Counter)
    scenarios: Counter[str] = Counter()
    hard_negatives: Counter[str] = Counter()
    visible_hashes: set[str] = set()
    trajectory_hashes: defaultdict[str, set[str]] = defaultdict(set)
    station_families: defaultdict[str, set[str]] = defaultdict(set)
    temporal_families: defaultdict[str, set[str]] = defaultdict(set)
    parameter_families: defaultdict[str, set[str]] = defaultdict(set)
    parameter_combinations: defaultdict[str, set[str]] = defaultdict(set)
    model_input_paths: dict[str, Path] = {}
    hidden_paths: dict[str, Path] = {}
    replay_checks: list[dict[str, Any]] = []
    annotations_path = staging / "annotations.jsonl"
    try:
        with annotations_path.open("x", encoding="utf-8", newline="\n") as annotation_file:
            for split in SPLITS:
                model_path = model_dir / f"{split}.jsonl"
                hidden_path = hidden_dir / f"{split}.jsonl"
                model_input_paths[split] = model_path
                hidden_paths[split] = hidden_path
                with (
                    model_path.open("x", encoding="utf-8", newline="\n") as model_file,
                    hidden_path.open("x", encoding="utf-8", newline="\n") as hidden_file,
                ):
                    for index in range(selected.split_counts[split]):
                        visible, metadata, annotation = _window_payload(
                            split,
                            index,
                            selected,
                        )
                        SyntheticAnomalyModelRecord.model_validate(visible)
                        truth = SyntheticAnomalyMetadata.model_validate(metadata)
                        model_file.write(_json_line(visible))
                        hidden_file.write(_json_line(metadata))
                        annotation_file.write(_json_line(annotation))
                        split_counts[split] += 1
                        scenarios[truth.scenario_family] += 1
                        for name, enabled in (
                            ("DATA_QUALITY_ANOMALY", truth.data_quality_anomaly),
                            ("WEATHER_BEHAVIOR_ANOMALY", truth.weather_behavior_anomaly),
                            ("OVERALL_ANOMALY", truth.overall_anomaly),
                            ("NORMAL", not truth.overall_anomaly),
                        ):
                            if enabled:
                                labels[name] += 1
                                split_labels[split][name] += 1
                        hard_negatives.update(truth.hard_negative_categories)
                        if visible["window_sha256"] in visible_hashes:
                            raise RuntimeError("duplicate synthetic window hash generated")
                        visible_hashes.add(visible["window_sha256"])
                        trajectory_hashes[split].add(truth.trajectory_sha256)
                        station_families[split].add(truth.station_family)
                        temporal_families[split].add(truth.temporal_pattern_family)
                        parameter_families[split].add(truth.anomaly_parameter_family)
                        parameter_combinations[split].add(
                            truth.parameter_combination_id
                        )
                        if index in {0, len(SCENARIO_FAMILIES) - 1}:
                            replay_visible, replay_metadata, _ = _window_payload(
                                split,
                                index,
                                selected,
                            )
                            replay_checks.append(
                                {
                                    "split": split,
                                    "index": index,
                                    "visible_equal": replay_visible == visible,
                                    "metadata_equal": replay_metadata == metadata,
                                }
                            )

        split_hashes = {split: _file_sha256(path) for split, path in model_input_paths.items()}
        hidden_hashes = {split: _file_sha256(path) for split, path in hidden_paths.items()}
        annotation_hash = _file_sha256(annotations_path)

        def cross_overlap(groups: dict[str, set[str]]) -> int:
            return sum(
                len(groups[left] & groups[right])
                for left, right in (
                    ("train", "validation"),
                    ("train", "test"),
                    ("validation", "test"),
                )
            )

        leakage = {
            "window_hash_cross_split": 0,
            "trajectory_hash_cross_split": cross_overlap(trajectory_hashes),
            "station_family_cross_split": cross_overlap(station_families),
            "temporal_pattern_family_cross_split": cross_overlap(temporal_families),
            "parameter_family_cross_split": cross_overlap(parameter_families),
            "parameter_combination_cross_split": cross_overlap(
                parameter_combinations
            ),
            "naive_row_random_split": False,
            "grouped_split": True,
        }
        leakage["status"] = (
            "PASS"
            if not any(
                value
                for key, value in leakage.items()
                if key.endswith("_cross_split")
            )
            else "FAIL"
        )
        model_fields = list(SyntheticAnomalyModelRecord.model_fields)
        hidden_fields = sorted(
            set(SyntheticAnomalyMetadata.model_fields) - set(model_fields)
        )
        quality = {
            "schema_version": "1.0",
            "valid": (
                dict(split_counts) == selected.split_counts
                and len(visible_hashes) == selected.dataset_size
                and leakage["status"] == "PASS"
                and all(
                    item["visible_equal"] and item["metadata_equal"]
                    for item in replay_checks
                )
            ),
            "errors": [],
            "warnings": [],
            "window_count": selected.dataset_size,
            "split_counts": dict(split_counts),
            "label_distribution": dict(sorted(labels.items())),
            "split_label_distribution": {
                split: dict(sorted(counts.items()))
                for split, counts in sorted(split_labels.items())
            },
            "scenario_distribution": dict(sorted(scenarios.items())),
            "hard_negative_distribution": dict(sorted(hard_negatives.items())),
            "window_integrity": {
                "unique_window_hashes": len(visible_hashes),
                "present_values_finite": True,
                "missingness_encoding": "JSON_NULL",
                "timestamps_timezone_aware_and_strictly_increasing": True,
            },
            "hidden_metadata_isolation": {
                "physically_separate": True,
                "detector_receives_hidden_metadata": False,
                "model_record_fields": model_fields,
                "hidden_fields_not_in_model_record": hidden_fields,
                "label_derived_from_detector_output": False,
                "label_derivation": "EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY",
            },
            "leakage_checks": leakage,
            "deterministic_replay": {
                "status": "PASS",
                "checks": replay_checks,
            },
            "generator_version": GENERATOR_VERSION,
            "production_validation": "NOT_VALIDATED",
        }
        if not quality["valid"]:
            quality["errors"].append("one or more synthetic dataset gates failed")
            raise RuntimeError("synthetic anomaly dataset quality gates failed")
        quality_path = staging / "quality_report.json"
        quality_path.write_bytes(_canonical_json(quality) + b"\n")
        dataset_payload = {
            "dataset_id": DATASET_ID,
            "dataset_version": DATASET_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "generator_source_sha256": _source_sha256(),
            "seed": selected.seed,
            "split_counts": selected.split_counts,
            "split_sha256": split_hashes,
            "hidden_metadata_sha256": hidden_hashes,
            "annotation_sha256": annotation_hash,
        }
        dataset_hash = _sha256_bytes(_canonical_json(dataset_payload))
        manifest = {
            **dataset_payload,
            "dataset_sha256": dataset_hash,
            "window_count": selected.dataset_size,
            "window_length": selected.window_length,
            "supported_measurements": ["rainfall_mm", "river_level_m"],
            "label_distribution": dict(sorted(labels.items())),
            "split_label_distribution": {
                split: dict(sorted(counts.items()))
                for split, counts in sorted(split_labels.items())
            },
            "scenario_families": list(SCENARIO_FAMILIES),
            "task": "DUAL_DOMAIN_ANOMALY_DETECTION",
            "data_origin": "PROJECT_AUTHORED_SYNTHETIC",
            "classification": "DEVELOPMENT_ONLY",
            "split_strategy": (
                "STATION_TEMPORAL_PATTERN_PARAMETER_FAMILY_GROUPED"
            ),
            "ground_truth_source": "EXPLICIT_SYNTHETIC_SCENARIO_IDENTITY",
            "policy": {
                "project_authored": True,
                "synthetic": True,
                "development_only": True,
                "production_validation": "NOT_VALIDATED",
                "detector_receives_hidden_metadata": False,
                "pretrained_models": [],
                "open_weight_models": [],
                "external_apis": [],
                "network_access": False,
                "live_backend_modified": False,
            },
            "quality_report_sha256": _file_sha256(quality_path),
            "creation_timestamp": "2026-09-24T09:00:00Z",
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
        os.replace(staging, output)
        staging = output
        if register:
            _register_generated_dataset(
                output,
                manifest,
                quality,
                registry_path=Path(
                    registry_path or DEFAULT_DATASET_REGISTRY_PATH
                ).resolve(),
            )
        return SyntheticAnomalyDataset(
            output_directory=output,
            manifest_path=output / "manifest.json",
            quality_report_path=output / "quality_report.json",
            annotations_path=output / "annotations.jsonl",
            model_input_paths={
                split: output / "model_inputs" / f"{split}.jsonl"
                for split in SPLITS
            },
            hidden_metadata_paths={
                split: output / "hidden_generator_metadata" / f"{split}.jsonl"
                for split in SPLITS
            },
            dataset_sha256=dataset_hash,
            split_sha256=split_hashes,
            split_counts=dict(split_counts),
        )
    except Exception:
        if staging.exists() and staging != output:
            shutil.rmtree(staging)
        raise


def load_model_records(path: Path | str) -> list[SyntheticAnomalyModelRecord]:
    return [
        SyntheticAnomalyModelRecord.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_hidden_metadata(path: Path | str) -> list[SyntheticAnomalyMetadata]:
    return [
        SyntheticAnomalyMetadata.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


__all__ = [
    "DATASET_ID",
    "DATASET_VERSION",
    "GENERATOR_VERSION",
    "HARD_NEGATIVE_BY_SCENARIO",
    "SCENARIO_FAMILIES",
    "SyntheticAnomalyDataset",
    "SyntheticAnomalyGeneratorConfig",
    "SyntheticAnomalyMetadata",
    "SyntheticAnomalyModelRecord",
    "build_synthetic_window",
    "generate_synthetic_anomaly_dataset",
    "load_hidden_metadata",
    "load_model_records",
]
