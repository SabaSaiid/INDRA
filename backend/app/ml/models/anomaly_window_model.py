"""Scratch-trained dual-domain anomaly model for synthetic development only.

This module is deliberately disconnected from the live ``AnomalyDetector``.
Features are computed exclusively from the detector-visible temporal window;
no synthetic scenario identity, split family, or label is accepted here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.ml.data.synthetic_anomaly.generator import (
    GENERATOR_VERSION,
    SyntheticAnomalyMetadata,
    SyntheticAnomalyModelRecord,
)


FEATURE_VERSION = "anomaly-window-features-v1-synthetic-development"
PREPROCESSING_VERSION = "anomaly-window-preprocessing-v1"
MODEL_VERSION = "anomaly-model-v1-synthetic-development"
MODEL_FAMILY = "LOCAL_SCRATCH_DUAL_LOGISTIC"
DOMAIN_LABELS = ("DATA_QUALITY_ANOMALY", "WEATHER_BEHAVIOR_ANOMALY")

MEASUREMENT_FEATURES = (
    "availability_ratio",
    "missing_ratio",
    "last_value",
    "mean",
    "median",
    "standard_deviation",
    "mad",
    "lower_quantile",
    "upper_quantile",
    "robust_scale",
    "minimum",
    "maximum",
    "range",
    "latest_robust_z",
    "maximum_robust_z",
    "latest_delta",
    "maximum_absolute_delta",
    "latest_rate_per_hour",
    "maximum_absolute_rate_per_hour",
    "tail_mean_robust_z",
    "tail_outlier_ratio",
    "longest_identical_run_ratio",
    "jump_reversal_score",
    "linear_slope",
    "negative_value_ratio",
)
GLOBAL_FEATURES = (
    "interval_median_hours",
    "interval_scale_ratio",
    "irregular_interval_ratio",
    "minimum_interval_ratio",
    "maximum_interval_ratio",
    "observation_density_per_hour",
    "all_measurements_missing_ratio",
    "maximum_missing_run_ratio",
    "rain_river_value_correlation",
    "rain_river_delta_correlation",
    "start_hour_sine",
    "start_hour_cosine",
)
FEATURE_NAMES = tuple(
    [f"rainfall_{name}" for name in MEASUREMENT_FEATURES]
    + [f"river_level_{name}" for name in MEASUREMENT_FEATURES]
    + list(GLOBAL_FEATURES)
)


class LogisticHead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["DATA_QUALITY_ANOMALY", "WEATHER_BEHAVIOR_ANOMALY"]
    coefficients: list[float]
    intercept: float


class ScratchDualLogisticArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    artifact_version: Literal["anomaly-model-v1-synthetic-development"] = (
        MODEL_VERSION
    )
    model_family: Literal["LOCAL_SCRATCH_DUAL_LOGISTIC"] = MODEL_FAMILY
    baseline_name: Literal["STATISTICAL_ANOMALY_BASELINE"] = (
        "STATISTICAL_ANOMALY_BASELINE"
    )
    feature_version: Literal[
        "anomaly-window-features-v1-synthetic-development"
    ] = FEATURE_VERSION
    preprocessing_version: Literal["anomaly-window-preprocessing-v1"] = (
        PREPROCESSING_VERSION
    )
    generator_version: Literal["synthetic-anomaly-generator-v1"] = GENERATOR_VERSION
    development_status: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    initialization: Literal["SCRATCH_NO_PRETRAINED_WEIGHTS"] = (
        "SCRATCH_NO_PRETRAINED_WEIGHTS"
    )
    score_interpretation: Literal[
        "SYNTHETIC_DEVELOPMENT_MODEL_SCORE_NOT_FIELD_PROBABILITY"
    ] = "SYNTHETIC_DEVELOPMENT_MODEL_SCORE_NOT_FIELD_PROBABILITY"
    feature_names: list[str]
    scaler_mean: list[float]
    scaler_scale: list[float]
    heads: dict[str, LogisticHead]
    thresholds: dict[str, float]
    training_dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_seed: int
    training_configuration: dict[str, str | int | float | bool]
    calibration: Literal["NONE_VALIDATION_THRESHOLDS_ONLY"] = (
        "NONE_VALIDATION_THRESHOLDS_ONLY"
    )
    pretrained_models: list[str] = Field(default_factory=list, max_length=0)
    open_weight_models: list[str] = Field(default_factory=list, max_length=0)
    external_apis: list[str] = Field(default_factory=list, max_length=0)
    network_access: Literal[False] = False

    @model_validator(mode="after")
    def dimensions_and_policy_are_consistent(self) -> "ScratchDualLogisticArtifact":
        if self.feature_names != list(FEATURE_NAMES):
            raise ValueError("artifact feature order does not match frozen feature space")
        feature_count = len(self.feature_names)
        if len(self.scaler_mean) != feature_count or len(self.scaler_scale) != feature_count:
            raise ValueError("scaler dimensions do not match feature names")
        if set(self.heads) != set(DOMAIN_LABELS):
            raise ValueError("both anomaly-domain heads are required")
        if set(self.thresholds) != set(DOMAIN_LABELS):
            raise ValueError("both anomaly-domain thresholds are required")
        for label, head in self.heads.items():
            if head.label != label or len(head.coefficients) != feature_count:
                raise ValueError("logistic head dimensions or identity are invalid")
        if any(scale <= 0.0 or not math.isfinite(scale) for scale in self.scaler_scale):
            raise ValueError("scaler scales must be finite and positive")
        if any(not 0.0 <= threshold <= 1.0 for threshold in self.thresholds.values()):
            raise ValueError("thresholds must be within [0, 1]")
        return self


def _longest_run(values: Sequence[float | None], *, missing: bool) -> int:
    best = current = 0
    previous: float | None | object = object()
    for value in values:
        if missing:
            current = current + 1 if value is None else 0
        elif value is not None and value == previous:
            current += 1
        elif value is not None:
            current = 1
        else:
            current = 0
        best = max(best, current)
        previous = value
    return best


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) <= 1e-12 or np.std(right) <= 1e-12:
        return 0.0
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else 0.0


def _measurement_vector(
    values: Sequence[float | None],
    timestamps_hours: np.ndarray,
    *,
    minimum_scale: float,
) -> list[float]:
    length = len(values)
    present_indexes = np.asarray(
        [index for index, value in enumerate(values) if value is not None],
        dtype=np.int64,
    )
    if not len(present_indexes):
        return [0.0, 1.0, *([0.0] * (len(MEASUREMENT_FEATURES) - 2))]
    array = np.asarray([float(values[index]) for index in present_indexes], dtype=np.float64)
    center = float(np.median(array))
    mad = float(np.median(np.abs(array - center)))
    lower = float(np.quantile(array, 0.25))
    upper = float(np.quantile(array, 0.75))
    robust_scale = max(1.4826 * mad, (upper - lower) / 1.3489795, minimum_scale)
    reference_indexes = present_indexes[present_indexes < max(12, length // 2)]
    if len(reference_indexes) >= 5:
        reference = np.asarray(
            [float(values[index]) for index in reference_indexes], dtype=np.float64
        )
    else:
        reference = array
    ref_center = float(np.median(reference))
    ref_mad = float(np.median(np.abs(reference - ref_center)))
    ref_lower = float(np.quantile(reference, 0.25))
    ref_upper = float(np.quantile(reference, 0.75))
    ref_scale = max(
        1.4826 * ref_mad,
        (ref_upper - ref_lower) / 1.3489795,
        minimum_scale,
    )
    z_values = np.abs((array - ref_center) / ref_scale)
    latest = float(array[-1])
    latest_z = abs(latest - ref_center) / ref_scale
    deltas: list[float] = []
    rates: list[float] = []
    for left, right in zip(present_indexes, present_indexes[1:]):
        delta = float(values[right]) - float(values[left])
        elapsed = timestamps_hours[right] - timestamps_hours[left]
        deltas.append(delta)
        if elapsed > 0.0:
            rates.append(delta / elapsed)
    tail_indexes = present_indexes[present_indexes >= length - 4]
    tail = (
        np.asarray([float(values[index]) for index in tail_indexes], dtype=np.float64)
        if len(tail_indexes)
        else np.asarray([], dtype=np.float64)
    )
    tail_z = (tail - ref_center) / ref_scale if len(tail) else np.asarray([])
    reversal = 0.0
    if len(deltas) >= 2:
        reversal = max(
            (
                min(abs(left), abs(right)) / ref_scale
                if left * right < 0.0
                else 0.0
            )
            for left, right in zip(deltas, deltas[1:])
        )
    if len(array) >= 2:
        slope = float(
            np.polyfit(timestamps_hours[present_indexes], array, deg=1)[0]
        )
    else:
        slope = 0.0
    return [
        len(array) / length,
        1.0 - len(array) / length,
        latest,
        float(array.mean()),
        center,
        float(array.std(ddof=0)),
        mad,
        lower,
        upper,
        robust_scale,
        float(array.min()),
        float(array.max()),
        float(array.max() - array.min()),
        latest_z,
        float(z_values.max()),
        deltas[-1] if deltas else 0.0,
        max((abs(value) for value in deltas), default=0.0),
        rates[-1] if rates else 0.0,
        max((abs(value) for value in rates), default=0.0),
        float(tail_z.mean()) if len(tail_z) else 0.0,
        float(np.mean(np.abs(tail_z) >= 3.5)) if len(tail_z) else 0.0,
        _longest_run(values, missing=False) / length,
        reversal,
        slope,
        float(np.mean(array < 0.0)),
    ]


def extract_window_feature_vector(record: SyntheticAnomalyModelRecord) -> np.ndarray:
    """Return the frozen detector-visible feature vector for one window."""

    timestamps = record.timestamps
    origin = timestamps[0]
    timestamp_hours = np.asarray(
        [(value - origin).total_seconds() / 3600.0 for value in timestamps],
        dtype=np.float64,
    )
    intervals = np.diff(timestamp_hours)
    interval_median = float(np.median(intervals))
    interval_mad = float(np.median(np.abs(intervals - interval_median)))
    interval_scale = max(interval_mad, interval_median * 0.01, 1.0 / 60.0)
    irregular = np.abs(intervals - interval_median) > max(
        interval_median * 0.25,
        1.0 / 60.0,
    )
    all_missing = [
        rain is None and river is None
        for rain, river in zip(record.rainfall_mm, record.river_level_m)
    ]
    matched = [
        index
        for index, (rain, river) in enumerate(
            zip(record.rainfall_mm, record.river_level_m)
        )
        if rain is not None and river is not None
    ]
    rain_values = np.asarray(
        [float(record.rainfall_mm[index]) for index in matched], dtype=np.float64
    )
    river_values = np.asarray(
        [float(record.river_level_m[index]) for index in matched], dtype=np.float64
    )
    value_correlation = _safe_correlation(rain_values, river_values)
    delta_correlation = _safe_correlation(
        np.diff(rain_values),
        np.diff(river_values),
    )
    elapsed = timestamp_hours[-1] - timestamp_hours[0]
    start_hour = timestamps[0].hour + timestamps[0].minute / 60.0
    global_values = [
        interval_median,
        interval_scale / max(interval_median, 1.0 / 60.0),
        float(irregular.mean()),
        float(intervals.min() / max(interval_median, 1.0 / 60.0)),
        float(intervals.max() / max(interval_median, 1.0 / 60.0)),
        len(timestamps) / elapsed if elapsed > 0.0 else 0.0,
        float(np.mean(all_missing)),
        _longest_run(
            [None if value else 0.0 for value in all_missing], missing=True
        )
        / len(all_missing),
        value_correlation,
        delta_correlation,
        math.sin(start_hour / 24.0 * 2.0 * math.pi),
        math.cos(start_hour / 24.0 * 2.0 * math.pi),
    ]
    vector = np.asarray(
        [
            *_measurement_vector(
                record.rainfall_mm,
                timestamp_hours,
                minimum_scale=0.1,
            ),
            *_measurement_vector(
                record.river_level_m,
                timestamp_hours,
                minimum_scale=0.01,
            ),
            *global_values,
        ],
        dtype=np.float64,
    )
    if vector.shape != (len(FEATURE_NAMES),) or not np.isfinite(vector).all():
        raise ValueError("anomaly feature vector is non-finite or has wrong dimensions")
    return vector


def feature_matrix(records: Sequence[SyntheticAnomalyModelRecord]) -> np.ndarray:
    if not records:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    return np.vstack([extract_window_feature_vector(record) for record in records])


def fit_scratch_dual_logistic(
    records: Sequence[SyntheticAnomalyModelRecord],
    metadata: Sequence[SyntheticAnomalyMetadata],
    *,
    dataset_hash: str,
    training_dataset_hash: str,
    validation_dataset_hash: str,
    seed: int,
) -> ScratchDualLogisticArtifact:
    """Fit two independent local logistic heads from random initialization."""

    if len(records) != len(metadata) or not records:
        raise ValueError("records and metadata must be non-empty and aligned")
    by_id = {item.window_id: item for item in metadata}
    if len(by_id) != len(metadata) or any(item.window_id not in by_id for item in records):
        raise ValueError("records and hidden labels are not one-to-one")
    matrix = feature_matrix(records)
    scaler = StandardScaler().fit(matrix)
    scaled = scaler.transform(matrix)
    targets = {
        "DATA_QUALITY_ANOMALY": np.asarray(
            [int(by_id[item.window_id].data_quality_anomaly) for item in records],
            dtype=np.int64,
        ),
        "WEATHER_BEHAVIOR_ANOMALY": np.asarray(
            [int(by_id[item.window_id].weather_behavior_anomaly) for item in records],
            dtype=np.int64,
        ),
    }
    heads: dict[str, LogisticHead] = {}
    for offset, (label, target) in enumerate(targets.items()):
        if set(target.tolist()) != {0, 1}:
            raise ValueError(f"both classes are required for {label}")
        model = LogisticRegression(
            C=1.0,
            class_weight="balanced",
            fit_intercept=True,
            max_iter=500,
            random_state=seed + offset,
            solver="liblinear",
            tol=1e-8,
        ).fit(scaled, target)
        heads[label] = LogisticHead(
            label=label,
            coefficients=[round(float(value), 14) for value in model.coef_[0]],
            intercept=round(float(model.intercept_[0]), 14),
        )
    return ScratchDualLogisticArtifact(
        feature_names=list(FEATURE_NAMES),
        scaler_mean=[round(float(value), 14) for value in scaler.mean_],
        scaler_scale=[round(float(value), 14) for value in scaler.scale_],
        heads=heads,
        thresholds={label: 0.5 for label in DOMAIN_LABELS},
        training_dataset_hash=training_dataset_hash,
        validation_dataset_hash=validation_dataset_hash,
        dataset_hash=dataset_hash,
        training_seed=seed,
        training_configuration={
            "algorithm": "scikit-learn LogisticRegression",
            "solver": "liblinear",
            "regularization": "L2",
            "C": 1.0,
            "class_weight": "balanced",
            "max_iter": 500,
            "tolerance": 1e-8,
            "heads": 2,
            "supervision": "PROJECT_AUTHORED_SYNTHETIC_LABELS",
        },
    )


def score_feature_matrix(
    artifact: ScratchDualLogisticArtifact,
    matrix: np.ndarray,
) -> dict[str, np.ndarray]:
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
        raise ValueError("feature matrix dimensions do not match artifact")
    mean = np.asarray(artifact.scaler_mean, dtype=np.float64)
    scale = np.asarray(artifact.scaler_scale, dtype=np.float64)
    scaled = (matrix - mean) / scale
    result: dict[str, np.ndarray] = {}
    for label in DOMAIN_LABELS:
        head = artifact.heads[label]
        logits = scaled @ np.asarray(head.coefficients, dtype=np.float64) + head.intercept
        logits = np.clip(logits, -60.0, 60.0)
        result[label] = 1.0 / (1.0 + np.exp(-logits))
    return result


def score_records(
    artifact: ScratchDualLogisticArtifact,
    records: Sequence[SyntheticAnomalyModelRecord],
) -> dict[str, np.ndarray]:
    return score_feature_matrix(artifact, feature_matrix(records))


__all__ = [
    "DOMAIN_LABELS",
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "MODEL_FAMILY",
    "MODEL_VERSION",
    "PREPROCESSING_VERSION",
    "LogisticHead",
    "ScratchDualLogisticArtifact",
    "extract_window_feature_vector",
    "feature_matrix",
    "fit_scratch_dual_logistic",
    "score_feature_matrix",
    "score_records",
]
