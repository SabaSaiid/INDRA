"""Component interfaces and local ML component implementations."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class InferenceComponent(Protocol[InputT, OutputT]):
    def predict(self, input_value: InputT) -> OutputT:
        ...


class TrainableComponent(Protocol):
    """Optional capability; inference-only components need not implement it."""

    def fit(self, training_data: Any, config: dict[str, Any]) -> Any:
        ...


class TrainingNotImplemented(RuntimeError):
    pass


__all__ = ["InferenceComponent", "TrainableComponent", "TrainingNotImplemented"]
