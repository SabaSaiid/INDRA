"""Local deterministic generator for a synthetic duplicate-pair benchmark.

Ground truth is assigned from explicit scenario identity.  This module never
imports or executes the duplicate matcher.  The generated corpus is suitable
only for development, regression, and controlled local validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.ml.config import file_sha256, local_only_path
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord


GENERATOR_VERSION: Final[str] = "synthetic-duplicate-generator-v1"
SCENARIO_VERSION: Final[str] = "synthetic-duplicate-scenarios-v1"
SPLIT_VERSION: Final[str] = "synthetic-duplicate-generator-splits-v1"
TEMPLATE_VERSION: Final[str] = "synthetic-duplicate-templates-v1"
MANIFEST_VERSION: Final[str] = "synthetic-duplicate-dataset-manifest-v1"
REPORT_VERSION: Final[str] = "synthetic-duplicate-quality-report-v1"
DEFAULT_SEED: Final[int] = 190019
DEFAULT_TOTAL_PAIRS: Final[int] = 100_000
DEFAULT_DATASET_ID: Final[str] = "indra-duplicate-project-synthetic-v1"
DEFAULT_DATASET_VERSION: Final[str] = "synthetic-duplicate-100k-v1"
DEFAULT_CREATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 23, 0, 0, tzinfo=timezone.utc
)

DUPLICATE_SCENARIOS: Final[tuple[str, ...]] = (
    "EASY_DUPLICATE",
    "NEAR_DUPLICATE",
    "PARAPHRASED_DUPLICATE",
    "MINOR_TYPO_DUPLICATE",
    "TIME_VARIATION_DUPLICATE",
    "LOCATION_VARIATION_DUPLICATE_WHEN_VALID",
)
HARD_NEGATIVE_SCENARIOS: Final[tuple[str, ...]] = (
    "SAME_WEATHER_DIFFERENT_EVENT",
    "SAME_LOCATION_DIFFERENT_TIME",
    "SAME_EVENT_TYPE_DIFFERENT_EVENT",
    "SAME_TEXT_DIFFERENT_EVENT",
    "SAME_SOURCE_DIFFERENT_EVENT",
    "SPATIALLY_NEAR_TEMPORALLY_FAR",
    "TEMPORALLY_NEAR_SPATIALLY_FAR",
)
UNCERTAIN_SCENARIOS: Final[tuple[str, ...]] = (
    "AMBIGUOUS_PARTIAL_CONTEXT",
    "CONFLICTING_TIME_LOCATION_BOUNDARY",
)
SCENARIO_LABEL: Final[dict[str, DuplicatePairLabel]] = {
    **{name: DuplicatePairLabel.DUPLICATE for name in DUPLICATE_SCENARIOS},
    **{name: DuplicatePairLabel.NOT_DUPLICATE for name in HARD_NEGATIVE_SCENARIOS},
    **{name: DuplicatePairLabel.UNCERTAIN for name in UNCERTAIN_SCENARIOS},
}

_SPLITS: Final[tuple[str, ...]] = ("train", "validation", "test")
_LANGUAGES: Final[tuple[str, ...]] = ("en", "hi", "hinglish")
_EVENT_TYPES: Final[tuple[str, ...]] = (
    "URBAN_FLOOD",
    "RIVER_BREACH",
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
)
_SOURCE_TYPES: Final[tuple[str, ...]] = (
    "CITIZEN_APP",
    "DISTRICT_HELPLINE",
    "FIELD_OFFICER",
    "SENSOR_RELAY",
)
_LOCATIONS: Final[dict[str, tuple[tuple[str, float, float], ...]]] = {
    "train": (
        ("Patna", 25.5941, 85.1376),
        ("Gaya", 24.7914, 85.0002),
        ("Lucknow", 26.8467, 80.9462),
        ("Jaipur", 26.9124, 75.7873),
        ("Guwahati", 26.1445, 91.7362),
        ("Kochi", 9.9312, 76.2673),
    ),
    "validation": (
        ("Ranchi", 23.3441, 85.3096),
        ("Bhopal", 23.2599, 77.4126),
        ("Surat", 21.1702, 72.8311),
    ),
    "test": (
        ("Cuttack", 20.4625, 85.8830),
        ("Madurai", 9.9252, 78.1198),
        ("Dehradun", 30.3165, 78.0322),
    ),
}
_SPLIT_ORIGINS: Final[dict[str, datetime]] = {
    "train": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "validation": datetime(2026, 5, 1, tzinfo=timezone.utc),
    "test": datetime(2026, 8, 1, tzinfo=timezone.utc),
}


@dataclass(frozen=True, slots=True)
class SyntheticDuplicateGeneratorConfig:
    total_pairs: int = DEFAULT_TOTAL_PAIRS
    seed: int = DEFAULT_SEED
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_version: str = DEFAULT_DATASET_VERSION
    creation_timestamp: datetime = DEFAULT_CREATION_TIMESTAMP
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    duplicate_fraction: float = 0.45
    non_duplicate_fraction: float = 0.45
    uncertain_fraction: float = 0.10

    def __post_init__(self) -> None:
        if self.total_pairs < 300:
            raise ValueError("total_pairs must be at least 300")
        split_total = self.train_fraction + self.validation_fraction + self.test_fraction
        class_total = (
            self.duplicate_fraction
            + self.non_duplicate_fraction
            + self.uncertain_fraction
        )
        if not math.isclose(split_total, 1.0, abs_tol=1e-12):
            raise ValueError("split fractions must sum to one")
        if not math.isclose(class_total, 1.0, abs_tol=1e-12):
            raise ValueError("class fractions must sum to one")
        if min(
            self.train_fraction,
            self.validation_fraction,
            self.test_fraction,
            self.duplicate_fraction,
            self.non_duplicate_fraction,
            self.uncertain_fraction,
        ) <= 0.0:
            raise ValueError("split and class fractions must be positive")
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError("dataset identity cannot be blank")


class SyntheticDuplicateQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str
    valid: bool
    generated_at: datetime
    expected_pair_count: int = Field(ge=0)
    actual_pair_count: int = Field(ge=0)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    scenario_version: str
    split_version: str
    seed: int
    label_counts: dict[str, int]
    split_counts: dict[str, int]
    split_label_counts: dict[str, dict[str, int]]
    scenario_counts: dict[str, int]
    language_counts: dict[str, int]
    leakage_checks: dict[str, int | str]
    invariant_checks: dict[str, bool]
    held_out_combination_count: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    classification: str = "DEVELOPMENT_ONLY"
    provenance: str = "PROJECT_AUTHORED"
    data_kind: str = "SYNTHETIC"
    production_validation: str = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class SyntheticDuplicateArtifacts:
    output_directory: Path
    dataset_path: Path
    report_path: Path
    manifest_path: Path
    dataset_hash: str
    report_hash: str
    manifest_hash: str
    report: SyntheticDuplicateQualityReport
    manifest: dict[str, Any]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _allocate(total: int, weighted_names: tuple[tuple[str, float], ...]) -> dict[str, int]:
    raw = [(name, total * weight) for name, weight in weighted_names]
    counts = {name: int(math.floor(value)) for name, value in raw}
    remainder = total - sum(counts.values())
    order = sorted(raw, key=lambda item: (-(item[1] - math.floor(item[1])), item[0]))
    for name, _ in order[:remainder]:
        counts[name] += 1
    return counts


def _record_rng(config: SyntheticDuplicateGeneratorConfig, *parts: object) -> random.Random:
    material = "|".join((GENERATOR_VERSION, str(config.seed), *(str(x) for x in parts)))
    seed = int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:16], "big")
    return random.Random(seed)


def _uuid(config: SyntheticDuplicateGeneratorConfig, kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{config.dataset_id}|{config.seed}|{kind}|{value}"))


def _offset_coordinate(
    latitude: float,
    longitude: float,
    distance_km: float,
    bearing_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(bearing_degrees)
    latitude_delta = (distance_km / 111.32) * math.cos(angle)
    longitude_scale = max(0.2, math.cos(math.radians(latitude)))
    longitude_delta = (distance_km / (111.32 * longitude_scale)) * math.sin(angle)
    return latitude + latitude_delta, longitude + longitude_delta


def _scenario_geometry(scenario: str, rng: random.Random) -> tuple[float, float]:
    ranges = {
        "EASY_DUPLICATE": ((0.01, 0.08), (0.0, 2.0)),
        "NEAR_DUPLICATE": ((0.08, 0.25), (2.0, 5.0)),
        "PARAPHRASED_DUPLICATE": ((0.15, 0.40), (4.0, 7.0)),
        "MINOR_TYPO_DUPLICATE": ((0.03, 0.15), (1.0, 3.0)),
        "TIME_VARIATION_DUPLICATE": ((0.08, 0.22), (11.0, 14.0)),
        "LOCATION_VARIATION_DUPLICATE_WHEN_VALID": ((0.65, 0.95), (5.0, 10.0)),
        "SAME_WEATHER_DIFFERENT_EVENT": ((0.05, 0.25), (1.0, 5.0)),
        "SAME_LOCATION_DIFFERENT_TIME": ((0.0, 0.03), (150.0, 300.0)),
        "SAME_EVENT_TYPE_DIFFERENT_EVENT": ((1.5, 4.0), (30.0, 75.0)),
        "SAME_TEXT_DIFFERENT_EVENT": ((2.0, 5.0), (90.0, 180.0)),
        "SAME_SOURCE_DIFFERENT_EVENT": ((0.3, 0.8), (60.0, 120.0)),
        "SPATIALLY_NEAR_TEMPORALLY_FAR": ((0.03, 0.20), (180.0, 360.0)),
        "TEMPORALLY_NEAR_SPATIALLY_FAR": ((8.0, 20.0), (1.0, 6.0)),
        "AMBIGUOUS_PARTIAL_CONTEXT": ((0.6, 1.4), (8.0, 22.0)),
        "CONFLICTING_TIME_LOCATION_BOUNDARY": ((0.8, 1.2), (13.0, 20.0)),
    }
    distance, minutes = ranges[scenario]
    return rng.uniform(*distance), rng.uniform(*minutes)


def _event_phrase(language: str, event_type: str) -> str:
    phrases = {
        "en": {
            "URBAN_FLOOD": "street flooding and deep waterlogging",
            "RIVER_BREACH": "river embankment breach with rapid overflow",
            "CLOUDBURST": "cloudburst causing sudden runoff",
            "CYCLONE_INUNDATION": "cyclone surge inundating low-lying roads",
        },
        "hi": {
            "URBAN_FLOOD": "सड़क पर बाढ़ और भारी जलभराव",
            "RIVER_BREACH": "नदी तटबंध टूटने से तेज बहाव",
            "CLOUDBURST": "बादल फटने से अचानक पानी का बहाव",
            "CYCLONE_INUNDATION": "चक्रवाती ज्वार से निचली सड़कें जलमग्न",
        },
        "hinglish": {
            "URBAN_FLOOD": "road flooding aur heavy waterlogging",
            "RIVER_BREACH": "nadi bandh breach se fast overflow",
            "CLOUDBURST": "cloudburst se sudden paani ka flow",
            "CYCLONE_INUNDATION": "cyclone surge se low road inundated",
        },
    }
    return phrases[language][event_type]


def _render_text(
    *,
    language: str,
    event_type: str,
    location: str,
    site: str,
    depth_cm: int,
    reference: str,
    variant: int,
) -> str:
    phrase = _event_phrase(language, event_type)
    if language == "en":
        templates = (
            "{phrase} reported near {location} {site}; water depth {depth} cm; ref {ref}",
            "At {location} {site}, {phrase} is reported with {depth} cm water; ref {ref}",
            "Local update {ref}: {depth} cm water after {phrase} around {location} {site}",
        )
    elif language == "hi":
        templates = (
            "{location} {site} के पास {phrase} की सूचना; पानी {depth} सेमी; संदर्भ {ref}",
            "{location} {site} में {depth} सेमी पानी के साथ {phrase}; संदर्भ {ref}",
            "स्थानीय सूचना {ref}: {location} {site} के आसपास {phrase}, पानी {depth} सेमी",
        )
    else:
        templates = (
            "{location} {site} ke paas {phrase}; paani {depth} cm; ref {ref}",
            "Update {ref}: {location} {site} mein {depth} cm paani, {phrase}",
            "Local report {ref}, {phrase} around {location} {site}, depth {depth} cm",
        )
    return templates[variant % len(templates)].format(
        phrase=phrase,
        location=location,
        site=site,
        depth=depth_cm,
        ref=reference,
    )


def _minor_typo(text: str) -> str:
    chars = list(text)
    candidates = [
        index
        for index, char in enumerate(chars[2:-2], start=2)
        if unicodedata.category(char).startswith("L")
        and unicodedata.category(chars[index + 1]).startswith("L")
    ]
    if not candidates:
        return text + " typo"
    index = candidates[len(candidates) // 2]
    chars[index], chars[index + 1] = chars[index + 1], chars[index]
    return "".join(chars)


def _pair_texts(
    *,
    scenario: str,
    language: str,
    event_a: str,
    event_b: str,
    location_a: str,
    location_b: str,
    site_a: str,
    site_b: str,
    depth: int,
    reference_a: str,
    reference_b: str,
    variant: int,
) -> tuple[str, str]:
    text_a = _render_text(
        language=language,
        event_type=event_a,
        location=location_a,
        site=site_a,
        depth_cm=depth,
        reference=reference_a,
        variant=variant,
    )
    if scenario == "SAME_TEXT_DIFFERENT_EVENT":
        return text_a, text_a
    if scenario == "MINOR_TYPO_DUPLICATE":
        return text_a, _minor_typo(text_a)
    if scenario == "EASY_DUPLICATE":
        return text_a, text_a + " confirmed"
    if scenario in {
        "SAME_WEATHER_DIFFERENT_EVENT",
        "SAME_LOCATION_DIFFERENT_TIME",
        "SPATIALLY_NEAR_TEMPORALLY_FAR",
    }:
        text_b = _render_text(
            language=language,
            event_type=event_b,
            location=location_b,
            site=site_b,
            depth_cm=depth + 1,
            reference=reference_b,
            variant=variant,
        )
    else:
        text_b = _render_text(
            language=language,
            event_type=event_b,
            location=location_b,
            site=site_b,
            depth_cm=depth + (variant % 3),
            reference=reference_b,
            variant=variant + 1,
        )
    return text_a, text_b


def _scenario_records(
    config: SyntheticDuplicateGeneratorConfig,
    *,
    split: str,
    label: DuplicatePairLabel,
    scenario: str,
    ordinal: int,
) -> DuplicatePairRecord:
    rng = _record_rng(config, split, label.value, scenario, ordinal)
    scenario_index = (
        DUPLICATE_SCENARIOS + HARD_NEGATIVE_SCENARIOS + UNCERTAIN_SCENARIOS
    ).index(scenario)
    scenario_span = (
        len(DUPLICATE_SCENARIOS)
        if label is DuplicatePairLabel.DUPLICATE
        else len(HARD_NEGATIVE_SCENARIOS)
        if label is DuplicatePairLabel.NOT_DUPLICATE
        else len(UNCERTAIN_SCENARIOS)
    )
    # Balance every contextual factor *within each scenario*.  Using the class
    # ordinal directly would couple modulo cycles to class-specific scenario
    # counts and could accidentally make event/source values label proxies.
    scenario_ordinal = ordinal // scenario_span
    language = _LANGUAGES[scenario_ordinal % len(_LANGUAGES)]
    event_a = _EVENT_TYPES[
        (scenario_ordinal // len(_LANGUAGES)) % len(_EVENT_TYPES)
    ]
    event_b = event_a
    if scenario in {"SAME_WEATHER_DIFFERENT_EVENT", "SAME_SOURCE_DIFFERENT_EVENT"}:
        event_b = _EVENT_TYPES[(_EVENT_TYPES.index(event_a) + 1) % len(_EVENT_TYPES)]
    source_a = _SOURCE_TYPES[
        (scenario_ordinal // (len(_LANGUAGES) * len(_EVENT_TYPES)))
        % len(_SOURCE_TYPES)
    ]
    source_b = (
        source_a
        if scenario == "SAME_SOURCE_DIFFERENT_EVENT"
        else _SOURCE_TYPES[(_SOURCE_TYPES.index(source_a) + 1) % len(_SOURCE_TYPES)]
    )
    location_pool = _LOCATIONS[split]
    location_name, base_latitude, base_longitude = location_pool[
        (
            scenario_ordinal
            // (len(_LANGUAGES) * len(_EVENT_TYPES) * len(_SOURCE_TYPES))
        )
        % len(location_pool)
    ]
    distance_km, time_delta_minutes = _scenario_geometry(scenario, rng)
    latitude_a = base_latitude + rng.uniform(-0.003, 0.003)
    longitude_a = base_longitude + rng.uniform(-0.003, 0.003)
    latitude_b, longitude_b = _offset_coordinate(
        latitude_a,
        longitude_a,
        distance_km,
        rng.uniform(0.0, 360.0),
    )
    nearby_name = (
        f"{location_name} East"
        if scenario == "LOCATION_VARIATION_DUPLICATE_WHEN_VALID"
        else location_name
    )
    if scenario in {"SAME_EVENT_TYPE_DIFFERENT_EVENT", "SAME_TEXT_DIFFERENT_EVENT", "TEMPORALLY_NEAR_SPATIALLY_FAR"}:
        second_location = location_pool[
            (
                scenario_ordinal
                // (len(_LANGUAGES) * len(_EVENT_TYPES) * len(_SOURCE_TYPES))
                + 1
            )
            % len(location_pool)
        ][0]
    else:
        second_location = nearby_name
    site_a = f"sector-{(ordinal % 97) + 1}-{split[0]}"
    site_b = (
        f"sector-{((ordinal + 31) % 97) + 1}-{split[0]}"
        if scenario in {"SAME_EVENT_TYPE_DIFFERENT_EVENT", "SAME_SOURCE_DIFFERENT_EVENT", "TEMPORALLY_NEAR_SPATIALLY_FAR"}
        else site_a
    )
    split_token = {"train": "TR", "validation": "VA", "test": "TE"}[split]
    reference_a = f"{split_token}-{scenario_index:02d}-{ordinal:06d}-A"
    same_incident = label is DuplicatePairLabel.DUPLICATE
    reference_b = (
        reference_a
        if same_incident
        else f"{split_token}-{scenario_index:02d}-{ordinal:06d}-B"
    )
    text_a, text_b = _pair_texts(
        scenario=scenario,
        language=language,
        event_a=event_a,
        event_b=event_b,
        location_a=location_name,
        location_b=second_location,
        site_a=site_a,
        site_b=site_b,
        depth=20 + (scenario_ordinal % 81),
        reference_a=reference_a,
        reference_b=reference_b,
        variant=(
            scenario_ordinal
            // (
                len(_LANGUAGES)
                * len(_EVENT_TYPES)
                * len(_SOURCE_TYPES)
                * len(location_pool)
            )
        )
        % 3,
    )
    base_time = _SPLIT_ORIGINS[split] + timedelta(
        minutes=(ordinal * 17 + scenario_index * 37) % (90 * 24 * 60)
    )
    occurred_at_b = base_time + timedelta(minutes=time_delta_minutes)
    pair_key = f"{split}|{label.value}|{scenario}|{ordinal}"
    pair_id = f"pair-{_uuid(config, 'pair', pair_key)}"
    report_a_id = _uuid(config, "report-a", pair_key)
    report_b_id = _uuid(config, "report-b", pair_key)
    incident_a = f"incident-{_uuid(config, 'incident-a', pair_key)}"
    incident_b = incident_a if same_incident else f"incident-{_uuid(config, 'incident-b', pair_key)}"
    split_group_id = f"{split}-group-{_uuid(config, 'group', pair_key)}"
    scenario_family = (
        f"{split}:{scenario}:family-{scenario_ordinal // 25:05d}"
    )
    parameter_combination_id = (
        f"{split}:{scenario}:{language}:{event_a}:{source_a}:variant-"
        f"{scenario_ordinal % 997:03d}"
    )
    relationship = (
        "same"
        if scenario in {"EASY_DUPLICATE", "MINOR_TYPO_DUPLICATE", "SAME_TEXT_DIFFERENT_EVENT"}
        else "paraphrase"
        if label is DuplicatePairLabel.DUPLICATE
        else "unknown"
        if label is DuplicatePairLabel.UNCERTAIN
        else "unrelated"
    )
    return DuplicatePairRecord(
        pair_id=pair_id,
        report_a_id=report_a_id,
        report_b_id=report_b_id,
        label=label,
        annotator_id=f"{GENERATOR_VERSION}:scenario-identity",
        annotation_timestamp=config.creation_timestamp,
        annotation_reason=(
            f"Direct scenario identity {scenario}; no matcher- or model-derived label."
        ),
        label_provenance="PROJECT_GENERATED_SYNTHETIC_SCENARIO_IDENTITY",
        event_id_when_known=incident_a if same_incident else None,
        incident_id_when_known=split_group_id,
        text_relationship=relationship,
        temporal_relationship=f"DELTA_MINUTES_{time_delta_minutes:.6f}",
        geographic_relationship=f"DISTANCE_KM_{distance_km:.6f}",
        time_delta_seconds=time_delta_minutes * 60.0,
        distance_km=distance_km,
        latitude_a=latitude_a,
        longitude_a=longitude_a,
        latitude_b=latitude_b,
        longitude_b=longitude_b,
        source_relationship="SAME" if source_a == source_b else "DIFFERENT",
        split=split,
        text_a=text_a,
        text_b=text_b,
        occurred_at_a=base_time,
        occurred_at_b=occurred_at_b,
        language=language,
        event_type_a=event_a,
        event_type_b=event_b,
        source_type_a=source_a,
        source_type_b=source_b,
        incident_a_id=incident_a,
        incident_b_id=incident_b,
        scenario_type=scenario,
        scenario_family=scenario_family,
        split_group_id=split_group_id,
        parameter_combination_id=parameter_combination_id,
        synthetic_generator_version=GENERATOR_VERSION,
        synthetic_generator_seed=config.seed,
    )


def _generation_plan(
    config: SyntheticDuplicateGeneratorConfig,
) -> Iterator[tuple[str, DuplicatePairLabel, str, int]]:
    split_counts = _allocate(
        config.total_pairs,
        (
            ("train", config.train_fraction),
            ("validation", config.validation_fraction),
            ("test", config.test_fraction),
        ),
    )
    label_weights = (
        (DuplicatePairLabel.DUPLICATE.value, config.duplicate_fraction),
        (DuplicatePairLabel.NOT_DUPLICATE.value, config.non_duplicate_fraction),
        (DuplicatePairLabel.UNCERTAIN.value, config.uncertain_fraction),
    )
    scenario_map = {
        DuplicatePairLabel.DUPLICATE: DUPLICATE_SCENARIOS,
        DuplicatePairLabel.NOT_DUPLICATE: HARD_NEGATIVE_SCENARIOS,
        DuplicatePairLabel.UNCERTAIN: UNCERTAIN_SCENARIOS,
    }
    for split in _SPLITS:
        label_counts = _allocate(split_counts[split], label_weights)
        for label in DuplicatePairLabel:
            scenarios = scenario_map[label]
            count = label_counts[label.value]
            for ordinal in range(count):
                yield split, label, scenarios[ordinal % len(scenarios)], ordinal


def generate_pair_records(
    config: SyntheticDuplicateGeneratorConfig | None = None,
) -> Iterator[DuplicatePairRecord]:
    selected = config or SyntheticDuplicateGeneratorConfig()
    for split, label, scenario, ordinal in _generation_plan(selected):
        yield _scenario_records(
            selected,
            split=split,
            label=label,
            scenario=scenario,
            ordinal=ordinal,
        )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def validate_synthetic_duplicate_dataset(
    dataset_path: Path,
    *,
    config: SyntheticDuplicateGeneratorConfig,
) -> SyntheticDuplicateQualityReport:
    pair_ids: set[str] = set()
    unordered_pairs: set[tuple[str, str]] = set()
    report_splits: defaultdict[str, set[str]] = defaultdict(set)
    incident_splits: defaultdict[str, set[str]] = defaultdict(set)
    family_splits: defaultdict[str, set[str]] = defaultdict(set)
    text_splits: defaultdict[str, set[str]] = defaultdict(set)
    combination_splits: defaultdict[str, set[str]] = defaultdict(set)
    labels: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    split_labels: defaultdict[str, Counter[str]] = defaultdict(Counter)
    scenarios: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    errors: list[str] = []
    label_mismatches = 0
    row_count = 0
    with dataset_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = DuplicatePairRecord.model_validate_json(line)
            except Exception as error:  # noqa: BLE001 - quality report captures all failures
                errors.append(f"row {line_number}: {type(error).__name__}: {error}")
                continue
            row_count += 1
            split = record.split or "MISSING"
            pair_key = tuple(sorted((str(record.report_a_id), str(record.report_b_id))))
            if record.pair_id in pair_ids:
                errors.append(f"duplicate pair id: {record.pair_id}")
            pair_ids.add(record.pair_id)
            if pair_key in unordered_pairs:
                errors.append(f"duplicate or reversed pair: {'::'.join(pair_key)}")
            unordered_pairs.add(pair_key)
            for report_id in pair_key:
                report_splits[report_id].add(split)
            for incident in (record.incident_a_id, record.incident_b_id):
                if incident:
                    incident_splits[incident].add(split)
            if record.scenario_family:
                family_splits[record.scenario_family].add(split)
            if record.parameter_combination_id:
                combination_splits[record.parameter_combination_id].add(split)
            for text in (record.text_a, record.text_b):
                if text:
                    text_splits[_normalize_text(text)].add(split)
            expected_label = SCENARIO_LABEL.get(record.scenario_type or "")
            if expected_label is not record.label:
                label_mismatches += 1
            labels[record.label.value] += 1
            splits[split] += 1
            split_labels[split][record.label.value] += 1
            scenarios[record.scenario_type or "MISSING"] += 1
            languages[record.language or "MISSING"] += 1

    def leak_count(values: dict[str, set[str]]) -> int:
        return sum(len(found) > 1 for found in values.values())

    report_leaks = leak_count(report_splits)
    incident_leaks = leak_count(incident_splits)
    family_leaks = leak_count(family_splits)
    text_leaks = leak_count(text_splits)
    combination_leaks = leak_count(combination_splits)
    if row_count != config.total_pairs:
        errors.append(
            f"pair count mismatch: expected {config.total_pairs}, found {row_count}"
        )
    if label_mismatches:
        errors.append(f"{label_mismatches} labels do not match scenario identity")
    for name, count in (
        ("report", report_leaks),
        ("incident", incident_leaks),
        ("scenario family", family_leaks),
        ("exact text", text_leaks),
        ("parameter combination", combination_leaks),
    ):
        if count:
            errors.append(f"{name} leakage spans splits: {count}")
    missing_scenarios = sorted(set(SCENARIO_LABEL) - set(scenarios))
    if missing_scenarios:
        errors.append("required scenarios missing: " + ", ".join(missing_scenarios))
    missing_languages = sorted(set(_LANGUAGES) - set(languages))
    if missing_languages:
        errors.append("required languages missing: " + ", ".join(missing_languages))
    held_out = len(
        {
            key
            for key, found_splits in combination_splits.items()
            if found_splits == {"test"}
        }
    )
    invariants = {
        "labels_come_from_scenario_identity": label_mismatches == 0,
        "all_required_scenarios_present": not missing_scenarios,
        "all_required_languages_present": not missing_languages,
        "no_report_reuse_across_splits": report_leaks == 0,
        "no_reversed_pairs": len(unordered_pairs) == row_count,
        "no_incident_leakage": incident_leaks == 0,
        "no_scenario_family_leakage": family_leaks == 0,
        "no_exact_text_leakage": text_leaks == 0,
        "test_has_held_out_combinations": held_out > 0,
        "matcher_not_used_for_labels": True,
    }
    if not all(invariants.values()):
        errors.append("one or more dataset invariants failed")
    return SyntheticDuplicateQualityReport(
        report_version=REPORT_VERSION,
        valid=not errors,
        generated_at=config.creation_timestamp,
        expected_pair_count=config.total_pairs,
        actual_pair_count=row_count,
        dataset_sha256=file_sha256(dataset_path),
        generator_version=GENERATOR_VERSION,
        scenario_version=SCENARIO_VERSION,
        split_version=SPLIT_VERSION,
        seed=config.seed,
        label_counts=dict(sorted(labels.items())),
        split_counts={name: splits[name] for name in _SPLITS},
        split_label_counts={
            name: dict(sorted(split_labels[name].items())) for name in _SPLITS
        },
        scenario_counts=dict(sorted(scenarios.items())),
        language_counts=dict(sorted(languages.items())),
        leakage_checks={
            "report_cross_split": report_leaks,
            "incident_cross_split": incident_leaks,
            "scenario_family_cross_split": family_leaks,
            "exact_text_cross_split": text_leaks,
            "parameter_combination_cross_split": combination_leaks,
            "reversed_or_duplicate_pairs": row_count - len(unordered_pairs),
            "status": "PASS" if not errors else "FAIL",
        },
        invariant_checks=invariants,
        held_out_combination_count=held_out,
        errors=sorted(set(errors)),
        warnings=[
            "Synthetic scenario performance is not field or production evidence."
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


def write_synthetic_duplicate_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticDuplicateGeneratorConfig | None = None,
    overwrite: bool = False,
) -> SyntheticDuplicateArtifacts:
    """Generate, validate, hash, and manifest one immutable pair corpus."""

    selected = config or SyntheticDuplicateGeneratorConfig()
    output = local_only_path(
        output_directory, description="synthetic duplicate output directories"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    dataset_path = output / "synthetic_duplicate_pairs.jsonl"
    report_path = output / "synthetic_duplicate_quality_report.json"
    manifest_path = output / "synthetic_duplicate_dataset_manifest.json"
    targets = (dataset_path, report_path, manifest_path)
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite generated artifacts: "
            + ", ".join(path.name for path in existing)
        )

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output,
            prefix=dataset_path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for record in generate_pair_records(selected):
                handle.write(
                    _canonical_json(record.model_dump(mode="json")) + b"\n"
                )
        temporary.replace(dataset_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    report = validate_synthetic_duplicate_dataset(dataset_path, config=selected)
    report_hash = _write_json_atomic(report, report_path)
    if not report.valid:
        raise ValueError(
            "generated synthetic duplicate dataset failed validation: "
            + "; ".join(report.errors)
        )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_id": selected.dataset_id,
        "dataset_version": selected.dataset_version,
        "created_at": selected.creation_timestamp.isoformat(),
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "template_version": TEMPLATE_VERSION,
        "split_version": SPLIT_VERSION,
        "seed": selected.seed,
        "total_pairs": selected.total_pairs,
        "split_counts": report.split_counts,
        "label_counts": report.label_counts,
        "dataset_file": dataset_path.name,
        "dataset_sha256": report.dataset_sha256,
        "quality_report_file": report_path.name,
        "quality_report_sha256": report_hash,
        "provenance": "PROJECT_AUTHORED",
        "data_kind": "SYNTHETIC",
        "classification": "DEVELOPMENT_ONLY",
        "production_validation": "NOT_VALIDATED",
        "label_source": "GENERATOR_SCENARIO_IDENTITY",
        "matcher_used_for_labels": False,
        "random_row_split": False,
        "holdout_strategy": "GROUPED_GENERATOR_LEVEL_SEPARATION",
        "models_trained": [],
        "pretrained_models": [],
        "open_weight_models": [],
        "external_apis": [],
        "network_access": False,
    }
    manifest_hash = _write_json_atomic(manifest, manifest_path)
    return SyntheticDuplicateArtifacts(
        output_directory=output,
        dataset_path=dataset_path,
        report_path=report_path,
        manifest_path=manifest_path,
        dataset_hash=report.dataset_sha256,
        report_hash=report_hash,
        manifest_hash=manifest_hash,
        report=report,
        manifest=manifest,
    )


def _registry_relative(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path, registry_path.parent)).as_posix()


def register_synthetic_duplicate_dataset(
    artifacts: SyntheticDuplicateArtifacts,
    *,
    config: SyntheticDuplicateGeneratorConfig,
    registry_path: Path | str,
    replace_existing: bool = False,
):
    """Register and structurally validate the development-only pair corpus."""

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
        component=DatasetComponent.DUPLICATE,
        local_path=_registry_relative(artifacts.dataset_path, selected_registry),
        format=DatasetFormat.JSONL,
        content_sha256=artifacts.dataset_hash,
        schema_version="synthetic-duplicate-pair-dataset-v1",
        label_schema_version="duplicate-pair-labels-v1",
        creation_timestamp=config.creation_timestamp,
        source_description=(
            "Reproducible project-generated synthetic English, Hindi, and "
            "Hinglish duplicate pairs. Labels are direct scenario identity, "
            "not matcher output. This corpus is development-only."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development and regression use only; prohibited "
            "as field-performance or production-validation evidence."
        ),
        grouping_field="split_group_id",
        time_field="occurred_at_a",
        split_field="split",
        label_count=config.total_pairs,
        row_or_image_count=config.total_pairs,
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_GENERATED_SYNTHETIC_SCENARIO_IDENTITY",
        metadata={
            "synthetic": True,
            "synthetic_classification": "SYNTHETIC",
            "production_validation": "NOT_VALIDATED",
            "dataset_hash": artifacts.dataset_hash,
            "generator_version": GENERATOR_VERSION,
            "scenario_version": SCENARIO_VERSION,
            "template_version": TEMPLATE_VERSION,
            "split_version": SPLIT_VERSION,
            "seed": config.seed,
            "quality_report_path": _registry_relative(
                artifacts.report_path, selected_registry
            ),
            "quality_report_sha256": artifacts.report_hash,
            "manifest_path": _registry_relative(
                artifacts.manifest_path, selected_registry
            ),
            "manifest_sha256": artifacts.manifest_hash,
            "holdout_strategy": "GROUPED_GENERATOR_LEVEL_SEPARATION",
            "random_row_split": False,
            "matcher_used_for_labels": False,
            "nlp_v3_modified": False,
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
            "registered synthetic duplicate dataset failed structural validation: "
            + "; ".join(validation.errors)
        )
    return find_dataset(
        load_dataset_registry(selected_registry),
        config.dataset_id,
        config.dataset_version,
    )


__all__ = [
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_SEED",
    "DEFAULT_TOTAL_PAIRS",
    "DUPLICATE_SCENARIOS",
    "GENERATOR_VERSION",
    "HARD_NEGATIVE_SCENARIOS",
    "MANIFEST_VERSION",
    "SCENARIO_LABEL",
    "SCENARIO_VERSION",
    "SPLIT_VERSION",
    "SyntheticDuplicateArtifacts",
    "SyntheticDuplicateGeneratorConfig",
    "SyntheticDuplicateQualityReport",
    "UNCERTAIN_SCENARIOS",
    "generate_pair_records",
    "register_synthetic_duplicate_dataset",
    "validate_synthetic_duplicate_dataset",
    "write_synthetic_duplicate_dataset",
]
