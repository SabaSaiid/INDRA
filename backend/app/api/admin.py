"""
INDRA Platform — The source credibility table (layer 8a, Phase 5 T6)

GET /api/admin/sources — ANALYST, COMMANDER or ADMIN

What each kind of source has contributed and how human reviewers judged it,
so "why does INDRA trust a citizen report at 0.60?" has an answer with numbers
behind it:

* **by source type and platform:** reports, how many landed in events a
  commander approved or rejected, the share a flag marked down, and the prior
  the fusion engine starts from (`SOURCE_RELIABILITY`);
* **by news publisher:** the same, plus its trust by the published formula
  (T7: publishers get no account flags; each has its own record here);
* **the 20 most active reporters,** as **hashes only**, with their trust and
  the multiplier their next report gets (services/reputation.py);
* **rate limiting** (T8): how many submissions were refused in the last 24 h.

No raw id, handle or name appears anywhere in the answer: reporter hashes are
the only identifiers.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TokenData, require_roles
from app.services import reputation
from app.services.fusion_engine import SOURCE_RELIABILITY
from app.services.report_flags import FLAGS

logger = logging.getLogger("indra.api.admin")
router = APIRouter(prefix="/api/admin", tags=["Admin"])

TOP_REPORTERS = 20
TOP_PUBLISHERS = 50

# Flags that lower credibility: what "flagged" counts.
PENALISING = [flag for flag, factor in FLAGS.items() if factor is not None]


def _prior(source_type: str) -> float:
    try:
        return float(SOURCE_RELIABILITY[source_type])
    except KeyError:
        return min(SOURCE_RELIABILITY.values())


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


@router.get("/sources")
async def source_credibility(
    operator: TokenData = Depends(require_roles("ANALYST", "COMMANDER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        by_source = (await db.execute(
            text("""
                SELECT CAST(r.source_type AS text), r.platform, count(*),
                       count(*) FILTER (WHERE CAST(e.review_status AS text) = 'HUMAN_APPROVED'),
                       count(*) FILTER (WHERE CAST(e.review_status AS text) = 'REJECTED'),
                       count(*) FILTER (WHERE COALESCE(r.flags, '{}'::text[]) && CAST(:pen AS text[]))
                FROM raw_reports r
                LEFT JOIN verified_events e ON e.id = r.event_id
                WHERE r.duplicate_of IS NULL
                GROUP BY 1, 2
                ORDER BY 3 DESC
            """),
            {"pen": PENALISING},
        )).fetchall()
        publishers = (await db.execute(
            text("""
                SELECT lower(COALESCE(r.source_meta->>'publisher_domain', r.source_meta->>'publisher')),
                       max(r.source_meta->>'publisher'), count(*),
                       count(DISTINCT e.id) FILTER (WHERE CAST(e.review_status AS text) = 'HUMAN_APPROVED'),
                       count(DISTINCT e.id) FILTER (WHERE CAST(e.review_status AS text) = 'REJECTED'),
                       count(*) FILTER (WHERE COALESCE(r.flags, '{}'::text[]) && CAST(:pen AS text[]))
                FROM raw_reports r
                LEFT JOIN verified_events e ON e.id = r.event_id
                WHERE CAST(r.source_type AS text) = 'NEWS_MEDIA'
                  AND r.duplicate_of IS NULL
                  AND COALESCE(r.source_meta->>'publisher_domain', r.source_meta->>'publisher') IS NOT NULL
                GROUP BY 1
                ORDER BY 3 DESC
                LIMIT :n
            """),
            {"pen": PENALISING, "n": TOP_PUBLISHERS},
        )).fetchall()
        reporters = (await db.execute(
            text("""
                SELECT reporter_hash, source_type, platform, reports, approved, rejected, flagged,
                       first_seen, last_seen
                FROM reporter_stats
                ORDER BY reports DESC, reporter_hash
                LIMIT :n
            """),
            {"n": TOP_REPORTERS},
        )).fetchall()
    except Exception as e:
        logger.warning(f"Database query failed in source_credibility: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    from app.services.rate_limit import rejected_last_24h

    return {
        "sources": [
            {
                "source_type": r[0],
                "platform": r[1],
                "reports": r[2],
                "in_approved_events": r[3],
                "in_rejected_events": r[4],
                "flagged": r[5],
                "flagged_share": _share(r[5], r[2]),
                "prior": _prior(r[0]),
            }
            for r in by_source
        ],
        "publishers": [
            {
                "publisher": r[1] or r[0],
                "domain": r[0],
                "items": r[2],
                "approved_events": r[3],
                "rejected_events": r[4],
                "flagged_share": _share(r[5], r[2]),
                "prior": _prior("NEWS_MEDIA"),
                "trust": reputation.trust(r[3], r[4]),
            }
            for r in publishers
        ],
        "top_reporters": [
            {
                # The keyed hash only: never the device id or an account handle.
                "reporter_hash": r[0],
                "source_type": r[1],
                "platform": r[2],
                "reports": r[3],
                "approved": r[4],
                "rejected": r[5],
                "flagged": r[6],
                "trust": reputation.trust(r[4], r[5]),
                "multiplier": reputation.multiplier(r[4], r[5]),
                "first_seen": r[7].isoformat() if r[7] else None,
                "last_seen": r[8].isoformat() if r[8] else None,
            }
            for r in reporters
        ],
        "rate_limited_24h": await rejected_last_24h(),
        "rules": {
            "trust": "(approved + 1) / (approved + rejected + 2); only human decisions count",
            "credibility": "× (0.5 + trust), at most 1.0",
            "flagged": "reports carrying a flag that lowers credibility (report_flags.FLAGS)",
        },
    }
