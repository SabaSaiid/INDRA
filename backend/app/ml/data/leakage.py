"""Non-embedding leakage checks for duplicate-pair dataset splits."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.ml.data.duplicate_pairs import DuplicatePairRecord


class SplitLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    pair_keys_across_splits: list[str] = Field(default_factory=list)
    reversed_pair_keys_across_splits: list[str] = Field(default_factory=list)
    event_ids_across_splits: list[str] = Field(default_factory=list)
    incident_ids_across_splits: list[str] = Field(default_factory=list)
    exact_texts_across_splits: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _normalize_exact_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def validate_split_leakage(
    splits: Mapping[str, Sequence[DuplicatePairRecord]],
    *,
    report_text_by_id: Mapping[str, str] | None = None,
) -> SplitLeakageReport:
    """Reject pair, event, incident, and exact-text overlap across splits."""

    pair_locations: dict[tuple[str, str], set[str]] = defaultdict(set)
    oriented_locations: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    event_locations: dict[str, set[str]] = defaultdict(set)
    incident_locations: dict[str, set[str]] = defaultdict(set)
    text_locations: dict[str, set[str]] = defaultdict(set)
    errors: list[str] = []

    for split_name, records in splits.items():
        if split_name not in {"train", "validation", "test"}:
            errors.append(f"invalid split name: {split_name}")
        for record in records:
            key = tuple(sorted((str(record.report_a_id), str(record.report_b_id))))
            pair_locations[key].add(split_name)
            oriented_locations[key].add((record.report_a_id, record.report_b_id))
            event_id = record.event_id_when_known or record.event_id
            incident_id = record.incident_id_when_known or record.incident_id
            if event_id:
                event_locations[event_id].add(split_name)
            if incident_id:
                incident_locations[incident_id].add(split_name)
            if report_text_by_id:
                for report_id in key:
                    text = report_text_by_id.get(report_id)
                    if text:
                        text_locations[_normalize_exact_text(text)].add(split_name)

    pair_leaks = sorted("::".join(key) for key, locations in pair_locations.items() if len(locations) > 1)
    reversed_leaks = sorted(
        "::".join(key)
        for key, locations in pair_locations.items()
        if len(locations) > 1 and len(oriented_locations[key]) > 1
    )
    event_leaks = sorted(key for key, locations in event_locations.items() if len(locations) > 1)
    incident_leaks = sorted(key for key, locations in incident_locations.items() if len(locations) > 1)
    text_leaks = sorted(key for key, locations in text_locations.items() if key and len(locations) > 1)
    if pair_leaks:
        errors.append("identical unordered pair appears in multiple splits")
    if reversed_leaks:
        errors.append("reversed unordered pair appears in multiple splits")
    if event_leaks:
        errors.append("same event appears in multiple splits")
    if incident_leaks:
        errors.append("same incident appears in multiple splits")
    if text_leaks:
        errors.append("exact normalized report text appears in multiple splits")

    return SplitLeakageReport(
        valid=not errors,
        pair_keys_across_splits=pair_leaks,
        reversed_pair_keys_across_splits=reversed_leaks,
        event_ids_across_splits=event_leaks,
        incident_ids_across_splits=incident_leaks,
        exact_texts_across_splits=text_leaks,
        errors=errors,
    )
