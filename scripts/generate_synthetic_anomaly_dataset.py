"""Generate and register the Phase 23 project-authored anomaly dataset."""

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
from app.ml.data.synthetic_anomaly.generator import (
    SyntheticAnomalyGeneratorConfig,
    generate_synthetic_anomaly_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "data/labelled/anomaly/synthetic_v1",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--train", type=int, default=70_000)
    parser.add_argument("--validation", type=int, default=15_000)
    parser.add_argument("--test", type=int, default=15_000)
    parser.add_argument("--seed", type=int, default=230023)
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()
    config = SyntheticAnomalyGeneratorConfig(
        seed=args.seed,
        train_count=args.train,
        validation_count=args.validation,
        test_count=args.test,
    )
    dataset = generate_synthetic_anomaly_dataset(
        args.output,
        config=config,
        registry_path=args.registry,
        register=not args.no_register,
    )
    manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "dataset_directory": str(dataset.output_directory),
                "dataset_size": sum(dataset.split_counts.values()),
                "split_counts": dataset.split_counts,
                "label_distribution": manifest["label_distribution"],
                "dataset_sha256": dataset.dataset_sha256,
                "split_sha256": dataset.split_sha256,
                "generator_version": manifest["generator_version"],
                "production_validation": "NOT_VALIDATED",
                "pretrained_models": [],
                "open_weight_models": [],
                "external_apis": [],
                "network_access": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
