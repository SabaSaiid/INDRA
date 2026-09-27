"""Freeze and finalize the isolated Phase 19 duplicate validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH  # noqa: E402
from app.ml.training.duplicate_validation import (  # noqa: E402
    ARTIFACT_ROOT,
    DEFAULT_ARTIFACT_MANIFEST_PATH,
    finalize_duplicate_matcher_evaluation,
    freeze_duplicate_matcher_development,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "finalize"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument(
        "--artifact-manifest", type=Path, default=DEFAULT_ARTIFACT_MANIFEST_PATH
    )
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze_duplicate_matcher_development(
            registry_path=args.registry,
            output_directory=args.output,
            artifact_manifest_path=args.artifact_manifest,
        )
    else:
        result = finalize_duplicate_matcher_evaluation(
            registry_path=args.registry,
            output_directory=args.output,
            artifact_manifest_path=args.artifact_manifest,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
