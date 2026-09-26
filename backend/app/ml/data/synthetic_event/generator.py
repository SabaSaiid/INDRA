"""Deterministic local generator for Phase 20 event-grouping validation.

Canonical event identity is assigned before any detector code runs.  Hidden
truth and detector-visible fixtures are written to different files so the
grouping implementation cannot receive generator identity or scenario labels.
The corpus is project-authored, synthetic, and development-only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations, product
from pathlib import Path
from typing import Any, Final, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.ml.config import file_sha256, local_only_path
from app.ml.contracts import (
    DuplicatePrediction,
    EventObservation,
    PredictionStatus,
    StationObservation,
    TextPrediction,
)
from app.ml.data.event_annotations import EventAnnotationLabel, EventPairAnnotation

GENERATOR_VERSION: Final[str] = "synthetic-event-generator-v1"
SCENARIO_VERSION: Final[str] = "synthetic-event-scenarios-v1"
SPLIT_VERSION: Final[str] = "synthetic-event-canonical-splits-v1"
TEMPLATE_VERSION: Final[str] = "synthetic-event-templates-v1"
MANIFEST_VERSION: Final[str] = "synthetic-event-dataset-manifest-v1"
REPORT_VERSION: Final[str] = "synthetic-event-quality-report-v1"
DEFAULT_SEED: Final[int] = 200020
DEFAULT_BATCHES_PER_SCENARIO: Final[int] = 1_000
DEFAULT_DATASET_ID: Final[str] = "indra-event-project-synthetic-v1"
DEFAULT_DATASET_VERSION: Final[str] = "synthetic-event-110k-v1"
DEFAULT_CREATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 23, 20, 0, tzinfo=timezone.utc
)

EVENT_TYPES: Final[tuple[str, ...]] = (
    "URBAN_FLOOD",
    "RIVER_BREACH",
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
)
NLP_TAXONOMY: Final[tuple[str, ...]] = (*EVENT_TYPES, "NOT_RELEVANT")
EVENT_SCENARIOS: Final[tuple[str, ...]] = (
    "A_SINGLE_EVENT_MULTIPLE_REPORTS",
    "B_TWO_SPATIALLY_SEPARATE_EVENTS",
    "C_TWO_TEMPORALLY_SEPARATE_EVENTS",
    "D_SAME_WEATHER_TYPE_DIFFERENT_EVENTS",
    "E_DUPLICATE_REPORTS_WITHIN_EVENT",
    "F_EVENT_REPORT_NOISE",
    "G_PARTIALLY_OVERLAPPING_EVENTS",
    "H_CHAIN_BRIDGE",
    "I_EVENT_TYPE_CONFLICT",
    "J_SINGLE_REPORT_EVENT_CANDIDATE",
    "K_LEGITIMATE_ELONGATED_EVENT",
)
SPLITS: Final[tuple[str, ...]] = ("train", "validation", "test")
FORBIDDEN_DETECTOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_event_id",
        "generator_event_id",
        "scenario",
        "scenario_family",
        "batch_id",
        "incident_id",
        "duplicate_family",
        "split",
    }
)
SOURCE_FAMILIES: Final[tuple[str, ...]] = (
    "CITIZEN_APP",
    "DISTRICT_HELPLINE",
    "FIELD_OFFICER",
    "SENSOR_RELAY",
)
LANGUAGES: Final[tuple[str, ...]] = ("en", "hi", "hinglish")
_SPLIT_ORIGINS: Final[dict[str, datetime]] = {
    "train": datetime(2020, 1, 1, tzinfo=timezone.utc),
    "validation": datetime(2032, 1, 1, tzinfo=timezone.utc),
    "test": datetime(2036, 1, 1, tzinfo=timezone.utc),
}
_LOCATIONS: Final[dict[str, tuple[tuple[float, float], ...]]] = {
    "train": (
        (25.5941, 85.1376),
        (24.7914, 85.0002),
        (26.8467, 80.9462),
        (26.9124, 75.7873),
        (26.1445, 91.7362),
    ),
    "validation": ((23.3441, 85.3096), (23.2599, 77.4126), (21.1702, 72.8311)),
    "test": ((20.4625, 85.8830), (9.9252, 78.1198), (30.3165, 78.0322)),
}


@dataclass(frozen=True, slots=True)
class SyntheticEventGeneratorConfig:
    batches_per_scenario: int = DEFAULT_BATCHES_PER_SCENARIO
    seed: int = DEFAULT_SEED
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_version: str = DEFAULT_DATASET_VERSION
    creation_timestamp: datetime = DEFAULT_CREATION_TIMESTAMP
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    reports_per_batch: int = 10
    pairs_per_batch: int = 5
    event_types: tuple[str, ...] = EVENT_TYPES

    def __post_init__(self) -> None:
        if self.batches_per_scenario < 20:
            raise ValueError("batches_per_scenario must be at least 20")
        if self.reports_per_batch != 10:
            raise ValueError("Phase 20 scenario templates require 10 reports per batch")
        if self.pairs_per_batch != 5:
            raise ValueError("Phase 20 ground truth requires five pairs per batch")
        if not math.isclose(
            self.train_fraction + self.validation_fraction + self.test_fraction,
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("split fractions must sum to one")
        if min(self.train_fraction, self.validation_fraction, self.test_fraction) <= 0:
            raise ValueError("split fractions must be positive")
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError("dataset identity cannot be blank")
        if not self.event_types or not set(self.event_types).issubset(EVENT_TYPES):
            raise ValueError("event_types must use only the approved event taxonomy")

    @property
    def total_batches(self) -> int:
        return self.batches_per_scenario * len(EVENT_SCENARIOS)

    @property
    def total_reports(self) -> int:
        return self.total_batches * self.reports_per_batch

    @property
    def total_pairs(self) -> int:
        return self.total_batches * self.pairs_per_batch


class SyntheticEventGroundTruth(BaseModel):
    """Generator-only annotation.  This object is never passed to the detector."""

    model_config = ConfigDict(extra="forbid")

    canonical_event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    report_id: UUID
    incident_id: str = Field(min_length=1)
    timestamp: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_family: str = Field(min_length=1)
    duplicate_family: str | None = None
    duplicate_of_report_id: UUID | None = None
    language: str = Field(min_length=1)
    report_text: str = Field(min_length=1)
    split: Literal["train", "validation", "test"]
    batch_id: str = Field(min_length=1)
    scenario_family: str = Field(min_length=1)
    noise_profile: str = Field(min_length=1)
    report_ordinal: int = Field(ge=0)


class SyntheticDetectorInput(BaseModel):
    """Only detector-permitted evidence; generator identity is structurally absent."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    report_text: str = Field(min_length=1)
    language: str = Field(min_length=1)
    occurred_at: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_type: str = Field(min_length=1)
    text_prediction: TextPrediction
    duplicate_prediction: DuplicatePrediction
    weather_observations: list[StationObservation] = Field(default_factory=list)

    def to_observation(self) -> EventObservation:
        return EventObservation(
            report_id=self.report_id,
            text_prediction=self.text_prediction,
            occurred_at=self.occurred_at,
            latitude=self.latitude,
            longitude=self.longitude,
            source_type=self.source_type,
            duplicate_prediction=self.duplicate_prediction,
            weather_observations=self.weather_observations,
        )


class SyntheticEventQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str
    valid: bool
    generated_at: datetime
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_hashes: dict[str, str]
    generator_version: str
    scenario_version: str
    split_version: str
    seed: int
    report_count: int = Field(ge=0)
    canonical_event_count: int = Field(ge=0)
    pair_count: int = Field(ge=0)
    split_report_counts: dict[str, int]
    split_event_counts: dict[str, int]
    split_pair_counts: dict[str, int]
    scenario_counts: dict[str, int]
    event_type_counts: dict[str, int]
    pair_label_counts: dict[str, int]
    language_counts: dict[str, int]
    duplicate_report_count: int = Field(ge=0)
    leakage_checks: dict[str, int | str | bool]
    invariant_checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: Literal["PROJECT_AUTHORED"] = "PROJECT_AUTHORED"
    data_kind: Literal["SYNTHETIC"] = "SYNTHETIC"
    classification: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    production_validation: Literal["NOT_VALIDATED"] = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class SyntheticEventArtifacts:
    output_directory: Path
    ground_truth_paths: dict[str, Path]
    detector_input_paths: dict[str, Path]
    pair_path: Path
    quality_report_path: Path
    manifest_path: Path
    dataset_hash: str
    split_hash: str
    pair_hash: str
    quality_report_hash: str
    manifest_hash: str
    report: SyntheticEventQualityReport
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ReportPlan:
    event_index: int
    distance_km: float
    bearing_degrees: float
    minute_offset: float
    predicted_type: str | None = None
    prediction_confidence: float = 0.84
    duplicate_of_index: int | None = None
    noise_profile: str = "CLEAN"
    weather_value: float | None = None


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _uuid(config: SyntheticEventGeneratorConfig, kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{config.dataset_id}|{config.seed}|{kind}|{value}")


def _record_rng(config: SyntheticEventGeneratorConfig, *parts: object) -> random.Random:
    material = "|".join((GENERATOR_VERSION, str(config.seed), *(str(x) for x in parts)))
    return random.Random(
        int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:16], "big")
    )


def _allocate(total: int, weights: tuple[tuple[str, float], ...]) -> dict[str, int]:
    raw = [(name, total * weight) for name, weight in weights]
    counts = {name: math.floor(value) for name, value in raw}
    remainder = total - sum(counts.values())
    order = sorted(raw, key=lambda item: (-(item[1] - math.floor(item[1])), item[0]))
    for name, _ in order[:remainder]:
        counts[name] += 1
    return counts


def split_batch_counts(config: SyntheticEventGeneratorConfig) -> dict[str, int]:
    return _allocate(
        config.batches_per_scenario,
        (
            ("train", config.train_fraction),
            ("validation", config.validation_fraction),
            ("test", config.test_fraction),
        ),
    )


def _offset_coordinate(
    latitude: float,
    longitude: float,
    distance_km: float,
    bearing_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(bearing_degrees)
    latitude_delta = distance_km * math.cos(angle) / 111.32
    longitude_scale = max(0.2, math.cos(math.radians(latitude)))
    longitude_delta = distance_km * math.sin(angle) / (111.32 * longitude_scale)
    return latitude + latitude_delta, longitude + longitude_delta


def _event_count(scenario: str) -> int:
    return (
        2
        if scenario
        in {
            "B_TWO_SPATIALLY_SEPARATE_EVENTS",
            "C_TWO_TEMPORALLY_SEPARATE_EVENTS",
            "D_SAME_WEATHER_TYPE_DIFFERENT_EVENTS",
            "G_PARTIALLY_OVERLAPPING_EVENTS",
            "H_CHAIN_BRIDGE",
            "J_SINGLE_REPORT_EVENT_CANDIDATE",
        }
        else 1
    )


def _probabilities(label: str, confidence: float) -> dict[str, float]:
    remainder = (1.0 - confidence) / (len(NLP_TAXONOMY) - 1)
    return {item: (confidence if item == label else remainder) for item in NLP_TAXONOMY}


def _text_prediction(
    label: str | None,
    confidence: float,
) -> TextPrediction:
    if label is None:
        return TextPrediction(
            status=PredictionStatus.NOT_IMPLEMENTED,
            reason_codes=["CONTROLLED_SYNTHETIC_NLP_MISSING"],
            evidence=["fixture_source=PROJECT_AUTHORED_SYNTHETIC"],
        )
    return TextPrediction(
        status=PredictionStatus.AVAILABLE,
        label=label,
        probabilities=_probabilities(label, confidence),
        confidence=confidence,
        model_version="controlled-synthetic-text-prediction-v1",
        feature_version="controlled-synthetic-nlp-fixture-v1",
        evidence=[
            "fixture_source=PROJECT_AUTHORED_SYNTHETIC",
            "NOT_A_FROZEN_NLP_MODEL_INFERENCE",
        ],
    )


def _report_text(
    event_type: str,
    language: str,
    ordinal: int,
    noise_profile: str,
) -> str:
    stems = {
        "en": {
            "URBAN_FLOOD": "Water is rising across the city road",
            "RIVER_BREACH": "River embankment breach reported nearby",
            "CLOUDBURST": "Sudden intense rain and flash flooding reported",
            "CYCLONE_INUNDATION": "Cyclone surge has inundated the coastal area",
        },
        "hi": {
            "URBAN_FLOOD": "shahar ki sadak par paani bhar raha hai",
            "RIVER_BREACH": "nadi ka bandh tootne ki soochna mili",
            "CLOUDBURST": "achanak tez barish aur baadh ki soochna",
            "CYCLONE_INUNDATION": "chakravat se tat par paani bhar gaya",
        },
        "hinglish": {
            "URBAN_FLOOD": "city road par water level badh raha hai",
            "RIVER_BREACH": "river bandh breach hua hai nearby",
            "CLOUDBURST": "sudden heavy rain se flash flood hua",
            "CYCLONE_INUNDATION": "cyclone surge se coastal area flooded hai",
        },
    }
    suffixes = {
        "CLEAN": "verified local observation",
        "DUPLICATE_COPY": "forwarded local observation",
        "MISSING_NLP": "metadata partial",
        "LOW_CONFIDENCE_NLP": "wording uncertain",
        "TYPE_CONFLICT": "classification evidence conflicts",
        "SPATIAL_NOISE": "location estimate approximate",
        "ELONGATED_EVENT": "extent marker",
    }
    return f"{stems[language][event_type]} {suffixes.get(noise_profile, noise_profile)} ref-{ordinal:06d}"


def _scenario_plan(
    config: SyntheticEventGeneratorConfig,
    scenario: str,
    ordinal: int,
    event_types: tuple[str, ...],
    rng: random.Random,
) -> list[_ReportPlan]:
    count_a = 4 + ordinal % 3
    assignments = [0] * count_a + [1] * (10 - count_a)

    def jitter(index: int, radius: float = 0.35) -> tuple[float, float]:
        return radius * (0.25 + 0.75 * rng.random()), (
            index * 137.508 + ordinal * 17
        ) % 360

    plans: list[_ReportPlan] = []
    if scenario == "A_SINGLE_EVENT_MULTIPLE_REPORTS":
        for index in range(10):
            distance, bearing = jitter(index, 0.8 + (ordinal % 4) * 0.2)
            plans.append(_ReportPlan(0, distance, bearing, index * (4 + ordinal % 3)))
    elif scenario == "B_TWO_SPATIALLY_SEPARATE_EVENTS":
        separation = 9.0 + (ordinal % 5) * 1.5
        for index, event_index in enumerate(assignments):
            local, bearing = jitter(index, 0.45)
            distance = local if event_index == 0 else separation + local
            plans.append(
                _ReportPlan(
                    event_index,
                    distance,
                    90.0 if event_index else bearing,
                    (index % 6) * 6,
                )
            )
    elif scenario == "C_TWO_TEMPORALLY_SEPARATE_EVENTS":
        separation = (240.0, 270.0, 330.0)[ordinal % 3]
        for index, event_index in enumerate(assignments):
            distance, bearing = jitter(index, 0.45)
            plans.append(
                _ReportPlan(
                    event_index,
                    distance,
                    bearing,
                    (index % 6) * 6 + separation * event_index,
                )
            )
    elif scenario == "D_SAME_WEATHER_TYPE_DIFFERENT_EVENTS":
        separation = 9.5 + (ordinal % 4)
        weather = 22.0 + ordinal % 7
        for index, event_index in enumerate(assignments):
            local, bearing = jitter(index, 0.35)
            distance = local if event_index == 0 else separation + local
            plans.append(
                _ReportPlan(
                    event_index,
                    distance,
                    90.0 if event_index else bearing,
                    (index % 6) * 5,
                    weather_value=weather,
                )
            )
    elif scenario == "E_DUPLICATE_REPORTS_WITHIN_EVENT":
        duplicate_count = 3 + ordinal % 3
        original_count = 10 - duplicate_count
        for index in range(original_count):
            plans.append(_ReportPlan(0, 0.0, 0.0, index * 6.0))
        for index in range(original_count, 10):
            # Keep generated duplicate relations disjoint.  The frozen detector's
            # duplicate-aware independent-count formula is pair based, so a head
            # reused by several copies would be a different graph topology rather
            # than an additional independent observation.
            target = index - original_count
            plans.append(
                _ReportPlan(
                    0,
                    0.0,
                    0.0,
                    target * 6.0,
                    duplicate_of_index=target,
                    noise_profile="DUPLICATE_COPY",
                )
            )
    elif scenario == "F_EVENT_REPORT_NOISE":
        for index in range(10):
            distance, bearing = jitter(index, 2.15)
            missing = index in {1, 7}
            low = index in {3, 8}
            plans.append(
                _ReportPlan(
                    0,
                    distance,
                    bearing,
                    index * (16.0 / 0.9),
                    predicted_type=None if missing else event_types[0],
                    prediction_confidence=0.38 if low else 0.84,
                    noise_profile="MISSING_NLP"
                    if missing
                    else "LOW_CONFIDENCE_NLP"
                    if low
                    else "SPATIAL_NOISE",
                )
            )
    elif scenario == "G_PARTIALLY_OVERLAPPING_EVENTS":
        variant = ordinal % 4
        separation = 3.8 if variant < 2 else 5.8
        second_type = event_types[0] if variant % 2 == 0 else event_types[1]
        for index, event_index in enumerate(assignments):
            local, bearing = jitter(index, 0.18)
            distance = local if event_index == 0 else separation + local
            predicted = event_types[0] if event_index == 0 else second_type
            plans.append(
                _ReportPlan(
                    event_index,
                    distance,
                    90.0 if event_index else bearing,
                    (index % 6) * 7,
                    predicted_type=predicted,
                    prediction_confidence=0.45
                    if event_index == 1 and second_type != event_types[0]
                    else 0.84,
                    noise_profile="LOW_CONFIDENCE_NLP"
                    if event_index == 1 and second_type != event_types[0]
                    else "CLEAN",
                )
            )
    elif scenario == "H_CHAIN_BRIDGE":
        # True event 0 spans nodes A/B; true event 1 is node C.  A-C is outside
        # the 5 km complete-link constraint even though B-C is close.
        for index in range(10):
            if index < 3:
                event_index, distance = 0, 0.0
            elif index < 6:
                event_index, distance = 0, 3.6
            else:
                event_index, distance = 1, 7.2
            plans.append(_ReportPlan(event_index, distance, 90.0, index * 5.0))
    elif scenario == "I_EVENT_TYPE_CONFLICT":
        primary_index = config.event_types.index(event_types[0])
        conflicting = config.event_types[(primary_index + 1) % len(config.event_types)]
        for index in range(10):
            distance, bearing = jitter(index, 0.3)
            conflict = index >= 4
            plans.append(
                _ReportPlan(
                    0,
                    distance,
                    bearing,
                    index * 5.0,
                    predicted_type=conflicting if conflict else event_types[0],
                    noise_profile="TYPE_CONFLICT" if conflict else "CLEAN",
                )
            )
    elif scenario == "J_SINGLE_REPORT_EVENT_CANDIDATE":
        plans.append(_ReportPlan(0, 0.0, 0.0, 0.0))
        for index in range(1, 10):
            local, _ = jitter(index, 0.25)
            plans.append(_ReportPlan(1, 10.0 + local, 90.0, index * 5.0))
    elif scenario == "K_LEGITIMATE_ELONGATED_EVENT":
        for index in range(10):
            signed_distance = -2.2 + (4.4 * index / 9.0)
            plans.append(
                _ReportPlan(
                    0,
                    abs(signed_distance),
                    90.0 if signed_distance >= 0 else 270.0,
                    160.0 * index / 9.0,
                    noise_profile="ELONGATED_EVENT",
                )
            )
    else:  # pragma: no cover - guarded by the public scenario tuple
        raise ValueError(f"unsupported event scenario: {scenario}")
    if len(plans) != config.reports_per_batch:
        raise AssertionError("scenario template did not create ten reports")
    return plans


def _scenario_event_types(
    config: SyntheticEventGeneratorConfig,
    scenario: str,
    scenario_index: int,
    ordinal: int,
) -> tuple[str, ...]:
    primary_index = (scenario_index + ordinal) % len(config.event_types)
    primary = config.event_types[primary_index]
    secondary = config.event_types[(primary_index + 1) % len(config.event_types)]
    count = _event_count(scenario)
    if count == 1:
        # Type-conflict truth stays primary; only its controlled NLP fixtures differ.
        return (primary,)
    if scenario == "G_PARTIALLY_OVERLAPPING_EVENTS" and ordinal % 2 == 1:
        return primary, secondary
    return primary, primary


def generate_scenario_batch(
    config: SyntheticEventGeneratorConfig,
    *,
    split: Literal["train", "validation", "test"],
    scenario: str,
    scenario_ordinal: int,
    split_batch_ordinal: int,
) -> tuple[
    tuple[SyntheticEventGroundTruth, ...],
    tuple[SyntheticDetectorInput, ...],
    tuple[EventPairAnnotation, ...],
]:
    """Generate one batch with truth fixed before detector-visible fixtures."""

    if scenario not in EVENT_SCENARIOS:
        raise ValueError(f"unsupported scenario: {scenario}")
    scenario_index = EVENT_SCENARIOS.index(scenario)
    rng = _record_rng(config, split, scenario, scenario_ordinal)
    batch_id = f"{split}-{scenario_index:02d}-{scenario_ordinal:05d}"
    location = _LOCATIONS[split][
        (scenario_index + scenario_ordinal) % len(_LOCATIONS[split])
    ]
    # Twelve-hour spacing prevents unrelated batches from entering the temporal
    # sweep if an evaluator elects to process an entire split at once.
    batch_time = _SPLIT_ORIGINS[split] + timedelta(hours=12 * split_batch_ordinal)
    event_types = _scenario_event_types(
        config, scenario, scenario_index, scenario_ordinal
    )
    plans = _scenario_plan(config, scenario, scenario_ordinal, event_types, rng)
    canonical_ids = tuple(
        f"event-{_uuid(config, 'canonical-event', f'{batch_id}|{index}')}"
        for index in range(_event_count(scenario))
    )
    incident_ids = tuple(
        f"incident-{_uuid(config, 'incident', f'{batch_id}|{index}')}"
        for index in range(_event_count(scenario))
    )
    report_ids = tuple(
        _uuid(config, "report", f"{batch_id}|{index}") for index in range(10)
    )
    duplicate_families: dict[int, str] = {}
    for index, plan in enumerate(plans):
        if plan.duplicate_of_index is not None:
            family = f"duplicate-{_uuid(config, 'duplicate-family', f'{batch_id}|{plan.duplicate_of_index}')}"
            duplicate_families[index] = family
            duplicate_families[plan.duplicate_of_index] = family

    truth_rows: list[SyntheticEventGroundTruth] = []
    input_rows: list[SyntheticDetectorInput] = []
    for index, plan in enumerate(plans):
        true_type = event_types[plan.event_index]
        predicted_type = (
            plan.predicted_type
            if plan.predicted_type is not None or plan.noise_profile == "MISSING_NLP"
            else true_type
        )
        latitude, longitude = _offset_coordinate(
            location[0], location[1], plan.distance_km, plan.bearing_degrees
        )
        occurred_at = batch_time + timedelta(minutes=plan.minute_offset)
        language = LANGUAGES[
            (scenario_index + scenario_ordinal + index) % len(LANGUAGES)
        ]
        source = SOURCE_FAMILIES[
            (scenario_index + scenario_ordinal + index) % len(SOURCE_FAMILIES)
        ]
        if scenario == "F_EVENT_REPORT_NOISE" and index in {1, 7}:
            source = "UNKNOWN_SOURCE"
        if plan.duplicate_of_index is not None:
            source = truth_rows[plan.duplicate_of_index].source_family
        text = _report_text(
            true_type,
            language,
            scenario_ordinal * 10 + index,
            plan.noise_profile,
        )
        truth = SyntheticEventGroundTruth(
            canonical_event_id=canonical_ids[plan.event_index],
            event_type=true_type,
            report_id=report_ids[index],
            incident_id=incident_ids[plan.event_index],
            timestamp=occurred_at,
            latitude=latitude,
            longitude=longitude,
            source_family=source,
            duplicate_family=duplicate_families.get(index),
            duplicate_of_report_id=(
                report_ids[plan.duplicate_of_index]
                if plan.duplicate_of_index is not None
                else None
            ),
            language=language,
            report_text=text,
            split=split,
            batch_id=batch_id,
            scenario_family=scenario,
            noise_profile=plan.noise_profile,
            report_ordinal=index,
        )
        weather: list[StationObservation] = []
        if plan.weather_value is not None:
            weather = [
                StationObservation(
                    station_id=f"synthetic-station-{scenario_ordinal % 17:02d}",
                    observed_at=occurred_at,
                    latitude=latitude,
                    longitude=longitude,
                    measurements={"rainfall_mm_24h": plan.weather_value},
                )
            ]
        duplicate = DuplicatePrediction(
            status=(
                PredictionStatus.AVAILABLE
                if plan.duplicate_of_index is not None
                else PredictionStatus.NOT_APPLICABLE
            ),
            is_duplicate=plan.duplicate_of_index is not None,
            matched_report_id=(
                report_ids[plan.duplicate_of_index]
                if plan.duplicate_of_index is not None
                else None
            ),
            similarity=0.99 if plan.duplicate_of_index is not None else None,
            method=(
                "PROJECT_GENERATED_RELATION"
                if plan.duplicate_of_index is not None
                else "NO_PROJECT_GENERATED_RELATION"
            ),
            reason_codes=(
                ["PROJECT_GENERATED_DUPLICATE_RELATION"]
                if plan.duplicate_of_index is not None
                else []
            ),
        )
        detector_input = SyntheticDetectorInput(
            report_id=report_ids[index],
            report_text=text,
            language=language,
            occurred_at=occurred_at,
            latitude=latitude,
            longitude=longitude,
            source_type=source,
            text_prediction=_text_prediction(
                predicted_type, plan.prediction_confidence
            ),
            duplicate_prediction=duplicate,
            weather_observations=weather,
        )
        truth_rows.append(truth)
        input_rows.append(detector_input)

    indexes_by_event: defaultdict[str, list[int]] = defaultdict(list)
    for index, truth in enumerate(truth_rows):
        indexes_by_event[truth.canonical_event_id].append(index)
    event_indexes = list(indexes_by_event.values())
    selected_pairs: list[tuple[int, int, EventAnnotationLabel]] = []
    if len(event_indexes) == 1:
        selected_pairs = [
            (left, right, EventAnnotationLabel.EVENT_MATCH)
            for left, right in list(combinations(event_indexes[0], 2))[:5]
        ]
    else:
        for indexes in event_indexes:
            selected_pairs.extend(
                (left, right, EventAnnotationLabel.EVENT_MATCH)
                for left, right in list(combinations(indexes, 2))[:2]
            )
        selected_pairs = selected_pairs[:3]
        cross_pairs = list(product(event_indexes[0], event_indexes[1]))
        cross_label = (
            EventAnnotationLabel.UNCERTAIN
            if scenario == "G_PARTIALLY_OVERLAPPING_EVENTS"
            else EventAnnotationLabel.EVENT_NOT_MATCH
        )
        selected_pairs.extend(
            (left, right, cross_label)
            for left, right in cross_pairs[: 5 - len(selected_pairs)]
        )
    if len(selected_pairs) != config.pairs_per_batch:
        raise AssertionError("scenario did not produce five pair annotations")

    pair_rows: list[EventPairAnnotation] = []
    for pair_index, (left, right, label) in enumerate(selected_pairs):
        left_truth, right_truth = truth_rows[left], truth_rows[right]
        canonical = (
            left_truth.canonical_event_id
            if label is EventAnnotationLabel.EVENT_MATCH
            else None
        )
        pair_rows.append(
            EventPairAnnotation(
                event_a_id=str(left_truth.report_id),
                event_b_id=str(right_truth.report_id),
                label=label,
                annotator_id=GENERATOR_VERSION,
                reason=(
                    "Direct project-generator event identity; detector output was not used."
                    if label is not EventAnnotationLabel.UNCERTAIN
                    else "Generator-declared partial-overlap boundary; identity remains hidden from the detector."
                ),
                timestamp=config.creation_timestamp
                + timedelta(
                    seconds=split_batch_ordinal * config.pairs_per_batch + pair_index
                ),
                canonical_event_id=canonical,
                split=split,
                report_ids_a=[str(left_truth.report_id)],
                report_ids_b=[str(right_truth.report_id)],
                event_definition_hash_a=_sha256_payload(
                    {"canonical_event_id": left_truth.canonical_event_id}
                ),
                event_definition_hash_b=_sha256_payload(
                    {"canonical_event_id": right_truth.canonical_event_id}
                ),
            )
        )
    return tuple(truth_rows), tuple(input_rows), tuple(pair_rows)


def iter_generated_batches(
    config: SyntheticEventGeneratorConfig,
) -> Iterator[
    tuple[
        str,
        str,
        int,
        tuple[SyntheticEventGroundTruth, ...],
        tuple[SyntheticDetectorInput, ...],
        tuple[EventPairAnnotation, ...],
    ]
]:
    counts = split_batch_counts(config)
    split_ordinals = {split: 0 for split in SPLITS}
    for split in SPLITS:
        for scenario in EVENT_SCENARIOS:
            for scenario_ordinal in range(counts[split]):
                split_ordinal = split_ordinals[split]
                truth, inputs, pairs = generate_scenario_batch(
                    config,
                    split=split,  # type: ignore[arg-type]
                    scenario=scenario,
                    scenario_ordinal=scenario_ordinal,
                    split_batch_ordinal=split_ordinal,
                )
                split_ordinals[split] += 1
                yield split, scenario, scenario_ordinal, truth, inputs, pairs


def _dataset_hash(file_hashes: dict[str, str]) -> str:
    return _sha256_payload({"files": dict(sorted(file_hashes.items()))})


def _split_hash(canonical_splits: dict[str, str]) -> str:
    return _sha256_payload({"canonical_event_splits": sorted(canonical_splits.items())})


def validate_synthetic_event_dataset(
    ground_truth_paths: dict[str, Path],
    detector_input_paths: dict[str, Path],
    pair_path: Path,
    *,
    config: SyntheticEventGeneratorConfig,
) -> SyntheticEventQualityReport:
    """Validate deterministic truth, isolation, labels, and event-level splits."""

    errors: list[str] = []
    canonical_splits: defaultdict[str, set[str]] = defaultdict(set)
    incident_splits: defaultdict[str, set[str]] = defaultdict(set)
    report_splits: defaultdict[str, set[str]] = defaultdict(set)
    report_to_event: dict[str, str] = {}
    event_types_by_id: dict[str, str] = {}
    report_count = 0
    duplicate_count = 0
    split_reports: Counter[str] = Counter()
    scenarios: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    input_isolation = True
    duplicate_cross_event = 0
    for split in SPLITS:
        truth_path = ground_truth_paths[split]
        input_path = detector_input_paths[split]
        with (
            truth_path.open("r", encoding="utf-8") as truth_handle,
            input_path.open("r", encoding="utf-8") as input_handle,
        ):
            line_number = 0
            while True:
                truth_line = truth_handle.readline()
                input_line = input_handle.readline()
                if not truth_line and not input_line:
                    break
                line_number += 1
                if not truth_line or not input_line:
                    errors.append(f"{split}: truth/input line count mismatch")
                    break
                try:
                    raw_input = json.loads(input_line)
                    if FORBIDDEN_DETECTOR_FIELDS.intersection(raw_input):
                        input_isolation = False
                        errors.append(
                            f"{split} row {line_number}: detector input contains hidden fields"
                        )
                    truth = SyntheticEventGroundTruth.model_validate_json(truth_line)
                    detector_input = SyntheticDetectorInput.model_validate(raw_input)
                except Exception as error:  # noqa: BLE001
                    errors.append(
                        f"{split} row {line_number}: {type(error).__name__}: {error}"
                    )
                    continue
                if truth.split != split:
                    errors.append(f"{split} row {line_number}: split mismatch")
                if truth.report_id != detector_input.report_id:
                    errors.append(
                        f"{split} row {line_number}: report identity mismatch"
                    )
                if (
                    truth.timestamp != detector_input.occurred_at
                    or truth.latitude != detector_input.latitude
                    or truth.longitude != detector_input.longitude
                    or truth.source_family != detector_input.source_type
                ):
                    errors.append(
                        f"{split} row {line_number}: visible evidence mismatch"
                    )
                report_id = str(truth.report_id)
                if report_id in report_to_event:
                    errors.append(f"duplicate report id: {report_id}")
                report_to_event[report_id] = truth.canonical_event_id
                event_types_by_id.setdefault(truth.canonical_event_id, truth.event_type)
                if event_types_by_id[truth.canonical_event_id] != truth.event_type:
                    errors.append(
                        f"canonical event has inconsistent type: {truth.canonical_event_id}"
                    )
                canonical_splits[truth.canonical_event_id].add(split)
                incident_splits[truth.incident_id].add(split)
                report_splits[report_id].add(split)
                report_count += 1
                split_reports[split] += 1
                scenarios[truth.scenario_family] += 1
                event_types[truth.event_type] += 1
                languages[truth.language] += 1
                if truth.duplicate_of_report_id is not None:
                    duplicate_count += 1
                    matched = str(truth.duplicate_of_report_id)
                    if (
                        matched in report_to_event
                        and report_to_event[matched] != truth.canonical_event_id
                    ):
                        duplicate_cross_event += 1

    pair_labels: Counter[str] = Counter()
    split_pairs: Counter[str] = Counter()
    pair_count = 0
    seen_pairs: set[tuple[str, str]] = set()
    try:
        with pair_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    pair_payload = json.loads(line)
                    pair_payload.pop("event_type_a", None)
                    pair_payload.pop("event_type_b", None)
                    pair = EventPairAnnotation.model_validate(pair_payload)
                except Exception as error:  # noqa: BLE001
                    errors.append(
                        f"pair row {line_number}: {type(error).__name__}: {error}"
                    )
                    continue
                pair_count += 1
                split = pair.split or "MISSING"
                split_pairs[split] += 1
                pair_labels[pair.label.value] += 1
                key = tuple(sorted((pair.event_a_id, pair.event_b_id)))
                if key in seen_pairs:
                    errors.append(f"duplicate/reversed pair: {'::'.join(key)}")
                seen_pairs.add(key)
                if key[0] not in report_to_event or key[1] not in report_to_event:
                    errors.append(f"pair row {line_number}: unknown report identity")
                    continue
                same = report_to_event[key[0]] == report_to_event[key[1]]
                if pair.label is EventAnnotationLabel.EVENT_MATCH and not same:
                    errors.append(
                        f"pair row {line_number}: invalid EVENT_MATCH identity"
                    )
                if pair.label is EventAnnotationLabel.EVENT_NOT_MATCH and same:
                    errors.append(
                        f"pair row {line_number}: invalid EVENT_NOT_MATCH identity"
                    )
                if pair.label is EventAnnotationLabel.UNCERTAIN and same:
                    errors.append(
                        f"pair row {line_number}: UNCERTAIN cannot hide same identity"
                    )
                if (
                    split not in report_splits[key[0]]
                    or split not in report_splits[key[1]]
                ):
                    errors.append(f"pair row {line_number}: pair split mismatch")
    except OSError as error:
        errors.append(f"pair dataset load failed: {error}")

    canonical_leaks = sum(len(value) > 1 for value in canonical_splits.values())
    incident_leaks = sum(len(value) > 1 for value in incident_splits.values())
    report_leaks = sum(len(value) > 1 for value in report_splits.values())
    expected_reports = config.total_reports
    expected_pairs = config.total_pairs
    if report_count != expected_reports:
        errors.append(
            f"report count mismatch: expected {expected_reports}, found {report_count}"
        )
    if pair_count != expected_pairs:
        errors.append(
            f"pair count mismatch: expected {expected_pairs}, found {pair_count}"
        )
    missing_scenarios = sorted(set(EVENT_SCENARIOS) - set(scenarios))
    missing_types = sorted(set(config.event_types) - set(event_types))
    missing_labels = sorted(
        {item.value for item in EventAnnotationLabel} - set(pair_labels)
    )
    if missing_scenarios:
        errors.append("required scenarios missing: " + ", ".join(missing_scenarios))
    if missing_types:
        errors.append("configured event types missing: " + ", ".join(missing_types))
    if missing_labels:
        errors.append("pair labels missing: " + ", ".join(missing_labels))
    if canonical_leaks:
        errors.append(f"canonical event leakage spans splits: {canonical_leaks}")
    if incident_leaks:
        errors.append(f"incident leakage spans splits: {incident_leaks}")
    if report_leaks:
        errors.append(f"report leakage spans splits: {report_leaks}")
    if duplicate_cross_event:
        errors.append(
            f"duplicate relationships cross event identity: {duplicate_cross_event}"
        )

    file_hashes = {
        **{
            f"ground_truth_{split}": file_sha256(ground_truth_paths[split])
            for split in SPLITS
        },
        **{
            f"detector_inputs_{split}": file_sha256(detector_input_paths[split])
            for split in SPLITS
        },
        "event_pairs": file_sha256(pair_path),
    }
    canonical_split_values = {
        key: next(iter(value))
        for key, value in canonical_splits.items()
        if len(value) == 1
    }
    split_event_counts = {
        split: sum(value == split for value in canonical_split_values.values())
        for split in SPLITS
    }
    invariants = {
        "truth_defined_before_detector": True,
        "detector_inputs_exclude_hidden_fields": input_isolation,
        "canonical_events_do_not_cross_splits": canonical_leaks == 0,
        "reports_do_not_cross_splits": report_leaks == 0,
        "incidents_do_not_cross_splits": incident_leaks == 0,
        "pair_labels_derive_from_generator_identity": not any(
            "invalid EVENT_" in error for error in errors
        ),
        "duplicates_remain_within_event": duplicate_cross_event == 0,
        "all_required_scenarios_present": not missing_scenarios,
        "all_configured_event_types_present": not missing_types,
        "all_pair_labels_present": not missing_labels,
        "random_row_split_absent": True,
        "detector_not_used_for_labels": True,
    }
    if not all(invariants.values()):
        errors.append("one or more synthetic event invariants failed")
    return SyntheticEventQualityReport(
        report_version=REPORT_VERSION,
        valid=not errors,
        generated_at=config.creation_timestamp,
        dataset_sha256=_dataset_hash(file_hashes),
        split_sha256=_split_hash(canonical_split_values),
        file_hashes=dict(sorted(file_hashes.items())),
        generator_version=GENERATOR_VERSION,
        scenario_version=SCENARIO_VERSION,
        split_version=SPLIT_VERSION,
        seed=config.seed,
        report_count=report_count,
        canonical_event_count=len(canonical_splits),
        pair_count=pair_count,
        split_report_counts={split: split_reports[split] for split in SPLITS},
        split_event_counts=split_event_counts,
        split_pair_counts={split: split_pairs[split] for split in SPLITS},
        scenario_counts=dict(sorted(scenarios.items())),
        event_type_counts=dict(sorted(event_types.items())),
        pair_label_counts=dict(sorted(pair_labels.items())),
        language_counts=dict(sorted(languages.items())),
        duplicate_report_count=duplicate_count,
        leakage_checks={
            "canonical_event_cross_split": canonical_leaks,
            "incident_cross_split": incident_leaks,
            "report_cross_split": report_leaks,
            "duplicate_cross_event": duplicate_cross_event,
            "ground_truth_isolation": input_isolation,
            "status": "PASS" if not errors else "FAIL",
        },
        invariant_checks=invariants,
        errors=sorted(set(errors)),
        warnings=[
            "Synthetic event performance is not field or production evidence.",
            "Controlled TextPrediction fixtures are not frozen NLP model inferences.",
        ],
    )


def _write_json_atomic(payload: Any, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        if isinstance(payload, BaseModel):
            encoded = payload.model_dump_json(indent=2).encode("utf-8")
        else:
            encoded = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8")
        handle.write(encoded + b"\n")
    temporary.replace(path)
    return file_sha256(path)


def write_synthetic_event_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticEventGeneratorConfig | None = None,
    overwrite: bool = False,
) -> SyntheticEventArtifacts:
    """Generate isolated truth/input files, validate them, and write a manifest."""

    selected = config or SyntheticEventGeneratorConfig()
    output = local_only_path(
        output_directory, description="synthetic event output directories"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    ground_truth_paths = {
        split: output / f"synthetic_event_ground_truth_{split}.jsonl"
        for split in SPLITS
    }
    detector_input_paths = {
        split: output / f"synthetic_event_detector_inputs_{split}.jsonl"
        for split in SPLITS
    }
    pair_path = output / "synthetic_event_pairs.jsonl"
    quality_path = output / "synthetic_event_quality_report.json"
    manifest_path = output / "synthetic_event_dataset_manifest.json"
    targets = [
        *ground_truth_paths.values(),
        *detector_input_paths.values(),
        pair_path,
        quality_path,
        manifest_path,
    ]
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite generated event artifacts: "
            + ", ".join(path.name for path in existing)
        )

    temporary_paths: dict[Path, Path] = {}
    handles: dict[Path, Any] = {}
    data_targets = [
        *ground_truth_paths.values(),
        *detector_input_paths.values(),
        pair_path,
    ]
    try:
        with ExitStack() as stack:
            for target in data_targets:
                handle = stack.enter_context(
                    tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=output,
                        prefix=target.name + ".",
                        suffix=".tmp",
                        delete=False,
                    )
                )
                temporary_paths[target] = Path(handle.name)
                handles[target] = handle
            for (
                split,
                _,
                _,
                truth_rows,
                input_rows,
                pair_rows,
            ) in iter_generated_batches(selected):
                truth_handle = handles[ground_truth_paths[split]]
                input_handle = handles[detector_input_paths[split]]
                for truth, detector_input in zip(truth_rows, input_rows):
                    truth_handle.write(
                        _canonical_json(truth.model_dump(mode="json")) + b"\n"
                    )
                    input_handle.write(
                        _canonical_json(detector_input.model_dump(mode="json")) + b"\n"
                    )
                pair_handle = handles[pair_path]
                for pair in pair_rows:
                    payload = pair.model_dump(mode="json")
                    # The registered event schema accepts these optional type fields;
                    # identity labels still come exclusively from canonical mapping.
                    left = next(
                        item
                        for item in truth_rows
                        if str(item.report_id) == pair.event_a_id
                    )
                    right = next(
                        item
                        for item in truth_rows
                        if str(item.report_id) == pair.event_b_id
                    )
                    payload["event_type_a"] = left.event_type
                    payload["event_type_b"] = right.event_type
                    pair_handle.write(_canonical_json(payload) + b"\n")
        for target, temporary in temporary_paths.items():
            temporary.replace(target)
        temporary_paths.clear()
    finally:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)

    report = validate_synthetic_event_dataset(
        ground_truth_paths,
        detector_input_paths,
        pair_path,
        config=selected,
    )
    quality_hash = _write_json_atomic(report, quality_path)
    if not report.valid:
        raise ValueError(
            "generated synthetic event dataset failed validation: "
            + "; ".join(report.errors[:20])
        )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_id": selected.dataset_id,
        "dataset_version": selected.dataset_version,
        "created_at": selected.creation_timestamp.isoformat(),
        "dataset_sha256": report.dataset_sha256,
        "split_sha256": report.split_sha256,
        "file_hashes": report.file_hashes,
        "quality_report_file": quality_path.name,
        "quality_report_sha256": quality_hash,
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "template_version": TEMPLATE_VERSION,
        "split_version": SPLIT_VERSION,
        "seed": selected.seed,
        "report_count": report.report_count,
        "canonical_event_count": report.canonical_event_count,
        "pair_count": report.pair_count,
        "split_report_counts": report.split_report_counts,
        "split_event_counts": report.split_event_counts,
        "scenario_counts": report.scenario_counts,
        "event_type_counts": report.event_type_counts,
        "event_types": list(selected.event_types),
        "provenance": "PROJECT_AUTHORED",
        "data_kind": "SYNTHETIC",
        "classification": "DEVELOPMENT_ONLY",
        "production_validation": "NOT_VALIDATED",
        "ground_truth_method": "GENERATOR_CANONICAL_EVENT_ID_BEFORE_DETECTION",
        "detector_used_for_labels": False,
        "random_row_split": False,
        "holdout_strategy": "CANONICAL_EVENT_ID",
        "text_prediction_source": "CONTROLLED_SYNTHETIC_FIXTURES",
        "duplicate_relation_source": "PROJECT_GENERATED_RELATIONSHIPS",
        "models_trained": [],
        "pretrained_models": [],
        "open_weight_models": [],
        "external_apis": [],
        "network_access": False,
    }
    manifest_hash = _write_json_atomic(manifest, manifest_path)
    return SyntheticEventArtifacts(
        output_directory=output,
        ground_truth_paths=ground_truth_paths,
        detector_input_paths=detector_input_paths,
        pair_path=pair_path,
        quality_report_path=quality_path,
        manifest_path=manifest_path,
        dataset_hash=report.dataset_sha256,
        split_hash=report.split_sha256,
        pair_hash=file_sha256(pair_path),
        quality_report_hash=quality_hash,
        manifest_hash=manifest_hash,
        report=report,
        manifest=manifest,
    )


def _registry_relative(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path, registry_path.parent)).as_posix()


def register_synthetic_event_dataset(
    artifacts: SyntheticEventArtifacts,
    *,
    config: SyntheticEventGeneratorConfig,
    registry_path: Path | str,
    replace_existing: bool = False,
):
    """Register the event-pair annotation layer and run common validation."""

    from app.ml.data.dataset_validation import validate_registered_dataset
    from app.ml.data.registry import (
        DatasetClassification,
        DatasetComponent,
        DatasetFormat,
        DatasetProvenance,
        DatasetRegistryRecord,
        DatasetStatus,
        find_dataset,
        load_dataset_registry,
        register_dataset,
    )

    selected_registry = local_only_path(
        registry_path, description="dataset registries"
    ).resolve()
    record = DatasetRegistryRecord(
        dataset_id=config.dataset_id,
        dataset_version=config.dataset_version,
        component=DatasetComponent.EVENT,
        local_path=_registry_relative(artifacts.pair_path, selected_registry),
        format=DatasetFormat.JSONL,
        content_sha256=artifacts.pair_hash,
        schema_version="synthetic-event-pair-dataset-v1",
        label_schema_version="event-pair-labels-v1",
        creation_timestamp=config.creation_timestamp,
        source_description=(
            "Reproducible project-authored synthetic event reports and pair labels. "
            "Canonical event identity is assigned before detector execution."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development and regression use only; prohibited "
            "as field-performance or production-validation evidence."
        ),
        grouping_field="event_definition_hash_a",
        time_field="timestamp",
        split_field="split",
        label_count=artifacts.report.pair_count,
        row_or_image_count=artifacts.report.pair_count,
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_GENERATED_CANONICAL_EVENT_IDENTITY",
        metadata={
            "synthetic": True,
            "synthetic_classification": "SYNTHETIC",
            "production_validation": "NOT_VALIDATED",
            "dataset_hash": artifacts.dataset_hash,
            "pair_dataset_hash": artifacts.pair_hash,
            "split_hash": artifacts.split_hash,
            "generator_version": GENERATOR_VERSION,
            "scenario_version": SCENARIO_VERSION,
            "template_version": TEMPLATE_VERSION,
            "split_version": SPLIT_VERSION,
            "seed": config.seed,
            "report_count": artifacts.report.report_count,
            "canonical_event_count": artifacts.report.canonical_event_count,
            "quality_report_path": _registry_relative(
                artifacts.quality_report_path, selected_registry
            ),
            "quality_report_sha256": artifacts.quality_report_hash,
            "manifest_path": _registry_relative(
                artifacts.manifest_path, selected_registry
            ),
            "manifest_sha256": artifacts.manifest_hash,
            "ground_truth_paths": {
                split: _registry_relative(path, selected_registry)
                for split, path in artifacts.ground_truth_paths.items()
            },
            "detector_input_paths": {
                split: _registry_relative(path, selected_registry)
                for split, path in artifacts.detector_input_paths.items()
            },
            "holdout_strategy": "CANONICAL_EVENT_ID",
            "random_row_split": False,
            "detector_used_for_labels": False,
            "duplicate_model_modified": False,
            "nlp_model_modified": False,
            "models_trained": [],
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        },
    )
    register_dataset(
        record,
        registry_path=selected_registry,
        replace_existing=replace_existing,
        modified_at=config.creation_timestamp,
    )
    validation = validate_registered_dataset(
        config.dataset_id,
        registry_path=selected_registry,
        dataset_version=config.dataset_version,
        generated_at=config.creation_timestamp,
    )
    if not validation.valid:
        raise ValueError(
            "registered synthetic event dataset failed structural validation: "
            + "; ".join(validation.errors[:20])
        )
    return find_dataset(
        load_dataset_registry(selected_registry),
        config.dataset_id,
        config.dataset_version,
    )


__all__ = [
    "DEFAULT_BATCHES_PER_SCENARIO",
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_SEED",
    "EVENT_SCENARIOS",
    "EVENT_TYPES",
    "FORBIDDEN_DETECTOR_FIELDS",
    "GENERATOR_VERSION",
    "LANGUAGES",
    "MANIFEST_VERSION",
    "SCENARIO_VERSION",
    "SPLIT_VERSION",
    "SyntheticDetectorInput",
    "SyntheticEventArtifacts",
    "SyntheticEventGeneratorConfig",
    "SyntheticEventGroundTruth",
    "SyntheticEventQualityReport",
    "generate_scenario_batch",
    "iter_generated_batches",
    "register_synthetic_event_dataset",
    "split_batch_counts",
    "validate_synthetic_event_dataset",
    "write_synthetic_event_dataset",
]
