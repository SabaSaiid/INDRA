"""Policy-gated anomaly-detector training entry point.

Phase 9 has no validated anomaly ground-truth dataset. This command therefore
returns an explicit blocked state and never constructs or writes an artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.ml.components.anomaly_detection import AnomalyDetector
from app.ml.contracts import AnomalyTrainingResult
from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH, DatasetComponent
from app.ml.training.dataset_gate import require_training_dataset


def train_anomaly_detector(
    dataset_id: str | None = None,
    *,
    dataset_version: str | None = None,
    registry_path: Path | None = None,
) -> AnomalyTrainingResult:
    """Return the honest no-dataset state without fitting a learned model."""

    if dataset_id is not None:
        require_training_dataset(
            dataset_id,
            DatasetComponent.ANOMALY,
            dataset_version=dataset_version,
            registry_path=registry_path or DEFAULT_DATASET_REGISTRY_PATH,
        )
    return AnomalyDetector().fit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Policy-gated local anomaly training")
    parser.add_argument("--dataset-id")
    parser.add_argument("--dataset-version")
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    args = parser.parse_args(argv)
    result = train_anomaly_detector(
        args.dataset_id,
        dataset_version=args.dataset_version,
        registry_path=args.registry,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["train_anomaly_detector"]
