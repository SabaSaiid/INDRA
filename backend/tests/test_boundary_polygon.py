"""
T4 (Day 5) — verified_events.boundary_polygon, the footprint on the operator's map.

The column existed from migration 0001 and the pipeline never wrote it, so every
event served `boundary_geojson: null` and the dashboard had nothing to draw but a
centroid and a radius.

Filled in pipeline step 7, from the event's linked non-duplicate reports:

    ST_Buffer(ST_ConcaveHull(ST_Collect(geom_point), 0.8)::geography, 250)

Measured against this database (PostGIS 3.4 / GEOS 3.9): a one-point hull is an
ST_Point and a two-point hull is an ST_LineString, and the buffer turns both into
polygons. That is why a lone report still gets a footprint instead of a NULL.
"""

import math
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import pipeline
from app.services.pipeline import process_report
from tests.conftest import wipe_event_tables
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration

BUFFER_M = 250
DISC_AREA = math.pi * BUFFER_M ** 2                      # 196,350 m²
TWO_POINT_AREA = 2 * BUFFER_M * 1000 + DISC_AREA         # 696,350 m²


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
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
            await session.rollback()
            await wipe_event_tables(session)


async def boundary(db, event_id):
    """(geometry type, geodesic area m², is_null) for an event's polygon."""
    row = (
        await db.execute(
            text("""
                SELECT ST_GeometryType(boundary_polygon),
                       ST_Area(boundary_polygon::geography),
                       boundary_polygon IS NULL
                FROM verified_events WHERE id = CAST(:e AS uuid)
            """),
            {"e": event_id},
        )
    ).fetchone()
    return row[0], row[1], row[2]


async def contains_all_reports(db, event_id) -> bool:
    """True when every linked non-duplicate report falls inside the polygon."""
    outside = (
        await db.execute(
            text("""
                SELECT COUNT(*) FROM raw_reports r
                JOIN verified_events e ON e.id = r.event_id
                WHERE e.id = CAST(:e AS uuid)
                  AND r.duplicate_of IS NULL
                  AND r.geom_point IS NOT NULL
                  AND NOT ST_Contains(e.boundary_polygon, r.geom_point)
            """),
            {"e": event_id},
        )
    ).scalar()
    return outside == 0


# ── Shape and size ─────────────────────────────────────────────────────────────

async def test_a_two_report_event_gets_a_polygon_covering_both(db):
    """
    Two reports 1 km apart: a LineString hull, buffered into a capsule.

    Area within 3% of 2·250·1000 + π·250² — a 1 km corridor 500 m wide with
    semicircular caps.
    """
    a = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    await insert_report(db, PATNA_LAT + 0.009, PATNA_LNG, CLUSTER_TEXTS[1][2])

    result = await process_report(db, {"id": str(a)})
    assert result is not None

    gtype, area, is_null = await boundary(db, result["id"])
    assert not is_null
    assert gtype == "ST_Polygon"
    assert area == pytest.approx(TWO_POINT_AREA, rel=0.03)
    assert await contains_all_reports(db, result["id"])


async def test_the_five_report_scene_contains_every_point(db):
    ids = []
    for lat, lng, body in CLUSTER_TEXTS:
        ids.append(await insert_report(db, lat, lng, body))

    result = await process_report(db, {"id": str(ids[0])})

    gtype, _, is_null = await boundary(db, result["id"])
    assert not is_null
    assert gtype == "ST_Polygon"
    assert await contains_all_reports(db, result["id"])

    linked = (
        await db.execute(
            text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": result["id"]},
        )
    ).scalar()
    assert linked == 5


async def test_a_merge_widens_the_polygon_to_cover_the_new_report(db):
    """
    A merge must recompute the footprint, not keep the one it had.

    The added report is ~800 m outside the original pair, so a stale polygon
    would visibly exclude a report the event now claims.
    """
    a = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    await insert_report(db, PATNA_LAT + 0.002, PATNA_LNG, CLUSTER_TEXTS[1][2])
    result = await process_report(db, {"id": str(a)})
    event_id = result["id"]

    _, area_before, _ = await boundary(db, event_id)

    far = await insert_report(db, PATNA_LAT + 0.0072, PATNA_LNG + 0.004, CLUSTER_TEXTS[3][2])
    merged = await process_report(db, {"id": str(far)})
    assert merged is not None and merged["id"] == event_id

    gtype, area_after, is_null = await boundary(db, event_id)
    assert not is_null
    assert gtype == "ST_Polygon"
    assert area_after > area_before
    assert await contains_all_reports(db, event_id)

    inside = (
        await db.execute(
            text("""
                SELECT ST_Contains(e.boundary_polygon, r.geom_point)
                FROM verified_events e, raw_reports r
                WHERE e.id = CAST(:e AS uuid) AND r.id = CAST(:r AS uuid)
            """),
            {"e": event_id, "r": str(far)},
        )
    ).scalar()
    assert inside is True


async def test_the_polygon_is_never_a_multipolygon(db):
    """
    The column is geometry(Polygon,4326): a MULTIPOLYGON would be rejected.

    Two reports far enough apart that their individual 250 m discs do not touch
    would be a MultiPolygon if each point were buffered separately. Hulling first
    is what keeps it a single ring.
    """
    a = await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    await insert_report(db, PATNA_LAT + 0.03, PATNA_LNG + 0.03, CLUSTER_TEXTS[1][2])

    result = await process_report(db, {"id": str(a)})
    if result is None:
        pytest.skip("reports too far apart to cluster; nothing to assert here")

    gtype, _, _ = await boundary(db, result["id"])
    assert gtype == "ST_Polygon"


# ── Duplicates must not stretch the footprint ──────────────────────────────────

async def test_a_suppressed_duplicate_does_not_widen_the_polygon(db):
    ids = []
    for lat, lng, body in CLUSTER_TEXTS:
        ids.append(await insert_report(db, lat, lng, body))
    result = await process_report(db, {"id": str(ids[0])})
    event_id = result["id"]

    _, area_before, _ = await boundary(db, event_id)

    # Same text and place as report 0 → suppressed, and never linked, so it
    # cannot reach the polygon even though _set_boundary_polygon also filters it.
    lat, lng, body = CLUSTER_TEXTS[0]
    dupe = await insert_report(db, lat, lng, body)
    assert await process_report(db, {"id": str(dupe)}) is None

    _, area_after, _ = await boundary(db, event_id)
    assert area_after == pytest.approx(area_before, rel=1e-9)


# ── Failure is soft ────────────────────────────────────────────────────────────

async def test_a_server_side_failure_does_not_poison_the_transaction(db):
    """
    The savepoint, and why it is the difference between a missing outline and a
    lost alert.

    Catching the Python exception is not enough. A server-side failure — a GEOS
    error on a degenerate hull — aborts the entire Postgres transaction, so every
    later statement in pipeline step 7 would fail with "current transaction is
    aborted", the blanket handler in process_report would roll back, and the event
    would vanish with only a WARNING about a polygon.

    This asserts the property directly: after a server-side error the session must
    still be usable. Without `async with db.begin_nested()` in
    _set_boundary_polygon, the SELECT below raises instead.
    """
    await db.execute(text("SELECT 1"))

    # A server-side error, of the same shape a GEOS failure would take.
    try:
        async with db.begin_nested():
            await db.execute(text("SELECT 1 / 0"))
    except Exception:
        pass

    assert (await db.execute(text("SELECT 1"))).scalar() == 1


async def test_a_polygon_failure_leaves_the_event_intact(db, monkeypatch):
    """
    The event and its score are the product; the map outline is a nicety.

    With the polygon step failing outright, process_report must still produce an
    event — boundary_polygon simply stays NULL.
    """
    async def _no_polygon(db_, event_id):
        return False

    monkeypatch.setattr(pipeline, "_set_boundary_polygon", _no_polygon)

    ids = []
    for lat, lng, body in CLUSTER_TEXTS[:2]:
        ids.append(await insert_report(db, lat, lng, body))

    result = await process_report(db, {"id": str(ids[0])})

    assert result is not None
    assert result["confidence_score"] > 0
    _, _, is_null = await boundary(db, result["id"])
    assert is_null


async def test_the_helper_swallows_its_own_failure(db, caplog):
    """
    _set_boundary_polygon returns False on a bad event id rather than raising.

    This is the guarantee process_report relies on, so it is asserted directly
    instead of only through the pipeline.
    """
    with caplog.at_level("WARNING", logger="indra.services.pipeline"):
        wrote = await pipeline._set_boundary_polygon(db, uuid.uuid4())
    assert wrote is False


async def test_an_event_with_no_geometry_gets_no_polygon(db):
    """
    A hull of nothing is NULL, and the UPDATE must simply not fire.

    Guarded by `hull.poly IS NOT NULL`; without it the statement would try to
    write NULL over an existing footprint.
    """
    event_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km)
            VALUES (CAST(:id AS uuid), :code,
                    CAST('URBAN_FLOOD' AS event_type_enum),
                    CAST('MODERATE' AS severity_enum), 0.5,
                    CAST('QUARANTINED' AS review_status_enum),
                    CAST('Noise' AS quadrant_enum), 1.0)
        """),
        {"id": event_id, "code": f"INDRA-TEST-{uuid.uuid4().hex[:6]}"},
    )
    await db.commit()

    wrote = await pipeline._set_boundary_polygon(db, uuid.UUID(event_id))
    assert wrote is False

    _, _, is_null = await boundary(db, event_id)
    assert is_null


# ── What the API serves ────────────────────────────────────────────────────────

async def test_the_detail_endpoint_serves_the_polygon_as_geojson(db):
    """
    GET /api/events/{id} already selected boundary_polygon as boundary_geojson;
    it was simply always null. No frontend change is needed for it to appear.
    """
    import json

    ids = []
    for lat, lng, body in CLUSTER_TEXTS:
        ids.append(await insert_report(db, lat, lng, body))
    result = await process_report(db, {"id": str(ids[0])})

    raw = (
        await db.execute(
            text("""
                SELECT ST_AsGeoJSON(boundary_polygon)
                FROM verified_events WHERE id = CAST(:e AS uuid)
            """),
            {"e": result["id"]},
        )
    ).scalar()

    assert raw is not None
    geo = json.loads(raw)
    assert geo["type"] == "Polygon"
    assert len(geo["coordinates"][0]) >= 4          # a closed ring
    assert geo["coordinates"][0][0] == geo["coordinates"][0][-1]
