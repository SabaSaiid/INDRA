from __future__ import annotations

import ast
import hashlib
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ml.anomaly_artifacts import (
    AnomalyArtifactProvenance,
    authorize_anomaly_artifact,
)
from app.ml.components.anomaly_detection import (
    STATISTICAL_ANOMALY_BASELINE,
    STATISTICAL_OUTLIER_SCORE,
    AnomalyDetector,
    benchmark_anomaly_pipeline,
    score_statistical_window,
)
from app.ml.components.anomaly_features import (
    APPROVED_MEASUREMENTS,
    anomaly_baseline_dataset_hash,
    baseline_statistics_for,
    extract_anomaly_features,
    fit_statistical_baseline,
    statistical_outlier_score,
    validate_anomaly_window,
)
from app.ml.config import AnomalyDetectionConfig
from app.ml.contracts import (
    AnomalyDomain,
    AnomalyInputWindow,
    AnomalyPrediction,
    AnomalyScope,
    AnomalyType,
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    CalibrationStatus,
    MissingDataState,
    PredictionStatus,
    StatisticalAnomalyBaseline,
    WeatherObservation,
)
from app.ml.data.anomaly_annotations import (
    AnomalyAnnotation,
    AnomalyAnnotationLabel,
    AnomalyAnnotationStore,
    temporal_observation_split,
    validate_anomaly_annotations,
    validate_station_group_leakage,
    validate_temporal_leakage,
)
from app.ml.evaluation.evaluate import (
    calibrate_anomaly_threshold,
    evaluate_anomaly_predictions,
    evaluate_anomaly_test,
)
from app.ml.training.train_anomaly_detector import train_anomaly_detector

START = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase9-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _observation(
    index: int,
    *,
    rainfall_mm: float | None = 1.0,
    river_level_m: float | None = None,
    station_id: str = "station-1",
    observed_at: datetime | None = None,
) -> WeatherObservation:
    return WeatherObservation(
        observation_id=f"{station_id}-observation-{index}",
        station_id=station_id,
        observed_at=observed_at or START + timedelta(hours=index),
        latitude=20.0,
        longitude=80.0,
        rainfall_mm=rainfall_mm,
        river_level_m=river_level_m,
        source_metadata={"fixture": "UNIT_TEST_ONLY"},
    )


def _window(
    rainfall: list[float | None],
    *,
    river_levels: list[float | None] | None = None,
    station_id: str = "station-1",
    start_at: datetime = START,
) -> AnomalyInputWindow:
    if river_levels is None:
        river_levels = [None] * len(rainfall)
    assert len(rainfall) == len(river_levels)
    observations = [
        _observation(
            index,
            rainfall_mm=rainfall_value,
            river_level_m=river_value,
            station_id=station_id,
            observed_at=start_at + timedelta(hours=index),
        )
        for index, (rainfall_value, river_value) in enumerate(
            zip(rainfall, river_levels)
        )
    ]
    return AnomalyInputWindow(
        station_id=station_id,
        observations=observations,
        start_at=observations[0].observed_at if observations else start_at,
        end_at=observations[-1].observed_at if observations else start_at,
        station_metadata={"fixture": "UNIT_TEST_ONLY"},
        event_context={},
    )


def _annotation(
    target_id: str,
    label: AnomalyAnnotationLabel,
    *,
    annotator_id: str = "annotator-1",
    anomaly_type: AnomalyType | None = None,
    anomaly_domain: AnomalyDomain | None = None,
    split: str | None = None,
) -> AnomalyAnnotation:
    return AnomalyAnnotation(
        annotation_id=f"annotation-{target_id}-{annotator_id}",
        target_id=target_id,
        station_id="station-1",
        observation_ids=[target_id],
        scope=AnomalyScope.POINT_ANOMALY,
        label=label,
        annotator_id=annotator_id,
        annotation_timestamp=START + timedelta(days=30),
        reason="Reviewed against the supplied station and event context.",
        evidence=["UNIT_TEST_ONLY reviewed evidence"],
        anomaly_type=anomaly_type,
        anomaly_domain=anomaly_domain,
        observed_start_at=START,
        observed_end_at=START,
        split=split,
    )


def _prediction(
    is_anomaly: bool,
    domain: AnomalyDomain | None = None,
) -> AnomalyPrediction:
    return AnomalyPrediction(
        status=PredictionStatus.HEURISTIC_ONLY,
        is_anomaly=is_anomaly,
        anomaly_domain=domain,
        score=4.0 if is_anomaly else 0.0,
        score_type=STATISTICAL_OUTLIER_SCORE,
        threshold=3.5,
        calibration_status=CalibrationStatus.NOT_CALIBRATED,
    )


def test_input_contract_contains_only_repository_approved_measurements():
    fields = set(WeatherObservation.model_fields)
    assert APPROVED_MEASUREMENTS == ("rainfall_mm", "river_level_m")
    assert {"rainfall_mm", "river_level_m"} <= fields
    assert not {"temperature", "humidity", "pressure", "wind_speed"} & fields
    with pytest.raises(ValidationError, match="temperature"):
        WeatherObservation(
            observation_id="observation-1",
            station_id="station-1",
            observed_at=START,
            temperature=30.0,
        )


def test_validation_reports_order_duplicates_and_irregular_intervals_without_fixing():
    observations = [
        _observation(0, observed_at=START),
        _observation(1, observed_at=START + timedelta(hours=2)),
        _observation(2, observed_at=START + timedelta(hours=1)),
        _observation(3, observed_at=START + timedelta(hours=1)),
        _observation(4, observed_at=START + timedelta(hours=10)),
    ]
    value = AnomalyInputWindow(
        station_id="station-1",
        observations=observations,
        start_at=START,
        end_at=START + timedelta(hours=10),
    )
    original_ids = [item.observation_id for item in value.observations]
    result = validate_anomaly_window(value)
    codes = {item.code for item in result.errors}
    warning_codes = {item.code for item in result.warnings}
    assert {"NON_CHRONOLOGICAL_ORDER", "DUPLICATE_TIMESTAMP"} <= codes
    assert "IRREGULAR_SAMPLING_INTERVALS" in warning_codes
    assert [item.observation_id for item in value.observations] == original_ids


def test_validation_reports_missing_timestamp_numeric_coordinate_and_missing_values():
    observations = [
        WeatherObservation(
            observation_id="missing-time",
            station_id="station-1",
            observed_at=None,
            rainfall_mm=None,
            river_level_m=None,
        ),
        WeatherObservation(
            observation_id="invalid-values",
            station_id="station-1",
            observed_at=START,
            latitude=91.0,
            longitude=181.0,
            rainfall_mm=math.inf,
        ),
        WeatherObservation(
            observation_id="negative-rain",
            station_id="station-1",
            observed_at=START + timedelta(hours=1),
            rainfall_mm=-0.1,
        ),
    ]
    result = validate_anomaly_window(
        AnomalyInputWindow(station_id="station-1", observations=observations)
    )
    error_codes = {item.code for item in result.errors}
    warning_codes = {item.code for item in result.warnings}
    assert {
        "MISSING_TIMESTAMP",
        "INVALID_COORDINATES",
        "NONFINITE_MEASUREMENT",
        "IMPOSSIBLE_NEGATIVE_RAINFALL",
    } <= error_codes
    assert "MISSING_MEASUREMENTS" in warning_codes
    assert result.missing_measurement_count == 1


def test_validation_returns_timezone_issues_instead_of_raising_type_errors():
    naive = datetime(2026, 9, 1, 0, 0)  # noqa: DTZ001 - invalid-input fixture
    value = AnomalyInputWindow(
        station_id="station-1",
        observations=[_observation(0)],
        start_at=naive,
        end_at=naive + timedelta(hours=1),
    )
    result = validate_anomaly_window(value)
    assert "NAIVE_WINDOW_TIMESTAMP" in {item.code for item in result.errors}


def test_features_are_versioned_causal_and_include_change_rolling_context():
    first = _window([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    changed_future = _window([1.0, 2.0, 3.0, 4.0, 5.0, 600.0])
    first_rows = extract_anomaly_features(first)
    changed_rows = extract_anomaly_features(changed_future)
    assert [row.model_dump() for row in first_rows[:5]] == [
        row.model_dump() for row in changed_rows[:5]
    ]
    target = first_rows[-1]
    assert target.feature_version == "anomaly-features-v1"
    assert target.rainfall.previous_value == 5.0
    assert target.rainfall.delta == 1.0
    assert target.rainfall.rate_per_hour == 1.0
    assert target.rainfall.rolling_median == 3.0
    assert target.rainfall.rolling_mad == 1.0
    assert target.rainfall.reference_count == 5
    assert target.observation_density_per_hour is not None


def test_explicit_baseline_records_provenance_and_robust_score_definition():
    training = _window([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    first = fit_statistical_baseline(training)
    second = fit_statistical_baseline(training)
    assert first.status == "AVAILABLE"
    assert first.baseline is not None
    assert first.baseline == second.baseline
    baseline = first.baseline
    assert baseline.baseline_name == STATISTICAL_ANOMALY_BASELINE
    assert baseline.baseline_dataset_hash == anomaly_baseline_dataset_hash(
        training.observations
    )
    assert baseline.baseline_start_at == START
    assert baseline.baseline_end_at == START + timedelta(hours=5)
    assert baseline.feature_version == "anomaly-features-v1"
    assert baseline.fitting_parameters["seasonality_mode"] == "NONE"
    statistics = baseline.measurement_statistics["rainfall_mm"]
    assert statistics.robust_scale == 0.1
    assert statistical_outlier_score(1.0, statistics) == 10.0

    differently_configured = fit_statistical_baseline(
        training,
        config=AnomalyDetectionConfig(lower_quantile=0.1, upper_quantile=0.9),
    ).baseline
    assert differently_configured is not None
    assert (
        differently_configured.baseline_dataset_hash == baseline.baseline_dataset_hash
    )
    assert differently_configured.baseline_version != baseline.baseline_version

    custom = fit_statistical_baseline(
        _window([float(index) for index in range(10)]),
        config=AnomalyDetectionConfig(lower_quantile=0.1, upper_quantile=0.9),
    ).baseline
    assert custom is not None
    custom_statistics = custom.measurement_statistics["rainfall_mm"]
    assert custom_statistics.lower_quantile_probability == 0.1
    assert custom_statistics.upper_quantile_probability == 0.9
    assert custom_statistics.lower_quantile < custom_statistics.upper_quantile


def test_hour_of_day_baseline_is_explicit_and_falls_back_to_global_statistics():
    observations = [
        _observation(
            index,
            rainfall_mm=0.0 if index % 2 == 0 else 10.0,
            observed_at=START + timedelta(hours=12 * index),
        )
        for index in range(8)
    ]
    value = AnomalyInputWindow(
        station_id="station-1",
        observations=observations,
        start_at=observations[0].observed_at,
        end_at=observations[-1].observed_at,
    )
    config = AnomalyDetectionConfig(
        minimum_reference_observations=3,
        seasonality_mode="HOUR_OF_DAY",
    )
    result = fit_statistical_baseline(value, config=config)
    assert result.baseline is not None
    midnight = baseline_statistics_for(result.baseline, "rainfall_mm", START)
    noon = baseline_statistics_for(
        result.baseline, "rainfall_mm", START + timedelta(hours=12)
    )
    fallback = baseline_statistics_for(
        result.baseline, "rainfall_mm", START + timedelta(hours=6)
    )
    assert midnight is not None and midnight.median == 0.0
    assert noon is not None and noon.median == 10.0
    assert fallback is not None and fallback.count == 8


def test_fixture_a_stable_series_is_not_an_anomaly():
    prediction = score_statistical_window(_window([1.0] * 8))
    assert prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert prediction.is_anomaly is False
    assert prediction.anomaly_type is None
    assert prediction.anomaly_scope is None
    assert prediction.score == 0.0
    assert prediction.score_type == STATISTICAL_OUTLIER_SCORE
    assert prediction.calibration_status is CalibrationStatus.NOT_CALIBRATED


def test_fixture_b_single_extreme_is_a_weather_point_anomaly():
    fitted = fit_statistical_baseline(_window([0.0] * 8)).baseline
    assert fitted is not None
    future = _window([100.0], start_at=START + timedelta(hours=8))
    prediction = score_statistical_window(future, baseline=fitted)
    assert prediction.is_anomaly is True
    assert prediction.anomaly_type is AnomalyType.VALUE_OUTLIER
    assert prediction.anomaly_scope is AnomalyScope.POINT_ANOMALY
    assert prediction.anomaly_domain is AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY
    assert prediction.score is not None and prediction.score > prediction.threshold


def test_fixture_c_rapid_change_is_a_rate_of_change_anomaly():
    config = AnomalyDetectionConfig(
        river_level_minimum_scale_m=1.0,
        river_level_rate_threshold_m_per_hour=0.5,
    )
    value = _window(
        [None] * 6,
        river_levels=[1.0, 1.1, 1.2, 1.3, 1.4, 2.0],
    )
    prediction = score_statistical_window(value, config=config)
    assert prediction.is_anomaly is True
    assert prediction.anomaly_type is AnomalyType.RATE_OF_CHANGE
    assert AnomalyType.VALUE_OUTLIER not in prediction.anomaly_types


def test_fixture_d_persistent_deviation_is_a_window_anomaly():
    fitted = fit_statistical_baseline(_window([0.0] * 8)).baseline
    assert fitted is not None
    future = _window([20.0, 20.0, 20.0], start_at=START + timedelta(hours=8))
    prediction = score_statistical_window(future, baseline=fitted)
    assert prediction.is_anomaly is True
    assert prediction.anomaly_type is AnomalyType.PERSISTENT_DEVIATION
    assert prediction.anomaly_scope is AnomalyScope.WINDOW_ANOMALY
    assert prediction.observation_ids == [
        item.observation_id for item in future.observations
    ]


def test_fixture_e_missing_readings_have_explicit_non_equivalent_states():
    single_missing = score_statistical_window(_window([1.0] * 5 + [None]))
    assert single_missing.status is PredictionStatus.INSUFFICIENT_DATA
    assert single_missing.is_anomaly is None
    assert single_missing.missing_data_state is MissingDataState.MISSING_INPUT

    repeated_missing = score_statistical_window(_window([1.0] * 5 + [None, None, None]))
    assert repeated_missing.status is PredictionStatus.HEURISTIC_ONLY
    assert repeated_missing.is_anomaly is True
    assert repeated_missing.anomaly_type is AnomalyType.MISSINGNESS_PATTERN
    assert repeated_missing.anomaly_domain is AnomalyDomain.DATA_QUALITY_ANOMALY
    assert repeated_missing.missing_data_state is MissingDataState.SENSOR_GAP
    assert {
        MissingDataState.SEASONALLY_UNAVAILABLE,
        MissingDataState.UNKNOWN,
    } <= set(MissingDataState)


def test_fixture_f_impossible_measurement_is_a_data_quality_anomaly():
    prediction = score_statistical_window(_window([-1.0]))
    assert prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert prediction.is_anomaly is True
    assert prediction.anomaly_domain is AnomalyDomain.DATA_QUALITY_ANOMALY
    assert prediction.score is None
    assert prediction.score_type is None
    assert "IMPOSSIBLE_NEGATIVE_RAINFALL" in prediction.reason_codes


def test_fixture_g_legitimate_extreme_is_not_automatically_bad_data():
    fitted = fit_statistical_baseline(_window([0.0] * 8)).baseline
    assert fitted is not None
    prediction = score_statistical_window(
        _window([250.0], start_at=START + timedelta(hours=8)),
        baseline=fitted,
    )
    assert prediction.is_anomaly is True
    assert prediction.anomaly_domain is AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY
    assert "IMPOSSIBLE_NEGATIVE_RAINFALL" not in prediction.reason_codes
    assert any("not automatically" in warning for warning in prediction.warnings)


def test_insufficient_history_and_baseline_compatibility_are_explicit():
    insufficient = score_statistical_window(_window([1.0, 2.0]))
    assert insufficient.status is PredictionStatus.INSUFFICIENT_DATA
    assert insufficient.score is None
    assert insufficient.reason_codes == ["INSUFFICIENT_REFERENCE_HISTORY"]

    fitted = fit_statistical_baseline(_window([1.0] * 6)).baseline
    assert fitted is not None
    overlapping = score_statistical_window(_window([1.0]), baseline=fitted)
    assert overlapping.status is PredictionStatus.ERROR
    assert overlapping.reason_codes == ["TEMPORAL_LEAKAGE_BASELINE_NOT_EARLIER"]

    mismatched = fitted.model_copy(update={"feature_version": "future-features-v2"})
    future = _window([1.0], start_at=START + timedelta(hours=7))
    mismatch_prediction = score_statistical_window(future, baseline=mismatched)
    assert mismatch_prediction.status is PredictionStatus.ERROR
    assert mismatch_prediction.reason_codes == ["BASELINE_FEATURE_VERSION_MISMATCH"]


def test_temporal_split_preserves_order_and_detects_temporal_leakage():
    observations = _window([1.0] * 10).observations
    split = temporal_observation_split(observations)
    assert split.status == "TEMPORAL_SPLIT_AVAILABLE"
    report = validate_temporal_leakage(split.train, split.validation, split.test)
    assert report.valid
    assert max(item.observed_at for item in split.train) < min(
        item.observed_at for item in split.validation
    )
    assert max(item.observed_at for item in split.validation) < min(
        item.observed_at for item in split.test
    )
    shuffled = temporal_observation_split(
        [observations[1], observations[0], *observations[2:]]
    )
    assert shuffled.status == "INSUFFICIENT_DATA"
    sparse_stations = temporal_observation_split(
        [
            *[_observation(index, station_id="station-a") for index in range(3)],
            *[_observation(index, station_id="station-b") for index in range(3)],
        ]
    )
    assert sparse_stations.status == "INSUFFICIENT_DATA"
    assert "station-a" in sparse_stations.warnings[0]
    leaking = validate_temporal_leakage(split.validation, split.train, split.test)
    assert not leaking.valid


def test_station_grouping_reports_counts_and_optional_disjointness():
    train = [_observation(0, station_id="station-a")]
    validation = [
        _observation(1, station_id="station-a"),
        _observation(2, station_id="station-b"),
    ]
    test = [_observation(3, station_id="station-c")]
    reported = validate_station_group_leakage(
        train,
        validation,
        test,
        require_disjoint_stations=False,
    )
    assert reported.valid
    assert reported.station_count == 3
    assert reported.observations_per_station == {
        "station-a": 2,
        "station-b": 1,
        "station-c": 1,
    }
    assert reported.train_validation_overlap == ["station-a"]
    disjoint = validate_station_group_leakage(
        train,
        validation,
        test,
        require_disjoint_stations=True,
    )
    assert not disjoint.valid


def test_annotation_schema_store_and_quality_preserve_uncertainty(local_tmp_path):
    anomaly = _annotation(
        "target-1",
        AnomalyAnnotationLabel.ANOMALY,
        anomaly_type=AnomalyType.VALUE_OUTLIER,
        anomaly_domain=AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY,
    )
    disagreement = _annotation(
        "target-1",
        AnomalyAnnotationLabel.UNCERTAIN,
        annotator_id="annotator-2",
    )
    optional_type = _annotation(
        "target-2",
        AnomalyAnnotationLabel.ANOMALY,
        anomaly_domain=AnomalyDomain.UNCERTAIN,
    )
    assert optional_type.anomaly_type is None
    assert optional_type.anomaly_domain is AnomalyDomain.UNCERTAIN
    with pytest.raises(ValidationError, match="require a resolved or UNCERTAIN domain"):
        _annotation("target-no-domain", AnomalyAnnotationLabel.ANOMALY)
    with pytest.raises(ValidationError, match="cannot carry"):
        _annotation(
            "target-3",
            AnomalyAnnotationLabel.NORMAL,
            anomaly_type=AnomalyType.VALUE_OUTLIER,
            anomaly_domain=AnomalyDomain.DATA_QUALITY_ANOMALY,
        )

    store = AnomalyAnnotationStore(local_tmp_path / "anomaly-annotations.jsonl")
    store.append(anomaly)
    store.append(disagreement)
    assert store.load() == [anomaly, disagreement]
    quality = validate_anomaly_annotations(
        store.load(), available_observation_ids={"target-1"}
    )
    assert quality.valid
    assert quality.agreement_status == "DATA_AVAILABLE"
    assert quality.agreement_rate == 0.0
    assert quality.disagreement_target_ids == ["target-1"]
    assert any("UNCERTAIN" in warning for warning in quality.warnings)
    with pytest.raises(ValueError, match="same annotator"):
        store.append(anomaly.model_copy(update={"annotation_id": "another-annotation"}))


def test_evaluation_is_unavailable_without_labels_and_reports_all_supported_metrics():
    unavailable = evaluate_anomaly_predictions([], [])
    assert unavailable.evaluation_status == "DATA_UNAVAILABLE"
    annotations = [
        _annotation(
            "weather-1",
            AnomalyAnnotationLabel.ANOMALY,
            anomaly_type=AnomalyType.VALUE_OUTLIER,
            anomaly_domain=AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY,
        ),
        _annotation(
            "quality-1",
            AnomalyAnnotationLabel.ANOMALY,
            anomaly_type=AnomalyType.VALUE_OUTLIER,
            anomaly_domain=AnomalyDomain.DATA_QUALITY_ANOMALY,
        ),
        _annotation("normal-1", AnomalyAnnotationLabel.NORMAL),
        _annotation("uncertain-1", AnomalyAnnotationLabel.UNCERTAIN),
    ]
    predictions = [
        _prediction(True, AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY),
        _prediction(False),
        _prediction(True, AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY),
        _prediction(True, AnomalyDomain.DATA_QUALITY_ANOMALY),
    ]
    report = evaluate_anomaly_predictions(
        annotations,
        predictions,
        detection_delay_minutes=[5.0, None, None, None],
        observation_period_hours=24.0,
        event_ids=["event-weather", "event-quality", "event-normal", None],
    )
    assert report.evaluation_status == "DATA_AVAILABLE"
    assert report.sample_count == 3
    assert report.excluded_uncertain_count == 1
    assert report.overall_metrics is not None
    assert report.overall_metrics.precision == 0.5
    assert report.overall_metrics.recall == 0.5
    assert report.overall_metrics.f1 == 0.5
    assert report.overall_metrics.false_positive_rate == 1.0
    assert report.overall_metrics.false_negative_rate == 0.5
    assert report.mean_detection_delay_minutes == 5.0
    assert report.false_alarm_rate_per_day == 1.0
    assert report.event_level_metrics["event_precision"] == 0.5
    assert report.event_level_metrics["event_recall"] == 0.5
    assert report.event_level_metrics["event_f1"] == 0.5
    assert set(report.metrics_by_domain) == {
        "DATA_QUALITY_ANOMALY",
        "WEATHER_BEHAVIOR_ANOMALY",
    }


def test_threshold_is_selected_on_validation_frozen_and_applied_to_test():
    frozen = calibrate_anomaly_threshold(
        ["NORMAL", "ANOMALY", "ANOMALY", "UNCERTAIN"],
        [0.1, 0.7, 0.9, 100.0],
        [0.5, 0.8],
        split_name="validation",
    )
    assert frozen.threshold == 0.5
    assert frozen.selected_on == "validation"
    assert frozen.frozen is True
    with pytest.raises(ValidationError):
        frozen.threshold = 0.8
    with pytest.raises(ValueError, match="validation-only"):
        calibrate_anomaly_threshold(
            ["NORMAL", "ANOMALY"],
            [0.1, 0.9],
            [0.5],
            split_name="test",
        )
    test_annotations = [
        _annotation("test-normal", AnomalyAnnotationLabel.NORMAL, split="test"),
        _annotation(
            "test-anomaly",
            AnomalyAnnotationLabel.ANOMALY,
            anomaly_type=AnomalyType.VALUE_OUTLIER,
            anomaly_domain=AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY,
            split="test",
        ),
    ]
    report = evaluate_anomaly_test(
        test_annotations,
        {"test-normal": 0.1, "test-anomaly": 0.9},
        frozen,
        predicted_domains={"test-anomaly": AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY},
    )
    assert report.evaluation_status == "DATA_AVAILABLE"
    assert report.threshold == frozen.threshold
    assert report.calibration_status == "THRESHOLD_SELECTED_ON_VALIDATION"


def test_training_is_blocked_without_validated_data_and_creates_no_artifact():
    artifact_root = Path(__file__).resolve().parents[1] / "artifacts"
    anomaly_artifacts_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifact_root.glob("*anomaly*.json")
    }
    direct = AnomalyDetector().fit(training_data=[])
    command = train_anomaly_detector()
    assert direct == command
    assert command.status == "TRAINING_BLOCKED_NO_VALIDATED_ANOMALY_DATA"
    assert command.artifact_created is False
    assert command.reason_codes == ["NO_VALIDATED_ANOMALY_GROUND_TRUTH"]
    assert not list(artifact_root.glob("*anomaly*.joblib"))
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifact_root.glob("*anomaly*.json")
    } == anomaly_artifacts_before


def test_artifact_governance_requires_local_project_provenance(local_tmp_path):
    artifact = local_tmp_path / "anomaly_v1.joblib"
    artifact.write_bytes(b"UNIT_TEST_ONLY_PROJECT_TRAINED_PLACEHOLDER")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = ArtifactMetadata(
        artifact_name=artifact.name,
        artifact_version="anomaly-v1",
        sha256=digest,
        training_dataset_hash="d" * 64,
        feature_version="anomaly-features-v1",
        preprocessing_version="statistical-anomaly-baseline-v1-example",
        training_timestamp=START + timedelta(days=1),
        random_seed=42,
        framework_versions={"scikit-learn": "test-version"},
        intended_component="anomaly_detector",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    manifest = ArtifactManifest(
        manifest_version="1.0",
        schema_version="1.0",
        policy_status="SCAFFOLD_ONLY",
        runtime_downloads_allowed=False,
        artifacts=[metadata],
    )
    provenance = AnomalyArtifactProvenance(
        artifact_name=artifact.name,
        model_version="anomaly-v1",
        model_family="ISOLATION_FOREST",
        dataset_hash="d" * 64,
        feature_version="anomaly-features-v1",
        baseline_version="statistical-anomaly-baseline-v1-example",
        library_version="test-version",
        random_seed=42,
        artifact_hash=digest,
        training_start_at=START,
        training_end_at=START + timedelta(days=1),
        station_scope=["station-1"],
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    assert (
        authorize_anomaly_artifact(artifact, provenance, manifest) == artifact.resolve()
    )
    with pytest.raises(ValueError, match="remote anomaly artifacts"):
        authorize_anomaly_artifact(
            "https://example.invalid/model.joblib", provenance, manifest
        )
    with pytest.raises(ValueError, match="remote anomaly artifacts"):
        authorize_anomaly_artifact(
            r"\\example.invalid\share\model.joblib", provenance, manifest
        )
    with pytest.raises(ValueError, match="provenance is required"):
        authorize_anomaly_artifact(artifact, None, manifest)
    with pytest.raises(ValueError, match="baseline version"):
        authorize_anomaly_artifact(
            artifact,
            provenance.model_copy(update={"baseline_version": "wrong-baseline"}),
            manifest,
        )


def test_inference_is_deterministic_and_never_outputs_a_fake_probability():
    value = _window([1.0] * 7 + [50.0])
    first = AnomalyDetector().predict(value)
    second = AnomalyDetector().predict(value)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.status is PredictionStatus.HEURISTIC_ONLY
    assert first.score_type == STATISTICAL_OUTLIER_SCORE
    assert first.score is not None and first.score > 1.0
    assert first.calibration_status is CalibrationStatus.NOT_CALIBRATED
    assert not hasattr(first, "probability")


@pytest.mark.parametrize("observation_count", [100, 1_000, 10_000])
def test_local_benchmark_separates_feature_fit_score_and_inference_stages(
    observation_count,
):
    result = benchmark_anomaly_pipeline(_window([1.0] * observation_count))
    assert result.observation_count == observation_count
    assert result.feature_computation_seconds >= 0.0
    assert result.baseline_fitting_seconds >= 0.0
    assert result.baseline_scoring_seconds >= 0.0
    assert result.detector_inference_seconds >= 0.0
    assert result.benchmark_scope == "LOCAL_PREPROCESSING_AND_INFERENCE_ONLY"


def test_phase9_source_has_no_pretrained_external_api_database_or_network_imports():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "anomaly_artifacts.py",
        root / "components" / "anomaly_detection.py",
        root / "components" / "anomaly_features.py",
        root / "data" / "anomaly_annotations.py",
        root / "training" / "train_anomaly_detector.py",
    ]
    prohibited_roots = {
        "anthropic",
        "asyncpg",
        "httpx",
        "openai",
        "redis",
        "requests",
        "sentence_transformers",
        "socket",
        "sqlalchemy",
        "torchvision",
        "transformers",
        "urllib",
    }
    prohibited_calls = {
        "from_pretrained",
        "hf_hub_download",
        "load_state_dict_from_url",
        "snapshot_download",
        "urlopen",
    }
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                modules = []
            for module in modules:
                if module.split(".")[0] in prohibited_roots:
                    violations.append(f"{path.name}: import {module}")
                if module.startswith(("app.db", "app.models")):
                    violations.append(f"{path.name}: import {module}")
            if isinstance(node, ast.Call):
                call_name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if call_name in prohibited_calls:
                    violations.append(f"{path.name}: call {call_name}")
    assert violations == []


def test_contract_supports_all_required_missing_states_and_no_learned_artifact():
    assert {item.value for item in MissingDataState} == {
        "MISSING_INPUT",
        "SEASONALLY_UNAVAILABLE",
        "SENSOR_GAP",
        "UNKNOWN",
    }
    assert {item.value for item in AnomalyType} == {
        "VALUE_OUTLIER",
        "RATE_OF_CHANGE",
        "PERSISTENT_DEVIATION",
        "MISSINGNESS_PATTERN",
        "UNCERTAIN",
    }
    assert StatisticalAnomalyBaseline.model_fields["baseline_name"].default == (
        STATISTICAL_ANOMALY_BASELINE
    )
