from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.ml.contracts import (
    AnomalyPrediction,
    CredibilityPrediction,
    DuplicatePrediction,
    EventPrediction,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    TextPrediction,
    UnifiedMLResult,
)


def make_report() -> ReportInput:
    return ReportInput(
        report_id=uuid4(),
        text="Water is rising near the road",
        occurred_at=datetime.now(timezone.utc),
        latitude=25.5941,
        longitude=85.1376,
        source_type="CITIZEN_APP",
    )


def test_report_input_round_trips_without_platform_access():
    report = make_report()
    restored = ReportInput.model_validate_json(report.model_dump_json())
    assert restored == report


def test_unified_result_contains_explicit_component_states():
    status = PredictionStatus.NOT_IMPLEMENTED
    result = UnifiedMLResult(
        report_id=uuid4(),
        text_prediction=TextPrediction(status=status),
        event_prediction=EventPrediction(status=status),
        credibility_prediction=CredibilityPrediction(status=status),
        duplicate_prediction=DuplicatePrediction(status=status),
        image_prediction=ImagePrediction(status=status),
        anomaly_prediction=AnomalyPrediction(status=status),
    )
    assert result.text_prediction.confidence is None
    assert result.image_prediction.probabilities == {}
    assert result.model_dump()["schema_version"] == "1.0"
    assert list(result.model_dump())[:8] == [
        "schema_version",
        "report_id",
        "text_prediction",
        "duplicate_prediction",
        "event_prediction",
        "credibility_prediction",
        "image_prediction",
        "anomaly_prediction",
    ]
    assert UnifiedMLResult.model_validate_json(result.model_dump_json()) == result


def test_missing_prediction_values_are_not_encoded_as_zero():
    prediction = CredibilityPrediction(status=PredictionStatus.OFFLINE)
    assert prediction.score is None
    assert prediction.confidence is None


def test_probability_contracts_reject_invalid_or_misnormalized_values():
    with pytest.raises(ValueError, match="sum to 1"):
        TextPrediction(
            status=PredictionStatus.AVAILABLE,
            label="A",
            probabilities={"A": 0.6, "B": 0.3},
        )
    with pytest.raises(ValueError, match="finite and in"):
        ImagePrediction(
            status=PredictionStatus.AVAILABLE,
            labels=["VISIBLE"],
            probabilities={"VISIBLE": float("nan")},
        )
    with pytest.raises(ValueError, match="cannot disagree"):
        CredibilityPrediction(
            status=PredictionStatus.AVAILABLE,
            score=0.1,
            risk_score=0.2,
        )
