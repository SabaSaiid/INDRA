"""
INDRA Platform — Photos and videos (layers 2, 7 and 8a; Phase 5 T1, T5)

**Uploads** (T1, as re-planned on 27 Sep in webpage.MD §8.3). The text of a
report goes first, on its own, so it reaches the dashboard in about a second;
its photos and videos follow in **5 MiB parts**, so a video survives a dropped
mobile connection and the API never holds a whole file in memory:

    POST /api/media/uploads                          start: {docket, mime, size_bytes}
    PUT  /api/media/uploads/{upload_id}/parts/{n}    the raw bytes of part n (1-based)
    GET  /api/media/uploads/{upload_id}              which parts arrived
    POST /api/media/uploads/{upload_id}/complete     all parts in → processing

Each part the phone sends becomes one S3 UploadPart in the object store. The
rules, all checked before anything is stored:

* **Only the device that filed the report can attach media:** the keyed hash
  of `X-Reporter-Id` must equal the report's `reporter_hash`, or 403.
* **The media window is MEDIA_WINDOW_HOURS (24) after the report was
  received;** after that, 409.
* **Limits** (media_types.py): a photo up to 10 MB, a video up to 50 MB, at
  most 4 files and 80 MB per report → 413; a declared type that is not an
  image or a video → 415.
* **Magic bytes on part 1**, the moment it arrives: a file whose first bytes
  are not a JPEG, PNG, WebP, HEIC, MP4 or MOV is refused with 415, the upload
  is aborted and its row marked `rejected`. A renamed `.exe` is stopped after
  its first 5 MB, not its fiftieth.
* **Object store down:** 503 `media_store_unavailable`. The report itself is
  already stored and is not affected.

Parts go to `indra-media/incoming/{upload_id}`; the media worker moves the file
to `originals/{yyyy}/{mm}/{dd}/{report_id}/{sha256}.{ext}` once it knows the
SHA-256 (workers/media_worker.py).

**Serving** (T5, as re-planned in webpage.MD §8.5): the store is private, so
the API signs its own short-lived URLs and streams the bytes itself:

    POST /api/media/signed-urls        ANALYST+ · {ids, size: thumb|full, original?}
    GET  /api/media/{id}/file          anyone holding an unexpired signed URL

What is served by default is the EXIF-free copy: published media never leaks
where a citizen took it. The original, EXIF and GPS included, is for
verification work only, and every link to one is written to the audit ledger.
A Mastodon attachment is never served at all: its "URL" is the author's own
link, because INDRA never re-hosts other people's posts (T4).
"""

import asyncio
import logging
import re
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import TokenData, require_roles
from app.models.enums import AuditAction
from app.services import audit, clock, objectstore
from app.services.ingest import normalise_docket, reporter_hash_for
from app.services.media_signing import SigningUnavailable, media_url_valid, sign_media_url
from app.services.media_types import (
    CHUNK_SIZE,
    MAX_BYTES_PER_REPORT,
    MAX_FILES_PER_REPORT,
    SNIFF_BYTES,
    declared_kind,
    expected_part_size,
    max_bytes,
    mb,
    parts_for,
    sniff,
)

logger = logging.getLogger("indra.api.media")
router = APIRouter(prefix="/api/media", tags=["Media"])

STORE_UNAVAILABLE = "media_store_unavailable"
# Statuses that still count towards a report's 4 files and 80 MB.
LIVE_STATUSES = ("uploading", "processing", "ready")


def _bucket() -> str:
    return get_settings().S3_MEDIA_BUCKET


def _store_down(e: Exception) -> HTTPException:
    logger.warning(f"Object store unavailable for media: {e}")
    return HTTPException(status_code=503, detail=STORE_UNAVAILABLE)


def _owner_or_403(stored_hash: Optional[str], x_reporter_id: Optional[str]) -> None:
    """
    403 unless this request comes from the device that filed the report. A
    report stored without a reporter hash (no X-Reporter-Id, or no
    REPORTER_SALT) has no owner anyone can prove, so nobody may attach to it.
    """
    mine = reporter_hash_for(x_reporter_id)
    if not stored_hash or not mine or mine != stored_hash:
        raise HTTPException(
            status_code=403, detail="Only the device that filed this report can attach media to it"
        )


# ── Start ──────────────────────────────────────────────────────────────────────

class UploadStart(BaseModel):
    docket: str = Field(..., min_length=1, max_length=40)
    # Accepted for the client's own bookkeeping and never stored: a gallery
    # file name can carry a person's name or a place.
    file_name: Optional[str] = Field(None, max_length=255)
    mime: str = Field(..., min_length=1, max_length=100)
    size_bytes: int = Field(..., gt=0)


@router.post("/uploads", status_code=201)
async def start_upload(
    body: UploadStart,
    db: AsyncSession = Depends(get_db),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
):
    """Open an upload session for one photo or video of a report. See the module docstring."""
    settings = get_settings()
    docket = normalise_docket(body.docket)
    if docket is None:
        raise HTTPException(status_code=404, detail="No report with that docket")

    kind = declared_kind(body.mime)
    if kind is None:
        raise HTTPException(status_code=415, detail="Only photos and videos can be attached")
    limit = max_bytes(kind)
    if body.size_bytes > limit:
        raise HTTPException(
            status_code=413, detail=f"A {kind} may be at most {mb(limit)}; this one is {mb(body.size_bytes)}"
        )

    try:
        # Locked, so two uploads started at once cannot both be the 4th file.
        report = (await db.execute(
            text("""
                SELECT id, reporter_hash, created_at, withdrawn_at
                FROM raw_reports WHERE docket = :docket
                FOR UPDATE
            """),
            {"docket": docket},
        )).fetchone()
    except Exception as e:
        logger.warning(f"Database query failed in start_upload: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")
    if report is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="No report with that docket")
    report_id, stored_hash, received_at, withdrawn_at = report

    try:
        _owner_or_403(stored_hash, x_reporter_id)
        if withdrawn_at is not None:
            raise HTTPException(status_code=409, detail="This report was withdrawn")
        if clock.now() > received_at + timedelta(hours=settings.MEDIA_WINDOW_HOURS):
            raise HTTPException(
                status_code=409,
                detail=f"Media can be attached for {settings.MEDIA_WINDOW_HOURS} hours after a report is received",
            )
        files, total = (await db.execute(
            text("""
                SELECT count(*), COALESCE(sum(declared_size), 0)
                FROM report_media
                WHERE report_id = :rid AND origin = 'citizen' AND status = ANY(CAST(:live AS text[]))
            """),
            {"rid": report_id, "live": list(LIVE_STATUSES)},
        )).one()
        if files >= MAX_FILES_PER_REPORT:
            raise HTTPException(
                status_code=413, detail=f"A report can carry at most {MAX_FILES_PER_REPORT} files"
            )
        if total + body.size_bytes > MAX_BYTES_PER_REPORT:
            raise HTTPException(
                status_code=413,
                detail=f"A report's files may add up to at most {mb(MAX_BYTES_PER_REPORT)}",
            )
    except HTTPException:
        await db.rollback()
        raise

    media_id = uuid.uuid4()
    key = f"incoming/{media_id}"
    try:
        s3_upload_id = await objectstore.create_multipart(_bucket(), key, body.mime)
    except objectstore.ObjectStoreUnavailable as e:
        await db.rollback()
        raise _store_down(e)

    parts = parts_for(body.size_bytes)
    try:
        await db.execute(
            text("""
                INSERT INTO report_media
                    (id, report_id, origin, kind, status, declared_mime, declared_size, parts,
                     s3_upload_id, incoming_key)
                VALUES (:id, :rid, 'citizen', :kind, 'uploading', :mime, :size, :parts, :upload, :key)
            """),
            {
                "id": media_id, "rid": report_id, "kind": kind, "mime": body.mime,
                "size": body.size_bytes, "parts": parts, "upload": s3_upload_id, "key": key,
            },
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Upload session for {docket} could not be stored: {e}")
        try:
            await objectstore.abort_multipart(_bucket(), key, s3_upload_id)
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info(f"Media upload {media_id} started for {docket}: {kind}, {body.size_bytes} bytes, {parts} part(s)")
    return JSONResponse(
        status_code=201,
        content={
            "upload_id": str(media_id),
            "media_id": str(media_id),
            "kind": kind,
            "chunk_size": CHUNK_SIZE,
            "parts": parts,
        },
    )


# ── Parts ──────────────────────────────────────────────────────────────────────

_SESSION_SQL = text("""
    SELECT m.id, m.report_id, m.kind, m.status, m.reason, m.declared_mime, m.declared_size,
           m.parts, m.s3_upload_id, m.incoming_key, r.reporter_hash
    FROM report_media m
    JOIN raw_reports r ON r.id = m.report_id
    WHERE m.id = CAST(:id AS uuid) AND m.origin = 'citizen'
""")


def _media_uuid_or_404(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No such upload")


async def _session(db: AsyncSession, upload_id: str, x_reporter_id: Optional[str]) -> Dict[str, Any]:
    media_id = _media_uuid_or_404(upload_id)
    try:
        row = (await db.execute(_SESSION_SQL, {"id": media_id})).fetchone()
    except Exception as e:
        logger.warning(f"Database query failed for upload {media_id}: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")
    # End the read transaction now: a part can take a minute to arrive over a
    # slow mobile link, and an open transaction would hold a pooled connection
    # for all of it. Later writes open their own.
    await db.rollback()
    if row is None:
        raise HTTPException(status_code=404, detail="No such upload")
    session = dict(row._mapping)
    _owner_or_403(session.pop("reporter_hash"), x_reporter_id)
    return session


async def _read_part(request: Request) -> bytes:
    """The request body, refused with 413 as soon as it is longer than one part."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > CHUNK_SIZE:
        raise HTTPException(status_code=413, detail=f"A part may be at most {CHUNK_SIZE} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > CHUNK_SIZE:
            raise HTTPException(status_code=413, detail=f"A part may be at most {CHUNK_SIZE} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _reject(db: AsyncSession, session: Dict[str, Any], reason: str) -> None:
    """Abort the store's upload and mark the row rejected. Never raises."""
    try:
        await objectstore.abort_multipart(_bucket(), session["incoming_key"], session["s3_upload_id"])
    except Exception as e:
        logger.warning(f"Abort of upload {session['id']} failed (the cleanup script retries): {e}")
    try:
        await db.execute(
            text("UPDATE report_media SET status = 'rejected', reason = :r WHERE id = :id"),
            {"r": reason, "id": session["id"]},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Upload {session['id']} could not be marked rejected: {e}")


@router.put("/uploads/{upload_id}/parts/{n}")
async def upload_part(
    upload_id: str,
    n: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
):
    """
    Part n of the file, as raw bytes (`application/octet-stream`). Every part
    is exactly 5,242,880 bytes except the last. Sending a part again replaces
    it. Part 1's first bytes decide what the file really is.
    """
    session = await _session(db, upload_id, x_reporter_id)
    if session["status"] != "uploading":
        raise HTTPException(status_code=409, detail=f"This upload is {session['status']}")
    if not 1 <= n <= session["parts"]:
        raise HTTPException(status_code=422, detail=f"Parts are numbered 1 to {session['parts']}")

    body = await _read_part(request)
    expected = expected_part_size(n, session["declared_size"])
    if len(body) != expected:
        raise HTTPException(
            status_code=422, detail=f"Part {n} must be {expected} bytes; {len(body)} arrived"
        )

    if n == 1:
        sniffed = sniff(body[:SNIFF_BYTES])
        if sniffed is None or sniffed.kind != session["kind"]:
            what = "not a photo or video" if sniffed is None else f"a {sniffed.kind}, not a {session['kind']}"
            await _reject(db, session, f"refused on its first bytes: {what}")
            logger.info(f"Upload {session['id']} refused on part 1: {what}")
            raise HTTPException(status_code=415, detail="Only photos and videos can be attached")
        try:
            await db.execute(
                text("UPDATE report_media SET mime = :mime WHERE id = :id"),
                {"mime": sniffed.mime, "id": session["id"]},
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning(f"Database write failed for upload {session['id']}: {e}")
            raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        etag = await objectstore.upload_part(
            _bucket(), session["incoming_key"], session["s3_upload_id"], n, body
        )
    except objectstore.ObjectStoreUnavailable as e:
        raise _store_down(e)
    return {"n": n, "etag": etag}


@router.get("/uploads/{upload_id}")
async def upload_state(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
):
    """
    Which parts have arrived, so a phone that lost its connection sends only
    the rest. While uploading, the list comes from the object store itself.
    """
    session = await _session(db, upload_id, x_reporter_id)
    received = []
    if session["status"] == "uploading":
        try:
            received = [p["n"] for p in await objectstore.list_parts(
                _bucket(), session["incoming_key"], session["s3_upload_id"]
            )]
        except objectstore.ObjectStoreUnavailable as e:
            raise _store_down(e)
    elif session["status"] in ("processing", "ready"):
        received = list(range(1, session["parts"] + 1))
    return {
        "upload_id": str(session["id"]),
        "status": session["status"],
        "reason": session["reason"],
        "chunk_size": CHUNK_SIZE,
        "parts": session["parts"],
        "received_parts": received,
    }


@router.post("/uploads/{upload_id}/complete", status_code=202)
async def complete_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
):
    """
    Every part is in: join them into one object and hand it to the media
    worker. 409 with `missing_parts` if any has not arrived. Completing twice
    answers the same 202.
    """
    session = await _session(db, upload_id, x_reporter_id)
    media_id = str(session["id"])
    if session["status"] in ("processing", "ready"):
        return JSONResponse(status_code=202, content={"media_id": media_id, "status": session["status"]})
    if session["status"] != "uploading":
        raise HTTPException(status_code=409, detail=f"This upload is {session['status']}")

    already_joined = False
    try:
        parts = await objectstore.list_parts(_bucket(), session["incoming_key"], session["s3_upload_id"])
    except objectstore.ObjectStoreUnavailable as e:
        raise _store_down(e)
    except Exception as e:
        # No such upload: a previous complete joined the parts and then failed
        # to record it. The object is there; only the row is behind.
        if not objectstore._is_missing(e):
            raise
        try:
            already_joined = await objectstore.exists(_bucket(), session["incoming_key"])
        except objectstore.ObjectStoreUnavailable as down:
            raise _store_down(down)
        if not already_joined:
            await _reject(db, session, "the object store lost this upload")
            raise HTTPException(status_code=409, detail="This upload was lost; start it again")
        parts = []

    if not already_joined:
        have = {p["n"] for p in parts}
        missing = [n for n in range(1, session["parts"] + 1) if n not in have]
        if missing:
            return JSONResponse(
                status_code=409,
                content={"detail": "Some parts have not arrived", "missing_parts": missing},
            )
        try:
            await objectstore.complete_multipart(
                _bucket(), session["incoming_key"], session["s3_upload_id"],
                [p for p in parts if p["n"] <= session["parts"]],
            )
        except objectstore.ObjectStoreUnavailable as e:
            raise _store_down(e)

    try:
        await db.execute(
            text("UPDATE report_media SET status = 'processing', bytes = :size WHERE id = :id"),
            {"size": session["declared_size"], "id": media_id},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        # The object is complete in incoming/; the row still says uploading, so
        # completing again finishes the job.
        logger.error(f"Upload {media_id} completed in the store but not recorded: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    from app.workers import media_worker

    media_worker.enqueue(media_id)
    logger.info(f"Media upload {media_id} complete ({session['parts']} part(s)); processing")
    return JSONResponse(status_code=202, content={"media_id": media_id, "status": "processing"})


# ── Serving to officials (T5, webpage.MD §8.5) ─────────────────────────────────

class SignedUrlRequest(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=100)
    size: Literal["thumb", "full"] = "thumb"
    # The original file, EXIF and GPS included, for verification work. Audited.
    original: bool = False


def _served_key(row: Dict[str, Any], size: str) -> Optional[str]:
    """The object a size means for this media, or None when it does not exist (any more)."""
    if size == "original":
        return None if row["original_deleted_at"] else row["object_key"]
    if row["derivatives_deleted_at"]:
        return None
    return row["thumb_key"] if size == "thumb" else row["derivative_key"]


_SERVE_SQL = text("""
    SELECT id, report_id, origin, kind, status, mime, source_url, object_key, derivative_key,
           thumb_key, original_deleted_at, derivatives_deleted_at
    FROM report_media
    WHERE id = ANY(CAST(:ids AS uuid[]))
""")


@router.post("/signed-urls")
async def signed_urls(
    body: SignedUrlRequest,
    operator: TokenData = Depends(require_roles("ANALYST", "COMMANDER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """
    `{urls: {id: url}}` for the media asked for, each valid for
    MEDIA_URL_TTL_SECONDS (10 min); on an image `error`, mint again. Media
    that is not ready, or whose copy retention has removed, is listed under
    `unavailable` with the reason. A Mastodon attachment's URL is the
    author's own link (`external: true`).

    `original: true` gives links to the originals and writes one
    MEDIA_ORIGINAL_ACCESS row to the ledger naming the operator and the media.
    """
    ids = []
    for value in body.ids:
        try:
            ids.append(str(uuid.UUID(value)))
        except (ValueError, AttributeError):
            continue
    size = "original" if body.original else body.size
    try:
        rows = [dict(r._mapping) for r in (await db.execute(_SERVE_SQL, {"ids": ids})).fetchall()]
    except Exception as e:
        logger.warning(f"Database query failed in signed_urls: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    urls: Dict[str, str] = {}
    external: Dict[str, bool] = {}
    unavailable: Dict[str, str] = {i: "no such media" for i in ids}
    try:
        for row in rows:
            media_id = str(row["id"])
            if row["status"] != "ready":
                unavailable[media_id] = f"media is {row['status']}"
                continue
            if row["origin"] == "social":
                urls[media_id] = row["source_url"]
                external[media_id] = True
                unavailable.pop(media_id, None)
                continue
            if _served_key(row, size) is None:
                unavailable[media_id] = f"the {size} copy is not held (retention or not produced)"
                continue
            urls[media_id] = sign_media_url(media_id, size)
            unavailable.pop(media_id, None)
    except SigningUnavailable:
        raise HTTPException(status_code=503, detail="Media serving is not configured (MEDIA_URL_SECRET)")

    signed_originals = [i for i in urls if size == "original" and not external.get(i)]
    if signed_originals:
        operator_id = operator.operator_id or operator.sub
        try:
            await audit.record(
                db,
                event_id=None,
                operator_id=operator_id,
                action=AuditAction.MEDIA_ORIGINAL_ACCESS,
                reason=f"{len(signed_originals)} original photo(s)/video(s) linked for verification",
                details={
                    "media_ids": sorted(signed_originals),
                    "report_ids": sorted({str(r["report_id"]) for r in rows if str(r["id"]) in signed_originals}),
                },
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"MEDIA_ORIGINAL_ACCESS could not be recorded: {e}")
            # No audit row, no original: the ledger is the condition of access.
            raise HTTPException(status_code=503, detail="Access to originals could not be recorded")

    return {
        "urls": urls,
        "external": external,
        "size": size,
        "expires_in": get_settings().MEDIA_URL_TTL_SECONDS,
        "unavailable": unavailable,
    }


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
STREAM_CHUNK = 64 * 1024


def parse_range(header: Optional[str], total: int):
    """
    (start, end) inclusive for a single `Range: bytes=…` header, None for no
    header, or "invalid" for one that cannot be satisfied (416). Multiple
    ranges are not supported and are treated as invalid.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match or total <= 0:
        return "invalid"
    first, last = match.groups()
    if first == "" and last == "":
        return "invalid"
    if first == "":
        # The last N bytes.
        n = int(last)
        if n == 0:
            return "invalid"
        return max(0, total - n), total - 1
    start = int(first)
    end = min(int(last), total - 1) if last else total - 1
    if start >= total or start > end:
        return "invalid"
    return start, end


@router.get("/{media_id}/file")
async def media_file(
    media_id: str,
    request: Request,
    size: str = Query(...),
    exp: int = Query(...),
    sig: str = Query(..., max_length=128),
    db: AsyncSession = Depends(get_db),
):
    """
    The bytes behind a signed URL. `Range` is supported, so a video can seek
    (206 with `Content-Range`). An expired or altered URL is 403.
    """
    try:
        media_uuid = str(uuid.UUID(media_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    if not media_url_valid(media_uuid, size, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired link")

    try:
        row = (await db.execute(_SERVE_SQL, {"ids": [media_uuid]})).fetchone()
    except Exception as e:
        logger.warning(f"Database query failed in media_file: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")
    if row is None or row._mapping["status"] != "ready" or row._mapping["origin"] != "citizen":
        raise HTTPException(status_code=404, detail="No such media")
    row = dict(row._mapping)
    key = _served_key(row, size)
    if key is None:
        raise HTTPException(status_code=404, detail="This copy is no longer held")

    bucket = get_settings().S3_MEDIA_BUCKET
    try:
        meta = await objectstore.head(bucket, key)
    except objectstore.ObjectStoreUnavailable as e:
        raise _store_down(e)
    if meta is None:
        raise HTTPException(status_code=404, detail="This copy is no longer held")
    total = int(meta["size"])
    is_video_copy = row["kind"] == "video" and size != "thumb"
    content_type = (row["mime"] if (size == "original" or is_video_copy) else "image/jpeg") \
        or meta.get("content_type") or "application/octet-stream"

    wanted = parse_range(request.headers.get("range"), total)
    if wanted == "invalid":
        raise HTTPException(
            status_code=416, detail="Range not satisfiable", headers={"Content-Range": f"bytes */{total}"}
        )
    start, end = wanted if wanted else (None, None)

    try:
        response = await asyncio.to_thread(objectstore.open_range_sync, bucket, key, start, end)
    except Exception as e:
        raise _store_down(e)
    body = response["Body"]

    async def chunks():
        try:
            while True:
                block = await asyncio.to_thread(body.read, STREAM_CHUNK)
                if not block:
                    break
                yield block
        finally:
            await asyncio.to_thread(body.close)

    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": f"private, max-age={get_settings().MEDIA_URL_TTL_SECONDS}",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    if wanted:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(chunks(), status_code=206, media_type=content_type, headers=headers)
    headers["Content-Length"] = str(total)
    return StreamingResponse(chunks(), status_code=200, media_type=content_type, headers=headers)


# ── What the open lists may say about a report's media ─────────────────────────

async def media_counts(db: AsyncSession, report_ids: List[Any]) -> Dict[str, Dict[str, Any]]:
    """
    {report_id: {"media_count", "media_kinds", "media_ids", "media_flags"}} for
    the ready media of each report. **No URL, ever:** the lists that use this
    (`GET /api/reports/recent`) are open, so they carry ids, and the pictures
    come from the signed-in call above. Empty on any failure.
    """
    ids = [str(r) for r in report_ids]
    if not ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                text("""
                    SELECT report_id, id, kind, COALESCE(flags, '{}'::text[])
                    FROM report_media
                    WHERE report_id = ANY(CAST(:ids AS uuid[])) AND status = 'ready'
                    ORDER BY created_at, id
                """),
                {"ids": ids},
            )).fetchall()
    except Exception as e:
        logger.warning(f"Media lookup failed for a report list: {e}")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for report_id, media_id, kind, flags in rows:
        entry = out.setdefault(str(report_id), {
            "media_count": 0, "media_kinds": [], "media_ids": [], "media_flags": [],
        })
        entry["media_count"] += 1
        entry["media_ids"].append(str(media_id))
        if kind not in entry["media_kinds"]:
            entry["media_kinds"].append(kind)
        for flag in flags:
            if flag not in entry["media_flags"]:
                entry["media_flags"].append(flag)
    return out
