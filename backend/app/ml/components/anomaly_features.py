"""Causal anomaly validation, features, and robust baseline fitting.

All rolling features for observation *t* use observations strictly earlier
than *t*. No database, station discovery, network, or external weather lookup
occurs in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from statistics import NormalDist, median

import numpy as np

from app.ml.config import (
    DEFAULT_ANOMALY_DETECTION_CONFIG,
    AnomalyDetectionConfig,
)
from app.ml.contracts import (
    AnomalyBaselineFitResult,
    AnomalyBaselineStatistics,
    AnomalyFeatureRow,
    AnomalyInputWindow,
    AnomalyValidationIssue,
    AnomalyWindowValidationResult,
    StatisticalAnomalyBaseline,
    WeatherMeasurementFeatures,
    WeatherObservation,
)

APPROVED_MEASUREMENTS = ("rainfall_mm", "river_level_m")


def _normal_equivalent_quantile_scale(
    lower_value: float,
    upper_value: float,
    *,
    lower_probability: float,
    upper_probability: float,
) -> float:
    """Scale a quantile span to one normal-distribution standard deviation."""

    normal = NormalDist()
    normal_span = normal.inv_cdf(upper_probability) - normal.inv_cdf(lower_probability)
    return (upper_value - lower_value) / normal_span


def _issue(
    code: str,
    message: str,
    *,
    severity: str,
    observation_id: str | None = None,
    field: str | None = None,
    value=None,
) -> AnomalyValidationIssue:
    return AnomalyValidationIssue(
        code=code,
        message=message,
        severity=severity,
        observation_id=observation_id,
        field=field,
        value=value,
    )


def _has_timezone(value: datetime) -> bool:
    """Return whether a datetime has an effective UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


def validate_anomaly_window(
    window: AnomalyInputWindow,
    *,
    config: AnomalyDetectionConfig | None = None,
) -> AnomalyWindowValidationResult:
    """Return issues without reordering, imputing, or mutating observations."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    errors: list[AnomalyValidationIssue] = []
    validation_warnings: list[AnomalyValidationIssue] = []
    if not window.observations:
        errors.append(
            _issue(
                "EMPTY_WINDOW",
                "No observations were supplied.",
                severity="ERROR",
            )
        )
    if (window.start_at is None) != (window.end_at is None):
        errors.append(
            _issue(
                "INCOMPLETE_WINDOW_TIME_SPAN",
                "Both start_at and end_at are required when either is supplied.",
                severity="ERROR",
            )
        )
    elif window.start_at is None:
        validation_warnings.append(
            _issue(
                "WINDOW_TIME_SPAN_UNAVAILABLE",
                "Caller did not supply an explicit time span.",
                severity="WARNING",
            )
        )
    else:
        if not _has_timezone(window.start_at) or not _has_timezone(window.end_at):
            errors.append(
                _issue(
                    "NAIVE_WINDOW_TIMESTAMP",
                    "Window start_at and end_at must include a timezone.",
                    severity="ERROR",
                )
            )
        elif window.start_at > window.end_at:
            errors.append(
                _issue(
                    "INVALID_WINDOW_TIME_SPAN",
                    "start_at occurs after end_at.",
                    severity="ERROR",
                )
            )

    observation_ids: set[str] = set()
    times: list[tuple[str, datetime]] = []
    missing_measurement_count = 0
    for observation in window.observations:
        if observation.observation_id in observation_ids:
            errors.append(
                _issue(
                    "DUPLICATE_OBSERVATION_ID",
                    "Observation ID occurs more than once.",
                    severity="ERROR",
                    observation_id=observation.observation_id,
                )
            )
        observation_ids.add(observation.observation_id)
        if observation.station_id != window.station_id:
            errors.append(
                _issue(
                    "STATION_ID_MISMATCH",
                    "Observation station does not match the input window.",
                    severity="ERROR",
                    observation_id=observation.observation_id,
                    field="station_id",
                    value=observation.station_id,
                )
            )
        if observation.observed_at is None:
            errors.append(
                _issue(
                    "MISSING_TIMESTAMP",
                    "Observation timestamp is required.",
                    severity="ERROR",
                    observation_id=observation.observation_id,
                    field="observed_at",
                )
            )
        else:
            if not _has_timezone(observation.observed_at):
                errors.append(
                    _issue(
                        "NAIVE_TIMESTAMP",
                        "Observation timestamp must include a timezone.",
                        severity="ERROR",
                        observation_id=observation.observation_id,
                        field="observed_at",
                    )
                )
            else:
                times.append((observation.observation_id, observation.observed_at))
                if (
                    window.start_at is not None
                    and window.end_at is not None
                    and _has_timezone(window.start_at)
                    and _has_timezone(window.end_at)
                    and not window.start_at <= observation.observed_at <= window.end_at
                ):
                    errors.append(
                        _issue(
                            "OBSERVATION_OUTSIDE_WINDOW",
                            "Observation timestamp lies outside the declared time span.",
                            severity="ERROR",
                            observation_id=observation.observation_id,
                            field="observed_at",
                        )
                    )

        coordinates = (observation.latitude, observation.longitude)
        if any(value is not None for value in coordinates):
            if any(value is None for value in coordinates):
                errors.append(
                    _issue(
                        "INCOMPLETE_COORDINATES",
                        "Latitude and longitude must be supplied together.",
                        severity="ERROR",
                        observation_id=observation.observation_id,
                    )
                )
            elif not (
                math.isfinite(float(observation.latitude))
                and math.isfinite(float(observation.longitude))
                and -90.0 <= float(observation.latitude) <= 90.0
                and -180.0 <= float(observation.longitude) <= 180.0
            ):
                errors.append(
                    _issue(
                        "INVALID_COORDINATES",
                        "Coordinates are non-finite or outside valid ranges.",
                        severity="ERROR",
                        observation_id=observation.observation_id,
                    )
                )

        present_measurements = 0
        for field_name in APPROVED_MEASUREMENTS:
            value = getattr(observation, field_name)
            if value is None:
                continue
            present_measurements += 1
            if not math.isfinite(float(value)):
                errors.append(
                    _issue(
                        "NONFINITE_MEASUREMENT",
                        "Measurement is NaN or infinity.",
                        severity="ERROR",
                        observation_id=observation.observation_id,
                        field=field_name,
                        value=str(value),
                    )
                )
            elif field_name == "rainfall_mm" and value < 0.0:
                errors.append(
                    _issue(
                        "IMPOSSIBLE_NEGATIVE_RAINFALL",
                        "A 24-hour rainfall accumulation cannot be negative.",
                        severity="ERROR",
                        observation_id=observation.observation_id,
                        field=field_name,
                        value=value,
                    )
                )
        if present_measurements == 0:
            missing_measurement_count += 1
            validation_warnings.append(
                _issue(
                    "MISSING_MEASUREMENTS",
                    "Observation has no approved weather measurement.",
                    severity="WARNING",
                    observation_id=observation.observation_id,
                )
            )

    time_counts = Counter(timestamp for _, timestamp in times)
    duplicate_timestamps = sorted(
        timestamp for timestamp, count in time_counts.items() if count > 1
    )
    for timestamp in duplicate_timestamps:
        errors.append(
            _issue(
                "DUPLICATE_TIMESTAMP",
                "More than one observation has the same station timestamp.",
                severity="ERROR",
                field="observed_at",
                value=timestamp.isoformat(),
            )
        )
    for (left_id, left), (right_id, right) in pairwise(times):
        if right < left:
            errors.append(
                _issue(
                    "NON_CHRONOLOGICAL_ORDER",
                    "Observations are not in chronological order.",
                    severity="ERROR",
                    observation_id=right_id,
                    field="observed_at",
                    value=f"previous={left_id}:{left.isoformat()}",
                )
            )

    intervals = [
        (right - left).total_seconds()
        for (_, left), (_, right) in pairwise(times)
        if right > left
    ]
    median_interval = float(median(intervals)) if intervals else None
    irregular_count = 0
    if median_interval is not None:
        tolerance = max(
            1.0, median_interval * config.irregular_interval_tolerance_ratio
        )
        irregular_count = sum(
            abs(interval - median_interval) > tolerance for interval in intervals
        )
        if irregular_count:
            validation_warnings.append(
                _issue(
                    "IRREGULAR_SAMPLING_INTERVALS",
                    "Sampling intervals vary beyond the configured tolerance.",
                    severity="WARNING",
                    value={
                        "median_seconds": median_interval,
                        "irregular_count": irregular_count,
                    },
                )
            )
    return AnomalyWindowValidationResult(
        valid=not errors,
        station_id=window.station_id,
        observation_count=len(window.observations),
        errors=errors,
        warnings=validation_warnings,
        duplicate_timestamps=duplicate_timestamps,
        median_interval_seconds=median_interval,
        irregular_interval_count=irregular_count,
        missing_measurement_count=missing_measurement_count,
    )


def _measurement_features(
    value: float | None,
    observed_at: datetime,
    history: deque[tuple[datetime, float]],
    *,
    config: AnomalyDetectionConfig,
) -> WeatherMeasurementFeatures:
    values = np.asarray([item[1] for item in history], dtype=np.float64)
    previous = history[-1] if history else None
    previous_value = previous[1] if previous else None
    delta = None
    rate = None
    if value is not None and previous is not None:
        delta = float(value) - previous_value
        elapsed_hours = (observed_at - previous[0]).total_seconds() / 3600.0
        if elapsed_hours > 0.0:
            rate = delta / elapsed_hours
    rolling_change_mean = None
    if len(values) >= 2:
        rolling_change_mean = float(np.diff(values).mean())
    return WeatherMeasurementFeatures(
        value=float(value) if value is not None else None,
        previous_value=previous_value,
        delta=delta,
        rate_per_hour=rate,
        rolling_mean=float(values.mean()) if len(values) else None,
        rolling_median=float(np.median(values)) if len(values) else None,
        rolling_standard_deviation=float(values.std(ddof=0)) if len(values) else None,
        rolling_lower_quantile=float(np.quantile(values, config.lower_quantile))
        if len(values)
        else None,
        rolling_upper_quantile=float(np.quantile(values, config.upper_quantile))
        if len(values)
        else None,
        rolling_mad=float(np.median(np.abs(values - np.median(values))))
        if len(values)
        else None,
        rolling_change_mean=rolling_change_mean,
        reference_count=len(values),
        missing=value is None,
    )


def extract_anomaly_features(
    window: AnomalyInputWindow,
    *,
    config: AnomalyDetectionConfig | None = None,
) -> list[AnomalyFeatureRow]:
    """Create causal rows; every rolling statistic is prior-only."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    validation = validate_anomaly_window(window, config=config)
    if not validation.valid:
        raise ValueError(
            "invalid anomaly input window: "
            + ", ".join(issue.code for issue in validation.errors)
        )
    rows: list[AnomalyFeatureRow] = []
    missing_count = 0
    first_timestamp = window.observations[0].observed_at
    rainfall_history: deque[tuple[datetime, float]] = deque(
        maxlen=config.rolling_window_size
    )
    river_history: deque[tuple[datetime, float]] = deque(
        maxlen=config.rolling_window_size
    )
    for index, observation in enumerate(window.observations):
        if observation.rainfall_mm is None and observation.river_level_m is None:
            missing_count += 1
        interval_seconds = None
        if index:
            interval_seconds = (
                observation.observed_at - window.observations[index - 1].observed_at
            ).total_seconds()
        elapsed_hours = (
            observation.observed_at - first_timestamp
        ).total_seconds() / 3600.0
        density = (index + 1) / elapsed_hours if elapsed_hours > 0.0 else None
        row = AnomalyFeatureRow(
            feature_version=config.feature_version,
            observation_id=observation.observation_id,
            station_id=observation.station_id,
            observed_at=observation.observed_at,
            hour_of_day=observation.observed_at.hour,
            day_of_year=observation.observed_at.timetuple().tm_yday,
            interval_seconds=interval_seconds,
            observation_density_per_hour=density,
            cumulative_missingness_ratio=missing_count / (index + 1),
            lower_quantile_probability=config.lower_quantile,
            upper_quantile_probability=config.upper_quantile,
            rainfall=_measurement_features(
                observation.rainfall_mm,
                observation.observed_at,
                rainfall_history,
                config=config,
            ),
            river_level=_measurement_features(
                observation.river_level_m,
                observation.observed_at,
                river_history,
                config=config,
            ),
        )
        rows.append(row)
        if observation.rainfall_mm is not None:
            rainfall_history.append(
                (observation.observed_at, float(observation.rainfall_mm))
            )
        if observation.river_level_m is not None:
            river_history.append(
                (observation.observed_at, float(observation.river_level_m))
            )
    return rows


def anomaly_baseline_dataset_hash(observations: Sequence[WeatherObservation]) -> str:
    payload = [item.model_dump(mode="json") for item in observations]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _statistics(
    measurement: str,
    values: Sequence[float],
    *,
    minimum_scale: float,
    lower_quantile: float,
    upper_quantile: float,
) -> AnomalyBaselineStatistics:
    array = np.asarray(values, dtype=np.float64)
    center = float(np.median(array))
    mad = float(np.median(np.abs(array - center)))
    lower_value = float(np.quantile(array, lower_quantile))
    upper_value = float(np.quantile(array, upper_quantile))
    quantile_scale = _normal_equivalent_quantile_scale(
        lower_value,
        upper_value,
        lower_probability=lower_quantile,
        upper_probability=upper_quantile,
    )
    robust_scale = max(1.4826 * mad, quantile_scale, minimum_scale)
    return AnomalyBaselineStatistics(
        measurement=measurement,
        count=len(array),
        median=center,
        mad=mad,
        lower_quantile_probability=lower_quantile,
        upper_quantile_probability=upper_quantile,
        lower_quantile=lower_value,
        upper_quantile=upper_value,
        robust_scale=robust_scale,
    )


def fit_statistical_baseline(
    training_window: AnomalyInputWindow,
    *,
    config: AnomalyDetectionConfig | None = None,
) -> AnomalyBaselineFitResult:
    """Fit an unlabeled reference distribution from an explicit past window."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    validation = validate_anomaly_window(training_window, config=config)
    if not validation.valid:
        return AnomalyBaselineFitResult(
            status="INSUFFICIENT_DATA",
            warnings=[
                "Baseline input failed validation: "
                + ", ".join(issue.code for issue in validation.errors)
            ],
        )
    observations = training_window.observations
    statistics: dict[str, AnomalyBaselineStatistics] = {}
    seasonal: defaultdict[str, dict[str, AnomalyBaselineStatistics]] = defaultdict(dict)
    for measurement, minimum_scale in (
        ("rainfall_mm", config.rainfall_minimum_scale_mm),
        ("river_level_m", config.river_level_minimum_scale_m),
    ):
        values = [
            float(getattr(item, measurement))
            for item in observations
            if getattr(item, measurement) is not None
        ]
        if len(values) >= config.minimum_reference_observations:
            statistics[measurement] = _statistics(
                measurement,
                values,
                minimum_scale=minimum_scale,
                lower_quantile=config.lower_quantile,
                upper_quantile=config.upper_quantile,
            )
        if config.seasonality_mode == "HOUR_OF_DAY":
            by_hour: defaultdict[int, list[float]] = defaultdict(list)
            for item in observations:
                value = getattr(item, measurement)
                if value is not None:
                    by_hour[item.observed_at.hour].append(float(value))
            for hour, hour_values in sorted(by_hour.items()):
                if len(hour_values) >= config.minimum_reference_observations:
                    seasonal[f"hour={hour}"][measurement] = _statistics(
                        measurement,
                        hour_values,
                        minimum_scale=minimum_scale,
                        lower_quantile=config.lower_quantile,
                        upper_quantile=config.upper_quantile,
                    )
    if not statistics:
        return AnomalyBaselineFitResult(
            status="INSUFFICIENT_DATA",
            warnings=[
                "No approved measurement has enough past observations for baseline fitting."
            ],
        )
    digest = anomaly_baseline_dataset_hash(observations)
    timestamps = [item.observed_at for item in observations]
    fitting_parameters = {
        "rolling_window_size": config.rolling_window_size,
        "minimum_reference_observations": config.minimum_reference_observations,
        "robust_scale_definition": (
            "max(1.4826*MAD, (Q_upper-Q_lower)/"
            "(NormalPPF(upper)-NormalPPF(lower)), measurement_floor)"
        ),
        "lower_quantile": config.lower_quantile,
        "upper_quantile": config.upper_quantile,
        "rainfall_minimum_scale_mm": config.rainfall_minimum_scale_mm,
        "river_level_minimum_scale_m": config.river_level_minimum_scale_m,
        "seasonality_mode": config.seasonality_mode,
    }
    version_payload = json.dumps(
        {
            "dataset_hash": digest,
            "feature_version": config.feature_version,
            "fitting_parameters": fitting_parameters,
            "station_scope": [training_window.station_id],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    version_digest = hashlib.sha256(version_payload).hexdigest()
    baseline = StatisticalAnomalyBaseline(
        baseline_version=f"{config.baseline_version_prefix}-{version_digest[:12]}",
        baseline_dataset_hash=digest,
        baseline_start_at=min(timestamps),
        baseline_end_at=max(timestamps),
        feature_version=config.feature_version,
        fitting_parameters=fitting_parameters,
        measurement_statistics=statistics,
        seasonal_statistics=dict(seasonal),
        station_scope=[training_window.station_id],
        observation_count=len(observations),
        seasonality_mode=config.seasonality_mode,
    )
    return AnomalyBaselineFitResult(status="AVAILABLE", baseline=baseline)


def baseline_statistics_for(
    baseline: StatisticalAnomalyBaseline,
    measurement: str,
    observed_at: datetime,
) -> AnomalyBaselineStatistics | None:
    if baseline.seasonality_mode == "HOUR_OF_DAY":
        seasonal = baseline.seasonal_statistics.get(f"hour={observed_at.hour}", {})
        if measurement in seasonal:
            return seasonal[measurement]
    return baseline.measurement_statistics.get(measurement)


def statistical_outlier_score(
    value: float,
    statistics: AnomalyBaselineStatistics,
) -> float:
    """Absolute robust standardized deviation; never an anomaly probability."""

    return abs(float(value) - statistics.median) / statistics.robust_scale


__all__ = [
    "APPROVED_MEASUREMENTS",
    "anomaly_baseline_dataset_hash",
    "baseline_statistics_for",
    "extract_anomaly_features",
    "fit_statistical_baseline",
    "statistical_outlier_score",
    "validate_anomaly_window",
]
