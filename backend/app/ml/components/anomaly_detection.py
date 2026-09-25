"""Transparent local statistical anomaly baseline and future detector interface.

The statistical score is an inspectable outlier statistic, never a calibrated
probability and never ground truth. Learned detector training remains blocked
because no validated anomaly dataset exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import NormalDist
from time import perf_counter
from typing import Any

from app.ml.components.anomaly_features import (
    baseline_statistics_for,
    extract_anomaly_features,
    fit_statistical_baseline,
    statistical_outlier_score,
    validate_anomaly_window,
)
from app.ml.config import (
    DEFAULT_ANOMALY_DETECTION_CONFIG,
    AnomalyDetectionConfig,
)
from app.ml.contracts import (
    AnomalyBaselineFitResult,
    AnomalyBaselineStatistics,
    AnomalyDomain,
    AnomalyFeatureRow,
    AnomalyInputWindow,
    AnomalyPerformanceBenchmark,
    AnomalyPrediction,
    AnomalyScope,
    AnomalyTrainingResult,
    AnomalyType,
    CalibrationStatus,
    MissingDataState,
    PredictionStatus,
    ReportInput,
    StatisticalAnomalyBaseline,
    WeatherObservation,
)

STATISTICAL_ANOMALY_BASELINE = "STATISTICAL_ANOMALY_BASELINE"
STATISTICAL_OUTLIER_SCORE = "STATISTICAL_OUTLIER_SCORE"


def anomaly_window_from_report(report: ReportInput) -> AnomalyInputWindow | None:
    """Adapt already-loaded legacy station observations without querying data."""

    if not report.station_observations:
        return None
    station_ids = {item.station_id for item in report.station_observations}
    if len(station_ids) != 1:
        raise ValueError("MULTIPLE_STATIONS_REQUIRE_SEPARATE_WINDOWS")
    observations = [
        WeatherObservation(
            observation_id=f"{item.station_id}:{item.observed_at.isoformat()}:{index}",
            station_id=item.station_id,
            observed_at=item.observed_at,
            latitude=item.latitude,
            longitude=item.longitude,
            rainfall_mm=item.measurements.get("rainfall_mm"),
            river_level_m=item.measurements.get("river_level_m"),
            source_metadata={"adapter": "ReportInput.station_observations"},
        )
        for index, item in enumerate(report.station_observations)
    ]
    return AnomalyInputWindow(
        station_id=observations[0].station_id,
        observations=observations,
        start_at=observations[0].observed_at,
        end_at=observations[-1].observed_at,
        event_context={"report_id": str(report.report_id)},
    )


def _rolling_statistics(
    row: AnomalyFeatureRow,
    measurement: str,
    config: AnomalyDetectionConfig,
) -> AnomalyBaselineStatistics | None:
    features = row.rainfall if measurement == "rainfall_mm" else row.river_level
    if (
        features.reference_count < config.minimum_reference_observations
        or features.rolling_median is None
        or features.rolling_mad is None
        or features.rolling_lower_quantile is None
        or features.rolling_upper_quantile is None
    ):
        return None
    floor = (
        config.rainfall_minimum_scale_mm
        if measurement == "rainfall_mm"
        else config.river_level_minimum_scale_m
    )
    normal = NormalDist()
    normal_span = normal.inv_cdf(config.upper_quantile) - normal.inv_cdf(
        config.lower_quantile
    )
    quantile_scale = (
        features.rolling_upper_quantile - features.rolling_lower_quantile
    ) / normal_span
    scale = max(
        1.4826 * features.rolling_mad,
        quantile_scale,
        floor,
    )
    return AnomalyBaselineStatistics(
        measurement=measurement,
        count=features.reference_count,
        median=features.rolling_median,
        mad=features.rolling_mad,
        lower_quantile_probability=config.lower_quantile,
        upper_quantile_probability=config.upper_quantile,
        lower_quantile=features.rolling_lower_quantile,
        upper_quantile=features.rolling_upper_quantile,
        robust_scale=scale,
    )


def _row_score_components(
    row: AnomalyFeatureRow,
    *,
    baseline: StatisticalAnomalyBaseline | None,
    config: AnomalyDetectionConfig,
) -> tuple[dict[str, float], dict[str, float]]:
    level_scores: dict[str, float] = {}
    rate_scores: dict[str, float] = {}
    for measurement, features, rate_threshold in (
        (
            "rainfall_mm",
            row.rainfall,
            config.rainfall_rate_threshold_mm_per_hour,
        ),
        (
            "river_level_m",
            row.river_level,
            config.river_level_rate_threshold_m_per_hour,
        ),
    ):
        if features.value is not None:
            statistics = (
                baseline_statistics_for(baseline, measurement, row.observed_at)
                if baseline is not None
                else _rolling_statistics(row, measurement, config)
            )
            if statistics is not None:
                level_scores[measurement] = statistical_outlier_score(
                    features.value,
                    statistics,
                )
        if features.rate_per_hour is not None and (
            baseline is not None
            or features.reference_count >= config.minimum_reference_observations
        ):
            rate_scores[measurement] = (
                abs(features.rate_per_hour) / rate_threshold * config.robust_z_threshold
            )
    return level_scores, rate_scores


def _quality_prediction(
    window: AnomalyInputWindow,
    issue_codes: Sequence[str],
    observation_ids: Sequence[str],
    config: AnomalyDetectionConfig,
) -> AnomalyPrediction:
    return AnomalyPrediction(
        status=PredictionStatus.HEURISTIC_ONLY,
        station_id=window.station_id,
        observation_ids=list(dict.fromkeys(observation_ids)),
        is_anomaly=True,
        anomaly_type=AnomalyType.VALUE_OUTLIER,
        anomaly_types=[AnomalyType.VALUE_OUTLIER],
        anomaly_scope=AnomalyScope.POINT_ANOMALY,
        anomaly_domain=AnomalyDomain.DATA_QUALITY_ANOMALY,
        model_version=config.model_version,
        feature_version=config.feature_version,
        calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
        evidence=[
            "Deterministic physical/data validation failed; no statistical probability was calculated."
        ],
        reason_codes=list(dict.fromkeys(issue_codes)),
        warnings=["DATA_QUALITY_ANOMALY is separate from WEATHER_BEHAVIOR_ANOMALY."],
    )


def score_statistical_window(
    window: AnomalyInputWindow,
    *,
    baseline: StatisticalAnomalyBaseline | None = None,
    config: AnomalyDetectionConfig | None = None,
) -> AnomalyPrediction:
    """Score the latest point/window using past-only references."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    validation = validate_anomaly_window(window, config=config)
    quality_codes = {"NONFINITE_MEASUREMENT", "IMPOSSIBLE_NEGATIVE_RAINFALL"}
    quality_issues = [
        issue for issue in validation.errors if issue.code in quality_codes
    ]
    structural_issues = [
        issue for issue in validation.errors if issue.code not in quality_codes
    ]
    if structural_issues:
        status = (
            PredictionStatus.INSUFFICIENT_DATA
            if {issue.code for issue in structural_issues} <= {"EMPTY_WINDOW"}
            else PredictionStatus.ERROR
        )
        return AnomalyPrediction(
            status=status,
            station_id=window.station_id,
            observation_ids=[item.observation_id for item in window.observations],
            model_version=config.model_version,
            feature_version=config.feature_version,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            reason_codes=[issue.code for issue in structural_issues],
            warnings=[issue.message for issue in validation.warnings],
        )
    if quality_issues:
        return _quality_prediction(
            window,
            [issue.code for issue in quality_issues],
            [issue.observation_id for issue in quality_issues if issue.observation_id],
            config,
        )

    current = window.observations[-1]
    consecutive_missing = 0
    for observation in reversed(window.observations):
        if observation.rainfall_mm is None and observation.river_level_m is None:
            consecutive_missing += 1
        else:
            break
    if consecutive_missing >= config.missingness_pattern_points:
        return AnomalyPrediction(
            status=PredictionStatus.HEURISTIC_ONLY,
            station_id=window.station_id,
            observation_ids=[
                item.observation_id
                for item in window.observations[-consecutive_missing:]
            ],
            is_anomaly=True,
            anomaly_type=AnomalyType.MISSINGNESS_PATTERN,
            anomaly_types=[AnomalyType.MISSINGNESS_PATTERN],
            anomaly_scope=AnomalyScope.WINDOW_ANOMALY,
            anomaly_domain=AnomalyDomain.DATA_QUALITY_ANOMALY,
            model_version=config.model_version,
            feature_version=config.feature_version,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            missing_data_state=MissingDataState.SENSOR_GAP,
            evidence=[
                f"{consecutive_missing} consecutive observations have no approved measurements; configured pattern threshold={config.missingness_pattern_points}."
            ],
            reason_codes=["MISSINGNESS_PATTERN"],
            warnings=[
                "A missingness pattern is a data-availability signal, not proof of weather behavior."
            ],
        )
    if current.rainfall_mm is None and current.river_level_m is None:
        return AnomalyPrediction(
            status=PredictionStatus.INSUFFICIENT_DATA,
            station_id=window.station_id,
            observation_ids=[current.observation_id],
            model_version=config.model_version,
            feature_version=config.feature_version,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            missing_data_state=MissingDataState.MISSING_INPUT,
            reason_codes=["MISSING_INPUT"],
            warnings=["Missing measurements were not automatically labeled anomalous."],
        )
    if baseline is not None:
        if baseline.feature_version != config.feature_version:
            return AnomalyPrediction(
                status=PredictionStatus.ERROR,
                station_id=window.station_id,
                observation_ids=[current.observation_id],
                model_version=config.model_version,
                feature_version=config.feature_version,
                baseline_id=baseline.baseline_dataset_hash,
                baseline_version=baseline.baseline_version,
                calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                reason_codes=["BASELINE_FEATURE_VERSION_MISMATCH"],
                warnings=[
                    "The fitted baseline feature version does not match inference configuration."
                ],
            )
        if current.observed_at <= baseline.baseline_end_at:
            return AnomalyPrediction(
                status=PredictionStatus.ERROR,
                station_id=window.station_id,
                observation_ids=[current.observation_id],
                model_version=config.model_version,
                feature_version=config.feature_version,
                baseline_id=baseline.baseline_dataset_hash,
                baseline_version=baseline.baseline_version,
                calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                reason_codes=["TEMPORAL_LEAKAGE_BASELINE_NOT_EARLIER"],
                warnings=[
                    "Inference timestamp must be later than the fitted baseline window."
                ],
            )
        if window.station_id not in baseline.station_scope:
            return AnomalyPrediction(
                status=PredictionStatus.INSUFFICIENT_DATA,
                station_id=window.station_id,
                observation_ids=[current.observation_id],
                model_version=config.model_version,
                feature_version=config.feature_version,
                baseline_id=baseline.baseline_dataset_hash,
                baseline_version=baseline.baseline_version,
                calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                reason_codes=["BASELINE_STATION_SCOPE_MISMATCH"],
                warnings=["No approved cross-station baseline was supplied."],
            )

    rows = extract_anomaly_features(window, config=config)
    target = rows[-1]
    level_scores, rate_scores = _row_score_components(
        target,
        baseline=baseline,
        config=config,
    )
    all_components = {
        **level_scores,
        **{f"rate:{key}": value for key, value in rate_scores.items()},
    }
    if not all_components:
        return AnomalyPrediction(
            status=PredictionStatus.INSUFFICIENT_DATA,
            station_id=window.station_id,
            observation_ids=[current.observation_id],
            model_version=config.model_version,
            feature_version=config.feature_version,
            baseline_id=baseline.baseline_dataset_hash if baseline else None,
            baseline_version=(
                baseline.baseline_version
                if baseline
                else "rolling-statistical-baseline-v1"
            ),
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            reason_codes=["INSUFFICIENT_REFERENCE_HISTORY"],
            warnings=[
                "No score was produced without the configured amount of past reference data."
            ],
        )

    anomaly_types: list[AnomalyType] = []
    if any(score >= config.robust_z_threshold for score in level_scores.values()):
        anomaly_types.append(AnomalyType.VALUE_OUTLIER)
    if any(score >= config.robust_z_threshold for score in rate_scores.values()):
        anomaly_types.append(AnomalyType.RATE_OF_CHANGE)

    persistent_rows = rows[-config.persistent_points :]
    persistent_ids: list[str] = []
    if len(persistent_rows) == config.persistent_points:
        persistent_flags = []
        for row in persistent_rows:
            row_levels, _ = _row_score_components(
                row,
                baseline=baseline,
                config=config,
            )
            persistent_flags.append(
                bool(row_levels)
                and max(row_levels.values()) >= config.robust_z_threshold
            )
        if all(persistent_flags):
            anomaly_types.append(AnomalyType.PERSISTENT_DEVIATION)
            persistent_ids = [row.observation_id for row in persistent_rows]

    primary_type = (
        AnomalyType.PERSISTENT_DEVIATION
        if AnomalyType.PERSISTENT_DEVIATION in anomaly_types
        else AnomalyType.RATE_OF_CHANGE
        if AnomalyType.RATE_OF_CHANGE in anomaly_types
        else AnomalyType.VALUE_OUTLIER
        if AnomalyType.VALUE_OUTLIER in anomaly_types
        else None
    )
    score = max(all_components.values())
    is_anomaly = bool(anomaly_types)
    baseline_version = (
        baseline.baseline_version if baseline else "rolling-statistical-baseline-v1"
    )
    evidence = [
        "STATISTICAL_OUTLIER_SCORE=max(abs(value-median)/robust_scale, threshold-scaled absolute rate ratio).",
        "robust_scale=max(1.4826*MAD, normal-equivalent configured quantile span, configured measurement floor).",
        *[f"{name}={value:.6f}" for name, value in sorted(all_components.items())],
    ]
    return AnomalyPrediction(
        status=PredictionStatus.HEURISTIC_ONLY,
        station_id=window.station_id,
        observation_ids=persistent_ids or [current.observation_id],
        is_anomaly=is_anomaly,
        anomaly_type=primary_type,
        anomaly_types=anomaly_types,
        anomaly_scope=(
            AnomalyScope.WINDOW_ANOMALY
            if AnomalyType.PERSISTENT_DEVIATION in anomaly_types
            else AnomalyScope.POINT_ANOMALY
            if is_anomaly
            else None
        ),
        anomaly_domain=(AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY if is_anomaly else None),
        score=score,
        score_type=STATISTICAL_OUTLIER_SCORE,
        threshold=config.robust_z_threshold,
        model_version=config.model_version,
        baseline_id=baseline.baseline_dataset_hash if baseline else None,
        baseline_version=baseline_version,
        feature_version=config.feature_version,
        calibration_status=CalibrationStatus.NOT_CALIBRATED,
        evidence=evidence,
        reason_codes=(
            [item.value for item in anomaly_types]
            if anomaly_types
            else ["NO_STATISTICAL_OUTLIER_SIGNAL"]
        ),
        warnings=[
            "STATISTICAL_OUTLIER_SCORE is not a calibrated anomaly probability or ground-truth label.",
            "Extreme weather is not automatically classified as sensor error.",
        ],
    )


def benchmark_anomaly_pipeline(
    window: AnomalyInputWindow,
    *,
    config: AnomalyDetectionConfig | None = None,
) -> AnomalyPerformanceBenchmark:
    """Measure local computation stages only; this is not throughput validation."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    if len(window.observations) <= config.minimum_reference_observations:
        raise ValueError(
            "benchmark requires a reference period plus at least one future observation"
        )
    feature_started = perf_counter()
    rows = extract_anomaly_features(window, config=config)
    feature_seconds = perf_counter() - feature_started

    training_count = max(
        config.minimum_reference_observations,
        int(len(window.observations) * 0.6),
    )
    training_count = min(training_count, len(window.observations) - 1)
    training_observations = window.observations[:training_count]
    training_window = window.model_copy(
        update={
            "observations": training_observations,
            "start_at": training_observations[0].observed_at,
            "end_at": training_observations[-1].observed_at,
        }
    )
    fit_started = perf_counter()
    fit_result = fit_statistical_baseline(training_window, config=config)
    fit_seconds = perf_counter() - fit_started

    score_started = perf_counter()
    if fit_result.baseline is not None:
        for row in rows[training_count:]:
            _row_score_components(row, baseline=fit_result.baseline, config=config)
    score_seconds = perf_counter() - score_started

    inference_started = perf_counter()
    score_statistical_window(
        window,
        baseline=fit_result.baseline,
        config=config,
    )
    inference_seconds = perf_counter() - inference_started
    return AnomalyPerformanceBenchmark(
        observation_count=len(window.observations),
        feature_computation_seconds=feature_seconds,
        baseline_fitting_seconds=fit_seconds,
        baseline_scoring_seconds=score_seconds,
        detector_inference_seconds=inference_seconds,
    )


class AnomalyDetector:
    """Statistical baseline plus blocked future Isolation Forest interface."""

    component_name = "anomaly_detector"

    def __init__(self, config: AnomalyDetectionConfig | None = None) -> None:
        self.config = config or DEFAULT_ANOMALY_DETECTION_CONFIG

    def predict(
        self,
        value: AnomalyInputWindow | ReportInput,
        *,
        baseline: StatisticalAnomalyBaseline | None = None,
    ) -> AnomalyPrediction:
        if isinstance(value, ReportInput):
            try:
                window = anomaly_window_from_report(value)
            except ValueError as error:
                return AnomalyPrediction(
                    status=PredictionStatus.INSUFFICIENT_DATA,
                    model_version=self.config.model_version,
                    feature_version=self.config.feature_version,
                    calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                    reason_codes=[str(error)],
                    warnings=[
                        "Each anomaly input window must contain exactly one station."
                    ],
                )
            if window is None:
                return AnomalyPrediction(
                    status=PredictionStatus.NOT_APPLICABLE,
                    model_version=self.config.model_version,
                    feature_version=self.config.feature_version,
                    calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                    reason_codes=["WEATHER_OBSERVATIONS_NOT_SUPPLIED"],
                    warnings=["No already-loaded station observations were supplied."],
                )
        else:
            window = value
        return score_statistical_window(
            window,
            baseline=baseline,
            config=self.config,
        )

    def fit(
        self,
        training_data: Sequence[Any] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> AnomalyTrainingResult:
        del training_data, config
        return AnomalyTrainingResult(
            status="TRAINING_BLOCKED_NO_VALIDATED_ANOMALY_DATA",
            artifact_created=False,
            reason_codes=["NO_VALIDATED_ANOMALY_GROUND_TRUTH"],
            required_provenance=[
                "model_version",
                "dataset_hash",
                "feature_version",
                "baseline_version",
                "library_version",
                "random_seed",
                "artifact_hash",
                "training_window",
                "station_scope",
                "policy_status",
            ],
            warnings=[
                "Isolation Forest or another learned detector requires legitimate local training data and validation labels."
            ],
        )

    def fit_baseline(
        self,
        training_window: AnomalyInputWindow,
    ) -> AnomalyBaselineFitResult:
        return fit_statistical_baseline(training_window, config=self.config)

    def evaluate(self, annotations=None, predictions=None, **kwargs):
        from app.ml.evaluation.evaluate import evaluate_anomaly_predictions

        supplied_annotations = [] if annotations is None else annotations
        supplied_predictions = [] if predictions is None else predictions
        return evaluate_anomaly_predictions(
            supplied_annotations,
            supplied_predictions,
            **kwargs,
        )


__all__ = [
    "STATISTICAL_ANOMALY_BASELINE",
    "STATISTICAL_OUTLIER_SCORE",
    "AnomalyDetector",
    "anomaly_window_from_report",
    "benchmark_anomaly_pipeline",
    "score_statistical_window",
]
