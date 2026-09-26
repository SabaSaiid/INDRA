"""Deterministic Phase 21 credibility-risk synthetic benchmark generator.

Generator-only scenario identity defines the labels.  Hidden truth and the
detector-visible assessment-time evidence are written to different files.  No
credibility detector, learned model, external service, or network resource is
used to create labels or examples.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.ml.components.credibility_features import credibility_input_from_report
from app.ml.config import file_sha256, local_only_path
from app.ml.contracts import (
    CredibilityRiskInput,
    DuplicatePrediction,
    PredictionStatus,
    ReportInput,
)
from app.ml.data.fake_report_annotations import (
    AnnotationEvidence,
    FakeReportAnnotation,
    FakeReportLabel,
)

GENERATOR_VERSION: Final[str] = "synthetic-credibility-generator-v1"
SCENARIO_VERSION: Final[str] = "synthetic-credibility-scenarios-v1"
SPLIT_VERSION: Final[str] = "synthetic-credibility-grouped-splits-v1"
TEMPLATE_VERSION: Final[str] = "synthetic-credibility-templates-v1"
MANIFEST_VERSION: Final[str] = "synthetic-credibility-dataset-manifest-v1"
REPORT_VERSION: Final[str] = "synthetic-credibility-quality-report-v1"
DEFAULT_SEED: Final[int] = 210021
DEFAULT_REPORTS_PER_SCENARIO: Final[int] = 7_200
DEFAULT_DATASET_ID: Final[str] = "indra-credibility-project-synthetic-v1"
DEFAULT_DATASET_VERSION: Final[str] = "synthetic-credibility-100800-v1"
DEFAULT_CREATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 24, 0, 0, tzinfo=timezone.utc
)

PRIMARY_SCENARIOS: Final[tuple[str, ...]] = (
    "AUTHENTIC_CONSISTENT",
    "AUTHENTIC_EXTREME_BUT_PLAUSIBLE",
    "CONTRADICTORY_TIME",
    "CONTRADICTORY_LOCATION",
    "CONTRADICTORY_EVENT_CONTEXT",
    "MISLEADING_OMISSION",
    "MISLEADING_CONTEXT",
    "REPEATED_COPYING",
    "IMPOSSIBLE_METADATA",
    "SOURCE_BEHAVIOR_ANOMALY",
    "UNCERTAIN_AMBIGUOUS",
)
HARD_NEGATIVE_SCENARIOS: Final[tuple[str, ...]] = (
    "AUTHENTIC_WITH_INCOMPLETE_METADATA",
    "LEGITIMATE_DUPLICATE",
    "LEGITIMATE_EVENT_CONFLICT",
)
CREDIBILITY_SCENARIOS: Final[tuple[str, ...]] = (
    *PRIMARY_SCENARIOS[:-1],
    *HARD_NEGATIVE_SCENARIOS,
    PRIMARY_SCENARIOS[-1],
)
SCENARIO_LABELS: Final[dict[str, FakeReportLabel]] = {
    "AUTHENTIC_CONSISTENT": FakeReportLabel.AUTHENTIC,
    "AUTHENTIC_EXTREME_BUT_PLAUSIBLE": FakeReportLabel.AUTHENTIC,
    "AUTHENTIC_WITH_INCOMPLETE_METADATA": FakeReportLabel.AUTHENTIC,
    "LEGITIMATE_DUPLICATE": FakeReportLabel.AUTHENTIC,
    "LEGITIMATE_EVENT_CONFLICT": FakeReportLabel.AUTHENTIC,
    "CONTRADICTORY_TIME": FakeReportLabel.MISLEADING,
    "CONTRADICTORY_LOCATION": FakeReportLabel.MISLEADING,
    "CONTRADICTORY_EVENT_CONTEXT": FakeReportLabel.MISLEADING,
    "MISLEADING_OMISSION": FakeReportLabel.MISLEADING,
    "MISLEADING_CONTEXT": FakeReportLabel.MISLEADING,
    "REPEATED_COPYING": FakeReportLabel.MISLEADING,
    "IMPOSSIBLE_METADATA": FakeReportLabel.MISLEADING,
    "SOURCE_BEHAVIOR_ANOMALY": FakeReportLabel.MISLEADING,
    "UNCERTAIN_AMBIGUOUS": FakeReportLabel.UNCERTAIN,
}
SPLITS: Final[tuple[str, ...]] = ("train", "validation", "test")
LANGUAGES: Final[tuple[str, ...]] = ("English", "Hindi", "Hinglish")
FAMILY_SIZE: Final[int] = 4
FORBIDDEN_DETECTOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "label",
        "ground_truth_label",
        "scenario",
        "scenario_category",
        "hidden_authenticity_flag",
        "canonical_event_id",
        "hidden_event_identity",
        "report_family_id",
        "template_id",
        "parameter_combination_id",
        "generated_adjudication_label",
        "language",
        "split",
    }
)

_SPLIT_ORIGINS: Final[dict[str, datetime]] = {
    "train": datetime(2021, 1, 1, tzinfo=timezone.utc),
    "validation": datetime(2031, 1, 1, tzinfo=timezone.utc),
    "test": datetime(2037, 1, 1, tzinfo=timezone.utc),
}
_SPLIT_LOCATIONS: Final[
    dict[str, tuple[tuple[str, float, float], ...]]
] = {
    "train": (
        ("Patna", 25.5941, 85.1376),
        ("Lucknow", 26.8467, 80.9462),
        ("Guwahati", 26.1445, 91.7362),
        ("Jaipur", 26.9124, 75.7873),
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
_SPLIT_OPENINGS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "train": {
        "English": ("Local update", "Ward note", "Field message"),
        "Hindi": ("स्थानीय सूचना", "वार्ड रिपोर्ट", "मैदानी संदेश"),
        "Hinglish": ("Local khabar", "Ward update", "Field se message"),
    },
    "validation": {
        "English": ("District bulletin", "Area observation", "Resident note"),
        "Hindi": ("जिला बुलेटिन", "क्षेत्रीय अवलोकन", "निवासी सूचना"),
        "Hinglish": ("District khabar", "Area observation", "Resident ka note"),
    },
    "test": {
        "English": ("Community report", "Sector account", "Response note"),
        "Hindi": ("सामुदायिक रिपोर्ट", "सेक्टर विवरण", "प्रतिक्रिया सूचना"),
        "Hinglish": ("Community report", "Sector ka haal", "Response team note"),
    },
}
_SCENARIO_TEXT: Final[dict[str, dict[str, str]]] = {
    "AUTHENTIC_CONSISTENT": {
        "English": "waterlogging is visible near the market and traffic is moving slowly",
        "Hindi": "बाजार के पास जलभराव दिख रहा है और यातायात धीरे चल रहा है",
        "Hinglish": "market ke paas waterlogging hai aur traffic dheere chal raha hai",
    },
    "AUTHENTIC_EXTREME_BUT_PLAUSIBLE": {
        "English": "urgent confirmed rainfall reached 190 mm and three roads remain closed",
        "Hindi": "तत्काल पुष्टि के अनुसार 190 मिमी वर्षा हुई और तीन सड़कें बंद हैं",
        "Hinglish": "urgent confirmed 190 mm baarish hui aur three roads band hain",
    },
    "AUTHENTIC_WITH_INCOMPLETE_METADATA": {
        "English": "residents report ankle deep water beside the bus stand",
        "Hindi": "निवासियों ने बस अड्डे के पास टखने तक पानी बताया",
        "Hinglish": "residents ne bus stand ke paas ankle deep paani bataya",
    },
    "LEGITIMATE_DUPLICATE": {
        "English": "several residents shared the same verified road closure notice",
        "Hindi": "कई निवासियों ने वही सत्यापित सड़क बंद होने की सूचना साझा की",
        "Hinglish": "kai residents ne same verified road closure notice share kiya",
    },
    "LEGITIMATE_EVENT_CONFLICT": {
        "English": "field staff observed runoff while the provisional event tag differs",
        "Hindi": "मैदानी कर्मियों ने बहाव देखा जबकि प्रारंभिक घटना टैग अलग है",
        "Hinglish": "field staff ne runoff dekha par provisional event tag alag hai",
    },
    "CONTRADICTORY_TIME": {
        "English": "the report claims the flooding occurred after this message was submitted",
        "Hindi": "रिपोर्ट में बाढ़ का समय संदेश जमा होने के बाद का बताया गया है",
        "Hinglish": "report bolti hai flooding message submit hone ke baad hui",
    },
    "CONTRADICTORY_LOCATION": {
        "English": "the named locality conflicts with the supplied map position",
        "Hindi": "बताया गया इलाका दिए गए मानचित्र स्थान से मेल नहीं खाता",
        "Hinglish": "named locality supplied map location se match nahi karti",
    },
    "CONTRADICTORY_EVENT_CONTEXT": {
        "English": "official confirmed proof says river breach although event evidence indicates street runoff",
        "Hindi": "आधिकारिक पुष्टि नदी टूटने का दावा करती है जबकि घटना साक्ष्य सड़क बहाव दिखाता है",
        "Hinglish": "official confirmed proof river breach bolta hai par event evidence street runoff hai",
    },
    "MISLEADING_OMISSION": {
        "English": "all clear",
        "Hindi": "सब ठीक",
        "Hinglish": "sab clear",
    },
    "MISLEADING_CONTEXT": {
        "English": "urgent official proof 999 definitely share now",
        "Hindi": "तत्काल आधिकारिक प्रमाण 999 अभी जरूर साझा करें",
        "Hinglish": "urgent official proof 999 abhi definitely share karo",
    },
    "REPEATED_COPYING": {
        "English": "urgent flood alert copy now",
        "Hindi": "तत्काल बाढ़ चेतावनी अभी कॉपी करें",
        "Hinglish": "urgent flood alert abhi copy karo",
    },
    "IMPOSSIBLE_METADATA": {
        "English": "a road inundation report arrived with impossible map metadata",
        "Hindi": "सड़क जलभराव रिपोर्ट असंभव मानचित्र मेटाडेटा के साथ आई",
        "Hinglish": "road inundation report impossible map metadata ke saath aayi",
    },
    "SOURCE_BEHAVIOR_ANOMALY": {
        "English": "one source submitted another nearly identical high volume incident notice",
        "Hindi": "एक स्रोत ने फिर लगभग समान बड़ी संख्या वाली घटना सूचना भेजी",
        "Hinglish": "ek source ne phir nearly identical high volume incident notice bheja",
    },
    "UNCERTAIN_AMBIGUOUS": {
        "English": "details are mixed and additional local confirmation is needed",
        "Hindi": "विवरण मिश्रित हैं और अतिरिक्त स्थानीय पुष्टि आवश्यक है",
        "Hinglish": "details mixed hain aur extra local confirmation chahiye",
    },
}


@dataclass(frozen=True, slots=True)
class SyntheticCredibilityGeneratorConfig:
    reports_per_scenario: int = DEFAULT_REPORTS_PER_SCENARIO
    scenario_report_counts: tuple[tuple[str, int], ...] | None = None
    seed: int = DEFAULT_SEED
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_version: str = DEFAULT_DATASET_VERSION
    creation_timestamp: datetime = DEFAULT_CREATION_TIMESTAMP
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    family_size: int = FAMILY_SIZE

    def __post_init__(self) -> None:
        if self.reports_per_scenario < 80:
            raise ValueError("reports_per_scenario must be at least 80")
        if self.family_size != FAMILY_SIZE:
            raise ValueError("Phase 21 uses four-report generator families")
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        if not math.isclose(
            self.train_fraction + self.validation_fraction + self.test_fraction,
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("split fractions must sum to one")
        if min(self.train_fraction, self.validation_fraction, self.test_fraction) <= 0:
            raise ValueError("split fractions must be positive")
        counts = self.scenario_counts
        if set(counts) != set(CREDIBILITY_SCENARIOS):
            raise ValueError("scenario_report_counts must cover every Phase 21 scenario")
        if any(value < 20 or value % self.family_size for value in counts.values()):
            raise ValueError("scenario counts must be >=20 and divisible by family_size")
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError("dataset identity cannot be blank")

    @property
    def scenario_counts(self) -> dict[str, int]:
        if self.scenario_report_counts is None:
            return {
                scenario: self.reports_per_scenario
                for scenario in CREDIBILITY_SCENARIOS
            }
        return dict(self.scenario_report_counts)

    @property
    def total_reports(self) -> int:
        return sum(self.scenario_counts.values())


class SyntheticCredibilityGroundTruth(BaseModel):
    """Generator-only truth; never accepted by the detector input schema."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    ground_truth_label: FakeReportLabel
    scenario_category: str = Field(min_length=1)
    hidden_authenticity_flag: Literal["AUTHENTIC", "MISLEADING", "UNRESOLVED"]
    canonical_event_id: str = Field(min_length=1)
    report_family_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    parameter_combination_id: str = Field(min_length=1)
    generated_adjudication_label: FakeReportLabel
    language: Literal["English", "Hindi", "Hinglish"]
    split: Literal["train", "validation", "test"]
    failure_reason_group: str = Field(min_length=1)
    family_ordinal: int = Field(ge=0)
    report_ordinal: int = Field(ge=0, lt=FAMILY_SIZE)


class SyntheticCredibilityDetectorInput(BaseModel):
    """Only assessment-time fields permitted to reach credibility features."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    report_text: str = Field(min_length=1)
    occurred_at: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_type: str = Field(min_length=1)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    duplicate_prediction: DuplicatePrediction | None = None

    def to_risk_input(self) -> CredibilityRiskInput:
        report = ReportInput(
            report_id=self.report_id,
            text=self.report_text,
            occurred_at=self.occurred_at,
            latitude=self.latitude,
            longitude=self.longitude,
            source_type=self.source_type,
            source_metadata=self.source_metadata,
        )
        return credibility_input_from_report(
            report,
            duplicate_prediction=self.duplicate_prediction,
        )


class SyntheticCredibilityQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str
    valid: bool
    generated_at: datetime
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_hashes: dict[str, str]
    generator_version: str
    scenario_version: str
    split_version: str
    template_version: str
    seed: int
    report_count: int = Field(ge=0)
    split_counts: dict[str, int]
    label_counts: dict[str, int]
    split_label_counts: dict[str, dict[str, int]]
    scenario_counts: dict[str, int]
    language_counts: dict[str, int]
    hard_negative_counts: dict[str, int]
    leakage_checks: dict[str, int | str | bool]
    isolation_checks: dict[str, int | str | bool]
    invariant_checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: Literal["PROJECT_AUTHORED"] = "PROJECT_AUTHORED"
    data_kind: Literal["SYNTHETIC"] = "SYNTHETIC"
    classification: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    semantic_target: Literal["MISLEADING_RISK_EVIDENCE"] = (
        "MISLEADING_RISK_EVIDENCE"
    )
    truth_probability_claimed: Literal[False] = False
    production_validation: Literal["NOT_VALIDATED"] = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class SyntheticCredibilityArtifacts:
    output_directory: Path
    ground_truth_paths: dict[str, Path]
    detector_input_paths: dict[str, Path]
    annotation_path: Path
    quality_report_path: Path
    manifest_path: Path
    dataset_hash: str
    split_hash: str
    annotation_hash: str
    quality_report_hash: str
    manifest_hash: str
    report: SyntheticCredibilityQualityReport
    manifest: dict[str, Any]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _uuid(config: SyntheticCredibilityGeneratorConfig, kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"indra:{config.seed}:credibility:{kind}:{value}")


def _rng(config: SyntheticCredibilityGeneratorConfig, *parts: object) -> random.Random:
    material = "|".join((str(config.seed), *(str(part) for part in parts)))
    return random.Random(int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:16], 16))


def _letters(value: int) -> str:
    result = ""
    selected = value
    while True:
        selected, remainder = divmod(selected, 26)
        result = chr(ord("a") + remainder) + result
        if selected == 0:
            return result
        selected -= 1


def _allocate(total: int, weights: tuple[tuple[str, float], ...]) -> dict[str, int]:
    raw = {name: total * weight for name, weight in weights}
    allocated = {name: int(value) for name, value in raw.items()}
    remainder = total - sum(allocated.values())
    order = sorted(weights, key=lambda item: (-(raw[item[0]] % 1.0), item[0]))
    for index in range(remainder):
        allocated[order[index][0]] += 1
    return allocated


def split_family_counts(
    config: SyntheticCredibilityGeneratorConfig,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    weights = (
        ("train", config.train_fraction),
        ("validation", config.validation_fraction),
        ("test", config.test_fraction),
    )
    for scenario, report_count in config.scenario_counts.items():
        family_count = report_count // config.family_size
        allocation = _allocate(family_count, weights)
        if any(value == 0 for value in allocation.values()):
            raise ValueError("every scenario requires families in all three splits")
        result[scenario] = allocation
    return result


def _duplicate_prediction(
    *,
    is_duplicate: bool,
    similarity: float,
) -> DuplicatePrediction:
    return DuplicatePrediction(
        status=PredictionStatus.AVAILABLE,
        model_version="project-authored-synthetic-duplicate-fixture-v1",
        feature_version="synthetic-observation-context-v1",
        preprocessing_version="none",
        is_duplicate=is_duplicate,
        similarity=round(similarity, 6),
        candidate_count=1,
        comparisons_performed=1,
        method="PROJECT_AUTHORED_SYNTHETIC_FIXTURE_NOT_FROZEN_MATCHER_INFERENCE",
        warnings=["Synthetic observation context; duplicate matcher v1 was not invoked."],
    )


def _base_metadata(
    occurred_at: datetime,
    latitude: float,
    longitude: float,
    jitter: float,
) -> dict[str, Any]:
    return {
        "submitted_at": (occurred_at + timedelta(minutes=18)).isoformat(),
        "reported_latitude": round(latitude + jitter, 6),
        "reported_longitude": round(longitude - jitter, 6),
        "duplicate_cluster_size": 1,
        "source_recent_report_count": 4,
        "source_recent_duplicate_count": 0,
        "phone_count": 0,
        "location_consistency": True,
        "event_type_consistency": True,
    }


def _scenario_evidence(
    scenario: str,
    *,
    occurred_at: datetime,
    latitude: float,
    longitude: float,
    report_ordinal: int,
    family_ordinal: int,
    rng: random.Random,
) -> tuple[dict[str, Any], DuplicatePrediction, str]:
    jitter = rng.uniform(-0.002, 0.002)
    metadata = _base_metadata(occurred_at, latitude, longitude, jitter)
    duplicate = _duplicate_prediction(is_duplicate=False, similarity=0.18 + 0.03 * report_ordinal)
    source_type = ("CITIZEN_APP", "FIELD_OFFICER", "DISTRICT_HELPLINE")[
        family_ordinal % 3
    ]

    if scenario == "AUTHENTIC_EXTREME_BUT_PLAUSIBLE":
        metadata["source_recent_report_count"] = 7
        metadata["phone_count"] = 1
    elif scenario == "AUTHENTIC_WITH_INCOMPLETE_METADATA":
        for key in (
            "submitted_at",
            "reported_latitude",
            "reported_longitude",
            "location_consistency",
            "source_recent_duplicate_count",
        ):
            metadata.pop(key, None)
    elif scenario == "LEGITIMATE_DUPLICATE":
        duplicate = _duplicate_prediction(is_duplicate=True, similarity=0.96)
        metadata["duplicate_cluster_size"] = 3
        metadata["source_recent_report_count"] = 7
        metadata["source_recent_duplicate_count"] = 1
    elif scenario == "LEGITIMATE_EVENT_CONFLICT":
        metadata["event_type_consistency"] = False
        source_type = "FIELD_OFFICER"
    elif scenario == "CONTRADICTORY_TIME":
        hours = 2 + family_ordinal % 10
        metadata["submitted_at"] = (occurred_at - timedelta(hours=hours)).isoformat()
    elif scenario == "CONTRADICTORY_LOCATION":
        metadata["location_consistency"] = False
        metadata["reported_latitude"] = round(latitude + 1.2, 6)
        metadata["reported_longitude"] = round(longitude - 1.2, 6)
    elif scenario == "CONTRADICTORY_EVENT_CONTEXT":
        metadata["event_type_consistency"] = False
        metadata["source_recent_report_count"] = 11
        metadata["phone_count"] = 2
    elif scenario == "MISLEADING_OMISSION":
        metadata["source_recent_report_count"] = 8
    elif scenario == "MISLEADING_CONTEXT":
        metadata["phone_count"] = 4
        metadata["source_recent_report_count"] = 12
    elif scenario == "REPEATED_COPYING":
        duplicate = _duplicate_prediction(is_duplicate=True, similarity=0.985)
        metadata["duplicate_cluster_size"] = 12 + family_ordinal % 5
        metadata["source_recent_report_count"] = 20
        metadata["source_recent_duplicate_count"] = 16
    elif scenario == "IMPOSSIBLE_METADATA":
        metadata["reported_latitude"] = 95.0 + report_ordinal
        metadata["reported_longitude"] = 190.0 + report_ordinal
        metadata["phone_count"] = "many"
    elif scenario == "SOURCE_BEHAVIOR_ANOMALY":
        metadata["source_recent_report_count"] = 28 + family_ordinal % 13
        metadata["source_recent_duplicate_count"] = 18 + family_ordinal % 8
        source_type = "CITIZEN_APP"
    elif scenario == "UNCERTAIN_AMBIGUOUS":
        metadata["duplicate_cluster_size"] = 4 + family_ordinal % 2
        metadata["source_recent_report_count"] = 8 + family_ordinal % 3
        metadata["source_recent_duplicate_count"] = 3 + family_ordinal % 2
        metadata.pop("location_consistency", None)
        if family_ordinal % 3 == 0:
            metadata.pop("submitted_at", None)
        duplicate = _duplicate_prediction(
            is_duplicate=False,
            similarity=0.84 + 0.02 * (report_ordinal % 3),
        )
    return metadata, duplicate, source_type


def _report_text(
    scenario: str,
    *,
    split: str,
    language: str,
    location_name: str,
    family_ordinal: int,
    report_ordinal: int,
) -> tuple[str, str]:
    variant = family_ordinal % 3
    opening = _SPLIT_OPENINGS[split][language][variant]
    stem = _SCENARIO_TEXT[scenario][language]
    family_code = f"ref{split[0]}{_letters(family_ordinal)}"
    report_code = ("alpha", "bravo", "charlie", "delta")[report_ordinal]
    template_id = f"cred-{split}-{scenario.casefold()}-{language.casefold()}-v{variant}"
    if scenario == "MISLEADING_OMISSION":
        text = f"{stem} {family_code}"
    elif scenario == "MISLEADING_CONTEXT":
        synthetic_url_prefix = "https:" + "/" + "/"
        text = (
            f"{opening}: {stem}!!! {synthetic_url_prefix}one.invalid/{family_code} "
            f"{synthetic_url_prefix}two.invalid/{family_code} "
            f"{synthetic_url_prefix}three.invalid/{family_code}"
        )
    elif scenario == "REPEATED_COPYING":
        repeated = " ".join([stem] * 6)
        text = f"{opening}: {repeated} {family_code}"
    elif scenario == "LEGITIMATE_DUPLICATE":
        text = f"{opening}: {stem} in {location_name}; {family_code}"
    else:
        text = (
            f"{opening}: {stem} in {location_name}; "
            f"{family_code} {report_code}"
        )
    return text, template_id


_REASON_GROUPS: Final[dict[str, str]] = {
    "CONTRADICTORY_TIME": "contradictory time",
    "CONTRADICTORY_LOCATION": "contradictory location",
    "CONTRADICTORY_EVENT_CONTEXT": "event conflict",
    "LEGITIMATE_EVENT_CONFLICT": "event conflict",
    "REPEATED_COPYING": "duplicate behavior",
    "LEGITIMATE_DUPLICATE": "duplicate behavior",
    "IMPOSSIBLE_METADATA": "metadata inconsistency",
    "AUTHENTIC_WITH_INCOMPLETE_METADATA": "metadata inconsistency",
    "MISLEADING_OMISSION": "omission",
    "SOURCE_BEHAVIOR_ANOMALY": "source behavior",
    "MISLEADING_CONTEXT": "event conflict",
    "AUTHENTIC_EXTREME_BUT_PLAUSIBLE": "metadata inconsistency",
    "AUTHENTIC_CONSISTENT": "metadata inconsistency",
    "UNCERTAIN_AMBIGUOUS": "metadata inconsistency",
}


def generate_report_family(
    config: SyntheticCredibilityGeneratorConfig,
    *,
    split: Literal["train", "validation", "test"],
    scenario: str,
    family_ordinal: int,
) -> tuple[
    tuple[SyntheticCredibilityGroundTruth, ...],
    tuple[SyntheticCredibilityDetectorInput, ...],
    tuple[FakeReportAnnotation, ...],
]:
    """Generate one grouped family with hidden labels assigned first."""

    if scenario not in SCENARIO_LABELS:
        raise ValueError(f"unsupported credibility scenario: {scenario}")
    if split not in SPLITS:
        raise ValueError(f"unsupported split: {split}")
    rng = _rng(config, split, scenario, family_ordinal)
    label = SCENARIO_LABELS[scenario]
    language = LANGUAGES[family_ordinal % len(LANGUAGES)]
    location_name, latitude, longitude = _SPLIT_LOCATIONS[split][
        family_ordinal % len(_SPLIT_LOCATIONS[split])
    ]
    event_id = f"cred-event-{split}-{scenario.casefold()}-{family_ordinal:05d}"
    family_id = f"cred-family-{split}-{scenario.casefold()}-{family_ordinal:05d}"
    base_time = _SPLIT_ORIGINS[split] + timedelta(
        days=family_ordinal % 1_200,
        minutes=(family_ordinal * 17) % 1_440,
    )
    truths: list[SyntheticCredibilityGroundTruth] = []
    inputs: list[SyntheticCredibilityDetectorInput] = []
    annotations: list[FakeReportAnnotation] = []
    for report_ordinal in range(config.family_size):
        report_id = _uuid(
            config,
            "report",
            f"{split}:{scenario}:{family_ordinal}:{report_ordinal}",
        )
        occurred_at = base_time + timedelta(minutes=report_ordinal * 3)
        metadata, duplicate, source_type = _scenario_evidence(
            scenario,
            occurred_at=occurred_at,
            latitude=latitude,
            longitude=longitude,
            report_ordinal=report_ordinal,
            family_ordinal=family_ordinal,
            rng=rng,
        )
        text, template_id = _report_text(
            scenario,
            split=split,
            language=language,
            location_name=location_name,
            family_ordinal=family_ordinal,
            report_ordinal=report_ordinal,
        )
        combination = _sha256_payload(
            {
                "scenario": scenario,
                "template_id": template_id,
                "location": location_name,
                "language": language,
                "profile_variant": family_ordinal % 7,
            }
        )
        hidden_flag = (
            "UNRESOLVED"
            if label is FakeReportLabel.UNCERTAIN
            else label.value
        )
        truth = SyntheticCredibilityGroundTruth(
            report_id=report_id,
            ground_truth_label=label,
            scenario_category=scenario,
            hidden_authenticity_flag=hidden_flag,
            canonical_event_id=event_id,
            report_family_id=family_id,
            template_id=template_id,
            parameter_combination_id=combination,
            generated_adjudication_label=label,
            language=language,
            split=split,
            failure_reason_group=_REASON_GROUPS[scenario],
            family_ordinal=family_ordinal,
            report_ordinal=report_ordinal,
        )
        detector_input = SyntheticCredibilityDetectorInput(
            report_id=report_id,
            report_text=text,
            occurred_at=occurred_at,
            latitude=round(latitude + report_ordinal * 0.0002, 6),
            longitude=round(longitude - report_ordinal * 0.0002, 6),
            source_type=source_type,
            source_metadata=metadata,
            duplicate_prediction=duplicate,
        )
        annotation = FakeReportAnnotation(
            annotation_id=f"synthetic-credibility-{report_id}",
            report_id=str(report_id),
            label=label,
            annotator_id="project-scenario-specification-v1",
            annotation_timestamp=config.creation_timestamp
            + timedelta(seconds=family_ordinal * config.family_size + report_ordinal),
            reason=(
                "Project-generated scenario identity supplies synthetic ground truth; "
                "no detector output or rule score was used."
            ),
            evidence=[
                AnnotationEvidence(
                    code="PROJECT_GENERATED_SCENARIO_IDENTITY",
                    description="Deterministic Phase 21 scenario specification.",
                    provenance="project-authored-synthetic-generator",
                )
            ],
            canonical_event_id=event_id,
            incident_id=event_id,
            report_family_id=family_id,
            report_text=text,
            reported_latitude=detector_input.latitude,
            reported_longitude=detector_input.longitude,
            reported_at=occurred_at,
            split=split,
            blinded=True,
            taxonomy_version="fake-report-taxonomy-v1",
        )
        truths.append(truth)
        inputs.append(detector_input)
        annotations.append(annotation)
    return tuple(truths), tuple(inputs), tuple(annotations)


def iter_generated_families(
    config: SyntheticCredibilityGeneratorConfig,
) -> Iterator[
    tuple[
        str,
        str,
        int,
        tuple[SyntheticCredibilityGroundTruth, ...],
        tuple[SyntheticCredibilityDetectorInput, ...],
        tuple[FakeReportAnnotation, ...],
    ]
]:
    allocations = split_family_counts(config)
    for split in SPLITS:
        for scenario in CREDIBILITY_SCENARIOS:
            prior = sum(
                allocations[scenario][name]
                for name in SPLITS[: SPLITS.index(split)]
            )
            for local_ordinal in range(allocations[scenario][split]):
                family_ordinal = prior + local_ordinal
                truth, detector_inputs, annotations = generate_report_family(
                    config,
                    split=split,  # type: ignore[arg-type]
                    scenario=scenario,
                    family_ordinal=family_ordinal,
                )
                yield (
                    split,
                    scenario,
                    family_ordinal,
                    truth,
                    detector_inputs,
                    annotations,
                )


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name} line {line_number}: {error}") from error
            if not isinstance(payload, dict):
                raise TypeError(f"{path.name} line {line_number}: row must be an object")
            yield payload


def _composite_hash(file_hashes: Mapping[str, str]) -> str:
    return _sha256_payload(dict(sorted(file_hashes.items())))


def validate_synthetic_credibility_dataset(
    ground_truth_paths: Mapping[str, Path],
    detector_input_paths: Mapping[str, Path],
    annotation_path: Path,
    *,
    config: SyntheticCredibilityGeneratorConfig,
) -> SyntheticCredibilityQualityReport:
    """Validate isolation, identities, grouped splits, labels, and leakage."""

    errors: list[str] = []
    split_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    split_label_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    scenario_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    hard_negative_counts: Counter[str] = Counter()
    report_ids: set[str] = set()
    group_splits: defaultdict[str, set[str]] = defaultdict(set)
    event_splits: defaultdict[str, set[str]] = defaultdict(set)
    template_splits: defaultdict[str, set[str]] = defaultdict(set)
    parameter_splits: defaultdict[str, set[str]] = defaultdict(set)
    text_splits: defaultdict[str, set[str]] = defaultdict(set)
    hidden_field_hits = 0
    annotation_iterator = _read_jsonl(annotation_path)

    for split in SPLITS:
        truth_iterator = _read_jsonl(ground_truth_paths[split])
        input_iterator = _read_jsonl(detector_input_paths[split])
        while True:
            truth_payload = next(truth_iterator, None)
            input_payload = next(input_iterator, None)
            if truth_payload is None and input_payload is None:
                break
            if truth_payload is None or input_payload is None:
                errors.append(f"{split}: truth/input row counts differ")
                break
            annotation_payload = next(annotation_iterator, None)
            if annotation_payload is None:
                errors.append("annotation dataset ended before detector/truth rows")
                break
            try:
                truth = SyntheticCredibilityGroundTruth.model_validate(truth_payload)
                detector_input = SyntheticCredibilityDetectorInput.model_validate(
                    input_payload
                )
                annotation = FakeReportAnnotation.model_validate(annotation_payload)
            except Exception as error:  # noqa: BLE001 - aggregate quality failures
                errors.append(f"{split}: schema failure: {type(error).__name__}: {error}")
                continue
            input_keys = set(input_payload)
            hidden_field_hits += len(FORBIDDEN_DETECTOR_FIELDS.intersection(input_keys))
            report_id = str(truth.report_id)
            if report_id in report_ids:
                errors.append(f"duplicate report ID: {report_id}")
            report_ids.add(report_id)
            if str(detector_input.report_id) != report_id or annotation.report_id != report_id:
                errors.append(f"identity mismatch: {report_id}")
            expected_label = SCENARIO_LABELS.get(truth.scenario_category)
            if (
                expected_label is None
                or truth.ground_truth_label is not expected_label
                or truth.generated_adjudication_label is not expected_label
                or annotation.label is not expected_label
            ):
                errors.append(f"scenario-label mismatch: {report_id}")
            if truth.split != split or annotation.split != split:
                errors.append(f"split mismatch: {report_id}")
            split_counts[split] += 1
            label_counts[truth.ground_truth_label.value] += 1
            split_label_counts[split][truth.ground_truth_label.value] += 1
            scenario_counts[truth.scenario_category] += 1
            language_counts[truth.language] += 1
            if truth.scenario_category in HARD_NEGATIVE_SCENARIOS or truth.scenario_category in {
                "AUTHENTIC_EXTREME_BUT_PLAUSIBLE",
                "MISLEADING_OMISSION",
                "MISLEADING_CONTEXT",
                "SOURCE_BEHAVIOR_ANOMALY",
            }:
                hard_negative_counts[truth.scenario_category] += 1
            group_splits[truth.report_family_id].add(split)
            event_splits[truth.canonical_event_id].add(split)
            template_splits[truth.template_id].add(split)
            parameter_splits[truth.parameter_combination_id].add(split)
            text_splits[_normalize_text(detector_input.report_text)].add(split)

    if next(annotation_iterator, None) is not None:
        errors.append("annotation dataset contains rows beyond truth/input files")

    expected_scenarios = config.scenario_counts
    for scenario, expected in expected_scenarios.items():
        if scenario_counts[scenario] != expected:
            errors.append(
                f"scenario count mismatch for {scenario}: "
                f"{scenario_counts[scenario]} != {expected}"
            )
    expected_total = config.total_reports
    if sum(split_counts.values()) != expected_total:
        errors.append("total report count does not match generator configuration")
    if set(label_counts) != {label.value for label in FakeReportLabel}:
        errors.append("all three credibility labels must be represented")
    if set(language_counts) != set(LANGUAGES):
        errors.append("English, Hindi, and Hinglish must all be represented")

    group_leaks = sum(len(splits) > 1 for splits in group_splits.values())
    event_leaks = sum(len(splits) > 1 for splits in event_splits.values())
    template_leaks = sum(len(splits) > 1 for splits in template_splits.values())
    parameter_leaks = sum(len(splits) > 1 for splits in parameter_splits.values())
    exact_text_leaks = sum(len(splits) > 1 for splits in text_splits.values())
    if group_leaks:
        errors.append("report-family leakage across splits")
    if event_leaks:
        errors.append("canonical-event leakage across splits")
    if template_leaks:
        errors.append("template leakage across splits")
    if parameter_leaks:
        errors.append("parameter-combination leakage across splits")
    if exact_text_leaks:
        errors.append("exact normalized text leakage across splits")
    if hidden_field_hits:
        errors.append("hidden generator fields reached detector inputs")

    file_hashes = {
        **{
            f"ground_truth_{split}": file_sha256(ground_truth_paths[split])
            for split in SPLITS
        },
        **{
            f"detector_inputs_{split}": file_sha256(detector_input_paths[split])
            for split in SPLITS
        },
        "annotations": file_sha256(annotation_path),
    }
    dataset_hash = _composite_hash(file_hashes)
    split_hash = _sha256_payload(
        {
            split: {
                "ground_truth": file_hashes[f"ground_truth_{split}"],
                "detector_inputs": file_hashes[f"detector_inputs_{split}"],
                "rows": split_counts[split],
            }
            for split in SPLITS
        }
    )
    invariants = {
        "scenario_identity_supplies_ground_truth": not any(
            "scenario-label mismatch" in error for error in errors
        ),
        "rule_detector_not_used_for_labels": True,
        "learned_detector_not_used_for_labels": True,
        "hidden_fields_absent_from_detector_input": hidden_field_hits == 0,
        "all_inputs_available_at_assessment_time": True,
        "uncertain_is_annotation_state": True,
        "truth_probability_not_claimed": True,
    }
    return SyntheticCredibilityQualityReport(
        report_version=REPORT_VERSION,
        valid=not errors and all(invariants.values()),
        generated_at=config.creation_timestamp,
        dataset_sha256=dataset_hash,
        split_sha256=split_hash,
        annotation_sha256=file_hashes["annotations"],
        file_hashes=file_hashes,
        generator_version=GENERATOR_VERSION,
        scenario_version=SCENARIO_VERSION,
        split_version=SPLIT_VERSION,
        template_version=TEMPLATE_VERSION,
        seed=config.seed,
        report_count=sum(split_counts.values()),
        split_counts={name: split_counts[name] for name in SPLITS},
        label_counts=dict(sorted(label_counts.items())),
        split_label_counts={
            name: dict(sorted(split_label_counts[name].items())) for name in SPLITS
        },
        scenario_counts=dict(sorted(scenario_counts.items())),
        language_counts=dict(sorted(language_counts.items())),
        hard_negative_counts=dict(sorted(hard_negative_counts.items())),
        leakage_checks={
            "status": "PASS" if not any(
                (group_leaks, event_leaks, template_leaks, parameter_leaks, exact_text_leaks)
            ) else "FAIL",
            "report_family_cross_split": group_leaks,
            "canonical_event_cross_split": event_leaks,
            "template_cross_split": template_leaks,
            "parameter_combination_cross_split": parameter_leaks,
            "exact_normalized_text_cross_split": exact_text_leaks,
            "grouped_split": True,
            "random_row_split": False,
        },
        isolation_checks={
            "status": "PASS" if hidden_field_hits == 0 else "FAIL",
            "forbidden_field_occurrences": hidden_field_hits,
            "truth_and_input_physically_separate": True,
        },
        invariant_checks=invariants,
        errors=sorted(set(errors)),
        warnings=[
            "Synthetic results are development evidence, not field authenticity performance.",
            "The target is misleading-risk evidence, never truth probability.",
            "Controlled duplicate context is project-authored and does not invoke duplicate matcher v1.",
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
        encoded = (
            payload.model_dump_json(indent=2).encode("utf-8")
            if isinstance(payload, BaseModel)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
        )
        handle.write(encoded + b"\n")
    temporary.replace(path)
    return file_sha256(path)


def write_synthetic_credibility_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticCredibilityGeneratorConfig | None = None,
    overwrite: bool = False,
) -> SyntheticCredibilityArtifacts:
    """Write isolated truth/input files, annotation layer, report, and manifest."""

    selected = config or SyntheticCredibilityGeneratorConfig()
    output = local_only_path(
        output_directory, description="synthetic credibility output directories"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    ground_truth_paths = {
        split: output / f"synthetic_credibility_ground_truth_{split}.jsonl"
        for split in SPLITS
    }
    detector_input_paths = {
        split: output / f"synthetic_credibility_detector_inputs_{split}.jsonl"
        for split in SPLITS
    }
    annotation_path = output / "synthetic_credibility_annotations.jsonl"
    quality_path = output / "synthetic_credibility_quality_report.json"
    manifest_path = output / "synthetic_credibility_dataset_manifest.json"
    targets = [
        *ground_truth_paths.values(),
        *detector_input_paths.values(),
        annotation_path,
        quality_path,
        manifest_path,
    ]
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite generated credibility artifacts: "
            + ", ".join(path.name for path in existing)
        )

    data_targets = [
        *ground_truth_paths.values(),
        *detector_input_paths.values(),
        annotation_path,
    ]
    temporary_paths: dict[Path, Path] = {}
    try:
        with ExitStack() as stack:
            handles: dict[Path, Any] = {}
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
                handles[target] = handle
                temporary_paths[target] = Path(handle.name)
            for split, _, _, truths, inputs, annotations in iter_generated_families(
                selected
            ):
                truth_handle = handles[ground_truth_paths[split]]
                input_handle = handles[detector_input_paths[split]]
                annotation_handle = handles[annotation_path]
                for truth, detector_input, annotation in zip(
                    truths, inputs, annotations, strict=True
                ):
                    truth_handle.write(
                        _canonical_json(truth.model_dump(mode="json")) + b"\n"
                    )
                    input_handle.write(
                        _canonical_json(detector_input.model_dump(mode="json")) + b"\n"
                    )
                    annotation_handle.write(
                        _canonical_json(annotation.model_dump(mode="json")) + b"\n"
                    )
        for target, temporary in temporary_paths.items():
            temporary.replace(target)
    except Exception:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)
        raise

    report = validate_synthetic_credibility_dataset(
        ground_truth_paths,
        detector_input_paths,
        annotation_path,
        config=selected,
    )
    if not report.valid:
        raise ValueError(
            "generated credibility dataset failed validation: "
            + "; ".join(report.errors[:20])
        )
    quality_hash = _write_json_atomic(report, quality_path)
    split_descriptors = {
        split: {
            "row_count": report.split_counts[split],
            "ground_truth_file": ground_truth_paths[split].name,
            "ground_truth_sha256": report.file_hashes[f"ground_truth_{split}"],
            "detector_input_file": detector_input_paths[split].name,
            "detector_input_sha256": report.file_hashes[
                f"detector_inputs_{split}"
            ],
        }
        for split in SPLITS
    }
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "schema_version": "1.0",
        "dataset_id": selected.dataset_id,
        "dataset_version": selected.dataset_version,
        "created_at": selected.creation_timestamp.isoformat(),
        "provenance": "PROJECT_AUTHORED",
        "data_kind": "SYNTHETIC",
        "classification": "DEVELOPMENT_ONLY",
        "semantic_target": "MISLEADING_RISK_EVIDENCE",
        "truth_probability_claimed": False,
        "production_validation": "NOT_VALIDATED",
        "generator": {
            "version": GENERATOR_VERSION,
            "scenario_version": SCENARIO_VERSION,
            "split_version": SPLIT_VERSION,
            "template_version": TEMPLATE_VERSION,
            "seed": selected.seed,
            "reports_per_scenario": selected.scenario_counts,
            "family_size": selected.family_size,
        },
        "dataset_sha256": report.dataset_sha256,
        "split_sha256": report.split_sha256,
        "annotation_file": annotation_path.name,
        "annotation_sha256": report.annotation_sha256,
        "quality_report_file": quality_path.name,
        "quality_report_sha256": quality_hash,
        "split_descriptors": split_descriptors,
        "label_distribution": report.label_counts,
        "scenario_distribution": report.scenario_counts,
        "language_distribution": report.language_counts,
        "ground_truth_method": "PROJECT_GENERATED_SCENARIO_IDENTITY",
        "detector_used_for_labels": False,
        "grouped_split": {
            "group_keys": [
                "report_family_id",
                "canonical_event_id",
                "template_id",
                "parameter_combination_id",
            ],
            "random_row_split": False,
            "checks": report.leakage_checks,
        },
        "detector_input_isolation": {
            "physically_separate": True,
            "forbidden_fields": sorted(FORBIDDEN_DETECTOR_FIELDS),
            "checks": report.isolation_checks,
        },
        "policy": {
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
            "nlp_v3_modified": False,
            "duplicate_matcher_v1_modified": False,
            "event_grouping_v1_modified": False,
        },
    }
    manifest_hash = _write_json_atomic(manifest, manifest_path)
    return SyntheticCredibilityArtifacts(
        output_directory=output,
        ground_truth_paths=ground_truth_paths,
        detector_input_paths=detector_input_paths,
        annotation_path=annotation_path,
        quality_report_path=quality_path,
        manifest_path=manifest_path,
        dataset_hash=report.dataset_sha256,
        split_hash=report.split_sha256,
        annotation_hash=report.annotation_sha256,
        quality_report_hash=quality_hash,
        manifest_hash=manifest_hash,
        report=report,
        manifest=manifest,
    )


def _registry_relative(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path, registry_path.parent)).as_posix()


def register_synthetic_credibility_dataset(
    artifacts: SyntheticCredibilityArtifacts,
    *,
    config: SyntheticCredibilityGeneratorConfig,
    registry_path: Path | str,
    replace_existing: bool = False,
):
    """Register the hidden annotation layer and run common validation."""

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
        component=DatasetComponent.CREDIBILITY,
        local_path=_registry_relative(artifacts.annotation_path, selected_registry),
        format=DatasetFormat.JSONL,
        content_sha256=artifacts.annotation_hash,
        schema_version="synthetic-credibility-annotation-dataset-v1",
        label_schema_version="fake-report-taxonomy-v1",
        creation_timestamp=config.creation_timestamp,
        source_description=(
            "Reproducible project-authored synthetic credibility-risk benchmark. "
            "Labels come only from generator scenario identity."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development and regression use only; prohibited "
            "as field-authenticity, truth-probability, or production-validation evidence."
        ),
        grouping_field="report_family_id",
        time_field="reported_at",
        split_field="split",
        label_count=artifacts.report.report_count,
        row_or_image_count=artifacts.report.report_count,
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_SYNTHETIC_SCENARIO_IDENTITY",
        metadata={
            "synthetic": True,
            "synthetic_classification": "SYNTHETIC",
            "semantic_target": "MISLEADING_RISK_EVIDENCE",
            "truth_probability_claimed": False,
            "production_validation": "NOT_VALIDATED",
            "dataset_hash": artifacts.dataset_hash,
            "annotation_hash": artifacts.annotation_hash,
            "split_hash": artifacts.split_hash,
            "generator_version": GENERATOR_VERSION,
            "scenario_version": SCENARIO_VERSION,
            "template_version": TEMPLATE_VERSION,
            "split_version": SPLIT_VERSION,
            "seed": config.seed,
            "report_count": artifacts.report.report_count,
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
            "holdout_strategy": "GROUPED_SCENARIO_FAMILY_EVENT_TEMPLATE_PARAMETER",
            "random_row_split": False,
            "detector_used_for_labels": False,
            "live_backend_modified": False,
            "nlp_v3_modified": False,
            "duplicate_matcher_v1_modified": False,
            "event_grouping_v1_modified": False,
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
            "registered synthetic credibility dataset failed structural validation: "
            + "; ".join(validation.errors[:20])
        )
    return find_dataset(
        load_dataset_registry(selected_registry),
        config.dataset_id,
        config.dataset_version,
    )


__all__ = [
    "CREDIBILITY_SCENARIOS",
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_REPORTS_PER_SCENARIO",
    "DEFAULT_SEED",
    "FORBIDDEN_DETECTOR_FIELDS",
    "GENERATOR_VERSION",
    "HARD_NEGATIVE_SCENARIOS",
    "LANGUAGES",
    "PRIMARY_SCENARIOS",
    "SCENARIO_LABELS",
    "SyntheticCredibilityArtifacts",
    "SyntheticCredibilityDetectorInput",
    "SyntheticCredibilityGeneratorConfig",
    "SyntheticCredibilityGroundTruth",
    "SyntheticCredibilityQualityReport",
    "generate_report_family",
    "iter_generated_families",
    "register_synthetic_credibility_dataset",
    "split_family_counts",
    "validate_synthetic_credibility_dataset",
    "write_synthetic_credibility_dataset",
]
