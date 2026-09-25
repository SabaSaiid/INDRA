#!/usr/bin/env python3
"""
Export everything the live stack has collected into `data/live/`, in formats you
can open by hand.

    python scripts/export_live_data.py

Writes, all under `data/live/`:

    indra_live.db       SQLite — open with `sqlite3`, DB Browser, or DBeaver
    *.csv               one file per table, opens in Excel or Numbers
    agency_alerts.geojson   the SACHET warning footprints, drag onto geojson.io
    verified_events.geojson the events INDRA verified, same
    export_log.txt      a plain-text summary of what was exported and when

A .geojson is written only when at least one row has a polygon; when none has,
the file from an earlier export is removed rather than left behind.

**Why this exists.** The real data lives in Postgres inside a Docker container,
which means checking what the platform actually holds needs a `docker exec` and
some SQL. That is a bad way to answer "is this real?" during a demo rehearsal,
and an impossible way to answer it afterwards when the container is gone. A
SQLite file and a pile of CSVs can be opened on any machine, months later, with
no stack running at all.

**This is an export, not a source of truth.** Nothing reads these files back
into the platform. They are a snapshot of Postgres at the moment you ran the
command, and the header of `export_log.txt` records that moment. Re-run it and
the snapshot is replaced.

Nothing is invented here. A table with no rows exports as a CSV containing only
its header, and `export_log.txt` says `0 rows` beside it — which is the honest
answer on a stack that has just started.

Credentials are never exported: `user_profiles.password_hash` stays in Postgres.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

OUT_DIR = REPO_ROOT / "data" / "live"

# Tables worth exporting, with the geometry column (if any) rendered as GeoJSON
# rather than the raw WKB that would otherwise land in the CSV as unreadable hex.
TABLES = {
    "raw_reports": None,
    "verified_events": "boundary_polygon",
    "agency_alerts": "area_polygon",
    "station_readings": "station_location",
    "audit_logs": None,
    "user_profiles": None,
    "teams": None,
}

# Tables that also get a .geojson, with the columns to carry as feature properties.
GEOJSON = {
    "agency_alerts": ("area_polygon", ["identifier", "sender", "event", "severity", "headline", "area_desc", "expires_at"]),
    "verified_events": ("boundary_polygon", ["event_code", "event_type", "severity", "confidence_score", "review_status", "report_count"]),
}

# Columns left out of every file. data/live is committed, and a bcrypt hash in
# git can be attacked offline for as long as the repository exists.
EXCLUDED_COLUMNS = {
    "user_profiles": {"password_hash"},
}


async def fetch_all(engine, table: str, geom_col: str | None):
    """Every row of one table, with geometry as GeoJSON text and a WKT-free copy."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        cols = [
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t ORDER BY ordinal_position"
                    ),
                    {"t": table},
                )
            ).all()
            if r[0] not in EXCLUDED_COLUMNS.get(table, ())
        ]
        if not cols:
            return [], []

        # Geometry columns come back as binary WKB, which is useless in a CSV.
        # ST_AsGeoJSON keeps them readable and re-usable.
        select_parts = []
        for c in cols:
            if c == geom_col:
                select_parts.append(f"ST_AsGeoJSON({c}) AS {c}")
            else:
                select_parts.append(c)

        rows = (
            await conn.execute(text(f"SELECT {', '.join(select_parts)} FROM {table}"))
        ).mappings().all()
        return cols, [dict(r) for r in rows]


def _cell(value):
    """Everything becomes a string a spreadsheet can show, without losing meaning."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_csv(table: str, cols: list[str], rows: list[dict]) -> Path:
    path = OUT_DIR / f"{table}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        for row in rows:
            writer.writerow([_cell(row.get(c)) for c in cols])
    return path


def write_sqlite(conn: sqlite3.Connection, table: str, cols: list[str], rows: list[dict]) -> None:
    quoted = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(f'CREATE TABLE "{table}" ({quoted})')
    if rows:
        placeholders = ", ".join("?" for _ in cols)
        conn.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',
            [[_cell(r.get(c)) for c in cols] for r in rows],
        )


def write_geojson(table: str, geom_col: str, props: list[str], rows: list[dict]) -> Path | None:
    features = []
    for row in rows:
        raw = row.get(geom_col)
        if not raw:
            continue
        try:
            geometry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {p: _cell(row.get(p)) for p in props if p in row},
            }
        )
    path = OUT_DIR / f"{table}.geojson"
    if not features:
        # A stale file from an earlier export would still map rows that are gone.
        path.unlink(missing_ok=True)
        return None
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return path


async def main() -> int:
    from app.core.config import get_settings
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    started = datetime.now(timezone.utc)
    lines: list[str] = []
    db_path = OUT_DIR / "indra_live.db"
    sqlite_conn = sqlite3.connect(db_path)

    total = 0
    try:
        for table, geom_col in TABLES.items():
            try:
                cols, rows = await fetch_all(engine, table, geom_col)
            except Exception as e:
                lines.append(f"  {table:<20} FAILED  {type(e).__name__}: {e}")
                continue
            if not cols:
                lines.append(f"  {table:<20} (no such table)")
                continue

            write_csv(table, cols, rows)
            write_sqlite(sqlite_conn, table, cols, rows)
            total += len(rows)
            note = ""
            if table in GEOJSON:
                gcol, props = GEOJSON[table]
                written = write_geojson(table, gcol, props, rows)
                note = f"  → {written.name}" if written else "  (no geometry to map)"
            lines.append(f"  {table:<20} {len(rows):>6} rows{note}")
        sqlite_conn.commit()
    finally:
        sqlite_conn.close()
        await engine.dispose()

    header = (
        "INDRA — live data export\n"
        f"Taken at   : {started.isoformat()}\n"
        f"Source     : {settings.DATABASE_URL.split('@')[-1]}\n"
        f"Total rows : {total}\n"
        "\n"
        "This is a snapshot of the source database at that moment. Rows are\n"
        "exported exactly as stored, so they are only as real as that database;\n"
        "user_profiles holds the login accounts migration 0008 seeds. A table\n"
        "showing 0 rows had no rows. Nothing reads these files back into the\n"
        "platform.\n"
        "\n"
        "Open indra_live.db with `sqlite3 data/live/indra_live.db`, the CSVs with\n"
        "any spreadsheet, and the .geojson files by dragging them onto geojson.io.\n"
        "\n"
        "Tables\n"
    )
    log_path = OUT_DIR / "export_log.txt"
    log_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

    print(header + "\n".join(lines))
    print(f"\nWritten to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
