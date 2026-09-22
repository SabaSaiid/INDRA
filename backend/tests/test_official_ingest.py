"""
BUG-025 — a trusted source can reach the pipeline, and only through a token.

Source reliability had a real prior table and could never move in a live run,
because the citizen route stamps every report CITIZEN_APP — correctly, since a
client that names its own source can claim 1.00. POST /api/reports/official is
the authenticated path: COMMANDER or ADMIN, stored as OFFICIAL_DISPATCH, with
the operator recorded in `submitted_by`.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services.pipeline import process_report
from tests.conftest import wipe_event_tables
from tests.test_pipeline import CLUSTER_TEXTS, insert_report
from tests.test_review_api import api, fixed_weather, tokens  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

DISPATCH = {
    "latitude": 25.5949,
    "longitude": 85.1381,
    "text": "District control room confirms waterlogging at Kankarbagh, SDRF team en route",
}


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


async def _row(db, report_id):
    return (
        await db.execute(
            text("SELECT source_type, submitted_by FROM raw_reports WHERE id = CAST(:id AS uuid)"),
            {"id": report_id},
        )
    ).first()


@pytest.mark.parametrize("who", ["citizen", "analyst"])
async def test_only_a_commander_or_admin_can_file_an_official_report(api, tokens, db, who):  # noqa: F811
    r = await api.post("/api/reports/official", json=DISPATCH, headers=tokens[who])

    assert r.status_code == 403
    assert (await db.execute(text("SELECT COUNT(*) FROM raw_reports"))).scalar() == 0


async def test_an_anonymous_official_report_is_401_and_stores_nothing(api, db):  # noqa: F811
    r = await api.post("/api/reports/official", json=DISPATCH)

    assert r.status_code == 401
    assert (await db.execute(text("SELECT COUNT(*) FROM raw_reports"))).scalar() == 0


@pytest.mark.parametrize("who", ["commander", "admin"])
async def test_an_official_report_is_stored_as_official_dispatch_with_its_author(api, tokens, db, who):  # noqa: F811
    r = await api.post("/api/reports/official", json=DISPATCH, headers=tokens[who])

    assert r.status_code == 202, r.text
    assert r.json()["source_type"] == "OFFICIAL_DISPATCH"
    source_type, submitted_by = await _row(db, r.json()["id"])
    assert source_type == "OFFICIAL_DISPATCH"
    assert submitted_by == who


async def test_the_citizen_route_still_cannot_claim_a_source(api, db):  # noqa: F811
    """The guard BUG-025 was right to keep: extra fields are ignored, not obeyed."""
    r = await api.post(
        "/api/reports/submit",
        json={**DISPATCH, "source_type": "OFFICIAL_DISPATCH", "submitted_by": "commander"},
    )

    assert r.status_code == 202
    assert r.json()["source_type"] == "CITIZEN_APP"
    source_type, submitted_by = await _row(db, r.json()["id"])
    assert source_type == "CITIZEN_APP"
    assert submitted_by is None


async def test_an_official_report_gets_the_same_coordinate_checks(api, tokens, db):  # noqa: F811
    r = await api.post(
        "/api/reports/official",
        json={**DISPATCH, "latitude": 51.5074, "longitude": -0.1278},
        headers=tokens["commander"],
    )

    assert r.status_code == 422


async def test_one_official_report_lifts_source_reliability_to_one(api, tokens, db):  # noqa: F811
    """
    End to end: four citizen reports and one official dispatch in the same
    Kankarbagh cluster. The factor is the maximum over the cluster's sources,
    so it reads 1.00 instead of the 0.60 every live run has shown until now.
    """
    for lat, lng, body in CLUSTER_TEXTS[:4]:
        await insert_report(db, lat, lng, body)
    r = await api.post("/api/reports/official", json=DISPATCH, headers=tokens["commander"])
    assert r.status_code == 202

    result = await process_report(db, {"id": r.json()["id"]})
    assert result is not None

    receipt = (
        await db.execute(
            text("SELECT verification_receipt FROM verified_events WHERE id = CAST(:id AS uuid)"),
            {"id": str(result["id"])},
        )
    ).scalar()
    factor = next(f for f in receipt["factors"] if f["factor"] == "Source Reliability Index")
    assert factor["state"] == "computed"
    assert factor["score"] == 1.0
    assert receipt["cluster"]["source_types"] == ["CITIZEN_APP", "OFFICIAL_DISPATCH"]


async def test_provenance_names_who_vouched_for_an_official_report(api, tokens, db):  # noqa: F811
    for lat, lng, body in CLUSTER_TEXTS[:4]:
        await insert_report(db, lat, lng, body)
    official_id = (await api.post("/api/reports/official", json=DISPATCH, headers=tokens["commander"])).json()["id"]
    result = await process_report(db, {"id": official_id})

    r = await api.get(f"/api/events/{result['id']}/provenance", headers=tokens["analyst"])

    assert r.status_code == 200
    by_id = {rep["id"]: rep for rep in r.json()["reports"]}
    assert by_id[official_id]["submitted_by"] == "commander"
    assert all(rep["submitted_by"] is None for rid, rep in by_id.items() if rid != official_id)
