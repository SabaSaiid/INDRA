#!/usr/bin/env python3
"""
Tag every report INDRA already holds with its hazards (Phase 3 T4).

    backend/.venv/bin/python scripts/backfill_hazards.py
    backend/.venv/bin/python scripts/backfill_hazards.py --dry-run

Reports stored before Phase 3 (citizen reports, and the posts and headlines
the Phase 2 pollers have collected since 24 Sep) have no hazards, because the
tagger did not exist when they arrived. This re-runs the same layer-3
extraction ingest now runs (`ingest.analyse`), over every row, in batches of
1,000, and writes:

    raw_reports.analysis        the full extraction, hazards included
    raw_reports.hazard_primary  the hazard the report is about, or NULL
    raw_reports.hazard_family   its family, or NULL
    raw_reports.flags           the misleading-text flags (T8)
    raw_reports.credibility_score  the source prior × the flags' multipliers (T8)

**Idempotent.** A row is written only when something differs from what is
stored, ignoring `analysis.extracted_at`, so a second run changes 0 rows and
says so. `raw_text` is never touched. Nothing about clustering or events
changes: an event's type is decided when its reports are processed (T6).

Prints how many rows it scanned and changed, then the count per primary hazard
across the whole table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

BATCH = 1000

SELECT = """
    SELECT id, raw_text, CAST(source_type AS text), analysis, hazard_primary, hazard_family, flags,
           credibility_score
    FROM raw_reports
    WHERE (CAST(:after AS uuid) IS NULL OR id > CAST(:after AS uuid))
    ORDER BY id
    LIMIT :batch
"""

UPDATE = """
    UPDATE raw_reports SET
        analysis = CAST(:analysis AS jsonb),
        hazard_primary = :hazard_primary,
        hazard_family = :hazard_family,
        flags = CAST(:flags AS text[]),
        credibility_score = :credibility
    WHERE id = CAST(:id AS uuid)
"""


def _comparable(analysis: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if analysis is None:
        return None
    return {k: v for k, v in analysis.items() if k != "extracted_at"}


async def run(dry_run: bool) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.services.ingest import derive_text_fields

    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    scanned = changed = 0
    after = None
    try:
        while True:
            async with engine.begin() as conn:
                rows = (await conn.execute(text(SELECT), {"after": after, "batch": BATCH})).fetchall()
                if not rows:
                    break
                updates = []
                for rid, raw_text, source_type, analysis, primary, family, flags, credibility in rows:
                    scanned += 1
                    # `coordinated` comes from other reports, not the text:
                    # kept as the pipeline set it, with its reason.
                    kept = [f for f in (flags or []) if f == "coordinated"]
                    new = derive_text_fields(source_type, raw_text or "", rid, extra_flags=kept)
                    if kept and new["analysis"] is not None and analysis:
                        reason = (analysis.get("flag_basis") or {}).get("coordinated")
                        if reason:
                            new["analysis"].setdefault("flag_basis", {})["coordinated"] = reason
                    same = (
                        _comparable(new["analysis"]) == _comparable(analysis)
                        and new["hazard_primary"] == primary
                        and new["hazard_family"] == family
                        and list(new["flags"]) == list(flags or [])
                        and round(new["credibility"], 4) == round(float(credibility or 0), 4)
                    )
                    if same:
                        continue
                    updates.append({
                        "id": str(rid),
                        "analysis": json.dumps(new["analysis"]) if new["analysis"] is not None else None,
                        "hazard_primary": new["hazard_primary"],
                        "hazard_family": new["hazard_family"],
                        "flags": list(new["flags"]),
                        "credibility": new["credibility"],
                    })
                if updates and not dry_run:
                    await conn.execute(text(UPDATE), updates)
                changed += len(updates)
                after = str(rows[-1][0])
                print(f"  … {scanned} scanned, {changed} {'would change' if dry_run else 'changed'}")

        async with engine.connect() as conn:
            counts = Counter({
                (r[0] or "(none)"): r[1]
                for r in (await conn.execute(text(
                    "SELECT hazard_primary, count(*) FROM raw_reports GROUP BY hazard_primary"
                ))).fetchall()
            })
    finally:
        await engine.dispose()

    print(f"{scanned} rows scanned, {changed} {'would change' if dry_run else 'changed'}")
    print("primary hazard, whole table" + (" (before this dry run)" if dry_run else "") + ":")
    for hazard, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {hazard:<20} {n}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would change, write nothing")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
