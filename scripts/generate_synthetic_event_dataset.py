"""Generate and register the Phase 20 local synthetic event benchmark."""

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
from app.ml.data.synthetic_event import (
    SyntheticEventGeneratorConfig,
    register_synthetic_event_dataset,
    write_synthetic_event_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "labelled" / "events" / "synthetic_v1",
    )
    parser.add_argument("--batches-per-scenario", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=200020)
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-registry-entry", action="store_true")
    args = parser.parse_args()
    config = SyntheticEventGeneratorConfig(
        batches_per_scenario=args.batches_per_scenario,
        seed=args.seed,
    )
    artifacts = write_synthetic_event_dataset(
        args.output,
        config=config,
        overwrite=args.overwrite,
    )
    registered = register_synthetic_event_dataset(
        artifacts,
        config=config,
        registry_path=args.registry,
        replace_existing=args.replace_registry_entry,
    )
    print(
        json.dumps(
            {
                "dataset_directory": str(artifacts.output_directory),
                "dataset_sha256": artifacts.dataset_hash,
                "split_sha256": artifacts.split_hash,
                "report_count": artifacts.report.report_count,
                "canonical_event_count": artifacts.report.canonical_event_count,
                "pair_count": artifacts.report.pair_count,
                "registry_status": registered.status.value,
                "production_validation": "NOT_VALIDATED",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
