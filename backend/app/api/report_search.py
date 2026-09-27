"""
INDRA Platform — Report search and export (layer 8a, Phase 2 T10)

GET /api/reports/search  — every report INDRA holds, filtered; total in X-Total-Count
GET /api/reports/export  — the same selection as CSV or GeoJSON, streamed and audited

The backend of the PS's "Admin Panel for monitoring and analysing collected
data": citizen reports, official dispatches, Mastodon posts and news headlines
in one searchable table.

**ANALYST or above.** Unlike the open read routes, this returns exact
coordinates and full text, which are personal data under the DPDP Act.

Filters (all optional, all combined with AND; a comma list is OR within it):

    from, to        an IST day (YYYY-MM-DD) or an ISO 8601 timestamp, on
                    observed_at; time_field=created switches to received time
    source_type     CITIZEN_APP, OFFICIAL_DISPATCH, SOCIAL_MEDIA, NEWS_MEDIA, …
    platform        mastodon, google_news
    publisher       a news publisher's name, any case
    state, district exact names, any case
    precision       gps, district, state, none
    status          fused, duplicate, unfused, stale, held (see STATUS_SQL)
    has_media       true / false
    language        en, hi, hinglish, or a post's own language code
    hazard          an event type: a hazard the report's text is tagged with
                    (Phase 3, any of them, not only the primary), or the
                    category a citizen picked
    flag            a misleading-text flag (Phase 3 T8): promotional,
                    not_an_observation, past_event, implausible_value,
                    exaggeration, shouting, forward_marker, coordinated
    q               text contains, any case
    sort            observed_at | created_at | credibility, then :asc or :desc
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.query_params import csv_values, date_range, invalid, like_pattern
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import TokenData, require_roles
from app.models.enums import EventType, SourceType
from app.services import exports
from app.services.report_flags import FLAGS

logger = logging.getLogger("indra.api.report_search")
router = APIRouter(prefix="/api/reports", tags=["Reports"])

_analyst = require_roles("ANALYST", "COMMANDER", "ADMIN")

PLATFORMS = ("mastodon", "google_news")
PRECISIONS = ("gps", "district", "state", "none")
STATUSES = ("fused", "duplicate", "unfused", "stale", "held")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,8}(-[a-z0-9]{2,8})?$")

# One status per report, in this order of precedence:
#   duplicate  suppressed as a copy of an earlier report (duplicate_of set)
#   fused      part of an event
#   stale      a headline already over 48 h old when collected; never clustered
#   held       a post or headline, stored and shown, that cannot cluster: social
#              clustering is off, it names no district (state or no place),
#              or it is a forecast or warning (context only, Phase 3 T8)
#   unfused    anything else not (yet) part of an event: a report people filed,
#              or a post that could cluster and has found no neighbours
STATUS_SQL = """
    CASE
        WHEN r.duplicate_of IS NOT NULL THEN 'duplicate'
        WHEN r.event_id IS NOT NULL THEN 'fused'
        WHEN COALESCE((r.source_meta->>'stale')::boolean, false) THEN 'stale'
        WHEN CAST(r.source_type AS text) IN ('SOCIAL_MEDIA', 'NEWS_MEDIA')
             AND (NOT CAST(:social_on AS boolean)
                  OR COALESCE(r.place_precision, 'gps') IN ('state', 'none')
                  OR 'not_an_observation' = ANY(COALESCE(r.flags, '{}'::text[])))
             THEN 'held'
        ELSE 'unfused'
    END
"""

MEDIA_COUNT_SQL = """
    (CASE WHEN r.media_url IS NOT NULL THEN 1 ELSE 0 END
     + CASE WHEN jsonb_typeof(r.source_meta->'media') = 'array'
            THEN jsonb_array_length(r.source_meta->'media') ELSE 0 END)
"""

# Every hazard type the report's text is tagged with (analysis.hazards, the
# tagger's full detail), in the tagger's precedence order.
HAZARD_TYPES_SQL = """
    ARRAY(
        SELECT h->>'type'
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(r.analysis->'hazards') = 'array'
                 THEN r.analysis->'hazards' ELSE '[]'::jsonb END
        ) WITH ORDINALITY AS t(h, n)
        ORDER BY n
    )
"""

SORTS = {
    "observed_at": "COALESCE(r.observed_at, r.created_at)",
    "created_at": "r.created_at",
    "credibility": "r.credibility_score",
}

SELECT_SQL = f"""
    SELECT r.id,
           CASE WHEN CAST(r.source_type AS text) = 'CITIZEN_APP' THEN r.docket END AS docket,
           CAST(r.source_type AS text) AS source_type,
           r.platform,
           r.source_meta->>'publisher' AS publisher,
           r.source_meta->>'url' AS url,
           left(r.raw_text, 500) AS text,
           COALESCE(r.source_meta->>'language', r.analysis->>'language') AS language,
           r.district, r.state,
           COALESCE(r.place_precision, 'gps') AS precision,
           round(CAST(r.latitude AS numeric), 4) AS lat,
           round(CAST(r.longitude AS numeric), 4) AS lng,
           r.observed_at, r.created_at,
           {STATUS_SQL} AS status,
           e.event_code,
           r.duplicate_of,
           r.credibility_score AS credibility,
           {MEDIA_COUNT_SQL} AS media_count,
           r.citizen_hazard AS hazard,
           r.hazard_primary,
           {HAZARD_TYPES_SQL} AS hazards,
           r.flags
    FROM raw_reports r
    LEFT JOIN verified_events e ON e.id = r.event_id
"""

COLUMNS = [
    "id", "docket", "source_type", "platform", "publisher", "url", "text", "language",
    "district", "state", "precision", "lat", "lng", "observed_at", "created_at", "status",
    "event_code", "duplicate_of", "credibility", "media_count", "hazard",
    "hazard_primary", "hazards", "flags",
]


class ReportQuery:
    """
    The filters of both routes, validated once: `where` and `params` for the
    SQL, `order_by`, and `echo` — the filters as given, for the export's
    ledger row.
    """

    def __init__(
        self,
        date_from: Optional[str] = Query(None, alias="from", description="IST day or ISO 8601 timestamp"),
        date_to: Optional[str] = Query(None, alias="to", description="IST day (inclusive) or ISO 8601 timestamp"),
        time_field: str = Query("observed", description="observed (when it happened) or created (when received)"),
        source_type: Optional[str] = Query(None, description="Comma-separated source types"),
        platform: Optional[str] = Query(None, description="Comma-separated: mastodon, google_news"),
        publisher: Optional[str] = Query(None, max_length=200),
        state: Optional[str] = Query(None, max_length=120),
        district: Optional[str] = Query(None, max_length=120),
        precision: Optional[str] = Query(None, description="Comma-separated: gps, district, state, none"),
        status: Optional[str] = Query(None, description="Comma-separated: fused, duplicate, unfused, stale, held"),
        has_media: Optional[bool] = Query(None),
        language: Optional[str] = Query(None, description="Comma-separated language codes"),
        hazard: Optional[str] = Query(None, description="Comma-separated event types"),
        flag: Optional[str] = Query(None, description="Comma-separated misleading-text flags"),
        q: Optional[str] = Query(None, max_length=200, description="Text contains, any case"),
        sort: str = Query("observed_at:desc", description="observed_at, created_at or credibility, then :asc or :desc"),
    ):
        conditions: List[str] = []
        # STATUS_SQL reads it, in the select list and in ?status=.
        params: Dict[str, Any] = {"social_on": bool(get_settings().SOCIAL_CLUSTERING_ENABLED)}

        if time_field not in ("observed", "created"):
            raise invalid("time_field", "expected observed or created", time_field)
        time_col = "COALESCE(r.observed_at, r.created_at)" if time_field == "observed" else "r.created_at"
        start, stop = date_range(date_from, date_to)
        if start:
            conditions.append(f"{time_col} >= :from_ts")
            params["from_ts"] = start[0]
        if stop:
            conditions.append(f"{time_col} < :to_ts" if stop[1] else f"{time_col} <= :to_ts")
            params["to_ts"] = stop[0]

        sources = csv_values("source_type", source_type, [s.value for s in SourceType])
        if sources:
            conditions.append("CAST(r.source_type AS text) = ANY(CAST(:sources AS text[]))")
            params["sources"] = sources
        platforms = csv_values("platform", platform, PLATFORMS, normalise=str.lower)
        if platforms:
            conditions.append("r.platform = ANY(CAST(:platforms AS text[]))")
            params["platforms"] = platforms
        if publisher is not None and publisher.strip():
            conditions.append("lower(r.source_meta->>'publisher') = lower(:publisher)")
            params["publisher"] = publisher.strip()
        if state is not None and state.strip():
            conditions.append("lower(r.state) = lower(:state)")
            params["state"] = state.strip()
        if district is not None and district.strip():
            conditions.append("lower(r.district) = lower(:district)")
            params["district"] = district.strip()
        precisions = csv_values("precision", precision, PRECISIONS, normalise=str.lower)
        if precisions:
            conditions.append("COALESCE(r.place_precision, 'gps') = ANY(CAST(:precisions AS text[]))")
            params["precisions"] = precisions
        statuses = csv_values("status", status, STATUSES, normalise=str.lower)
        if statuses:
            conditions.append(f"({STATUS_SQL}) = ANY(CAST(:statuses AS text[]))")
            params["statuses"] = statuses
        if has_media is not None:
            conditions.append(f"({MEDIA_COUNT_SQL}) {'>' if has_media else '='} 0")
        if language is not None:
            languages = [v.strip().lower() for v in language.split(",") if v.strip()]
            bad = [v for v in languages if not _LANGUAGE_RE.match(v)]
            if bad or not languages:
                raise invalid("language", "expected language codes such as en, hi, hinglish", language)
            conditions.append(
                "COALESCE(r.source_meta->>'language', r.analysis->>'language') = ANY(CAST(:languages AS text[]))"
            )
            params["languages"] = languages
        hazards = csv_values("hazard", hazard, [t.value for t in EventType])
        if hazards:
            conditions.append(
                f"(r.citizen_hazard = ANY(CAST(:hazards AS text[])) "
                f"OR ({HAZARD_TYPES_SQL}) && CAST(:hazards AS text[]))"
            )
            params["hazards"] = hazards
        flags = csv_values("flag", flag, list(FLAGS), normalise=str.lower)
        if flags:
            conditions.append("r.flags && CAST(:flags AS text[])")
            params["flags"] = flags
        if q and q.strip():
            conditions.append("r.raw_text ILIKE :q ESCAPE '\\'")
            params["q"] = like_pattern(q.strip())

        field, _, direction = sort.partition(":")
        direction = (direction or "desc").lower()
        if field not in SORTS or direction not in ("asc", "desc"):
            raise invalid("sort", f"expected one of {sorted(SORTS)}, then :asc or :desc", sort)

        self.where = " AND ".join(conditions) if conditions else "TRUE"
        self.params = params
        self.order_by = f"{SORTS[field]} {direction.upper()} NULLS LAST, r.id {direction.upper()}"
        self.echo = {
            "from": date_from, "to": date_to, "time_field": time_field,
            "source_type": source_type, "platform": platform, "publisher": publisher,
            "state": state, "district": district, "precision": precision, "status": status,
            "has_media": has_media, "language": language, "hazard": hazard, "flag": flag, "q": q,
            "sort": sort,
        }


def _item(row) -> Dict[str, Any]:
    out = {c: exports.plain(row[c]) for c in COLUMNS}
    out["id"] = str(row["id"])
    out["duplicate_of"] = str(row["duplicate_of"]) if row["duplicate_of"] else None
    out["hazards"] = list(row["hazards"] or [])
    out["flags"] = list(row["flags"] or [])
    return out


@router.get("/search")
async def search_reports(
    response: Response,
    query: ReportQuery = Depends(),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(_analyst),
):
    """Reports matching the filters, newest first by default. Total in X-Total-Count."""
    sql = f"{SELECT_SQL} WHERE {query.where} ORDER BY {query.order_by} LIMIT :limit OFFSET :offset"
    try:
        rows = (await db.execute(text(sql), {**query.params, "limit": limit, "offset": offset})).mappings().all()
        if len(rows) < limit and (rows or offset == 0):
            total = offset + len(rows)
        else:
            total = (await db.execute(
                text(f"SELECT count(*) FROM raw_reports r WHERE {query.where}"), query.params
            )).scalar() or 0
    except Exception as e:
        # No fallback payload: an invented report in an analyst's search is the one
        # thing this route must never return.
        logger.warning(f"Database query failed in search_reports: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    response.headers["X-Total-Count"] = str(total)
    return [_item(r) for r in rows]


def _report_feature(row) -> Dict[str, Any]:
    props = _item(row)
    return {
        "type": "Feature",
        "id": props["id"],
        "geometry": exports.point_geometry(row["lat"], row["lng"]),
        "properties": props,
    }


@router.get("/export")
async def export_reports(
    format: str = Query("csv", description="csv or geojson"),
    query: ReportQuery = Depends(),
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(_analyst),
):
    """
    The search's selection, every row up to the cap, as CSV or GeoJSON. Writes
    one DATA_EXPORT ledger row first; a report with no place is a feature
    with a null geometry, as GeoJSON allows.
    """
    fmt = format.lower()
    if fmt not in exports.FORMATS:
        raise invalid("format", f"expected one of {list(exports.FORMATS)}", format)

    try:
        await exports.record_export(
            db, operator_id=operator.sub, kind="reports", fmt=fmt, filters=query.echo
        )
    except Exception as e:
        # An export the ledger cannot record does not happen.
        logger.warning(f"Export not audited, refused: {e}")
        raise HTTPException(status_code=503, detail="Export could not be recorded in the audit ledger")

    sql = f"{SELECT_SQL} WHERE {query.where} ORDER BY {query.order_by} LIMIT :row_cap"
    body = (
        exports.stream_csv(sql, query.params, COLUMNS)
        if fmt == "csv"
        else exports.stream_geojson(sql, query.params, _report_feature)
    )
    return StreamingResponse(
        body,
        media_type=exports.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{exports.filename("reports", fmt)}"'},
    )
