"""
T3 + T4 (Day 3) — the pipeline's audit rows, and merges that respect human decisions.

Weather is pinned at 0.35 / 15.6 mm as in test_pipeline.py. The five reports
come from five unverified reporters with credibility 0.595, 0.565, 0.555, 0.57
and 0.565, so n_eff is 1.9333 / 2.8583 / 3.8083 / 4.75, each report counting
credibility / 0.60 of a witness (Phase 3 T8).

**Receipt v2 (Phase 4, 27 Sep).** Streaming CLUSTER_TEXTS one report at a time,
with SACHET current (the conftest default):

    no warning in force        2 reports 0.4530 → 3: 0.4776 → 4: 0.4991 → 5: 0.5171
    a Severe warning in force  2 reports 0.5593 → 3: 0.5839 → 4: 0.6054 → 5: 0.6234

Derived by hand from the v1 ladder before measuring. v1's total was
0.1775 + 0.2·(density + coherence); v2's is 0.16 + 0.2·density + 0.15·coherence
(+ 0.085 under a Severe warning), with density 0.2629 / 0.3636 / 0.4531 / 0.5298
from n_eff and coherence backed out of the v1 totals (0.4299 / 0.4494 / 0.4664 /
0.4805). The v1 ladder was 0.5374 / 0.5617 / 0.5830 / 0.6006, and on 20 Sep,
counting reports, 0.5393 / 0.5654 / 0.5871 / 0.6052.

So **without a warning the five Patna reports stay QUARANTINED**: the official
factor reads 0.0 ("no warning in force covers this event"), which v1 could not
say. Under an IMD warning the fourth report crosses the 0.60 gate. Coverage is
0.80 at every step: vision and anomaly are permanently offline and excluded.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import audit, pipeline
from app.services.pipeline import process_report
from app.services import clock
from tests.conftest import TEST_ACCOUNTS, wipe_event_tables
from tests.phase4_support import insert_warning, wipe_phase4_rows
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration

# A commander's severity override, as the review endpoint records it.
COMMANDER_OVERRIDE = json.dumps({
    "action": "override_severity", "operator_id": TEST_ACCOUNTS["commander"][3],
    "reason": "test", "severity_override": "HIGH",
})


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        await wipe_phase4_rows(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_phase4_rows(session)
            await wipe_event_tables(session)


async def warning_over_patna(db):
    """A Severe heavy-rain warning in force over Patna: official_warning 0.85."""
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=clock.now())


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

    Five reports arrive under an IMD warning, but only two of them change the
    event's status, so only two rows are written: created at 2 reports, and
    escalated when the fourth crosses 0.60. Before the review gate moved to 0.60
    nothing in the ladder could clear 0.70; since receipt v2, nothing does
    without a warning (see the module docstring).
    """
    await warning_over_patna(db)
    results = await stream(db, CLUSTER_TEXTS)

    rows = await audit_rows(db)
    assert [r["action_taken"] for r in rows] == ["QUARANTINE", "ESCALATE"]
    assert all(r["operator_id"] == "SYSTEM-PIPELINE" for r in rows)
    assert all(r["event_id"] == results[-1]["id"] for r in rows)

    first, second = rows
    assert first["details"]["from_status"] is None
    assert first["details"]["to_status"] == "QUARANTINED"
    assert first["details"]["report_count"] == 2
    assert first["details"]["confidence_score"] == pytest.approx(0.5593, abs=1e-4)
    assert first["details"]["verdict"] == "CORROBORATED"

    # 0.6054 clears HUMAN_REVIEW_THRESHOLD (0.60) on the fourth report.
    assert second["details"]["from_status"] == "QUARANTINED"
    assert second["details"]["to_status"] == "PENDING_HUMAN_REVIEW"
    assert second["details"]["report_count"] == 4
    assert second["details"]["confidence_score"] == pytest.approx(0.6054, abs=1e-4)

    assert await audit.verify_chain(db) == {"valid": True, "checked": 2, "broken_at_seq": None}


async def test_a_status_change_on_merge_writes_a_second_row(db, monkeypatch):
    # 0.4653 sits between the n=2 score (0.4530) and the n=3 score (0.4776) with
    # no warning in force, so the third report is what crosses the gate.
    #
    # Rule for picking this number: take the midpoint of the two adjacent
    # measured scores you want to straddle, so a ±1e-3 tweak to a scoring curve
    # cannot flip which report triggers the change. (v1: 0.55, between 0.5374
    # and 0.5617.)
    monkeypatch.setattr(pipeline.settings, "HUMAN_REVIEW_THRESHOLD", 0.4653)

    await stream(db, CLUSTER_TEXTS)

    rows = await audit_rows(db)
    assert [r["action_taken"] for r in rows] == ["QUARANTINE", "ESCALATE"]

    first, second = rows
    assert first["details"]["report_count"] == 2
    assert first["details"]["confidence_score"] == pytest.approx(0.4530, abs=1e-4)
    assert second["details"]["report_count"] == 3
    assert second["details"]["confidence_score"] == pytest.approx(0.4776, abs=1e-4)
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
    assert score == pytest.approx(0.5171, abs=1e-4)


async def test_merges_keep_a_severity_override(db):
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("""
            UPDATE verified_events SET
                review_status = 'HUMAN_APPROVED',
                severity = 'HIGH',
                verification_receipt = jsonb_set(
                    verification_receipt, '{human_review}',
                    CAST(:review AS jsonb))
            WHERE id = CAST(:e AS uuid)
        """),
        {"e": event_id, "review": COMMANDER_OVERRIDE},
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


async def test_an_override_to_high_keeps_a_weak_event_in_front_of_a_human(db, monkeypatch):
    """
    BUG-067 on the merge path: routing now depends on severity, so the
    commander's severity counts, not only the machine's. Without rainfall the
    score stays under the 0.60 gate, where a MODERATE event is quarantined.
    """
    async def _dry(lat, lng):
        return 0.0, 0.0

    monkeypatch.setattr(pipeline, "weather_score", _dry)
    event_id = await _event_from_first_two(db)
    await db.execute(
        text("""
            UPDATE verified_events SET
                severity = 'HIGH',
                verification_receipt = jsonb_set(
                    verification_receipt, '{human_review}',
                    CAST(:review AS jsonb))
            WHERE id = CAST(:e AS uuid)
        """),
        {"e": event_id, "review": COMMANDER_OVERRIDE},
    )
    await db.commit()

    await stream(db, CLUSTER_TEXTS[2:3])

    status, severity, _, score, receipt = await event_row(db, event_id)
    assert score < 0.60
    assert severity == "HIGH"
    assert status == "PENDING_HUMAN_REVIEW"
    assert receipt["routing"]["basis"] == "severity"


async def test_without_a_human_decision_status_is_recomputed(db):
    """
    With no human decision on record, status follows the score on every merge.

    The claim is "recomputed, not frozen", demonstrated by a status that
    actually moves. Under an IMD warning, report 3 leaves it QUARANTINED
    (0.5839), report 4 takes it to 0.6054 and the gate at 0.60 escalates it, and
    report 5 keeps it there (0.6234).
    """
    await warning_over_patna(db)
    event_id = await _event_from_first_two(db)

    results = await stream(db, CLUSTER_TEXTS[2:])

    assert [r["review_status"] for r in results] == [
        "QUARANTINED",
        "PENDING_HUMAN_REVIEW",
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
