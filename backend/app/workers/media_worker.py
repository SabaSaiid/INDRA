"""
INDRA Platform — Media worker (layers 3, 6 and 7; Phase 5 T2, T3, T4, T5)

Everything that happens to a photo or video after its bytes have arrived, off
the request path, so a citizen's report is never held up by ffmpeg:

1. **Read it.** The completed upload is streamed from `incoming/{upload_id}`
   to a temporary file. SHA-256, then EXIF and the perceptual hash for a photo,
   or ffprobe and four frame hashes for a video (services/media_extract.py). A
   video longer than 60 seconds is dropped here, with its reason; the report
   is kept.
2. **File it.** The original goes to the private
   `originals/{yyyy}/{mm}/{dd}/{report_id}/{sha256}.{ext}`; the EXIF-free copy
   and the 320 px thumbnail (a video's poster and stripped copy) go to
   `derivatives/{report_id}/{media_id}/…` (services/media_derivatives.py).
3. **Judge it.** The recycled-media rules (services/media_rules.py) compare it
   with every photo and video INDRA has stored, citizen and social. Each new
   flag is set on the media and on its report, and lowers the report's
   credibility once (report_flags.FLAGS).
4. **Re-score.** If the report is already in an event, the event is re-scored
   (pipeline.rescore_event) and a change is broadcast as `VERIFIED_EVENT`.
5. **Tell the dashboard:** `REPORT_MEDIA_READY`, with ids and flags and never
   a URL, because the socket is open.

**Mastodon attachments go through the same checks** (T4): images up to 10 MB,
and for a video its preview image plus the video itself if it is 50 MB or
less, downloaded as a private copy used only for hashing. INDRA never re-hosts
anyone's post: every link it shows is the author's own URL. That is how "the
old flood video goes viral again" is caught.

**Nothing is lost if the worker is down.** Completed uploads wait in
`processing`; the sweep every MEDIA_WORKER_SWEEP_SECONDS picks up whatever the
in-process queue missed, including after a restart. A file that fails three
times for a reason other than being unreadable is marked `rejected` with the
error, so one bad file cannot hold the queue.
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

from app.core.config import get_settings
from app.services import cache, objectstore
from app.services.media_derivatives import image_derivatives, strip_video, video_poster
from app.services.media_extract import (
    Extracted,
    UnreadableMedia,
    extract_image,
    extract_video,
    ffmpeg_available,
    sha256_file,
)
from app.services.media_rules import RECYCLED_MAX_HAMMING, RECYCLED_MIN_AGE, media_flags
from app.services.media_types import (
    MAX_FILES_PER_REPORT,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_SECONDS,
    SNIFF_BYTES,
    VIDEO,
    sniff,
)
from app.services.report_flags import CREDIBILITY_FLOOR, FLAGS, credibility_multiplier

logger = logging.getLogger("indra.workers.media_worker")

MAX_ATTEMPTS = 3
FAIL_KEY_PREFIX = "media:fail:"
FAIL_TTL_SECONDS = 24 * 60 * 60
SWEEP_BATCH = 20
# Social posts younger than this are picked up by the sweep; older ones are the
# backfill's (scripts/backfill_social_media.py).
SOCIAL_SWEEP_HOURS = 48

_queue: Optional[asyncio.Queue] = None
_inflight: set = set()


# ── The queue ──────────────────────────────────────────────────────────────────

def enqueue(media_id: str) -> None:
    """Hand a completed citizen upload to the worker. A full or absent queue is fine: the sweep finds it."""
    _put(("citizen", str(media_id)))


def enqueue_social(report_id: Any) -> None:
    """Hash a stored post's attachments (T4)."""
    if get_settings().SOCIAL_MEDIA_HASHING_ENABLED:
        _put(("social", str(report_id)))


def _put(item: Tuple[str, str]) -> None:
    if _queue is None:
        return
    try:
        _queue.put_nowait(item)
    except asyncio.QueueFull:
        logger.info(f"Media queue full; {item[0]} {item[1]} waits for the sweep")


def _bucket() -> str:
    return get_settings().S3_MEDIA_BUCKET


# ── Broadcasts ─────────────────────────────────────────────────────────────────

async def _broadcast(message: Dict[str, Any]) -> None:
    """Send one WebSocket message to every dashboard. Never raises."""
    try:
        from app.main import ws_manager

        await ws_manager.broadcast(message)
    except Exception as e:
        logger.warning(f"{message.get('type')} broadcast failed: {e}")


def media_ready_message(report_id: Any, event_id: Any, media: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    REPORT_MEDIA_READY: ids, kinds, statuses and flags only. No URL and no
    docket: the socket is open to anyone, the URLs come from the signed-in
    call (api/media.py), and a docket is the citizen's own credential.
    """
    return {
        "type": "REPORT_MEDIA_READY",
        "report_id": str(report_id),
        "event_id": str(event_id) if event_id else None,
        "media": [
            {
                "id": str(m["id"]),
                "kind": m["kind"],
                "status": m["status"],
                "flags": list(m.get("flags") or []),
                **({"duration_s": m["duration_s"]} if m.get("duration_s") is not None else {}),
            }
            for m in media
        ],
    }


# ── Finding earlier media (T3's inputs) ────────────────────────────────────────

# Hamming distance of two bigint hashes in SQL: XOR, as 64 bits, count the 1s.
_HAMMING_SQL = "length(replace(CAST(CAST(({a}) # ({b}) AS bit(64)) AS text), '0', ''))"


async def same_file_matches(db, *, media_id: Any, report_id: Any, sha256: str, before) -> List[Dict[str, Any]]:
    """Earlier media with the same SHA-256, with its report's reporter and time."""
    rows = (await db.execute(
        text("""
            SELECT m.report_id, r.reporter_hash, r.created_at
            FROM report_media m
            JOIN raw_reports r ON r.id = m.report_id
            WHERE m.sha256 = :sha
              AND m.id <> CAST(:id AS uuid)
              AND m.report_id <> CAST(:rid AS uuid)
              AND m.status = 'ready'
              AND r.created_at < CAST(:before AS timestamptz)
            ORDER BY r.created_at
            LIMIT 20
        """),
        {"sha": sha256, "id": str(media_id), "rid": str(report_id), "before": before},
    )).fetchall()
    return [{"report_id": r[0], "reporter_hash": r[1], "created_at": r[2]} for r in rows]


async def near_matches(db, *, media_id: Any, hashes: Sequence[int], observed) -> List[Dict[str, Any]]:
    """
    Earlier media whose pHash (or any frame's) is within the recycled distance
    of any of `hashes`, first seen more than 48 h before `observed`, oldest
    first. "First seen" is when the post was published for a social
    attachment, and when INDRA stored it for a citizen's.
    """
    if not hashes or observed is None:
        return []
    first_seen = (
        "CASE WHEN m.origin = 'social' THEN COALESCE(r.observed_at, m.created_at) ELSE m.created_at END"
    )
    distance = _HAMMING_SQL.format(a="t.h", b="mine.h")
    rows = (await db.execute(
        text(f"""
            WITH mine AS (SELECT unnest(CAST(:hashes AS bigint[])) AS h)
            SELECT m.id, m.phash, m.frame_phashes, m.origin, r.platform, {first_seen} AS first_seen,
                   min({distance}) AS distance
            FROM report_media m
            JOIN raw_reports r ON r.id = m.report_id
            CROSS JOIN LATERAL unnest(array_prepend(m.phash, COALESCE(m.frame_phashes, '{{}}'::bigint[]))) AS t(h)
            CROSS JOIN mine
            WHERE m.id <> CAST(:id AS uuid)
              AND m.status = 'ready'
              AND m.phash IS NOT NULL
              AND {first_seen} < CAST(:cutoff AS timestamptz)
            GROUP BY m.id, m.phash, m.frame_phashes, m.origin, r.platform, first_seen
            HAVING min({distance}) <= :max_distance
            ORDER BY first_seen
            LIMIT 10
        """),
        {
            "hashes": [int(h) for h in hashes],
            "id": str(media_id),
            "cutoff": observed - RECYCLED_MIN_AGE,
            "max_distance": RECYCLED_MAX_HAMMING,
        },
    )).fetchall()
    return [
        {"phash": r[1], "frame_phashes": list(r[2] or []), "origin": r[3], "platform": r[4],
         "first_seen": r[5], "distance": r[6]}
        for r in rows
    ]


# ── Setting flags on the report ────────────────────────────────────────────────

async def apply_report_flags(db, report_id: Any, flags: Sequence[str], basis: Dict[str, str]) -> List[str]:
    """
    Add media flags to a report, in the caller's transaction. Each flag the
    report did not already carry lowers its credibility once, by its published
    multiplier, floored at 0.05; its reason joins `analysis.flag_basis`.
    Returns the flags newly added.
    """
    row = (await db.execute(
        text("""
            SELECT COALESCE(flags, '{}'::text[]), credibility_score
            FROM raw_reports WHERE id = CAST(:id AS uuid) FOR UPDATE
        """),
        {"id": str(report_id)},
    )).fetchone()
    if row is None:
        return []
    current = list(row[0] or [])
    fresh = [f for f in flags if f not in current]
    if not fresh:
        return []
    merged = [f for f in FLAGS if f in set(current) | set(fresh)]
    factor = credibility_multiplier(fresh)
    credibility = float(row[1] or 0.0)
    if factor != 1.0:
        credibility = round(max(CREDIBILITY_FLOOR, credibility * factor), 4)
    await db.execute(
        text("""
            UPDATE raw_reports SET
                flags = CAST(:flags AS text[]),
                credibility_score = :cred,
                analysis = CASE WHEN analysis IS NULL THEN NULL ELSE
                    jsonb_set(
                        jsonb_set(analysis, '{flags}', CAST(:flags_json AS jsonb)),
                        '{flag_basis}',
                        COALESCE(analysis->'flag_basis', '{}'::jsonb) || CAST(:basis AS jsonb)
                    )
                END
            WHERE id = CAST(:id AS uuid)
        """),
        {
            "id": str(report_id),
            "flags": merged,
            "flags_json": json.dumps(merged),
            "cred": credibility,
            "basis": json.dumps({f: basis[f] for f in fresh if f in basis}),
        },
    )
    # The reporter's record counts reports a flag marked down (T6), once each.
    if factor != 1.0 and credibility_multiplier(current) == 1.0:
        from app.services import reputation

        await reputation.note_flagged(db, report_id)
    return fresh


# ── One citizen upload ─────────────────────────────────────────────────────────

_CITIZEN_SQL = text("""
    SELECT m.id, m.report_id, m.kind, m.status, m.declared_mime, m.mime, m.incoming_key,
           r.reporter_hash, r.latitude, r.longitude, COALESCE(r.place_precision, 'gps'),
           r.observed_at, r.created_at, r.event_id
    FROM report_media m
    JOIN raw_reports r ON r.id = m.report_id
    WHERE m.id = CAST(:id AS uuid)
""")


def _original_key(report_id: Any, created_at: datetime, sha: str, ext: str, prefix: str = "originals") -> str:
    day = created_at.astimezone(timezone.utc)
    return f"{prefix}/{day:%Y/%m/%d}/{report_id}/{sha}.{ext}"


async def _fail(media_id: str, error: str) -> None:
    """Count one failure; the third marks the media rejected. Never raises."""
    attempts = await cache.incr(FAIL_KEY_PREFIX + media_id, FAIL_TTL_SECONDS)
    if attempts < MAX_ATTEMPTS:
        logger.warning(f"Media {media_id} failed (attempt {attempts} of {MAX_ATTEMPTS}); retried by the sweep: {error}")
        return
    await _set_status(media_id, "rejected", f"processing failed {attempts} times: {error}"[:500])


async def _set_status(media_id: str, status: str, reason: Optional[str], flags: Sequence[str] = ()) -> None:
    from app.core.database import async_session

    try:
        async with async_session() as db:
            await db.execute(
                text("""
                    UPDATE report_media SET status = :s, reason = :r, flags = CAST(:f AS text[]),
                                            processed_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                      -- Only a file still in flight: a withdrawn one stays withdrawn.
                      AND status IN ('uploading', 'processing')
                """),
                {"s": status, "r": reason, "f": list(flags), "id": media_id},
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Media {media_id} could not be marked {status}: {e}")


async def _read_file(path: str) -> bytes:
    def _read():
        with open(path, "rb") as f:
            return f.read()

    return await asyncio.to_thread(_read)


async def process_citizen_media(media_id: str) -> Optional[Dict[str, Any]]:
    """
    Steps 1–5 of the module docstring for one completed upload. Returns the
    media as broadcast, or None when it was not ready to process. Never raises.
    """
    from app.core.database import async_session

    try:
        async with async_session() as db:
            row = (await db.execute(_CITIZEN_SQL, {"id": media_id})).fetchone()
    except Exception as e:
        logger.warning(f"Media {media_id} not loaded: {e}")
        return None
    if row is None or row[3] != "processing":
        return None
    (_, report_id, kind, _status, declared_mime, sniffed_mime, incoming_key, reporter_hash,
     lat, lng, precision, observed_at, created_at, event_id) = row
    report = {
        "id": report_id, "reporter_hash": reporter_hash, "latitude": lat, "longitude": lng,
        "place_precision": precision, "observed_at": observed_at or created_at,
        "created_at": created_at,
    }

    with tempfile.TemporaryDirectory(prefix="indra-media-") as tmp:
        src = os.path.join(tmp, "original")
        try:
            await objectstore.download_to_file(_bucket(), incoming_key, src)
        except objectstore.ObjectStoreUnavailable as e:
            logger.warning(f"Media {media_id}: store unavailable, left for the sweep: {e}")
            return None
        except Exception as e:
            await _fail(media_id, f"download: {type(e).__name__}: {e}")
            return None

        try:
            sha, size = await asyncio.to_thread(sha256_file, src)
            with open(src, "rb") as f:
                sniffed = sniff(f.read(SNIFF_BYTES))
            if sniffed is None or sniffed.kind != kind:
                raise UnreadableMedia("the completed file is not the photo or video its first part was")
            mime = sniffed_mime or sniffed.mime
            derivatives: Dict[str, Tuple[bytes, str]] = {}
            stripped_path: Optional[str] = None
            if kind == VIDEO:
                if not ffmpeg_available():
                    raise UnreadableMedia("ffmpeg is not installed on this server (Phase 5 T0)")
                info: Extracted = await asyncio.to_thread(extract_video, src, mime)
                if info.duration_s is not None and info.duration_s > MAX_VIDEO_SECONDS:
                    await _drop(media_id, incoming_key,
                                f"video is {info.duration_s:.0f} s long; at most {MAX_VIDEO_SECONDS:.0f} s is accepted")
                    return None
                stripped_path = os.path.join(tmp, f"stripped.{sniffed.ext}")
                await asyncio.to_thread(strip_video, src, stripped_path)
                poster, thumb = await asyncio.to_thread(video_poster, src, info.duration_s)
                derivatives["poster"] = (poster, "image/jpeg")
                derivatives["thumb"] = (thumb, "image/jpeg")
            else:
                data = await _read_file(src)
                info = await asyncio.to_thread(extract_image, data, mime)
                full, thumb = await asyncio.to_thread(image_derivatives, data)
                derivatives["full"] = (full, "image/jpeg")
                derivatives["thumb"] = (thumb, "image/jpeg")
                del data
        except UnreadableMedia as e:
            await _drop(media_id, incoming_key, f"unreadable: {e}", flags=["unreadable"])
            return None
        except Exception as e:
            await _fail(media_id, f"extract: {type(e).__name__}: {e}")
            return None

        # Step 2: file the original and the safe copies.
        original_key = _original_key(report_id, created_at, sha, sniffed.ext)
        base = f"derivatives/{report_id}/{media_id}"
        keys = {"full": None, "poster": None, "thumb": None, "video": None}
        try:
            await objectstore.upload_file(src, _bucket(), original_key, mime)
            for name, (body, content_type) in derivatives.items():
                keys[name] = f"{base}/{name}.jpg"
                await objectstore.put(_bucket(), keys[name], body, content_type)
            if stripped_path:
                keys["video"] = f"{base}/video.{sniffed.ext}"
                await objectstore.upload_file(stripped_path, _bucket(), keys["video"], mime)
        except objectstore.ObjectStoreUnavailable as e:
            logger.warning(f"Media {media_id}: store unavailable while filing, left for the sweep: {e}")
            return None

    # Step 3: judge it, and write everything in one transaction.
    try:
        async with async_session() as db:
            hashes = [h for h in [info.phash, *info.frame_phashes] if h is not None]
            same = await same_file_matches(db, media_id=media_id, report_id=report_id, sha256=sha,
                                           before=created_at)
            near = await near_matches(db, media_id=media_id, hashes=hashes, observed=report["observed_at"])
            flags, basis = media_flags(info.as_dict() | {"exif_taken_at": info.exif_taken_at},
                                       report, same_file=same, near=near)
            updated = await db.execute(
                text("""
                    UPDATE report_media SET
                        status = 'ready', reason = NULL, mime = :mime, bytes = :bytes, sha256 = :sha,
                        phash = :phash, frame_phashes = CAST(:frames AS bigint[]),
                        width = :w, height = :h, duration_s = :dur,
                        exif_taken_at = :taken, exif_offset = :offset, exif_lat = :elat, exif_lng = :elng,
                        exif_make = :make, exif_model = :model, exif_software = :software,
                        object_key = :original, derivative_key = :derivative, poster_key = :poster,
                        thumb_key = :thumb, flags = CAST(:flags AS text[]),
                        flag_basis = CAST(:basis AS jsonb), processed_at = NOW()
                    WHERE id = CAST(:id AS uuid) AND status = 'processing'
                """),
                {
                    "id": media_id, "mime": mime, "bytes": size, "sha": sha,
                    "phash": info.phash, "frames": info.frame_phashes or None,
                    "w": info.width, "h": info.height, "dur": info.duration_s,
                    "taken": info.exif_taken_at, "offset": info.exif_offset,
                    "elat": info.exif_lat, "elng": info.exif_lng, "make": info.exif_make,
                    "model": info.exif_model, "software": info.exif_software,
                    "original": original_key,
                    "derivative": keys["video"] or keys["full"],
                    "poster": keys["poster"], "thumb": keys["thumb"],
                    "flags": flags,
                    "basis": json.dumps({**basis, **({"offset_assumed": "the camera wrote no time zone; "
                                                      "read as IST"} if info.exif_offset_assumed else {})}),
                },
            )
            if (updated.rowcount or 0) == 0:
                # No longer processing: the report was withdrawn (or the row
                # rejected) while this file was being read. Nothing is flagged,
                # and the copies just filed are removed again.
                await db.rollback()
                filed = [k for k in (original_key, *keys.values()) if k]
                for key in filed + [incoming_key]:
                    try:
                        await objectstore.delete(_bucket(), key)
                    except Exception:
                        pass
                logger.info(f"Media {media_id} no longer processing; its copies removed")
                return None
            added = await apply_report_flags(db, report_id, flags, basis)
            await db.commit()
    except Exception as e:
        await _fail(media_id, f"record: {type(e).__name__}: {e}")
        return None

    # The file is filed under its hash; the incoming copy is no longer needed.
    try:
        await objectstore.delete(_bucket(), incoming_key)
    except Exception as e:
        logger.info(f"Media {media_id}: incoming copy not deleted (retention removes it): {e}")
    await cache.delete(FAIL_KEY_PREFIX + media_id)

    media = {"id": media_id, "kind": kind, "status": "ready", "flags": flags,
             "duration_s": info.duration_s}
    logger.info(
        f"Media {media_id} ready: {kind}, {size} bytes, flags {flags or 'none'}"
        + (f"; report now also {added}" if added else "")
    )
    await _after_ready(report_id, event_id, [media], trigger=f"media:{media_id}")
    return media


async def _drop(media_id: str, incoming_key: Optional[str], reason: str, flags: Sequence[str] = ()) -> None:
    """Refuse one file for good (too long, unreadable): the report keeps everything else."""
    await _set_status(media_id, "rejected", reason, flags)
    if incoming_key:
        try:
            await objectstore.delete(_bucket(), incoming_key)
        except Exception:
            pass
    logger.info(f"Media {media_id} rejected: {reason}")


async def _after_ready(report_id: Any, event_id: Any, media: List[Dict[str, Any]], *, trigger: str) -> None:
    """Re-score the report's event if it has one, then tell the dashboard. Never raises."""
    if event_id:
        try:
            from app.core.database import async_session
            from app.services import pipeline
            from app.services.late_corroboration import _broadcast as broadcast_event

            async with async_session() as db:
                event = await pipeline.rescore_event(
                    db, event_id, trigger=trigger, trigger_detail={"report_id": str(report_id)}
                )
            if event is not None:
                await broadcast_event(event)
        except Exception as e:
            logger.warning(f"Re-score after {trigger} failed (non-fatal): {e}")
    await _broadcast(media_ready_message(report_id, event_id, media))


# ── One social post (T4) ───────────────────────────────────────────────────────

_SOCIAL_SQL = text("""
    SELECT id, source_meta, reporter_hash, latitude, longitude, COALESCE(place_precision, 'none'),
           observed_at, created_at, event_id, platform
    FROM raw_reports
    WHERE id = CAST(:id AS uuid) AND CAST(source_type AS text) = 'SOCIAL_MEDIA'
""")


def social_attachments(source_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    What to fetch for one post, in order, at most MAX_FILES_PER_REPORT:
    [{"source_url", "kind", "limit", "role"}]. A video contributes its preview
    image and, if small enough, the video itself; audio and unknown types
    contribute nothing.
    """
    out: List[Dict[str, Any]] = []
    for a in (source_meta or {}).get("media") or []:
        if not isinstance(a, dict):
            continue
        kind, url, preview = a.get("type"), a.get("url"), a.get("preview_url")
        if kind == "image" and url:
            out.append({"source_url": url, "kind": "image", "limit": MAX_IMAGE_BYTES, "role": "image"})
        elif kind in ("video", "gifv"):
            if preview:
                out.append({"source_url": preview, "kind": "image", "limit": MAX_IMAGE_BYTES, "role": "preview"})
            if url:
                out.append({"source_url": url, "kind": "video", "limit": MAX_VIDEO_BYTES, "role": "video"})
    return out[: MAX_FILES_PER_REPORT * 2]


async def download_capped(client, url: str, limit: int, path: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Stream a URL to `path`, stopping at `limit` bytes. (bytes written, None) on
    success, (None, reason) otherwise — a 404, a timeout, a file too large.
    Never raises.
    """
    try:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                return None, f"larger than {limit // 1_000_000} MB ({int(declared)} bytes); not downloaded"
            size = 0
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        return None, f"larger than {limit // 1_000_000} MB; download stopped"
                    f.write(chunk)
            return size, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:300]


async def process_social_post(report_id: str, client=None) -> Dict[str, int]:
    """
    Download and hash a post's attachments (T4). Idempotent: an attachment that
    already has a row, whatever its outcome, is not fetched again. Returns
    {"downloaded", "skipped", "failed"}. Never raises.
    """
    import httpx

    from app.core.database import async_session

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    try:
        async with async_session() as db:
            row = (await db.execute(_SOCIAL_SQL, {"id": report_id})).fetchone()
            if row is None:
                return counts
            done = {r[0] for r in (await db.execute(
                text("SELECT source_url FROM report_media WHERE report_id = CAST(:id AS uuid) "
                     "AND source_url IS NOT NULL"),
                {"id": report_id},
            )).fetchall()}
    except Exception as e:
        logger.warning(f"Social post {report_id} not loaded: {e}")
        return counts

    (_, source_meta, reporter_hash, lat, lng, precision, observed_at, created_at, event_id,
     platform) = row
    report = {
        "id": row[0], "reporter_hash": reporter_hash, "latitude": lat, "longitude": lng,
        "place_precision": precision, "observed_at": observed_at or created_at, "created_at": created_at,
    }
    todo = [a for a in social_attachments(source_meta or {}) if a["source_url"] not in done]
    if not todo:
        return counts

    settings = get_settings()
    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=settings.MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
            headers={"User-Agent": "INDRA-SIH2026/1.0 (Team Sixth Sense; recycled-media checks)"},
        )
    ready: List[Dict[str, Any]] = []
    try:
        for attachment in todo:
            outcome = await _one_social(client, report, attachment, platform)
            counts[outcome["result"]] += 1
            if outcome.get("media"):
                ready.append(outcome["media"])
    finally:
        if own:
            await client.aclose()

    if ready:
        await _after_ready(report["id"], event_id, ready, trigger=f"media:social:{report_id}")
    return counts


async def _one_social(client, report: Dict[str, Any], attachment: Dict[str, Any], platform) -> Dict[str, Any]:
    from uuid import uuid4

    from app.core.database import async_session

    media_id = str(uuid4())
    kind, url = attachment["kind"], attachment["source_url"]
    status, reason, flags, basis = "rejected", None, [], {}
    info: Optional[Extracted] = None
    sha = size = key = None
    mime = None

    with tempfile.TemporaryDirectory(prefix="indra-social-") as tmp:
        path = os.path.join(tmp, "attachment")
        size, reason = await download_capped(client, url, attachment["limit"], path)
        if size is not None:
            try:
                sha, size = await asyncio.to_thread(sha256_file, path)
                with open(path, "rb") as f:
                    sniffed = sniff(f.read(SNIFF_BYTES))
                if sniffed is None or sniffed.kind != kind:
                    raise UnreadableMedia("not a photo or video INDRA reads")
                mime = sniffed.mime
                if kind == VIDEO:
                    if not ffmpeg_available():
                        raise UnreadableMedia("ffmpeg is not installed on this server")
                    info = await asyncio.to_thread(extract_video, path, mime)
                else:
                    info = await asyncio.to_thread(extract_image, await _read_file(path), mime)
                key = _original_key(report["id"], report["created_at"], sha, sniffed.ext, prefix="social")
                await objectstore.upload_file(path, _bucket(), key, mime)
                status = "ready"
            except UnreadableMedia as e:
                reason = f"unreadable: {e}"
            except objectstore.ObjectStoreUnavailable as e:
                # Not recorded, so the next run fetches it again.
                logger.warning(f"Social media {url}: store unavailable: {e}")
                return {"result": "failed"}
            except Exception as e:
                reason = f"{type(e).__name__}: {e}"[:300]

    try:
        async with async_session() as db:
            if status == "ready" and info is not None:
                hashes = [h for h in [info.phash, *info.frame_phashes] if h is not None]
                same = await same_file_matches(db, media_id=media_id, report_id=report["id"], sha256=sha,
                                               before=report["created_at"])
                near = await near_matches(db, media_id=media_id, hashes=hashes, observed=report["observed_at"])
                flags, basis = media_flags(info.as_dict() | {"exif_taken_at": info.exif_taken_at},
                                           report, same_file=same, near=near)
                # Platforms strip EXIF from every upload, so its absence on a
                # social attachment says nothing at all; the flag is left off.
                flags = [f for f in flags if f != "no_metadata"]
                basis.pop("no_metadata", None)
            inserted = (await db.execute(
                text("""
                    INSERT INTO report_media
                        (id, report_id, origin, kind, status, reason, source_url, object_key, mime,
                         bytes, sha256, phash, frame_phashes, width, height, duration_s,
                         exif_taken_at, exif_offset, exif_lat, exif_lng, exif_make, exif_model,
                         exif_software, flags, flag_basis, processed_at)
                    VALUES
                        (CAST(:id AS uuid), CAST(:rid AS uuid), 'social', :kind, :status, :reason, :url,
                         :key, :mime, :bytes, :sha, :phash, CAST(:frames AS bigint[]), :w, :h, :dur,
                         :taken, :offset, :elat, :elng, :make, :model, :software,
                         CAST(:flags AS text[]), CAST(:basis AS jsonb), NOW())
                    ON CONFLICT (report_id, source_url) WHERE source_url IS NOT NULL DO NOTHING
                    RETURNING id
                """),
                {
                    "id": media_id, "rid": str(report["id"]), "kind": kind, "status": status,
                    "reason": reason, "url": url, "key": key, "mime": mime, "bytes": size,
                    "sha": sha, "phash": info.phash if info else None,
                    "frames": (info.frame_phashes or None) if info else None,
                    "w": info.width if info else None, "h": info.height if info else None,
                    "dur": info.duration_s if info else None,
                    "taken": info.exif_taken_at if info else None,
                    "offset": info.exif_offset if info else None,
                    "elat": info.exif_lat if info else None, "elng": info.exif_lng if info else None,
                    "make": info.exif_make if info else None, "model": info.exif_model if info else None,
                    "software": info.exif_software if info else None,
                    "flags": flags, "basis": json.dumps(basis) if basis else None,
                },
            )).fetchone()
            if inserted is not None and flags:
                await apply_report_flags(db, report["id"], flags, basis)
            await db.commit()
    except Exception as e:
        logger.warning(f"Social media {url} not recorded: {type(e).__name__}: {e}")
        return {"result": "failed"}

    if status != "ready":
        logger.info(f"Social attachment skipped ({attachment['role']}): {reason}")
        return {"result": "skipped"}
    return {"result": "downloaded",
            "media": {"id": media_id, "kind": kind, "status": status, "flags": flags,
                      "duration_s": info.duration_s if info else None}}


# ── The loop ───────────────────────────────────────────────────────────────────

async def sweep() -> int:
    """
    Queue what the in-process queue missed: citizen uploads waiting in
    `processing`, and recent posts with attachments not yet hashed. Returns
    how many items were queued.
    """
    from app.core.database import async_session

    queued = 0
    try:
        async with async_session() as db:
            citizen = (await db.execute(
                text("""
                    SELECT id FROM report_media
                    WHERE status = 'processing' AND origin = 'citizen'
                    ORDER BY created_at LIMIT :n
                """),
                {"n": SWEEP_BATCH},
            )).fetchall()
            social = []
            if get_settings().SOCIAL_MEDIA_HASHING_ENABLED:
                social = (await db.execute(
                    text("""
                        SELECT r.id FROM raw_reports r
                        WHERE CAST(r.source_type AS text) = 'SOCIAL_MEDIA'
                          AND r.created_at > NOW() - make_interval(hours => CAST(:hours AS int))
                          AND jsonb_typeof(r.source_meta->'media') = 'array'
                          AND jsonb_array_length(r.source_meta->'media') > 0
                          AND NOT EXISTS (SELECT 1 FROM report_media m WHERE m.report_id = r.id)
                        ORDER BY r.created_at LIMIT :n
                    """),
                    {"hours": SOCIAL_SWEEP_HOURS, "n": SWEEP_BATCH},
                )).fetchall()
    except Exception as e:
        logger.warning(f"Media sweep failed (non-fatal): {e}")
        return 0
    for (media_id,) in citizen:
        if str(media_id) not in _inflight:
            _put(("citizen", str(media_id)))
            queued += 1
    for (report_id,) in social:
        if str(report_id) not in _inflight:
            _put(("social", str(report_id)))
            queued += 1
    return queued


async def handle(item: Tuple[str, str]) -> None:
    kind, ident = item
    if ident in _inflight:
        return
    _inflight.add(ident)
    try:
        if kind == "citizen":
            await process_citizen_media(ident)
        else:
            await process_social_post(ident)
    except Exception as e:
        logger.error(f"Media worker failed on {kind} {ident}: {type(e).__name__}: {e}", exc_info=True)
    finally:
        _inflight.discard(ident)


async def start_media_worker() -> None:
    """The lifespan task: one item at a time, and a sweep whenever the queue is quiet."""
    global _queue
    settings = get_settings()
    if not settings.MEDIA_WORKER_ENABLED:
        logger.info("Media worker disabled (MEDIA_WORKER_ENABLED=false); uploads wait in processing")
        return
    _queue = asyncio.Queue(maxsize=1000)
    if not ffmpeg_available():
        logger.warning("ffprobe/ffmpeg not found: videos will be marked unreadable until it is installed")
    logger.info(f"✓ Media worker started (sweep every {settings.MEDIA_WORKER_SWEEP_SECONDS}s)")
    await sweep()
    while True:
        try:
            try:
                item = await asyncio.wait_for(_queue.get(), timeout=settings.MEDIA_WORKER_SWEEP_SECONDS)
            except asyncio.TimeoutError:
                await sweep()
                continue
            await handle(item)
        except asyncio.CancelledError:
            logger.info("Media worker shutting down...")
            raise
        except Exception as e:
            logger.warning(f"Media worker loop error (non-fatal): {type(e).__name__}: {e}")
