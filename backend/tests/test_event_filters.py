"""
Phase 1 T5 — the PS's filters on GET /api/events.

"Date-wise filtering • Event-wise filtering • Location-wise filtering •
Verification status tracking" (PS 26069). Twelve events across three states,
four types, four review statuses and the days around the IST midnight, so every
filter has something to include and something to leave out.
"""

import json
import uuid
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session

pytestmark = pytest.mark.integration

PLACES = {
    "Patna": (85.1376, 25.5941),
    "Gaya": (85.0002, 24.7955),
    "Mumbai": (72.8777, 19.0760),
    "Pune": (73.8567, 18.5204),
    "New Delhi": (77.2090, 28.6139),
    None: (85.3000, 25.9000),
}

# code, type, status, severity, confidence, state, district, verified_at (UTC)
EVENTS = [
    ("E01", "URBAN_FLOOD", "QUARANTINED", "MODERATE", 0.52, "Bihar", "Patna", "2026-09-18T06:00:00+00:00"),
    ("E02", "HEATWAVE", "PENDING_HUMAN_REVIEW", "HIGH", 0.64, "Delhi", "New Delhi", "2026-09-19T06:00:00+00:00"),
    ("E03", "FOG", "HUMAN_APPROVED", "ADVISORY", 0.71, "Delhi", "New Delhi", "2026-09-20T00:00:00+00:00"),
    # 23:30 IST on 20 Sep — 18:00 UTC, still the 20th for an Indian operator.
    ("E04", "URBAN_FLOOD", "PENDING_HUMAN_REVIEW", "HIGH", 0.66, "Bihar", "Patna", "2026-09-20T18:00:00+00:00"),
    # 00:01 IST on 21 Sep.
    ("E05", "THUNDERSTORM", "QUARANTINED", "MODERATE", 0.45, "Maharashtra", "Mumbai", "2026-09-20T18:31:00+00:00"),
    ("E06", "HEATWAVE", "QUARANTINED", "CRITICAL", 0.58, "Maharashtra", "Pune", "2026-09-21T12:00:00+00:00"),
    # 23:59 IST on 19 Sep: one minute before the 20th begins.
    ("E07", "FOG", "QUARANTINED", "ADVISORY", 0.40, "Delhi", "New Delhi", "2026-09-19T18:29:00+00:00"),
    # 00:00 IST on 20 Sep exactly.
    ("E08", "URBAN_FLOOD", "HUMAN_APPROVED", "CRITICAL", 0.81, "Bihar", "Gaya", "2026-09-19T18:30:00+00:00"),
    # 23:59:59 IST on 21 Sep.
    ("E09", "THUNDERSTORM", "PENDING_HUMAN_REVIEW", "HIGH", 0.62, "Maharashtra", "Mumbai", "2026-09-21T18:29:59+00:00"),
    # 00:00 IST on 22 Sep; no district resolved.
    ("E10", "URBAN_FLOOD", "QUARANTINED", "MODERATE", 0.50, "Bihar", None, "2026-09-21T18:30:00+00:00"),
    ("E11", "HEATWAVE", "HUMAN_APPROVED", "HIGH", 0.77, "Delhi", "New Delhi", "2026-09-22T06:00:00+00:00"),
    ("E12", "FOG", "REJECTED", "MODERATE", 0.30, "Bihar", "Patna", "2026-09-17T06:00:00+00:00"),
]
NOT_REJECTED = [e[0] for e in EVENTS if e[2] != "REJECTED"]
# Which sources reported each event; the rest have one citizen report each.
SOURCES = {"E04": ["CITIZEN_APP", "OFFICIAL_DISPATCH"], "E08": ["OFFICIAL_DISPATCH"]}


def code(short):
    return f"INDRA-FLT-{short}"


@pytest_asyncio.fixture
async def events():
    async with async_session() as db:
        await wipe_event_tables(db)
        for short, etype, status, sev, conf, state, district, verified_at in EVENTS:
            lng, lat = PLACES[district]
            event_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO verified_events
                        (id, event_code, event_type, severity, confidence_score, review_status,
                         quadrant, impact_radius_km, center_point, boundary_polygon,
                         verification_receipt, state, district, place_precision, verified_at)
                    VALUES (CAST(:id AS uuid), :code, CAST(:etype AS event_type_enum),
                            CAST(:sev AS severity_enum), :conf, CAST(:status AS review_status_enum),
                            'Noise', 2.0, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                            ST_Buffer(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 0.01),
                            CAST(:receipt AS jsonb), :state, :district, 'district',
                            CAST(:verified_at AS timestamptz))
                """),
                {
                    "id": event_id, "code": code(short), "etype": etype, "sev": sev, "conf": conf,
                    "status": status, "lng": lng, "lat": lat, "receipt": json.dumps({}),
                    "state": state, "district": district,
                    "verified_at": datetime.fromisoformat(verified_at),
                },
            )
            for source in SOURCES.get(short, ["CITIZEN_APP"]):
                await db.execute(
                    text("""
                        INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, event_id)
                        VALUES (CAST(:id AS uuid), CAST(:source AS source_type_enum), 'fixture', :lat, :lng,
                                CAST(:event AS uuid))
                    """),
                    {"id": str(uuid.uuid4()), "source": source, "lat": lat, "lng": lng, "event": event_id},
                )
        await db.commit()
        try:
            yield
        finally:
            await wipe_event_tables(db)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def codes(api, **params):
    r = await api.get("/api/events", params=params)
    assert r.status_code == 200, r.text
    return {e["event_code"].removeprefix("INDRA-FLT-") for e in r.json()}


def assert_422_naming(r, param):
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", param]


# ── Date-wise (IST days) ───────────────────────────────────────────────────────

async def test_a_date_range_is_whole_ist_days(api, events):
    assert await codes(api, **{"from": "2026-09-20", "to": "2026-09-21"}) == {
        "E03", "E04", "E05", "E06", "E08", "E09",
    }


async def test_an_event_at_2330_ist_is_on_that_ist_day(api, events):
    got = await codes(api, **{"from": "2026-09-20", "to": "2026-09-20"})
    assert "E04" in got        # 20 Sep 23:30 IST, though 18:00 UTC
    assert "E08" in got        # 20 Sep 00:00 IST exactly
    assert "E07" not in got    # 19 Sep 23:59 IST
    assert "E05" not in got    # 21 Sep 00:01 IST
    assert got == {"E03", "E04", "E08"}


async def test_the_last_second_of_the_to_day_is_included_and_the_next_midnight_is_not(api, events):
    got = await codes(api, **{"from": "2026-09-21", "to": "2026-09-21"})
    assert "E09" in got        # 21 Sep 23:59:59 IST
    assert "E10" not in got    # 22 Sep 00:00 IST


async def test_a_full_timestamp_is_used_as_given(api, events):
    got = await codes(api, **{"from": "2026-09-20T18:00:00+00:00", "to": "2026-09-20T18:31:00+00:00"})
    assert got == {"E04", "E05"}


async def test_a_timestamp_without_an_offset_is_read_as_ist(api, events):
    # 23:30 IST on 20 Sep, given with no offset.
    got = await codes(api, **{"from": "2026-09-20T23:30:00", "to": "2026-09-20T23:30:00"})
    assert got == {"E04"}


async def test_from_after_to_is_422(api, events):
    assert_422_naming(await api.get("/api/events", params={"from": "2026-09-22", "to": "2026-09-01"}), "from")


async def test_a_range_over_366_days_is_422(api, events):
    assert_422_naming(await api.get("/api/events", params={"from": "2025-01-01", "to": "2026-09-22"}), "from")


async def test_a_full_leap_year_is_allowed(api, events):
    r = await api.get("/api/events", params={"from": "2028-01-01", "to": "2028-12-31"})
    assert r.status_code == 200


@pytest.mark.parametrize("bad", ["20-09-2026", "2026-13-01", "yesterday"])
async def test_a_date_that_is_not_a_date_is_422(api, events, bad):
    assert_422_naming(await api.get("/api/events", params={"from": bad}), "from")


async def test_time_range_still_works_relative_to_now(api, events):
    async with async_session() as db:
        await db.execute(text("""
            INSERT INTO verified_events (id, event_code, event_type, severity, confidence_score,
                                         review_status, quadrant, impact_radius_km, verified_at)
            VALUES (gen_random_uuid(), 'INDRA-FLT-NOW', 'FOG', 'ADVISORY', 0.5,
                    'QUARANTINED', 'Noise', 1.0, NOW() - INTERVAL '1 hour')
        """))
        await db.commit()
    assert await codes(api, time_range="24h") == {"NOW"}


# ── Event-wise ─────────────────────────────────────────────────────────────────

async def test_event_type_takes_a_list(api, events):
    assert await codes(api, event_type="HEATWAVE,FOG") == {"E02", "E03", "E06", "E07", "E11"}


async def test_event_type_ignores_case(api, events):
    assert await codes(api, event_type="heatwave") == {"E02", "E06", "E11"}


async def test_family_selects_every_type_in_it(api, events):
    assert await codes(api, family="water") == {"E01", "E04", "E08", "E10"}
    assert await codes(api, family="convective") == {"E05", "E09"}


async def test_family_and_event_type_both_apply(api, events):
    assert await codes(api, family="thermal", event_type="FOG") == set()


async def test_an_unknown_event_type_is_422_naming_it(api, events):
    assert_422_naming(await api.get("/api/events", params={"event_type": "TORNADO"}), "event_type")


async def test_an_unknown_family_is_422(api, events):
    assert_422_naming(await api.get("/api/events", params={"family": "seismic"}), "family")


# ── Location-wise ──────────────────────────────────────────────────────────────

async def test_state_and_district_ignore_case(api, events):
    assert await codes(api, state="bihar") == {"E01", "E04", "E08", "E10"}
    assert await codes(api, state="BIHAR", district="patna") == {"E01", "E04"}


async def test_bbox_is_unchanged(api, events):
    assert await codes(api, bbox="84,24,86,26") == {"E01", "E04", "E08", "E10"}


async def test_q_searches_code_district_and_state(api, events):
    assert await codes(api, q="patna") == {"E01", "E04"}
    assert await codes(api, q="maharash") == {"E05", "E06", "E09"}
    assert await codes(api, q="FLT-E1") == {"E10", "E11"}


async def test_q_treats_percent_and_underscore_literally(api, events):
    assert await codes(api, q="%") == set()
    assert await codes(api, q="_") == set()


async def test_a_value_that_looks_like_sql_is_only_a_value(api, events):
    r = await api.get("/api/events", params={"state": "' OR 1=1 --"})
    assert r.status_code == 200
    assert r.json() == []


# ── Verification status ────────────────────────────────────────────────────────

async def test_review_status_and_state_both_apply(api, events):
    assert await codes(api, review_status="QUARANTINED", state="bihar") == {"E01", "E10"}


async def test_rejected_events_appear_only_when_asked_for(api, events):
    assert "E12" not in await codes(api)
    assert await codes(api, review_status="REJECTED") == {"E12"}
    assert await codes(api, review_status="REJECTED,HUMAN_APPROVED") == {"E03", "E08", "E11", "E12"}


async def test_severity_takes_a_list_and_the_old_single_value_still_works(api, events):
    assert await codes(api, severity="HIGH,CRITICAL") == {"E02", "E04", "E06", "E08", "E09", "E11"}
    assert await codes(api, severity="high") == {"E02", "E04", "E09", "E11"}


async def test_an_unknown_severity_is_422_not_503(api, events):
    """BUG-061: it went to Postgres, failed as an enum cast, and came back as an outage."""
    assert_422_naming(await api.get("/api/events", params={"severity": "foo"}), "severity")


async def test_min_confidence(api, events):
    assert await codes(api, min_confidence=0.6) == {"E02", "E03", "E04", "E08", "E09", "E11"}


async def test_source_type_finds_events_with_a_report_from_that_source(api, events):
    assert await codes(api, source_type="OFFICIAL_DISPATCH") == {"E04", "E08"}


# ── Paging, sorting, extras ────────────────────────────────────────────────────

async def test_limit_and_offset_page_through_and_the_total_is_in_a_header(api, events):
    everything = (await api.get("/api/events")).json()
    r = await api.get("/api/events", params={"limit": 5, "offset": 5})

    assert r.status_code == 200
    assert [e["event_code"] for e in r.json()] == [e["event_code"] for e in everything[5:10]]
    assert r.headers["X-Total-Count"] == str(len(NOT_REJECTED))


async def test_the_total_counts_the_filter_not_the_page(api, events):
    r = await api.get("/api/events", params={"state": "bihar", "limit": 1})
    assert len(r.json()) == 1
    assert r.headers["X-Total-Count"] == "4"


async def test_an_offset_past_the_end_is_empty_with_the_true_total(api, events):
    r = await api.get("/api/events", params={"offset": 100})
    assert r.json() == []
    assert r.headers["X-Total-Count"] == str(len(NOT_REJECTED))


@pytest.mark.parametrize("limit", [0, 201])
async def test_limit_is_1_to_200(api, events, limit):
    assert_422_naming(await api.get("/api/events", params={"limit": limit}), "limit")


async def test_sort_by_severity_puts_the_worst_first(api, events):
    rank = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
    r = await api.get("/api/events", params={"sort": "severity:desc"})
    ranks = [rank[e["severity"]] for e in r.json()]
    assert ranks == sorted(ranks, reverse=True)
    assert ranks[0] == 3


async def test_sort_by_confidence_ascending(api, events):
    r = await api.get("/api/events", params={"sort": "confidence:asc"})
    scores = [e["confidence_score"] for e in r.json()]
    assert scores == sorted(scores)


@pytest.mark.parametrize("sort", ["nonsense", "severity:sideways", "raw_text:asc"])
async def test_an_unknown_sort_is_422(api, events, sort):
    assert_422_naming(await api.get("/api/events", params={"sort": sort}), "sort")


async def test_include_boundary_adds_each_events_footprint(api, events):
    r = await api.get("/api/events", params={"include": "boundary"})
    assert r.status_code == 200
    for item in r.json():
        assert json.loads(item["boundary_geojson"])["type"] == "Polygon"


async def test_include_something_else_is_422(api, events):
    assert_422_naming(await api.get("/api/events", params={"include": "nope"}), "include")


async def test_each_item_now_carries_its_type_and_family(api, events):
    r = await api.get("/api/events", params={"event_type": "HEATWAVE"})
    assert {(e["event_type"], e["family"], e["eventType"]) for e in r.json()} == {
        ("HEATWAVE", "thermal", "Heatwave")
    }


async def test_with_no_parameters_the_response_is_what_it_was(api, events):
    """
    The dashboard calls this with no new parameters. Same events, same order
    (newest first, rejected hidden), and every key it read before holds the
    value it held before. New keys (event_type, family) are additions only.
    """
    r = await api.get("/api/events")
    items = r.json()

    expected_order = sorted(
        (e for e in EVENTS if e[2] != "REJECTED"), key=lambda e: e[7], reverse=True
    )
    assert [i["event_code"] for i in items] == [code(e[0]) for e in expected_order]

    e04 = next(i for i in items if i["event_code"] == code("E04"))
    assert {k: e04[k] for k in (
        "eventType", "severity", "confidence_score", "verification", "review_status",
        "quadrant", "impact_radius_km", "city", "state", "place_precision", "imageGradient",
        "verified_at", "timestamp",
    )} == {
        "eventType": "Flood", "severity": "high", "confidence_score": 0.66,
        "verification": "under-review", "review_status": "PENDING_HUMAN_REVIEW",
        "quadrant": "Noise", "impact_radius_km": 2.0, "city": "Patna", "state": "Bihar",
        "place_precision": "district", "imageGradient": "linear-gradient(135deg, #2563EB, #1E3A8A)",
        "verified_at": "2026-09-20T18:00:00+00:00", "timestamp": "2026-09-20T18:00:00+00:00",
    }
    assert (e04["lat"], e04["lng"]) == pytest.approx((25.5941, 85.1376))
    assert "boundary_geojson" not in e04
