"""Phase 26: the six local advisory components across the backend boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import uuid4

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text

from app.core.database import async_session
from app.ml.contracts import (
    CandidateReport,
    CredibilityRiskLevel,
    PredictionStatus,
    ReportInput,
    StationObservation,
    UnifiedMLResult,
)
from app.ml.inference.engine import InferenceEngine
from app.ml.inference.frozen_engine import (
    build_frozen_inference_engine,
    group_report_candidates,
)
from app.services import pipeline
from app.services.ml_adapter import analyze_loaded_report
from app.services.pipeline import process_report
from tests.conftest import wipe_event_tables


WHEN = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
LAT = 25.5941
LNG = 85.1376
TEXT = "Heavy rain flooded the street near Patna; water is entering shops."


@pytest.fixture(scope="module")
def frozen_engine():
    return build_frozen_inference_engine()


def report(**updates) -> ReportInput:
    values = {
        "report_id": uuid4(),
        "text": TEXT,
        "occurred_at": WHEN,
        "latitude": LAT,
        "longitude": LNG,
        "source_type": "CITIZEN_APP",
    }
    values.update(updates)
    return ReportInput(**values)


def duplicate_candidate() -> CandidateReport:
    return CandidateReport(
        report_id=uuid4(),
        text=TEXT,
        occurred_at=WHEN - timedelta(minutes=2),
        latitude=LAT,
        longitude=LNG,
        source_type="OFFICIAL_DISPATCH",
    )


def station_history() -> list[StationObservation]:
    return [
        StationObservation(
            station_id="PATNA-TEST",
            observed_at=WHEN - timedelta(hours=24 - index),
            measurements={
                "rainfall_mm": 1.0 + index * 0.3,
                "river_level_m": 2.0 + index * 0.01,
            },
        )
        for index in range(24)
    ]


def local_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (96, 96), (38, 88, 130)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_text_only_report_has_typed_missing_inputs(frozen_engine):
    result = analyze_loaded_report(report(), engine=frozen_engine)
    assert isinstance(result, UnifiedMLResult)
    assert result.text_prediction.status is PredictionStatus.AVAILABLE
    assert result.duplicate_prediction.status is PredictionStatus.NOT_RUN
    assert result.image_prediction.status is PredictionStatus.NOT_RUN
    assert result.anomaly_prediction.status is PredictionStatus.NOT_RUN
    assert "MISSING_INPUT" in result.image_prediction.reason_codes
    assert "MISSING_INPUT" in result.anomaly_prediction.reason_codes
    assert result.image_prediction.confidence is None
    assert result.anomaly_prediction.score is None


def test_duplicate_candidate_uses_frozen_matcher(frozen_engine):
    candidate = duplicate_candidate()
    result = analyze_loaded_report(
        report(candidate_reports=[candidate]), engine=frozen_engine
    )
    assert result.duplicate_prediction.status is PredictionStatus.AVAILABLE
    assert result.duplicate_prediction.is_duplicate is True
    assert result.duplicate_prediction.matched_report_id == candidate.report_id
    assert result.duplicate_prediction.model_version.startswith("duplicate-matcher-v1")


def test_multi_report_event_is_grouped_as_candidate(frozen_engine):
    reports = [
        report(source_type=source, occurred_at=WHEN + timedelta(minutes=index))
        for index, source in enumerate(
            ("CITIZEN_APP", "OFFICIAL_DISPATCH", "CWC_GAUGE")
        )
    ]
    grouping = group_report_candidates(reports, engine=frozen_engine)
    assert grouping.status.value == "AVAILABLE"
    assert grouping.candidates
    assert any(candidate.report_count >= 2 for candidate in grouping.candidates)
    assert all(candidate.status.value == "CANDIDATE" for candidate in grouping.candidates)


def test_single_report_cannot_confirm_itself(frozen_engine):
    result = analyze_loaded_report(report(), engine=frozen_engine)
    assert result.event_prediction.status is PredictionStatus.HEURISTIC_ONLY
    assert result.event_prediction.candidate_event is not None
    assert result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"
    assert result.event_prediction.confidence is None
    assert "NOT_CONFIRMED_EVENT" in result.event_prediction.reason_codes


def test_already_loaded_image_is_inferred_locally(frozen_engine):
    result = analyze_loaded_report(
        report(image_bytes=local_png(), source_metadata={"image_mime_type": "image/png"}),
        engine=frozen_engine,
    )
    assert result.image_prediction.status is PredictionStatus.AVAILABLE
    assert result.image_prediction.model_version.startswith("image-model-v1")
    assert result.image_prediction.probabilities


def test_anomaly_enabled_report_uses_real_supplied_history(frozen_engine):
    result = analyze_loaded_report(
        report(station_observations=station_history()), engine=frozen_engine
    )
    assert result.anomaly_prediction.status is PredictionStatus.AVAILABLE
    assert result.anomaly_prediction.score_type == "SYNTHETIC_DEVELOPMENT_MODEL_SCORE"
    assert result.anomaly_prediction.model_version.startswith("anomaly-model-v1")
    assert result.anomaly_prediction.baseline_version is not None
    assert "SYNTHETIC_DEVELOPMENT_ONLY" in result.anomaly_prediction.reason_codes


def test_authentic_duplicate_is_not_an_automatic_fake_finding(frozen_engine):
    result = analyze_loaded_report(
        report(candidate_reports=[duplicate_candidate()]), engine=frozen_engine
    )
    assert result.duplicate_prediction.is_duplicate is True
    assert result.credibility_prediction.status is PredictionStatus.AVAILABLE
    assert result.credibility_prediction.risk_level in set(CredibilityRiskLevel)
    assert any("not proof" in warning for warning in result.credibility_prediction.warnings)
    assert result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"


def test_anomaly_does_not_become_credibility_evidence(frozen_engine):
    base = report()
    without = analyze_loaded_report(base, engine=frozen_engine)
    with_history = analyze_loaded_report(
        base.model_copy(update={"station_observations": station_history()}),
        engine=frozen_engine,
    )
    assert with_history.anomaly_prediction.status is PredictionStatus.AVAILABLE
    assert without.credibility_prediction.risk_score == with_history.credibility_prediction.risk_score
    assert with_history.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"


def test_component_failure_is_error_not_negative(frozen_engine):
    class BrokenDuplicate:
        def predict(self, _report):
            raise RuntimeError("deliberate local component failure")

    failing = InferenceEngine(
        nlp_classifier=frozen_engine.nlp_classifier,
        duplicate_matcher=BrokenDuplicate(),
        event_detector=frozen_engine.event_detector,
        fake_detector=frozen_engine.fake_detector,
        image_analyzer=frozen_engine.image_analyzer,
        anomaly_detector=frozen_engine.anomaly_detector,
    )
    result = failing.analyze(report(candidate_reports=[duplicate_candidate()]))
    assert result.duplicate_prediction.status is PredictionStatus.ERROR
    assert result.duplicate_prediction.is_duplicate is None
    assert result.credibility_prediction.status is PredictionStatus.NOT_RUN
    assert result.credibility_prediction.risk_score is None
    assert result.errors


def test_all_six_components_are_available_with_real_inputs(frozen_engine):
    result = analyze_loaded_report(
        report(
            candidate_reports=[duplicate_candidate()],
            station_observations=station_history(),
            image_bytes=local_png(),
            source_metadata={"image_mime_type": "image/png"},
        ),
        engine=frozen_engine,
    )
    assert [
        prediction.status
        for prediction in (
            result.text_prediction,
            result.duplicate_prediction,
            result.event_prediction,
            result.credibility_prediction,
            result.image_prediction,
            result.anomaly_prediction,
        )
    ] == [
        PredictionStatus.AVAILABLE,
        PredictionStatus.AVAILABLE,
        PredictionStatus.HEURISTIC_ONLY,
        PredictionStatus.AVAILABLE,
        PredictionStatus.AVAILABLE,
        PredictionStatus.AVAILABLE,
    ]
    assert set(result.model_versions) == {
        "nlp_classifier", "duplicate_matcher", "event_detector",
        "fake_detector", "image_analyzer", "anomaly_detector",
    }
    assert result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"
    assert result.errors == []


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


async def insert_report(db, body: str, *, source_type: str = "CITIZEN_APP"):
    report_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point)
            VALUES
                (CAST(:id AS uuid), CAST(:source_type AS source_type_enum), :body,
                 :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {
            "id": str(report_id), "source_type": source_type,
            "body": body, "lat": LAT, "lng": LNG,
        },
    )
    await db.commit()
    return report_id


@pytest.mark.integration
async def test_pipeline_persists_unified_result_for_single_report(db):
    report_id = await insert_report(db, TEXT)
    assert await process_report(db, {"id": str(report_id)}) is None
    payload = (
        await db.execute(
            text("SELECT analysis->'ml' FROM raw_reports WHERE id=CAST(:id AS uuid)"),
            {"id": str(report_id)},
        )
    ).scalar_one()
    result = UnifiedMLResult.model_validate(payload)
    assert result.report_id == report_id
    assert result.event_prediction.candidate_event.lifecycle_state == "CANDIDATE"
    assert result.image_prediction.status is PredictionStatus.NOT_RUN


@pytest.mark.integration
async def test_pipeline_receipt_keeps_multi_report_grouping_advisory(db, monkeypatch):
    async def fixed_weather(_lat, _lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", fixed_weather)
    await insert_report(db, "Patna street flooded after rain near shops", source_type="CITIZEN_APP")
    second = await insert_report(
        db, "Floodwater blocks vehicles on the same Patna road",
        source_type="OFFICIAL_DISPATCH",
    )
    event = await process_report(db, {"id": str(second)})
    assert event is not None
    grouping = event["verification_receipt"]["ml_event_grouping"]
    assert grouping["status"] == "AVAILABLE"
    assert grouping["candidates"]
    assert all(item["status"] == "CANDIDATE" for item in grouping["candidates"])
