"""
INDRA Platform — Feed heartbeats (layers 1 and 8a, Phase 2 T2)

Every feed INDRA reads, in one registry, and the heartbeat each poller writes
at the end of every tick.

**Why a heartbeat.** Until Phase 2, `GET /api/meta/sources` inferred whether a
poller was alive from the newest row it had written. A poller that ran and
found nothing new looked exactly like one that had died, and an error was
never recorded anywhere but a log line. Now each tick records its outcome in
`feed_status` (migration 0015), and the status is read from that:

    disabled   the poller's *_ENABLED setting is false
    failing    the last 3 ticks failed in a row (`last_error` says why)
    stale      no successful tick for 3 × the poll interval, or never one
    ok         otherwise

Push feeds — citizen reports and official dispatches — have no tick to record.
They are always `ok` (quiet is not broken for a feed that waits to be sent
something) and their `basis` says `push`.

`record_tick()` opens its own session, so a poller whose own transaction
rolled back still records the failure. It never raises: a heartbeat that fails
to write costs a line in the log, never the poller.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.config import get_settings

logger = logging.getLogger("indra.services.feed_status")

FAILING_AFTER_FAILURES = 3
STALE_AFTER_INTERVALS = 3
# Error text is stored for an operator to read, not to archive a traceback.
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class Feed:
    """One source INDRA reads, and where its rows land."""

    feed: str
    kind: str          # citizen, official, social, news, station, warnings
    title: str
    table: str         # the table its rows are counted in
    time_column: str   # the column rows_24h is counted on
    where: str         # which of that table's rows are this feed's
    enabled_setting: Optional[str] = None   # None: always on (a push feed)
    interval_setting: Optional[str] = None  # None: a push feed, which has no tick

    @property
    def push(self) -> bool:
        return self.interval_setting is None

    def enabled(self, settings=None) -> bool:
        if self.enabled_setting is None:
            return True
        return bool(getattr(settings or get_settings(), self.enabled_setting, False))

    def poll_interval_s(self, settings=None) -> Optional[int]:
        if self.interval_setting is None:
            return None
        return int(getattr(settings or get_settings(), self.interval_setting))


# The order is the order GET /api/meta/sources lists them in. The WHERE clauses
# are fixed strings, never built from a request.
FEEDS: List[Feed] = [
    Feed("citizen", "citizen", "Citizen reports", "raw_reports", "created_at",
         "CAST(source_type AS text) = 'CITIZEN_APP'"),
    Feed("official", "official", "Official dispatches", "raw_reports", "created_at",
         "CAST(source_type AS text) = 'OFFICIAL_DISPATCH'"),
    Feed("sachet", "warnings", "Official warnings (SACHET CAP)", "agency_alerts", "fetched_at",
         "TRUE", "SACHET_POLLER_ENABLED", "SACHET_POLL_INTERVAL_SECONDS"),
    Feed("open_meteo", "station", "Open-Meteo rainfall", "station_readings", "recorded_at",
         "CAST(agency AS text) = 'OPEN_METEO'", "STATION_POLLER_ENABLED",
         "STATION_POLL_INTERVAL_SECONDS"),
    # Counted on recorded_at, the observation time: rows_24h is "observations
    # made in the last day", which is what an airport network is judged on.
    Feed("metar", "station", "Airport weather (METAR)", "station_readings", "recorded_at",
         "feed = 'metar'", "METAR_POLLER_ENABLED", "METAR_POLL_INTERVAL_SECONDS"),
]

FEEDS_BY_NAME: Dict[str, Feed] = {f.feed: f for f in FEEDS}


def feed_state(
    *,
    enabled: bool,
    push: bool,
    last_success_at: Optional[datetime],
    consecutive_failures: int,
    poll_interval_s: Optional[int],
    now: datetime,
) -> str:
    """ok | stale | failing | disabled. Pure; see the module docstring."""
    if not enabled:
        return "disabled"
    if push:
        return "ok"
    if consecutive_failures >= FAILING_AFTER_FAILURES:
        return "failing"
    if last_success_at is None:
        return "stale"
    window = STALE_AFTER_INTERVALS * (poll_interval_s or 0)
    if (now - last_success_at).total_seconds() > window:
        return "stale"
    return "ok"


def stale_after_s(feed: Feed, settings=None) -> Optional[int]:
    interval = feed.poll_interval_s(settings)
    return None if interval is None else STALE_AFTER_INTERVALS * interval


_UPSERT = text("""
    INSERT INTO feed_status AS fs
        (feed, kind, enabled, last_attempt_at, last_success_at, last_error_at, last_error,
         consecutive_failures, items_last_tick, rows_total, cursor, updated_at)
    VALUES (
        :feed, :kind, :enabled, now(),
        CASE WHEN :ok THEN now() END,
        CASE WHEN CAST(:error AS text) IS NOT NULL THEN now() END,
        CAST(:error AS text),
        CASE WHEN :ok THEN 0 ELSE 1 END,
        :items, :items, CAST(:cursor AS jsonb), now()
    )
    ON CONFLICT (feed) DO UPDATE SET
        kind = EXCLUDED.kind,
        enabled = EXCLUDED.enabled,
        last_attempt_at = now(),
        last_success_at = CASE WHEN :ok THEN now() ELSE fs.last_success_at END,
        last_error_at = CASE WHEN CAST(:error AS text) IS NOT NULL THEN now() ELSE fs.last_error_at END,
        last_error = COALESCE(CAST(:error AS text), fs.last_error),
        consecutive_failures = CASE WHEN :ok THEN 0 ELSE fs.consecutive_failures + 1 END,
        items_last_tick = :items,
        rows_total = fs.rows_total + :items,
        -- A tick that learned no new resume point keeps the old one.
        cursor = COALESCE(CAST(:cursor AS jsonb), fs.cursor),
        updated_at = now()
""")


async def record_tick(
    feed: str,
    *,
    ok: bool,
    items: int = 0,
    error: Optional[str] = None,
    cursor: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record one tick's outcome. Never raises.

    `ok=False` counts towards `failing`; give the reason in `error`. A tick that
    succeeded only in part (one Mastodon instance of two answered) is `ok=True`
    with `error` set: it resets the failure count and still records what went
    wrong.
    """
    spec = FEEDS_BY_NAME.get(feed)
    if not ok and not error:
        error = "tick failed"
    try:
        from app.core.database import async_session

        async with async_session() as db:
            await db.execute(_UPSERT, {
                "feed": feed,
                "kind": spec.kind if spec else "unknown",
                "enabled": spec.enabled() if spec else True,
                "ok": bool(ok),
                "error": error[:MAX_ERROR_LENGTH] if error else None,
                "items": int(items or 0),
                "cursor": json.dumps(cursor) if cursor is not None else None,
            })
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not record the {feed} tick (non-fatal): {type(e).__name__}: {e}")


async def get_cursor(feed: str) -> Dict[str, Any]:
    """The feed's stored resume point; {} if none or unreadable."""
    try:
        from app.core.database import async_session

        async with async_session() as db:
            value = (await db.execute(
                text("SELECT cursor FROM feed_status WHERE feed = :feed"), {"feed": feed}
            )).scalar()
        return dict(value) if isinstance(value, dict) else {}
    except Exception as e:
        logger.warning(f"Could not read the {feed} cursor, starting fresh: {type(e).__name__}: {e}")
        return {}


async def load_heartbeats(db) -> Dict[str, Dict[str, Any]]:
    """Every feed_status row, keyed by feed."""
    rows = (await db.execute(text("""
        SELECT feed, last_attempt_at, last_success_at, last_error_at, last_error,
               consecutive_failures, items_last_tick, rows_total
        FROM feed_status
    """))).mappings().all()
    return {r["feed"]: dict(r) for r in rows}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
