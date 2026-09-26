"""Local report loading and deterministic candidate-pair generation.

Candidate records are review work items only.  They never contain or imply a
ground-truth duplicate label.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.duplicate_matching import haversine_km
from app.ml.components.duplicate_features import normalize_text
from app.ml.config import local_only_path
from app.ml.contracts import CandidateReport, ReportInput


class LocalReportRecord(BaseModel):
    """A report that can be read from a local file or an already-loaded object."""

    model_config = ConfigDict(extra="allow")

    report_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    occurred_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    source_type: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    event_id_when_known: str | None = Field(default=None, min_length=1)
    incident_id_when_known: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def coordinates_are_complete(self) -> "LocalReportRecord":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class CandidatePairRecord(BaseModel):
    """An unordered pair eligible for human review, never a duplicate label."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(min_length=1)
    report_a_id: str = Field(min_length=1)
    report_b_id: str = Field(min_length=1)
    status: str = "CANDIDATE_FOR_REVIEW"
    time_delta_seconds: float = Field(ge=0.0)
    distance_km: float = Field(ge=0.0)
    text_summary: dict[str, float] = Field(default_factory=dict)
    candidate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_score_label: str | None = None
    source_relationship: str | None = None
    event_id_when_known: str | None = None
    incident_id_when_known: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "CandidatePairRecord":
        if self.report_a_id == self.report_b_id:
            raise ValueError("self-pairs are not candidate pairs")
        if self.status != "CANDIDATE_FOR_REVIEW":
            raise ValueError("candidate status must remain CANDIDATE_FOR_REVIEW")
        if self.pair_id != deterministic_pair_id(self.report_a_id, self.report_b_id):
            raise ValueError("pair_id is not the deterministic canonical pair ID")
        return self


class CandidateGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    candidates: list[CandidatePairRecord] = Field(default_factory=list)
    reports_considered: int = 0
    comparisons_performed: int = 0
    reports_skipped_missing_context: int = 0
    warnings: list[str] = Field(default_factory=list)


def canonical_pair_key(report_a_id: str, report_b_id: str) -> tuple[str, str]:
    """Return the canonical unordered pair and reject self-pairs."""

    first, second = str(report_a_id), str(report_b_id)
    if first == second:
        raise ValueError("self-pairs are not candidate pairs")
    return tuple(sorted((first, second)))


def deterministic_pair_id(report_a_id: str, report_b_id: str) -> str:
    first, second = canonical_pair_key(report_a_id, report_b_id)
    digest = hashlib.sha256(f"{first}\n{second}".encode("utf-8")).hexdigest()
    return f"candidate-{digest}"


def _token_jaccard(text_a: str, text_b: str) -> float:
    tokens_a = set(re.findall(r"(?u)\b\w+\b", normalize_text(text_a)))
    tokens_b = set(re.findall(r"(?u)\b\w+\b", normalize_text(text_b)))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _text_summary(text_a: str, text_b: str) -> dict[str, float]:
    normalized_a = normalize_text(text_a)
    normalized_b = normalize_text(text_b)
    return {
        "token_jaccard": round(_token_jaccard(normalized_a, normalized_b), 12),
        "normalized_length_a": float(len(normalized_a)),
        "normalized_length_b": float(len(normalized_b)),
    }


def report_from_report_input(report: ReportInput) -> LocalReportRecord:
    return LocalReportRecord(
        report_id=str(report.report_id),
        text=report.text,
        occurred_at=report.occurred_at,
        latitude=report.latitude,
        longitude=report.longitude,
        source_type=report.source_type,
        source_metadata=report.source_metadata,
    )


def report_from_candidate(report: CandidateReport) -> LocalReportRecord:
    return LocalReportRecord(
        report_id=str(report.report_id),
        text=report.text,
        occurred_at=report.occurred_at,
        latitude=report.latitude,
        longitude=report.longitude,
        source_type=report.source_type,
    )


def coerce_local_report(report: LocalReportRecord | ReportInput | CandidateReport) -> LocalReportRecord:
    """Accept the existing typed backend report objects without database access."""

    if isinstance(report, LocalReportRecord):
        return report
    if isinstance(report, ReportInput):
        return report_from_report_input(report)
    if isinstance(report, CandidateReport):
        return report_from_candidate(report)
    raise TypeError(f"unsupported local report type: {type(report).__name__}")


def generate_candidate_pairs(
    reports: Sequence[LocalReportRecord | ReportInput | CandidateReport],
    *,
    max_time_delta_seconds: float = 15.0 * 60.0,
    max_distance_km: float = 1.0,
    require_same_source: bool = False,
    include_heuristic_score: bool = True,
) -> CandidateGenerationResult:
    """Generate deterministic review candidates using time and geo windows."""

    if max_time_delta_seconds < 0.0 or max_distance_km < 0.0:
        raise ValueError("candidate windows must be non-negative")
    ordered = sorted((coerce_local_report(report) for report in reports), key=lambda record: record.report_id)
    candidates: list[CandidatePairRecord] = []
    skipped = 0
    comparisons = 0
    warnings: list[str] = []
    for index, report_a in enumerate(ordered):
        for report_b in ordered[index + 1 :]:
            comparisons += 1
            if (
                report_a.occurred_at is None
                or report_b.occurred_at is None
                or report_a.latitude is None
                or report_a.longitude is None
                or report_b.latitude is None
                or report_b.longitude is None
            ):
                skipped += 1
                continue
            if require_same_source and report_a.source_type != report_b.source_type:
                continue
            try:
                time_delta = abs((report_a.occurred_at - report_b.occurred_at).total_seconds())
            except TypeError:
                skipped += 1
                warnings.append(
                    f"timestamp timezone mismatch skipped: {report_a.report_id}, {report_b.report_id}"
                )
                continue
            distance = haversine_km(
                report_a.latitude,
                report_a.longitude,
                report_b.latitude,
                report_b.longitude,
            )
            if time_delta > max_time_delta_seconds or distance > max_distance_km:
                continue
            text_summary = _text_summary(report_a.text, report_b.text)
            candidate_score = text_summary["token_jaccard"] if include_heuristic_score else None
            candidates.append(
                CandidatePairRecord(
                    pair_id=deterministic_pair_id(report_a.report_id, report_b.report_id),
                    report_a_id=report_a.report_id,
                    report_b_id=report_b.report_id,
                    time_delta_seconds=round(time_delta, 6),
                    distance_km=round(distance, 6),
                    text_summary=text_summary,
                    candidate_score=candidate_score,
                    candidate_score_label=(
                        "LOCAL HEURISTIC SCORE — NOT GROUND TRUTH"
                        if include_heuristic_score
                        else None
                    ),
                    source_relationship=(
                        "same_source"
                        if report_a.source_type == report_b.source_type
                        else "different_source"
                    ),
                    event_id_when_known=(
                        report_a.event_id_when_known
                        if report_a.event_id_when_known == report_b.event_id_when_known
                        else None
                    ),
                    incident_id_when_known=(
                        report_a.incident_id_when_known
                        if report_a.incident_id_when_known == report_b.incident_id_when_known
                        else None
                    ),
                )
            )
    candidates.sort(key=lambda candidate: candidate.pair_id)
    if skipped:
        warnings.append(
            f"{skipped} report comparisons skipped because time and coordinates were not complete."
        )
    return CandidateGenerationResult(
        status="CANDIDATES_AVAILABLE" if candidates else "NO_CANDIDATES",
        candidates=candidates,
        reports_considered=len(ordered),
        comparisons_performed=comparisons,
        reports_skipped_missing_context=skipped,
        warnings=warnings,
    )


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _row_to_report(row: dict[str, Any]) -> LocalReportRecord:
    known = {
        "id", "report_id", "text", "occurred_at", "timestamp", "created_at",
        "latitude", "longitude", "source_type", "event_id", "event_id_when_known",
        "incident_id", "incident_id_when_known",
    }
    return LocalReportRecord(
        report_id=str(row.get("report_id") or row.get("id") or ""),
        text=str(row.get("text") or ""),
        occurred_at=_parse_optional_datetime(
            row.get("occurred_at") or row.get("timestamp") or row.get("created_at")
        ),
        latitude=_parse_optional_float(row.get("latitude")),
        longitude=_parse_optional_float(row.get("longitude")),
        source_type=str(row.get("source_type") or "") or None,
        source_metadata={key: value for key, value in row.items() if key not in known},
        event_id_when_known=(
            str(row.get("event_id_when_known") or row.get("event_id"))
            if row.get("event_id_when_known") or row.get("event_id")
            else None
        ),
        incident_id_when_known=(
            str(row.get("incident_id_when_known") or row.get("incident_id"))
            if row.get("incident_id_when_known") or row.get("incident_id")
            else None
        ),
    )


def load_local_reports(path: Path) -> list[LocalReportRecord]:
    """Load reports from a local CSV, JSON array/object, or JSONL file only."""

    path = local_only_path(path, description="report paths")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return [_row_to_report(dict(row)) for row in csv.DictReader(handle)]
    if suffix in {".json", ".jsonl"}:
        if suffix == ".jsonl":
            payload = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = payload.get("reports", payload.get("records", payload))
        if not isinstance(payload, list):
            raise ValueError("local report JSON must be an array or an object containing reports")
        return [LocalReportRecord.model_validate(item) for item in payload]
    raise ValueError("supported local report formats are .csv, .json, and .jsonl")


def load_candidate_pairs(path: Path) -> list[CandidatePairRecord]:
    path = local_only_path(path, description="candidate paths")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [CandidatePairRecord.model_validate(row) for row in rows]


def write_candidate_pairs(path: Path, candidates: Sequence[CandidatePairRecord]) -> None:
    """Write review candidates as deterministic local JSONL."""

    path = local_only_path(path, description="candidate paths")
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(candidates, key=lambda candidate: candidate.pair_id)
    path.write_text(
        "".join(candidate.model_dump_json() + "\n" for candidate in ordered),
        encoding="utf-8",
    )
