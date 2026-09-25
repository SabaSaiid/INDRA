"""Deterministic generator-level split planning for synthetic NLP data."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from app.ml.data.synthetic_nlp.scenarios import (
    DATASET_SPLITS,
    LANGUAGES,
    PRIMARY_CLASSES,
    DatasetSplit,
    EventType,
    Language,
    NoiseProfile,
)

SPLIT_VERSION: Final[str] = "synthetic-nlp-generator-splits-v1"
SPLIT_WEIGHTS: Final[dict[DatasetSplit, Fraction]] = {
    "train": Fraction(8, 10),
    "validation": Fraction(1, 10),
    "test": Fraction(1, 10),
}


@dataclass(frozen=True, slots=True)
class GenerationSlot:
    """A deterministic row allocation before scenario values are selected."""

    global_index: int
    split_index: int
    class_ordinal: int
    split_class_ordinal: int
    event_type: EventType
    split: DatasetSplit
    language: Language
    noise_profile: NoiseProfile
    hard_negative: bool


def _balanced_counts(total: int, keys: tuple[str, ...]) -> dict[str, int]:
    quotient, remainder = divmod(total, len(keys))
    return {
        key: quotient + (1 if index < remainder else 0)
        for index, key in enumerate(keys)
    }


def _weighted_counts(
    total: int,
    weights: dict[DatasetSplit, Fraction],
) -> dict[DatasetSplit, int]:
    exact = {key: total * weight for key, weight in weights.items()}
    counts = {key: value.numerator // value.denominator for key, value in exact.items()}
    remaining = total - sum(counts.values())
    ranked = sorted(
        weights,
        key=lambda key: (
            exact[key] - counts[key],
            -DATASET_SPLITS.index(key),
        ),
        reverse=True,
    )
    for key in ranked[:remaining]:
        counts[key] += 1
    return counts


def class_split_counts(total_rows: int) -> dict[EventType, dict[DatasetSplit, int]]:
    """Allocate classes first, then fixed 80/10/10 generator partitions."""

    if total_rows < 50:
        raise ValueError("total_rows must allow every class in every split")
    class_counts = _balanced_counts(total_rows, PRIMARY_CLASSES)
    return {
        event_type: _weighted_counts(class_counts[event_type], SPLIT_WEIGHTS)
        for event_type in PRIMARY_CLASSES
    }


def noise_profiles_for_split(split: DatasetSplit) -> tuple[NoiseProfile, ...]:
    """Reserve HIGH noise for the synthetic holdout test partition."""

    if split == "test":
        return ("HIGH",)
    return ("NONE", "LOW", "MEDIUM")


def generation_slots(
    total_rows: int, *, hard_negative_every: int = 5
) -> Iterator[GenerationSlot]:
    """Yield stable balanced slots without performing a random row split."""

    if hard_negative_every < 2:
        raise ValueError("hard_negative_every must be at least 2")
    allocations = class_split_counts(total_rows)
    split_indexes: Counter[DatasetSplit] = Counter()
    global_index = 0
    for class_index, event_type in enumerate(PRIMARY_CLASSES):
        class_ordinal = 0
        for split in DATASET_SPLITS:
            profiles = noise_profiles_for_split(split)
            for split_class_ordinal in range(allocations[event_type][split]):
                language = LANGUAGES[global_index % len(LANGUAGES)]
                profile_offset = class_index + split_class_ordinal
                noise_profile = profiles[profile_offset % len(profiles)]
                yield GenerationSlot(
                    global_index=global_index,
                    split_index=split_indexes[split],
                    class_ordinal=class_ordinal,
                    split_class_ordinal=split_class_ordinal,
                    event_type=event_type,
                    split=split,
                    language=language,
                    noise_profile=noise_profile,
                    hard_negative=(split_class_ordinal % hard_negative_every == 0),
                )
                split_indexes[split] += 1
                global_index += 1
                class_ordinal += 1


def expected_split_counts(total_rows: int) -> dict[str, int]:
    allocations = class_split_counts(total_rows)
    return {
        split: sum(per_split[split] for per_split in allocations.values())
        for split in DATASET_SPLITS
    }


__all__ = [
    "SPLIT_VERSION",
    "SPLIT_WEIGHTS",
    "GenerationSlot",
    "class_split_counts",
    "expected_split_counts",
    "generation_slots",
    "noise_profiles_for_split",
]
