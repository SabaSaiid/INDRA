"""Dataset validation that uses no embeddings or external models."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from app.ml.data.schemas import DatasetRecord, DatasetSplit


class DatasetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(default_factory=list)
    exact_duplicate_text_groups: list[list[str]] = Field(default_factory=list)
    train_test_contamination: list[str] = Field(default_factory=list)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def detect_exact_duplicate_texts(
    records: list[DatasetRecord],
) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[normalize_text(record.text)].append(record.record_id)
    return sorted(
        [sorted(ids) for ids in groups.values() if len(ids) > 1],
        key=lambda ids: ids[0],
    )


def check_train_test_contamination(records: list[DatasetRecord]) -> list[str]:
    train = {
        normalize_text(r.text)
        for r in records
        if r.split is DatasetSplit.TRAIN
    }
    test = {
        normalize_text(r.text)
        for r in records
        if r.split is DatasetSplit.TEST
    }
    return sorted(train & test)


def validate_labels(records: list[DatasetRecord]) -> list[str]:
    errors: list[str] = []
    allowed_splits = {s.value for s in DatasetSplit}
    for record in records:
        if record.split is not None and record.split.value not in allowed_splits:
            errors.append(f"{record.record_id}: invalid split")
        if record.spam is not None and not isinstance(record.spam, bool):
            errors.append(f"{record.record_id}: spam must be boolean")
    return errors


def validate_dataset(
    records: list[DatasetRecord],
    *,
    require_split: bool = False,
) -> DatasetValidationReport:
    errors = validate_labels(records)
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for record in records:
        if record.record_id in seen:
            duplicate_ids.append(record.record_id)
        seen.add(record.record_id)
        if require_split and record.split is None:
            errors.append(f"{record.record_id}: missing split")

    exact_groups = detect_exact_duplicate_texts(records)
    contamination = check_train_test_contamination(records)
    if duplicate_ids:
        errors.append("duplicate record identifiers found")
    if contamination:
        errors.append("exact train/test text contamination found")

    return DatasetValidationReport(
        valid=not errors,
        errors=errors,
        duplicate_ids=sorted(set(duplicate_ids)),
        exact_duplicate_text_groups=exact_groups,
        train_test_contamination=contamination,
    )
