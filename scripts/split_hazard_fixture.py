#!/usr/bin/env python3
"""
Freeze the dev/test split of the hazard tagger's fixture, once (Phase 3 T3).

    python3 scripts/split_hazard_fixture.py backend/tests/fixtures/hazards_v1.csv

Stratified by `group`: in each of the 18 groups (15 hazards and 3 kinds of
negative) the rows are shuffled with a fixed seed and 40% become `test`, the
rest `dev`. The rules are tuned on `dev` only; `test` is read once, when the
tagger is measured.

Refuses (exit 1, file untouched) if any row already has a split. The split is
committed before the first rule is written, the same discipline as
split_dataset.py, so a rule can never have been chosen by looking at the test
rows. Standard library only, so it runs anywhere.
"""

import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

TEST_SHARE = 0.40
SEED = 42


def main(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if any(r["split"] for r in rows):
        print(f"refusing: {path} already has a split; it is frozen", file=sys.stderr)
        return 1

    groups = defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r["id"])

    rng = random.Random(SEED)
    test_ids = set()
    for group in sorted(groups):
        ids = sorted(groups[group])
        rng.shuffle(ids)
        test_ids.update(ids[: round(len(ids) * TEST_SHARE)])

    for r in rows:
        r["split"] = "test" if r["id"] in test_ids else "dev"

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"{path}: {len(rows) - len(test_ids)} dev / {len(test_ids)} test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
