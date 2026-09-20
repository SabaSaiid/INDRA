"""
T10 — Integration tests for the verification pipeline.

Requires a live Postgres with PostGIS. These are the tests that decide whether
the project's central claim — "a citizen report becomes a scored, verified
event" — is actually true.

The two that will really catch bugs are `test_status_is_consistent_with_the_
persisted_score` (it re-derives the status from the stored score rather than
trusting what the pipeline computed) and `test_running_twice_creates_no_second_
event` (without idempotency the consumer re-scores the same reports forever).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.models.enums import Severity
from app.services.fusion_engine import FusionEngine
from app.services.pipeline import process_report

pytestmark = pytest.mark.integration

PATNA_LAT = 25.5941
PATNA_LNG = 85.1376

# Five distinct reports within ~2 km — enough to corroborate one event.
CLUSTER_TEXTS = [
    (25.5941, 85.1376, "Water entering ground floor shops near Kankarbagh main road"),
    (25.5955, 85.1390, "Kankarbagh underpass completely submerged, cars stuck"),
    (25.5930, 85.1360, "Knee deep water outside my house, drain overflowing"),
    (25.5968, 85.1402, "Flooding on the road to Patna junction, buses diverted"),
    (25.5920, 85.1345, "Sewage water mixed with rain water on the street here"),
]


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    """
    Pin the weather factor so these tests do not depend on the internet or on
    today's rainfall in Patna. The live fetch has its own tests in test_weather.py.
    """
    from app.services import pipeline

    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


async def insert_report(db, lat, lng, body, when=None) -> uuid.UUID:
    """Insert a report the way api/reports.py does, and return its id."""
    rid = uuid.uuid4()
    params = {"id": str(rid), "t": body, "lat": lat, "lng": lng}
    when_sql = "NOW()"
    if when is not None:
        when_sql = ":created_at"
        params["created_at"] = when
    await db.execute(
        text(f"""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point, created_at)
            VALUES (:id, 'CITIZEN_APP', :t, :lat, :lng,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), {when_sql})
        """),
        params,
    )
    await db.commit()
    return rid


async def event_count(db) -> int:
    return (await db.execute(text("SELECT COUNT(*) FROM verified_events"))).scalar()


async def seed_cluster(db):
    """Insert the 5-report cluster; return the ids."""
    return [await insert_report(db, lat, lng, body) for lat, lng, body in CLUSTER_TEXTS]


# ── No-event paths ─────────────────────────────────────────────────────────────

async def test_duplicate_is_suppressed_and_creates_no_event(db):
    """Same text, 0.3 km away, 3 minutes later — must not become an event."""
    await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    dupe = await insert_report(
        db, PATNA_LAT + 0.0027, PATNA_LNG, CLUSTER_TEXTS[0][2]
    )

    result = await process_report(db, {"id": str(dupe)})

    assert result is None
    assert await event_count(db) == 0


async def test_lone_report_creates_no_event(db):
    """A single uncorroborated report is not an event. This is correct, not a failure."""
    rid = await insert_report(db, PATNA_LAT, PATNA_LNG, "Some water on the road here")

    result = await process_report(db, {"id": str(rid)})

    assert result is None
    assert await event_count(db) == 0


async def test_malformed_message_returns_none_and_does_not_raise(db):
    """Crash containment — the consumer loop must survive any bad message."""
    assert await process_report(db, {}) is None
    assert await process_report(db, {"id": "not-a-uuid"}) is None
    assert await process_report(db, {"id": str(uuid.uuid4())}) is None  # unknown id
    assert await event_count(db) == 0


# ── The happy path ─────────────────────────────────────────────────────────────

async def test_cluster_forms_exactly_one_event(db):
    await seed_cluster(db)
    ids = (await db.execute(text("SELECT id FROM raw_reports LIMIT 1"))).scalar()

    result = await process_report(db, {"id": str(ids)})

    assert result is not None
    assert await event_count(db) == 1


async def test_all_five_reports_are_linked_to_the_event(db):
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    linked = (
        await db.execute(
            text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": result["id"]},
        )
    ).scalar()
    assert linked == 5


async def test_receipt_is_persisted_with_six_weighted_factors(db):
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    receipt = (
        await db.execute(
            text("SELECT verification_receipt FROM verified_events WHERE id = CAST(:e AS uuid)"),
            {"e": result["id"]},
        )
    ).scalar()

    assert receipt is not None
    assert len(receipt["factors"]) == 6
    assert sum(f["weight_pct"] for f in receipt["factors"]) == pytest.approx(100.0)
    # The receipt must say which factors are measured and which are offline.
    assert receipt["provenance"]["report_density"] == "computed"
    assert receipt["provenance"]["weather_station"] == "computed"
    assert receipt["provenance"]["source_reliability"] == "computed"
    assert receipt["provenance"]["vision_analysis"] == "offline"
    assert receipt["provenance"]["anomaly_detection"] == "offline"
    assert "heuristic_placeholder" not in str(receipt["provenance"])
    assert receipt["cluster"]["size"] == 5
    assert receipt["cluster"]["source_types"] == ["CITIZEN_APP"]


async def test_confidence_is_in_range_and_matches_the_receipt(db):
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    score = (
        await db.execute(
            text("SELECT confidence_score FROM verified_events WHERE id = CAST(:e AS uuid)"),
            {"e": result["id"]},
        )
    ).scalar()

    assert 0.0 <= score <= 1.0
    assert score == pytest.approx(result["verification_receipt"]["confidence_score"])


async def test_status_is_consistent_with_the_persisted_score(db):
    """
    Re-derive the status from what is actually stored, rather than trusting the
    value the pipeline happened to compute. Catches a score/status mismatch.
    """
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    row = (
        await db.execute(
            text("""
                SELECT confidence_score, review_status, severity, quadrant
                FROM verified_events WHERE id = CAST(:e AS uuid)
            """),
            {"e": result["id"]},
        )
    ).fetchone()
    score, status, severity, quadrant = row

    fusion = FusionEngine()
    from app.core.config import get_settings

    settings = get_settings()

    expected_status = fusion.determine_review_status(
        score, settings.AUTO_PUBLISH_THRESHOLD, settings.HUMAN_REVIEW_THRESHOLD
    )
    expected_quadrant = fusion.assign_quadrant(Severity(severity), score)

    assert status == expected_status.value
    assert quadrant == expected_quadrant.value


async def test_five_reports_yield_moderate_severity(db):
    """Below the 10-report HIGH threshold, so a 5-report cluster is MODERATE."""
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    assert result["severity"] == Severity.MODERATE.value


async def test_event_centroid_sits_inside_the_cluster(db):
    ids = await seed_cluster(db)

    result = await process_report(db, {"id": str(ids[0])})

    assert result["lat"] == pytest.approx(PATNA_LAT, abs=0.02)
    assert result["lng"] == pytest.approx(PATNA_LNG, abs=0.02)
    assert result["impact_radius_km"] > 0


# ── Idempotency ────────────────────────────────────────────────────────────────

async def test_running_twice_creates_no_second_event(db):
    """
    Without this the consumer re-clusters and re-scores the same reports on every
    message, producing a new event each time.
    """
    ids = await seed_cluster(db)

    first = await process_report(db, {"id": str(ids[0])})
    assert first is not None
    assert await event_count(db) == 1

    second = await process_report(db, {"id": str(ids[0])})
    assert second is None
    assert await event_count(db) == 1


async def test_streaming_arrival_produces_one_event_not_several(db):
    """
    The case the end-to-end run exposed. Reports arrive one at a time, so a
    cluster hits DBSCAN_MIN_SAMPLES (2) long before the last report lands.
    Without merging, reports 1-2 create one event and reports 3-5 create a rival
    event a few hundred metres away — the fragmentation this platform exists to
    remove, reproduced by the platform itself.

    Feeding the reports in one at a time must still yield exactly one event,
    which accumulates all five reports.
    """
    results = []
    for lat, lng, body in CLUSTER_TEXTS:
        rid = await insert_report(db, lat, lng, body)
        results.append(await process_report(db, {"id": str(rid)}))

    assert await event_count(db) == 1

    created = [r for r in results if r is not None]
    assert len(created) >= 1
    # The first is a fresh event; every later one is a merge into it.
    assert created[0]["merged"] is False
    assert all(r["merged"] for r in created[1:])

    # All five reports end up on the single event.
    final = created[-1]
    linked = (
        await db.execute(
            text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": final["id"]},
        )
    ).scalar()
    assert linked == 5
    assert final["report_count"] == 5

    # Every emitted event carries the same identity — the feed shows one
    # incident strengthening, not several competing ones.
    assert len({r["event_code"] for r in created}) == 1


async def test_merging_raises_corroboration_and_confidence(db):
    """More corroborating reports must not lower the event's confidence."""
    scores = []
    for lat, lng, body in CLUSTER_TEXTS:
        rid = await insert_report(db, lat, lng, body)
        result = await process_report(db, {"id": str(rid)})
        if result:
            scores.append((result["report_count"], result["verification_receipt"]["factors"]))

    counts = [c for c, _ in scores]
    assert counts == sorted(counts), "report_count must grow monotonically"

    # report_density is a computed factor, so it must rise with corroboration.
    def density(factors):
        return next(f["score"] for f in factors if f["factor"] == "Report Density Analysis")

    densities = [density(f) for _, f in scores]
    assert densities == sorted(densities)


async def test_distant_event_is_not_merged(db):
    """A genuinely separate incident must still get its own event."""
    for lat, lng, body in CLUSTER_TEXTS[:2]:
        rid = await insert_report(db, lat, lng, body)
        await process_report(db, {"id": str(rid)})
    assert await event_count(db) == 1

    # ~100 km away, well outside impact_radius + eps.
    far = [
        (24.7900, 85.0000, "Severe waterlogging near the bus stand here"),
        (24.7905, 85.0010, "Market road under water, shops shutting"),
    ]
    for lat, lng, body in far:
        rid = await insert_report(db, lat, lng, body)
        await process_report(db, {"id": str(rid)})

    assert await event_count(db) == 2


async def test_processing_each_report_of_a_cluster_yields_one_event(db):
    """
    Realistic case: all five reports arrive on the topic, so the pipeline runs
    five times. Only the first should produce an event; the rest are already
    linked.
    """
    ids = await seed_cluster(db)

    results = [await process_report(db, {"id": str(rid)}) for rid in ids]

    created = [r for r in results if r is not None]
    assert len(created) == 1
    assert await event_count(db) == 1


async def test_suppressed_duplicate_is_not_absorbed_by_a_later_report(db):
    results = []
    for lat, lng, body in CLUSTER_TEXTS:
        rid = await insert_report(db, lat, lng, body)
        results.append(await process_report(db, {"id": str(rid)}))
    event_id = results[-1]["id"]

    dupe = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    assert await process_report(db, {"id": str(dupe)}) is None

    extra = await insert_report(
        db, 25.5968, 85.1376, "Auto stand near Rajendra Nagar flooded, rickshaws cannot move"
    )
    result = await process_report(db, {"id": str(extra)})

    assert result["id"] == event_id
    assert result["report_count"] == 6  # 5 + the new report; the duplicate stays out


# ── Suppressed duplicates are marked and never counted (Day 4, migration 0004) ─

async def duplicate_of(db, rid):
    return (
        await db.execute(
            text("SELECT duplicate_of, event_id FROM raw_reports WHERE id = CAST(:id AS uuid)"),
            {"id": str(rid)},
        )
    ).fetchone()


async def test_suppressed_duplicate_records_its_original(db):
    ids = await seed_cluster(db)
    for rid in ids:
        await process_report(db, {"id": str(rid)})

    dupe = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    assert await process_report(db, {"id": str(dupe)}) is None

    row = await duplicate_of(db, dupe)
    assert row[0] == ids[0]
    assert row[1] is None


async def test_every_copy_points_at_the_original_not_at_another_copy(db):
    now = datetime.now(timezone.utc)
    body = "Water entering ground floor shops near Kankarbagh main road"
    ids = []
    for minutes_ago in (3, 2, 1):  # arrive and are processed one at a time
        rid = await insert_report(db, PATNA_LAT, PATNA_LNG, body, when=now - timedelta(minutes=minutes_ago))
        assert await process_report(db, {"id": str(rid)}) is None
        ids.append(rid)
    original, second, third = ids

    assert (await duplicate_of(db, original))[0] is None
    assert (await duplicate_of(db, second))[0] == original
    assert (await duplicate_of(db, third))[0] == original


async def test_duplicates_do_not_corroborate_a_distinct_report(db):
    """
    The original sits in a rejected event (so nothing can merge into it); two
    suppressed copies of it remain unassigned. A distinct report 300 m away must
    stay a lone report: before migration 0004 the two copies clustered with it
    into a 3-report event.
    """
    event_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km, center_point, verification_receipt)
            VALUES (CAST(:id AS uuid), 'INDRA-TEST-REJ', 'URBAN_FLOOD', 'MODERATE', 0.4,
                    'REJECTED', 'Noise', 0.5,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), '{}'::jsonb)
        """),
        {"id": str(event_id), "lat": PATNA_LAT, "lng": PATNA_LNG},
    )
    await db.commit()
    body = CLUSTER_TEXTS[0][2]
    original = await insert_report(db, PATNA_LAT, PATNA_LNG, body)
    copies = [await insert_report(db, PATNA_LAT, PATNA_LNG, body) for _ in range(2)]
    await db.execute(
        text("UPDATE raw_reports SET event_id = CAST(:e AS uuid) WHERE id = CAST(:id AS uuid)"),
        {"e": str(event_id), "id": str(original)},
    )
    await db.execute(
        text("UPDATE raw_reports SET duplicate_of = CAST(:o AS uuid) WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"o": str(original), "ids": [str(c) for c in copies]},
    )
    await db.commit()

    distinct = await insert_report(
        db, PATNA_LAT + 0.0027, PATNA_LNG, "Auto stand near Rajendra Nagar flooded, rickshaws cannot move"
    )
    assert await process_report(db, {"id": str(distinct)}) is None
    assert await event_count(db) == 1  # only the rejected one


async def test_redelivered_duplicate_is_skipped(db):
    await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    dupe = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    assert await process_report(db, {"id": str(dupe)}) is None
    first = await duplicate_of(db, dupe)
    assert await process_report(db, {"id": str(dupe)}) is None
    assert await duplicate_of(db, dupe) == first
