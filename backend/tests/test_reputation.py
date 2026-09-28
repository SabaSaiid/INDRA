"""
Phase 5 T6 — reporter reputation (`app/services/reputation.py`) and the source
credibility table (`GET /api/admin/sources`).

Only human decisions count, by a published formula:

    trust = (approved + 1) / (approved + rejected + 2)
    a report's credibility × (0.5 + trust), at most 1.0

T6's two tables row for row. The database half files reports through the real
route as numbered devices, decides events through the real review route, and
reads back what the next report is worth.
"""

import json

import pytest
from sqlalchemy import text

from app.services import pipeline, reputation
from tests.phase5_support import (  # noqa: F401  (fixtures)
    FLOOD_TEXT, PATNA, api, db, device, filed, make_event, report_row, salted, submit, tokens,
)

REASON = "Checked with the district control room"


# ── T6's first table ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "approved, rejected, trust, multiplier",
    [(0, 0, 0.50, 1.00), (0, 2, 0.25, 0.75), (8, 0, 0.90, 1.40), (3, 3, 0.50, 1.00),
     (0, 1, 0.3333, 0.8333), (1, 0, 0.6667, 1.1667)],
)
def test_trust_and_multiplier(approved, rejected, trust, multiplier):
    assert reputation.trust(approved, rejected) == trust
    assert reputation.multiplier(approved, rejected) == multiplier


def test_the_multiplier_applies_and_the_result_is_capped_at_1():
    assert reputation.apply(0.57, 0, 0) == 0.57
    assert reputation.apply(0.57, 0, 2) == round(0.57 * 0.75, 4)
    assert reputation.apply(0.57, 8, 0) == round(0.57 * 1.4, 4)
    assert reputation.apply(0.9, 8, 0) == 1.0


def test_the_provenance_line():
    basis = reputation.reputation_basis(0, 2, 0.57, reputation.apply(0.57, 0, 2))
    assert basis["line"] == "reporter history: 0 approved, 2 rejected → × 0.75"
    assert (basis["credibility_before"], basis["credibility_after"]) == (0.57, 0.4275)
    capped = reputation.reputation_basis(8, 0, 0.9, 1.0)
    assert capped["line"] == "reporter history: 8 approved, 0 rejected → × 1.40 (capped at 1.0)"


def test_only_a_human_decision_is_recorded():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(reputation.record_decision(None, "e", "auto_published"))


# ── T6's second table, through the API ─────────────────────────────────────────

async def _stats(db, n):
    from app.services.ingest import reporter_hash_for

    row = (await db.execute(
        text("SELECT reports, approved, rejected, flagged FROM reporter_stats WHERE reporter_hash = :h"),
        {"h": reporter_hash_for(device(n)["X-Reporter-Id"])},
    )).fetchone()
    await db.commit()
    return tuple(row) if row else None


async def _decide(api, tokens, event_id, action):
    r = await api.patch(f"/api/events/{event_id}/review", json={"action": action, "reason": REASON},
                        headers=tokens["commander"])
    assert r.status_code == 200, r.text


@pytest.mark.integration
async def test_every_report_is_counted_against_its_reporter(api, db, salted):
    await filed(api, 1)
    await filed(api, 1, text_="FLOOD HERE PLEASE SHARE MAXIMUM, water everywhere in Kankarbagh")
    assert await _stats(db, 1) == (2, 0, 0, 1)  # the second carries penalising flags


@pytest.mark.integration
async def test_a_rejected_event_lowers_each_of_its_four_reporters_next_report(api, db, tokens, salted):
    reports = [await filed(api, n) for n in (1, 2, 3, 4)]
    first = await report_row(db, reports[0]["id"])
    event_id = await make_event(db, report_ids=[r["id"] for r in reports])

    await _decide(api, tokens, event_id, "reject")

    for n in (1, 2, 3, 4):
        assert await _stats(db, n) == (1, 0, 1, 0)
    again = await report_row(db, (await filed(api, 1))["id"])
    # One rejection: trust 1/3, × 0.8333.
    assert again["credibility_score"] == round(first["credibility_score"] * 0.8333, 4)
    assert again["analysis"]["reputation"]["line"] == "reporter history: 0 approved, 1 rejected → × 0.83"
    # Someone else's next report is untouched.
    other = await report_row(db, (await filed(api, 9))["id"])
    assert other["credibility_score"] == first["credibility_score"]
    assert "reputation" not in (other["analysis"] or {})


@pytest.mark.integration
async def test_approved_then_rejected_counts_once_as_rejected(api, db, tokens, salted):
    report = await filed(api, 1)
    event_id = await make_event(db, report_ids=[report["id"]])
    await _decide(api, tokens, event_id, "approve")
    assert await _stats(db, 1) == (1, 1, 0, 0)
    await _decide(api, tokens, event_id, "reject")
    assert await _stats(db, 1) == (1, 0, 1, 0)


@pytest.mark.integration
async def test_an_override_is_not_a_decision_about_the_reporters(api, db, tokens, salted):
    report = await filed(api, 1)
    event_id = await make_event(db, report_ids=[report["id"]])
    r = await api.patch(f"/api/events/{event_id}/review", headers=tokens["commander"],
                        json={"action": "override_severity", "reason": REASON, "new_severity": "HIGH"})
    assert r.status_code == 200, r.text
    assert await _stats(db, 1) == (1, 0, 0, 0)


@pytest.mark.integration
async def test_the_pipeline_never_records_a_decision(api, db, salted, monkeypatch):
    """Quarantine, review or auto-publish: machine outcomes change nobody's record."""
    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)
    texts = ["Water entering ground floor shops near Kankarbagh main road",
             "Kankarbagh underpass completely submerged, cars stuck",
             "Knee deep water outside my house, drain overflowing",
             "Flooding on the road to Patna junction, buses diverted"]
    for n, t in enumerate(texts, start=1):
        report = await filed(api, n, text_=t, lat=PATNA[0] + n * 0.0005)
        await pipeline.process_report(db, {"id": report["id"]})
    assert (await db.execute(text("SELECT count(*) FROM verified_events"))).scalar() >= 1
    assert (await db.execute(text("SELECT count(*) FROM reporter_decisions"))).scalar() == 0
    assert (await db.execute(text("SELECT sum(approved + rejected) FROM reporter_stats"))).scalar() == 0
    await db.commit()


@pytest.mark.integration
async def test_provenance_shows_a_rejected_reporters_history(api, db, tokens, salted):
    for _ in range(2):
        report = await filed(api, 1)
        await _decide(api, tokens, await make_event(db, report_ids=[report["id"]]), "reject")
    third = await filed(api, 1)
    event_id = await make_event(db, report_ids=[third["id"]])
    r = await api.get(f"/api/events/{event_id}/provenance", headers=tokens["analyst"])
    assert r.status_code == 200, r.text
    rep = r.json()["reports"][0]["reputation"]
    assert rep["line"] == "reporter history: 0 approved, 2 rejected → × 0.75"
    assert rep["multiplier"] == 0.75


# ── GET /api/admin/sources ─────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_source_table_needs_an_analyst(api, db, tokens):
    assert (await api.get("/api/admin/sources")).status_code == 401
    assert (await api.get("/api/admin/sources", headers=tokens["citizen"])).status_code == 403
    assert (await api.get("/api/admin/sources", headers=tokens["analyst"])).status_code == 200


@pytest.mark.integration
async def test_the_source_table_names_reporters_by_hash_only(api, db, tokens, salted):
    reports = [await filed(api, n) for n in (1, 2, 3)]
    await filed(api, 1)
    await _decide(api, tokens, await make_event(db, report_ids=[r["id"] for r in reports]), "reject")

    r = await api.get("/api/admin/sources", headers=tokens["analyst"])
    assert r.status_code == 200, r.text
    body = r.json()
    raw = json.dumps(body)
    assert "device-" not in raw  # no X-Reporter-Id, anywhere
    top = body["top_reporters"]
    assert len(top) == 3
    assert all(len(t["reporter_hash"]) == 64 for t in top)
    assert top[0]["reports"] == 2 and top[0]["rejected"] == 1
    assert (top[0]["trust"], top[0]["multiplier"]) == (0.3333, 0.8333)
    citizen = next(s for s in body["sources"] if s["source_type"] == "CITIZEN_APP")
    assert citizen["reports"] == 4 and citizen["in_rejected_events"] == 3
    assert citizen["prior"] == pytest.approx(0.6)
    assert "rate_limited_24h" in body and "trust" in body["rules"]
