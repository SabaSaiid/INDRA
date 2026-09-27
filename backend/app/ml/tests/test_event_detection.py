from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.ml.components.event_detection import (
    EventDetector,
    build_event_candidate,
    compare_event_candidates,
    event_types_compatible,
    group_event_observations,
    merge_event_candidates,
    transition_event,
)
from app.ml.config import EventDetectorConfig
from app.ml.contracts import (
    DuplicatePrediction,
    EventDetectionStatus,
    EventLifecycleStatus,
    EventObservation,
    PredictionStatus,
    ReportInput,
    StationObservation,
    TextPrediction,
)
from app.ml.data.event_annotations import (
    EventAnnotationLabel,
    EventPairAnnotation,
    validate_event_annotation_leakage,
    validate_event_annotations,
)
from app.ml.evaluation.evaluate import evaluate_event_matching


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _uuid(number: int) -> UUID:
    return UUID(int=number)


def _observation(
    number: int,
    *,
    event_type: str = "URBAN_FLOOD",
    minutes: int = 0,
    latitude: float = 25.5941,
    longitude: float = 85.1376,
    source_type: str | None = None,
    duplicate_of: UUID | None = None,
    nlp_status: PredictionStatus = PredictionStatus.AVAILABLE,
    weather_value: float | None = None,
) -> EventObservation:
    report_id = _uuid(number)
    probabilities = {
        "URBAN_FLOOD": 0.025,
        "RIVER_BREACH": 0.025,
        "CLOUDBURST": 0.025,
        "CYCLONE_INUNDATION": 0.025,
        "NOT_RELEVANT": 0.025,
    }
    probabilities[event_type] = 0.9
    prediction = TextPrediction(
        status=nlp_status,
        label=event_type if nlp_status is PredictionStatus.AVAILABLE else None,
        probabilities=probabilities if nlp_status is PredictionStatus.AVAILABLE else {},
        model_version="nlp-classifier-v1" if nlp_status is PredictionStatus.AVAILABLE else None,
        evidence=["model_status=EVALUATED"] if nlp_status is PredictionStatus.AVAILABLE else [],
    )
    duplicate = DuplicatePrediction(
        status=PredictionStatus.AVAILABLE if duplicate_of else PredictionStatus.NOT_APPLICABLE,
        is_duplicate=duplicate_of is not None,
        matched_report_id=duplicate_of,
        reason_codes=["DUPLICATE_MATCH"] if duplicate_of else [],
    )
    weather = []
    if weather_value is not None:
        weather = [
            StationObservation(
                station_id="station-1",
                observed_at=NOW + timedelta(minutes=minutes),
                latitude=latitude,
                longitude=longitude,
                measurements={"rainfall_mm": weather_value},
            )
        ]
    return EventObservation(
        report_id=report_id,
        text_prediction=prediction,
        occurred_at=NOW + timedelta(minutes=minutes),
        latitude=latitude,
        longitude=longitude,
        source_type=source_type or f"SOURCE_{number}",
        duplicate_prediction=duplicate,
        weather_observations=weather,
    )


def test_case_a_same_location_time_and_type_forms_one_candidate_deterministically():
    observations = [_observation(1), _observation(2, minutes=5), _observation(3, minutes=10)]
    first = group_event_observations(observations)
    second = group_event_observations(observations)
    assert first.status is EventDetectionStatus.AVAILABLE
    assert len(first.candidates) == 1
    candidate = first.candidates[0]
    assert candidate.event_type == "URBAN_FLOOD"
    assert candidate.report_count == 3
    assert candidate.independent_report_count == 3
    assert candidate.status is EventLifecycleStatus.CANDIDATE
    assert "HEURISTIC_EVENT_TYPE_AGGREGATION" in candidate.evidence
    assert "EVENT_EVIDENCE_SCORE_NOT_CALIBRATED" in candidate.evidence
    assert first.candidates[0].model_dump() == second.candidates[0].model_dump()
    assert first.candidate_comparisons == second.candidate_comparisons
    assert first.candidate_comparisons > 0
    assert first.total_seconds is not None


def test_case_b_geographic_gate_forms_separate_candidates():
    result = group_event_observations(
        [_observation(1), _observation(2, latitude=25.6941)],
    )
    assert len(result.candidates) == 2


def test_case_c_temporal_gate_forms_separate_candidates():
    result = group_event_observations(
        [_observation(1), _observation(2, minutes=181)],
    )
    assert len(result.candidates) == 2


def test_transitive_spatial_bridge_cannot_exceed_cluster_diameter():
    config = EventDetectorConfig(spatial_radius_km=5.0)
    observations = [
        _observation(1, longitude=85.0000),
        _observation(2, longitude=85.0400),
        _observation(3, longitude=85.0800),
    ]
    result = group_event_observations(observations, config=config)
    assert sorted(candidate.report_count for candidate in result.candidates) == [1, 2]
    assert all(candidate.report_count < 3 for candidate in result.candidates)
    assert result.algorithm_version == "event-grouping-v2"
    assert any("transitive bridge" in warning for warning in result.warnings)


def test_transitive_temporal_bridge_cannot_exceed_cluster_span():
    observations = [
        _observation(1, minutes=0),
        _observation(2, minutes=120),
        _observation(3, minutes=240),
    ]
    result = group_event_observations(observations)
    assert sorted(candidate.report_count for candidate in result.candidates) == [1, 2]
    assert all(
        candidate.duration <= 180.0
        for candidate in result.candidates
    )


def test_case_d_type_compatibility_is_explicit_and_configurable():
    observations = [
        _observation(1, event_type="URBAN_FLOOD"),
        _observation(2, event_type="RIVER_BREACH", minutes=5),
    ]
    separate = group_event_observations(observations)
    assert len(separate.candidates) == 2
    assert event_types_compatible("URBAN_FLOOD", "RIVER_BREACH") is False

    compatible = EventDetectorConfig(
        compatible_event_type_rules={
            "URBAN_FLOOD": ("URBAN_FLOOD", "RIVER_BREACH"),
            "RIVER_BREACH": ("URBAN_FLOOD", "RIVER_BREACH"),
        }
    )
    combined = group_event_observations(observations, config=compatible)
    assert len(combined.candidates) == 1
    assert combined.candidates[0].event_type in {"URBAN_FLOOD", "RIVER_BREACH"}


def test_case_e_duplicate_reports_do_not_inflate_independent_evidence():
    duplicate_observations = [
        _observation(1, source_type="CITIZEN_APP"),
        _observation(2, source_type="CITIZEN_APP", minutes=1, duplicate_of=_uuid(1)),
    ]
    duplicate_candidate = group_event_observations(duplicate_observations).candidates[0]
    single_candidate = group_event_observations([_observation(1, source_type="CITIZEN_APP")]).candidates[0]
    assert duplicate_candidate.report_count == 2
    assert duplicate_candidate.independent_report_count == 1
    assert duplicate_candidate.features.duplicate_ratio == 1.0
    assert duplicate_candidate.event_confidence <= single_candidate.event_confidence


def test_case_f_single_report_is_low_provisional_candidate():
    candidate = group_event_observations([_observation(1)]).candidates[0]
    assert candidate.report_count == 1
    assert candidate.event_confidence is not None
    assert "BELOW_MINIMUM_REPORTS" in candidate.evidence
    assert candidate.warnings


def test_optional_weather_evidence_is_recorded_without_fabrication():
    result = group_event_observations([_observation(1, weather_value=10.0), _observation(2, minutes=5, weather_value=12.0)])
    assert result.candidates[0].features.weather_consistency is not None
    assert "WEATHER_EVIDENCE_UNAVAILABLE" not in result.candidates[0].evidence


def test_merge_requires_all_rules_and_lifecycle_confirmation_is_explicit():
    left = build_event_candidate([_observation(1)])
    right = build_event_candidate([_observation(2, minutes=5)])
    decision = compare_event_candidates(left, right)
    assert decision.should_merge is True
    merged = merge_event_candidates(left, right)
    assert merged.status is EventLifecycleStatus.MERGED
    assert merged.report_count == 2

    far = build_event_candidate([_observation(3, latitude=25.6941)])
    assert compare_event_candidates(left, far).should_merge is False
    with pytest.raises(ValueError, match="human_confirmed"):
        transition_event(left, EventLifecycleStatus.CONFIRMED)
    confirmed = transition_event(left, EventLifecycleStatus.CONFIRMED, human_confirmed=True)
    assert confirmed.status is EventLifecycleStatus.CONFIRMED
    with pytest.raises(ValueError, match="MERGED"):
        transition_event(left, EventLifecycleStatus.MERGED)


def test_nlp_status_is_preserved_and_missing_nlp_does_not_create_type():
    observation = _observation(1, nlp_status=PredictionStatus.NOT_IMPLEMENTED)
    candidate = group_event_observations([observation]).candidates[0]
    assert candidate.event_type is None
    assert candidate.status is EventLifecycleStatus.UNCERTAIN
    assert "NLP_EVENT_TYPE_EVIDENCE_UNAVAILABLE" in candidate.evidence


def test_empty_input_and_engine_single_report_are_explicit():
    empty = EventDetector().detect([])
    assert empty.status is EventDetectionStatus.DATA_UNAVAILABLE
    prediction = EventDetector().predict(
        # One report may create a candidate but cannot confirm an event.
        ReportInput(
            report_id=_uuid(1),
            text="flood",
            occurred_at=NOW,
            latitude=25.5941,
            longitude=85.1376,
            source_type="TEST",
        )
    )
    assert prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert prediction.candidate_event is not None
    assert prediction.candidate_event.lifecycle_state == "CANDIDATE"
    assert prediction.candidate_event.report_ids == [_uuid(1)]
    assert prediction.confidence is None
    assert prediction.reason_codes == [
        "SINGLE_REPORT_EVENT_CANDIDATE",
        "NOT_CONFIRMED_EVENT",
    ]


def test_event_annotation_validation_and_grouped_leakage_checks():
    first = EventPairAnnotation(
        event_a_id="event-a",
        event_b_id="event-b",
        label=EventAnnotationLabel.EVENT_MATCH,
        annotator_id="ann-1",
        reason="same occurrence",
        timestamp=NOW,
        canonical_event_id="canonical-1",
        split="train",
        report_ids_a=["r1"],
        report_ids_b=["r2"],
        event_definition_hash_a="hash-1",
        event_definition_hash_b="hash-2",
    )
    second = first.model_copy(update={"label": EventAnnotationLabel.EVENT_NOT_MATCH})
    validation = validate_event_annotations([first, second])
    assert validation.valid is False
    assert validation.contradictory_pair_keys == ["event-a::event-b"]

    leaked = first.model_copy(
        update={
            "event_a_id": "event-c",
            "event_b_id": "event-d",
            "split": "test",
            "report_ids_a": ["r2"],
            "canonical_event_id": "canonical-1",
            "event_definition_hash_a": "hash-1",
        }
    )
    leakage = validate_event_annotation_leakage([first, leaked])
    assert leakage.valid is False
    assert "canonical-1" in leakage.canonical_event_ids_across_splits
    assert "r2" in leakage.report_ids_across_splits
    assert "hash-1" in leakage.near_identical_event_definitions
    assert "event-a" not in leakage.event_ids_across_splits


def test_event_evaluation_refuses_missing_ground_truth_and_reports_labeled_metrics():
    unavailable = evaluate_event_matching([], [])
    assert unavailable.evaluation_status == "DATA_UNAVAILABLE"
    assert unavailable.event_matching_f1 is None

    report = evaluate_event_matching(
        ["EVENT_MATCH", "EVENT_NOT_MATCH", "EVENT_MATCH", "UNCERTAIN"],
        [True, False, False, True],
        true_event_types=["URBAN_FLOOD", "CLOUDBURST", "URBAN_FLOOD", None],
        predicted_event_types=["URBAN_FLOOD", "CLOUDBURST", "RIVER_BREACH", None],
        detection_latency_minutes=[5.0, 10.0, 15.0, None],
    )
    assert report.evaluation_status == "DATA_AVAILABLE"
    assert report.event_matching_precision == pytest.approx(1.0)
    assert report.event_matching_recall == pytest.approx(0.5)
    assert report.false_split_rate == pytest.approx(0.5)
    assert report.event_type_agreement == pytest.approx(2 / 3)
    assert report.mean_detection_latency_minutes == pytest.approx(10.0)
