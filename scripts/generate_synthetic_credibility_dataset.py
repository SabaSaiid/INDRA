"""Generate and register the Phase 21 synthetic credibility benchmark."""

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
from app.ml.data.synthetic_credibility import (
    SyntheticCredibilityGeneratorConfig,
    register_synthetic_credibility_dataset,
    write_synthetic_credibility_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "data"
            / "labelled"
            / "credibility"
            / "synthetic_v1"
        ),
    )
    parser.add_argument("--reports-per-scenario", type=int, default=7_200)
    parser.add_argument("--seed", type=int, default=210021)
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-registry-entry", action="store_true")
    args = parser.parse_args()
    config = SyntheticCredibilityGeneratorConfig(
        reports_per_scenario=args.reports_per_scenario,
        seed=args.seed,
    )
    artifacts = write_synthetic_credibility_dataset(
        args.output,
        config=config,
        overwrite=args.overwrite,
    )
    registered = register_synthetic_credibility_dataset(
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
                "annotation_sha256": artifacts.annotation_hash,
                "report_count": artifacts.report.report_count,
                "label_distribution": artifacts.report.label_counts,
                "split_counts": artifacts.report.split_counts,
                "registry_status": registered.status.value,
                "semantic_target": "MISLEADING_RISK_EVIDENCE",
                "truth_probability": False,
                "production_validation": "NOT_VALIDATED",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
