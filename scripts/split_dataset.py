#!/usr/bin/env python3
"""
Freeze the train/test split of a labelled report dataset, once.

    backend/.venv/bin/python scripts/split_dataset.py data/labelled/reports_v1.csv

Stratified by event_type, test_size=0.30, random_state=42, written into the
`split` column. Refuses (exit 1, file untouched) if any row already has a
split: the test set must be fixed before any model sees it, and regenerating
it after training would let model choices leak into the test set.
"""

import csv
import sys
from pathlib import Path

from sklearn.model_selection import train_test_split

TEST_SIZE = 0.30
RANDOM_STATE = 42


def main(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if any(r["split"] for r in rows):
        print(f"refusing: {path} already has a split column set; the split is frozen", file=sys.stderr)
        return 1

    ids = [r["id"] for r in rows]
    labels = [r["event_type"] for r in rows]
    _, test_ids = train_test_split(
        ids, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=labels
    )
    test_ids = set(test_ids)
    for r in rows:
        r["split"] = "test" if r["id"] in test_ids else "train"

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"{path}: {len(rows) - len(test_ids)} train / {len(test_ids)} test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
