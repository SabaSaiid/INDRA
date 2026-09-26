"""Deterministic, non-mutating dataset splitting."""

from __future__ import annotations

import random
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from app.ml.data.duplicate_pairs import DuplicatePairRecord, DuplicatePairSplit
from app.ml.data.schemas import DatasetRecord, DatasetSplit


class GroupedDuplicateSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    group_field: str | None = None
    train: list[DuplicatePairRecord] = Field(default_factory=list)
    validation: list[DuplicatePairRecord] = Field(default_factory=list)
    test: list[DuplicatePairRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def grouped_duplicate_split(
    records: list[DuplicatePairRecord],
    *,
    seed: int = 42,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
    group_field: str | None = None,
) -> GroupedDuplicateSplit:
    """Split duplicate pairs by complete event/incident groups only."""

    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(fraction <= 0.0 for fraction in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("train, validation, and test fractions must be positive and sum to 1")
    if not records:
        return GroupedDuplicateSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=["No duplicate-pair records were supplied."],
        )

    candidates = [group_field] if group_field else [
        "event_id_when_known",
        "event_id",
        "incident_id_when_known",
        "incident_id",
    ]
    selected = next(
        (
            field
            for field in candidates
            if field in {
                "event_id_when_known",
                "event_id",
                "incident_id_when_known",
                "incident_id",
            }
            and all(getattr(record, field) for record in records)
        ),
        None,
    )
    if selected is None:
        return GroupedDuplicateSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=[
                "GROUPED_SPLIT_UNAVAILABLE: every pair must have event_id_when_known or incident_id_when_known "
                "before duplicate evaluation can be split."
            ],
        )

    groups: dict[str, list[DuplicatePairRecord]] = defaultdict(list)
    for record in records:
        groups[str(getattr(record, selected))].append(record)
    group_names = sorted(groups)
    random.Random(seed).shuffle(group_names)
    group_count = len(group_names)
    train_groups = max(1, round(group_count * train_fraction))
    validation_groups = max(1, round(group_count * validation_fraction)) if group_count >= 3 else 0
    if train_groups + validation_groups >= group_count:
        validation_groups = max(0, group_count - train_groups - 1)
    test_start = train_groups + validation_groups
    assignment: dict[str, DuplicatePairSplit] = {}
    for index, group_name in enumerate(group_names):
        assignment[group_name] = (
            "train" if index < train_groups else "validation" if index < test_start else "test"
        )
    buckets: dict[str, list[DuplicatePairRecord]] = {"train": [], "validation": [], "test": []}
    for group_name in group_names:
        split = assignment[group_name]
        buckets[split].extend(
            record.model_copy(update={"split": split}) for record in groups[group_name]
        )
    return GroupedDuplicateSplit(
        status="GROUPED_SPLIT_AVAILABLE",
        group_field=selected,
        train=buckets["train"],
        validation=buckets["validation"],
        test=buckets["test"],
        warnings=(
            ["Dataset has fewer than three groups; one or more evaluation buckets may be empty."]
            if group_count < 3
            else []
        ),
    )


def reproducible_split(
    records: list[DatasetRecord],
    *,
    test_fraction: float = 0.2,
    seed: int = 42,
    stratify_field: str | None = "event_type",
) -> list[DatasetRecord]:
    """Return copies with deterministic train/test labels.

    Existing split assignments are rejected so a later training run cannot
    silently redefine an evaluation set.
    """

    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
    if any(record.split is not None for record in records):
        raise ValueError("refusing to resplit records with existing assignments")

    groups: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        key = str(getattr(record, stratify_field)) if stratify_field else "_all"
        groups[key].append(record)

    rng = random.Random(seed)
    test_ids: set[str] = set()
    for group in groups.values():
        shuffled = list(group)
        rng.shuffle(shuffled)
        count = max(1, round(len(shuffled) * test_fraction))
        test_ids.update(record.record_id for record in shuffled[:count])

    return [
        record.model_copy(
            update={
                "split": (
                    DatasetSplit.TEST
                    if record.record_id in test_ids
                    else DatasetSplit.TRAIN
                )
            }
        )
        for record in records
    ]
