"""Run the new Phase 20R event evidence sequence; never rerun old Phase 20."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ml.evaluation.phase20r_event import evaluate_test_once, prepare


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "evaluate-once"))
    args = parser.parse_args()
    result = prepare() if args.stage == "prepare" else evaluate_test_once()
    print(json.dumps({key: result[key] for key in ("status", "production_validation")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
