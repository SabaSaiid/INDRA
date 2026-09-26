"""Generate and register the Phase 22 project-authored image dataset."""

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
from app.ml.data.synthetic_image import (
    SyntheticImageGeneratorConfig,
    register_synthetic_image_dataset,
    write_synthetic_image_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "labelled" / "image" / "synthetic_v1",
    )
    parser.add_argument("--train-images", type=int, default=70_000)
    parser.add_argument("--validation-images", type=int, default=15_000)
    parser.add_argument("--test-images", type=int, default=15_000)
    parser.add_argument("--seed", type=int, default=220022)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-registry-entry", action="store_true")
    args = parser.parse_args()
    config = SyntheticImageGeneratorConfig(
        train_images=args.train_images,
        validation_images=args.validation_images,
        test_images=args.test_images,
        seed=args.seed,
        generator_workers=args.workers,
    )
    artifacts = write_synthetic_image_dataset(
        args.output,
        config=config,
        overwrite=args.overwrite,
    )
    registered = register_synthetic_image_dataset(
        artifacts,
        config=config,
        registry_path=args.registry,
        replace_existing=args.replace_registry_entry,
    )
    print(
        json.dumps(
            {
                "dataset_directory": str(artifacts.output_directory),
                "dataset_size": artifacts.report.image_count,
                "split_counts": artifacts.report.split_counts,
                "label_distribution": artifacts.report.label_counts,
                "dataset_sha256": artifacts.dataset_hash,
                "split_sha256": artifacts.split_hashes,
                "generator_version": artifacts.report.generator_version,
                "registry_status": registered.status.value,
                "production_validation": "NOT_VALIDATED",
                "pretrained_models": [],
                "external_apis": [],
                "network_access": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
