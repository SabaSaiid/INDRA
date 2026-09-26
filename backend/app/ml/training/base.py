"""Shared training status types; no training occurs in Phase 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TRAINING_NOT_IMPLEMENTED = "TRAINING_NOT_IMPLEMENTED"


@dataclass(frozen=True)
class TrainingContext:
    dataset_identifier: str
    dataset_hash: str
    feature_version: str
    preprocessing_version: str
    random_seed: int
    configuration: dict[str, Any]


@dataclass(frozen=True)
class TrainingResult:
    status: str
    message: str
    artifact_path: str | None = None
    metrics: dict[str, Any] | None = None


def not_implemented_result(component: str) -> TrainingResult:
    return TrainingResult(
        status=TRAINING_NOT_IMPLEMENTED,
        message=f"{TRAINING_NOT_IMPLEMENTED}: {component}",
    )
