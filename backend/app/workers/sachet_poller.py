"""
INDRA Platform — SACHET poller (layer 1: official agency warnings)

Polls NDMA's national CAP feed and stores each live warning in `agency_alerts`.

    RSS index   https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml
    CAP detail  .../FetchXMLFile?identifier={guid}
    Polygon     .../FetchPolygonXMLFile?identifier={guid}

Verified against the live feed on 21 Sep 2026: 99 alerts, senders including IMD
Ahmedabad (18), Andhra Pradesh SDMA (11), IMD Bengaluru (9), IMD Chennai (9),
IMD Mumbai (8), IMD Kolkata (7), CWC (7). No API key, no registration.

**Why this is worth a worker.** IMD's own API answers `401 "IP … needs to be
whitelisted"` and CWC publishes no API at all, so this feed is the only route to
either agency's warnings inside a hackathon timeline. It is also the first
independent evidence the confidence receipt has ever had: until now every factor
was derived from the citizen reports themselves, which cannot corroborate each
other no matter how many arrive.

Four rules this worker follows, each for a reason found by running it:

1. **ETag caching, as NDMA's integration guide for agencies requires.** The index
   is 67 KB and changes a few times an hour. The `If-None-Match` header is sent
   on every poll and a `304` costs one request and no parsing. A public feed run
   by a disaster agency is not somewhere to spend bandwidth carelessly.

2. **Only new or updated alerts are fetched in detail.** An identifier already
   stored with the same `sent` timestamp is skipped without touching the CAP or
   polygon endpoints — otherwise a five-minute poll would pull 99 CAP documents
   and up to 99 polygons, some 235 KB each, forever.

3. **Detail fetches are throttled and bounded per tick.** `SACHET_MAX_FETCHES_PER_TICK`
   caps the burst on a cold start, where all 99 alerts are new at once. The rest
   arrive on the next tick.

4. **One failed alert costs one alert.** Every fetch and parse is wrapped
   individually. A single malformed CAP document must not abort the tick and lose
   the other 98.

Single process only, like the station poller and the Kafka consumer: two backends
polling would double-write. Same rule as BUG-011.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, NamedTuple, Optional, Tuple

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.agency_alerts import AgencyAlert
from app.services.cap_parser import (
    CapAlert,
    RssItem,
    parse_cap_alert,
    parse_polygon_points,
    parse_rss,
    polygon_to_wkt,
    thin,
)

logger = logging.getLogger("indra.workers.sachet_poller")
settings = get_settings()

# NDMA asks agencies to identify themselves rather than poll anonymously.
USER_AGENT = "INDRA-SIH2026/1.0 (Team Sixth Sense; disaster situational awareness)"

# This feed's name in feed_status and GET /api/meta/sources.
FEED = "sachet"

# Why the last tick failed, or None. fetch_index answers None both for "304,
# nothing changed" and for "unreachable", which is right for the tick's work but
# not for its heartbeat: the first is a success and the second is not. This is
# where the difference is kept (Phase 2 T2).
last_tick_error: Optional[str] = None

# Process-local ETag for the index. Deliberately not persisted: after a restart
# one full fetch is correct, since the database may have been rebuilt.
_index_etag: Optional[str] = None


def _reset_etag_for_tests() -> None:
    """Tests share a module, and a stale ETag would make the second one see 304."""
    global _index_etag
    _index_etag = None


def _failed(message: str) -> None:
    """Log a tick-level failure and keep it for the heartbeat."""
    global last_tick_error
    last_tick_error = message
    logger.warning(message)


async def fetch_index(client: httpx.AsyncClient) -> Optional[List[RssItem]]:
    """
    The RSS index, or None when nothing changed (304) or the fetch failed.

    None is deliberately ambiguous between "unchanged" and "unreachable": both
    mean this tick has no work, and both are logged distinctly. Never raises.
    """
    global _index_etag

    headers = {"User-Agent": USER_AGENT}
    if _index_etag:
        headers["If-None-Match"] = _index_etag

    try:
        resp = await client.get(
            settings.SACHET_RSS_URL,
            headers=headers,
            timeout=settings.SACHET_TIMEOUT_SECONDS,
        )
    except Exception as e:
        _failed(f"SACHET index fetch failed: {type(e).__name__}: {e}")
        return None

    if resp.status_code == 304:
        logger.debug("SACHET index unchanged (304)")
        return None
    if resp.status_code != 200:
        _failed(f"SACHET index returned HTTP {resp.status_code}")
        return None

    # Only remember the ETag once the body parsed. Storing it first would mean a
    # feed that arrived truncated is never re-fetched, because the next poll
    # sends its ETag and is told 304.
    items = parse_rss(resp.content)
    if not items:
        _failed("SACHET index parsed to zero alerts; ETag not stored")
        return None

    _index_etag = resp.headers.get("ETag") or None
    return items


async def fetch_cap(client: httpx.AsyncClient, item: RssItem) -> Optional[CapAlert]:
    """The CAP document for one index item. Never raises."""
    url = item.cap_url or (
        f"{settings.SACHET_CAP_URL}?identifier={item.identifier}"
    )
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=settings.SACHET_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning(f"SACHET CAP fetch failed for {item.identifier}: {type(e).__name__}: {e}")
        return None

    if resp.status_code != 200:
        logger.warning(f"SACHET CAP {item.identifier} returned HTTP {resp.status_code}")
        return None

    return parse_cap_alert(resp.content)


class PolygonResult(NamedTuple):
    """
    The outcome of trying to fetch one alert's footprint.

    `status` exists because "this alert has no polygon" and "I could not fetch
    this alert's polygon" are different facts with opposite consequences, and
    collapsing them into a bare `None` cost every stored polygon in the
    database once already:

    ABSENT  — the CAP document carries no polygon URL. The agency published no
              footprint, so NULL is the truth and an existing one should be
              cleared.
    FAILED  — the request failed or the body was unusable. Nothing is known, so
              whatever is already stored must be LEFT ALONE. NDMA answers 403
              when a client fetches too fast; treating that as "the agency
              withdrew the polygon" wiped 96 good footprints in one pass.
    OK      — a usable ring.
    """

    status: str  # "ok" | "absent" | "failed"
    wkt: Optional[str] = None
    thinned: bool = False
    points: Optional[int] = None


ABSENT = PolygonResult("absent")
FAILED = PolygonResult("failed")


async def fetch_polygon(client: httpx.AsyncClient, alert: CapAlert) -> PolygonResult:
    """One alert's footprint, with absence distinguished from failure."""
    if not alert.polygon_url:
        return ABSENT

    try:
        resp = await client.get(
            alert.polygon_url,
            headers={"User-Agent": USER_AGENT},
            timeout=settings.SACHET_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning(
            f"SACHET polygon fetch failed for {alert.identifier}: {type(e).__name__}: {e}"
        )
        return FAILED

    if resp.status_code != 200:
        # 403 is NDMA throttling a client that asked too fast, not a withdrawn
        # warning area.
        logger.warning(
            f"SACHET polygon {alert.identifier} returned HTTP {resp.status_code}"
        )
        return FAILED

    points = parse_polygon_points(resp.content)
    if not points:
        return FAILED

    original = len(points)
    points, was_thinned = thin(points, settings.SACHET_MAX_POLYGON_POINTS)
    wkt = polygon_to_wkt(points)
    if wkt is None:
        logger.warning(
            f"SACHET polygon {alert.identifier} had {original} points but no usable ring"
        )
        return FAILED

    if was_thinned:
        logger.info(
            f"SACHET polygon {alert.identifier} thinned {original} → {len(points)} points"
        )
    return PolygonResult("ok", wkt, was_thinned, original)


def _needs_fetch(item: RssItem, stored: Dict[str, Optional[datetime]]) -> bool:
    """
    True when this identifier is new, or the feed shows it republished since the
    stored copy. Rule 2 in the module docstring.

    **`stored` holds `feed_published_at`, not `sent_at`.** The RSS `pubDate` and
    the CAP `sent` are different fields and they disagree — one live alert said
    `2026-09-21T07:54:00+05:30` (02:24 UTC) in its CAP document and
    `Mon, 21 Sep 2026 02:28:50 GMT` in the feed. Comparing the feed's timestamp
    against the stored CAP timestamp makes the feed look four minutes newer than
    the database on every single alert, forever: each tick refetches all 99 CAP
    documents and all 99 polygons. Freshness is judged feed-against-feed, which
    is the only comparison where the two values mean the same thing.

    An item with no `pubDate` is fetched whenever it is new and skipped once
    stored — without a timestamp there is no way to tell an update from a repeat,
    and refetching everything to find out is the behaviour this guard prevents.
    """
    if item.identifier not in stored:
        return True
    previous = stored[item.identifier]
    if previous is None or item.published_at is None:
        return False
    return item.published_at > previous


async def poll_once(db, client: Optional[httpx.AsyncClient] = None) -> Tuple[int, int]:
    """
    One tick: (alerts_written, alerts_seen).

    (0, 0) is a legitimate outcome — the feed was unchanged, or unreachable.
    (0, 99) means every alert in the feed was already stored, which is the steady
    state and is why this poller is cheap to run at a short interval.
    """
    global last_tick_error
    last_tick_error = None

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.SACHET_TIMEOUT_SECONDS)

    try:
        items = await fetch_index(client)
        if not items:
            return 0, 0

        # One query for the whole feed, not one per alert.
        identifiers = [item.identifier for item in items]
        rows = (
            await db.execute(
                select(AgencyAlert.identifier, AgencyAlert.feed_published_at).where(
                    AgencyAlert.identifier.in_(identifiers)
                )
            )
        ).all()
        stored: Dict[str, Optional[datetime]] = {r[0]: r[1] for r in rows}

        pending = [item for item in items if _needs_fetch(item, stored)]
        if len(pending) > settings.SACHET_MAX_FETCHES_PER_TICK:
            logger.info(
                f"SACHET: {len(pending)} alerts to fetch, capping at "
                f"{settings.SACHET_MAX_FETCHES_PER_TICK} this tick"
            )
            pending = pending[: settings.SACHET_MAX_FETCHES_PER_TICK]

        written = 0
        for item in pending:
            try:
                alert = await fetch_cap(client, item)
                if alert is None:
                    continue
                polygon = await fetch_polygon(client, alert)
                await _upsert(db, item, alert, polygon)
                written += 1
            except Exception as e:
                # Rule 4: one bad alert costs one alert.
                logger.warning(
                    f"SACHET alert {item.identifier} failed: {type(e).__name__}: {e}"
                )
                continue
            if settings.SACHET_FETCH_DELAY_SECONDS:
                await asyncio.sleep(settings.SACHET_FETCH_DELAY_SECONDS)

        if written:
            await db.commit()
        return written, len(items)

    except Exception as e:
        await db.rollback()
        _failed(f"SACHET poll tick failed: {type(e).__name__}: {e}")
        return 0, 0
    finally:
        if own_client:
            await client.aclose()


async def _upsert(
    db,
    item: RssItem,
    alert: CapAlert,
    polygon: PolygonResult,
) -> None:
    """
    Insert the alert, or update the existing row with the same identifier.

    The feed republishes an alert as a CAP `Update` under the same identifier, so
    an insert-only poller would multiply every warning by the number of times it
    was revised — and any corroboration count derived from the table would climb
    without a single new warning being issued.
    """
    existing = (
        await db.execute(
            select(AgencyAlert).where(AgencyAlert.identifier == item.identifier)
        )
    ).scalar_one_or_none()

    geom = func.ST_GeomFromText(polygon.wkt, 4326) if polygon.wkt else None

    values = {
        "sender": alert.sender or item.sender_name,
        "status": alert.status,
        "msg_type": alert.msg_type,
        "category": alert.category or item.category,
        "event": alert.event,
        "urgency": alert.urgency,
        "severity": alert.severity,
        "raw_severity": alert.raw_severity,
        "certainty": alert.certainty,
        "sent_at": alert.sent_at or item.published_at,
        "feed_published_at": item.published_at,
        "effective_at": alert.effective_at,
        "onset_at": alert.onset_at,
        "expires_at": alert.expires_at,
        "headline": alert.headline or item.title or None,
        "description": alert.description,
        "area_desc": alert.area_desc,
        "district_codes": alert.district_codes or None,
        "fetched_at": datetime.now(timezone.utc),
    }

    if existing is None:
        db.add(
            AgencyAlert(
                identifier=item.identifier,
                source_feed="SACHET",
                area_polygon=geom,
                polygon_thinned=polygon.thinned,
                polygon_points=polygon.points,
                **values,
            )
        )
        return

    for key, value in values.items():
        setattr(existing, key, value)

    # The footprint is only touched when this fetch actually learned something.
    #
    #   ok     — store the new ring.
    #   absent — the agency published no polygon this time, so clear the old one;
    #            their current geometry is the one that is true.
    #   failed — nothing was learned. Keep what is stored. This branch is the
    #            whole reason PolygonResult carries a status: the first version
    #            cleared on any falsy result, so one throttled pass (NDMA
    #            answers 403 to a fast client) emptied every footprint in the
    #            table while reporting 99 alerts stored successfully.
    if polygon.status == "ok":
        existing.area_polygon = geom
        existing.polygon_thinned = polygon.thinned
        existing.polygon_points = polygon.points
    elif polygon.status == "absent":
        existing.area_polygon = None
        existing.polygon_thinned = False
        existing.polygon_points = None


async def run_tick(session_factory=None) -> Tuple[int, int]:
    """
    One scheduled tick: poll, then record the heartbeat GET /api/meta/sources
    reads (Phase 2 T2). Returns (alerts_written, alerts_seen).

    A 304 is a successful tick that wrote nothing; an unreachable index or a
    tick that raised is a failed one.
    """
    from app.services.feed_status import record_tick

    if session_factory is None:
        from app.core.database import async_session as session_factory

    try:
        async with session_factory() as db:
            written, seen = await poll_once(db)
    except Exception as e:
        # Includes a database that is not up yet on a cold start.
        await record_tick(FEED, ok=False, error=f"{type(e).__name__}: {e}")
        raise

    if written:
        logger.info(f"SACHET poll stored {written} alerts ({seen} in feed)")
    elif seen:
        logger.debug(f"SACHET poll: all {seen} alerts already current")

    await record_tick(
        FEED, ok=last_tick_error is None, items=written, error=last_tick_error
    )
    return written, seen


async def start_sachet_poller() -> None:
    """
    The lifespan task. Polls immediately so a fresh stack has warnings within
    seconds, then every interval.
    """
    if not settings.SACHET_POLLER_ENABLED:
        logger.info("SACHET poller disabled (SACHET_POLLER_ENABLED=false)")
        return

    from app.core.database import async_session

    logger.info(
        f"✓ SACHET poller started — NDMA national CAP feed every "
        f"{settings.SACHET_POLL_INTERVAL_SECONDS}s"
    )

    while True:
        try:
            await run_tick(async_session)
        except asyncio.CancelledError:
            logger.info("SACHET poller shutting down...")
            raise
        except Exception as e:
            # The task must outlive any single failure.
            logger.warning(f"SACHET poll failed (non-fatal): {type(e).__name__}: {e}")

        try:
            await asyncio.sleep(settings.SACHET_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("SACHET poller shutting down...")
            raise
