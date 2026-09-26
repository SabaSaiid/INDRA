#!/usr/bin/env python3
"""Generate and register INDRA's project-authored synthetic NLP corpus.

This command is local-only. It does not import a model, call an API, access the
network, or use NLP v2 to assign labels. Labels come directly from structured
generator scenarios.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH
from app.ml.data.synthetic_nlp import (
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_VERSION,
    DEFAULT_SEED,
    DEFAULT_TOTAL_ROWS,
    SyntheticNLPGeneratorConfig,
    register_synthetic_nlp_dataset,
    write_synthetic_nlp_dataset,
)

DEFAULT_OUTPUT_DIRECTORY = (
    REPOSITORY_ROOT / "data" / "labelled" / "nlp" / "synthetic_v1"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate, validate, hash, and optionally register a reproducible "
            "development-only synthetic NLP dataset."
        )
    )
    parser.add_argument("--size", type=int, default=DEFAULT_TOTAL_ROWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_DATASET_REGISTRY_PATH,
    )
    parser.add_argument(
        "--register",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="register and structurally validate the generated corpus",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace only the four deterministic generated output artifacts",
    )
    parser.add_argument(
        "--replace-registry-entry",
        action="store_true",
        help="replace the same dataset identity before revalidation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SyntheticNLPGeneratorConfig(
        total_rows=args.size,
        seed=args.seed,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
    )
    artifacts = write_synthetic_nlp_dataset(
        args.output_dir,
        config=config,
        overwrite=args.overwrite,
    )
    registry_status = "NOT_REGISTERED"
    if args.register:
        registered = register_synthetic_nlp_dataset(
            artifacts,
            config=config,
            registry_path=args.registry,
            replace_existing=args.replace_registry_entry,
        )
        registry_status = registered.status.value

    report = artifacts.report
    print("PHASE=17 — SYNTHETIC NLP DATASET")
    print(f"DATASET_SIZE={report.total_rows}")
    print(f"TRAIN={report.rows_per_split['train']}")
    print(f"VALIDATION={report.rows_per_split['validation']}")
    print(f"TEST={report.rows_per_split['test']}")
    print(f"HARD_NEGATIVES={report.hard_negative_rows}")
    print(f"LEAKAGE={report.leakage_results.status}")
    print(f"DATASET_HASH={artifacts.dataset_hash}")
    print(f"GENERATOR_VERSION={report.generator_version}")
    print(f"SEED={report.seed}")
    print(f"REGISTRY_STATUS={registry_status}")
    print("PROVENANCE=PROJECT_AUTHORED")
    print("CLASSIFICATION=SYNTHETIC / DEVELOPMENT_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
