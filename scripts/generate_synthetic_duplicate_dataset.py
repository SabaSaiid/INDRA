"""Generate and register the Phase 19 local synthetic duplicate corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH  # noqa: E402
from app.ml.data.synthetic_duplicates import (  # noqa: E402
    SyntheticDuplicateGeneratorConfig,
    register_synthetic_duplicate_dataset,
    write_synthetic_duplicate_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "labelled"
        / "duplicates"
        / "synthetic_v1",
    )
    parser.add_argument("--pairs", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=190019)
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-registry-entry", action="store_true")
    args = parser.parse_args()

    config = SyntheticDuplicateGeneratorConfig(
        total_pairs=args.pairs,
        seed=args.seed,
    )
    artifacts = write_synthetic_duplicate_dataset(
        args.output,
        config=config,
        overwrite=args.overwrite,
    )
    registered = register_synthetic_duplicate_dataset(
        artifacts,
        config=config,
        registry_path=args.registry,
        replace_existing=args.replace_registry_entry,
    )
    print(
        json.dumps(
            {
                "dataset_path": str(artifacts.dataset_path),
                "dataset_sha256": artifacts.dataset_hash,
                "quality_report_path": str(artifacts.report_path),
                "manifest_path": str(artifacts.manifest_path),
                "registry_status": registered.status.value,
                "production_validation": "NOT_VALIDATED",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
