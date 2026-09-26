"""Policy-gated image training entry point.

There is no validated image dataset in Phase 8, so this command always returns
the explicit blocked state and creates no artifact.  The provenance field list
documents what a future project-controlled training run must record.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.ml.components.image_analysis import ImageAnalyzer
from app.ml.contracts import ImageTrainingResult
from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH, DatasetComponent
from app.ml.training.dataset_gate import require_training_dataset


def train_image_analyzer(
    dataset_id: str | None = None,
    *,
    dataset_version: str | None = None,
    registry_path: Path | None = None,
) -> ImageTrainingResult:
    """Return the honest no-dataset state without constructing a model."""

    if dataset_id is not None:
        require_training_dataset(
            dataset_id,
            DatasetComponent.IMAGE,
            dataset_version=dataset_version,
            registry_path=registry_path or DEFAULT_DATASET_REGISTRY_PATH,
        )
    return ImageAnalyzer().fit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Policy-gated local image training")
    parser.add_argument("--dataset-id")
    parser.add_argument("--dataset-version")
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    args = parser.parse_args(argv)
    result = train_image_analyzer(
        args.dataset_id,
        dataset_version=args.dataset_version,
        registry_path=args.registry,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["train_image_analyzer"]
