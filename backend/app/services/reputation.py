"""
INDRA Platform — Reporter reputation (layers 6 and 8a, Phase 5 T6)

A reporter builds a record from **human decisions only**, because the
machine's own credibility is not ground truth:

* a commander **approving** an event adds `approved += 1` for each distinct
  reporter in it; **rejecting** it adds `rejected += 1`;
* an auto-published event changes nobody's record.

From the record, published and counted, never learned:

    trust      = (approved + 1) / (approved + rejected + 2)     0.5 for someone new
    multiplier = 0.5 + trust                                     0.5 … 1.5
    credibility of their next report = min(1.0, credibility × multiplier)

| history                   | trust | × |
|---------------------------|-------|---|
| new                       | 0.50  | 1.00 |
| 2 rejected                | 0.25  | 0.75 |
| 8 approved                | 0.90  | 1.40 (the result is capped at 1.0) |
| 3 approved, 3 rejected    | 0.50  | 1.00 |

It feeds `n_eff` through credibility, like every other signal. It is applied
when a report is stored, so what the receipt says a report counted for never
changes behind it; the line "reporter history: 0 approved, 2 rejected →
× 0.75" is kept in the report's `analysis.reputation` and shown in provenance.

One device cannot fake a crowd: its reports are one witness (n_eff), and a
device whose reports keep being rejected counts for less each time.
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger("indra.services.reputation")


def trust(approved: int, rejected: int) -> float:
    return round((int(approved) + 1) / (int(approved) + int(rejected) + 2), 4)


def multiplier(approved: int, rejected: int) -> float:
    return round(0.5 + trust(approved, rejected), 4)


def apply(credibility: float, approved: int, rejected: int) -> float:
    """A report's credibility after its reporter's record: × (0.5 + trust), capped at 1.0."""
    factor = multiplier(approved, rejected)
    if factor == 1.0:
        return round(credibility, 4)
    return round(min(1.0, credibility * factor), 4)


def reputation_basis(approved: int, rejected: int, before: float, after: float) -> Dict[str, Any]:
    """What provenance shows for one report, e.g. "reporter history: 0 approved, 2 rejected → × 0.75"."""
    factor = multiplier(approved, rejected)
    return {
        "approved": int(approved),
        "rejected": int(rejected),
        "trust": trust(approved, rejected),
        "multiplier": factor,
        "credibility_before": round(before, 4),
        "credibility_after": round(after, 4),
        "line": f"reporter history: {approved} approved, {rejected} rejected → × {factor:.2f}"
                + (" (capped at 1.0)" if before * factor > 1.0 else ""),
        "rule": "trust = (approved + 1) / (approved + rejected + 2); credibility × (0.5 + trust), at most 1.0",
    }


async def lookup(db, reporter_hash: Optional[str]) -> Optional[Dict[str, int]]:
    """{"approved", "rejected", "reports", "flagged"} for a reporter, or None if unknown."""
    if not reporter_hash:
        return None
    row = (await db.execute(
        text("SELECT approved, rejected, reports, flagged FROM reporter_stats WHERE reporter_hash = :h"),
        {"h": reporter_hash},
    )).fetchone()
    if row is None:
        return None
    return {"approved": row[0], "rejected": row[1], "reports": row[2], "flagged": row[3]}


async def note_report(
    db,
    reporter_hash: Optional[str],
    *,
    source_type: str,
    platform: Optional[str],
    flagged: bool,
) -> None:
    """One more report from this reporter, in the caller's transaction."""
    if not reporter_hash:
        return
    await db.execute(
        text("""
            INSERT INTO reporter_stats
                (reporter_hash, source_type, platform, reports, flagged, first_seen, last_seen)
            VALUES (:h, :source, :platform, 1, :flagged, NOW(), NOW())
            ON CONFLICT (reporter_hash) DO UPDATE SET
                reports = reporter_stats.reports + 1,
                flagged = reporter_stats.flagged + EXCLUDED.flagged,
                last_seen = NOW()
        """),
        {"h": reporter_hash, "source": source_type, "platform": platform, "flagged": 1 if flagged else 0},
    )


async def note_flagged(db, report_id: Any) -> None:
    """A report's credibility was lowered after it was stored (a media flag); count it once."""
    await db.execute(
        text("""
            UPDATE reporter_stats s SET flagged = s.flagged + 1
            FROM raw_reports r
            WHERE r.id = CAST(:id AS uuid) AND r.reporter_hash = s.reporter_hash
        """),
        {"id": str(report_id)},
    )


async def record_decision(db, event_id: Any, decision: str) -> int:
    """
    A commander approved ("approved") or rejected ("rejected") an event: every
    distinct reporter in it gets that decision for this event, replacing any
    earlier one, and their counts are recounted. In the caller's transaction,
    so the decision and the records commit together. Returns how many
    reporters were updated.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"not a human decision: {decision!r}")
    params = {"e": str(event_id), "d": decision}
    reporters = [r[0] for r in (await db.execute(
        text("""
            SELECT DISTINCT reporter_hash FROM raw_reports
            WHERE event_id = CAST(:e AS uuid) AND reporter_hash IS NOT NULL AND duplicate_of IS NULL
        """),
        params,
    )).fetchall()]
    if not reporters:
        return 0
    await db.execute(
        text("""
            INSERT INTO reporter_decisions (reporter_hash, event_id, decision, decided_at)
            SELECT h, CAST(:e AS uuid), :d, NOW() FROM unnest(CAST(:hashes AS text[])) AS h
            ON CONFLICT (reporter_hash, event_id) DO UPDATE SET
                decision = EXCLUDED.decision, decided_at = EXCLUDED.decided_at
        """),
        {**params, "hashes": reporters},
    )
    # A reporter known before 0022 but never seen since still gets a row.
    await db.execute(
        text("""
            INSERT INTO reporter_stats (reporter_hash, reports, first_seen, last_seen)
            SELECT h, 0, NULL, NULL FROM unnest(CAST(:hashes AS text[])) AS h
            ON CONFLICT (reporter_hash) DO NOTHING
        """),
        {"hashes": reporters},
    )
    await db.execute(
        text("""
            UPDATE reporter_stats s SET
                approved = (SELECT count(*) FROM reporter_decisions d
                            WHERE d.reporter_hash = s.reporter_hash AND d.decision = 'approved'),
                rejected = (SELECT count(*) FROM reporter_decisions d
                            WHERE d.reporter_hash = s.reporter_hash AND d.decision = 'rejected')
            WHERE s.reporter_hash = ANY(CAST(:hashes AS text[]))
        """),
        {"hashes": reporters},
    )
    logger.info(f"Reputation: event {event_id} {decision} for {len(reporters)} reporter(s)")
    return len(reporters)
