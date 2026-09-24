"""
INDRA Platform — Mastodon poller (layers 1 and 2, Phase 2 T4: #IMD posts)

The PS asks INDRA to collect social posts "tagged with #IMD and other relevant
weather hashtags". X and Reddit need paid or OAuth access and are never
scraped; Mastodon's public hashtag timelines answer without an account:

    GET https://{instance}/api/v1/timelines/tag/{tag}?limit=40&since_id={cursor}

Every MASTODON_POLL_INTERVAL_SECONDS, for each (instance, tag) pair in
MASTODON_INSTANCES × SOCIAL_HASHTAGS, the new posts are stored through
`ingest.store_report()` like every other report, so they reach the pipeline
through the outbox and Kafka like everything else:

    source_type     SOCIAL_MEDIA            platform   mastodon
    raw_text        the post as plain text (spoiler text first), links once
    observed_at     when it was posted
    place           from its words and hashtags (geocoding.place_from_text):
                    a district, a state, or none — never guessed
    reporter_hash   the author's keyed pseudonym, so Phase 5 can keep a
                    reputation per account without storing the account
    source_meta     url, author_hash, account age and counts, bot flag,
                    hashtags, instance, media, links, language

**Privacy.** The author's handle is stored nowhere, and neither is anything
that contains it. A post's canonical URI does
(`https://mastodon.social/users/<handle>/statuses/<id>`), so `external_id` is
its SHA-256, which is just as unique, and `url` is the instance's
`/web/statuses/<id>` link, which opens the same post without naming anyone.

**Being a good client.** One second between requests to an instance. When
`X-RateLimit-Remaining` drops below MASTODON_MIN_RATELIMIT_REMAINING the rest
of that instance's tags wait for the next tick; a 429 is waited out for its
`Retry-After`. One unreachable instance never stops the others.

**Idempotent.** Each (instance, tag) keeps its newest seen id in the feed's
heartbeat cursor, so a restart resumes where it stopped; and a post seen twice
(under two tags, or re-fetched) hits the unique (platform, external_id) and is
stored once. A boost is a repost, not a new post: the original is stored,
never the boost.
"""

import asyncio
import email.utils
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.services.geocoding import place_from_text
from app.services.ingest import StoreError, reporter_hash_for, store_report
from app.services.text_processing import URL_RE, canonical_url, html_to_text

logger = logging.getLogger("indra.workers.mastodon_poller")

FEED = "mastodon"
PLATFORM = "mastodon"
USER_AGENT = "INDRA-SIH2026/1.0 (Team Sixth Sense; disaster situational awareness)"
PAGE_LIMIT = 40

# instance → time.monotonic() before which it is not asked anything (a 429).
_backoff_until: Dict[str, float] = {}


def _reset_for_tests() -> None:
    _backoff_until.clear()


def cursor_key(instance: str, tag: str) -> str:
    return f"{instance}#{tag.lower()}"


# ── Mapping one status ─────────────────────────────────────────────────────────

def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def external_id_for(status: Dict[str, Any]) -> Optional[str]:
    """SHA-256 of the post's canonical URI: unique across instances, no handle in it."""
    uri = (status.get("uri") or "").strip()
    if not uri:
        return None
    return "sha256:" + hashlib.sha256(uri.encode("utf-8")).hexdigest()


def post_text(status: Dict[str, Any]) -> str:
    """Spoiler (content warning) first, then the body, as plain text."""
    spoiler = " ".join((status.get("spoiler_text") or "").split())
    body = html_to_text(status.get("content") or "")
    return "\n".join(part for part in (spoiler, body) if part)


def status_to_report(status: Dict[str, Any], instance: str, tag: str) -> Optional[Dict[str, Any]]:
    """
    The store_report() arguments for one status, or None to skip it.

    Pure: no I/O, no clock. A boost maps to the post it boosts. A post with no
    text at all (a bare image) is skipped: there is nothing for the pipeline to
    read, and Phase 5 collects media properly.
    """
    original = status.get("reblog") or status
    external_id = external_id_for(original)
    text = post_text(original)
    if not external_id or not text:
        return None

    account = original.get("account") or {}
    acct = (account.get("acct") or "").strip()
    # A local account's acct has no domain; the full handle identifies it
    # across instances. Only its keyed hash is kept.
    full_acct = acct if "@" in acct else f"{acct}@{instance}"
    author_hash = reporter_hash_for(f"mastodon:{full_acct.lower()}") if acct else None

    hashtags = [t.get("name") for t in original.get("tags") or [] if t.get("name")]
    place = place_from_text(text, hashtags)

    media = [
        {
            "type": m.get("type"),
            "url": m.get("remote_url") or m.get("url"),
            "preview_url": m.get("preview_url"),
            "description": m.get("description"),
        }
        for m in original.get("media_attachments") or []
    ]
    status_id = original.get("id")

    source_meta = {
        "url": f"https://{instance}/web/statuses/{status_id}" if status_id else None,
        "author_hash": author_hash,
        "account_created_at": account.get("created_at"),
        "followers_count": account.get("followers_count"),
        "statuses_count": account.get("statuses_count"),
        "bot": bool(account.get("bot")),
        "hashtags": hashtags,
        "instance": instance,
        "matched_tag": tag,
        "media": media,
        # Canonical, so a later post sharing the same article under another
        # tracking tag is recognised as a re-share (T7).
        "links": sorted({c for c in (canonical_url(u) for u in URL_RE.findall(text)) if c}),
        "language": original.get("language"),
        "place_basis": place["matched"],
    }
    if status.get("reblog"):
        source_meta["collected_via_boost"] = True

    return {
        "source_type": "SOCIAL_MEDIA",
        "raw_text": text,
        "latitude": place["lat"],
        "longitude": place["lng"],
        "district": place["district"],
        "state": place["state"],
        "observed_at": _parse_time(original.get("created_at")),
        "reporter_hash": author_hash,
        "platform": PLATFORM,
        "external_id": external_id,
        "source_meta": source_meta,
        "issue_docket": False,
        "place_precision": place["precision"],
    }


# ── Fetching ───────────────────────────────────────────────────────────────────

@dataclass
class Page:
    statuses: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    retry_after_s: Optional[float] = None    # set on a 429
    remaining: Optional[int] = None          # X-RateLimit-Remaining
    raw: bytes = b""
    unreachable: bool = False                # the request itself failed (DNS, connection)


def _retry_after_seconds(value: Optional[str], default: float = 60.0) -> float:
    """Retry-After as seconds: either a number or an HTTP date."""
    if not value:
        return default
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return default


async def fetch_tag(
    client: httpx.AsyncClient, instance: str, tag: str, since_id: Optional[str]
) -> Page:
    """One page of a tag timeline, newest first. Never raises."""
    settings = get_settings()
    params: Dict[str, Any] = {"limit": PAGE_LIMIT}
    if since_id:
        params["since_id"] = since_id
    url = f"https://{instance}/api/v1/timelines/tag/{tag}"
    try:
        resp = await client.get(
            url, params=params, headers={"User-Agent": USER_AGENT},
            timeout=settings.MASTODON_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return Page(error=f"{instance} #{tag}: {type(e).__name__}: {e}", unreachable=True)

    remaining = resp.headers.get("X-RateLimit-Remaining")
    remaining_n = int(remaining) if remaining and remaining.isdigit() else None

    if resp.status_code == 429:
        return Page(
            error=f"{instance} #{tag}: HTTP 429",
            retry_after_s=_retry_after_seconds(resp.headers.get("Retry-After")),
            remaining=remaining_n,
        )
    if resp.status_code != 200:
        return Page(error=f"{instance} #{tag}: HTTP {resp.status_code}", remaining=remaining_n)
    try:
        body = resp.json()
        if not isinstance(body, list):
            raise ValueError("not a list of statuses")
    except ValueError as e:
        return Page(error=f"{instance} #{tag}: malformed body: {e}", remaining=remaining_n)
    return Page(statuses=body, remaining=remaining_n, raw=resp.content)


def _newest_id(statuses: List[Dict[str, Any]], current: Optional[str]) -> Optional[str]:
    """The largest status id seen, compared as numbers (Mastodon ids are snowflakes)."""
    best = int(current) if current and str(current).isdigit() else None
    for s in statuses:
        sid = str(s.get("id") or "")
        if sid.isdigit() and (best is None or int(sid) > best):
            best = int(sid)
    return str(best) if best is not None else current


# ── One tick ───────────────────────────────────────────────────────────────────

@dataclass
class TickResult:
    written: int = 0
    seen: int = 0
    requests_ok: int = 0
    errors: List[str] = field(default_factory=list)
    cursors: Dict[str, str] = field(default_factory=dict)
    pages: List[Tuple[str, str, bytes]] = field(default_factory=list)  # (instance, tag, body)


async def poll_once(
    db,
    client: Optional[httpx.AsyncClient] = None,
    cursors: Optional[Dict[str, str]] = None,
    sleep=asyncio.sleep,
) -> TickResult:
    """
    One pass over every (instance, tag). `cursors` maps cursor_key() to the
    newest id already seen; the result carries the updated map.
    """
    settings = get_settings()
    result = TickResult(cursors=dict(cursors or {}))
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.MASTODON_TIMEOUT_SECONDS)

    try:
        for instance in settings.mastodon_instances:
            if _backoff_until.get(instance, 0.0) > time.monotonic():
                result.errors.append(f"{instance}: waiting out a 429")
                continue

            first = True
            for tag in settings.social_hashtags:
                if not first and settings.MASTODON_REQUEST_DELAY_SECONDS:
                    await sleep(settings.MASTODON_REQUEST_DELAY_SECONDS)
                first = False

                key = cursor_key(instance, tag)
                page = await fetch_tag(client, instance, tag, result.cursors.get(key))
                if page.error:
                    result.errors.append(page.error)
                    logger.warning(f"Mastodon: {page.error}")
                    if page.retry_after_s is not None:
                        _backoff_until[instance] = time.monotonic() + page.retry_after_s
                        break  # this instance waits; the others carry on
                    if page.unreachable:
                        break  # DNS or connection failed: no use asking again this tick
                    continue

                result.requests_ok += 1
                result.seen += len(page.statuses)
                if page.raw:
                    result.pages.append((instance, tag, page.raw))

                for status in page.statuses:
                    mapped = status_to_report(status, instance, tag)
                    if mapped is None:
                        continue
                    try:
                        stored = await store_report(db, **mapped)
                    except StoreError as e:
                        result.errors.append(f"{instance} #{tag}: a post was not stored: {e}")
                        continue
                    if stored.created:
                        result.written += 1

                newest = _newest_id(page.statuses, result.cursors.get(key))
                if newest:
                    result.cursors[key] = newest

                if (
                    page.remaining is not None
                    and page.remaining < settings.MASTODON_MIN_RATELIMIT_REMAINING
                ):
                    result.errors.append(
                        f"{instance}: {page.remaining} requests left in the rate-limit "
                        "window; the rest of its tags wait for the next tick"
                    )
                    break
    finally:
        if own_client:
            await client.aclose()
    return result


async def run_tick(session_factory=None) -> TickResult:
    """One scheduled tick: poll, then record the heartbeat and the cursors."""
    from app.services.feed_status import get_cursor, record_tick

    if session_factory is None:
        from app.core.database import async_session as session_factory

    cursors = (await get_cursor(FEED)).get("since_id") or {}
    try:
        async with session_factory() as db:
            result = await poll_once(db, cursors=cursors)
    except Exception as e:
        await record_tick(FEED, ok=False, error=f"{type(e).__name__}: {e}")
        raise

    if result.written:
        logger.info(
            f"Mastodon poll stored {result.written} new posts "
            f"({result.seen} seen, {result.requests_ok} timelines read)"
        )
    await record_tick(
        FEED,
        # A tick where at least one timeline answered is alive; the errors are
        # still recorded. Nothing answering at all is a failed tick.
        ok=result.requests_ok > 0,
        items=result.written,
        error="; ".join(result.errors)[:500] if result.errors else None,
        cursor={"since_id": result.cursors},
    )
    return result


async def start_mastodon_poller() -> None:
    """The lifespan task. Polls at once, then every interval."""
    settings = get_settings()
    if not settings.MASTODON_POLLER_ENABLED:
        logger.info("Mastodon poller disabled (MASTODON_POLLER_ENABLED=false)")
        return

    from app.core.database import async_session

    logger.info(
        f"✓ Mastodon poller started — {len(settings.social_hashtags)} hashtags on "
        f"{', '.join(settings.mastodon_instances)} every {settings.MASTODON_POLL_INTERVAL_SECONDS}s"
    )
    while True:
        try:
            await run_tick(async_session)
        except asyncio.CancelledError:
            logger.info("Mastodon poller shutting down...")
            raise
        except Exception as e:
            logger.warning(f"Mastodon poll failed (non-fatal): {type(e).__name__}: {e}")

        try:
            await asyncio.sleep(settings.MASTODON_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Mastodon poller shutting down...")
            raise
