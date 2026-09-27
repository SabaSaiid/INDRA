#!/usr/bin/env python3
"""
Draw the 100 real posts the hazard tagger is measured on (Phase 3 T3 part 4).

    backend/.venv/bin/python scripts/sample_real_posts.py            # on the server
    backend/.venv/bin/python scripts/sample_real_posts.py --out /tmp/sample.csv

Writes `backend/tests/fixtures/hazards_real_v1.csv` with the `hazards` and
`tense` columns **empty**: a person labels each row by hand, following the
rules in `hazards_v1.md`, and only then does `measure_hazard_tagger.py` score
the tagger on it. The labeller must not look at what the tagger says first.

**The sample is stratified, so it is not all stale English headlines.** What
the servers collected from 24 Sep is mostly English news, half of it placed
nowhere, so a plain random draw would measure the tagger on one kind of text:

    50 Mastodon posts + 50 news items (Google News)
    at least 30 in Hindi (Devanagari), spread over both
    up to 5 non-India #flood posts (US National Weather Service warnings),
      which must come out untagged or placed nowhere
    up to 5 Vietnam.vn items with "लू" in them (BUG-088), which must come out
      untagged

Within each stratum rows are drawn with a fixed seed from rows ordered by id,
so the same database gives the same sample. Refuses to overwrite a file that
already has a label in it: that labelling is an hour of someone's work.

**Privacy.** Only the post's text is written, with @mentions replaced by
"@user": no author, no handle, no link to the post. These are public posts,
but the file lives in the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import random
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_OUT = REPO_ROOT / "backend" / "tests" / "fixtures" / "hazards_real_v1.csv"
# The server started collecting at 19:41 IST on 24 Sep 2026.
DEFAULT_SINCE = "2026-09-24T14:11:00+00:00"
SEED = 24092026

PER_SOURCE = 50
MIN_HINDI = 30
MAX_NWS = 5
MAX_VIETNAM = 5

COLUMNS = ["id", "report_id", "source_type", "publisher", "language", "stratum", "text", "hazards", "tense",
           "notes"]
_MENTION_RE = re.compile(r"@[\w.]+(?:@[\w.-]+)?")

QUERY = """
    SELECT id, CAST(source_type AS text), platform,
           source_meta->>'publisher',
           COALESCE(source_meta->>'language', analysis->>'language'),
           raw_text,
           COALESCE(source_meta->>'url', '')
    FROM raw_reports
    WHERE CAST(source_type AS text) IN ('SOCIAL_MEDIA', 'NEWS_MEDIA')
      AND duplicate_of IS NULL
      AND created_at >= CAST(:since AS timestamptz)
    ORDER BY id
"""


def _is_hindi(row) -> bool:
    return (row["language"] or "").startswith("hi") and re.search(r"[ऀ-ॿ]", row["text"] or "") is not None


def _is_nws(row) -> bool:
    text = (row["text"] or "").lower()
    return "national weather service" in text or re.search(r"\bnws\b", text) is not None


def _is_vietnam(row) -> bool:
    where = f"{row['publisher'] or ''} {row['url'] or ''}".lower()
    return "vietnam" in where and "लू" in (row["text"] or "")


def draw(rows, rng: random.Random):
    """The stratified sample: (row, stratum) pairs, 50 per source at most."""
    by_source = {
        "SOCIAL_MEDIA": [r for r in rows if r["source_type"] == "SOCIAL_MEDIA"],
        "NEWS_MEDIA": [r for r in rows if r["source_type"] == "NEWS_MEDIA"],
    }
    chosen, taken = [], set()

    def take(pool, n, stratum, source):
        pool = [r for r in pool if r["id"] not in taken]
        rng.shuffle(pool)
        room = PER_SOURCE - sum(1 for _, _, s in chosen if s == source)
        for r in pool[: max(0, min(n, room))]:
            chosen.append((r, stratum, source))
            taken.add(r["id"])

    take([r for r in by_source["SOCIAL_MEDIA"] if _is_nws(r)], MAX_NWS, "non_india_flood", "SOCIAL_MEDIA")
    take([r for r in by_source["NEWS_MEDIA"] if _is_vietnam(r)], MAX_VIETNAM, "vietnam_lu", "NEWS_MEDIA")
    for source in by_source:
        take([r for r in by_source[source] if _is_hindi(r)], MIN_HINDI // 2, "hindi", source)
    hindi = sum(1 for r, _, _ in chosen if _is_hindi(r))
    if hindi < MIN_HINDI:
        for source in by_source:
            take([r for r in by_source[source] if _is_hindi(r)], MIN_HINDI - hindi, "hindi", source)
    for source in by_source:
        take(by_source[source], PER_SOURCE, "random", source)
    return [(r, stratum) for r, stratum, _ in chosen]


async def _fetch(since: str):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            # asyncpg binds a timestamptz from a datetime, never from a string.
            result = await conn.execute(text(QUERY), {"since": datetime.fromisoformat(since)})
            return [
                {"id": str(r[0]), "source_type": r[1], "platform": r[2], "publisher": r[3], "language": r[4],
                 "text": r[5], "url": r[6]}
                for r in result.fetchall()
            ]
    finally:
        await engine.dispose()


def _already_labelled(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8", newline="") as f:
        return any(row.get("hazards") or row.get("tense") or row.get("notes") for row in csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--since", default=DEFAULT_SINCE, help="collected at or after (ISO 8601)")
    args = parser.parse_args()

    if _already_labelled(args.out):
        print(f"refusing: {args.out} already has labels in it", file=sys.stderr)
        return 1

    rows = asyncio.run(_fetch(args.since))
    sample = draw(rows, random.Random(SEED))
    if len(sample) < 2 * PER_SOURCE:
        print(f"warning: only {len(sample)} rows available since {args.since}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for i, (r, stratum) in enumerate(sample, start=1):
            writer.writerow({
                "id": f"p{i:03d}",
                "report_id": r["id"],
                "source_type": r["source_type"],
                "publisher": r["publisher"] or "",
                "language": r["language"] or "",
                "stratum": stratum,
                "text": _MENTION_RE.sub("@user", " ".join((r["text"] or "").split())),
                "hazards": "",
                "tense": "",
                "notes": "",
            })

    hindi = sum(1 for r, _ in sample if _is_hindi(r))
    by_stratum = {}
    for _, stratum in sample:
        by_stratum[stratum] = by_stratum.get(stratum, 0) + 1
    print(f"{args.out}: {len(sample)} rows from {len(rows)} candidates; {hindi} in Hindi; {by_stratum}")
    print("Now label the hazards and tense columns by hand, before running measure_hazard_tagger.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
