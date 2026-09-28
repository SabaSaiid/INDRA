"""
Phase 3 T4's backfill (`scripts/backfill_hazards.py`) after Phase 5.

Re-deriving a report from its text must not drop what the text cannot show:
the media flags (T3) and account flags (T7) with their reasons, and the
reporter's record as it stood when the report was stored (T6). A withdrawn
report is a tombstone and is left alone. And the backfill stays idempotent:
a second run changes nothing.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import clock
from app.services.account_signals import account_flags
from app.services.ingest import store_report
from app.workers.media_worker import apply_report_flags
from tests.phase5_support import PATNA, db, report_row  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import backfill_hazards  # noqa: E402

TEXT = "Knee deep water outside my house in Kankarbagh, drain overflowing"


async def stored(db, **kw):
    report = await store_report(db, source_type=kw.pop("source_type", "CITIZEN_APP"), raw_text=TEXT,
                                latitude=PATNA[0], longitude=PATNA[1], **kw)
    return str(report.id)


async def test_media_flags_and_their_reasons_survive_and_a_second_run_changes_nothing(db, capsys):
    rid = await stored(db, reporter_hash="r1")
    await apply_report_flags(db, rid, ["old_capture"], {"old_capture": "taken 14 Aug 2023, 3 years before"})
    await db.commit()
    before = await report_row(db, rid)

    assert await backfill_hazards.run(dry_run=False) == 0
    after = await report_row(db, rid)
    assert after["flags"] == ["old_capture"]
    assert after["credibility_score"] == before["credibility_score"]
    assert after["analysis"]["flag_basis"]["old_capture"] == "taken 14 Aug 2023, 3 years before"
    capsys.readouterr()
    await backfill_hazards.run(dry_run=False)
    assert "1 rows scanned, 0 changed" in capsys.readouterr().out


async def test_account_flags_survive(db):
    flags, basis = account_flags(account_created_at=clock.now() - timedelta(days=2), followers_count=1,
                                 bot=False, posted_at=clock.now())
    rid = await stored(db, source_type="SOCIAL_MEDIA", reporter_hash="author", platform="mastodon",
                       extra_flags=flags, extra_basis=basis, issue_docket=False)
    before = await report_row(db, rid)
    await backfill_hazards.run(dry_run=False)
    after = await report_row(db, rid)
    assert after["flags"] == ["new_account", "few_followers"]
    assert after["credibility_score"] == before["credibility_score"]
    assert after["analysis"]["flag_basis"]["few_followers"] == "1 follower"


async def test_the_reporters_record_is_applied_again_not_dropped(db):
    await db.execute(text("INSERT INTO reporter_stats (reporter_hash, reports, rejected) VALUES ('r2', 2, 2)"))
    await db.commit()
    rid = await stored(db, reporter_hash="r2")
    before = await report_row(db, rid)
    assert before["analysis"]["reputation"]["multiplier"] == 0.75
    await backfill_hazards.run(dry_run=False)
    after = await report_row(db, rid)
    assert after["credibility_score"] == before["credibility_score"]
    assert after["analysis"]["reputation"]["line"] == "reporter history: 0 approved, 2 rejected → × 0.75"


async def test_a_withdrawn_tombstone_is_left_alone(db):
    rid = await stored(db, reporter_hash="r3")
    await db.execute(text("UPDATE raw_reports SET raw_text = '[withdrawn]', analysis = NULL, "
                          "withdrawn_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": rid})
    await db.commit()
    await backfill_hazards.run(dry_run=False)
    row = await report_row(db, rid)
    assert row["analysis"] is None and row["raw_text"] == "[withdrawn]"
