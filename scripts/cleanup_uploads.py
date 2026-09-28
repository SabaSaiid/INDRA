#!/usr/bin/env python3
"""
Abort photo and video uploads abandoned half-way (Phase 5 T1, webpage.MD §8.3).

    backend/.venv/bin/python scripts/cleanup_uploads.py --dry-run
    backend/.venv/bin/python scripts/cleanup_uploads.py

Runs daily on the server from a systemd timer (infra/systemd/). An upload session still
`uploading` more than MEDIA_WINDOW_HOURS (24) after it started can never
finish — the media window is shut — so its multipart upload is aborted in the
object store, which frees every part it received, and its row is marked
`rejected` with the reason `abandoned`.

Idempotent: a second run finds nothing. A store that is down leaves the rows
as they are and exits non-zero; the next run tries again.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


async def run(dry_run: bool) -> int:
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import async_session
    from app.services import objectstore

    s = get_settings()
    async with async_session() as db:
        rows = (await db.execute(
            text("""
                SELECT id, incoming_key, s3_upload_id FROM report_media
                WHERE status = 'uploading' AND origin = 'citizen'
                  AND created_at < NOW() - make_interval(hours => CAST(:hours AS int))
                ORDER BY created_at
            """),
            {"hours": s.MEDIA_WINDOW_HOURS},
        )).fetchall()
    print(f"{len(rows)} abandoned upload(s)")
    if dry_run:
        return 0

    aborted = 0
    for media_id, key, upload_id in rows:
        if key and upload_id:
            try:
                await objectstore.abort_multipart(s.S3_MEDIA_BUCKET, key, upload_id)
            except objectstore.ObjectStoreUnavailable as e:
                print(f"object store unavailable, stopping: {e}", file=sys.stderr)
                return 1
        async with async_session() as db:
            await db.execute(
                text("UPDATE report_media SET status = 'rejected', reason = 'abandoned', processed_at = NOW() "
                     "WHERE id = CAST(:id AS uuid) AND status = 'uploading'"),
                {"id": str(media_id)},
            )
            await db.commit()
        aborted += 1
    print(f"aborted {aborted}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
