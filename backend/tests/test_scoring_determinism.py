"""
Day 2 T9 — the scoring is deterministic.

The claim this file proves: run the same cluster through the scorer twice and
you get the same number, byte for byte. Until 17 Sep four of the six factors
were random.uniform(), so this test could not have passed.

The unit tests use `score_cluster()` — the pipeline's pure scoring step — so
they run without Docker. The integration test at the bottom runs the whole
pipeline twice over the same seeded reports in Postgres.
"""

import json

import pytest

from app.core.config import get_settings
from app.services.pipeline import score_cluster

# A fixed 5-report citizen cluster, ~1.9 km across, centred on Kankarbagh.
FIXTURE_STATS = {
    "count": 5,
    "centroid_lat": 25.5943,
    "centroid_lng": 85.1375,
    "max_pairwise_km": 1.9,
    "radius_km": 0.95,
}
CITIZENS = ["CITIZEN_APP"] * 5


@pytest.fixture(autouse=True)
def _pinned_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "DBSCAN_EPS_KM", 5.0)
    monkeypatch.setattr(s, "AUTO_PUBLISH_THRESHOLD", 0.90)
    monkeypatch.setattr(s, "HUMAN_REVIEW_THRESHOLD", 0.70)


def _score(stats=FIXTURE_STATS, sources=CITIZENS, weather=0.35, mm=15.6):
    return score_cluster(dict(stats), list(sources), weather, mm)


def _stats(**overrides):
    return {**FIXTURE_STATS, **overrides}


# ── Same input, same output ────────────────────────────────────────────────────

def test_same_fixture_twice_gives_byte_identical_confidence():
    a, b = _score(), _score()
    assert repr(a["confidence"]) == repr(b["confidence"])


def test_same_fixture_twice_gives_byte_identical_receipt():
    a, b = _score(), _score()
    assert json.dumps(a["receipt"], sort_keys=True) == json.dumps(b["receipt"], sort_keys=True)
    assert (a["severity"], a["quadrant"], a["review_status"]) == (
        b["severity"], b["quadrant"], b["review_status"]
    )


def test_same_fixture_twice_with_network_down_is_identical_and_offline():
    a = _score(weather=None, mm=None)
    b = _score(weather=None, mm=None)

    assert repr(a["confidence"]) == repr(b["confidence"])
    for result in (a, b):
        assert result["receipt"]["provenance"]["weather_station"] == "offline"
        weather = next(
            f for f in result["receipt"]["factors"]
            if f["factor"] == "Weather Station Corroboration"
        )
        assert weather["score"] == 0.0
        assert weather["evidence"] == "Telemetry factor offline"


def test_a_hundred_runs_give_one_distinct_score():
    assert len({_score()["confidence"] for _ in range(100)}) == 1


# ── Better evidence scores strictly higher ─────────────────────────────────────

def test_ten_report_cluster_beats_three_report_cluster():
    assert _score(_stats(count=10))["confidence"] > _score(_stats(count=3))["confidence"]


def test_one_km_cluster_beats_four_km_cluster():
    assert (
        _score(_stats(max_pairwise_km=1.0))["confidence"]
        > _score(_stats(max_pairwise_km=4.0))["confidence"]
    )


def test_citizen_plus_official_beats_all_citizen():
    mixed = ["CITIZEN_APP"] * 4 + ["OFFICIAL_DISPATCH"]
    assert _score(sources=mixed)["confidence"] > _score(sources=CITIZENS)["confidence"]


def test_heavy_rain_beats_no_rain():
    assert _score(weather=0.70, mm=64.5)["confidence"] > _score(weather=0.0, mm=0.0)["confidence"]


# ── Nothing invented ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("weather", [0.35, None])
def test_every_factor_is_computed_or_offline(weather):
    provenance = _score(weather=weather, mm=15.6 if weather is not None else None)["receipt"]["provenance"]

    factor_states = {k: v for k, v in provenance.items() if k != "severity"}
    assert set(factor_states) == {
        "report_density", "spatial_coherence", "weather_station",
        "vision_analysis", "source_reliability", "anomaly_detection",
    }
    assert set(factor_states.values()) <= {"computed", "offline"}
    assert "heuristic_placeholder" not in json.dumps(provenance)
    assert factor_states["vision_analysis"] == "offline"
    assert factor_states["anomaly_detection"] == "offline"


def test_fixture_value_is_pinned():
    """
    The actual number for the fixture, written down. If a curve or weight
    changes this fails, which is the point: a score change must be deliberate.

      density(5)          0.5483 × 0.20 = 0.10966
      coherence(1.9 km)   0.9135 × 0.20 = 0.18270
      reliability citizen 0.60   × 0.15 = 0.09
      weather 15.6 mm     0.35   × 0.25 = 0.0875
      vision, anomaly     offline       = 0
                                    total 0.46986 → 0.4699
    """
    result = _score()
    assert result["confidence"] == 0.4699
    assert result["review_status"].value == "QUARANTINED"


# ── Whole pipeline, twice, against Postgres ────────────────────────────────────

@pytest.mark.integration
async def test_pipeline_scores_the_same_seeded_cluster_identically_twice(monkeypatch):
    from sqlalchemy import text

    from app.core.database import async_session
    from app.services import pipeline
    from tests.test_pipeline import CLUSTER_TEXTS, insert_report

    async def fixed_weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", fixed_weather)

    async def run_once():
        async with async_session() as db:
            await db.execute(text("DELETE FROM raw_reports"))
            await db.execute(text("DELETE FROM verified_events"))
            await db.commit()
            try:
                ids = [await insert_report(db, lat, lng, body) for lat, lng, body in CLUSTER_TEXTS]
                result = await pipeline.process_report(db, {"id": str(ids[0])})
                stored = (
                    await db.execute(
                        text("SELECT confidence_score FROM verified_events WHERE id = CAST(:e AS uuid)"),
                        {"e": result["id"]},
                    )
                ).scalar()
                return result["confidence_score"], stored, result["verification_receipt"]["factors"]
            finally:
                await db.execute(text("DELETE FROM raw_reports"))
                await db.execute(text("DELETE FROM verified_events"))
                await db.commit()

    first, second = await run_once(), await run_once()

    assert repr(first[0]) == repr(second[0])
    assert first[1] == second[1] == first[0]
    assert json.dumps(first[2]) == json.dumps(second[2])
