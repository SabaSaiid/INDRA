"""Policy-gated duplicate training placeholder; no model is fitted in Phase 13."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH, DatasetComponent
from app.ml.training.base import not_implemented_result
from app.ml.training.dataset_gate import require_training_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Policy-gated local duplicate training"
    )
    parser.add_argument("--dataset-id")
    parser.add_argument("--dataset-version")
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    args = parser.parse_args(argv)
    if args.dataset_id:
        require_training_dataset(
            args.dataset_id,
            DatasetComponent.DUPLICATE,
            dataset_version=args.dataset_version,
            registry_path=args.registry,
        )
    print(not_implemented_result("duplicate_matcher").message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
