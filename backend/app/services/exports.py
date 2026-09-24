"""
INDRA Platform — Streaming CSV and GeoJSON exports (layer 8a, Phase 2 T10)

The PS asks for an admin panel "for monitoring and analysing collected data";
analysing means taking it elsewhere. GET /api/reports/export and
GET /api/events/export stream what their filters select:

* **Streamed, never held.** Rows come from a server-side cursor in chunks of
  CHUNK_ROWS and leave as they are formatted, so a 50,000-row export costs the
  memory of one chunk. The cursor runs on its own session: the request's
  session belongs to FastAPI's dependency, whose lifetime a streaming body
  outlives.
* **Capped at ROW_CAP rows.** A GeoJSON export says in its `indra` member
  whether the cap cut it short; a CSV export's last line says so.
* **Audited.** Every export appends one DATA_EXPORT row to the hash-chained
  ledger before the first byte is sent — who, what, in which format, with which
  filters. Exact coordinates and full text are personal data under the DPDP
  Act, so the ledger proves who took them as well as who decided what.
"""

import csv
import io
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditAction
from app.services import audit

logger = logging.getLogger("indra.services.exports")

ROW_CAP = 100_000
CHUNK_ROWS = 1000
FORMATS = ("csv", "geojson")
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "geojson": "application/geo+json"}


def filename(kind: str, fmt: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"indra-{kind}-{now:%Y%m%dT%H%M%SZ}.{'csv' if fmt == 'csv' else 'geojson'}"


async def record_export(
    db: AsyncSession, *, operator_id: str, kind: str, fmt: str, filters: Dict[str, Any]
) -> Dict[str, Any]:
    """Append the export's ledger row and commit it. Returns the row."""
    row = await audit.record(
        db,
        event_id=None,
        operator_id=operator_id,
        action=AuditAction.DATA_EXPORT,
        reason=f"{kind} exported as {fmt}",
        details={
            "kind": kind,
            "format": fmt,
            "filters": {k: v for k, v in filters.items() if v is not None},
            "row_cap": ROW_CAP,
        },
    )
    await db.commit()
    return row


def _plain(value: Any) -> Any:
    """A value as JSON and CSV can carry it."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)


async def _rows(sql: str, params: Dict[str, Any]) -> AsyncIterator[Sequence[Mapping[str, Any]]]:
    """The query's rows in chunks, from a server-side cursor on a session of its own."""
    from app.core.database import async_session

    async with async_session() as session:
        result = await session.stream(text(sql), {**params, "row_cap": ROW_CAP + 1})
        async for chunk in result.mappings().partitions(CHUNK_ROWS):
            yield chunk


async def stream_csv(
    sql: str, params: Dict[str, Any], columns: List[str]
) -> AsyncIterator[bytes]:
    """
    A header, then one line per row. `sql` must end in `LIMIT :row_cap`; one
    row past the cap is read only to know that the cap was reached.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    yield buffer.getvalue().encode("utf-8")

    count, truncated = 0, False
    try:
        async for chunk in _rows(sql, params):
            buffer.seek(0)
            buffer.truncate()
            for row in chunk:
                if count >= ROW_CAP:
                    truncated = True
                    break
                writer.writerow([
                    json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else ("" if v is None else v)
                    for v in (_plain(row[c]) for c in columns)
                ])
                count += 1
            yield buffer.getvalue().encode("utf-8")
            if truncated:
                break
    except Exception as e:
        # The status line has gone; the file can only say it is incomplete.
        logger.error(f"CSV export failed after {count} rows: {e}")
        yield f"# export failed after {count} rows: {type(e).__name__}\n".encode("utf-8")
        return
    if truncated:
        yield f"# truncated at {ROW_CAP} rows; narrow the filters for the rest\n".encode("utf-8")


async def stream_geojson(
    sql: str,
    params: Dict[str, Any],
    to_feature: Callable[[Mapping[str, Any]], Dict[str, Any]],
) -> AsyncIterator[bytes]:
    """A FeatureCollection, one feature per row, with an `indra` member saying how many and whether truncated."""
    yield b'{"type":"FeatureCollection","features":['
    count, truncated, error = 0, False, None
    try:
        async for chunk in _rows(sql, params):
            parts: List[str] = []
            for row in chunk:
                if count >= ROW_CAP:
                    truncated = True
                    break
                parts.append(("," if count else "") + json.dumps(to_feature(row), ensure_ascii=False, default=_plain))
                count += 1
            if parts:
                yield "".join(parts).encode("utf-8")
            if truncated:
                break
    except Exception as e:
        logger.error(f"GeoJSON export failed after {count} features: {e}")
        error = type(e).__name__
    tail = {"features": count, "truncated": truncated, "row_cap": ROW_CAP}
    if error:
        tail["error"] = f"export failed after {count} features: {error}"
    yield ('],"indra":' + json.dumps(tail) + "}").encode("utf-8")


def point_geometry(lat: Any, lng: Any) -> Optional[Dict[str, Any]]:
    if lat is None or lng is None:
        return None
    return {"type": "Point", "coordinates": [float(lng), float(lat)]}
