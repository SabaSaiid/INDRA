"""Explicit human adjudication for disagreements between annotations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.data.annotations import AnnotationRecord
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord


class AdjudicationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(min_length=1)
    report_a_id: str = Field(min_length=1)
    report_b_id: str = Field(min_length=1)
    annotations: list[AnnotationRecord] = Field(default_factory=list)
    disagreement: bool = False
    status: str = "UNRESOLVED"
    adjudicated_label: DuplicatePairLabel | None = None
    adjudicator_id: str | None = None
    adjudication_timestamp: datetime | None = None
    adjudication_reason: str | None = None

    @model_validator(mode="after")
    def validate_adjudication_state(self) -> "AdjudicationCase":
        if self.status == "ADJUDICATED":
            if not self.adjudicated_label or not self.adjudicator_id or not self.adjudication_timestamp:
                raise ValueError("an adjudicated case requires label, adjudicator, and timestamp")
            if not self.adjudication_reason:
                raise ValueError("an adjudicated case requires an explicit reason")
        elif self.adjudicated_label is not None:
            raise ValueError("unresolved cases cannot carry an adjudicated label")
        return self

    @property
    def effective_label(self) -> DuplicatePairLabel:
        """Unresolved cases remain uncertain; consensus is never inferred."""

        return self.adjudicated_label or DuplicatePairLabel.UNCERTAIN


def build_adjudication_case(
    annotations: Sequence[AnnotationRecord],
) -> AdjudicationCase:
    if not annotations:
        raise ValueError("at least one annotation is required")
    first = annotations[0]
    pair_ids = {(annotation.report_a_id, annotation.report_b_id) for annotation in annotations}
    if len(pair_ids) > 1:
        canonical_ids = {tuple(sorted((item.report_a_id, item.report_b_id))) for item in annotations}
        if len(canonical_ids) > 1:
            raise ValueError("annotations do not refer to one unordered pair")
    labels = {annotation.label for annotation in annotations}
    return AdjudicationCase(
        pair_id=first.pair_id,
        report_a_id=first.report_a_id,
        report_b_id=first.report_b_id,
        annotations=sorted(annotations, key=lambda item: (item.annotation_timestamp, item.annotation_id)),
        disagreement=len(labels) > 1,
    )


def adjudicate_case(
    case: AdjudicationCase,
    *,
    adjudicated_label: DuplicatePairLabel,
    adjudicator_id: str,
    reason: str,
    timestamp: datetime | None = None,
) -> AdjudicationCase:
    """Record an explicit adjudicator decision; never infer one."""

    if not adjudicator_id.strip() or not reason.strip():
        raise ValueError("adjudicator_id and reason are required")
    return case.model_copy(
        update={
            "status": "ADJUDICATED",
            "adjudicated_label": adjudicated_label,
            "adjudicator_id": adjudicator_id,
            "adjudication_timestamp": timestamp or datetime.now(timezone.utc),
            "adjudication_reason": reason,
        }
    )


def export_adjudicated_records(
    cases: Sequence[AdjudicationCase],
) -> list[DuplicatePairRecord]:
    """Export only explicitly adjudicated cases for dataset evaluation."""

    records: list[DuplicatePairRecord] = []
    for case in cases:
        if case.status != "ADJUDICATED" or case.adjudicated_label is None:
            continue
        source = case.annotations[0] if case.annotations else None
        records.append(
            DuplicatePairRecord(
                pair_id=case.pair_id,
                report_a_id=case.report_a_id,
                report_b_id=case.report_b_id,
                label=case.adjudicated_label,
                annotator_id=case.adjudicator_id or "",
                annotation_timestamp=case.adjudication_timestamp,
                annotation_reason=case.adjudication_reason or "",
                label_provenance="HUMAN_ADJUDICATION",
                event_id_when_known=source.event_id_when_known if source else None,
                incident_id_when_known=source.incident_id_when_known if source else None,
            )
        )
    return sorted(records, key=lambda record: record.pair_id)
