"""
INDRA Platform — Anti-flooding rate limits (layer 8a, Phase 5 T8)

"What stops someone flooding you with fake reports?" Three sliding windows,
each in Redis and, when Redis is down, in process memory (degraded, but still
limiting):

| scope                          | limit (`.env`)                                        |
|--------------------------------|-------------------------------------------------------|
| per device (`X-Reporter-Id`)   | RATE_LIMIT_REPORTS_PER_REPORTER = 10 per 10 minutes   |
| per IP address                 | RATE_LIMIT_REPORTS_PER_IP = 300 per 10 minutes        |
| docket lookups, per IP         | RATE_LIMIT_TRACK_PER_IP_PER_MINUTE = 60 per minute    |

Over a limit → **429** with `Retry-After`, and nothing is stored. The official
route is exempt: an operator's login is its check.

The per-IP limit is 300, not the plan's 30. Indian mobile carriers put many
phones behind one address (CGNAT), so 30 would block a flooded town while one
script still could not get past the per-device limit (webpage.MD §11.6, B10).
The client's address is the one the proxy saw (core/client_ip.py).

Every refusal is counted per hour for 25 hours, and `GET /api/meta/sources`
and `GET /api/admin/sources` show the last 24 h, so abuse is visible.
"""

import hashlib
import logging
import time
from typing import Optional

from fastapi import HTTPException, Request

from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.services import cache

logger = logging.getLogger("indra.services.rate_limit")

REJECTED_KEY_PREFIX = "rl:rejected:"
REJECTED_TTL_SECONDS = 25 * 60 * 60


def _device_key(reporter_id: Optional[str]) -> Optional[str]:
    """A key for one device, never the id itself: its keyed hash, or a plain SHA-256 without a salt."""
    if reporter_id is None or not reporter_id.strip():
        return None
    from app.services.ingest import reporter_hash_for

    return reporter_hash_for(reporter_id) or hashlib.sha256(reporter_id.strip().encode()).hexdigest()


async def _count_rejection(scope: str) -> None:
    hour = int(time.time() // 3600)
    await cache.incr(f"{REJECTED_KEY_PREFIX}{hour}", REJECTED_TTL_SECONDS)
    logger.info(f"Rate limit: a request refused ({scope})")


async def rejected_last_24h() -> int:
    """How many submissions and lookups were refused in the last 24 hours. Never raises."""
    hour = int(time.time() // 3600)
    total = 0
    for h in range(hour - 23, hour + 1):
        value = await cache.get_json(f"{REJECTED_KEY_PREFIX}{h}")
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            continue
    return total


def _too_many(retry_after: int, what: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Too many {what}; try again in {retry_after} seconds",
        headers={"Retry-After": str(retry_after)},
    )


async def check_report(request: Request, reporter_id: Optional[str]) -> None:
    """Raise 429 if this device or this address has sent too many reports. Counts the report if not."""
    settings = get_settings()
    if not settings.RATE_LIMIT_ENABLED:
        return
    window = settings.RATE_LIMIT_WINDOW_SECONDS
    device = _device_key(reporter_id)
    if device:
        allowed, retry = await cache.sliding_window(
            f"rl:rep:{device}", settings.RATE_LIMIT_REPORTS_PER_REPORTER, window
        )
        if not allowed:
            await _count_rejection("per device")
            raise _too_many(retry, "reports from this device")
    allowed, retry = await cache.sliding_window(
        f"rl:ip:{client_ip(request)}", settings.RATE_LIMIT_REPORTS_PER_IP, window
    )
    if not allowed:
        await _count_rejection("per address")
        raise _too_many(retry, "reports from this network")


async def check_lookup(request: Request) -> None:
    """Raise 429 if this address has made too many docket lookups in the last minute."""
    settings = get_settings()
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry = await cache.sliding_window(
        f"rl:track:{client_ip(request)}", settings.RATE_LIMIT_TRACK_PER_IP_PER_MINUTE, 60
    )
    if not allowed:
        await _count_rejection("docket lookups")
        raise _too_many(retry, "lookups")
