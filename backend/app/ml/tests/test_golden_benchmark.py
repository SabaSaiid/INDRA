"""Phase 12 synthetic golden, determinism, resource, and benchmark gates."""

from __future__ import annotations

import gc
import hashlib
import json
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

import app.ml.components.duplicate_matching as duplicate_module
import app.ml.components.nlp_classifier as nlp_module
from app.ml import anomaly_artifacts, image_artifacts
from app.ml.components.duplicate_features import (
    feature_state_sha256,
    load_feature_state,
)
from app.ml.components.duplicate_matching import DuplicateMatcher
from app.ml.components.event_detection import transition_event
from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact
from app.ml.config import (
    DEFAULT_DUPLICATE_MATCHING_CONFIG,
    DEFAULT_NLP_CLASSIFIER_CONFIG,
    get_ml_config,
    load_artifact_manifest,
)
from app.ml.contracts import (
    EventLifecycleStatus,
    PredictionStatus,
    ReportInput,
    SingleReportEventCandidate,
    UnifiedMLResult,
)
from app.ml.golden import (
    execute_golden_scenario,
    load_golden_scenarios,
    run_local_performance_benchmark,
    validate_golden_scenario,
)
from app.ml.golden.benchmark import (
    BENCHMARK_COMPONENTS,
    LocalPerformanceBenchmark,
)
from app.ml.inference.engine import InferenceEngine
from app.ml.models.anomaly_window_model import ScratchDualLogisticArtifact
from app.ml.release_gate import scan_new_ml_policy
from app.ml.training.event_validation import (
    DEFAULT_EVENT_ARTIFACT_PATH,
    load_event_development_artifact,
)

ML_ROOT = Path(__file__).resolve().parents[1]
RECORDED_BENCHMARK_PATH = (
    ML_ROOT / "golden" / "fixtures" / "golden_benchmark_results.json"
)
SUITE = load_golden_scenarios()
SCENARIO_IDS = (
    "SCENARIO_01_SINGLE_ORDINARY_REPORT",
    "SCENARIO_02_MULTIPLE_RELATED_REPORTS",
    "SCENARIO_03_DISTINCT_EVENTS",
    "SCENARIO_04_UNION_FIND_BRIDGE",
    "SCENARIO_05_DUPLICATE_FLOOD_REPORTS",
    "SCENARIO_06_CONTRADICTORY_REPORT",
    "SCENARIO_07_IMAGE_ABSENT",
    "SCENARIO_08_ANOMALY_HISTORY_INSUFFICIENT",
    "SCENARIO_09_VALID_ANOMALOUS_WEATHER_SERIES",
    "SCENARIO_10_MISSING_INVALID_WEATHER_DATA",
)
INVARIANT_NAMES = {
    "DUPLICATE_NE_FAKE",
    "ANOMALY_NE_FALSE_REPORT",
    "EVENT_NE_NLP_CLASSIFICATION",
    "RISK_SCORE_NE_PROBABILITY",
    "HEURISTIC_CONFIDENCE_NE_CALIBRATED_PROBABILITY",
    "MISSING_INFERENCE_NE_ZERO_SCORE",
    "IMAGE_EVIDENCE_NE_AUTHENTICITY_PROOF",
    "SINGLE_REPORT_NE_CONFIRMED_EVENT",
}


def _scenario(scenario_id: str):
    return next(item for item in SUITE.scenarios if item.scenario_id == scenario_id)


def _resource_reports(count: int) -> list[ReportInput]:
    started_at = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    return [
        ReportInput(
            report_id=UUID(int=13_000 + index),
            text=f"Synthetic resource regression flood report {index:03d}",
            occurred_at=started_at + timedelta(minutes=index),
            latitude=25.5941,
            longitude=85.1376,
            source_type="TEST_FIXTURE",
            source_metadata={
                "fixture_status": "TEST_FIXTURE_ONLY",
                "data_origin": "SYNTHETIC",
                "validation_scope": "NOT_PRODUCTION_DATA",
            },
        )
        for index in range(count)
    ]


def test_golden_schema_provenance_and_required_scenario_inventory():
    raw = json.loads(
        (ML_ROOT / "golden" / "fixtures" / "golden_scenarios_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert SUITE.suite_version == "golden-suite-v1"
    assert SUITE.schema_version == "1.0"
    assert SUITE.fixture_status == "TEST_FIXTURE_ONLY"
    assert SUITE.data_origin == "SYNTHETIC"
    assert SUITE.validation_scope == (
        "ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION"
    )
    assert tuple(item.scenario_id for item in SUITE.scenarios) == SCENARIO_IDS
    assert len(raw["scenarios"]) == 10
    for scenario, payload in zip(SUITE.scenarios, raw["scenarios"], strict=True):
        assert scenario.scenario_version == "golden-scenario-v1"
        assert scenario.schema_version == "1.0"
        assert scenario.creation_timestamp.tzinfo is not None
        assert scenario.fixture_status == "TEST_FIXTURE_ONLY"
        assert scenario.data_origin == "SYNTHETIC"
        assert scenario.validation_scope == "NOT_PRODUCTION_DATA"
        assert len(scenario.fixture_hash) == 64
        canonical = scenario.model_dump(mode="json", exclude={"fixture_hash"})
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert hashlib.sha256(encoded).hexdigest() == payload["fixture_hash"]


@pytest.mark.parametrize("scenario", SUITE.scenarios, ids=SCENARIO_IDS)
def test_golden_scenario_expected_outputs(scenario):
    execution = validate_golden_scenario(scenario)
    assert execution.scenario_id == scenario.scenario_id
    for result in execution.unified_results.values():
        assert result.model_versions == {
            "nlp_classifier": "nlp-classifier-v1",
            "event_detector": "event-grouping-v2",
            "fake_detector": "rule-based-credibility-baseline-v1",
            "anomaly_detector": "statistical-anomaly-detector-v1",
        }
        assert result.feature_versions == {
            "nlp_classifier": "nlp-features-v1",
            "duplicate_matcher": "duplicate-features-v1",
            "event_detector": "event-features-v1",
            "fake_detector": "credibility-risk-features-v1",
            "image_analyzer": "image-validation-features-v1",
            "anomaly_detector": "anomaly-features-v1",
        }
        assert (
            result.text_prediction.preprocessing_version,
            result.duplicate_prediction.preprocessing_version,
            result.event_prediction.preprocessing_version,
            result.credibility_prediction.preprocessing_version,
            result.image_prediction.preprocessing_version,
            result.anomaly_prediction.preprocessing_version,
        ) == (
            "nlp-text-normalization-v1",
            "duplicate-text-normalization-v1",
            None,
            "credibility-risk-normalization-v1",
            "image-preprocessing-v1",
            None,
        )


@pytest.mark.parametrize("scenario", SUITE.scenarios, ids=SCENARIO_IDS)
def test_golden_determinism_runs_every_scenario_twice(scenario):
    first = validate_golden_scenario(scenario)
    second = validate_golden_scenario(scenario)
    assert first.semantic_payload() == second.semantic_payload()
    for report_id in first.unified_results:
        first_result = first.unified_results[report_id]
        second_result = second.unified_results[report_id]
        assert first_result == second_result
        for field_name in (
            "text_prediction",
            "duplicate_prediction",
            "event_prediction",
            "credibility_prediction",
            "image_prediction",
            "anomaly_prediction",
        ):
            first_prediction = getattr(first_result, field_name)
            second_prediction = getattr(second_result, field_name)
            assert first_prediction.reason_codes == second_prediction.reason_codes
            assert first_prediction.evidence == second_prediction.evidence
            assert first_prediction.status is second_prediction.status


@pytest.mark.parametrize("scenario", SUITE.scenarios, ids=SCENARIO_IDS)
def test_golden_serialization_round_trip_is_exact(scenario):
    execution = execute_golden_scenario(scenario)
    for result in execution.unified_results.values():
        serialized = result.model_dump_json()
        restored = UnifiedMLResult.model_validate_json(serialized)
        assert restored == result
        assert restored.model_dump(mode="json") == result.model_dump(mode="json")


def test_single_report_event_is_only_a_candidate_and_confirmation_is_human_gated():
    execution = validate_golden_scenario(
        _scenario("SCENARIO_01_SINGLE_ORDINARY_REPORT")
    )
    result = next(iter(execution.unified_results.values()))
    prediction = result.event_prediction
    candidate = prediction.candidate_event
    assert prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert prediction.confidence is None
    assert candidate is not None
    assert candidate.report_ids == [result.report_id]
    assert candidate.lifecycle_state == "CANDIDATE"
    assert candidate.score_type == "EVENT_EVIDENCE_SCORE"
    assert "NOT_CONFIRMED_EVENT" in prediction.reason_codes

    invalid_payload = candidate.model_dump(mode="json")
    invalid_payload["lifecycle_state"] = "CONFIRMED"
    with pytest.raises(ValidationError):
        SingleReportEventCandidate.model_validate(invalid_payload)

    assert execution.event_result is not None
    with pytest.raises(ValueError, match="explicit human_confirmed=True"):
        transition_event(
            execution.event_result.candidates[0],
            EventLifecycleStatus.CONFIRMED,
        )


def test_cross_component_semantic_invariants_are_explicit_and_true():
    for scenario in SUITE.scenarios:
        checks = execute_golden_scenario(scenario).invariant_checks
        assert set(checks) == INVARIANT_NAMES
        assert all(checks.values())


def test_golden_artifacts_are_manifest_authorized_hashed_and_structurally_valid():
    manifest = load_artifact_manifest()
    assert manifest.runtime_downloads_allowed is False
    assert {item.intended_component for item in manifest.artifacts} == {
        "nlp_classifier",
        "duplicate_matcher",
        "event_detector",
        "fake_detector",
        "image_analyzer",
        "anomaly_detector",
    }

    nlp_path = DEFAULT_NLP_CLASSIFIER_CONFIG.artifact_path
    nlp_artifact = load_nlp_artifact(nlp_path)
    nlp_entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "nlp_classifier"
    )
    assert hashlib.sha256(nlp_path.read_bytes()).hexdigest() == nlp_entry.sha256
    assert nlp_artifact.n_features == (
        len(nlp_artifact.char_space.vocabulary)
        + len(nlp_artifact.word_space.vocabulary)
    )
    assert len(nlp_artifact.classifier.coefficients) == len(nlp_artifact.classes)

    duplicate_path = DEFAULT_DUPLICATE_MATCHING_CONFIG.feature_state_path
    duplicate_state = load_feature_state(duplicate_path)
    duplicate_entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "duplicate_matcher"
    )
    assert hashlib.sha256(duplicate_path.read_bytes()).hexdigest() == (
        duplicate_entry.sha256
    )
    normalized = "synthetic flood water near road"
    assert duplicate_state.char_space.transform(normalized) == (
        duplicate_state.char_space.transform(normalized)
    )
    assert duplicate_state.word_space.transform(normalized) == (
        duplicate_state.word_space.transform(normalized)
    )

    event_artifact, event_config = load_event_development_artifact()
    event_entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "event_detector"
    )
    assert hashlib.sha256(DEFAULT_EVENT_ARTIFACT_PATH.read_bytes()).hexdigest() == (
        event_entry.sha256
    )
    assert event_artifact.artifact_kind == (
        "DETERMINISTIC_CONFIGURATION_NOT_LEARNED_MODEL"
    )
    assert event_config.algorithm_version == "event-grouping-v2"

    image_path = ML_ROOT / "artifacts" / "image_model_v1.pt"
    image_entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "image_analyzer"
    )
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == image_entry.sha256

    anomaly_path = ML_ROOT / "artifacts" / "anomaly_model_v1.json"
    anomaly_entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "anomaly_detector"
    )
    anomaly_model = ScratchDualLogisticArtifact.model_validate_json(
        anomaly_path.read_text(encoding="utf-8")
    )
    assert hashlib.sha256(anomaly_path.read_bytes()).hexdigest() == (
        anomaly_entry.sha256
    )
    assert anomaly_model.model_family == "LOCAL_SCRATCH_DUAL_LOGISTIC"
    assert anomaly_model.network_access is False


def test_default_paths_do_not_load_opt_in_learned_artifacts(
    monkeypatch,
):
    def fail_placeholder_load(*_args, **_kwargs):
        raise AssertionError("unavailable learned artifact loader was called")

    monkeypatch.setattr(
        image_artifacts,
        "load_image_state_dict",
        fail_placeholder_load,
    )
    monkeypatch.setattr(
        anomaly_artifacts,
        "authorize_anomaly_artifact",
        fail_placeholder_load,
    )
    manifest = load_artifact_manifest()
    assert any(
        item.intended_component == "image_analyzer"
        for item in manifest.artifacts
    )
    assert any(
        item.intended_component == "anomaly_detector"
        for item in manifest.artifacts
    )
    assert {
        item.name for item in (ML_ROOT / "artifacts").glob("*.pt")
    } == {"image_model_v1.pt"}

    engine = InferenceEngine()
    image_execution = validate_golden_scenario(
        _scenario("SCENARIO_07_IMAGE_ABSENT"),
        execute_golden_scenario(
            _scenario("SCENARIO_07_IMAGE_ABSENT"),
            engine=engine,
        ),
    )
    image_result = next(iter(image_execution.unified_results.values()))
    assert image_result.image_prediction.status is PredictionStatus.NOT_APPLICABLE
    assert image_result.image_prediction.probabilities == {}

    anomaly_execution = validate_golden_scenario(
        _scenario("SCENARIO_08_ANOMALY_HISTORY_INSUFFICIENT"),
        execute_golden_scenario(
            _scenario("SCENARIO_08_ANOMALY_HISTORY_INSUFFICIENT"),
            engine=engine,
        ),
    )
    anomaly_result = next(iter(anomaly_execution.unified_results.values()))
    assert (
        anomaly_result.anomaly_prediction.status is PredictionStatus.INSUFFICIENT_DATA
    )
    assert anomaly_result.anomaly_prediction.score is None


def test_golden_resource_regression_reuses_artifacts_and_does_not_retain_results(
    monkeypatch,
):
    nlp_load_count = 0
    duplicate_load_count = 0
    vectorization_count = 0
    real_nlp_loader = nlp_module.load_nlp_artifact
    real_duplicate_loader = duplicate_module.load_feature_state
    real_vectorize = nlp_module._vectorize

    def counted_nlp_loader(*args, **kwargs):
        nonlocal nlp_load_count
        nlp_load_count += 1
        return real_nlp_loader(*args, **kwargs)

    def counted_duplicate_loader(*args, **kwargs):
        nonlocal duplicate_load_count
        duplicate_load_count += 1
        return real_duplicate_loader(*args, **kwargs)

    def counted_vectorize(*args, **kwargs):
        nonlocal vectorization_count
        vectorization_count += 1
        return real_vectorize(*args, **kwargs)

    monkeypatch.setattr(nlp_module, "load_nlp_artifact", counted_nlp_loader)
    monkeypatch.setattr(
        duplicate_module, "load_feature_state", counted_duplicate_loader
    )
    classifier = NLPClassifier()
    matcher = DuplicateMatcher()
    probe = _resource_reports(1)[0]
    classifier.predict(probe)
    classifier.predict(probe)
    matcher.predict(probe)
    matcher.predict(probe)
    assert nlp_load_count == 1
    assert duplicate_load_count == 1

    monkeypatch.setattr(nlp_module, "_vectorize", counted_vectorize)
    engine = InferenceEngine(
        nlp_classifier=classifier,
        duplicate_matcher=matcher,
    )
    component_ids = {name: id(getattr(engine, name)) for name in BENCHMARK_COMPONENTS}
    state_hash = feature_state_sha256(matcher.feature_state)
    result_references = []
    for report in _resource_reports(100):
        current = engine.analyze(report)
        result_references.append(weakref.ref(current))
        del current

    gc.collect()
    assert vectorization_count == 100
    assert nlp_load_count == 1
    assert duplicate_load_count == 1
    assert classifier._artifact is not None
    assert feature_state_sha256(matcher.feature_state) == state_hash
    assert component_ids == {
        name: id(getattr(engine, name)) for name in BENCHMARK_COMPONENTS
    }
    assert all(reference() is None for reference in result_references)


def test_golden_performance_regression_uses_recorded_gross_local_ceilings():
    recorded = LocalPerformanceBenchmark.model_validate_json(
        RECORDED_BENCHMARK_PATH.read_text(encoding="utf-8")
    )
    current = run_local_performance_benchmark(
        recorded_at=datetime(2026, 9, 22, tzinfo=timezone.utc)
    )
    assert [item.report_count for item in current.measurements] == [1, 10, 100]
    assert all(
        item.production_throughput_claim is False for item in current.measurements
    )
    assert current.resource_observations.nlp_artifact_identity_stable is True
    assert current.resource_observations.duplicate_feature_state_identity_stable is True
    assert [item.semantic_output_sha256 for item in current.measurements] == [
        item.semantic_output_sha256 for item in recorded.measurements
    ]

    guard = recorded.regression_guard
    for actual, baseline in zip(
        current.artifact_loads,
        recorded.artifact_loads,
        strict=True,
    ):
        ceiling = max(
            guard.minimum_artifact_ceiling_seconds,
            baseline.load_seconds * guard.artifact_time_multiplier,
        )
        assert actual.load_seconds <= ceiling
        assert actual.sha256 == baseline.sha256
    for actual, baseline in zip(
        current.measurements,
        recorded.measurements,
        strict=True,
    ):
        total_ceiling = max(
            guard.minimum_total_ceiling_seconds,
            baseline.total_inference_seconds * guard.total_time_multiplier,
        )
        assert actual.total_inference_seconds <= total_ceiling
        assert tuple(actual.per_component_seconds) == BENCHMARK_COMPONENTS
        for component in BENCHMARK_COMPONENTS:
            component_ceiling = max(
                guard.minimum_component_ceiling_seconds,
                baseline.per_component_seconds[component]
                * guard.component_time_multiplier,
            )
            assert actual.per_component_seconds[component] <= component_ceiling


def test_golden_policy_regression_blocks_network_and_external_model_paths(
    monkeypatch,
):
    policy = scan_new_ml_policy()
    assert policy.compliant is True
    assert policy.violations == []
    config = get_ml_config()
    assert config.allow_runtime_downloads is False
    assert config.allow_external_inference is False

    def reject_network(*_args, **_kwargs):
        raise AssertionError("network access attempted during golden execution")

    monkeypatch.setattr("socket.socket", reject_network)
    for scenario in SUITE.scenarios:
        validate_golden_scenario(scenario)
