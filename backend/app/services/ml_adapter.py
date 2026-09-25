"""Backend-owned I/O adapter for the frozen local AI/ML boundary.

Database reads and JSONB persistence stay here. The ML subsystem receives only
already-loaded typed values; media URLs are never fetched by inference.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.contracts import CandidateReport, ReportInput, StationObservation, UnifiedMLResult
from app.ml.inference.engine import InferenceEngine
from app.ml.inference.frozen_engine import (
    get_frozen_inference_engine,
    group_report_candidates,
)


STATION_HISTORY_LENGTH = 24
MAX_STATION_DISTANCE_METRES = 25_000


def build_report_input(
    stored: Mapping[str, Any],
    *,
    candidate_ids: Sequence[UUID] = (),
    candidates: Sequence[tuple[str, float, float, Any]] = (),
    station_observations: Sequence[StationObservation] = (),
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
) -> ReportInput:
    """Convert authoritative stored fields without inventing media or history."""

    if len(candidate_ids) != len(candidates):
        raise ValueError("candidate identities and values must align")
    source_type = stored.get("source_type") or "UNKNOWN_BACKEND_SOURCE"
    if hasattr(source_type, "value"):
        source_type = source_type.value
    metadata: dict[str, Any] = {}
    if image_mime_type is not None:
        metadata["image_mime_type"] = image_mime_type
    return ReportInput(
        report_id=stored["id"],
        text=stored["raw_text"],
        occurred_at=stored["created_at"],
        latitude=stored["latitude"],
        longitude=stored["longitude"],
        source_type=str(source_type),
        source_metadata=metadata,
        candidate_reports=[
            CandidateReport(
                report_id=report_id,
                text=value[0],
                latitude=value[1],
                longitude=value[2],
                occurred_at=value[3],
                source_type="BACKEND_CANDIDATE",
            )
            for report_id, value in zip(candidate_ids, candidates)
        ],
        station_observations=list(station_observations),
        image_bytes=image_bytes,
    )


def analyze_loaded_report(
    report: ReportInput, *, engine: InferenceEngine | None = None
) -> UnifiedMLResult:
    return (engine or get_frozen_inference_engine()).analyze(report)


async def load_station_observations(
    db: AsyncSession, stored: Mapping[str, Any]
) -> list[StationObservation]:
    """Use one nearby station's causal readings, never external weather APIs."""

    nearest = (
        await db.execute(
            text("""
                SELECT station_code
                FROM station_readings
                WHERE recorded_at <= CAST(:occurred_at AS timestamptz)
                  AND station_location IS NOT NULL
                  AND ST_DWithin(
                    station_location::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    :radius
                  )
                ORDER BY station_location <->
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    recorded_at DESC
                LIMIT 1
            """),
            {
                "occurred_at": stored["created_at"],
                "lng": stored["longitude"],
                "lat": stored["latitude"],
                "radius": MAX_STATION_DISTANCE_METRES,
            },
        )
    ).scalar_one_or_none()
    if nearest is None:
        return []
    rows = (
        await db.execute(
            text("""
                SELECT id, station_code, recorded_at, rainfall_mm, river_level_m
                FROM station_readings
                WHERE station_code = :station_code
                  AND recorded_at <= CAST(:occurred_at AS timestamptz)
                ORDER BY recorded_at DESC, id DESC
                LIMIT :limit
            """),
            {
                "station_code": nearest,
                "occurred_at": stored["created_at"],
                "limit": STATION_HISTORY_LENGTH,
            },
        )
    ).fetchall()
    return [
        StationObservation(
            station_id=row[1],
            observed_at=row[2],
            measurements={"rainfall_mm": row[3], "river_level_m": row[4]},
        )
        for row in reversed(rows)
    ]


async def analyze_stored_report(
    db: AsyncSession,
    stored: Mapping[str, Any],
    *,
    candidate_ids: Sequence[UUID] = (),
    candidates: Sequence[tuple[str, float, float, Any]] = (),
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
    engine: InferenceEngine | None = None,
) -> UnifiedMLResult:
    observations = await load_station_observations(db, stored)
    report = build_report_input(
        stored,
        candidate_ids=candidate_ids,
        candidates=candidates,
        station_observations=observations,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
    )
    result = await asyncio.to_thread(analyze_loaded_report, report, engine=engine)
    await db.execute(
        text("""
            UPDATE raw_reports
            SET analysis = jsonb_set(
                COALESCE(analysis, '{}'::jsonb),
                '{ml}',
                CAST(:ml_result AS jsonb),
                true
            )
            WHERE id = CAST(:report_id AS uuid)
        """),
        {"ml_result": result.model_dump_json(), "report_id": str(report.report_id)},
    )
    await db.commit()
    return result


async def analyze_stored_event_group(
    db: AsyncSession, report_ids: Sequence[UUID]
) -> dict[str, Any]:
    """Return advisory multi-report candidates from actual non-duplicate rows."""

    if not report_ids:
        return {"status": "DATA_UNAVAILABLE", "candidates": []}
    rows = (
        await db.execute(
            text("""
                SELECT id, raw_text, latitude, longitude, created_at, source_type
                FROM raw_reports
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND duplicate_of IS NULL
                ORDER BY created_at, id
            """),
            {"ids": [str(value) for value in report_ids]},
        )
    ).fetchall()
    reports = [
        build_report_input(
            {
                "id": row[0],
                "raw_text": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "created_at": row[4],
                "source_type": row[5],
            }
        )
        for row in rows
    ]
    result = await asyncio.to_thread(group_report_candidates, reports)
    return result.model_dump(mode="json")


__all__ = [
    "analyze_loaded_report",
    "analyze_stored_event_group",
    "analyze_stored_report",
    "build_report_input",
    "load_station_observations",
]
