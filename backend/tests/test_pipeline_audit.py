"""
T3 + T4 (Day 3) — the pipeline's audit rows, and merges that respect human decisions.

Weather is pinned at 0.35 / 15.6 mm as in test_pipeline.py. With that pin,
streaming CLUSTER_TEXTS one report at a time scores (re-measured 20 Sep, after
confidence became coverage-aware):

    2 reports 0.5393 → 3: 0.5654 → 4: 0.5871 → 5: 0.6052

`factor_coverage` is 0.80 at every step — vision (0.15) and anomaly (0.05) are
permanently offline and are now excluded from the weighted mean instead of being
scored 0.0, so each figure is its `total_weighted` (0.4314 / 0.4523 / 0.4697 /
0.4842 — the old pins) divided by 0.80.

All four remain QUARANTINED at the default thresholds: re-normalisation fixed the
scale, not the gates.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import audit, pipeline
from app.services.pipeline import process_report
from tests.conftest import wipe_event_tables
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration


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


async def stream(db, texts):
    results = []
    for lat, lng, body in texts:
        rid = await insert_report(db, lat, lng, body)
        results.append(await process_report(db, {"id": str(rid)}))
    return results


async def audit_rows(db):
    return await audit.fetch_rows(db)


async def event_row(db, event_id):
    return (
        await db.execute(
            text("""
                SELECT review_status, severity, quadrant, confidence_score,
                       verification_receipt
                FROM verified_events WHERE id = CAST(:e AS uuid)
            """),
            {"e": event_id},
        )
    ).fetchone()


# ── T3: the pipeline writes one audit row per decision ─────────────────────────

async def test_default_thresholds_write_one_row_per_status_change(db):
    """
    The audit trail records decisions, not traffic.

    Five reports arrive but only two of them change the event's status, so only
    two rows are written. Before the review gate moved to 0.60 this test asserted
    exactly one row, because nothing in the ladder could clear 0.70 — the
    escalation the product is built around was unreachable with default settings.
    Now report 5 crosses the gate and the trail shows it.
    """
    results = await stream(db, CLUSTER_TEXTS)

    rows = await audit_rows(db)
    assert [r["action_taken"] for r in rows] == ["QUARANTINE", "ESCALATE"]
    assert all(r["operator_id"] == "SYSTEM-PIPELINE" for r in rows)
    assert all(r["event_id"] == results[-1]["id"] for r in rows)

    first, second = rows
    assert first["details"]["from_status"] is None
    assert first["details"]["to_status"] == "QUARANTINED"
    assert first["details"]["report_count"] == 2
    assert first["details"]["confidence_score"] == pytest.approx(0.5393, abs=1e-4)

    # 0.6052 clears HUMAN_REVIEW_THRESHOLD (0.60) on the fifth report.
    assert second["details"]["from_status"] == "QUARANTINED"
    assert second["details"]["to_status"] == "PENDING_HUMAN_REVIEW"
    assert second["details"]["report_count"] == 5
    assert second["details"]["confidence_score"] == pytest.approx(0.6052, abs=1e-4)

    assert await audit.verify_chain(db) == {"valid": True, "checked": 2, "broken_at_seq": None}


async def test_a_status_change_on_merge_writes_a_second_row(db, monkeypatch):
    # 0.55 sits between the n=2 score (0.5393) and the n=3 score (0.5654), so the
    # third report is what crosses the gate. The old value here was 0.45, which
    # every score in the ladder now clears — the test would have passed
    # vacuously with a single ESCALATE row and no transition to observe.
    #
    # Rule for picking this number: take the midpoint of the two adjacent
    # measured scores you want to straddle (0.5524 here), so a ±1e-3 tweak to a
    # scoring curve cannot flip which report triggers the change.
    monkeypatch.setattr(pipeline.settings, "HUMAN_REVIEW_THRESHOLD", 0.55)

    await stream(db, CLUSTER_TEXTS)

    rows = await audit_rows(db)
    assert [r["action_taken"] for r in rows] == ["QUARANTINE", "ESCALATE"]

    first, second = rows
    assert first["details"]["report_count"] == 2
    assert first["details"]["confidence_score"] == pytest.approx(0.5393, abs=1e-4)
    assert second["details"]["report_count"] == 3
    assert second["details"]["confidence_score"] == pytest.approx(0.5654, abs=1e-4)
    assert second["details"]["from_status"] == "QUARANTINED"
    assert second["details"]["to_status"] == "PENDING_HUMAN_REVIEW"

    assert await audit.verify_chain(db) == {"valid": True, "checked": 2, "broken_at_seq": None}


async def test_duplicate_report_writes_no_row(db):
    await insert_report(db, PATNA_LAT, PATNA_LNG, CLUSTER_TEXTS[0][2])
    dupe = await insert_report(db, PATNA_LAT + 0.0027, PATNA_LNG, CLUSTER_TEXTS[0][2])

    assert await process_report(db, {"id": str(dupe)}) is None
    assert await audit_rows(db) == []


async def test_lone_report_writes_no_row(db):
    rid = await insert_report(db, PATNA_LAT, PATNA_LNG, "Some water on the road here")

    assert await process_report(db, {"id": str(rid)}) is None
    assert await audit_rows(db) == []


async def test_failed_audit_write_rolls_back_the_event(db, monkeypatch):
    """An event without its audit row must be impossible."""

    async def broken_record(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(audit, "record", broken_record)

    results = await stream(db, CLUSTER_TEXTS[:2])

    assert results == [None, None]
    assert (await db.execute(text("SELECT COUNT(*) FROM verified_events"))).scalar() == 0
    assert (
        await db.execute(text("SELECT COUNT(*) FROM raw_reports WHERE event_id IS NOT NULL"))
    ).scalar() == 0


# ── T4: merges never overwrite a human decision ────────────────────────────────

async def _event_from_first_two(db):
    results = await stream(db, CLUSTER_TEXTS[:2])
    event = results[-1]
    assert event is not None and event["report_count"] == 2
    return event["id"]


async def test_merges_keep_a_human_approval(db):
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("UPDATE verified_events SET review_status = 'HUMAN_APPROVED' WHERE id = CAST(:e AS uuid)"),
        {"e": event_id},
    )
    await db.commit()

    results = await stream(db, CLUSTER_TEXTS[2:])

    assert [r["review_status"] for r in results] == ["HUMAN_APPROVED"] * 3
    assert results[-1]["report_count"] == 5

    status, severity, quadrant, score, _ = await event_row(db, event_id)
    assert status == "HUMAN_APPROVED"
    assert quadrant == "Confirmed Minor Event"
    assert score == pytest.approx(0.6052, abs=1e-4)


async def test_merges_keep_a_severity_override(db):
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("""
            UPDATE verified_events SET
                review_status = 'HUMAN_APPROVED',
                severity = 'HIGH',
                verification_receipt = jsonb_set(
                    verification_receipt, '{human_review}',
                    '{"action": "override_severity", "operator_id": "OP-CMD-001",
                      "reason": "test", "severity_override": "HIGH"}'::jsonb)
            WHERE id = CAST(:e AS uuid)
        """),
        {"e": event_id},
    )
    await db.commit()

    await stream(db, CLUSTER_TEXTS[2:])

    status, severity, quadrant, _, receipt = await event_row(db, event_id)
    assert status == "HUMAN_APPROVED"
    # The content rule alone would say MODERATE here: the deepest phrase in
    # CLUSTER_TEXTS is "knee deep" (50 cm) and there are 5 reports, so both axes
    # read MODERATE. The commander's override outranks it.
    assert severity == "HIGH"
    assert quadrant == "Critical Verified Event"
    # Carried forward, or the next merge would lose it.
    assert receipt["human_review"]["severity_override"] == "HIGH"
    assert receipt["provenance"]["severity"] == "human_override"
    # The override records the decision without erasing the machine's reading —
    # an operator overruling the rule should still be able to see what it said.
    assert receipt["severity_basis"]["max_depth_cm"] == 50
    assert receipt["severity_basis"]["depth_axis"] == "MODERATE"


async def test_without_a_human_decision_status_is_recomputed(db):
    """
    With no human decision on record, status follows the score on every merge.

    The claim is "recomputed, not frozen", and it is now demonstrated by a status
    that actually moves: reports 3 and 4 leave it QUARANTINED, report 5 takes the
    score to 0.6052 and the gate at 0.60 escalates it. Previously every step
    stayed QUARANTINED, so the test could not distinguish "recomputed" from
    "never touched".
    """
    event_id = await _event_from_first_two(db)

    results = await stream(db, CLUSTER_TEXTS[2:])

    assert [r["review_status"] for r in results] == [
        "QUARANTINED",
        "QUARANTINED",
        "PENDING_HUMAN_REVIEW",
    ]
    status, severity, *_ = await event_row(db, event_id)
    assert (status, severity) == ("PENDING_HUMAN_REVIEW", "MODERATE")


async def test_rejected_event_is_untouched_and_new_reports_form_a_new_event(db):
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("UPDATE verified_events SET review_status = 'REJECTED' WHERE id = CAST(:e AS uuid)"),
        {"e": event_id},
    )
    await db.commit()
    before = await event_row(db, event_id)

    results = await stream(db, CLUSTER_TEXTS[2:4])

    assert await event_row(db, event_id) == before
    new = results[-1]
    assert new is not None
    assert new["id"] != event_id
    assert new["report_count"] == 2
    assert (await db.execute(text("SELECT COUNT(*) FROM verified_events"))).scalar() == 2


async def test_preserved_human_status_writes_no_merge_rows(db):
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("UPDATE verified_events SET review_status = 'HUMAN_APPROVED' WHERE id = CAST(:e AS uuid)"),
        {"e": event_id},
    )
    await db.commit()
    assert len(await audit_rows(db)) == 1

    await stream(db, CLUSTER_TEXTS[2:])

    assert len(await audit_rows(db)) == 1
