#!/usr/bin/env python3
"""
Delete stored media past its retention period (Phase 5 T5, DPDP Act 2023).

    backend/.venv/bin/python scripts/retention.py --dry-run
    backend/.venv/bin/python scripts/retention.py

Runs daily on the server from a systemd timer (docs/runbook). The policy,
published in the docs:

| what                                   | kept for                              |
|----------------------------------------|---------------------------------------|
| a citizen's original photo or video    | MEDIA_RETENTION_DAYS (90), **unless its report is in a HUMAN_APPROVED event** |
| the EXIF-free copy and thumbnail       | MEDIA_DERIVATIVE_RETENTION_DAYS (180) |
| a social post's private copy (T4)      | SOCIAL_MEDIA_RETENTION_DAYS (30)      |
| the hashes, EXIF fields and flags      | kept: they are what recycled-media detection compares against |
| media of a withdrawn report            | deleted at once (by the withdrawal; this run finishes any it could not) |

Only the files go. Each row keeps its hashes and is stamped
`original_deleted_at` / `derivatives_deleted_at`, so a signed URL for it
answers "no longer held" and nothing tries to serve it.

**Idempotent:** a row already stamped is not selected again, so a second run
deletes nothing. A store that is down fails the run with a non-zero exit, and
the next day's run picks up where it stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

BATCH = 500


async def run(dry_run: bool) -> int:
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import async_session
    from app.services import objectstore

    s = get_settings()
    bucket = s.S3_MEDIA_BUCKET
    plans = [
        (
            "citizen originals",
            "original_deleted_at",
            ["object_key"],
            f"""
                m.origin = 'citizen' AND m.original_deleted_at IS NULL AND m.object_key IS NOT NULL
                AND (
                      m.status = 'withdrawn'
                   OR (m.created_at < NOW() - make_interval(days => {int(s.MEDIA_RETENTION_DAYS)})
                       AND NOT EXISTS (
                           SELECT 1 FROM raw_reports r JOIN verified_events e ON e.id = r.event_id
                           WHERE r.id = m.report_id AND CAST(e.review_status AS text) = 'HUMAN_APPROVED'))
                )
            """,
        ),
        (
            "EXIF-free copies",
            "derivatives_deleted_at",
            ["derivative_key", "poster_key", "thumb_key"],
            f"""
                m.origin = 'citizen' AND m.derivatives_deleted_at IS NULL
                AND COALESCE(m.derivative_key, m.poster_key, m.thumb_key) IS NOT NULL
                AND (m.status = 'withdrawn'
                     OR m.created_at < NOW() - make_interval(days => {int(s.MEDIA_DERIVATIVE_RETENTION_DAYS)}))
            """,
        ),
        (
            "social copies",
            "original_deleted_at",
            ["object_key"],
            f"""
                m.origin = 'social' AND m.original_deleted_at IS NULL AND m.object_key IS NOT NULL
                AND m.created_at < NOW() - make_interval(days => {int(s.SOCIAL_MEDIA_RETENTION_DAYS)})
            """,
        ),
    ]

    failures = 0
    for label, stamp, columns, where in plans:
        async with async_session() as db:
            rows = (await db.execute(text(
                f"SELECT m.id, {', '.join('m.' + c for c in columns)} FROM report_media m "
                f"WHERE {where} ORDER BY m.created_at LIMIT {BATCH}"
            ))).fetchall()
        print(f"{label}: {len(rows)} past retention")
        if dry_run:
            continue
        deleted = 0
        for row in rows:
            media_id, keys = row[0], [k for k in row[1:] if k]
            try:
                for key in keys:
                    await objectstore.delete(bucket, key)
            except objectstore.ObjectStoreUnavailable as e:
                print(f"  object store unavailable, stopping: {e}", file=sys.stderr)
                failures += 1
                break
            async with async_session() as db:
                await db.execute(
                    text(f"UPDATE report_media SET {stamp} = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": str(media_id)},
                )
                await db.commit()
            deleted += 1
        print(f"  deleted {deleted}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
