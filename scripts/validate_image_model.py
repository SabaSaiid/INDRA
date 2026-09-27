"""Freeze or finalize the isolated Phase 22 image-model validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH
from app.ml.training.image_synthetic_validation import (
    ARTIFACT_ROOT,
    DEFAULT_ARTIFACT_MANIFEST_PATH,
    DEFAULT_DATASET_ROOT,
    finalize_image_evaluation,
    freeze_image_development,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "finalize"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument(
        "--artifact-manifest", type=Path, default=DEFAULT_ARTIFACT_MANIFEST_PATH
    )
    args = parser.parse_args()
    kwargs = {
        "registry_path": args.registry,
        "dataset_root": args.dataset,
        "output_directory": args.output,
        "artifact_manifest_path": args.artifact_manifest,
    }
    result = (
        freeze_image_development(**kwargs)
        if args.action == "freeze"
        else finalize_image_evaluation(**kwargs)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
