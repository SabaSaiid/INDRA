"""
T9 — Integration tests for GeoClusteringService.

Requires a live Postgres with PostGIS:
    docker compose up -d && alembic upgrade head
    pytest -m integration

Fixture: 7 reports — 5 tight around Patna (all within ~2 km), and 2 isolated
outliers near Gaya, ~30 km from each other so that neither can form a cluster
of its own at DBSCAN_MIN_SAMPLES=2.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.services.geo_clustering import GeoClusteringService

pytestmark = pytest.mark.integration


# 5 tight reports around Kankarbagh, Patna
TIGHT = [
    (25.5941, 85.1376, "Water entering ground floor shops near Kankarbagh main road"),
    (25.5955, 85.1390, "Kankarbagh underpass completely submerged, cars stuck"),
    (25.5930, 85.1360, "Knee deep water outside my house, drain overflowing"),
    (25.5968, 85.1402, "Flooding on the road to Patna junction, buses diverted"),
    (25.5920, 85.1345, "Sewage water mixed with rain water on the street here"),
]

# 2 isolated outliers, ~30 km apart from each other and ~100 km from Patna
OUTLIERS = [
    (24.7900, 85.0000, "Light drizzle reported here, nothing serious"),
    (24.7500, 85.3100, "Road repair work causing a minor traffic jam"),
]


@pytest_asyncio.fixture
async def db():
    """A session against the live database, cleaned before and after."""
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


async def seed(db, points):
    """Insert reports and return their ids, in the order given."""
    ids = []
    for lat, lng, body in points:
        rid = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO raw_reports
                    (id, source_type, raw_text, latitude, longitude, geom_point)
                VALUES (:id, 'CITIZEN_APP', :t, :lat, :lng,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
            """),
            {"id": str(rid), "t": body, "lat": lat, "lng": lng},
        )
        ids.append(rid)
    await db.commit()
    return ids


@pytest_asyncio.fixture
async def seeded(db):
    """The 7-report fixture. Returns (service, tight_ids, outlier_ids)."""
    tight_ids = await seed(db, TIGHT)
    outlier_ids = await seed(db, OUTLIERS)
    return GeoClusteringService(db), tight_ids, outlier_ids


# ── cluster_unassigned_reports() ───────────────────────────────────────────────

async def test_five_tight_reports_form_exactly_one_cluster(seeded):
    service, tight_ids, outlier_ids = seeded

    clusters = await service.cluster_unassigned_reports()

    assert len(clusters) == 1
    assert clusters[0]["size"] == 5
    assert set(clusters[0]["report_ids"]) == set(tight_ids)


async def test_isolated_outliers_appear_in_no_cluster(seeded):
    service, tight_ids, outlier_ids = seeded

    clusters = await service.cluster_unassigned_reports()
    clustered = {rid for c in clusters for rid in c["report_ids"]}

    for outlier in outlier_ids:
        assert outlier not in clustered


# ── get_cluster_stats() ────────────────────────────────────────────────────────

async def test_cluster_stats_describe_the_tight_cluster(seeded):
    service, tight_ids, _ = seeded

    stats = await service.get_cluster_stats(tight_ids)

    assert stats["count"] == 5

    # Centroid within 2 km of the arithmetic mean of the 5 points.
    mean_lat = sum(p[0] for p in TIGHT) / 5
    mean_lng = sum(p[1] for p in TIGHT) / 5
    assert stats["centroid_lat"] == pytest.approx(mean_lat, abs=0.02)
    assert stats["centroid_lng"] == pytest.approx(mean_lng, abs=0.02)

    # The fixture spans well under 2 km corner to corner.
    assert 0.0 < stats["max_pairwise_km"] <= 2.0
    assert 0.0 < stats["radius_km"] <= stats["max_pairwise_km"]


async def test_cluster_stats_of_empty_input_is_safe(seeded):
    """The pipeline must not crash on an empty cluster."""
    service, _, _ = seeded

    stats = await service.get_cluster_stats([])

    assert stats["count"] == 0
    assert stats["centroid_lat"] is None
    assert stats["max_pairwise_km"] == 0.0


# ── assign_reports_to_event() + idempotency ────────────────────────────────────

async def make_event(db) -> uuid.UUID:
    eid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant)
            VALUES (:id, :code, 'URBAN_FLOOD', 'HIGH', 0.8,
                    'PENDING_HUMAN_REVIEW', 'Unverified Threat')
        """),
        {"id": str(eid), "code": f"TEST-{str(eid)[:8]}"},
    )
    await db.commit()
    return eid


async def test_assign_reports_to_event_links_all_five(seeded, db):
    service, tight_ids, _ = seeded
    eid = await make_event(db)

    updated = await service.assign_reports_to_event(tight_ids, eid)

    assert updated == 5
    count = (
        await db.execute(
            text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": str(eid)},
        )
    ).scalar()
    assert count == 5


async def test_clustering_is_idempotent_after_assignment(seeded, db):
    """
    The one not to skip: without this the consumer would re-cluster and
    re-score the same reports on every message.
    """
    service, tight_ids, _ = seeded
    eid = await make_event(db)

    first = await service.cluster_unassigned_reports()
    assert len(first) == 1

    await service.assign_reports_to_event(tight_ids, eid)

    second = await service.cluster_unassigned_reports()
    assert second == []


async def test_assignment_does_not_steal_already_linked_reports(seeded, db):
    """A second event must not re-link reports that belong to the first."""
    service, tight_ids, _ = seeded
    first_event = await make_event(db)
    second_event = await make_event(db)

    assert await service.assign_reports_to_event(tight_ids, first_event) == 5
    assert await service.assign_reports_to_event(tight_ids, second_event) == 0

    still_first = (
        await db.execute(
            text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": str(first_event)},
        )
    ).scalar()
    assert still_first == 5


# ── assign_h3_cells() / update_geom_points() ───────────────────────────────────

async def test_h3_cells_assigned_to_all_and_tight_cluster_shares_cells(seeded, db):
    service, tight_ids, _ = seeded

    await service.assign_h3_cells()

    rows = (await db.execute(text("SELECT h3_res8 FROM raw_reports"))).fetchall()
    assert len(rows) == 7
    assert all(r[0] is not None for r in rows)

    tight_cells = (
        await db.execute(
            text("SELECT DISTINCT h3_res8 FROM raw_reports WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(i) for i in tight_ids]},
        )
    ).fetchall()
    assert len(tight_cells) <= 2


async def test_update_geom_points_backfills_missing_geometry(db):
    """A report inserted without geom_point gets one from its lat/lng."""
    rid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude)
            VALUES (:id, 'CITIZEN_APP', 'no geometry on insert', 25.5941, 85.1376)
        """),
        {"id": str(rid)},
    )
    await db.commit()

    updated = await GeoClusteringService(db).update_geom_points()
    assert updated >= 1

    geom = (
        await db.execute(
            text("SELECT ST_AsText(geom_point) FROM raw_reports WHERE id = CAST(:id AS uuid)"),
            {"id": str(rid)},
        )
    ).scalar()
    assert geom == "POINT(85.1376 25.5941)"


async def test_suppressed_duplicates_are_not_clustered(db):
    ids = await seed(db, TIGHT)
    dupe = (await seed(db, [TIGHT[0]]))[0]
    await db.execute(
        text("UPDATE raw_reports SET duplicate_of = CAST(:o AS uuid) WHERE id = CAST(:id AS uuid)"),
        {"o": str(ids[0]), "id": str(dupe)},
    )
    await db.commit()

    clusters = await GeoClusteringService(db).cluster_unassigned_reports()

    assert len(clusters) == 1
    assert clusters[0]["size"] == 5
    assert dupe not in clusters[0]["report_ids"]
