from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.ml.components.credibility_features import (
    credibility_input_from_report,
    extract_credibility_features,
)
from app.ml.components.fake_detection import FakeDetector
from app.ml.contracts import (
    CalibrationStatus,
    CredibilityRiskInput,
    CredibilityRiskLevel,
    DuplicatePrediction,
    EventPrediction,
    PredictionStatus,
    ReportInput,
    TextPrediction,
)
from app.ml.data.fake_report_annotations import (
    AnnotationEvidence,
    FakeReportAnnotation,
    FakeReportAnnotationStore,
    FakeReportLabel,
    RULE_EVIDENCE_DISCLAIMER,
    adjudicate_fake_report,
    build_fake_adjudication_case,
    build_fake_annotation_view,
    grouped_fake_report_split,
    validate_fake_report_annotations,
    validate_fake_report_leakage,
)
from app.ml.evaluation.evaluate import evaluate_credibility_predictions


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase7-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()


def _report(
    number: int = 1,
    *,
    text: str = "Water entered two homes near the market after heavy rain.",
    occurred_at: datetime = NOW,
    source_metadata: dict | None = None,
) -> ReportInput:
    return ReportInput(
        report_id=UUID(int=number),
        text=text,
        occurred_at=occurred_at,
        latitude=25.5941,
        longitude=85.1376,
        source_type="CITIZEN_APP",
        source_metadata=source_metadata or {},
    )


def _codes(prediction) -> set[str]:
    return {
        item.reason_code
        for item in prediction.evidence
        if hasattr(item, "reason_code")
    }


def _annotation(
    report_id: str,
    annotator: str,
    label: FakeReportLabel,
    *,
    split=None,
    canonical_event_id: str | None = None,
    report_text: str | None = None,
) -> FakeReportAnnotation:
    return FakeReportAnnotation(
        annotation_id=f"annotation-{report_id}-{annotator}-{split or 'none'}",
        report_id=report_id,
        label=label,
        annotator_id=annotator,
        annotation_timestamp=NOW,
        reason="Evidence reviewed for deterministic unit fixture.",
        evidence=[
            AnnotationEvidence(
                code="FIXTURE_EVIDENCE",
                description="Unit-test evidence only.",
                provenance="UNIT_TEST_ONLY",
            )
        ],
        canonical_event_id=canonical_event_id,
        report_text=report_text,
        split=split,
    )


def test_authentic_style_report_returns_low_uncalibrated_risk_not_truth_claim():
    prediction = FakeDetector().predict(_report())
    assert prediction.status is PredictionStatus.AVAILABLE
    assert prediction.risk_level is CredibilityRiskLevel.LOW
    assert prediction.risk_score == 0.0
    assert prediction.score is None
    assert prediction.confidence is None
    assert prediction.calibration_status is CalibrationStatus.NOT_CALIBRATED
    assert prediction.baseline_name == "RULE_BASED_CREDIBILITY_BASELINE"
    assert "NO_RULE_RISK_SIGNALS" in _codes(prediction)
    assert any("DOES NOT ESTABLISH TRUTH" in warning for warning in prediction.warnings)


def test_contradictory_timestamp_and_invalid_coordinates_are_inspectable():
    report = _report(occurred_at=NOW)
    risk_input = CredibilityRiskInput(
        report=report,
        submitted_at=NOW - timedelta(hours=1),
        reported_latitude=200.0,
        reported_longitude=85.0,
    )
    prediction = FakeDetector().predict(risk_input)
    assert {"CONTRADICTORY_TIMESTAMP", "INVALID_COORDINATES"} <= _codes(prediction)
    assert prediction.risk_level is CredibilityRiskLevel.HIGH
    assert prediction.risk_score is not None


def test_malformed_timestamp_is_metadata_evidence_not_an_exception():
    report = _report(source_metadata={"submitted_at": "not-a-timestamp"})
    risk_input = credibility_input_from_report(report)
    assert risk_input.metadata_validation_errors == ["invalid source_metadata.submitted_at"]
    prediction = FakeDetector().predict(risk_input)
    assert "INVALID_METADATA" in _codes(prediction)


def test_duplicate_report_is_review_evidence_not_a_fake_label():
    duplicate = DuplicatePrediction(
        status=PredictionStatus.AVAILABLE,
        is_duplicate=True,
        similarity=0.99,
    )
    risk_input = CredibilityRiskInput(
        report=_report(),
        duplicate_prediction=duplicate,
        duplicate_cluster_size=8,
    )
    prediction = FakeDetector().predict(risk_input)
    assert {"REPEATED_TEXT", "EXCESSIVE_DUPLICATE_BEHAVIOR"} <= _codes(prediction)
    assert prediction.label in {"LOW", "MODERATE", "HIGH"}
    repeated_item = next(item for item in prediction.evidence if getattr(item, "reason_code", None) == "REPEATED_TEXT")
    assert "does not mean" in repeated_item.interpretation


def test_missing_evidence_returns_uncertain_without_zero_score():
    prediction = FakeDetector().predict(_report(text=""))
    assert prediction.status is PredictionStatus.INSUFFICIENT_DATA
    assert prediction.risk_level is CredibilityRiskLevel.UNCERTAIN
    assert prediction.risk_score is None
    assert prediction.score is None
    assert prediction.calibration_status is CalibrationStatus.CALIBRATION_UNAVAILABLE


def test_feature_extraction_is_deterministic_and_uses_available_time_only():
    risk_input = CredibilityRiskInput(
        report=_report(text="flood flood flood!!! https://example.test"),
        submitted_at=NOW + timedelta(minutes=10),
        source_recent_report_count=12,
        source_recent_duplicate_count=6,
        supplied_phone_count=1,
    )
    first = extract_credibility_features(risk_input)
    second = extract_credibility_features(risk_input)
    assert first == second
    assert first.submission_delay_seconds == 600.0
    assert first.source_recent_duplicate_ratio == 0.5
    assert first.url_count == 1


def test_event_conflict_is_interpretable_and_media_interface_is_not_scored():
    risk_input = CredibilityRiskInput(
        report=_report(),
        text_prediction=TextPrediction(
            status=PredictionStatus.AVAILABLE,
            label="URBAN_FLOOD",
            probabilities={"URBAN_FLOOD": 1.0},
        ),
        event_prediction=EventPrediction(
            status=PredictionStatus.AVAILABLE,
            event_type="CLOUDBURST",
        ),
        media_text_consistency=False,
    )
    prediction = FakeDetector().predict(risk_input)
    assert "EVENT_TYPE_INCONSISTENCY" in _codes(prediction)
    assert "MEDIA_EVIDENCE_RESERVED_NOT_SCORED" in _codes(prediction)


def test_training_and_calibration_are_unavailable_without_validated_labels():
    detector = FakeDetector()
    training = detector.fit([])
    assert training.status == "TRAINING_BLOCKED_NO_VALIDATED_LABELS"
    assert training.artifact_created is False
    evaluation = detector.evaluate([], [])
    assert evaluation.evaluation_status == "DATA_UNAVAILABLE"
    assert evaluation.calibration_status == "CALIBRATION_UNAVAILABLE"


def test_future_evaluation_interface_supports_metrics_without_claiming_current_metrics():
    result = evaluate_credibility_predictions(
        ["AUTHENTIC", "MISLEADING", "MISLEADING", "UNCERTAIN"],
        [False, True, False, True],
        risk_scores=[0.1, 0.9, 0.4, 0.8],
    )
    assert result.evaluation_status == "DATA_AVAILABLE"
    assert result.precision == pytest.approx(1.0)
    assert result.recall == pytest.approx(0.5)
    assert result.calibration_status == "CALIBRATION_UNAVAILABLE"
    assert result.threshold_analysis


def test_multiple_annotators_disagreement_and_explicit_adjudication():
    first = _annotation("report-1", "ann-a", FakeReportLabel.AUTHENTIC)
    second = _annotation("report-1", "ann-b", FakeReportLabel.MISLEADING)
    quality = validate_fake_report_annotations([first, second], available_report_ids={"report-1"})
    assert quality.valid is True
    assert quality.agreement_status == "DATA_AVAILABLE"
    assert quality.agreement_rate == 0.0
    assert quality.disagreement_report_ids == ["report-1"]
    assert any("unresolved" in warning for warning in quality.warnings)

    case = build_fake_adjudication_case([first, second])
    assert case.effective_label is FakeReportLabel.UNCERTAIN
    adjudicated = adjudicate_fake_report(
        case,
        label=FakeReportLabel.UNCERTAIN,
        adjudicator_id="senior-reviewer",
        reason="Available evidence cannot resolve the disagreement.",
        timestamp=NOW + timedelta(hours=1),
    )
    assert adjudicated.status == "ADJUDICATED"
    assert adjudicated.effective_label is FakeReportLabel.UNCERTAIN


def test_annotation_store_is_append_only(local_tmp_path):
    store = FakeReportAnnotationStore(local_tmp_path / "annotations.jsonl")
    annotation = _annotation("report-1", "ann-a", FakeReportLabel.UNCERTAIN)
    store.append(annotation)
    assert store.load() == [annotation]
    with pytest.raises(ValueError, match="already exists"):
        store.append(annotation)


def test_annotation_blinding_hides_rule_score_by_default():
    report = _report()
    prediction = FakeDetector().predict(report)
    hidden = build_fake_annotation_view(report, prediction)
    shown = build_fake_annotation_view(report, prediction, blinded=False)
    assert hidden.rule_score is None
    assert hidden.rule_evidence == []
    assert shown.rule_score == prediction.risk_score
    assert shown.banner == RULE_EVIDENCE_DISCLAIMER


def test_annotation_quality_rejects_invalid_coordinates_and_missing_reports():
    annotation = _annotation("missing", "ann-a", FakeReportLabel.UNCERTAIN).model_copy(
        update={"reported_latitude": 100.0, "reported_longitude": 10.0}
    )
    quality = validate_fake_report_annotations([annotation], available_report_ids=set())
    assert quality.valid is False
    assert any("missing report data" in error for error in quality.errors)
    assert any("invalid coordinates" in error for error in quality.errors)


def test_grouped_splitting_and_leakage_keep_report_families_together():
    annotations = [
        _annotation(
            f"report-{index}",
            "ann-a",
            FakeReportLabel.UNCERTAIN,
            canonical_event_id=f"event-{index}",
            report_text=f"text {index}",
        )
        for index in range(5)
    ]
    split = grouped_fake_report_split(annotations)
    assert split.status == "GROUPED_SPLIT_AVAILABLE"
    assert split.group_field == "canonical_event_id"

    train = annotations[0].model_copy(
        update={"split": "train", "canonical_event_id": "same-event", "report_text": "Same text"}
    )
    test = annotations[1].model_copy(
        update={"split": "test", "canonical_event_id": "same-event", "report_text": " same   TEXT "}
    )
    leakage = validate_fake_report_leakage([train, test])
    assert leakage.valid is False
    assert leakage.canonical_events_across_splits == ["same-event"]
    assert leakage.exact_texts_across_splits == ["same text"]

    near = annotations[2].model_copy(
        update={"split": "test", "report_text": "Emergency flood water at market lane"}
    )
    near_train = annotations[3].model_copy(
        update={"split": "train", "report_text": "Emergency flood water at market lanes"}
    )
    near_leakage = validate_fake_report_leakage(
        [near, near_train], near_identical_threshold=0.90
    )
    assert near_leakage.near_identical_text_pairs
