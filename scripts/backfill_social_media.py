#!/usr/bin/env python3
"""
Hash every Mastodon image INDRA has collected since Phase 2 (Phase 5 T4).

    backend/.venv/bin/python scripts/backfill_social_media.py --dry-run
    backend/.venv/bin/python scripts/backfill_social_media.py --limit 200
    backend/.venv/bin/python scripts/backfill_social_media.py --images-only

The poller has kept each post's attachment URLs in `source_meta.media` since
24 Sep. This runs each post that has attachments through the media worker's
own `process_social_post`: download (images up to 10 MB; a video's preview,
and the video if 50 MB or less, unless `--images-only`), SHA-256, perceptual
hash, EXIF, and the recycled-media rules. The copies are private, used only
for hashing, and deleted after 30 days by scripts/retention.py; the hashes
stay, which is what lets INDRA say "this photo first appeared on Mastodon on
23 Sep".

* **Idempotent.** An attachment that already has a row, whatever happened to
  it, is never fetched again, so a second run downloads nothing.
* **A good client.** One post at a time, with --delay seconds between posts.
* **Bounded by disk:** images only is the plan's setting for the backfill
  (--images-only); check `df -h /` before a run without it.
* Oldest first, so the recycled index is built in the order images appeared.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


async def run(dry_run: bool, limit: int | None, delay: float, images_only: bool) -> int:
    import httpx
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import async_session
    from app.workers import media_worker

    async with async_session() as db:
        rows = (await db.execute(text(
            """
            SELECT r.id FROM raw_reports r
            WHERE CAST(r.source_type AS text) = 'SOCIAL_MEDIA'
              AND jsonb_typeof(r.source_meta->'media') = 'array'
              AND jsonb_array_length(r.source_meta->'media') > 0
              AND NOT EXISTS (SELECT 1 FROM report_media m WHERE m.report_id = r.id)
            ORDER BY COALESCE(r.observed_at, r.created_at), r.id
            """
            + (f" LIMIT {int(limit)}" if limit else "")
        ))).fetchall()
    print(f"{len(rows)} post(s) with attachments not yet hashed")
    if dry_run:
        return 0

    if images_only:
        # The plan's backfill setting: no video is downloaded, only its preview image.
        original = media_worker.social_attachments
        media_worker.social_attachments = lambda meta: [a for a in original(meta) if a["kind"] == "image"]

    totals = {"downloaded": 0, "skipped": 0, "failed": 0}
    s = get_settings()
    async with httpx.AsyncClient(
        timeout=s.MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": "INDRA-SIH2026/1.0 (Team Sixth Sense; recycled-media backfill)"},
    ) as client:
        for i, (report_id,) in enumerate(rows, 1):
            counts = await media_worker.process_social_post(str(report_id), client=client)
            for k, v in counts.items():
                totals[k] += v
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}: {totals}")
            if delay:
                await asyncio.sleep(delay)

    print(f"done: {totals['downloaded']} hashed, {totals['skipped']} skipped with a reason, "
          f"{totals['failed']} failed (retried on the next run)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, download nothing")
    parser.add_argument("--limit", type=int, default=None, help="at most this many posts")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between posts (default 1)")
    parser.add_argument("--images-only", action="store_true", help="never download a video, only its preview")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run, args.limit, args.delay, args.images_only))


if __name__ == "__main__":
    sys.exit(main())
