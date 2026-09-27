"""
Phase 2 T10 — report search, and CSV / GeoJSON export.

T10's table row for row: auth, filters, the 5,000-row CSV, the events
GeoJSON and the one DATA_EXPORT ledger row per export with the chain still
verifying. Reports are stored through `store_report()` where the row's shape
matters, and bulk-inserted where only the count does.
"""

import csv
import io
import json
import tracemalloc
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.services import audit
from app.services.ingest import store_report

pytestmark = pytest.mark.integration

USERS = ("analyst", "commander", "citizen")
_TOKENS = {}


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def tokens(api, accounts):
    if not _TOKENS:
        for user in USERS:
            password = accounts[user][0]
            r = await api.post("/api/auth/token", data={"username": user, "password": password})
            assert r.status_code == 200
            _TOKENS[user] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _TOKENS


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


async def _citizen(db, body, lat=25.5941, lng=85.1376, district="Patna", state="Bihar", **kw):
    stored = await store_report(
        db, source_type="CITIZEN_APP", raw_text=body, latitude=lat, longitude=lng,
        district=district, state=state, **kw,
    )
    return stored.id


async def _post(db, body, *, platform="mastodon", source_type="SOCIAL_MEDIA", meta=None, **place):
    place = {"latitude": None, "longitude": None, "district": None, "state": None,
             "place_precision": "none", **place}
    stored = await store_report(
        db, source_type=source_type, raw_text=body, platform=platform,
        external_id=f"test:{uuid.uuid4()}", source_meta=meta or {}, issue_docket=False, **place,
    )
    return stored.id


@pytest_asyncio.fixture
async def mixed(db):
    """One of each kind a search has to tell apart."""
    ids = {
        "citizen_kerala_waterlogging": await _citizen(
            db, "Severe WATERLOGGING near the bus stand", lat=9.98, lng=76.28,
            district="Ernakulam", state="Kerala", media_url="https://x/p.jpg"),
        "citizen_kerala_other": await _citizen(
            db, "Trees down on the main road", lat=9.98, lng=76.28,
            district="Ernakulam", state="Kerala"),
        "citizen_bihar_waterlogging": await _citizen(db, "waterlogging at Gandhi Maidan"),
        "mastodon": await _post(db, "Heavy rain #IMD", meta={
            "language": "en", "media": [{"type": "image"}, {"type": "image"}],
            "url": "https://mastodon.social/web/statuses/1"}),
        "news": await _post(db, "Red alert in Kerala", platform="google_news",
                            source_type="NEWS_MEDIA", meta={"publisher": "The Hindu"},
                            latitude=10.5, longitude=76.2, state="Kerala",
                            place_precision="state"),
        "news_stale": await _post(db, "Old floods in Assam", platform="google_news",
                                  source_type="NEWS_MEDIA",
                                  meta={"publisher": "The Hindu", "stale": True}),
    }
    ids["citizen_duplicate"] = await _citizen(db, "waterlogging at Gandhi Maidan again")
    await db.execute(
        text("UPDATE raw_reports SET duplicate_of = :o WHERE id = :d"),
        {"o": ids["citizen_bihar_waterlogging"], "d": ids["citizen_duplicate"]},
    )
    await db.commit()
    return {k: str(v) for k, v in ids.items()}


async def _search(api, tokens, query="", who="analyst"):
    r = await api.get(f"/api/reports/search?{query}", headers=tokens[who])
    assert r.status_code == 200, r.text
    return r


def _ids(r):
    return {item["id"] for item in r.json()}


# ── T10's table: auth ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/reports/search", "/api/reports/export", "/api/events/export"])
async def test_no_token_is_401(api, path):
    assert (await api.get(path)).status_code == 401


@pytest.mark.parametrize("path", ["/api/reports/search", "/api/reports/export", "/api/events/export"])
async def test_a_citizen_is_403(api, tokens, path):
    assert (await api.get(path, headers=tokens["citizen"])).status_code == 403


async def test_a_commander_may_search(api, tokens, mixed):
    await _search(api, tokens, who="commander")


# ── T10's table: filters ───────────────────────────────────────────────────────

async def test_source_type_and_platform_select_mastodon_posts_only(api, tokens, mixed):
    r = await _search(api, tokens, "source_type=SOCIAL_MEDIA&platform=mastodon")
    assert _ids(r) == {mixed["mastodon"]}
    assert r.headers["X-Total-Count"] == "1"


async def test_status_duplicate_returns_suppressed_reports_with_their_original(api, tokens, mixed):
    (item,) = (await _search(api, tokens, "status=duplicate")).json()
    assert item["id"] == mixed["citizen_duplicate"]
    assert item["duplicate_of"] == mixed["citizen_bihar_waterlogging"]
    assert item["status"] == "duplicate"


async def test_q_and_state_both_apply_and_q_ignores_case(api, tokens, mixed):
    r = await _search(api, tokens, "q=waterlogging&state=Kerala")
    assert _ids(r) == {mixed["citizen_kerala_waterlogging"]}


@pytest.mark.parametrize(
    "query, expected",
    [
        ("status=held", {"mastodon", "news"}),
        ("status=stale", {"news_stale"}),
        ("status=unfused", {"citizen_kerala_waterlogging", "citizen_kerala_other",
                            "citizen_bihar_waterlogging"}),
        ("precision=state", {"news"}),
        ("precision=none", {"mastodon", "news_stale"}),
        ("publisher=the%20hindu", {"news", "news_stale"}),
        ("has_media=true", {"citizen_kerala_waterlogging", "mastodon"}),
        ("district=ernakulam", {"citizen_kerala_waterlogging", "citizen_kerala_other"}),
        ("source_type=NEWS_MEDIA,SOCIAL_MEDIA", {"mastodon", "news", "news_stale"}),
    ],
)
async def test_each_filter(api, tokens, mixed, query, expected):
    assert _ids(await _search(api, tokens, query)) == {mixed[k] for k in expected}


async def test_language_reads_a_posts_own_code_or_the_text_analysis(api, tokens, mixed, db):
    hindi = str(await _citizen(db, "गांधी मैदान के पास घुटनों तक पानी भर गया है"))
    hi = _ids(await _search(api, tokens, "language=hi"))
    en = _ids(await _search(api, tokens, "language=en"))
    assert hi == {hindi}
    assert mixed["mastodon"] in en and hindi not in en


async def test_q_matches_percent_literally(api, tokens, mixed):
    assert _ids(await _search(api, tokens, "q=%25")) == set()


async def test_an_item_carries_the_contract_fields(api, tokens, mixed):
    items = {i["id"]: i for i in (await _search(api, tokens)).json()}
    citizen = items[mixed["citizen_kerala_waterlogging"]]
    assert citizen["docket"] and citizen["docket"].startswith("R-")
    assert citizen["lat"] == 9.98 and citizen["precision"] == "gps"
    assert citizen["media_count"] == 1
    post = items[mixed["mastodon"]]
    assert post["docket"] is None
    assert post["url"] == "https://mastodon.social/web/statuses/1"
    assert (post["lat"], post["lng"], post["precision"]) == (None, None, "none")
    assert post["media_count"] == 2
    assert items[mixed["news"]]["publisher"] == "The Hindu"


@pytest.mark.parametrize(
    "query",
    ["source_type=TWEETS", "platform=twitter", "precision=city", "status=verified",
     "language=english!", "sort=text:desc", "time_field=soon", "from=yesterday"],
)
async def test_a_bad_filter_is_422_naming_it(api, tokens, query):
    r = await api.get(f"/api/reports/search?{query}", headers=tokens["analyst"])
    assert r.status_code == 422


async def test_limit_offset_and_the_total(api, tokens, mixed):
    first = await _search(api, tokens, "limit=2&offset=0&sort=created_at:asc")
    second = await _search(api, tokens, "limit=2&offset=2&sort=created_at:asc")
    assert first.headers["X-Total-Count"] == second.headers["X-Total-Count"] == "7"
    assert not _ids(first) & _ids(second)


async def test_from_and_to_filter_on_observed_time(api, tokens, db):
    old = await _citizen(db, "old report", observed_at=datetime(2026, 9, 1, 6, tzinfo=timezone.utc))
    new = await _citizen(db, "new report", observed_at=datetime(2026, 9, 20, 6, tzinfo=timezone.utc))
    r = await _search(api, tokens, "from=2026-09-10&to=2026-09-24")
    assert _ids(r) == {str(new)}
    r = await _search(api, tokens, "to=2026-09-01")
    assert _ids(r) == {str(old)}


# ── Exports ────────────────────────────────────────────────────────────────────

async def _ledger(db):
    rows = await audit.fetch_rows(db)
    return [r for r in rows if r["action_taken"] == "DATA_EXPORT"]


async def test_csv_export_of_five_thousand_rows(api, tokens, db):
    await db.execute(text("""
        INSERT INTO raw_reports (source_type, raw_text, latitude, longitude, place_precision)
        SELECT 'CITIZEN_APP', 'bulk report ' || g, 25.59, 85.13, 'gps'
        FROM generate_series(1, 5000) g
    """))
    await db.commit()

    tracemalloc.start()
    r = await api.get("/api/reports/export?format=csv", headers=tokens["analyst"])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="indra-reports-' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["id", "docket", "source_type"]
    assert len(rows) == 1 + 5000
    # Streamed in 1,000-row chunks. The client buffers the whole body here, so
    # this bounds the server's side loosely; the point is no 5,000-row list.
    assert peak < 40 * 1024 * 1024


async def test_report_geojson_export_has_null_geometry_for_no_place(api, tokens, mixed):
    r = await api.get("/api/reports/export?format=geojson", headers=tokens["analyst"])
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["indra"] == {"features": 7, "truncated": False, "row_cap": 100_000}
    by_id = {f["id"]: f for f in body["features"]}
    assert by_id[mixed["mastodon"]]["geometry"] is None
    assert by_id[mixed["citizen_kerala_other"]]["geometry"] == {
        "type": "Point", "coordinates": [76.28, 9.98]}


async def test_export_applies_the_same_filters(api, tokens, mixed):
    r = await api.get("/api/reports/export?format=csv&platform=mastodon", headers=tokens["analyst"])
    assert len(list(csv.reader(io.StringIO(r.text)))) == 2


async def test_an_unknown_format_is_422_and_not_audited(api, tokens, db):
    r = await api.get("/api/reports/export?format=xlsx", headers=tokens["analyst"])
    assert r.status_code == 422
    assert await _ledger(db) == []


async def _event(db, *, polygon: bool):
    event_id = uuid.uuid4()
    await db.execute(text(f"""
        INSERT INTO verified_events
            (id, event_code, event_type, severity, confidence_score, review_status, quadrant,
             impact_radius_km, center_point, boundary_polygon, verification_receipt, state)
        VALUES (:id, :code, 'URBAN_FLOOD', 'MODERATE', 0.72, 'PENDING_HUMAN_REVIEW', 'Noise', 1.0,
                ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326),
                {"ST_Buffer(ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326), 0.01)" if polygon else "NULL"},
                '{{"confidence_score": 0.72, "factor_coverage": 0.8}}'::jsonb, 'Bihar')
    """), {"id": event_id, "code": f"INDRA-T-{str(event_id)[:8]}"})
    await db.commit()
    return str(event_id)


async def test_events_geojson_has_polygon_or_point_and_the_scores(api, tokens, db):
    with_polygon = await _event(db, polygon=True)
    without = await _event(db, polygon=False)

    r = await api.get("/api/events/export?format=geojson", headers=tokens["analyst"])
    assert r.status_code == 200
    body = r.json()
    by_id = {f["id"]: f for f in body["features"]}
    assert by_id[with_polygon]["geometry"]["type"] == "Polygon"
    assert by_id[without]["geometry"] == {"type": "Point", "coordinates": [85.1376, 25.5941]}
    props = by_id[with_polygon]["properties"]
    assert props["confidence_score"] == 0.72
    assert props["factor_coverage"] == 0.8
    assert props["family"] and props["label"]


async def test_events_csv_export(api, tokens, db):
    await _event(db, polygon=False)
    r = await api.get("/api/events/export?format=csv", headers=tokens["analyst"])
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1
    assert rows[0]["confidence_score"] == "0.72"


@pytest.mark.parametrize(
    "path",
    ["/api/reports/export?format=csv&state=Bihar", "/api/reports/export?format=geojson",
     "/api/events/export?format=csv", "/api/events/export?format=geojson&severity=MODERATE"],
)
async def test_every_export_writes_exactly_one_ledger_row_and_the_chain_verifies(api, tokens, db, path):
    r = await api.get(path, headers=tokens["analyst"])
    assert r.status_code == 200

    (row,) = await _ledger(db)
    assert row["operator_id"] == "analyst"
    details = row["details"] if isinstance(row["details"], dict) else json.loads(row["details"])
    assert details["kind"] in ("reports", "events")
    assert details["format"] in ("csv", "geojson")
    if "state=Bihar" in path:
        assert details["filters"]["state"] == "Bihar"
    assert (await audit.verify_chain(db))["valid"] is True


async def test_exports_are_exposed_to_the_dashboard_origin(api, tokens):
    from app.core.config import get_settings

    origin = get_settings().cors_origins[0]
    r = await api.get("/api/reports/export?format=csv",
                      headers={**tokens["analyst"], "Origin": origin})
    assert "Content-Disposition" in r.headers["access-control-expose-headers"]


# ── Phase 3 T4, T8: search by hazard and by flag ───────────────────────────────

@pytest_asyncio.fixture
async def hazardous(db):
    ids = {
        "heat_citizen": await _citizen(db, "46 degree hai, loo chal rahi hai", district="Delhi", state="Delhi"),
        # The text names no hazard; the citizen picked one.
        "heat_pick": await _citizen(db, "Please send help to our street", citizen_hazard="HEATWAVE"),
        "heat_post": await _post(db, "Scorching heat in Delhi, 45 degree #heatwave"),
        "flood_citizen": await _citizen(db, "Knee deep water in Kankarbagh colony"),
        # Rain that floods a road: tagged with both, primary URBAN_FLOOD.
        "rain_and_flood": await _citizen(db, "Heavy rain since morning, Boring Road waterlogged"),
        "forecast": await _post(db, "IMD: heavy rain likely in Patna tomorrow", platform="google_news",
                                source_type="NEWS_MEDIA", meta={"publisher": "The Hindu"}),
        "advert": await _citizen(db, "SELLING UMBRELLAS!!! CALL 9812345678"),
    }
    return {k: str(v) for k, v in ids.items()}


@pytest.mark.parametrize(
    "query, expected",
    [
        ("hazard=HEATWAVE", {"heat_citizen", "heat_pick", "heat_post"}),
        ("hazard=URBAN_FLOOD", {"flood_citizen", "rain_and_flood"}),
        # Any tagged hazard, not only the primary: the waterlogged road names rain too.
        ("hazard=RAINFALL", {"rain_and_flood", "forecast"}),
        ("flag=not_an_observation", {"forecast"}),
        ("flag=promotional", {"advert"}),
        ("hazard=HEATWAVE&source_type=SOCIAL_MEDIA", {"heat_post"}),
    ],
)
async def test_search_by_hazard_and_flag(api, tokens, hazardous, query, expected):
    assert _ids(await _search(api, tokens, query)) == {hazardous[k] for k in expected}


async def test_an_item_carries_its_hazards_and_flags(api, tokens, hazardous):
    items = {i["id"]: i for i in (await _search(api, tokens)).json()}
    both = items[hazardous["rain_and_flood"]]
    assert both["hazard_primary"] == "URBAN_FLOOD"
    assert both["hazards"] == ["URBAN_FLOOD", "RAINFALL"]  # type names, in precedence order
    assert both["flags"] == []
    assert items[hazardous["advert"]]["flags"] == ["promotional", "shouting"]


async def test_a_forecast_is_held(api, tokens, hazardous):
    """A forecast never makes a cluster (T8), so search counts it as held."""
    assert hazardous["forecast"] in _ids(await _search(api, tokens, "status=held"))


@pytest.mark.parametrize("query", ["hazard=TORNADO", "flag=suspicious"])
async def test_an_unknown_hazard_or_flag_is_422(api, tokens, query):
    r = await api.get(f"/api/reports/search?{query}", headers=tokens["analyst"])
    assert r.status_code == 422
