"""
Phase 4 T7 — the review queue, claiming, and an event's history.

Tokens come from POST /api/auth/token with indra_test's test passwords, as in
test_review_api.py. The two operators who may claim are the test commander
(OP-CMD-001) and the test admin (OP-ADMIN-001).
"""

import json
import uuid
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import clock, pipeline
from tests.conftest import TEST_ACCOUNTS, wipe_event_tables
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration

COMMANDER_OP = TEST_ACCOUNTS["commander"][3]
ADMIN_OP = TEST_ACCOUNTS["admin"][3]
REASON = "Checked with the district control room"


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest.fixture
def broadcasts(monkeypatch):
    from app.main import ws_manager

    sent = []

    async def record(message):
        sent.append(message)

    monkeypatch.setattr(ws_manager, "broadcast", record)
    return sent


@pytest_asyncio.fixture
async def api():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


_TOKENS = {}


@pytest_asyncio.fixture
async def tokens(api, accounts):
    if not _TOKENS:
        for user, (password, *_rest) in accounts.items():
            r = await api.post("/api/auth/token", data={"username": user, "password": password})
            assert r.status_code == 200, r.text
            _TOKENS[user] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _TOKENS


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


async def make_event(
    db, *, severity="MODERATE", status="PENDING_HUMAN_REVIEW", verdict="UNCONFIRMED",
    hours_old=0.0, reviewed=False, claimed_by=None, claimed_minutes_ago=None, flags=None,
):
    event_id = str(uuid.uuid4())
    receipt = {"contradictions": []}
    if verdict == "CONTRADICTED":
        receipt["contradictions"] = [{"factor": "weather_station", "rule": "r", "reason": "VIDP 26.7 °C"}]
    if reviewed:
        receipt["human_review"] = {"action": "override_severity", "operator_id": COMMANDER_OP}
    now = clock.now()
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score, review_status, quadrant,
                 impact_radius_km, center_point, verification_receipt, hazard_family, verdict,
                 verified_at, updated_at, claimed_by, claimed_at)
            VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD', CAST(:sev AS severity_enum), 0.5,
                    CAST(:status AS review_status_enum), 'Noise', 1.0,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326), CAST(:receipt AS jsonb),
                    'water', CAST(:verdict AS verdict_enum), :at, :at, :claimed_by, :claimed_at)
        """),
        {
            "id": event_id, "code": f"INDRA-Q-{event_id[:8]}", "sev": severity, "status": status,
            "receipt": json.dumps(receipt), "verdict": verdict,
            "at": now - timedelta(hours=hours_old),
            "claimed_by": claimed_by,
            "claimed_at": now - timedelta(minutes=claimed_minutes_ago)
            if claimed_minutes_ago is not None else None,
        },
    )
    if flags is not None:
        await db.execute(
            text("""
                INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point,
                                         event_id, flags, credibility_score)
                VALUES (gen_random_uuid(), 'CITIZEN_APP', 'a report', 25.5941, 85.1376,
                        ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326), CAST(:e AS uuid),
                        CAST(:flags AS text[]), 0.3)
            """),
            {"e": event_id, "flags": flags},
        )
    await db.commit()
    return event_id


async def queue(api, tokens, **params):
    r = await api.get("/api/review/queue", params=params, headers=tokens["analyst"])
    assert r.status_code == 200, r.text
    return r.json()


# ── The tabs ───────────────────────────────────────────────────────────────────

async def test_the_contradicted_tab_holds_only_unreviewed_contradicted_events(api, db, tokens):
    wanted = await make_event(db, verdict="CONTRADICTED")
    await make_event(db, verdict="CONTRADICTED", reviewed=True)
    await make_event(db, verdict="CONTRADICTED", status="REJECTED")
    await make_event(db, verdict="UNCONFIRMED")

    body = await queue(api, tokens, tab="contradicted")

    assert [i["id"] for i in body["items"]] == [wanted]
    assert body["total"] == 1
    assert body["items"][0]["contradictions"][0]["reason"] == "VIDP 26.7 °C"


async def test_each_tab_selects_what_it_says(api, db, tokens):
    pending = await make_event(db, status="PENDING_HUMAN_REVIEW")
    quarantined = await make_event(db, status="QUARANTINED", hours_old=5)
    published = await make_event(db, status="AUTO_PUBLISHED", severity="CRITICAL", hours_old=5)
    flagged = await make_event(db, status="AUTO_PUBLISHED", hours_old=5, flags=["promotional"])
    forecast_only = await make_event(db, status="AUTO_PUBLISHED", hours_old=5, flags=["not_an_observation"])
    claimed = await make_event(db, status="AUTO_PUBLISHED", hours_old=5, claimed_by=ADMIN_OP,
                               claimed_minutes_ago=5)
    await make_event(db, status="AUTO_PUBLISHED", hours_old=5, claimed_by=ADMIN_OP,
                     claimed_minutes_ago=20)

    ids = lambda body: {i["id"] for i in body["items"]}
    assert ids(await queue(api, tokens, tab="pending")) == {pending, quarantined}
    assert ids(await queue(api, tokens, tab="high_impact")) == {published}
    assert ids(await queue(api, tokens, tab="suspicious")) == {flagged}
    assert forecast_only not in ids(await queue(api, tokens, tab="suspicious"))
    assert ids(await queue(api, tokens, tab="recent")) == {pending}
    assert ids(await queue(api, tokens, tab="claimed")) == {claimed}


async def test_counts_equal_a_count_of_each_tab(api, db, tokens):
    await make_event(db, status="PENDING_HUMAN_REVIEW", severity="HIGH", verdict="CONTRADICTED")
    await make_event(db, status="QUARANTINED", hours_old=3)
    await make_event(db, status="AUTO_PUBLISHED", flags=["coordinated"], claimed_by=COMMANDER_OP,
                     claimed_minutes_ago=1)
    await make_event(db, status="REJECTED", severity="CRITICAL")

    counts = await queue(api, tokens, counts="true")

    for tab in ("pending", "contradicted", "suspicious", "high_impact", "recent", "claimed"):
        body = await queue(api, tokens, tab=tab)
        assert counts[tab] == body["total"] == len(body["items"]), tab
    assert counts == {"pending": 2, "contradicted": 1, "suspicious": 1, "high_impact": 1,
                      "recent": 2, "claimed": 1}


async def test_the_order_is_severity_then_verdict_then_age(api, db, tokens):
    high = await make_event(db, severity="HIGH", verdict="CORROBORATED", hours_old=9)
    critical_contradicted = await make_event(db, severity="CRITICAL", verdict="CONTRADICTED", hours_old=9)
    critical_corroborated_new = await make_event(db, severity="CRITICAL", verdict="CORROBORATED", hours_old=1)
    critical_corroborated_old = await make_event(db, severity="CRITICAL", verdict="CORROBORATED", hours_old=4)
    critical_unconfirmed = await make_event(db, severity="CRITICAL", verdict="UNCONFIRMED", hours_old=2)

    body = await queue(api, tokens, tab="pending")

    assert [i["id"] for i in body["items"]] == [
        critical_corroborated_old, critical_corroborated_new, critical_unconfirmed,
        critical_contradicted, high,
    ]


async def test_an_unknown_tab_is_a_422_naming_it(api, db, tokens):
    r = await api.get("/api/review/queue", params={"tab": "urgent"}, headers=tokens["analyst"])
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["query", "tab"]


@pytest.mark.parametrize("who, status", [(None, 401), ("citizen", 403), ("analyst", 200)])
async def test_reading_the_queue_needs_an_analyst(api, db, tokens, who, status):
    headers = tokens[who] if who else {}
    assert (await api.get("/api/review/queue", headers=headers)).status_code == status


# ── Claiming ───────────────────────────────────────────────────────────────────

async def test_a_second_claim_is_a_409_naming_the_holder(api, db, tokens, broadcasts):
    event_id = await make_event(db)

    first = await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])
    second = await api.post(f"/api/events/{event_id}/claim", headers=tokens["admin"])

    assert first.status_code == 200
    assert first.json()["claim"]["operator_id"] == COMMANDER_OP
    assert second.status_code == 409
    assert COMMANDER_OP in second.json()["detail"]["message"]
    assert broadcasts == [{
        "type": "EVENT_CLAIMED",
        "event": {"id": event_id, "event_code": f"INDRA-Q-{event_id[:8]}"},
        "claim": first.json()["claim"],
    }]
    detail = (await api.get(f"/api/events/{event_id}")).json()
    assert detail["claim"]["operator_id"] == COMMANDER_OP


async def test_after_fifteen_minutes_someone_else_may_claim(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    assert (await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])).status_code == 200

    with clock.frozen(clock.now() + timedelta(minutes=15, seconds=1)):
        r = await api.post(f"/api/events/{event_id}/claim", headers=tokens["admin"])

    assert r.status_code == 200
    assert r.json()["claim"]["operator_id"] == ADMIN_OP


async def test_the_holder_claiming_again_renews_it(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    first = await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])
    with clock.frozen(clock.now() + timedelta(minutes=10)):
        again = await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])
    assert again.status_code == 200
    assert again.json()["claim"]["expires_at"] > first.json()["claim"]["expires_at"]


async def test_an_analyst_may_not_claim(api, db, tokens):
    event_id = await make_event(db)
    assert (await api.post(f"/api/events/{event_id}/claim", headers=tokens["analyst"])).status_code == 403


async def test_a_rejected_event_cannot_be_claimed(api, db, tokens):
    event_id = await make_event(db, status="REJECTED")
    assert (await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])).status_code == 409


async def test_a_decision_releases_the_claim(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])

    r = await api.patch(f"/api/events/{event_id}/review", headers=tokens["commander"],
                        json={"action": "approve", "reason": REASON})

    assert r.status_code == 200
    assert r.json()["claim"] is None
    reviewed = [m for m in broadcasts if m["type"] == "EVENT_REVIEWED"]
    assert len(reviewed) == 1 and reviewed[0]["claim_released"] is True
    row = (await db.execute(text("SELECT claimed_by FROM verified_events WHERE id = CAST(:e AS uuid)"),
                            {"e": event_id})).scalar()
    await db.commit()
    assert row is None


async def test_a_commander_may_not_decide_an_event_someone_else_holds(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    await api.post(f"/api/events/{event_id}/claim", headers=tokens["admin"])

    r = await api.patch(f"/api/events/{event_id}/review", headers=tokens["commander"],
                        json={"action": "approve", "reason": REASON})

    assert r.status_code == 409
    assert ADMIN_OP in r.json()["detail"]["message"]


async def test_an_admin_may_still_decide_a_claimed_event(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    await api.post(f"/api/events/{event_id}/claim", headers=tokens["commander"])
    r = await api.patch(f"/api/events/{event_id}/review", headers=tokens["admin"],
                        json={"action": "approve", "reason": REASON})
    assert r.status_code == 200


async def test_release_by_the_holder_and_not_by_another_commander(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    await api.post(f"/api/events/{event_id}/claim", headers=tokens["admin"])

    refused = await api.delete(f"/api/events/{event_id}/claim", headers=tokens["commander"])
    released = await api.delete(f"/api/events/{event_id}/claim", headers=tokens["admin"])
    again = await api.delete(f"/api/events/{event_id}/claim", headers=tokens["admin"])

    assert refused.status_code == 409
    assert released.status_code == 200 and released.json()["claim"] is None
    assert again.status_code == 200 and again.json()["claim"] is None
    assert broadcasts[-1] == {
        "type": "EVENT_CLAIMED",
        "event": {"id": event_id, "event_code": f"INDRA-Q-{event_id[:8]}"},
        "claim": None,
        "released_by": ADMIN_OP,
    }


# ── History ────────────────────────────────────────────────────────────────────

async def test_history_of_three_merges_and_an_approval(api, db, tokens, broadcasts):
    event = None
    for lat, lng, body in CLUSTER_TEXTS:
        rid = await insert_report(db, lat, lng, body)
        event = await pipeline.process_report(db, {"id": str(rid)}) or event
    r = await api.patch(f"/api/events/{event['id']}/review", headers=tokens["commander"],
                        json={"action": "approve", "reason": REASON})
    assert r.status_code == 200

    h = await api.get(f"/api/events/{event['id']}/history", headers=tokens["analyst"])

    assert h.status_code == 200
    body = h.json()
    assert body["snapshots"] == 4
    snapshots = [e for e in body["timeline"] if e["kind"] == "snapshot"]
    assert [s["trigger"] for s in snapshots] == ["created", "merge", "merge", "merge"]
    assert [s["report_count"] for s in snapshots] == [2, 3, 4, 5]
    confidences = [s["confidence_score"] for s in snapshots]
    assert confidences == sorted(confidences)
    assert all(s["factor_coverage"] == 0.8 and s["receipt_version"] == 2 for s in snapshots)
    audit_actions = [e["action_taken"] for e in body["timeline"] if e["kind"] == "audit"]
    assert audit_actions == ["QUARANTINE", "HUMAN_APPROVE"]
    times = [e["at"] for e in body["timeline"]]
    assert times == sorted(times)
    assert body["timeline"][-1]["action_taken"] == "HUMAN_APPROVE"


async def test_history_needs_an_analyst(api, db, tokens):
    event_id = await make_event(db)
    assert (await api.get(f"/api/events/{event_id}/history")).status_code == 401
    assert (await api.get(f"/api/events/{event_id}/history", headers=tokens["citizen"])).status_code == 403
    assert (await api.get(f"/api/events/{uuid.uuid4()}/history", headers=tokens["analyst"])).status_code == 404


async def test_the_verdict_filter_and_its_counts(api, db, tokens):
    contradicted = await make_event(db, verdict="CONTRADICTED")
    await make_event(db, verdict="CORROBORATED")
    await make_event(db, verdict="UNCONFIRMED")

    r = await api.get("/api/events", params={"verdict": "CONTRADICTED"})
    assert r.status_code == 200
    assert [e["id"] for e in r.json()] == [contradicted]
    assert r.json()[0]["verdict"] == "CONTRADICTED"
    assert (await api.get("/api/events", params={"verdict": "FAKE"})).status_code == 422
