"""Versioned schema for local synthetic engineering-regression scenarios."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import local_only_path
from app.ml.contracts import (
    AnomalyDomain,
    EventDetectionStatus,
    PredictionStatus,
    ReportInput,
    WeatherObservation,
)


GOLDEN_ROOT = Path(__file__).resolve().parent
GOLDEN_SCENARIO_PATH = GOLDEN_ROOT / "fixtures" / "golden_scenarios_v1.json"


class GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenComponent(str, Enum):
    NLP = "NLP"
    DUPLICATE = "DUPLICATE"
    EVENT = "EVENT"
    CREDIBILITY = "CREDIBILITY"
    IMAGE = "IMAGE"
    ANOMALY = "ANOMALY"


class ExpectedComponentStatuses(GoldenModel):
    NLP: PredictionStatus
    DUPLICATE: PredictionStatus
    EVENT: PredictionStatus
    CREDIBILITY: PredictionStatus
    IMAGE: PredictionStatus
    ANOMALY: PredictionStatus


class ExpectedStructuralProperties(GoldenModel):
    unified_result_count: int = Field(ge=1)
    schema_version: Literal["1.0"] = "1.0"
    component_order: tuple[
        Literal["NLP"],
        Literal["DUPLICATE"],
        Literal["EVENT"],
        Literal["CREDIBILITY"],
        Literal["IMAGE"],
        Literal["ANOMALY"],
    ] = (
        "NLP",
        "DUPLICATE",
        "EVENT",
        "CREDIBILITY",
        "IMAGE",
        "ANOMALY",
    )
    serialization_round_trip: Literal[True] = True
    no_fabricated_scores: Literal[True] = True
    image_artifact_expected: Literal[False] = False


class ReasonCodeExpectation(GoldenModel):
    match: Literal["EXACT", "CONTAINS"] = "CONTAINS"
    codes: list[str] = Field(min_length=1)


class ExpectedEventStructure(GoldenModel):
    detection_status: EventDetectionStatus
    candidate_count: int = Field(ge=0)
    group_sizes: list[int] = Field(default_factory=list)
    independent_report_counts: list[int] = Field(default_factory=list)
    lifecycle_states: list[str] = Field(default_factory=list)


class ExpectedDuplicateRelationship(GoldenModel):
    report_id: UUID
    is_duplicate: bool
    matched_report_id: UUID | None = None


class ExpectedAnomalyOutcome(GoldenModel):
    status: PredictionStatus
    anomaly_domain: AnomalyDomain | None = None
    is_anomaly: bool | None = None
    score_present: bool


class GoldenWeatherObservation(GoldenModel):
    observation_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    observed_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    rainfall_mm: float | Literal["NON_FINITE_NAN", "POSITIVE_INFINITY"] | None = None
    river_level_m: float | Literal["NON_FINITE_NAN", "POSITIVE_INFINITY"] | None = None

    def to_contract(self) -> WeatherObservation:
        def measurement(
            value: float | str | None,
        ) -> float | None:
            if value == "NON_FINITE_NAN":
                return math.nan
            if value == "POSITIVE_INFINITY":
                return math.inf
            return value

        return WeatherObservation(
            observation_id=self.observation_id,
            station_id=self.station_id,
            observed_at=self.observed_at,
            latitude=self.latitude,
            longitude=self.longitude,
            rainfall_mm=measurement(self.rainfall_mm),
            river_level_m=measurement(self.river_level_m),
            source_metadata={
                "fixture_status": "TEST_FIXTURE_ONLY",
                "data_origin": "SYNTHETIC",
            },
        )


class GoldenAnomalyWindow(GoldenModel):
    station_id: str = Field(min_length=1)
    observations: list[GoldenWeatherObservation] = Field(min_length=1)


class GoldenScenarioInput(GoldenModel):
    reports: list[ReportInput] = Field(min_length=1)
    event_batch_report_ids: list[UUID] = Field(default_factory=list)
    anomaly_window: GoldenAnomalyWindow | None = None

    @model_validator(mode="after")
    def referenced_reports_exist(self) -> "GoldenScenarioInput":
        report_ids = {report.report_id for report in self.reports}
        missing = set(self.event_batch_report_ids) - report_ids
        if missing:
            raise ValueError(
                f"event batch references unknown report IDs: {sorted(map(str, missing))}"
            )
        if len(report_ids) != len(self.reports):
            raise ValueError("golden scenario report IDs must be unique")
        return self


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class GoldenScenario(GoldenModel):
    scenario_id: str = Field(pattern=r"^SCENARIO_[0-9]{2}_[A-Z0-9_]+$")
    scenario_version: Literal["golden-scenario-v1"] = "golden-scenario-v1"
    schema_version: Literal["1.0"] = "1.0"
    creation_timestamp: datetime
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_status: Literal["TEST_FIXTURE_ONLY"] = "TEST_FIXTURE_ONLY"
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"
    validation_scope: Literal["NOT_PRODUCTION_DATA"] = "NOT_PRODUCTION_DATA"
    description: str = Field(min_length=1)
    input: GoldenScenarioInput
    expected_component_statuses: dict[str, ExpectedComponentStatuses]
    expected_structural_properties: ExpectedStructuralProperties
    expected_reason_codes: dict[str, ReasonCodeExpectation] = Field(
        default_factory=dict
    )
    expected_event_structure: ExpectedEventStructure | None = None
    expected_duplicate_relationship: ExpectedDuplicateRelationship | None = None
    expected_anomaly_outcome: ExpectedAnomalyOutcome | None = None

    @model_validator(mode="after")
    def provenance_and_hash_are_valid(self) -> "GoldenScenario":
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("golden scenario timestamps must include a timezone")
        report_ids = {str(report.report_id) for report in self.input.reports}
        if set(self.expected_component_statuses) != report_ids:
            raise ValueError(
                "expected component statuses must exist for every scenario report"
            )
        payload = self.model_dump(mode="json", exclude={"fixture_hash"})
        actual_hash = hashlib.sha256(_canonical_json(payload)).hexdigest()
        if actual_hash != self.fixture_hash:
            raise ValueError(
                f"fixture hash mismatch for {self.scenario_id}: {actual_hash}"
            )
        return self


class GoldenScenarioSuite(GoldenModel):
    suite_version: Literal["golden-suite-v1"] = "golden-suite-v1"
    schema_version: Literal["1.0"] = "1.0"
    fixture_status: Literal["TEST_FIXTURE_ONLY"] = "TEST_FIXTURE_ONLY"
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"
    validation_scope: Literal["ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION"] = (
        "ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION"
    )
    scenarios: list[GoldenScenario] = Field(min_length=10)

    @model_validator(mode="after")
    def scenario_ids_are_unique(self) -> "GoldenScenarioSuite":
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("golden scenario IDs must be unique")
        return self


def load_golden_scenarios(
    path: Path | str = GOLDEN_SCENARIO_PATH,
) -> GoldenScenarioSuite:
    scenario_path = local_only_path(path, description="golden scenario files")
    return GoldenScenarioSuite.model_validate_json(
        scenario_path.read_text(encoding="utf-8")
    )


__all__ = [
    "GOLDEN_SCENARIO_PATH",
    "GoldenAnomalyWindow",
    "GoldenComponent",
    "GoldenScenario",
    "GoldenScenarioSuite",
    "GoldenWeatherObservation",
    "load_golden_scenarios",
]
