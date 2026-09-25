"""
INDRA Platform — Google News poller (layers 1 and 2, Phase 2 T5: headlines)

Every NEWS_POLL_INTERVAL_SECONDS, run each weather query against Google News'
RSS search, in English (`hl=en-IN&gl=IN&ceid=IN:en`) and Hindi
(`hl=hi&gl=IN&ceid=IN:hi`), and store each new headline through
`ingest.store_report()`:

    source_type     NEWS_MEDIA              platform     google_news
    external_id     the item's guid
    raw_text        the headline (and the description, in the rare case it
                    adds anything)
    observed_at     the item's pubDate, in UTC
    place           from the headline's words (geocoding.place_from_text)
    source_meta     publisher, publisher_domain, url, query, language,
                    headline_key, stale

**Headline, link and publisher only.** The article is the publisher's; INDRA
keeps what the feed shows and links to the rest.

**One story, one row.** The same guid under two queries is one item (the
unique (platform, external_id) does that). The same headline from the same
publisher under a different guid — Google re-issues items — is caught by
(publisher, headline_key) before storing.

**Old news is kept but marked.** An item first seen more than
NEWS_STALE_AFTER_HOURS after it was published is stored with `stale: true`
and never clustered: the search feed happily returns last week's floods.

Two seconds between queries. Google sends no Last-Modified or ETag for these
feeds, so every tick reads every query; If-Modified-Since is sent anyway in
case it ever starts to. One malformed or failed query costs that query.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.services.geocoding import place_from_text
from app.services.ingest import StoreError, store_report
from app.services.news_rss import FeedUnreadable, NewsItem, parse_feed

logger = logging.getLogger("indra.workers.news_poller")

FEED = "google_news"
PLATFORM = "google_news"
USER_AGENT = "INDRA-SIH2026/1.0 (Team Sixth Sense; disaster situational awareness)"
LOCALES = {
    "en": {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
    "hi": {"hl": "hi", "gl": "IN", "ceid": "IN:hi"},
}


def item_to_report(
    item: NewsItem, query: str, language: str, now: datetime
) -> Dict[str, Any]:
    """The store_report() arguments for one item. Pure: `now` is passed in."""
    settings = get_settings()
    stale = bool(
        item.published_at
        and now - item.published_at > timedelta(hours=settings.NEWS_STALE_AFTER_HOURS)
    )
    body = item.headline if not item.description else f"{item.headline}\n{item.description}"
    place = place_from_text(item.headline)
    return {
        "source_type": "NEWS_MEDIA",
        "raw_text": body,
        "latitude": place["lat"],
        "longitude": place["lng"],
        "district": place["district"],
        "state": place["state"],
        "observed_at": item.published_at,
        "platform": PLATFORM,
        "external_id": item.guid[:512],
        "source_meta": {
            "publisher": item.publisher,
            "publisher_domain": item.publisher_domain,
            "url": item.link,
            "query": query,
            "language": language,
            "headline_key": item.headline_key,
            "stale": stale,
            "place_basis": place["matched"],
        },
        "issue_docket": False,
        "place_precision": place["precision"],
    }


async def fetch_query(
    client: httpx.AsyncClient, query: str, language: str, if_modified_since: Optional[str]
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """(body, last_modified, error). body None with no error means 304. Never raises."""
    settings = get_settings()
    headers = {"User-Agent": USER_AGENT}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    params = {"q": query, **LOCALES[language]}
    try:
        resp = await client.get(
            settings.NEWS_RSS_URL, params=params, headers=headers,
            timeout=settings.NEWS_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return None, None, f"{query!r}: {type(e).__name__}: {e}"
    if resp.status_code == 304:
        return None, if_modified_since, None
    if resp.status_code != 200:
        return None, None, f"{query!r}: HTTP {resp.status_code}"
    return resp.content, resp.headers.get("Last-Modified") or None, None


async def _already_stored(db, publisher: Optional[str], key: str) -> bool:
    """The same headline from the same publisher, under any guid."""
    if not publisher or not key:
        return False
    row = (await db.execute(
        text("""
            SELECT 1 FROM raw_reports
            WHERE platform = 'google_news'
              AND source_meta->>'publisher' = :publisher
              AND source_meta->>'headline_key' = :key
            LIMIT 1
        """),
        {"publisher": publisher, "key": key},
    )).first()
    return row is not None


@dataclass
class TickResult:
    written: int = 0
    seen: int = 0
    queries_ok: int = 0
    errors: List[str] = field(default_factory=list)
    last_modified: Dict[str, str] = field(default_factory=dict)
    feeds: List[Tuple[str, str, bytes]] = field(default_factory=list)  # (language, query, body)


async def poll_once(
    db,
    client: Optional[httpx.AsyncClient] = None,
    last_modified: Optional[Dict[str, str]] = None,
    sleep=asyncio.sleep,
    now: Optional[datetime] = None,
) -> TickResult:
    """One pass over every query. `last_modified` maps "lang:query" to its header."""
    settings = get_settings()
    result = TickResult(last_modified=dict(last_modified or {}))
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.NEWS_TIMEOUT_SECONDS)

    # Within one tick, across queries: (publisher, headline_key) already handled.
    handled: Set[Tuple[str, str]] = set()
    try:
        for i, (language, query) in enumerate(settings.news_queries):
            if i and settings.NEWS_REQUEST_DELAY_SECONDS:
                await sleep(settings.NEWS_REQUEST_DELAY_SECONDS)
            key = f"{language}:{query}"
            body, modified, error = await fetch_query(
                client, query, language, result.last_modified.get(key)
            )
            if error:
                result.errors.append(error)
                logger.warning(f"Google News: {error}")
                continue
            result.queries_ok += 1
            if modified:
                result.last_modified[key] = modified
            if body is None:
                continue  # 304

            try:
                items = parse_feed(body)
            except FeedUnreadable as e:
                result.errors.append(f"{query!r}: {e}")
                logger.warning(f"Google News {query!r}: {e}")
                result.queries_ok -= 1
                continue
            result.feeds.append((language, query, body))
            result.seen += len(items)

            tick_now = now or datetime.now(timezone.utc)
            for item in items:
                dedup_key = (item.publisher or "", item.headline_key)
                if dedup_key in handled:
                    continue
                handled.add(dedup_key)
                try:
                    if await _already_stored(db, item.publisher, item.headline_key):
                        continue
                    stored = await store_report(db, **item_to_report(item, query, language, tick_now))
                except StoreError as e:
                    result.errors.append(f"{query!r}: an item was not stored: {e}")
                    continue
                if stored.created:
                    result.written += 1
    finally:
        if own_client:
            await client.aclose()
    return result


async def run_tick(session_factory=None) -> TickResult:
    """One scheduled tick: poll, then record the heartbeat."""
    from app.services.feed_status import get_cursor, record_tick

    if session_factory is None:
        from app.core.database import async_session as session_factory

    last_modified = (await get_cursor(FEED)).get("last_modified") or {}
    try:
        async with session_factory() as db:
            result = await poll_once(db, last_modified=last_modified)
    except Exception as e:
        await record_tick(FEED, ok=False, error=f"{type(e).__name__}: {e}")
        raise

    # Each query's RSS as fetched, into the lake's raw layer (T9). Never raises.
    from app.services import lake

    for language, query, body in result.feeds:
        await lake.put_raw(
            FEED, body, "application/rss+xml", metadata={"query": query, "language": language}
        )

    if result.written:
        logger.info(
            f"Google News poll stored {result.written} new headlines "
            f"({result.seen} items over {result.queries_ok} queries)"
        )
    await record_tick(
        FEED,
        ok=result.queries_ok > 0,
        items=result.written,
        error="; ".join(result.errors)[:500] if result.errors else None,
        cursor={"last_modified": result.last_modified} if result.last_modified else None,
    )
    return result


async def start_news_poller() -> None:
    """The lifespan task. Polls at once, then every interval."""
    settings = get_settings()
    if not settings.NEWS_POLLER_ENABLED:
        logger.info("Google News poller disabled (NEWS_POLLER_ENABLED=false)")
        return

    from app.core.database import async_session

    logger.info(
        f"✓ Google News poller started — {len(settings.news_queries)} queries every "
        f"{settings.NEWS_POLL_INTERVAL_SECONDS}s"
    )
    while True:
        try:
            await run_tick(async_session)
        except asyncio.CancelledError:
            logger.info("Google News poller shutting down...")
            raise
        except Exception as e:
            logger.warning(f"Google News poll failed (non-fatal): {type(e).__name__}: {e}")

        try:
            await asyncio.sleep(settings.NEWS_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Google News poller shutting down...")
            raise
