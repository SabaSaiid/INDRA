"""
Phase 1 T4 — the citizen's tracking docket and GET /api/reports/track/{docket}.

The first half is unit-level (generation, normalisation, the status rules).
The second half follows real reports through the real pipeline on
`indra_test`, from submission to a commander's decision.
"""

import re
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.services import ingest

DOCKET = re.compile(r"^R-[0-9A-HJKMNP-TV-Z]{8}$")


# ── Generation ─────────────────────────────────────────────────────────────────

def test_a_docket_is_r_and_eight_unambiguous_characters():
    for _ in range(200):
        assert DOCKET.match(ingest.new_docket())


def test_the_alphabet_leaves_out_every_character_that_reads_as_another():
    assert len(ingest.DOCKET_ALPHABET) == 32
    assert not set("ILOU") & set(ingest.DOCKET_ALPHABET)


def test_ten_thousand_dockets_do_not_collide():
    """
    Random, 40 bits each: a working generator repeats about once in 22,000
    runs of this test, which the unique constraint and the retry absorb (see
    the collision test below). One repeat is therefore tolerated; a broken
    generator — a fixed seed, a counter, low entropy — repeats thousands of
    times and fails.
    """
    dockets = [ingest.new_docket() for _ in range(10_000)]
    assert len(set(dockets)) >= 9_999


# ── Normalisation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "typed",
    ["R-7K3M9QX2", "r-7k3m9qx2", "R7K3M9QX2", "7K3M9QX2", " R-7K3M 9QX2 ", "R-7K3M-9QX2"],
)
def test_case_spaces_hyphens_and_the_prefix_are_forgiven(typed):
    assert ingest.normalise_docket(typed) == "R-7K3M9QX2"


@pytest.mark.parametrize("typed, meant", [("R-7K3M9QXO", "R-7K3M9QX0"), ("R-7K3M9QXI", "R-7K3M9QX1"), ("R-7K3M9QXL", "R-7K3M9QX1")])
def test_letters_that_look_like_digits_are_read_as_the_digits(typed, meant):
    assert ingest.normalise_docket(typed) == meant


@pytest.mark.parametrize("typed", ["", "hello", "R-7K3M9QX", "R-7K3M9QX22", "R-7K3M9QXU", "R-7K3M9QX!", None])
def test_what_cannot_be_a_docket_is_none(typed):
    assert ingest.normalise_docket(typed) is None


def test_a_docket_one_character_short_is_not_read_as_a_different_docket():
    """R is also a docket character; "R-7K3M9QX" must not become R-R7K3M9QX."""
    assert ingest.normalise_docket("R-7K3M9QX") is None
    assert ingest.normalise_docket("R7K3M9QX") == "R-R7K3M9QX"   # no hyphen: an 8-character body


# ── The status rules ───────────────────────────────────────────────────────────

EVENT = uuid.uuid4()
ORIGINAL = uuid.uuid4()


@pytest.mark.parametrize(
    "duplicate_of, event_id, review_status, processed_at, status",
    [
        (None, None, None, None, "received"),
        (None, None, None, "2026-09-23T10:00:00Z", "not_yet_an_event"),
        (ORIGINAL, None, None, "2026-09-23T10:00:00Z", "duplicate"),
        (None, EVENT, "QUARANTINED", "2026-09-23T10:00:00Z", "part_of_event"),
        (None, EVENT, "PENDING_HUMAN_REVIEW", None, "part_of_event"),
        (None, EVENT, "HUMAN_APPROVED", None, "event_approved"),
        (None, EVENT, "AUTO_PUBLISHED", None, "event_approved"),
        (None, EVENT, "REJECTED", None, "event_rejected"),
    ],
)
def test_docket_status(duplicate_of, event_id, review_status, processed_at, status):
    assert ingest.docket_status(duplicate_of, event_id, review_status, processed_at) == status


# ── End to end, on the real pipeline ───────────────────────────────────────────

CLUSTER = [
    (25.5941, 85.1376, "Water entering ground floor shops near Kankarbagh main road"),
    (25.5955, 85.1390, "Kankarbagh underpass completely submerged, cars stuck"),
    (25.5930, 85.1360, "Knee deep water outside my house, drain overflowing"),
    (25.5968, 85.1402, "Flooding on the road to Patna junction, buses diverted"),
    (25.5920, 85.1345, "Sewage water mixed with rain water on the street here"),
]


@pytest.fixture
def fixed_weather(monkeypatch):
    from app.services import pipeline

    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest_asyncio.fixture
async def db():
    from app.core.database import async_session

    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def submit(api, lat, lng, body):
    r = await api.post("/api/reports/submit", json={"latitude": lat, "longitude": lng, "text": body})
    assert r.status_code == 202
    return r.json()


async def track(api, docket):
    r = await api.get(f"/api/reports/track/{docket}")
    assert r.status_code == 200, r.text
    return r.json()


async def process(db, report_id):
    from app.services.pipeline import process_report

    return await process_report(db, {"id": report_id})


@pytest.mark.integration
async def test_the_submit_body_carries_a_docket_and_the_row_keeps_it(api, db):
    res = await submit(api, *CLUSTER[0])

    assert DOCKET.match(res["docket"])
    stored = (
        await db.execute(
            text("SELECT docket FROM raw_reports WHERE id = CAST(:id AS uuid)"), {"id": res["id"]}
        )
    ).scalar()
    assert stored == res["docket"]


@pytest.mark.integration
async def test_a_report_is_followed_from_submission_to_approval(api, db, fixed_weather):
    first = await submit(api, *CLUSTER[0])
    assert (await track(api, first["docket"]))["status"] == "received"

    # Processed, and alone: nothing corroborates it yet.
    await process(db, first["id"])
    alone = await track(api, first["docket"])
    assert alone["status"] == "not_yet_an_event"
    assert alone["event_code"] is None

    # The cluster forms and the report is part of an event.
    for lat, lng, body in CLUSTER[1:]:
        res = await submit(api, lat, lng, body)
        await process(db, res["id"])
    joined = await track(api, first["docket"])
    assert joined["status"] == "part_of_event"
    assert joined["event_code"].startswith("INDRA-")
    assert joined["review_status"] in {"QUARANTINED", "PENDING_HUMAN_REVIEW"}
    assert (joined["district"], joined["state"]) == ("Patna", "Bihar")

    # A commander approves the event.
    await db.execute(text("UPDATE verified_events SET review_status = 'HUMAN_APPROVED'"))
    await db.commit()
    approved = await track(api, first["docket"])
    assert (approved["status"], approved["review_status"]) == ("event_approved", "HUMAN_APPROVED")

    await db.execute(text("UPDATE verified_events SET review_status = 'REJECTED'"))
    await db.commit()
    assert (await track(api, first["docket"]))["status"] == "event_rejected"


@pytest.mark.integration
async def test_a_suppressed_duplicate_says_so(api, db, fixed_weather):
    await submit(api, *CLUSTER[0])
    copy = await submit(api, CLUSTER[0][0] + 0.0027, CLUSTER[0][1], CLUSTER[0][2])

    await process(db, copy["id"])

    assert (await track(api, copy["docket"]))["status"] == "duplicate"


@pytest.mark.integration
async def test_a_docket_typed_in_lower_case_finds_the_same_report(api, db):
    res = await submit(api, *CLUSTER[0])

    assert await track(api, res["docket"].lower()) == await track(api, res["docket"])


@pytest.mark.integration
@pytest.mark.parametrize("docket", ["R-00000000", "R-7K3M9QXU", "not-a-docket"])
async def test_an_unknown_or_impossible_docket_is_the_same_404(api, db, docket):
    r = await api.get(f"/api/reports/track/{docket}")

    assert r.status_code == 404
    assert r.json() == {"detail": "No report with that docket"}


@pytest.mark.integration
async def test_the_answer_never_carries_the_text_the_place_or_the_reporter(api, db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "test-salt")
    r = await api.post(
        "/api/reports/submit",
        json={"latitude": 25.5941, "longitude": 85.1376, "text": "Water rising at the Boring Road crossing"},
        headers={"X-Reporter-Id": "device-123"},
    )
    body = await track(api, r.json()["docket"])

    assert set(body) == {
        "docket", "received_at", "status", "event_code", "review_status", "district", "state",
    }
    raw = str(body)
    assert "Boring Road" not in raw and "25.5941" not in raw and "85.1376" not in raw
    stored_hash = (
        await db.execute(text("SELECT reporter_hash FROM raw_reports WHERE docket = :d"), {"d": body["docket"]})
    ).scalar()
    assert stored_hash and stored_hash not in raw


@pytest.mark.integration
async def test_a_docket_that_is_already_taken_is_replaced_not_fatal(db, monkeypatch):
    taken = "R-7K3M9QX2"
    await db.execute(
        text("""
            INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, docket)
            VALUES (CAST(:id AS uuid), 'CITIZEN_APP', 'an earlier report', 25.59, 85.13, :d)
        """),
        {"id": str(uuid.uuid4()), "d": taken},
    )
    await db.commit()
    issued = iter([taken, taken, "R-AAAAAAAA"])
    monkeypatch.setattr(ingest, "new_docket", lambda: next(issued))

    stored = await ingest.store_report(
        db, source_type="CITIZEN_APP", raw_text="Water on the road", latitude=25.5941, longitude=85.1376,
    )

    assert stored.docket == "R-AAAAAAAA"
    assert (await db.execute(text("SELECT count(*) FROM raw_reports"))).scalar() == 2


@pytest.mark.integration
async def test_a_feed_item_gets_no_docket(db):
    stored = await ingest.store_report(
        db, source_type="NEWS_MEDIA", raw_text="Waterlogging reported across Patna", latitude=25.5941,
        longitude=85.1376, issue_docket=False,
    )

    assert stored.docket is None
