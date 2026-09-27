"""
T5 + T6 (Day 3) — PATCH /api/events/{id}/review and GET /api/events/{id}/provenance.

Tokens come from POST /api/auth/token exactly as a client would get them, with
the test-only passwords conftest.TEST_ACCOUNTS writes into indra_test. The
WebSocket manager's broadcast is replaced with a recorder, so EVENT_REVIEWED is
asserted on the message that would actually have gone out.
"""

import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import audit, pipeline
from tests.conftest import TEST_ACCOUNTS, wipe_event_tables
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration

COMMANDER_OP = TEST_ACCOUNTS["commander"][3]
ADMIN_OP = TEST_ACCOUNTS["admin"][3]


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

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


_TOKENS = {}


@pytest_asyncio.fixture
async def tokens(api, accounts):
    """Log in once per user for the module, with indra_test's test passwords."""
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


async def make_event(db, status="QUARANTINED", severity="MODERATE", quadrant="Noise", score=0.4314):
    event_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km, center_point,
                 verification_receipt)
            VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD',
                    CAST(:sev AS severity_enum), :score,
                    CAST(:status AS review_status_enum), CAST(:quad AS quadrant_enum), 1.0,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326),
                    '{"confidence_score": 0.4314}'::jsonb)
        """),
        {"id": event_id, "code": f"INDRA-T-{event_id[:8]}", "sev": severity,
         "score": score, "status": status, "quad": quadrant},
    )
    await db.commit()
    return event_id


async def audit_count(db, action=None):
    rows = await audit.fetch_rows(db)
    return len([r for r in rows if action is None or r["action_taken"] == action])


def review(api, event_id, headers, **body):
    return api.patch(f"/api/events/{event_id}/review", json=body, headers=headers)


REASON = "Verified with SDRF field team by phone"


# ── T5: approve ────────────────────────────────────────────────────────────────

async def test_commander_approves_a_quarantined_event(api, db, tokens, broadcasts):
    event_id = await make_event(db)

    r = await review(api, event_id, tokens["commander"], action="approve", reason=REASON)

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == event_id
    assert body["review_status"] == "HUMAN_APPROVED"
    assert body["verification"] == "verified"
    assert body["quadrant"] == "Confirmed Minor Event"
    assert body["confidence_score"] == pytest.approx(0.4314)
    hr = body["verification_receipt"]["human_review"]
    assert hr["action"] == "approve" and hr["operator_id"] == COMMANDER_OP and hr["reason"] == REASON

    rows = await audit.fetch_rows(db)
    assert [(a["action_taken"], a["operator_id"]) for a in rows] == [("HUMAN_APPROVE", COMMANDER_OP)]
    assert rows[0]["details"]["from_status"] == "QUARANTINED"
    assert rows[0]["details"]["to_status"] == "HUMAN_APPROVED"

    assert len(broadcasts) == 1
    msg = broadcasts[0]
    assert msg["type"] == "EVENT_REVIEWED"
    assert msg["event"] == {
        "id": event_id,
        "event_code": body["event_code"],
        "review_status": "HUMAN_APPROVED",
        "severity": "MODERATE",
        "quadrant": "Confirmed Minor Event",
        "confidence_score": pytest.approx(0.4314),
        # Phase 3 T6: the type rides along, so a type override reaches the screen.
        "event_type": "URBAN_FLOOD",
    }
    assert msg["review"]["action"] == "approve"
    assert msg["review"]["operator_id"] == COMMANDER_OP
    assert msg["review"]["at"] == hr["at"]


async def test_admin_approves_a_pending_event(api, db, tokens, broadcasts):
    event_id = await make_event(db, status="PENDING_HUMAN_REVIEW", severity="HIGH",
                                quadrant="Unverified Threat", score=0.75)

    r = await review(api, event_id, tokens["admin"], action="approve", reason=REASON)

    assert r.status_code == 200
    assert r.json()["quadrant"] == "Critical Verified Event"
    [row] = await audit.fetch_rows(db)
    assert row["operator_id"] == ADMIN_OP


@pytest.mark.parametrize("status", ["HUMAN_APPROVED", "AUTO_PUBLISHED", "REJECTED"])
async def test_approve_from_a_non_reviewable_status_is_409(api, db, tokens, broadcasts, status):
    event_id = await make_event(db, status=status)

    r = await review(api, event_id, tokens["commander"], action="approve", reason=REASON)

    assert r.status_code == 409
    assert await audit_count(db) == 0
    assert broadcasts == []


# ── T5: reject and override ────────────────────────────────────────────────────

async def test_reject_hides_the_event_from_the_list_but_not_the_detail(api, db, tokens, broadcasts):
    event_id = await make_event(db)
    # A second, live event keeps the list non-empty, so the assertion below is
    # about real rows and not about an empty table.
    other_id = await make_event(db)

    r = await review(api, event_id, tokens["commander"], action="reject", reason="Prank reports, confirmed by police")

    assert r.status_code == 200
    assert r.json()["review_status"] == "REJECTED"
    assert await audit_count(db, "HUMAN_REJECT") == 1

    ids = [e["id"] for e in (await api.get("/api/events")).json()]
    assert other_id in ids
    assert event_id not in ids

    detail = await api.get(f"/api/events/{event_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == event_id
    assert detail.json()["review_status"] == "REJECTED"


async def test_reject_an_already_rejected_event_is_409(api, db, tokens, broadcasts):
    event_id = await make_event(db, status="REJECTED")

    r = await review(api, event_id, tokens["commander"], action="reject", reason="again, surely")

    assert r.status_code == 409
    assert await audit_count(db) == 0


async def test_override_severity_on_an_approved_event(api, db, tokens, broadcasts):
    event_id = await make_event(db, status="HUMAN_APPROVED", quadrant="Confirmed Minor Event")

    r = await review(api, event_id, tokens["commander"], action="override_severity",
                     new_severity="HIGH", reason="Hospital basement flooded")

    assert r.status_code == 200
    body = r.json()
    assert body["severity"] == "HIGH"
    assert body["quadrant"] == "Critical Verified Event"
    assert body["review_status"] == "HUMAN_APPROVED"
    assert body["verification_receipt"]["human_review"]["severity_override"] == "HIGH"
    assert await audit_count(db, "MANUAL_OVERRIDE") == 1


async def test_approve_after_override_keeps_the_override(api, db, tokens, broadcasts):
    event_id = await make_event(db)

    await review(api, event_id, tokens["commander"], action="override_severity",
                 new_severity="CRITICAL", reason="Embankment breach reported")
    r = await review(api, event_id, tokens["commander"], action="approve", reason=REASON)

    body = r.json()
    assert body["severity"] == "CRITICAL"
    assert body["quadrant"] == "Critical Verified Event"
    assert body["verification_receipt"]["human_review"]["severity_override"] == "CRITICAL"


# ── T5: validation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"action": "override_severity", "reason": "no severity given"},
    {"action": "approve", "reason": "ok"},
    {"action": "delete", "reason": "remove this event"},
    {"action": "override_severity", "reason": "bad severity", "new_severity": "APOCALYPTIC"},
    {"action": "approve", "reason": "x" * 1001},
])
async def test_invalid_bodies_are_422_and_write_nothing(api, db, tokens, broadcasts, body):
    event_id = await make_event(db)

    r = await api.patch(f"/api/events/{event_id}/review", json=body, headers=tokens["commander"])

    assert r.status_code == 422
    assert await audit_count(db) == 0


@pytest.mark.parametrize("event_id", [str(uuid.uuid4()), "not-a-uuid"])
async def test_unknown_event_is_404(api, db, tokens, broadcasts, event_id):
    r = await review(api, event_id, tokens["commander"], action="approve", reason=REASON)

    assert r.status_code == 404


async def test_concurrent_approves_serialise(api, db, tokens, broadcasts):
    event_id = await make_event(db)

    results = await asyncio.gather(
        review(api, event_id, tokens["commander"], action="approve", reason=REASON),
        review(api, event_id, tokens["admin"], action="approve", reason=REASON),
    )

    assert sorted(r.status_code for r in results) == [200, 409]
    assert await audit_count(db, "HUMAN_APPROVE") == 1
    assert len(broadcasts) == 1


async def test_chain_is_valid_after_a_run_of_reviews(api, db, tokens, broadcasts):
    a = await make_event(db)
    b = await make_event(db, status="PENDING_HUMAN_REVIEW", score=0.75)
    await review(api, a, tokens["commander"], action="approve", reason=REASON)
    await review(api, a, tokens["commander"], action="approve", reason=REASON)  # 409
    await review(api, b, tokens["admin"], action="override_severity", new_severity="HIGH", reason="upgraded by admin")
    await review(api, b, tokens["commander"], action="reject", reason="duplicate of another incident")

    assert await audit.verify_chain(db) == {"valid": True, "checked": 3, "broken_at_seq": None}


# ── T6: provenance ─────────────────────────────────────────────────────────────

async def test_provenance_of_a_streamed_then_approved_event(api, db, tokens, broadcasts):
    ids = []
    for lat, lng, body in CLUSTER_TEXTS:
        rid = await insert_report(db, lat, lng, body)
        ids.append(str(rid))
        result = await pipeline.process_report(db, {"id": str(rid)})
    # A duplicate of report 1 — suppressed, so it must not appear in provenance.
    dupe = await insert_report(db, PATNA_LAT + 0.0027, PATNA_LNG, CLUSTER_TEXTS[0][2])
    assert await pipeline.process_report(db, {"id": str(dupe)}) is None
    event_id = result["id"]

    r = await review(api, event_id, tokens["commander"], action="approve", reason=REASON)
    assert r.status_code == 200

    p = await api.get(f"/api/events/{event_id}/provenance", headers=tokens["commander"])

    assert p.status_code == 200
    body = p.json()
    assert body["event"]["id"] == event_id
    assert body["event"]["review_status"] == "HUMAN_APPROVED"
    assert sorted(x["id"] for x in body["reports"]) == sorted(ids)
    assert str(dupe) not in [x["id"] for x in body["reports"]]
    created = [x["created_at"] for x in body["reports"]]
    assert created == sorted(created)
    # QUARANTINE at report 2, ESCALATE when report 5 takes the score past the
    # 0.60 review gate, then the commander's HUMAN_APPROVE. The ESCALATE row is
    # new since the gate moved: the pipeline's own escalation is now reachable
    # with default settings, so the provenance shows the full decision history
    # rather than jumping from quarantine straight to approval.
    assert [a["action_taken"] for a in body["audit"]] == [
        "QUARANTINE",
        "ESCALATE",
        "HUMAN_APPROVE",
    ]
    assert body["audit"][1]["prev_hash"] == body["audit"][0]["sha256_hash"]
    assert body["audit"][2]["prev_hash"] == body["audit"][1]["sha256_hash"]
    assert body["chain"] == {"valid": True, "checked": 3, "broken_at_seq": None}


async def test_provenance_of_an_event_with_no_audit_rows(api, db, tokens):
    event_id = await make_event(db)

    p = await api.get(f"/api/events/{event_id}/provenance", headers=tokens["analyst"])

    assert p.status_code == 200
    assert p.json()["audit"] == []
    assert p.json()["reports"] == []
    assert p.json()["chain"] == {"valid": True, "checked": 0, "broken_at_seq": None}


async def test_provenance_unknown_event_is_404(api, db, tokens):
    p = await api.get(f"/api/events/{uuid.uuid4()}/provenance", headers=tokens["analyst"])

    assert p.status_code == 404
