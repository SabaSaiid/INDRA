"""Structured scenario contracts for project-generated synthetic NLP data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal, TypeAlias

EventType: TypeAlias = Literal[
    "URBAN_FLOOD",
    "RIVER_BREACH",
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
    "NOT_RELEVANT",
]
Language: TypeAlias = Literal["English", "Hindi", "Hinglish"]
DatasetSplit: TypeAlias = Literal["train", "validation", "test"]
NoiseProfile: TypeAlias = Literal["NONE", "LOW", "MEDIUM", "HIGH"]

PRIMARY_CLASSES: Final[tuple[EventType, ...]] = (
    "URBAN_FLOOD",
    "RIVER_BREACH",
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
    "NOT_RELEVANT",
)
LANGUAGES: Final[tuple[Language, ...]] = ("English", "Hindi", "Hinglish")
DATASET_SPLITS: Final[tuple[DatasetSplit, ...]] = (
    "train",
    "validation",
    "test",
)
NOISE_PROFILES: Final[tuple[NoiseProfile, ...]] = (
    "NONE",
    "LOW",
    "MEDIUM",
    "HIGH",
)

HARD_NEGATIVE_TYPES: Final[dict[EventType, str]] = {
    "URBAN_FLOOD": "URBAN_DRAINAGE_NOT_RIVER_FAILURE",
    "RIVER_BREACH": "RIVER_FAILURE_NOT_URBAN_DRAINAGE",
    "CLOUDBURST": "LOCALIZED_DOWNPOUR_NOT_GENERIC_WATERLOGGING",
    "CYCLONE_INUNDATION": "CYCLONE_SURGE_NOT_ROUTINE_URBAN_FLOOD",
    "NOT_RELEVANT": "WEATHER_MENTION_WITHOUT_OBSERVED_EVENT",
}


@dataclass(frozen=True, slots=True)
class SyntheticScenario:
    """One fully specified scenario from which a report is rendered."""

    scenario_id: str
    record_id: str
    event_type: EventType
    concept: str
    scenario_family: str
    location: str
    event_time: str
    rain_intensity: str
    water_depth_cm: int | None
    river_condition: str
    storm_condition: str
    cyclone_context: str
    language: Language
    severity: str
    source_style: str
    noise_profile: NoiseProfile
    split: DatasetSplit
    template_id: str
    parameter_combination_id: str
    hard_negative: bool
    hard_negative_type: str | None
    generator_version: str
    scenario_version: str
    template_version: str
    split_version: str
    seed: int
    ordinal: int
    label_origin: Literal["GENERATOR_SCENARIO_SPECIFICATION"] = (
        "GENERATOR_SCENARIO_SPECIFICATION"
    )

    def as_metadata(self) -> dict[str, object]:
        """Return canonical JSON-compatible metadata without generated text."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SyntheticNLPRecord:
    """Compact released row consumed by downstream development tooling."""

    record_id: str
    text: str
    event_type: EventType
    language: Language
    split: DatasetSplit
    scenario_id: str
    event_time: str
    template_id: str
    parameter_combination_id: str
    noise_profile: NoiseProfile
    hard_negative: bool
    label_origin: Literal["GENERATOR_SCENARIO_SPECIFICATION"] = (
        "GENERATOR_SCENARIO_SPECIFICATION"
    )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


__all__ = [
    "DATASET_SPLITS",
    "HARD_NEGATIVE_TYPES",
    "LANGUAGES",
    "NOISE_PROFILES",
    "PRIMARY_CLASSES",
    "DatasetSplit",
    "EventType",
    "Language",
    "NoiseProfile",
    "SyntheticNLPRecord",
    "SyntheticScenario",
]
