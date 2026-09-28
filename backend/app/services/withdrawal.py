"""
INDRA Platform — A citizen takes their report back (layers 7 and 8a, Phase 5 T5)

    DELETE /api/reports/{docket}     with the X-Reporter-Id that filed it

Only the device that filed a report can withdraw it (the keyed hash of its
`X-Reporter-Id` must match the stored one; anything else is 403). Then, in one
transaction:

* **the text is redacted** to "[withdrawn]", and the analysis, the exact
  position (coordinates, point, H3 cell) and `source_meta` are cleared;
* **its media is marked withdrawn**, and uploads still in progress are
  aborted;
* **it leaves clustering for good:** no event, no position, `withdrawn_at` set;
* **the outbox copy of its message is redacted** the same way;
* **a `REPORT_WITHDRAWN` row** goes to the audit ledger.

After the commit the files are deleted from the object store (retention
finishes the job if the store is down), and the event it was in is re-scored
without it and broadcast.

The row itself stays as a tombstone — docket, time received, district, state,
reporter pseudonym — so the docket answers "withdrawn", the ledger rows that
name it still resolve, and withdrawing a rejected report cannot wipe its
reporter's record (T6).

**What it does not reach:** the lake's raw copy of the report stream
(Phase 2 T9) holds the message as it was published, in batched objects; it is
not rewritten. Recorded in the bug register.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.config import get_settings
from app.models.enums import AuditAction
from app.services import audit, objectstore

logger = logging.getLogger("indra.services.withdrawal")

REDACTED_TEXT = "[withdrawn]"
CITIZEN_OPERATOR = "CITIZEN"


class NotFound(Exception):
    pass


class NotYours(Exception):
    pass


def _media_keys(row: Dict[str, Any]) -> List[str]:
    keys = [row.get(k) for k in ("object_key", "derivative_key", "poster_key", "thumb_key", "incoming_key")]
    return [k for k in keys if k]


async def withdraw(db, docket: str, reporter_hash: Optional[str]) -> Dict[str, Any]:
    """
    Withdraw one report. Raises NotFound or NotYours; otherwise returns what
    was done. Withdrawing twice answers the same, and changes nothing.
    """
    row = (await db.execute(
        text("""
            SELECT r.id, r.reporter_hash, r.event_id, r.withdrawn_at, e.event_code
            FROM raw_reports r
            LEFT JOIN verified_events e ON e.id = r.event_id
            WHERE r.docket = :docket
            FOR UPDATE OF r
        """),
        {"docket": docket},
    )).fetchone()
    if row is None:
        await db.rollback()
        raise NotFound(docket)
    report_id, stored_hash, event_id, withdrawn_at, event_code = row
    if not stored_hash or not reporter_hash or stored_hash != reporter_hash:
        await db.rollback()
        raise NotYours(docket)
    if withdrawn_at is not None:
        await db.rollback()
        return {"docket": docket, "status": "withdrawn", "withdrawn_at": withdrawn_at.isoformat(),
                "media_deleted": 0, "event_rescored": False, "already": True}

    media = [dict(m._mapping) for m in (await db.execute(
        text("""
            SELECT id, status, s3_upload_id, object_key, derivative_key, poster_key, thumb_key, incoming_key
            FROM report_media
            WHERE report_id = CAST(:id AS uuid) AND origin = 'citizen'
            FOR UPDATE
        """),
        {"id": str(report_id)},
    )).fetchall()]

    await db.execute(
        text("""
            UPDATE raw_reports SET
                raw_text = :redacted,
                analysis = NULL,
                source_meta = NULL,
                media_url = NULL,
                latitude = NULL,
                longitude = NULL,
                geom_point = NULL,
                h3_res8 = NULL,
                place_precision = 'none',
                event_id = NULL,
                withdrawn_at = NOW()
            WHERE id = CAST(:id AS uuid)
        """),
        {"id": str(report_id), "redacted": REDACTED_TEXT},
    )
    await db.execute(
        text("UPDATE report_media SET status = 'withdrawn', reason = 'withdrawn by the reporter' "
             "WHERE report_id = CAST(:id AS uuid) AND origin = 'citizen'"),
        {"id": str(report_id)},
    )
    # The outbox keeps the published message; it carries the text and position too.
    await db.execute(
        text("""
            UPDATE outbox SET payload = payload || CAST(:redacted AS jsonb)
            WHERE key = :key
        """),
        {
            "key": str(report_id),
            "redacted": json.dumps({
                "raw_text": REDACTED_TEXT, "latitude": None, "longitude": None,
                "h3_res8": None, "media_url": None,
            }),
        },
    )
    await audit.record(
        db,
        event_id=event_id,
        operator_id=CITIZEN_OPERATOR,
        action=AuditAction.REPORT_WITHDRAWN,
        reason=f"report {docket} withdrawn by its reporter"
               + (f"; it leaves {event_code}" if event_code else ""),
        details={
            "report_id": str(report_id),
            "docket": docket,
            "event_code": event_code,
            "media_deleted": len(media),
        },
    )
    await db.commit()
    logger.info(f"Report {docket} withdrawn ({len(media)} media; event {event_code or 'none'})")

    deleted = await delete_media_objects(db, media)
    rescored = False
    if event_id is not None:
        rescored = await _rescore(event_id, report_id)
    return {"docket": docket, "status": "withdrawn", "media_deleted": deleted,
            "event_rescored": rescored, "event_code": event_code, "already": False}


async def delete_media_objects(db, media: List[Dict[str, Any]]) -> int:
    """
    Remove each file's objects and abort any upload still open, then stamp the
    rows. A store that is down leaves the stamps unset, and the retention run
    deletes them later. Returns how many files are gone.
    """
    bucket = get_settings().S3_MEDIA_BUCKET
    gone = 0
    for m in media:
        try:
            if m.get("status") == "uploading" and m.get("s3_upload_id") and m.get("incoming_key"):
                await objectstore.abort_multipart(bucket, m["incoming_key"], m["s3_upload_id"])
            for key in _media_keys(m):
                await objectstore.delete(bucket, key)
        except Exception as e:
            logger.warning(f"Media {m['id']} of a withdrawn report not deleted yet (retention retries): {e}")
            continue
        try:
            await db.execute(
                text("""
                    UPDATE report_media SET original_deleted_at = COALESCE(original_deleted_at, NOW()),
                                            derivatives_deleted_at = COALESCE(derivatives_deleted_at, NOW())
                    WHERE id = CAST(:id AS uuid)
                """),
                {"id": str(m["id"])},
            )
            await db.commit()
            gone += 1
        except Exception as e:
            await db.rollback()
            logger.warning(f"Media {m['id']} deleted but not stamped: {e}")
    return gone


async def _rescore(event_id: Any, report_id: Any) -> bool:
    """Re-score the event without the withdrawn report, and broadcast a change. Never raises."""
    try:
        from app.core.database import async_session
        from app.services import pipeline
        from app.services.late_corroboration import _broadcast

        async with async_session() as db:
            event = await pipeline.rescore_event(
                db, event_id, trigger=f"withdrawal:{report_id}", trigger_detail={"report_id": str(report_id)}
            )
        if event is not None:
            await _broadcast(event)
            return True
    except Exception as e:
        logger.warning(f"Re-score after a withdrawal failed (non-fatal): {e}")
    return False
