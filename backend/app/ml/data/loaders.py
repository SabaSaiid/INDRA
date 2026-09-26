"""Read-only local dataset loaders."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.ml.config import local_only_path
from app.ml.data.schemas import DatasetRecord, DatasetSplit


def _optional_text(value: Any) -> str | None:
    value = "" if value is None else str(value).strip()
    return value or None


def _optional_float(value: Any) -> float | None:
    value = _optional_text(value)
    return None if value is None else float(value)


def _optional_bool(value: Any) -> bool | None:
    value = _optional_text(value)
    if value is None:
        return None
    if value in {"1", "true", "True"}:
        return True
    if value in {"0", "false", "False"}:
        return False
    raise ValueError(f"invalid boolean dataset value: {value!r}")


def load_csv(path: Path | str) -> list[DatasetRecord]:
    """Load a local CSV without downloading or mutating it."""

    path = local_only_path(path, description="dataset paths")
    records: list[DatasetRecord] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            split = _optional_text(row.get("split"))
            records.append(
                DatasetRecord(
                    record_id=str(row.get("id") or row.get("record_id") or ""),
                    text=str(row.get("text") or ""),
                    split=DatasetSplit(split) if split else None,
                    event_type=_optional_text(row.get("event_type")),
                    severity=_optional_text(row.get("severity")),
                    depth_cm=_optional_float(row.get("depth_cm")),
                    spam=_optional_bool(row.get("spam")),
                    language=_optional_text(row.get("lang") or row.get("language")),
                )
            )
    return records
