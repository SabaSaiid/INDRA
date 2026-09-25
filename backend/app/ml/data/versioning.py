"""Deterministic manifests for released human-adjudicated datasets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.ml.config import local_only_path
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord
from app.ml.data.splits import GroupedDuplicateSplit


class DatasetVersionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    creation_timestamp: datetime
    source_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    dataset_content_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    annotation_schema_version: str = Field(min_length=1)
    annotation_guideline_version: str = Field(min_length=1)
    annotator_count: int = Field(ge=0)
    label_counts: dict[str, int] = Field(default_factory=dict)
    split_definition: str = Field(min_length=1)
    grouping_strategy: str = Field(min_length=1)
    split_counts: dict[str, int] = Field(default_factory=dict)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def dataset_content_sha256(records: Sequence[DuplicatePairRecord]) -> str:
    payload = [
        record.model_dump(mode="json")
        for record in sorted(
            records,
            key=lambda item: (item.pair_id, item.annotator_id, item.annotation_timestamp.isoformat()),
        )
    ]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def dataset_manifest_sha256(manifest: DatasetVersionManifest) -> str:
    return hashlib.sha256(_canonical_json(manifest.model_dump(mode="json"))).hexdigest()


def source_file_sha256(path: Path) -> str:
    path = local_only_path(path, description="dataset sources")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset_version_manifest(
    records: Sequence[DuplicatePairRecord],
    *,
    dataset_version: str,
    source_hash: str,
    annotation_schema_version: str = "duplicate-annotation-v1",
    annotation_guideline_version: str = "duplicate-guidance-v1",
    split_definition: str = "grouped train/validation/test",
    grouping_strategy: str = "event_id_when_known then incident_id_when_known",
    split: GroupedDuplicateSplit | None = None,
    creation_timestamp: datetime | None = None,
) -> DatasetVersionManifest:
    annotators = {record.annotator_id for record in records}
    label_counts = {label.value: 0 for label in DuplicatePairLabel}
    for record in records:
        label_counts[record.label.value] += 1
    split_counts = {
        "train": len(split.train) if split else sum(record.split == "train" for record in records),
        "validation": len(split.validation) if split else sum(record.split == "validation" for record in records),
        "test": len(split.test) if split else sum(record.split == "test" for record in records),
    }
    return DatasetVersionManifest(
        dataset_version=dataset_version,
        creation_timestamp=creation_timestamp or datetime.now(timezone.utc),
        source_hash=source_hash,
        dataset_content_hash=dataset_content_sha256(records),
        annotation_schema_version=annotation_schema_version,
        annotation_guideline_version=annotation_guideline_version,
        annotator_count=len(annotators),
        label_counts=label_counts,
        split_definition=split_definition,
        grouping_strategy=grouping_strategy,
        split_counts=split_counts,
    )


def write_dataset_manifest(path: Path, manifest: DatasetVersionManifest) -> None:
    path = local_only_path(path, description="dataset manifest paths")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
