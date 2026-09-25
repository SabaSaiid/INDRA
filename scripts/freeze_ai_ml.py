"""Create the immutable Phase 24 six-component AI/ML freeze manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.final_freeze import (
    DEFAULT_FINAL_FREEZE_PATH,
    write_final_freeze_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only Phase 24 forensic audits and create the final "
            "manifest exactly once. This command never trains or evaluates a "
            "protected final-test split."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_FINAL_FREEZE_PATH)
    parser.add_argument("--tests-passed", type=int, required=True)
    parser.add_argument("--tests-failed", type=int, default=0)
    parser.add_argument("--tests-skipped", type=int, default=0)
    parser.add_argument("--warnings", type=int, default=0)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument(
        "--pytest-command",
        default="python -m pytest app/ml/tests",
    )
    args = parser.parse_args()
    if args.tests_passed < 0 or args.tests_failed < 0 or args.tests_skipped < 0:
        parser.error("test counts must be non-negative")
    if args.warnings < 0:
        parser.error("warning count must be non-negative")
    if args.tests_failed:
        parser.error("a final freeze requires a passing AI/ML regression suite")
    regression = {
        "status": "PASS",
        "command": args.pytest_command,
        "passed": args.tests_passed,
        "failed": args.tests_failed,
        "skipped": args.tests_skipped,
        "warnings": args.warnings,
        "duration_seconds": args.duration_seconds,
        "protected_final_test_evaluations_rerun": False,
        "scope": "COMPLETE_AI_ML_TEST_SUITE",
    }
    manifest = write_final_freeze_manifest(
        args.output,
        test_regression=regression,
    )
    summary = {
        "output": str(args.output.resolve()),
        "freeze_version": manifest["freeze_version"],
        "frozen_at": manifest["frozen_at"],
        "components": manifest["component_count"],
        "artifact_hash_audit": manifest["artifact_hash_audit"]["status"],
        "receipt_audit": manifest["protected_test_receipt_audit"]["status"],
        "leakage_audit": manifest["global_data_leakage_audit"]["status"],
        "artifact_reproducibility": manifest["artifact_reproducibility_audit"][
            "status"
        ],
        "network_isolation": manifest["network_isolation_audit"]["status"],
        "production_validation": manifest["global_final_status"][
            "PRODUCTION_VALIDATION"
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
