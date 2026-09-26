"""
Phase 3 T5, T6, T8 and T9 through the pipeline, on a real PostGIS.

* **T5** — `cluster_around`: local, time-limited, per hazard family. T5's table
  row for row, including the timing with 10,000 old unassigned reports in the
  table (the figure is printed; run with `-s` to read it).
* **T6** — the vote in a real event, UNCLASSIFIED held for a human, a
  commander's type override that survives merges, and the 403 for an analyst.
* **T8** — `coordinated`: the same text from three devices 3 km apart.
* **T9** — posts and headlines join clustering within their family, never
  verify an event on their own, and a forecast headline is context only.

Reports are stored through `store_report()` (ingest's own path, so every
text-derived field is what production writes) and processed with
`process_report()`, as the consumer does.
"""

import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables
from tests.test_feed_pipeline import _headline, _post

from app.core.database import async_session
from app.services import pipeline
from app.services.geo_clustering import GeoClusteringService
from app.services.ingest import store_report
from app.services.pipeline import process_report, take_failure

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc).replace(microsecond=0)

# Patna city, and Patna district's centroid (where a post naming Patna is put).
PATNA = (25.5941, 85.1376)
PATNA_DISTRICT = (25.468287, 85.195887)

KM_LAT = 1 / 111.2  # one kilometre north, in degrees of latitude


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


async def citizen(db, body, at=PATNA, *, observed=NOW, reporter=None, citizen_hazard=None, north_km=0.0):
    """Store one citizen report through ingest; return its id."""
    stored = await store_report(
        db,
        source_type="CITIZEN_APP",
        raw_text=body,
        latitude=at[0] + north_km * KM_LAT,
        longitude=at[1],
        observed_at=observed,
        reporter_hash=reporter or f"dev-{uuid.uuid4().hex[:12]}",
        citizen_hazard=citizen_hazard,
        issue_docket=False,
    )
    return stored.id


async def process(db, report_id):
    result = await process_report(db, {"id": str(report_id)})
    assert take_failure() is None
    return result


async def feed(db, mapped):
    stored = await store_report(db, **mapped)
    assert stored.created
    await process(db, stored.id)
    return stored.id


async def row(db, report_id):
    return (await db.execute(text("""
        SELECT id, latitude, longitude, observed_at, created_at, hazard_family, event_id, flags,
               credibility_score, place_precision
        FROM raw_reports WHERE id = :id
    """), {"id": report_id})).mappings().one()


async def around(db, report_id):
    return await GeoClusteringService(db).cluster_around(dict(await row(db, report_id)))


async def events(db):
    return (await db.execute(text("""
        SELECT id, CAST(event_type AS text) AS event_type, CAST(review_status AS text) AS review_status,
               confidence_score, verification_receipt
        FROM verified_events ORDER BY verified_at
    """))).mappings().all()


async def members(db, event_id):
    rows = await db.execute(text("SELECT id FROM raw_reports WHERE event_id = :e"), {"e": event_id})
    return {r[0] for r in rows}


# ── T5: local, time-limited, per family ────────────────────────────────────────

async def test_two_flood_reports_3_km_and_2_h_apart_cluster(db):
    a = await citizen(db, "Knee deep water in Kankarbagh colony", observed=NOW - timedelta(hours=2))
    b = await citizen(db, "Road flooded near the station, cars stuck", north_km=3)
    cluster = await around(db, b)
    assert cluster is not None and set(cluster["report_ids"]) == {a, b}
    assert cluster["family"] == "water"
    assert (cluster["basis"]["eps_km"], cluster["basis"]["window_hours"]) == (5.0, 6)


async def test_the_same_pair_30_h_apart_does_not(db):
    await citizen(db, "Knee deep water in Kankarbagh colony", observed=NOW - timedelta(hours=30))
    b = await citizen(db, "Road flooded near the station, cars stuck", north_km=3)
    assert await around(db, b) is None


async def test_a_flood_and_a_heatwave_1_km_apart_never_cluster(db):
    await citizen(db, "Knee deep water in Kankarbagh colony")
    b = await citizen(db, "46 degree hai, loo chal rahi hai", north_km=1)
    assert await around(db, b) is None


async def test_two_heatwave_reports_20_km_and_10_h_apart_cluster(db):
    a = await citizen(db, "46 degree hai, loo chal rahi hai", observed=NOW - timedelta(hours=10))
    b = await citizen(db, "Scorching heat, 45 degree in the afternoon", north_km=20)
    cluster = await around(db, b)
    assert cluster is not None and set(cluster["report_ids"]) == {a, b}
    assert (cluster["family"], cluster["basis"]["eps_km"], cluster["basis"]["window_hours"]) == (
        "thermal", 25.0, 24,
    )


async def test_two_fog_reports_20_km_apart_do_not(db):
    await citizen(db, "Dense fog on the highway, visibility 50 m")
    b = await citizen(db, "Ghana kohra, kuch dikh nahi raha", north_km=20)
    assert await around(db, b) is None


async def test_a_state_precision_post_is_never_a_candidate(db):
    kerala = await feed(db, _post("<p>Heavy rain in Kerala today #KeralaRains</p>"))
    assert (await row(db, kerala))["place_precision"] == "state"
    near = await citizen(db, "Heavy rain and waterlogging in Thrissur town", at=(10.4116, 76.3604))
    cluster = await around(db, near)
    assert cluster is None or kerala not in cluster["report_ids"]
    assert (await row(db, kerala))["event_id"] is None


async def test_an_untagged_report_joins_its_tagged_neighbours(db):
    a = await citizen(db, "Knee deep water in Kankarbagh colony")
    b = await citizen(db, "Road flooded near the station, cars stuck", north_km=1)
    c = await citizen(db, "Big crowd outside the market, police here", north_km=2)
    cluster = await around(db, c)
    assert cluster is not None and set(cluster["report_ids"]) == {a, b, c}
    assert cluster["family"] == "water"


async def test_the_patna_cluster_is_still_one_event_with_the_same_members(db):
    from tests.test_pipeline import CLUSTER_TEXTS

    ids = []
    for lat, lng, body in CLUSTER_TEXTS:
        ids.append(await citizen(db, body, at=(lat, lng)))
        await process(db, ids[-1])
    (event,) = await events(db)
    assert event["event_type"] == "URBAN_FLOOD"
    assert await members(db, event["id"]) == set(ids)


async def test_clustering_cost_does_not_grow_with_the_table(db):
    """
    T5's measurement: 10,000 old unassigned reports, then one new report.
    Half are within 15 km of Patna but 2–60 days old; half are fresh but spread
    over India. None can join the new report's cluster, and every one would have
    been scanned by the old whole-table DBSCAN.
    """
    await db.execute(text("SELECT setseed(0.26)"))
    await db.execute(text("""
        INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point,
                                 created_at, observed_at, hazard_primary, hazard_family,
                                 place_precision, credibility_score)
        SELECT gen_random_uuid(), 'CITIZEN_APP', 'old report ' || g, lat, lng,
               ST_SetSRID(ST_MakePoint(lng, lat), 4326), t, t, h, f, 'gps', 0.57
        FROM (
            SELECT g,
                   CASE WHEN g <= 5000 THEN 25.5941 + (random() - 0.5) * 0.27 ELSE 8 + random() * 26 END AS lat,
                   CASE WHEN g <= 5000 THEN 85.1376 + (random() - 0.5) * 0.30 ELSE 70 + random() * 20 END AS lng,
                   CASE WHEN g <= 5000 THEN now() - (interval '2 days' + random() * interval '58 days')
                        ELSE now() - random() * interval '6 hours' END AS t,
                   (ARRAY['URBAN_FLOOD','HEATWAVE','FOG','THUNDERSTORM'])[1 + (g % 4)] AS h,
                   (ARRAY['water','thermal','visibility','convective'])[1 + (g % 4)] AS f
            FROM generate_series(1, 10000) AS g
        ) s
    """))
    await db.commit()
    await db.execute(text("ANALYZE raw_reports"))
    await db.commit()

    a = await citizen(db, "Knee deep water in Kankarbagh colony")
    b = await citizen(db, "Road flooded near the station, cars stuck", north_km=1)
    report = dict(await row(db, b))
    service = GeoClusteringService(db)

    timings = []
    for _ in range(7):
        started = time.perf_counter()
        cluster = await service.cluster_around(report)
        timings.append((time.perf_counter() - started) * 1000.0)
    assert set(cluster["report_ids"]) == {a, b}

    started = time.perf_counter()
    await service.cluster_unassigned_reports()
    old_ms = (time.perf_counter() - started) * 1000.0

    median, worst = statistics.median(timings), max(timings)
    print(f"\n[T5] 10,000 old reports + 1 new: cluster_around median {median:.1f} ms, "
          f"worst {worst:.1f} ms over 7 runs, {cluster['basis']['candidates']} candidates; "
          f"the old whole-table cluster_unassigned_reports {old_ms:.0f} ms")
    assert worst < 200.0


# ── T6: the type, in a real event ──────────────────────────────────────────────

async def test_an_untyped_cluster_is_unclassified_and_never_auto_published(db):
    for i, body in enumerate(("Big crowd outside the market, police here",
                              "Something happened near the bridge, people gathering",
                              "Traffic stopped on the main road near the temple",
                              "Everyone is standing outside the school gate")):
        await process(db, await citizen(db, body, north_km=i * 0.8))
    (event,) = await events(db)
    assert event["event_type"] == "UNCLASSIFIED"
    assert event["review_status"] != "AUTO_PUBLISHED"
    receipt = event["verification_receipt"]
    assert receipt["routing"]["caps"] == ["unclassified"]
    assert receipt["event_type_basis"]["votes"] == {}


async def test_the_citizens_pick_types_an_untagged_cluster(db):
    await process(db, await citizen(db, "Big crowd outside the market, police here"))
    await process(db, await citizen(db, "Something happened near the bridge", north_km=0.8))
    await process(db, await citizen(db, "Everyone is standing outside", north_km=1.6,
                                    citizen_hazard="HEATWAVE"))
    (event,) = await events(db)
    assert event["event_type"] == "HEATWAVE"
    assert event["verification_receipt"]["event_type_basis"]["citizen_choice_used"] == 1


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _login(api, user, password):
    r = await api.post("/api/auth/token", data={"username": user, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _flood_event(db):
    ids = []
    for i, body in enumerate(("Knee deep water in Kankarbagh colony",
                              "Road flooded near the station, cars stuck")):
        ids.append(await citizen(db, body, north_km=i))
        await process(db, ids[-1])
    (event,) = await events(db)
    return event


async def test_a_commanders_type_survives_later_reports(db, api, monkeypatch):
    from app.main import ws_manager

    async def _quiet(message):
        return None

    monkeypatch.setattr(ws_manager, "broadcast", _quiet)
    event = await _flood_event(db)
    commander = await _login(api, "commander", "commander123")
    r = await api.patch(f"/api/events/{event['id']}/review", headers=commander, json={
        "action": "override_event_type", "event_type": "FOG",
        "reason": "Field team: it is fog on the river bank, not a flood",
    })
    assert r.status_code == 200, r.text

    for i, body in enumerate(("Water entering shops near the main road",
                              "Underpass completely submerged, buses diverted",
                              "Waterlogging outside the hospital gate")):
        await process(db, await citizen(db, body, north_km=0.4 + i * 0.5))

    (after,) = await events(db)
    assert after["id"] == event["id"]
    assert after["event_type"] == "FOG"
    basis = after["verification_receipt"]["event_type_basis"]
    assert basis["override"]["event_type"] == "FOG"
    assert basis["override"]["machine_vote"] == "URBAN_FLOOD"
    assert basis["votes"]["URBAN_FLOOD"] == 5

    ledger = (await db.execute(text("""
        SELECT details FROM audit_logs
        WHERE event_id = :e AND CAST(action_taken AS text) = 'MANUAL_OVERRIDE'
    """), {"e": event["id"]})).scalars().all()
    assert len(ledger) == 1
    assert (ledger[0]["field"], ledger[0]["from"], ledger[0]["to"]) == ("event_type", "URBAN_FLOOD", "FOG")


async def test_an_analyst_cannot_override_the_type(db, api):
    event = await _flood_event(db)
    analyst = await _login(api, "analyst", "analyst123")
    r = await api.patch(f"/api/events/{event['id']}/review", headers=analyst, json={
        "action": "override_event_type", "event_type": "FOG", "reason": "I think it is fog",
    })
    assert r.status_code == 403


# ── T8: coordinated ────────────────────────────────────────────────────────────

async def test_the_same_text_from_three_devices_is_coordinated(db):
    """
    Three devices, 3 km apart, within 5 minutes: the citizen dedup (1 km) does
    not catch them. Each is flagged `coordinated` and its credibility halved, so
    together they count about 1.4 witnesses, not 3.
    """
    body = "Heavy flooding near Kankarbagh main road, water entering shops"
    ids = []
    for i in range(3):
        ids.append(await citizen(db, body, observed=NOW - timedelta(minutes=4 - 2 * i), north_km=3 * i))
        await process(db, ids[-1])

    for rid in ids:
        r = await row(db, rid)
        assert "coordinated" in r["flags"]
    from app.services.ingest import derive_text_fields

    clean = derive_text_fields("CITIZEN_APP", body, uuid.uuid4())["credibility"]
    credibility = [float((await row(db, rid))["credibility_score"]) for rid in ids]
    assert credibility == [round(clean * 0.5, 4)] * 3  # halved once, each

    (event,) = await events(db)
    density = event["verification_receipt"]["density_basis"]
    assert density["reports"] == 3
    # T8's table said ≈ 1.4 for a 0.57 report; this text starts at 0.60, so
    # 3 × 0.30 / 0.60 = 1.5 witnesses instead of 3.
    assert clean == 0.6
    assert density["n_eff"] == pytest.approx(1.5, abs=1e-4)


async def test_three_people_writing_heavy_rain_here_are_not_a_campaign(db):
    """Texts under 30 normalised characters are skipped: people really do write this."""
    ids = []
    for i in range(3):
        ids.append(await citizen(db, "heavy rain here", north_km=3 * i))
        await process(db, ids[-1])
    for rid in ids:
        assert "coordinated" not in (await row(db, rid))["flags"]


# ── T9: posts and headlines join clustering, capped ────────────────────────────

async def test_citizen_reports_and_posts_about_the_same_district_make_one_event(db):
    citizens = []
    for i, body in enumerate(("Knee deep water in our colony, cars stuck",
                              "Road flooded near the bus stand",
                              "Water entered houses in the lane")):
        citizens.append(await citizen(db, body, at=PATNA_DISTRICT, north_km=i * 0.7,
                                      observed=NOW - timedelta(hours=3)))
        await process(db, citizens[-1])
    posts = [
        await feed(db, _post("<p>Waterlogging everywhere in Patna, knee deep near the market #PatnaRains</p>")),
        await feed(db, _post("<p>Roads under water in Patna after the night's rain #flood</p>")),
    ]
    (event,) = await events(db)
    assert await members(db, event["id"]) == set(citizens) | set(posts)
    assert event["event_type"] == "URBAN_FLOOD"


async def test_provenance_shows_where_a_post_came_from(db, api):
    for i, body in enumerate(("Knee deep water in our colony, cars stuck",
                              "Road flooded near the bus stand")):
        await process(db, await citizen(db, body, at=PATNA_DISTRICT, north_km=i * 0.7))
    post = await feed(db, _post("<p>Waterlogging everywhere in Patna, knee deep near the market</p>"))
    (event,) = await events(db)
    analyst = await _login(api, "analyst", "analyst123")
    r = await api.get(f"/api/events/{event['id']}/provenance", headers=analyst)
    assert r.status_code == 200
    (entry,) = [p for p in r.json()["reports"] if p["id"] == str(post)]
    assert entry["platform"] == "mastodon"
    assert entry["url"].startswith("https://mastodon.social/")
    assert entry["place_precision"] == "district"
    assert entry["hazard_primary"] == "URBAN_FLOOD"


async def test_posts_alone_never_verify_an_event(db):
    for words in ("Heavy rain and waterlogging in Ernakulam, roads flooded",
                  "Kochi streets under water after the downpour, Ernakulam",
                  "Knee deep water near the Ernakulam market this morning",
                  "Ernakulam: houses flooded in the low-lying areas",
                  "Ernakulam district, water entered shops on MG Road"):
        await feed(db, _post(f"<p>{words}</p>"))
    (event,) = await events(db)
    assert event["review_status"] != "AUTO_PUBLISHED"
    assert "posts_only" in event["verification_receipt"]["routing"]["caps"]


async def test_a_forecast_headline_is_context_not_a_witness(db):
    for i, body in enumerate(("Knee deep water in our colony, cars stuck",
                              "Road flooded near the bus stand",
                              "Water entered houses in the lane")):
        await process(db, await citizen(db, body, at=PATNA_DISTRICT, north_km=i * 0.7))
    warning = await feed(db, _headline("IMD warns of heavy rain tomorrow in Patna"))
    assert "not_an_observation" in (await row(db, warning))["flags"]
    (event,) = await events(db)
    density = event["verification_receipt"]["density_basis"]
    assert density["reports"] == 3
    assert "publishers" in density and density["publishers"] == 0


async def test_a_state_level_post_is_in_no_cluster(db):
    rid = await feed(db, _post("<p>Heavy rain in Kerala today, many districts waterlogged</p>"))
    r = await row(db, rid)
    assert r["place_precision"] == "state" and r["event_id"] is None
    assert await events(db) == []


async def test_a_heatwave_cluster_never_merges_into_a_flood_event(db, api, monkeypatch):
    """Nor into a commander-typed event whose reports voted flood."""
    from app.main import ws_manager

    async def _quiet(message):
        return None

    monkeypatch.setattr(ws_manager, "broadcast", _quiet)
    flood = await _flood_event(db)
    for i, body in enumerate(("46 degree hai, loo chal rahi hai", "Scorching heat, 45 degree today")):
        await process(db, await citizen(db, body, north_km=0.3 + i * 0.4))
    assert {e["event_type"] for e in await events(db)} == {"URBAN_FLOOD", "HEATWAVE"}

    commander = await _login(api, "commander", "commander123")
    r = await api.patch(f"/api/events/{flood['id']}/review", headers=commander, json={
        "action": "override_event_type", "event_type": "FOG", "reason": "Field team says fog",
    })
    assert r.status_code == 200
    for i, body in enumerate(("Heatstroke cases, 44 degree", "Loo ke thapede, 45 degree")):
        await process(db, await citizen(db, body, north_km=0.5 + i * 0.4))
    assert len(await members(db, flood["id"])) == 2
