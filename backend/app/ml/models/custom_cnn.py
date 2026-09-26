"""A deliberately modest image CNN initialized entirely from scratch.

This module defines an architecture only.  It never downloads or loads weights
and does not perform training.  The output is logits for the Phase 8
``MULTI_LABEL`` taxonomy; a future, approved inference layer may apply sigmoid
after loading a policy-compliant project-trained artifact.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class ScratchCNNConfig:
    number_of_classes: int = 5
    random_seed: int = 42
    multi_label: bool = True
    dropout: float = 0.25
    input_channels: int = 3

    def __post_init__(self) -> None:
        if self.number_of_classes <= 0:
            raise ValueError("number_of_classes must be positive")
        if self.input_channels <= 0:
            raise ValueError("input_channels must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if not self.multi_label:
            raise ValueError("Phase 8 taxonomy requires multi_label=True")


class ScratchImageCNN(nn.Module):
    """Three convolution blocks plus global pooling and a linear head."""

    architecture_version = "scratch-cnn-v1"

    def __init__(self, config: ScratchCNNConfig | None = None) -> None:
        super().__init__()
        self.config = config or ScratchCNNConfig()
        # Preserve the caller's global RNG state while making construction
        # reproducible for the configured seed.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.config.random_seed)
            self.features = nn.Sequential(
                nn.Conv2d(self.config.input_channels, 16, kernel_size=3, padding=1),
                nn.BatchNorm2d(16),
                nn.ReLU(inplace=False),
                nn.MaxPool2d(kernel_size=2),
                nn.Conv2d(16, 32, kernel_size=3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=False),
                nn.MaxPool2d(kernel_size=2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=False),
                nn.AdaptiveAvgPool2d((1, 1)),
            )
            self.dropout = nn.Dropout(p=self.config.dropout)
            self.classifier = nn.Linear(64, self.config.number_of_classes)
            self._initialize_parameters()

    def _initialize_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.BatchNorm2d):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        features = self.features(pixel_values)
        flattened = torch.flatten(features, start_dim=1)
        return self.classifier(self.dropout(flattened))


def build_scratch_cnn(config: ScratchCNNConfig | None = None) -> ScratchImageCNN:
    """Construct a randomly initialized model without reading any artifact."""

    return ScratchImageCNN(config)


class ScratchImageCNNV2(nn.Module):
    """The v1 feature extractor with average and max evidence pooling.

    The small successor preserves the three convolution blocks and scratch
    initialization while retaining localized puddle/debris evidence that a
    global-average-only head can suppress.
    """

    architecture_version = "scratch-cnn-v2-dual-pool"

    def __init__(self, config: ScratchCNNConfig | None = None) -> None:
        super().__init__()
        self.config = config or ScratchCNNConfig()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.config.random_seed)
            self.features = nn.Sequential(
                nn.Conv2d(self.config.input_channels, 16, kernel_size=3, padding=1),
                nn.BatchNorm2d(16),
                nn.ReLU(inplace=False),
                nn.MaxPool2d(kernel_size=2),
                nn.Conv2d(16, 32, kernel_size=3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=False),
                nn.MaxPool2d(kernel_size=2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=False),
            )
            self.average_pool = nn.AdaptiveAvgPool2d((1, 1))
            self.maximum_pool = nn.AdaptiveMaxPool2d((1, 1))
            self.dropout = nn.Dropout(p=self.config.dropout)
            self.classifier = nn.Linear(128, self.config.number_of_classes)
            self._initialize_parameters()

    def _initialize_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.BatchNorm2d):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        features = self.features(pixel_values)
        average = torch.flatten(self.average_pool(features), start_dim=1)
        maximum = torch.flatten(self.maximum_pool(features), start_dim=1)
        return self.classifier(self.dropout(torch.cat((average, maximum), dim=1)))


def build_scratch_cnn_v2(config: ScratchCNNConfig | None = None) -> ScratchImageCNNV2:
    """Construct the local-evidence successor without reading any weights."""

    return ScratchImageCNNV2(config)


__all__ = [
    "ScratchCNNConfig",
    "ScratchImageCNN",
    "ScratchImageCNNV2",
    "build_scratch_cnn",
    "build_scratch_cnn_v2",
]
