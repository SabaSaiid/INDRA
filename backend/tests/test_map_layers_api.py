"""
The two map layers added after the console was found showing a single pin.

The database held 112 real CAP warnings from CWC, IMD and the state SDMAs,
and four citizen reports belonging to no event. None of it could reach the
map: alerts had no coordinates to draw at, and there was no endpoint for a
report that had not become an event (BUG-037).

The assertions that matter here are the ones about what is *left off*. An
alert whose scope is a mandal has no district-level location, and pinning it
to a district centroid would draw an official warning in the wrong place.
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def clean_db():
    async with async_session() as db:
        await wipe_event_tables(db)
        try:
            yield db
        finally:
            await wipe_event_tables(db)


async def _insert_report(db, lat, lng, body, event_id=None, duplicate_of=None):
    rid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 district, state, event_id, duplicate_of)
            VALUES (CAST(:id AS uuid), 'CITIZEN_APP', :t, :lat, :lng,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    'Patna', 'Bihar',
                    CAST(:eid AS uuid), CAST(:dup AS uuid))
        """),
        {
            "id": str(rid), "t": body, "lat": lat, "lng": lng,
            "eid": str(event_id) if event_id else None,
            "dup": str(duplicate_of) if duplicate_of else None,
        },
    )
    return rid


class TestFieldReportsLayer:
    async def test_an_unfused_report_is_returned_with_its_place(self, api, clean_db):
        await _insert_report(clean_db, 25.5941, 85.1376, "Water rising near the underpass")
        await clean_db.commit()

        rows = (await api.get("/api/reports/recent?hours=720")).json()
        assert len(rows) == 1
        assert rows[0]["district"] == "Patna"
        assert rows[0]["state"] == "Bihar"
        assert rows[0]["fused"] is False

    async def test_a_suppressed_duplicate_is_not_drawn(self, api, clean_db):
        """
        Counting a suppressed duplicate as a separate sighting is the exact
        double-count dedup exists to prevent. Drawing it would undo that work
        on the screen — the same incident would look like two.
        """
        original = await _insert_report(clean_db, 25.5941, 85.1376, "Water rising here")
        await _insert_report(
            clean_db, 25.5941, 85.1376, "Water rising here too", duplicate_of=original
        )
        await clean_db.commit()

        rows = (await api.get("/api/reports/recent?hours=720")).json()
        assert [r["id"] for r in rows] == [str(original)]

    async def test_reports_already_on_the_map_as_an_event_are_not_drawn_twice(
        self, api, clean_db
    ):
        event_id = uuid.uuid4()
        await clean_db.execute(
            text("""
                INSERT INTO verified_events
                    (id, event_code, event_type, severity, confidence_score,
                     review_status, quadrant, center_point)
                VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD', 'MODERATE', 0.5,
                        'QUARANTINED', 'Noise',
                        ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326))
            """),
            {"id": str(event_id), "code": f"INDRA-ML-{str(event_id)[:6]}"},
        )
        await _insert_report(clean_db, 25.5941, 85.1376, "Fused report", event_id=event_id)
        unfused = await _insert_report(clean_db, 25.5942, 85.1377, "Unfused report")
        await clean_db.commit()

        rows = (await api.get("/api/reports/recent?hours=720")).json()
        assert [r["id"] for r in rows] == [str(unfused)]

        # ...but they are reachable when explicitly asked for.
        everything = (
            await api.get("/api/reports/recent?hours=720&unfused_only=false")
        ).json()
        assert len(everything) == 2

    async def test_an_empty_layer_is_an_empty_list_not_demo_data(self, api, clean_db):
        await clean_db.commit()
        rows = (await api.get("/api/reports/recent?hours=720")).json()
        assert rows == []


class TestAgencyAlertCoordinates:
    """
    NDMA answers 403 on the CAP polygon endpoint, so no stored alert has a
    geometry and the coordinates come from resolving area_desc.
    """

    async def _insert_alert(self, db, area_desc):
        alert_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO agency_alerts
                    (id, identifier, source_feed, sender, event, area_desc,
                     sent_at, expires_at, fetched_at)
                VALUES (CAST(:id AS uuid), :ident, 'SACHET', 'TEST-SDMA', 'Flood',
                        :area, NOW(), NOW() + INTERVAL '6 hours', NOW())
            """),
            {"id": str(alert_id), "ident": str(alert_id), "area": area_desc},
        )
        await db.commit()
        return str(alert_id)

    async def _fetch(self, api, alert_id):
        rows = (await api.get("/api/alerts/agency?limit=200")).json()
        return next(r for r in rows if r["id"] == alert_id)

    async def test_a_district_alert_gets_coordinates(self, api, clean_db):
        alert_id = await self._insert_alert(
            clean_db, "Ganga, Bhagalpur, Bhagalpur, Bihar"
        )
        try:
            alert = await self._fetch(api, alert_id)
            assert alert["lat"] is not None and alert["lng"] is not None
            assert alert["location_label"] == "Bhagalpur"
            assert alert["location_precision"] == "district"
        finally:
            await clean_db.execute(
                text("DELETE FROM agency_alerts WHERE id = CAST(:id AS uuid)"),
                {"id": alert_id},
            )
            await clean_db.commit()

    async def test_a_state_wide_alert_is_marked_as_state_level(self, api, clean_db):
        alert_id = await self._insert_alert(clean_db, "6 districts of Kerala")
        try:
            alert = await self._fetch(api, alert_id)
            assert alert["location_precision"] == "state"
            assert alert["location_label"] == "Kerala"
            assert alert["lat"] is not None
        finally:
            await clean_db.execute(
                text("DELETE FROM agency_alerts WHERE id = CAST(:id AS uuid)"),
                {"id": alert_id},
            )
            await clean_db.commit()

    async def test_a_mandal_alert_is_left_off_the_map(self, api, clean_db):
        """
        Below district level there is no honest point to draw. Null keeps the
        marker off rather than putting an official warning somewhere it is not.
        """
        alert_id = await self._insert_alert(
            clean_db, "atp-bukkarayasamudram, atp-singanamala mandals"
        )
        try:
            alert = await self._fetch(api, alert_id)
            assert alert["lat"] is None
            assert alert["lng"] is None
            assert alert["location_label"] is None
            assert alert["districts_matched"] == 0
        finally:
            await clean_db.execute(
                text("DELETE FROM agency_alerts WHERE id = CAST(:id AS uuid)"),
                {"id": alert_id},
            )
            await clean_db.commit()

    async def test_a_multi_district_alert_reports_how_many_it_covers(
        self, api, clean_db
    ):
        """The marker sits on one district; the count stops that reading as the scope."""
        alert_id = await self._insert_alert(
            clean_db, "Chamarajanagara,Kodagu,Mysuru districts of Karnataka"
        )
        try:
            alert = await self._fetch(api, alert_id)
            assert alert["districts_matched"] == 3
            assert alert["location_label"] == "Chamarajanagara"
        finally:
            await clean_db.execute(
                text("DELETE FROM agency_alerts WHERE id = CAST(:id AS uuid)"),
                {"id": alert_id},
            )
            await clean_db.commit()
