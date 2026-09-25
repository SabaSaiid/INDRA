"""Execution and assertion helpers for synthetic golden regression scenarios."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ml.components.anomaly_detection import AnomalyDetector
from app.ml.components.anomaly_features import validate_anomaly_window
from app.ml.components.event_detection import EventDetector, observation_from_report
from app.ml.contracts import (
    AnomalyInputWindow,
    AnomalyPrediction,
    AnomalyWindowValidationResult,
    EventDetectionResult,
    PredictionStatus,
    UnifiedMLResult,
)
from app.ml.golden.schema import GoldenScenario, ReasonCodeExpectation
from app.ml.inference.engine import InferenceEngine


COMPONENT_RESULT_FIELDS = (
    "text_prediction",
    "duplicate_prediction",
    "event_prediction",
    "credibility_prediction",
    "image_prediction",
    "anomaly_prediction",
)
COMPONENT_NAMES = (
    "NLP",
    "DUPLICATE",
    "EVENT",
    "CREDIBILITY",
    "IMAGE",
    "ANOMALY",
)


class GoldenExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    scenario_id: str
    unified_results: dict[str, UnifiedMLResult]
    event_result: EventDetectionResult | None = None
    anomaly_prediction: AnomalyPrediction | None = None
    anomaly_validation: AnomalyWindowValidationResult | None = None
    invariant_checks: dict[str, bool] = Field(default_factory=dict)

    def semantic_payload(self) -> dict[str, Any]:
        event_payload = None
        if self.event_result is not None:
            event_payload = self.event_result.model_dump(
                mode="json",
                exclude={
                    "grouping_seconds",
                    "feature_extraction_seconds",
                    "total_seconds",
                },
            )
        return {
            "scenario_id": self.scenario_id,
            "unified_results": {
                key: value.model_dump(mode="json")
                for key, value in sorted(self.unified_results.items())
            },
            "event_result": event_payload,
            "anomaly_prediction": (
                self.anomaly_prediction.model_dump(mode="json")
                if self.anomaly_prediction is not None
                else None
            ),
            "anomaly_validation": (
                self.anomaly_validation.model_dump(mode="json")
                if self.anomaly_validation is not None
                else None
            ),
            "invariant_checks": dict(sorted(self.invariant_checks.items())),
        }


def _anomaly_window(scenario: GoldenScenario) -> AnomalyInputWindow | None:
    specification = scenario.input.anomaly_window
    if specification is None:
        return None
    observations = [item.to_contract() for item in specification.observations]
    present_timestamps = [
        item.observed_at for item in observations if item.observed_at is not None
    ]
    return AnomalyInputWindow(
        station_id=specification.station_id,
        observations=observations,
        start_at=min(present_timestamps) if present_timestamps else None,
        end_at=max(present_timestamps) if present_timestamps else None,
        station_metadata={
            "fixture_status": "TEST_FIXTURE_ONLY",
            "data_origin": "SYNTHETIC",
            "validation_scope": "NOT_PRODUCTION_DATA",
        },
    )


def execute_golden_scenario(
    scenario: GoldenScenario,
    *,
    engine: InferenceEngine | None = None,
) -> GoldenExecution:
    """Execute all applicable local paths without asserting real-world quality."""

    selected_engine = engine or InferenceEngine()
    reports_by_id = {str(report.report_id): report for report in scenario.input.reports}
    unified_results = {
        report_id: selected_engine.analyze(report)
        for report_id, report in reports_by_id.items()
    }

    event_result = None
    if scenario.input.event_batch_report_ids:
        observations = []
        for report_id in scenario.input.event_batch_report_ids:
            key = str(report_id)
            report = reports_by_id[key]
            result = unified_results[key]
            observations.append(
                observation_from_report(
                    report,
                    text_prediction=result.text_prediction,
                    duplicate_prediction=result.duplicate_prediction,
                    image_prediction=result.image_prediction,
                    credibility_prediction=result.credibility_prediction,
                    anomaly_prediction=result.anomaly_prediction,
                )
            )
        event_result = EventDetector().detect(observations)

    window = _anomaly_window(scenario)
    anomaly_validation = None
    anomaly_prediction = None
    if window is not None:
        anomaly_validation = validate_anomaly_window(window)
        anomaly_prediction = AnomalyDetector().predict(window)

    execution = GoldenExecution(
        scenario_id=scenario.scenario_id,
        unified_results=unified_results,
        event_result=event_result,
        anomaly_prediction=anomaly_prediction,
        anomaly_validation=anomaly_validation,
    )
    execution.invariant_checks = cross_component_invariants(execution)
    return execution


def cross_component_invariants(execution: GoldenExecution) -> dict[str, bool]:
    """Return explicit semantic separations that must hold across components."""

    results = list(execution.unified_results.values())
    duplicate_not_fake = all(
        not (
            result.duplicate_prediction.is_duplicate is True
            and result.credibility_prediction.label in {"FAKE", "FALSE_REPORT"}
        )
        for result in results
    )
    anomaly_not_false_report = all(
        result.credibility_prediction.label != "FALSE_REPORT"
        for result in results
    )
    event_not_nlp = all(
        result.event_prediction.candidate_event is not None
        and result.event_prediction.model_version
        != result.text_prediction.model_version
        and result.event_prediction.reason_codes
        != result.text_prediction.reason_codes
        for result in results
    )
    risk_not_probability = all(
        result.credibility_prediction.confidence is None
        and result.credibility_prediction.score is None
        and result.credibility_prediction.calibration_status.value
        in {"NOT_CALIBRATED", "CALIBRATION_UNAVAILABLE"}
        for result in results
    )
    heuristic_not_probability = all(
        result.event_prediction.confidence is None
        and (
            result.event_prediction.candidate_event is None
            or result.event_prediction.candidate_event.score_type
            == "EVENT_EVIDENCE_SCORE"
        )
        for result in results
    ) and (
        execution.event_result is None
        or all(
            "EVENT_EVIDENCE_SCORE_NOT_CALIBRATED" in candidate.evidence
            and "PROVISIONAL_EVENT_CONFIDENCE" in candidate.evidence
            for candidate in execution.event_result.candidates
        )
    )
    missing_not_zero = all(
        (
            result.duplicate_prediction.status
            not in {
                PredictionStatus.NOT_APPLICABLE,
                PredictionStatus.INSUFFICIENT_DATA,
            }
            or result.duplicate_prediction.similarity is None
        )
        and (
            result.anomaly_prediction.status
            not in {
                PredictionStatus.NOT_APPLICABLE,
                PredictionStatus.INSUFFICIENT_DATA,
            }
            or result.anomaly_prediction.score is None
        )
        for result in results
    )
    image_not_authenticity = all(
        "AUTHENTIC" not in result.image_prediction.reason_codes
        and "FAKE" not in result.image_prediction.reason_codes
        for result in results
    )
    single_report_not_confirmed = all(
        result.event_prediction.candidate_event is None
        or result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"
        for result in results
    ) and (
        execution.event_result is None
        or all(
            candidate.status.value != "CONFIRMED"
            for candidate in execution.event_result.candidates
        )
    )
    return {
        "DUPLICATE_NE_FAKE": duplicate_not_fake,
        "ANOMALY_NE_FALSE_REPORT": anomaly_not_false_report,
        "EVENT_NE_NLP_CLASSIFICATION": event_not_nlp,
        "RISK_SCORE_NE_PROBABILITY": risk_not_probability,
        "HEURISTIC_CONFIDENCE_NE_CALIBRATED_PROBABILITY": heuristic_not_probability,
        "MISSING_INFERENCE_NE_ZERO_SCORE": missing_not_zero,
        "IMAGE_EVIDENCE_NE_AUTHENTICITY_PROOF": image_not_authenticity,
        "SINGLE_REPORT_NE_CONFIRMED_EVENT": single_report_not_confirmed,
    }


def _component_statuses(result: UnifiedMLResult) -> dict[str, PredictionStatus]:
    return {
        "NLP": result.text_prediction.status,
        "DUPLICATE": result.duplicate_prediction.status,
        "EVENT": result.event_prediction.status,
        "CREDIBILITY": result.credibility_prediction.status,
        "IMAGE": result.image_prediction.status,
        "ANOMALY": result.anomaly_prediction.status,
    }


def _reason_codes(execution: GoldenExecution, target: str) -> list[str]:
    if target == "anomaly_prediction":
        return (
            execution.anomaly_prediction.reason_codes
            if execution.anomaly_prediction is not None
            else []
        )
    if target == "anomaly_validation":
        if execution.anomaly_validation is None:
            return []
        return [item.code for item in execution.anomaly_validation.errors]
    prefix, report_id, component = target.split(":", maxsplit=2)
    if prefix != "report":
        raise AssertionError(f"unknown reason-code target: {target}")
    result = execution.unified_results[report_id]
    prediction = {
        "nlp": result.text_prediction,
        "duplicate": result.duplicate_prediction,
        "event": result.event_prediction,
        "credibility": result.credibility_prediction,
        "image": result.image_prediction,
        "anomaly": result.anomaly_prediction,
    }[component]
    return prediction.reason_codes


def _assert_reason_codes(
    actual: list[str],
    expected: ReasonCodeExpectation,
    target: str,
) -> None:
    if expected.match == "EXACT":
        assert actual == expected.codes, (target, actual, expected.codes)
    else:
        assert all(code in actual for code in expected.codes), (
            target,
            actual,
            expected.codes,
        )


def _assert_no_fabricated_scores(result: UnifiedMLResult) -> None:
    if result.duplicate_prediction.status in {
        PredictionStatus.NOT_APPLICABLE,
        PredictionStatus.INSUFFICIENT_DATA,
    }:
        assert result.duplicate_prediction.similarity is None
    if result.image_prediction.status in {
        PredictionStatus.NOT_APPLICABLE,
        PredictionStatus.OFFLINE,
    }:
        assert result.image_prediction.confidence is None
        assert result.image_prediction.probabilities == {}
    if result.anomaly_prediction.status in {
        PredictionStatus.NOT_APPLICABLE,
        PredictionStatus.INSUFFICIENT_DATA,
    }:
        assert result.anomaly_prediction.score is None
    assert result.event_prediction.confidence is None
    assert result.credibility_prediction.confidence is None
    assert result.credibility_prediction.score is None


def _assert_unified_envelope(result: UnifiedMLResult) -> None:
    """Verify exact envelope shape, version maps, and warning/error semantics."""

    component_predictions = (
        ("nlp_classifier", result.text_prediction),
        ("duplicate_matcher", result.duplicate_prediction),
        ("event_detector", result.event_prediction),
        ("fake_detector", result.credibility_prediction),
        ("image_analyzer", result.image_prediction),
        ("anomaly_detector", result.anomaly_prediction),
    )
    assert tuple(result.model_dump(mode="json")) == tuple(
        UnifiedMLResult.model_fields
    )
    assert result.model_versions == {
        name: prediction.model_version
        for name, prediction in component_predictions
        if prediction.model_version is not None
    }
    assert result.feature_versions == {
        name: prediction.feature_version
        for name, prediction in component_predictions
        if prediction.feature_version is not None
    }
    for _, prediction in component_predictions:
        for version in (
            prediction.model_version,
            prediction.feature_version,
            prediction.preprocessing_version,
        ):
            assert version is None or version.strip()
    assert result.warnings == [
        warning
        for _, prediction in component_predictions
        for warning in prediction.warnings
    ]
    assert result.errors == [
        f"{type(prediction).__name__}: {prediction.reason_codes}"
        for _, prediction in component_predictions
        if prediction.status is PredictionStatus.ERROR
    ]


def validate_golden_scenario(
    scenario: GoldenScenario,
    execution: GoldenExecution | None = None,
) -> GoldenExecution:
    """Assert one scenario's stable engineering-regression expectations."""

    execution = execution or execute_golden_scenario(scenario)
    structural = scenario.expected_structural_properties
    assert len(execution.unified_results) == structural.unified_result_count
    assert tuple(COMPONENT_NAMES) == structural.component_order
    assert tuple(COMPONENT_RESULT_FIELDS) == tuple(
        name
        for name in UnifiedMLResult.model_fields
        if name in COMPONENT_RESULT_FIELDS
    )

    for report_id, expected in scenario.expected_component_statuses.items():
        result = execution.unified_results[report_id]
        assert str(result.report_id) == report_id
        assert result.schema_version == structural.schema_version
        assert _component_statuses(result) == expected.model_dump()
        _assert_unified_envelope(result)
        round_trip = UnifiedMLResult.model_validate_json(result.model_dump_json())
        assert round_trip == result
        _assert_no_fabricated_scores(result)
        candidate = result.event_prediction.candidate_event
        assert candidate is not None
        assert candidate.report_ids == [result.report_id]
        assert candidate.lifecycle_state == "CANDIDATE"
        assert candidate.feature_version == result.event_prediction.feature_version
        assert candidate.algorithm_version == result.event_prediction.model_version

    for target, expected in scenario.expected_reason_codes.items():
        _assert_reason_codes(_reason_codes(execution, target), expected, target)

    if scenario.expected_event_structure is not None:
        assert execution.event_result is not None
        expected = scenario.expected_event_structure
        assert execution.event_result.status is expected.detection_status
        assert len(execution.event_result.candidates) == expected.candidate_count
        assert sorted(
            candidate.report_count for candidate in execution.event_result.candidates
        ) == sorted(expected.group_sizes)
        assert sorted(
            candidate.independent_report_count
            for candidate in execution.event_result.candidates
        ) == sorted(expected.independent_report_counts)
        assert sorted(
            candidate.status.value for candidate in execution.event_result.candidates
        ) == sorted(expected.lifecycle_states)

    if scenario.expected_duplicate_relationship is not None:
        expected = scenario.expected_duplicate_relationship
        result = execution.unified_results[str(expected.report_id)]
        assert result.duplicate_prediction.is_duplicate is expected.is_duplicate
        assert result.duplicate_prediction.matched_report_id == expected.matched_report_id

    if scenario.expected_anomaly_outcome is not None:
        assert execution.anomaly_prediction is not None
        expected = scenario.expected_anomaly_outcome
        prediction = execution.anomaly_prediction
        assert prediction.status is expected.status
        assert prediction.anomaly_domain is expected.anomaly_domain
        assert prediction.is_anomaly is expected.is_anomaly
        assert (prediction.score is not None) is expected.score_present

    assert execution.invariant_checks
    assert all(execution.invariant_checks.values())
    return execution


__all__ = [
    "GoldenExecution",
    "cross_component_invariants",
    "execute_golden_scenario",
    "validate_golden_scenario",
]
