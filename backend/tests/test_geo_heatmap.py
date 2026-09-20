"""
T5 (Day 5) — GET /api/geo/heatmap.

The first reader of `raw_reports.h3_res8`, which has had two writers since Day 1
and no consumer at all.

The property that matters is that zooming out is **aggregation, not
re-binning**: a res-7 count must be the exact sum of its res-8 children. H3
guarantees each cell has one parent at the next coarser resolution, so that sum
is exact and nothing is smoothed, spread or double counted. Every number the heat
layer draws traces back to rows in raw_reports.
"""

import uuid
from datetime import datetime, timedelta, timezone

import h3
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session, get_db
from app.core.config import get_settings
from app.main import app
from tests.conftest import wipe_event_tables

pytestmark = pytest.mark.integration

PATNA_LAT, PATNA_LNG = 25.5941, 85.1376


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


@pytest_asyncio.fixture
async def api(db):
    import httpx

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def add_report(db, lat, lng, *, hours_ago=0, duplicate_of=None, linked=None):
    """Insert a report with its h3_res8 filled the way api/reports.py does."""
    rid = uuid.uuid4()
    cell = h3.latlng_to_cell(lat, lng, 8)
    await db.execute(
        text("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 h3_res8, created_at, duplicate_of, event_id)
            VALUES (:id, 'CITIZEN_APP', 'water on the road', :lat, :lng,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :cell, NOW() - make_interval(hours => :h),
                    CAST(:dup AS uuid), CAST(:ev AS uuid))
        """),
        {
            "id": str(rid), "lat": lat, "lng": lng, "cell": cell,
            "h": hours_ago,
            "dup": str(duplicate_of) if duplicate_of else None,
            "ev": str(linked) if linked else None,
        },
    )
    await db.commit()
    return rid, cell


async def make_event(db) -> uuid.UUID:
    event_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km)
            VALUES (CAST(:id AS uuid), :code,
                    CAST('URBAN_FLOOD' AS event_type_enum),
                    CAST('MODERATE' AS severity_enum), 0.6,
                    CAST('QUARANTINED' AS review_status_enum),
                    CAST('Noise' AS quadrant_enum), 1.0)
        """),
        {"id": str(event_id), "code": f"INDRA-T-{uuid.uuid4().hex[:6]}"},
    )
    await db.commit()
    return event_id


def cells_by_id(body):
    return {c["h3"]: c for c in body["cells"]}


# ── Two neighbouring res-8 cells that share a res-7 parent ────────────────────

async def _seed_two_cells(db):
    """
    3 reports in one res-8 cell and 2 in another, both under one res-7 parent.

    The second cell is found rather than assumed: neighbouring res-8 cells do not
    always share a parent, so the fixture asks H3 which neighbour does.
    """
    home = h3.latlng_to_cell(PATNA_LAT, PATNA_LNG, 8)
    parent = h3.cell_to_parent(home, 7)

    sibling = next(
        c for c in h3.grid_disk(home, 2)
        if c != home and h3.cell_to_parent(c, 7) == parent
    )

    for _ in range(3):
        lat, lng = h3.cell_to_latlng(home)
        await add_report(db, lat, lng)
    for _ in range(2):
        lat, lng = h3.cell_to_latlng(sibling)
        await add_report(db, lat, lng)

    return home, sibling, parent


async def test_res8_returns_each_cell_with_its_own_count(db, api):
    home, sibling, _ = await _seed_two_cells(db)

    body = (await api.get("/api/geo/heatmap?resolution=8")).json()

    assert body["resolution"] == 8
    assert body["window"] == "24h"
    assert len(body["cells"]) == 2

    by_id = cells_by_id(body)
    assert by_id[home]["report_count"] == 3
    assert by_id[sibling]["report_count"] == 2


async def test_res7_is_the_exact_sum_of_its_res8_children(db, api):
    """The whole point of H3 here: zooming out adds up, it does not re-bin."""
    _, _, parent = await _seed_two_cells(db)

    body = (await api.get("/api/geo/heatmap?resolution=7")).json()

    assert body["resolution"] == 7
    assert len(body["cells"]) == 1
    assert body["cells"][0]["h3"] == parent
    assert body["cells"][0]["report_count"] == 5


async def test_every_resolution_totals_the_same_reports(db, api):
    """Coarsening must conserve the total. Five reports are five reports."""
    await _seed_two_cells(db)

    totals = {}
    for res in (6, 7, 8):
        body = (await api.get(f"/api/geo/heatmap?resolution={res}")).json()
        totals[res] = sum(c["report_count"] for c in body["cells"])

    assert totals == {6: 5, 7: 5, 8: 5}


# ── The time window ───────────────────────────────────────────────────────────

async def test_a_25_hour_old_report_is_outside_24h_and_inside_48h(db, api):
    await add_report(db, PATNA_LAT, PATNA_LNG, hours_ago=25)

    assert (await api.get("/api/geo/heatmap?window=24h")).json()["cells"] == []

    body48 = (await api.get("/api/geo/heatmap?window=48h")).json()
    assert sum(c["report_count"] for c in body48["cells"]) == 1

    body7d = (await api.get("/api/geo/heatmap?window=7d")).json()
    assert sum(c["report_count"] for c in body7d["cells"]) == 1


# ── Duplicates ────────────────────────────────────────────────────────────────

async def test_a_suppressed_duplicate_is_counted_nowhere(db, api):
    """
    A repost is not a second piece of evidence.

    Counting it would make the heat map brighter where a report went viral rather
    than where the water is deeper.
    """
    original, _ = await add_report(db, PATNA_LAT, PATNA_LNG)
    await add_report(db, PATNA_LAT, PATNA_LNG, duplicate_of=original)

    body = (await api.get("/api/geo/heatmap?resolution=8")).json()

    assert len(body["cells"]) == 1
    assert body["cells"][0]["report_count"] == 1
    assert body["cells"][0]["linked_report_count"] == 0


# ── linked_report_count ───────────────────────────────────────────────────────

async def test_linked_report_count_counts_only_fused_reports(db, api):
    """
    The difference between "people are reporting here" and "this is an incident".
    """
    event_id = await make_event(db)
    await add_report(db, PATNA_LAT, PATNA_LNG, linked=event_id)
    await add_report(db, PATNA_LAT, PATNA_LNG)

    body = (await api.get("/api/geo/heatmap?resolution=8")).json()

    cell = body["cells"][0]
    assert cell["report_count"] == 2
    assert cell["linked_report_count"] == 1


# ── Cell geometry ─────────────────────────────────────────────────────────────

async def test_cell_coordinates_are_the_h3_centre(db, api):
    """
    lat/lng must be the cell's own centre, not the mean of its reports.

    A heat layer draws the hexagon; giving it a drifting centroid would put the
    hexagon somewhere no cell actually is.
    """
    await add_report(db, PATNA_LAT, PATNA_LNG)

    cell = (await api.get("/api/geo/heatmap?resolution=8")).json()["cells"][0]
    expected_lat, expected_lng = h3.cell_to_latlng(cell["h3"])

    assert cell["lat"] == pytest.approx(expected_lat, abs=1e-9)
    assert cell["lng"] == pytest.approx(expected_lng, abs=1e-9)


async def test_cells_come_back_densest_first(db, api):
    home, sibling, _ = await _seed_two_cells(db)

    cells = (await api.get("/api/geo/heatmap?resolution=8")).json()["cells"]

    counts = [c["report_count"] for c in cells]
    assert counts == sorted(counts, reverse=True)
    assert cells[0]["h3"] == home


# ── Validation and empties ────────────────────────────────────────────────────

@pytest.mark.parametrize("res", [5, 9, 0, -1, 15])
async def test_an_unsupported_resolution_is_422(api, res):
    """
    Finer than res 8 cannot be aggregated from stored data, only invented; coarser
    than 6 is not offered. Either way, say so rather than silently substituting.
    """
    assert (await api.get(f"/api/geo/heatmap?resolution={res}")).status_code == 422


@pytest.mark.parametrize("window", ["1y", "12h", "", "7days", "all"])
async def test_an_unsupported_window_is_422(api, window):
    r = await api.get(f"/api/geo/heatmap?window={window}")
    assert r.status_code == 422
    assert "window must be one of" in r.text


async def test_no_reports_in_the_window_is_an_empty_200(db, api):
    body = (await api.get("/api/geo/heatmap")).json()
    assert body["cells"] == []
    assert body["resolution"] == 8
    assert body["generated_at"]


async def test_the_default_is_24h_at_the_stored_resolution(api):
    body = (await api.get("/api/geo/heatmap")).json()
    assert (body["window"], body["resolution"]) == ("24h", 8)


# ── Failure behaviour ─────────────────────────────────────────────────────────

async def test_a_database_error_is_503_when_demo_mode_is_off(api, monkeypatch):
    """
    The endpoint must not invent a heat map. With DEMO_MODE off a broken database
    is a 503, not an empty map that reads as "no flooding anywhere".
    """
    monkeypatch.setattr(get_settings(), "DEMO_MODE", False)

    class Broken:
        async def execute(self, *a, **k):
            raise RuntimeError("connection refused")

    async def _db():
        yield Broken()

    app.dependency_overrides[get_db] = _db
    try:
        r = await api.get("/api/geo/heatmap")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── The roll-up, without a database ───────────────────────────────────────────

def test_roll_up_drops_an_unparseable_cell_rather_than_guessing():
    """
    A heat map is a claim about where reports are; an unreadable cell id has
    nothing to say about that, so it is dropped with a warning, not placed.
    """
    from app.api.geo import _roll_up

    good = h3.latlng_to_cell(PATNA_LAT, PATNA_LNG, 8)
    out = _roll_up([(good, 2, 1), ("not-a-cell", 9, 9)], 7)

    assert len(out) == 1
    assert out[0]["report_count"] == 2


# ── Scale ─────────────────────────────────────────────────────────────────────

async def test_nine_thousand_reports_aggregate_quickly_and_conserve_the_total(db, api):
    """
    The national seed set's volume, at the coarsest resolution.

    Two claims: it answers well inside the 500 ms the dashboard can absorb, and —
    the one that actually matters — the total is conserved exactly at every
    resolution. If coarsening ever dropped or duplicated a report, this is where
    it would show.

    Measured on this machine: ~14 ms at res 6 over 9,400 rows. The assertion is
    set an order of magnitude looser so it fails on a real regression, not on a
    busy laptop.
    """
    import random
    import time

    random.seed(7)
    rows = []
    for _ in range(9_400):
        lat = 25.6 + random.uniform(-1.5, 1.5)
        lng = 85.1 + random.uniform(-1.5, 1.5)
        rows.append({"lat": lat, "lng": lng, "cell": h3.latlng_to_cell(lat, lng, 8)})

    await db.execute(
        text("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 h3_res8, created_at)
            VALUES (gen_random_uuid(), 'CITIZEN_APP', 'x', :lat, :lng,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :cell, NOW())
        """),
        rows,
    )
    await db.commit()

    for resolution in (6, 7, 8):
        started = time.monotonic()
        body = (
            await api.get(f"/api/geo/heatmap?window=7d&resolution={resolution}")
        ).json()
        elapsed_ms = (time.monotonic() - started) * 1000

        assert sum(c["report_count"] for c in body["cells"]) == 9_400, resolution
        assert elapsed_ms < 500, (resolution, elapsed_ms)

    # Coarser resolutions must fold cells together, never split them.
    counts = {}
    for resolution in (6, 7, 8):
        body = (
            await api.get(f"/api/geo/heatmap?window=7d&resolution={resolution}")
        ).json()
        counts[resolution] = len(body["cells"])
    assert counts[6] < counts[7] < counts[8]
