import socket
from datetime import datetime, timezone
from uuid import uuid4

from app.ml.contracts import (
    AnomalyPrediction,
    CredibilityPrediction,
    CredibilityRiskInput,
    DuplicatePrediction,
    EventPrediction,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    TextPrediction,
)
from app.ml.inference.engine import InferenceEngine
from app.ml.orchestration.service import analyze_report


def report() -> ReportInput:
    return ReportInput(
        report_id=uuid4(),
        text="Water is rising near the road",
        occurred_at=datetime.now(timezone.utc),
        latitude=25.5941,
        longitude=85.1376,
        source_type="CITIZEN_APP",
    )


def test_default_engine_returns_no_fabricated_predictions():
    result = InferenceEngine().analyze(report())
    assert result.text_prediction.status is PredictionStatus.AVAILABLE
    assert result.text_prediction.label in result.text_prediction.probabilities
    assert result.text_prediction.probabilities
    assert result.text_prediction.confidence is not None
    assert result.text_prediction.reason_codes == ["DEVELOPMENT_MODEL_INFERENCE"]
    assert result.event_prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert result.event_prediction.candidate_event is not None
    assert result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"
    assert result.event_prediction.candidate_event.report_ids == [result.report_id]
    assert result.event_prediction.confidence is None
    assert result.credibility_prediction.status is PredictionStatus.AVAILABLE
    assert result.credibility_prediction.baseline_name == "RULE_BASED_CREDIBILITY_BASELINE"
    assert result.credibility_prediction.risk_score is not None
    assert result.credibility_prediction.confidence is None
    assert result.duplicate_prediction.status is PredictionStatus.NOT_APPLICABLE
    assert result.image_prediction.status is PredictionStatus.NOT_APPLICABLE
    assert result.anomaly_prediction.status is PredictionStatus.NOT_APPLICABLE
    assert result.duplicate_prediction.similarity is None
    assert result.errors == []
    assert result.warnings


def test_orchestration_entry_point_is_pure_and_deterministic():
    input_report = report()
    first = analyze_report(input_report).model_dump()
    second = analyze_report(input_report).model_dump()
    assert first == second


def test_engine_order_and_credibility_upstream_inputs_are_explicit():
    calls: list[str] = []
    text = TextPrediction(
        status=PredictionStatus.AVAILABLE,
        label="URBAN_FLOOD",
        probabilities={"URBAN_FLOOD": 1.0},
    )
    duplicate = DuplicatePrediction(
        status=PredictionStatus.AVAILABLE,
        is_duplicate=False,
    )
    event = EventPrediction(status=PredictionStatus.HEURISTIC_ONLY)

    class Component:
        def __init__(self, name, prediction):
            self.name = name
            self.prediction = prediction

        def predict(self, value, **kwargs):
            calls.append(self.name)
            return self.prediction

    class CredibilityComponent:
        supplied: CredibilityRiskInput | None = None

        def predict(self, value):
            calls.append("credibility")
            self.supplied = value
            return CredibilityPrediction(
                status=PredictionStatus.AVAILABLE,
                risk_score=0.0,
            )

    credibility = CredibilityComponent()
    engine = InferenceEngine(
        nlp_classifier=Component("nlp", text),
        duplicate_matcher=Component("duplicate", duplicate),
        event_detector=Component("event", event),
        fake_detector=credibility,
        image_analyzer=Component(
            "image", ImagePrediction(status=PredictionStatus.NOT_APPLICABLE)
        ),
        anomaly_detector=Component(
            "anomaly", AnomalyPrediction(status=PredictionStatus.NOT_APPLICABLE)
        ),
    )
    result = engine.analyze(report())
    assert calls == ["nlp", "duplicate", "event", "credibility", "image", "anomaly"]
    assert isinstance(credibility.supplied, CredibilityRiskInput)
    assert credibility.supplied.text_prediction == text
    assert credibility.supplied.duplicate_prediction == duplicate
    assert credibility.supplied.event_prediction == event
    assert result.duplicate_prediction == duplicate


def test_default_engine_performs_no_network_socket_access(monkeypatch):
    def reject_socket(*args, **kwargs):
        raise AssertionError("ML inference attempted network socket access")

    monkeypatch.setattr(socket, "socket", reject_socket)
    result = InferenceEngine().analyze(report())
    assert result.text_prediction.status is PredictionStatus.AVAILABLE
