#!/usr/bin/env python3
"""
Re-score stored events under receipt v2, so every event has a verdict (Phase 4).

    backend/.venv/bin/python scripts/rescore_events.py --dry-run
    backend/.venv/bin/python scripts/rescore_events.py
    backend/.venv/bin/python scripts/rescore_events.py --all

Events scored before migration 0020 carry a v1 receipt and no verdict. This
runs each through `pipeline.rescore_event`, the same re-score late
corroboration uses: their current reports, the evidence as it stands, the
human decisions standing (an approval keeps its status, an override its value).

* By default only events **without a verdict** that are not REJECTED; `--all`
  re-scores every non-rejected event.
* **Idempotent.** An event whose confidence, verdict, status and severity come
  out as stored is not written, so a second run changes 0 and says so.
* Every change is one `LATE_CORROBORATION` ledger row with trigger
  `backfill:receipt_v2`, one snapshot, and the new receipt; nothing is
  broadcast (an operator's screen should not fill with a backfill).

**What an old event's evidence reads.** The window is built from the event's
own report times and ends no later than now, but the Open-Meteo request covers
yesterday and today only, and "in force" means in force now. So an event more
than a day old mostly gets its model evidence offline and no official warning;
the airport observations stored in the database still count. Its verdict is
then honest about what can still be checked, which is usually UNCONFIRMED.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

TRIGGER = "backfill:receipt_v2"


async def run(dry_run: bool, every: bool, limit: int | None) -> int:
    from sqlalchemy import text

    from app.core.database import async_session
    from app.services import pipeline

    where = "review_status <> 'REJECTED'" + ("" if every else " AND verdict IS NULL")
    async with async_session() as db:
        ids = [r[0] for r in (await db.execute(text(
            f"SELECT id FROM verified_events WHERE {where} ORDER BY verified_at, id"
            + (f" LIMIT {int(limit)}" if limit else "")
        ))).fetchall()]

    print(f"{len(ids)} event(s) to re-score ({'every non-rejected event' if every else 'no verdict yet'})")
    if dry_run:
        return 0

    changed = 0
    verdicts: Counter = Counter()
    for event_id in ids:
        async with async_session() as db:
            event = await pipeline.rescore_event(
                db, event_id, trigger=TRIGGER, trigger_detail={"script": "rescore_events.py"}
            )
        if event is not None:
            changed += 1
            verdicts[event["verdict"]] += 1
            print(f"  {event['event_code']}: {event['late_corroboration']['before']['confidence_score']}"
                  f" -> {event['confidence_score']}, {event['verdict']}, {event['review_status']}")

    print(f"re-scored {len(ids)}, changed {changed}")
    for verdict, n in sorted(verdicts.items()):
        print(f"  {verdict}: {n}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, write nothing")
    parser.add_argument("--all", action="store_true", help="every non-rejected event, not only those without a verdict")
    parser.add_argument("--limit", type=int, default=None, help="at most this many events")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run, args.all, args.limit))


if __name__ == "__main__":
    sys.exit(main())
