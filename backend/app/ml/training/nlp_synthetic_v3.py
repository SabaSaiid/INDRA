"""Phase 18 synthetic-only NLP v3 development protocol.

The module has three deliberately separate actions:

``freeze``
    Verify the exact registered Phase 17 corpus, search only the train and
    validation partitions, calibrate only on validation, and freeze a local
    JSON artifact.
``golden``
    Exercise the existing engineering-regression suite with the opt-in v3
    classifier.  This does not change the configured live/default classifier.
``finalize``
    Exclusively claim and evaluate the protected synthetic holdout exactly
    once.  A completed or failed claim can never be reused.

No code in this module performs network I/O or loads externally fitted state.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import sys
import warnings
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.duplicate_features import FrozenTfidfSpace, normalize_text
from app.ml.components.nlp_classifier import (
    NLPCalibrationState,
    NLPClassifier,
    NLPClassifierArtifact,
    NLPFeatureWeights,
    NLPLinearClassifierState,
    load_nlp_artifact,
)
from app.ml.config import NLPClassifierConfig, file_sha256, local_only_path
from app.ml.contracts import (
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    UnifiedMLResult,
)
from app.ml.data.dataset_validation import CheckStatus
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetClassification,
    DatasetComponent,
    DatasetProvenance,
    DatasetStatus,
    find_dataset,
    load_bound_validation_report,
    load_dataset_registry,
    resolve_registry_path,
)
from app.ml.golden import (
    execute_golden_scenario,
    load_golden_scenarios,
    validate_golden_scenario,
)
from app.ml.inference.engine import InferenceEngine
from app.ml.training.dataset_gate import evaluate_training_dataset

ML_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ML_ROOT / "artifacts"

EXPECTED_DATASET_ID = "indra-nlp-project-synthetic-v1"
EXPECTED_DATASET_VERSION = "synthetic-nlp-100k-v1"
EXPECTED_DATASET_SHA256 = (
    "6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76"
)
EXPECTED_GENERATOR_VERSION = "synthetic-nlp-generator-v1"
EXPECTED_GENERATOR_SEED = 170017
EXPECTED_SPLIT_VERSION = "synthetic-nlp-generator-splits-v1"
EXPECTED_COUNTS = {"train": 80_000, "validation": 10_000, "test": 10_000}

MODEL_VERSION = "nlp-classifier-v3-synthetic-development"
FEATURE_VERSION = "nlp-features-v3-synthetic"
PREPROCESSING_VERSION = "nlp-text-normalization-v1"
DEVELOPMENT_STATUS = "DEVELOPMENT_ONLY_SYNTHETIC"
PRODUCTION_STATUS = "NOT_PRODUCTION_READY"
PRODUCTION_VALIDATION = "NOT_VALIDATED"

V3_CLASSES = (
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
    "NOT_RELEVANT",
    "RIVER_BREACH",
    "URBAN_FLOOD",
)
V3_LANGUAGES = ("English", "Hindi", "Hinglish")
V3_NOISE_PROFILES = ("NONE", "LOW", "MEDIUM", "HIGH")

DEFAULT_ARTIFACT_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH = (
    ARTIFACT_ROOT / "nlp_classifier_v3.development_manifest.json"
)
DEFAULT_SEARCH_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.search.json"
DEFAULT_CALIBRATION_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.calibration.json"
DEFAULT_GOLDEN_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.golden.json"
DEFAULT_METRICS_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.metrics.json"
DEFAULT_FINAL_RECEIPT_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.final_test_receipt.json"
DEFAULT_ERROR_REPORT_PATH = ARTIFACT_ROOT / "nlp_classifier_v3.error_report.json"
DEFAULT_ARTIFACT_MANIFEST_PATH = ARTIFACT_ROOT / "manifest.json"
DEFAULT_V2_METRICS_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.metrics.json"


class SyntheticV3TrainingBlocked(ValueError):
    """Fail-closed error carrying a stable Phase 18 reason code."""


class V3ProtocolConfig(BaseModel):
    """Frozen controls for the bounded synthetic development experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = "nlp-v3-synthetic-development-v1"
    model_version: str = MODEL_VERSION
    feature_version: str = FEATURE_VERSION
    preprocessing_version: str = PREPROCESSING_VERSION
    random_seed: int = EXPECTED_GENERATOR_SEED
    max_iterations: int = Field(default=500, gt=0)
    tolerance: float = Field(default=1e-4, gt=0.0)
    minimum_not_relevant_recall: float = Field(default=0.80, ge=0.0, le=1.0)
    minimum_development_macro_f1: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
    )
    vectorizer_min_df: int = Field(default=2, ge=1)
    character_max_features: int = Field(default=60_000, ge=1)
    word_max_features: int = Field(default=20_000, ge=1)
    calibration_lower_bound: float = Field(default=0.25, gt=0.0)
    calibration_upper_bound: float = Field(default=4.0, gt=0.0)
    calibration_bins: int = Field(default=10, ge=2, le=50)
    maximum_error_examples_per_category: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_protocol(self) -> V3ProtocolConfig:
        if self.calibration_upper_bound <= self.calibration_lower_bound:
            raise ValueError("calibration bounds must be ascending")
        return self


DEFAULT_PROTOCOL_CONFIG = V3ProtocolConfig()


class V3Candidate(BaseModel):
    """One explicitly enumerated local logistic-regression configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    configuration_id: str = Field(min_length=1)
    feature_space_id: Literal["A", "B", "C"]
    char_ngram_range: tuple[int, int]
    word_ngram_range: tuple[int, int] = (1, 2)
    character_weight: float = Field(default=1.0, gt=0.0)
    word_weight: float = Field(default=1.0, gt=0.0)
    classifier: Literal["LOGISTIC_REGRESSION"] = "LOGISTIC_REGRESSION"
    regularization_c: float = Field(default=1.0, gt=0.0)
    class_weight: Literal["NONE", "BALANCED"] = "NONE"
    deterministic_tie_rank: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> V3Candidate:
        if self.char_ngram_range[0] > self.char_ngram_range[1]:
            raise ValueError("character n-gram range must be ascending")
        if self.word_ngram_range[0] > self.word_ngram_range[1]:
            raise ValueError("word n-gram range must be ascending")
        return self


def controlled_search_space() -> tuple[V3Candidate, ...]:
    """Return the fixed 11-candidate search; no generated Cartesian grid exists."""

    candidates = (
        V3Candidate(
            configuration_id="A_EQUAL_NONE_C1",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            deterministic_tie_rank=0,
        ),
        V3Candidate(
            configuration_id="A_EQUAL_BALANCED_C1",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            class_weight="BALANCED",
            deterministic_tie_rank=1,
        ),
        V3Candidate(
            configuration_id="A_CHAR125_NONE_C1",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            character_weight=1.25,
            word_weight=0.75,
            deterministic_tie_rank=2,
        ),
        V3Candidate(
            configuration_id="A_CHAR150_NONE_C1",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            character_weight=1.5,
            word_weight=0.5,
            deterministic_tie_rank=3,
        ),
        V3Candidate(
            configuration_id="A_EQUAL_NONE_C0_25",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            regularization_c=0.25,
            deterministic_tie_rank=4,
        ),
        V3Candidate(
            configuration_id="A_EQUAL_NONE_C0_5",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            regularization_c=0.5,
            deterministic_tie_rank=5,
        ),
        V3Candidate(
            configuration_id="A_EQUAL_NONE_C2",
            feature_space_id="A",
            char_ngram_range=(3, 5),
            regularization_c=2.0,
            deterministic_tie_rank=6,
        ),
        V3Candidate(
            configuration_id="B_EQUAL_NONE_C1",
            feature_space_id="B",
            char_ngram_range=(2, 5),
            deterministic_tie_rank=7,
        ),
        V3Candidate(
            configuration_id="B_EQUAL_BALANCED_C1",
            feature_space_id="B",
            char_ngram_range=(2, 5),
            class_weight="BALANCED",
            deterministic_tie_rank=8,
        ),
        V3Candidate(
            configuration_id="C_EQUAL_NONE_C1",
            feature_space_id="C",
            char_ngram_range=(3, 6),
            deterministic_tie_rank=9,
        ),
        V3Candidate(
            configuration_id="C_EQUAL_BALANCED_C1",
            feature_space_id="C",
            char_ngram_range=(3, 6),
            class_weight="BALANCED",
            deterministic_tie_rank=10,
        ),
    )
    identifiers = [candidate.configuration_id for candidate in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("v3 configuration identifiers must be unique")
    if len(candidates) > 12:
        raise RuntimeError("v3 controlled search exceeds its frozen ceiling")
    return candidates


@dataclass(frozen=True, slots=True)
class SyntheticExample:
    record_id: str
    text: str
    label: str
    language: str
    split: str
    noise_profile: str
    hard_negative: bool
    hard_negative_type: str | None
    scenario_id: str
    scenario_family: str
    template_id: str
    base_template_family: str
    realized_structure_family: str
    parameter_combination_id: str


@dataclass(frozen=True, slots=True)
class SyntheticDatasetBinding:
    registry_path: Path
    dataset_path: Path
    scenario_path: Path
    dataset_manifest_path: Path
    quality_report_path: Path
    dataset_manifest_sha256: str
    scenario_metadata_sha256: str
    quality_report_sha256: str
    dataset_manifest: dict[str, Any]
    quality_report: dict[str, Any]
    production_training_gate: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProtectedTestDescriptor:
    sample_count: int
    split_sha256: str
    source_order_sha256: str
    record_ids_in_source_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelectionDataset:
    train_examples: tuple[SyntheticExample, ...]
    validation_examples: tuple[SyntheticExample, ...]
    train_sha256: str
    validation_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedSyntheticData:
    binding: SyntheticDatasetBinding
    selection: SelectionDataset
    protected_test: ProtectedTestDescriptor
    split_manifest: dict[str, Any]


@dataclass(slots=True)
class SelectedFit:
    candidate: V3Candidate
    char_vectorizer: Any
    word_vectorizer: Any
    classifier: Any
    train_predictions: list[str]
    validation_predictions: list[str]
    validation_logits: np.ndarray
    feature_count: int
    classifier_iterations: list[int]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return payload


def _metadata_path(
    value: Any,
    *,
    registry_path: Path,
    description: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise SyntheticV3TrainingBlocked(
            f"TRAINING_BLOCKED_DATASET_BINDING_MISMATCH: missing {description}"
        )
    return resolve_registry_path(value, registry_path)


def verify_synthetic_dataset_binding(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> SyntheticDatasetBinding:
    """Verify the exact registry, file, generator, seed, and leakage binding."""

    selected_registry_path = local_only_path(
        registry_path,
        description="dataset registries",
    ).resolve()
    registry = load_dataset_registry(selected_registry_path)
    registered = find_dataset(
        registry,
        EXPECTED_DATASET_ID,
        EXPECTED_DATASET_VERSION,
    )
    dataset_path = resolve_registry_path(
        registered.local_path,
        selected_registry_path,
    )
    registered_hash = registered.content_sha256.casefold()
    actual_hash = file_sha256(dataset_path).casefold() if dataset_path.is_file() else ""
    if (
        registered_hash != EXPECTED_DATASET_SHA256
        or actual_hash != EXPECTED_DATASET_SHA256
    ):
        raise SyntheticV3TrainingBlocked("TRAINING_BLOCKED_DATASET_HASH_MISMATCH")

    identity_checks = {
        "component": registered.component is DatasetComponent.NLP,
        "status": registered.status is DatasetStatus.VALID,
        "classification": registered.data_classification
        is DatasetClassification.DEVELOPMENT_ONLY,
        "provenance": registered.provenance is DatasetProvenance.PROJECT_AUTHORED,
        "human_adjudicated": registered.human_adjudicated is False,
        "label_source": registered.label_source == "PROJECT_GENERATED_SYNTHETIC",
        "row_count": registered.row_or_image_count == 100_000,
        "label_count": registered.label_count == 100_000,
        "generator_version": registered.metadata.get("generator_version")
        == EXPECTED_GENERATOR_VERSION,
        "generator_seed": registered.metadata.get("seed") == EXPECTED_GENERATOR_SEED,
        "split_version": registered.metadata.get("split_version")
        == EXPECTED_SPLIT_VERSION,
        "synthetic": registered.metadata.get("synthetic") is True,
        "network_access": registered.metadata.get("network_access") is False,
    }
    failed_identity = [name for name, passed in identity_checks.items() if not passed]
    if failed_identity:
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_DATASET_BINDING_MISMATCH: " + ", ".join(failed_identity)
        )

    dataset_manifest_path = _metadata_path(
        registered.metadata.get("manifest_path"),
        registry_path=selected_registry_path,
        description="synthetic manifest",
    )
    scenario_path = _metadata_path(
        registered.metadata.get("scenario_metadata_path"),
        registry_path=selected_registry_path,
        description="scenario metadata",
    )
    quality_report_path = _metadata_path(
        registered.metadata.get("quality_report_path"),
        registry_path=selected_registry_path,
        description="quality report",
    )
    bound_hashes = {
        "manifest": (
            dataset_manifest_path,
            str(registered.metadata.get("manifest_sha256", "")),
        ),
        "scenario": (
            scenario_path,
            str(registered.metadata.get("scenario_metadata_sha256", "")),
        ),
        "quality_report": (
            quality_report_path,
            str(registered.metadata.get("quality_report_sha256", "")),
        ),
    }
    for name, (path, expected_hash) in bound_hashes.items():
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise SyntheticV3TrainingBlocked(
                f"TRAINING_BLOCKED_DATASET_BINDING_MISMATCH: {name} hash"
            )

    dataset_manifest = _read_json(dataset_manifest_path)
    manifest_checks = {
        "dataset_hash": dataset_manifest.get("dataset_sha256")
        == EXPECTED_DATASET_SHA256,
        "generator_version": dataset_manifest.get("generator_version")
        == EXPECTED_GENERATOR_VERSION,
        "seed": dataset_manifest.get("seed") == EXPECTED_GENERATOR_SEED,
        "dataset_id": dataset_manifest.get("dataset_id") == EXPECTED_DATASET_ID,
        "dataset_version": dataset_manifest.get("dataset_version")
        == EXPECTED_DATASET_VERSION,
        "classification": dataset_manifest.get("classification") == "DEVELOPMENT_ONLY",
        "production_validation": dataset_manifest.get("production_validation")
        == "NOT_PRODUCTION_VALIDATION",
        "network_access": dataset_manifest.get("network_access") is False,
        "models_trained": dataset_manifest.get("models_trained") == [],
        "pretrained_models": dataset_manifest.get("pretrained_models") == [],
        "open_weight_models": dataset_manifest.get("open_weight_models") == [],
        "external_apis": dataset_manifest.get("external_apis") == [],
    }
    failed_manifest = [name for name, passed in manifest_checks.items() if not passed]
    if failed_manifest:
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_DATASET_BINDING_MISMATCH: manifest "
            + ", ".join(failed_manifest)
        )

    quality_report = _read_json(quality_report_path)
    if (
        quality_report.get("valid") is not True
        or quality_report.get("dataset_hash") != EXPECTED_DATASET_SHA256
        or quality_report.get("generator_version") != EXPECTED_GENERATOR_VERSION
        or quality_report.get("seed") != EXPECTED_GENERATOR_SEED
        or quality_report.get("leakage_results", {}).get("status") != "PASS"
    ):
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_DATASET_QUALITY_EVIDENCE_INVALID"
        )

    registered_validation = load_bound_validation_report(
        registered,
        selected_registry_path,
    )
    if (
        not registered_validation.valid
        or registered_validation.content_sha256 != EXPECTED_DATASET_SHA256
        or registered_validation.leakage.overall_status is not CheckStatus.PASS
    ):
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_REGISTERED_VALIDATION_INVALID"
        )

    production_gate = evaluate_training_dataset(
        EXPECTED_DATASET_ID,
        DatasetComponent.NLP,
        registry_path=selected_registry_path,
        dataset_version=EXPECTED_DATASET_VERSION,
        supplied_path=dataset_path,
        require_evaluation_approvals=True,
    )
    if production_gate.allowed:
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_PRODUCTION_GATE_UNEXPECTEDLY_OPEN"
        )

    return SyntheticDatasetBinding(
        registry_path=selected_registry_path,
        dataset_path=dataset_path,
        scenario_path=scenario_path,
        dataset_manifest_path=dataset_manifest_path,
        quality_report_path=quality_report_path,
        dataset_manifest_sha256=file_sha256(dataset_manifest_path),
        scenario_metadata_sha256=file_sha256(scenario_path),
        quality_report_sha256=file_sha256(quality_report_path),
        dataset_manifest=dataset_manifest,
        quality_report=quality_report,
        production_training_gate=production_gate.model_dump(mode="json"),
    )


def _realized_structure_family(template_id: str) -> str:
    _, separator, frame = template_id.partition("::")
    if not separator:
        return "UNRECORDED"
    prefix, final_separator, variant = frame.rpartition("-")
    if final_separator and variant.isdigit():
        return prefix
    return frame


def _example_from_payloads(
    record: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> SyntheticExample:
    template_id = str(record.get("template_id", ""))
    base_template, separator, _ = template_id.partition("::")
    if not separator:
        base_template = template_id
    return SyntheticExample(
        record_id=str(record["record_id"]),
        text=str(record["text"]),
        label=str(record["event_type"]),
        language=str(record["language"]),
        split=str(record["split"]),
        noise_profile=str(record["noise_profile"]),
        hard_negative=record.get("hard_negative") is True,
        hard_negative_type=(
            str(scenario["hard_negative_type"])
            if scenario.get("hard_negative_type") is not None
            else None
        ),
        scenario_id=str(record["scenario_id"]),
        scenario_family=str(scenario["scenario_family"]),
        template_id=template_id,
        base_template_family=base_template,
        realized_structure_family=_realized_structure_family(template_id),
        parameter_combination_id=str(record["parameter_combination_id"]),
    )


def _counter_payload(
    examples: Sequence[SyntheticExample], attribute: str
) -> dict[str, int]:
    return dict(
        sorted(
            Counter(str(getattr(example, attribute)) for example in examples).items()
        )
    )


def _hash_string_sequence(values: Sequence[str]) -> str:
    return _canonical_hash(list(values))


def prepare_synthetic_selection_data(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> PreparedSyntheticData:
    """Load train/validation rows while exposing only test integrity metadata."""

    binding = verify_synthetic_dataset_binding(registry_path=registry_path)
    train: list[SyntheticExample] = []
    validation: list[SyntheticExample] = []
    test_ids: list[str] = []
    hashers = {name: hashlib.sha256() for name in EXPECTED_COUNTS}
    counts: Counter[str] = Counter()
    class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    language_counts: dict[str, Counter[str]] = defaultdict(Counter)
    noise_counts: dict[str, Counter[str]] = defaultdict(Counter)
    hard_negative_counts: Counter[str] = Counter()
    base_templates: dict[str, set[str]] = defaultdict(set)
    realized_templates: dict[str, set[str]] = defaultdict(set)
    parameter_combinations: dict[str, set[str]] = defaultdict(set)
    scenario_ids: dict[str, set[str]] = defaultdict(set)

    with (
        binding.dataset_path.open(encoding="utf-8") as dataset_handle,
        binding.scenario_path.open(encoding="utf-8") as scenario_handle,
    ):
        paired_lines = zip_longest(dataset_handle, scenario_handle)
        for line_number, pair in enumerate(paired_lines, start=1):
            dataset_line, scenario_line = pair
            if dataset_line is None or scenario_line is None:
                raise SyntheticV3TrainingBlocked(
                    "TRAINING_BLOCKED_DATASET_BINDING_MISMATCH: row counts"
                )
            try:
                record = json.loads(dataset_line)
                scenario = json.loads(scenario_line)
            except json.JSONDecodeError as error:
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_INVALID_JSONL: line {line_number}"
                ) from error
            if (
                record.get("record_id") != scenario.get("record_id")
                or record.get("scenario_id") != scenario.get("scenario_id")
                or record.get("event_type") != scenario.get("event_type")
                or record.get("split") != scenario.get("split")
            ):
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_SCENARIO_BINDING_MISMATCH: line {line_number}"
                )
            if (
                scenario.get("generator_version") != EXPECTED_GENERATOR_VERSION
                or scenario.get("seed") != EXPECTED_GENERATOR_SEED
                or scenario.get("split_version") != EXPECTED_SPLIT_VERSION
            ):
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_GENERATOR_BINDING_MISMATCH: line {line_number}"
                )

            split = str(record.get("split"))
            if split not in EXPECTED_COUNTS:
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_INVALID_SPLIT: {split}"
                )
            label = str(record.get("event_type"))
            language = str(record.get("language"))
            noise_profile = str(record.get("noise_profile"))
            if label not in V3_CLASSES:
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_INVALID_LABEL: {label}"
                )
            if language not in V3_LANGUAGES or noise_profile not in V3_NOISE_PROFILES:
                raise SyntheticV3TrainingBlocked(
                    f"TRAINING_BLOCKED_INVALID_SUBGROUP: line {line_number}"
                )

            canonical_record = _canonical_json_bytes(record) + b"\n"
            hashers[split].update(canonical_record)
            counts[split] += 1
            class_counts[split][label] += 1
            language_counts[split][language] += 1
            noise_counts[split][noise_profile] += 1
            if record.get("hard_negative") is True:
                hard_negative_counts[split] += 1
            template_id = str(record["template_id"])
            base_templates[split].add(template_id.partition("::")[0])
            realized_templates[split].add(_realized_structure_family(template_id))
            parameter_combinations[split].add(str(record["parameter_combination_id"]))
            scenario_ids[split].add(str(record["scenario_id"]))

            if split == "train":
                train.append(_example_from_payloads(record, scenario))
            elif split == "validation":
                validation.append(_example_from_payloads(record, scenario))
            else:
                test_ids.append(str(record["record_id"]))

    if dict(counts) != EXPECTED_COUNTS:
        raise SyntheticV3TrainingBlocked(
            "TRAINING_BLOCKED_UNEXPECTED_SPLIT_COUNTS: " + json.dumps(dict(counts))
        )
    for split, expected_count in EXPECTED_COUNTS.items():
        if set(class_counts[split]) != set(V3_CLASSES):
            raise SyntheticV3TrainingBlocked(
                f"TRAINING_BLOCKED_CLASS_COVERAGE: {split}"
            )
        if len(scenario_ids[split]) != expected_count:
            raise SyntheticV3TrainingBlocked(
                f"TRAINING_BLOCKED_DUPLICATE_SCENARIO: {split}"
            )

    pairwise_splits = (
        ("train", "validation"),
        ("train", "test"),
        ("validation", "test"),
    )
    template_overlap = {
        f"{left}_vs_{right}": len(base_templates[left] & base_templates[right])
        for left, right in pairwise_splits
    }
    combination_overlap = {
        f"{left}_vs_{right}": len(
            parameter_combinations[left] & parameter_combinations[right]
        )
        for left, right in pairwise_splits
    }
    scenario_overlap = {
        f"{left}_vs_{right}": len(scenario_ids[left] & scenario_ids[right])
        for left, right in pairwise_splits
    }
    if (
        any(template_overlap.values())
        or any(combination_overlap.values())
        or any(scenario_overlap.values())
    ):
        raise SyntheticV3TrainingBlocked("TRAINING_BLOCKED_CROSS_SPLIT_LEAKAGE")

    split_hashes = {name: hasher.hexdigest() for name, hasher in hashers.items()}
    split_manifest = {
        "schema_version": "1.0",
        "split_version": EXPECTED_SPLIT_VERSION,
        "strategy": "GENERATOR_LEVEL_SEPARATION",
        "random_row_split": False,
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "counts": dict(sorted(counts.items())),
        "split_sha256": split_hashes,
        "class_distribution": {
            split: dict(sorted(values.items()))
            for split, values in sorted(class_counts.items())
        },
        "language_distribution": {
            split: dict(sorted(values.items()))
            for split, values in sorted(language_counts.items())
        },
        "noise_distribution": {
            split: {profile: values.get(profile, 0) for profile in V3_NOISE_PROFILES}
            for split, values in sorted(noise_counts.items())
        },
        "hard_negative_distribution": {
            split: hard_negative_counts.get(split, 0) for split in EXPECTED_COUNTS
        },
        "base_template_family_counts": {
            split: len(values) for split, values in sorted(base_templates.items())
        },
        "realized_structure_family_counts": {
            split: len(values) for split, values in sorted(realized_templates.items())
        },
        "parameter_combination_counts": {
            split: len(values)
            for split, values in sorted(parameter_combinations.items())
        },
        "base_template_overlap": template_overlap,
        "parameter_combination_overlap": combination_overlap,
        "scenario_overlap": scenario_overlap,
        "test_policy": "PROTECTED_FINAL_SYNTHETIC_HOLDOUT",
        "test_available_to_selection": False,
        "fit_permitted_splits": ["train"],
        "transform_only_splits": ["validation", "test"],
    }
    split_manifest["split_definition_sha256"] = _canonical_hash(split_manifest)
    selection = SelectionDataset(
        train_examples=tuple(train),
        validation_examples=tuple(validation),
        train_sha256=split_hashes["train"],
        validation_sha256=split_hashes["validation"],
    )
    protected = ProtectedTestDescriptor(
        sample_count=len(test_ids),
        split_sha256=split_hashes["test"],
        source_order_sha256=_hash_string_sequence(test_ids),
        record_ids_in_source_order=tuple(test_ids),
    )
    return PreparedSyntheticData(
        binding=binding,
        selection=selection,
        protected_test=protected,
        split_manifest=split_manifest,
    )


def _metric_set(
    labels: Sequence[str],
    predictions: Sequence[str],
    *,
    classes: Sequence[str] = V3_CLASSES,
    include_confusion: bool = True,
    include_per_class: bool = True,
) -> dict[str, Any]:
    """Calculate deterministic measured metrics, including explicit empty strata."""

    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have equal length")
    if not labels:
        return {
            "status": "NO_SAMPLES_IN_SPLIT",
            "sample_count": 0,
            "accuracy": None,
            "macro_precision": None,
            "macro_recall": None,
            "macro_f1": None,
            "not_relevant_recall": None,
            "per_class_metrics": {},
            "confusion_matrix": [],
        }

    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        precision_recall_fscore_support,
    )

    selected_classes = list(classes)
    precision, recall, f1, support = precision_recall_fscore_support(
        labels,
        predictions,
        labels=selected_classes,
        zero_division=0,
    )
    per_class = {
        label: {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
        for index, label in enumerate(selected_classes)
    }
    present_indexes = [index for index, count in enumerate(support) if count > 0]
    present_macro_f1 = float(np.mean(f1[present_indexes])) if present_indexes else None
    if not include_confusion:
        confusion_payload: list[list[int]] = []
    elif len(selected_classes) == 1:
        only_label = selected_classes[0]
        confusion_payload = [
            [
                sum(
                    truth == only_label and prediction == only_label
                    for truth, prediction in zip(labels, predictions, strict=True)
                )
            ]
        ]
    else:
        confusion_payload = confusion_matrix(
            labels,
            predictions,
            labels=selected_classes,
        ).tolist()
    return {
        "status": "DATA_AVAILABLE",
        "sample_count": len(labels),
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
        "macro_f1": float(np.mean(f1)),
        "macro_f1_present_classes": present_macro_f1,
        "not_relevant_recall": (
            per_class["NOT_RELEVANT"]["recall"]
            if "NOT_RELEVANT" in per_class
            and per_class["NOT_RELEVANT"]["support"] > 0
            else None
        ),
        "per_class_metrics": per_class if include_per_class else {},
        "confusion_matrix": confusion_payload,
    }


def _indexes_by_value(
    examples: Sequence[SyntheticExample],
    attribute: str,
) -> dict[str, list[int]]:
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, example in enumerate(examples):
        indexes[str(getattr(example, attribute))].append(index)
    return dict(indexes)


def _metrics_for_indexes(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
    indexes: Sequence[int],
    *,
    present_classes_only: bool = False,
) -> dict[str, Any]:
    labels = [examples[index].label for index in indexes]
    selected_predictions = [predictions[index] for index in indexes]
    classes: Sequence[str] = V3_CLASSES
    if present_classes_only and labels:
        classes = tuple(sorted(set(labels)))
    return _metric_set(labels, selected_predictions, classes=classes)


def _language_report(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    by_language = _indexes_by_value(examples, "language")
    return {
        language: _metrics_for_indexes(
            examples,
            predictions,
            by_language.get(language, []),
        )
        for language in V3_LANGUAGES
    }


def _noise_report(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    by_noise = _indexes_by_value(examples, "noise_profile")
    report: dict[str, Any] = {}
    for profile in V3_NOISE_PROFILES:
        metrics = _metrics_for_indexes(
            examples,
            predictions,
            by_noise.get(profile, []),
        )
        report[profile] = {
            key: metrics[key]
            for key in (
                "status",
                "sample_count",
                "accuracy",
                "macro_f1",
                "not_relevant_recall",
            )
        }
    return report


HARD_NEGATIVE_DISTINCTIONS: dict[str, tuple[str, ...]] = {
    "URBAN_FLOOD_VS_RIVER_BREACH": (
        "URBAN_DRAINAGE_NOT_RIVER_FAILURE",
        "RIVER_FAILURE_NOT_URBAN_DRAINAGE",
    ),
    "CLOUDBURST_VS_URBAN_FLOOD": ("LOCALIZED_DOWNPOUR_NOT_GENERIC_WATERLOGGING",),
    "CYCLONE_INUNDATION_VS_URBAN_FLOOD": ("CYCLONE_SURGE_NOT_ROUTINE_URBAN_FLOOD",),
    "WEATHER_MENTION_VS_ACTUAL_EVENT": ("WEATHER_MENTION_WITHOUT_OBSERVED_EVENT",),
}


def _hard_negative_report(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    hard_indexes = [
        index for index, example in enumerate(examples) if example.hard_negative
    ]
    by_type: dict[str, list[int]] = defaultdict(list)
    for index in hard_indexes:
        hard_type = examples[index].hard_negative_type or "UNRECORDED"
        by_type[hard_type].append(index)
    return {
        "scope": "SYNTHETIC_ASSIGNED_SPLIT_ONLY",
        "overall": _metrics_for_indexes(examples, predictions, hard_indexes),
        "by_generator_type": {
            name: _metrics_for_indexes(
                examples,
                predictions,
                indexes,
                present_classes_only=True,
            )
            for name, indexes in sorted(by_type.items())
        },
        "distinctions": {
            distinction: _metrics_for_indexes(
                examples,
                predictions,
                [
                    index
                    for index in hard_indexes
                    if examples[index].hard_negative_type in hard_types
                ],
                present_classes_only=True,
            )
            for distinction, hard_types in HARD_NEGATIVE_DISTINCTIONS.items()
        },
    }


def _template_generalization_report(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    def grouped(attribute: str) -> dict[str, Any]:
        index_groups = _indexes_by_value(examples, attribute)
        return {
            name: _metrics_for_indexes(
                examples,
                predictions,
                indexes,
                present_classes_only=True,
            )
            for name, indexes in sorted(index_groups.items())
        }

    return {
        "scope": "HELD_OUT_SYNTHETIC_GENERATOR_FAMILIES",
        "base_template_family_count": len(
            {example.base_template_family for example in examples}
        ),
        "realized_structure_family_count": len(
            {example.realized_structure_family for example in examples}
        ),
        "base_template_families": grouped("base_template_family"),
        "realized_structure_families": grouped("realized_structure_family"),
    }


def _full_evaluation_report(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    return {
        "overall": _metric_set(
            [example.label for example in examples],
            predictions,
        ),
        "languages": _language_report(examples, predictions),
        "noise": _noise_report(examples, predictions),
        "hard_negatives": _hard_negative_report(examples, predictions),
        "template_generalization": _template_generalization_report(
            examples,
            predictions,
        ),
    }


def _candidate_evaluation(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
) -> dict[str, Any]:
    overall = _metric_set(
        [example.label for example in examples],
        predictions,
        include_confusion=False,
        include_per_class=False,
    )
    language_metrics = _language_report(examples, predictions)
    language_macro_f1 = {
        language: metrics["macro_f1"] for language, metrics in language_metrics.items()
    }
    available_language_scores = [
        float(value) for value in language_macro_f1.values() if value is not None
    ]
    hard_negative = _hard_negative_report(examples, predictions)["overall"]
    return {
        "overall": overall,
        "not_relevant_recall": overall["not_relevant_recall"],
        "hard_negative_accuracy": hard_negative["accuracy"],
        "hard_negative_macro_f1": hard_negative["macro_f1"],
        "language_macro_f1": language_macro_f1,
        "minimum_language_macro_f1": min(available_language_scores),
    }


def _new_vectorizer(
    *,
    analyzer: Literal["char", "word"],
    ngram_range: tuple[int, int],
    config: V3ProtocolConfig,
):
    from sklearn.feature_extraction.text import TfidfVectorizer

    return TfidfVectorizer(
        analyzer=analyzer,
        ngram_range=ngram_range,
        sublinear_tf=True,
        lowercase=False,
        norm="l2",
        token_pattern=r"(?u)\b\w+\b" if analyzer == "word" else None,
        min_df=config.vectorizer_min_df,
        max_features=(
            config.character_max_features
            if analyzer == "char"
            else config.word_max_features
        ),
        dtype=np.float32,
    )


def _fit_classifier(
    train_features: Any,
    train_labels: Sequence[str],
    candidate: V3Candidate,
    config: V3ProtocolConfig,
) -> tuple[Any, list[str]]:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression

    classifier = LogisticRegression(
        C=candidate.regularization_c,
        max_iter=config.max_iterations,
        tol=config.tolerance,
        random_state=config.random_seed,
        solver="lbfgs",
        class_weight=("balanced" if candidate.class_weight == "BALANCED" else None),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        classifier.fit(train_features, train_labels)
    convergence_warnings = [
        str(item.message)
        for item in caught
        if issubclass(item.category, ConvergenceWarning)
    ]
    return classifier, convergence_warnings


def _selection_sort_key(result: Mapping[str, Any]) -> tuple[Any, ...]:
    validation = result["validation"]
    configuration = result["configuration"]
    return (
        -float(validation["overall"]["macro_f1"]),
        -float(validation["not_relevant_recall"]),
        -float(validation["hard_negative_macro_f1"]),
        -float(validation["minimum_language_macro_f1"]),
        int(configuration["deterministic_tie_rank"]),
        str(configuration["configuration_id"]),
    )


def select_candidate_result(
    results: Sequence[Mapping[str, Any]],
    *,
    minimum_not_relevant_recall: float,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Apply the fixed validation-only selection rule and deterministic ties."""

    converged = [
        result for result in results if result["training_status"] == "CONVERGED"
    ]
    if not converged:
        raise RuntimeError("no v3 candidate converged")
    eligible = [
        result
        for result in converged
        if float(result["validation"]["not_relevant_recall"])
        >= minimum_not_relevant_recall
    ]
    pool = eligible or converged
    selected = min(pool, key=_selection_sort_key)
    return selected, {
        "rule_version": "nlp-v3-validation-selection-v1",
        "evaluation_split": "validation",
        "validation_row_count": 10_000,
        "primary_optimization": "maximize macro F1",
        "constraint": {
            "metric": "NOT_RELEVANT recall",
            "minimum": minimum_not_relevant_recall,
            "threshold_altered_after_results": False,
        },
        "ordered_tie_breaks": [
            "higher NOT_RELEVANT recall",
            "higher hard-negative macro F1",
            "higher minimum English/Hindi/Hinglish macro F1",
            "lower frozen deterministic complexity rank",
            "lexicographically smaller configuration ID",
        ],
        "selection_path": (
            "NOT_RELEVANT_FLOOR_SATISFIED"
            if eligible
            else "NO_CONFIGURATION_MET_NOT_RELEVANT_FLOOR"
        ),
        "eligible_configuration_ids": [
            item["configuration"]["configuration_id"]
            for item in sorted(eligible, key=_selection_sort_key)
        ],
        "selected_configuration_id": selected["configuration"]["configuration_id"],
        "test_set_used": False,
        "test_rows_available_to_function": False,
    }


def _best_candidate(
    results: Sequence[Mapping[str, Any]],
    *,
    class_weight: str | None = None,
    feature_weights: tuple[float, float] | None = None,
) -> Mapping[str, Any] | None:
    matching = []
    for result in results:
        configuration = result["configuration"]
        if class_weight is not None and configuration["class_weight"] != class_weight:
            continue
        if (
            feature_weights is not None
            and (
                float(configuration["character_weight"]),
                float(configuration["word_weight"]),
            )
            != feature_weights
        ):
            continue
        matching.append(result)
    return min(matching, key=_selection_sort_key) if matching else None


def _comparison_summary(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {"status": "NOT_EVALUATED"}
    return {
        "status": "EVALUATED",
        "configuration_id": result["configuration"]["configuration_id"],
        "validation": result["validation"],
    }


def run_controlled_model_selection(
    selection: SelectionDataset,
    *,
    config: V3ProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    candidates: Sequence[V3Candidate] | None = None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Fit the bounded search using train and validation only.

    The signature intentionally has no protected-test argument.  Every
    vectorizer calls ``fit_transform`` only on the 80,000 training texts;
    validation uses ``transform`` only.
    """

    from scipy.sparse import hstack

    selected_candidates = tuple(candidates or controlled_search_space())
    if not selected_candidates or len(selected_candidates) > 12:
        raise ValueError(
            "v3 controlled search must contain between 1 and 12 candidates"
        )
    train_texts = [normalize_text(example.text) for example in selection.train_examples]
    validation_texts = [
        normalize_text(example.text) for example in selection.validation_examples
    ]
    train_labels = [example.label for example in selection.train_examples]

    word_vectorizer = _new_vectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        config=config,
    )
    train_word = word_vectorizer.fit_transform(train_texts)
    validation_word = word_vectorizer.transform(validation_texts)
    results: list[dict[str, Any]] = []
    ranges = {
        candidate.feature_space_id: candidate.char_ngram_range
        for candidate in selected_candidates
    }
    for feature_space_id in sorted(ranges):
        char_range = ranges[feature_space_id]
        char_vectorizer = _new_vectorizer(
            analyzer="char",
            ngram_range=char_range,
            config=config,
        )
        train_char = char_vectorizer.fit_transform(train_texts)
        validation_char = char_vectorizer.transform(validation_texts)
        space_candidates = [
            candidate
            for candidate in selected_candidates
            if candidate.feature_space_id == feature_space_id
        ]
        for candidate in space_candidates:
            train_features = hstack(
                [
                    train_char * candidate.character_weight,
                    train_word * candidate.word_weight,
                ],
                format="csr",
                dtype=np.float32,
            )
            validation_features = hstack(
                [
                    validation_char * candidate.character_weight,
                    validation_word * candidate.word_weight,
                ],
                format="csr",
                dtype=np.float32,
            )
            classifier, convergence_warnings = _fit_classifier(
                train_features,
                train_labels,
                candidate,
                config,
            )
            predictions = classifier.predict(validation_features).tolist()
            candidate_evaluation = _candidate_evaluation(
                selection.validation_examples,
                predictions,
            )
            converged = not convergence_warnings and int(np.max(classifier.n_iter_)) < (
                config.max_iterations
            )
            results.append(
                {
                    "configuration": candidate.model_dump(mode="json"),
                    "training_status": "CONVERGED" if converged else "NOT_CONVERGED",
                    "classifier_iterations": [
                        int(value) for value in classifier.n_iter_.tolist()
                    ],
                    "convergence_warnings": convergence_warnings,
                    "feature_count": int(train_features.shape[1]),
                    "feature_fit_scope": "TRAIN_ONLY",
                    "validation_operation": "TRANSFORM_ONLY",
                    "validation": candidate_evaluation,
                }
            )
            del classifier, train_features, validation_features
        del char_vectorizer, train_char, validation_char
        gc.collect()
    del word_vectorizer, train_word, validation_word
    gc.collect()

    selected, selection_rule = select_candidate_result(
        results,
        minimum_not_relevant_recall=config.minimum_not_relevant_recall,
    )
    best_none = _best_candidate(results, class_weight="NONE")
    best_balanced = _best_candidate(results, class_weight="BALANCED")
    none_metrics = best_none["validation"] if best_none else None
    balanced_metrics = best_balanced["validation"] if best_balanced else None
    class_weight_conclusion = "MEASURED_RESULTS_RECORDED_WITHOUT_PRIOR_PREFERENCE"
    if none_metrics and balanced_metrics:
        equal = all(
            np.isclose(
                float(none_metrics[key]),
                float(balanced_metrics[key]),
                rtol=0.0,
                atol=1e-12,
            )
            for key in (
                "not_relevant_recall",
                "hard_negative_macro_f1",
                "minimum_language_macro_f1",
            )
        ) and np.isclose(
            float(none_metrics["overall"]["macro_f1"]),
            float(balanced_metrics["overall"]["macro_f1"]),
            rtol=0.0,
            atol=1e-12,
        )
        if equal:
            class_weight_conclusion = "NO_MEASURED_VALIDATION_BENEFIT_FROM_BALANCED"

    comparisons = {
        "class_weight": {
            "best_none": _comparison_summary(best_none),
            "best_balanced": _comparison_summary(best_balanced),
            "selected_class_weight": selected["configuration"]["class_weight"],
            "automatic_preference_for_balanced": False,
            "conclusion": class_weight_conclusion,
        },
        "feature_weighting": {
            "equal_1_0_1_0": _comparison_summary(
                _best_candidate(results, feature_weights=(1.0, 1.0))
            ),
            "character_1_25_word_0_75": _comparison_summary(
                _best_candidate(results, feature_weights=(1.25, 0.75))
            ),
            "character_1_5_word_0_5": _comparison_summary(
                _best_candidate(results, feature_weights=(1.5, 0.5))
            ),
        },
    }
    return tuple(results), {
        "selection_rule": selection_rule,
        "selected_result": dict(selected),
        "comparisons": comparisons,
    }


def _candidate_from_result(result: Mapping[str, Any]) -> V3Candidate:
    return V3Candidate.model_validate(result["configuration"])


def fit_selected_configuration(
    selection: SelectionDataset,
    selected: V3Candidate,
    *,
    config: V3ProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
) -> SelectedFit:
    """Refit the selected configuration from train only and transform validation."""

    from scipy.sparse import hstack

    train_texts = [normalize_text(example.text) for example in selection.train_examples]
    validation_texts = [
        normalize_text(example.text) for example in selection.validation_examples
    ]
    train_labels = [example.label for example in selection.train_examples]
    char_vectorizer = _new_vectorizer(
        analyzer="char",
        ngram_range=selected.char_ngram_range,
        config=config,
    )
    word_vectorizer = _new_vectorizer(
        analyzer="word",
        ngram_range=selected.word_ngram_range,
        config=config,
    )
    train_char = char_vectorizer.fit_transform(train_texts)
    train_word = word_vectorizer.fit_transform(train_texts)
    validation_char = char_vectorizer.transform(validation_texts)
    validation_word = word_vectorizer.transform(validation_texts)
    train_features = hstack(
        [
            train_char * selected.character_weight,
            train_word * selected.word_weight,
        ],
        format="csr",
        dtype=np.float32,
    )
    validation_features = hstack(
        [
            validation_char * selected.character_weight,
            validation_word * selected.word_weight,
        ],
        format="csr",
        dtype=np.float32,
    )
    classifier, convergence_warnings = _fit_classifier(
        train_features,
        train_labels,
        selected,
        config,
    )
    if convergence_warnings or int(np.max(classifier.n_iter_)) >= config.max_iterations:
        raise RuntimeError("selected v3 configuration did not converge")
    train_predictions = classifier.predict(train_features).tolist()
    validation_predictions = classifier.predict(validation_features).tolist()
    validation_logits = np.asarray(
        classifier.decision_function(validation_features),
        dtype=np.float64,
    )
    feature_count = int(train_features.shape[1])
    del train_char, train_word, validation_char, validation_word
    del train_features, validation_features
    gc.collect()
    return SelectedFit(
        candidate=selected,
        char_vectorizer=char_vectorizer,
        word_vectorizer=word_vectorizer,
        classifier=classifier,
        train_predictions=train_predictions,
        validation_predictions=validation_predictions,
        validation_logits=validation_logits,
        feature_count=feature_count,
        classifier_iterations=[int(value) for value in classifier.n_iter_.tolist()],
    )


def _row_softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    scaled = logits / temperature
    shifted = scaled - np.max(scaled, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _multiclass_brier(
    probabilities: np.ndarray,
    label_indexes: np.ndarray,
) -> float:
    targets = np.zeros_like(probabilities)
    targets[np.arange(len(label_indexes)), label_indexes] = 1.0
    return float(np.mean(np.sum((probabilities - targets) ** 2, axis=1)))


def _reliability_report(
    probabilities: np.ndarray,
    label_indexes: np.ndarray,
    bins: int,
) -> dict[str, Any]:
    confidences = np.max(probabilities, axis=1)
    predictions = np.argmax(probabilities, axis=1)
    correct = predictions == label_indexes
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(bins):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        mask = (confidences >= lower) & (
            confidences <= upper if index == bins - 1 else confidences < upper
        )
        count = int(mask.sum())
        if count:
            mean_confidence = float(confidences[mask].mean())
            empirical_accuracy = float(correct[mask].mean())
            gap = abs(mean_confidence - empirical_accuracy)
            ece += (count / len(label_indexes)) * gap
        else:
            mean_confidence = None
            empirical_accuracy = None
            gap = None
        rows.append(
            {
                "lower_inclusive": lower,
                "upper_exclusive": upper if index < bins - 1 else None,
                "upper_inclusive": upper if index == bins - 1 else None,
                "sample_count": count,
                "mean_confidence": mean_confidence,
                "empirical_accuracy": empirical_accuracy,
                "absolute_gap": gap,
            }
        )
    return {
        "bin_count": bins,
        "expected_calibration_error": float(ece),
        "bins": rows,
    }


def evaluate_validation_calibration(
    fit: SelectedFit,
    validation_labels: Sequence[str],
    validation_split_sha256: str,
    *,
    config: V3ProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
) -> tuple[NLPCalibrationState, dict[str, Any]]:
    """Fit one scalar temperature using validation logits and labels only."""

    from scipy.optimize import minimize_scalar
    from sklearn.metrics import log_loss

    classes = [str(value) for value in fit.classifier.classes_]
    class_indexes = {label: index for index, label in enumerate(classes)}
    label_indexes = np.asarray(
        [class_indexes[label] for label in validation_labels],
        dtype=np.int64,
    )
    before_probabilities = _row_softmax(fit.validation_logits)
    before_log_loss = float(
        log_loss(
            label_indexes,
            before_probabilities,
            labels=list(range(len(classes))),
        )
    )
    before_brier = _multiclass_brier(before_probabilities, label_indexes)
    before_reliability = _reliability_report(
        before_probabilities,
        label_indexes,
        config.calibration_bins,
    )

    def objective(temperature: float) -> float:
        probabilities = _row_softmax(fit.validation_logits, float(temperature))
        return float(
            log_loss(
                label_indexes,
                probabilities,
                labels=list(range(len(classes))),
            )
        )

    bounds = (config.calibration_lower_bound, config.calibration_upper_bound)
    optimization = minimize_scalar(
        objective,
        bounds=bounds,
        method="bounded",
        options={"xatol": 1e-8},
    )
    temperature = float(optimization.x)
    after_probabilities = _row_softmax(fit.validation_logits, temperature)
    after_log_loss = objective(temperature)
    after_brier = _multiclass_brier(after_probabilities, label_indexes)
    after_reliability = _reliability_report(
        after_probabilities,
        label_indexes,
        config.calibration_bins,
    )
    boundary_tolerance = max(1e-6, (bounds[1] - bounds[0]) * 1e-4)
    boundary_reached = (
        abs(temperature - bounds[0]) <= boundary_tolerance
        or abs(temperature - bounds[1]) <= boundary_tolerance
    )
    boundary_status = (
        "CALIBRATION_SEARCH_BOUNDARY_REACHED"
        if boundary_reached
        else "INTERIOR_OPTIMUM"
    )
    use_calibration = bool(
        optimization.success
        and np.isfinite(temperature)
        and after_log_loss < before_log_loss - 1e-12
    )
    if use_calibration:
        state = NLPCalibrationState(
            method="TEMPERATURE_SCALING",
            status="CALIBRATED_ON_VALIDATION",
            temperature=temperature,
            validation_split_sha256=validation_split_sha256,
            validation_log_loss_before=before_log_loss,
            validation_log_loss_after=after_log_loss,
            validation_brier_before=before_brier,
            validation_brier_after=after_brier,
            validation_ece_before=before_reliability["expected_calibration_error"],
            validation_ece_after=after_reliability["expected_calibration_error"],
            search_bounds=bounds,
            search_boundary_status=boundary_status,
        )
        selected_status = "CALIBRATED_ON_VALIDATION"
    else:
        state = NLPCalibrationState()
        selected_status = "NOT_CALIBRATED"
    report = {
        "schema_version": "1.0",
        "evaluation_scope": "VALIDATION_ONLY",
        "validation_split_sha256": validation_split_sha256,
        "method_evaluated": "SCALAR_TEMPERATURE_SCALING",
        "selected_status": selected_status,
        "selected_method": state.method,
        "selected_temperature": state.temperature,
        "optimization": {
            "success": bool(optimization.success),
            "message": str(optimization.message),
            "bounds": list(bounds),
            "candidate_temperature": temperature,
            "boundary_status": boundary_status,
            "search_expanded": False,
            "objective": "multiclass log loss",
        },
        "metrics": {
            "pre_calibration_log_loss": before_log_loss,
            "post_calibration_log_loss": after_log_loss,
            "pre_calibration_multiclass_brier": before_brier,
            "post_calibration_multiclass_brier": after_brier,
            "pre_calibration_ece": before_reliability["expected_calibration_error"],
            "post_calibration_ece": after_reliability["expected_calibration_error"],
        },
        "reliability_before": before_reliability,
        "reliability_after": after_reliability,
        "test_used": False,
        "production_calibration": "NOT_VALIDATED",
        "limitations": [
            "Calibration was fitted and measured on synthetic validation data.",
            "A boundary result is reported without expanding the search or touching test data.",
        ],
    }
    return state, report


def _library_versions() -> dict[str, str]:
    import scipy
    import sklearn

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


def _frozen_space(
    vectorizer: Any,
    *,
    analyzer: Literal["char", "word"],
    ngram_range: tuple[int, int],
    config: V3ProtocolConfig,
) -> FrozenTfidfSpace:
    return FrozenTfidfSpace(
        analyzer=analyzer,
        ngram_range=ngram_range,
        vocabulary={term: int(index) for term, index in vectorizer.vocabulary_.items()},
        idf=[float(value) for value in vectorizer.idf_],
        vectorizer_config={
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
            "token_pattern": r"(?u)\b\w+\b" if analyzer == "word" else None,
            "min_df": config.vectorizer_min_df,
            "max_features": (
                config.character_max_features
                if analyzer == "char"
                else config.word_max_features
            ),
            "dtype": "float32",
            "fit_scope": "TRAIN_ONLY",
            "local_only": True,
        },
    )


def _create_artifact(
    prepared: PreparedSyntheticData,
    fit: SelectedFit,
    calibration: NLPCalibrationState,
    config: V3ProtocolConfig,
    created_at: datetime,
) -> NLPClassifierArtifact:
    versions = _library_versions()
    classes = [str(value) for value in fit.classifier.classes_]
    if classes != list(V3_CLASSES):
        raise RuntimeError(f"unexpected v3 class order: {classes}")
    return NLPClassifierArtifact(
        artifact_version="nlp-classifier-artifact-v3",
        model_version=config.model_version,
        model_status=DEVELOPMENT_STATUS,
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        classes=classes,
        char_space=_frozen_space(
            fit.char_vectorizer,
            analyzer="char",
            ngram_range=fit.candidate.char_ngram_range,
            config=config,
        ),
        word_space=_frozen_space(
            fit.word_vectorizer,
            analyzer="word",
            ngram_range=fit.candidate.word_ngram_range,
            config=config,
        ),
        feature_weights=NLPFeatureWeights(
            character=fit.candidate.character_weight,
            word=fit.candidate.word_weight,
        ),
        classifier=NLPLinearClassifierState(
            regularization_c=fit.candidate.regularization_c,
            max_iterations=config.max_iterations,
            random_state=config.random_seed,
            solver="lbfgs",
            class_weight=fit.candidate.class_weight,
            classes=classes,
            coefficients=fit.classifier.coef_.tolist(),
            intercept=fit.classifier.intercept_.tolist(),
        ),
        calibration=calibration,
        n_features=fit.feature_count,
        provenance={
            "dataset_identifier": EXPECTED_DATASET_ID,
            "dataset_version": EXPECTED_DATASET_VERSION,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "training_split_sha256": prepared.selection.train_sha256,
            "validation_split_sha256": prepared.selection.validation_sha256,
            "final_test_split_sha256": prepared.protected_test.split_sha256,
            "split_version": EXPECTED_SPLIT_VERSION,
            "training_timestamp": created_at.isoformat(),
            "dataset_status": (
                "SYNTHETIC / DEVELOPMENT_ONLY / NOT_REAL_WORLD_VALIDATED"
            ),
            "python_version": versions["python"],
            "scikit_learn_version": versions["scikit_learn"],
            "numpy_version": versions["numpy"],
            "random_state": config.random_seed,
            "classifier_configuration": {
                **fit.candidate.model_dump(mode="json"),
                "solver": "lbfgs",
                "max_iterations": config.max_iterations,
                "tolerance": config.tolerance,
                "calibration_method": calibration.method,
                "classifier_iterations": fit.classifier_iterations,
            },
            "class_distribution": _counter_payload(
                prepared.selection.train_examples,
                "label",
            ),
            "dataset_generator_version": EXPECTED_GENERATOR_VERSION,
            "dataset_generator_seed": EXPECTED_GENERATOR_SEED,
            "dataset_manifest_sha256": (prepared.binding.dataset_manifest_sha256),
            "scenario_metadata_sha256": (prepared.binding.scenario_metadata_sha256),
        },
    )


def _vectorizer_from_frozen_space(space: FrozenTfidfSpace):
    """Reconstruct transform-only sklearn state without calling fit()."""

    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        analyzer=space.analyzer,
        ngram_range=tuple(space.ngram_range),
        sublinear_tf=True,
        lowercase=False,
        norm="l2",
        token_pattern=(r"(?u)\b\w+\b" if space.analyzer == "word" else None),
        vocabulary=dict(space.vocabulary),
        dtype=np.float64,
    )
    vectorizer.idf_ = np.asarray(space.idf, dtype=np.float64)
    return vectorizer


def batch_predict_artifact(
    artifact: NLPClassifierArtifact,
    texts: Sequence[str],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Run sparse, transform-only batch inference from the frozen JSON state."""

    from scipy.sparse import hstack

    normalized = [normalize_text(text) for text in texts]
    char_vectorizer = _vectorizer_from_frozen_space(artifact.char_space)
    word_vectorizer = _vectorizer_from_frozen_space(artifact.word_space)
    char_features = (
        char_vectorizer.transform(normalized) * artifact.feature_weights.character
    )
    word_features = (
        word_vectorizer.transform(normalized) * artifact.feature_weights.word
    )
    features = hstack(
        [char_features, word_features],
        format="csr",
        dtype=np.float64,
    )
    coefficients = np.asarray(artifact.classifier.coefficients, dtype=np.float64)
    intercept = np.asarray(artifact.classifier.intercept, dtype=np.float64)
    logits = np.asarray(features @ coefficients.T + intercept, dtype=np.float64)
    probabilities = _row_softmax(logits, artifact.calibration.temperature)
    indexes = np.argmax(probabilities, axis=1)
    predictions = [artifact.classes[int(index)] for index in indexes]
    return predictions, probabilities, logits


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _register_artifact(
    artifact_path: Path,
    artifact: NLPClassifierArtifact,
    manifest_path: Path,
) -> None:
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=artifact.model_version,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=artifact.provenance.dataset_sha256,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        training_timestamp=artifact.provenance.training_timestamp,
        random_seed=artifact.provenance.random_state,
        framework_versions=_library_versions(),
        intended_component="nlp_classifier",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    if manifest_path.exists():
        manifest = ArtifactManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    else:
        manifest = ArtifactManifest(
            manifest_version="1.0",
            schema_version="1.0",
            policy_status="SCAFFOLD_ONLY",
            runtime_downloads_allowed=False,
        )
    retained = [
        item
        for item in manifest.artifacts
        if not (
            item.artifact_name == metadata.artifact_name
            and item.intended_component == metadata.intended_component
        )
    ]
    retained.append(metadata)
    _write_json(
        manifest_path,
        manifest.model_copy(update={"artifacts": retained}).model_dump(mode="json"),
    )


def _require_absent(paths: Sequence[Path], *, operation: str) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            f"Phase 18 {operation} is immutable; refusing to overwrite: "
            + ", ".join(existing)
        )


def _selected_result_matches_refit(
    selected_result: Mapping[str, Any],
    validation_report: Mapping[str, Any],
) -> None:
    expected = selected_result["validation"]
    comparisons = {
        "macro_f1": (
            expected["overall"]["macro_f1"],
            validation_report["overall"]["macro_f1"],
        ),
        "not_relevant_recall": (
            expected["not_relevant_recall"],
            validation_report["overall"]["not_relevant_recall"],
        ),
        "hard_negative_macro_f1": (
            expected["hard_negative_macro_f1"],
            validation_report["hard_negatives"]["overall"]["macro_f1"],
        ),
    }
    failed = [
        name
        for name, (left, right) in comparisons.items()
        if not np.isclose(float(left), float(right), rtol=0.0, atol=1e-12)
    ]
    if failed:
        raise RuntimeError(
            "selected v3 refit did not reproduce search metrics: " + ", ".join(failed)
        )


def freeze_synthetic_v3_model(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    search_path: Path | str = DEFAULT_SEARCH_PATH,
    calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    config: V3ProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Select, calibrate, serialize, authorize, and freeze without test inference."""

    artifact_path = local_only_path(artifact_path, description="NLP artifacts")
    development_manifest_path = local_only_path(
        development_manifest_path,
        description="development manifests",
    )
    search_path = local_only_path(search_path, description="search reports")
    calibration_path = local_only_path(
        calibration_path,
        description="calibration reports",
    )
    artifact_manifest_path = local_only_path(
        artifact_manifest_path,
        description="artifact manifests",
    )
    _require_absent(
        (artifact_path, development_manifest_path, search_path, calibration_path),
        operation="freeze",
    )
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("v3 creation timestamp must include a timezone")

    prepared = prepare_synthetic_selection_data(registry_path=registry_path)
    candidate_results, selection_summary = run_controlled_model_selection(
        prepared.selection,
        config=config,
    )
    selected_result = selection_summary["selected_result"]
    selected_candidate = _candidate_from_result(selected_result)
    fit = fit_selected_configuration(
        prepared.selection,
        selected_candidate,
        config=config,
    )
    train_report = _full_evaluation_report(
        prepared.selection.train_examples,
        fit.train_predictions,
    )
    validation_report = _full_evaluation_report(
        prepared.selection.validation_examples,
        fit.validation_predictions,
    )
    _selected_result_matches_refit(selected_result, validation_report)
    calibration_state, calibration_report = evaluate_validation_calibration(
        fit,
        [example.label for example in prepared.selection.validation_examples],
        prepared.selection.validation_sha256,
        config=config,
    )
    artifact = _create_artifact(
        prepared,
        fit,
        calibration_state,
        config,
        timestamp,
    )

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        artifact.model_dump_json(indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    artifact_sha256 = file_sha256(artifact_path)
    _register_artifact(artifact_path, artifact, artifact_manifest_path)
    authorized = load_nlp_artifact(
        artifact_path,
        manifest_path=artifact_manifest_path,
    )
    serialized_validation_predictions, _, _ = batch_predict_artifact(
        authorized,
        [example.text for example in prepared.selection.validation_examples],
    )
    if serialized_validation_predictions != fit.validation_predictions:
        raise RuntimeError(
            "serialized v3 feature/classifier state changed validation predictions"
        )

    frozen_configuration = {
        "preprocessing_version": config.preprocessing_version,
        "feature_version": config.feature_version,
        "character_ngram_range": list(selected_candidate.char_ngram_range),
        "word_ngram_range": list(selected_candidate.word_ngram_range),
        "feature_weights": {
            "character": selected_candidate.character_weight,
            "word": selected_candidate.word_weight,
        },
        "feature_fitting": {
            "fit_split": "train",
            "fit_count": EXPECTED_COUNTS["train"],
            "validation_operation": "transform",
            "test_operation": "transform",
            "min_df": config.vectorizer_min_df,
            "character_max_features": config.character_max_features,
            "word_max_features": config.word_max_features,
        },
        "classifier": {
            "kind": "logistic_regression",
            "solver": "lbfgs",
            "regularization_c": selected_candidate.regularization_c,
            "class_weight": selected_candidate.class_weight,
            "max_iterations": config.max_iterations,
            "tolerance": config.tolerance,
            "iterations": fit.classifier_iterations,
        },
        "random_seed": config.random_seed,
        "calibration": calibration_state.model_dump(mode="json"),
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "dataset_generator_version": EXPECTED_GENERATOR_VERSION,
        "dataset_generator_seed": EXPECTED_GENERATOR_SEED,
        "train_split_sha256": prepared.selection.train_sha256,
        "validation_split_sha256": prepared.selection.validation_sha256,
        "test_split_sha256": prepared.protected_test.split_sha256,
    }
    frozen_configuration_sha256 = _canonical_hash(frozen_configuration)
    search_report = {
        "schema_version": "1.0",
        "protocol_version": config.protocol_version,
        "search_scope": "TRAIN_AND_VALIDATION_ONLY",
        "configuration_count": len(candidate_results),
        "configurations": list(candidate_results),
        **selection_summary,
        "feature_vocabulary_fit_split": "train",
        "validation_operation": "transform_only",
        "test_accessed": False,
        "search_space_generated_as_large_grid": False,
    }
    _write_json(search_path, search_report)
    _write_json(calibration_path, calibration_report)
    development_manifest = {
        "schema_version": "1.0",
        "protocol_version": config.protocol_version,
        "status": "FROZEN_FOR_FINAL_TEST",
        "development_status": DEVELOPMENT_STATUS,
        "synthetic_development_only": True,
        "production_status": PRODUCTION_STATUS,
        "production_validation": PRODUCTION_VALIDATION,
        "field_validation": "NOT_VALIDATED",
        "real_world_validation": "NOT_VALIDATED",
        "created_at": timestamp.isoformat(),
        "dataset": {
            "dataset_id": EXPECTED_DATASET_ID,
            "dataset_version": EXPECTED_DATASET_VERSION,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "generator_version": EXPECTED_GENERATOR_VERSION,
            "generator_seed": EXPECTED_GENERATOR_SEED,
            "dataset_manifest_sha256": (prepared.binding.dataset_manifest_sha256),
            "scenario_metadata_sha256": (prepared.binding.scenario_metadata_sha256),
            "quality_report_sha256": prepared.binding.quality_report_sha256,
            "registry_path": str(prepared.binding.registry_path),
            "dataset_path": str(prepared.binding.dataset_path),
            "scenario_path": str(prepared.binding.scenario_path),
            "classification": "DEVELOPMENT_ONLY",
            "data_kind": "SYNTHETIC",
            "label_source": "GENERATOR_SCENARIO_SPECIFICATION",
            "production_training_gate": (prepared.binding.production_training_gate),
            "development_exception_scope": (
                "EXACT_HASH_BOUND_SYNTHETIC_EXPERIMENT_ONLY"
            ),
        },
        "split": prepared.split_manifest,
        "selection": {
            "configuration_count": len(candidate_results),
            "selected_configuration": selected_candidate.model_dump(mode="json"),
            "selected_validation_summary": selected_result["validation"],
            "selection_rule": selection_summary["selection_rule"],
            "comparisons": selection_summary["comparisons"],
            "search_report_path": str(search_path.resolve()),
            "search_report_sha256": file_sha256(search_path),
        },
        "training_metrics": train_report,
        "validation_metrics": validation_report,
        "language_validation": validation_report["languages"],
        "noise_validation": validation_report["noise"],
        "hard_negative_validation": validation_report["hard_negatives"],
        "template_generalization_validation": validation_report[
            "template_generalization"
        ],
        "calibration": calibration_report,
        "calibration_report_path": str(calibration_path.resolve()),
        "calibration_report_sha256": file_sha256(calibration_path),
        "frozen_configuration": frozen_configuration,
        "frozen_configuration_sha256": frozen_configuration_sha256,
        "artifact": {
            "path": str(artifact_path.resolve()),
            "artifact_name": artifact_path.name,
            "artifact_format_version": artifact.artifact_version,
            "model_version": artifact.model_version,
            "model_status": artifact.model_status,
            "sha256": artifact_sha256,
            "n_features": artifact.n_features,
            "class_mapping": artifact.classes,
            "coefficient_shape": [
                len(artifact.classifier.coefficients),
                len(artifact.classifier.coefficients[0]),
            ],
            "structural_authorization": "PASS",
            "manifest_authorized": True,
            "library_versions": _library_versions(),
        },
        "final_test": {
            "status": "NOT_ACCESSED_FOR_EVALUATION",
            "required_evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
            "sample_count": prepared.protected_test.sample_count,
            "split_sha256": prepared.protected_test.split_sha256,
            "source_order_sha256": prepared.protected_test.source_order_sha256,
            "record_ids_in_source_order": list(
                prepared.protected_test.record_ids_in_source_order
            ),
            "available_to_configuration_selection": False,
            "configuration_changes_permitted_after_freeze": False,
            "evaluation_invocation_limit": 1,
        },
        "policy": {
            "allowed_libraries": [
                "standard_python",
                "numpy",
                "scipy",
                "scikit_learn",
            ],
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "runtime_downloads": False,
            "transfer_learning": False,
            "live_backend_modified": False,
            "default_nlp_configuration_modified": False,
        },
        "known_limitations": [
            "All training, validation, and holdout examples are project-generated synthetic text.",
            "Synthetic holdout performance does not estimate field or real-world performance.",
            "Generator lexicons, templates, framing rules, and controlled noise cannot represent the full deployment distribution.",
            "HIGH noise is held out for test, so validation has no HIGH-noise rows and reports that stratum explicitly as unavailable.",
            "Calibration is selected and measured on the same synthetic validation partition.",
            "No human-adjudicated real-data evaluation or production calibration exists.",
        ],
    }
    _write_json(development_manifest_path, development_manifest)
    return {
        "status": "FROZEN_FOR_FINAL_TEST",
        "development_status": DEVELOPMENT_STATUS,
        "production_status": PRODUCTION_STATUS,
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha256,
        "development_manifest_path": str(development_manifest_path),
        "development_manifest_sha256": file_sha256(development_manifest_path),
        "selected_configuration": selected_candidate.configuration_id,
        "configuration_count": len(candidate_results),
        "validation": validation_report["overall"],
        "calibration": calibration_report["selected_status"],
        "calibration_boundary": calibration_report["optimization"]["boundary_status"],
        "test_accessed": False,
    }


def _error_item(
    example: SyntheticExample,
    prediction: str,
) -> dict[str, Any]:
    return {
        "record_id": example.record_id,
        "true_label": example.label,
        "predicted_label": prediction,
        "language": example.language,
        "noise_profile": example.noise_profile,
        "hard_negative": example.hard_negative,
        "hard_negative_type": example.hard_negative_type,
        "base_template_family": example.base_template_family,
        "realized_structure_family": example.realized_structure_family,
        "text": example.text,
    }


def _summarize_error_items(
    items: Sequence[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: (
            item["true_label"],
            item["predicted_label"],
            item["record_id"],
        ),
    )
    return {
        "count": len(ordered),
        "examples_returned": min(len(ordered), limit),
        "examples_truncated": len(ordered) > limit,
        "examples": ordered[:limit],
    }


def deterministic_error_analysis(
    examples: Sequence[SyntheticExample],
    predictions: Sequence[str],
    *,
    limit: int,
) -> dict[str, Any]:
    """Categorize holdout errors deterministically without explanatory AI."""

    errors = [
        _error_item(example, prediction)
        for example, prediction in zip(examples, predictions, strict=True)
        if example.label != prediction
    ]
    false_positives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    false_negatives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confusions: Counter[tuple[str, str]] = Counter()
    for item in errors:
        false_positives[item["predicted_label"]].append(item)
        false_negatives[item["true_label"]].append(item)
        confusions[(item["true_label"], item["predicted_label"])] += 1

    def category(predicate) -> dict[str, Any]:
        return _summarize_error_items(
            [item for item in errors if predicate(item)],
            limit=limit,
        )

    report = {
        "schema_version": "1.0",
        "analysis_method": "DETERMINISTIC_RULE_BASED_GROUPING",
        "external_ai_used": False,
        "evaluation_scope": "FINAL_SYNTHETIC_HOLDOUT_ONLY",
        "total_errors": len(errors),
        "false_positives": {
            label: _summarize_error_items(false_positives.get(label, []), limit=limit)
            for label in V3_CLASSES
        },
        "false_negatives": {
            label: _summarize_error_items(false_negatives.get(label, []), limit=limit)
            for label in V3_CLASSES
        },
        "class_confusions": [
            {
                "true_label": true_label,
                "predicted_label": predicted_label,
                "count": count,
            }
            for (true_label, predicted_label), count in sorted(
                confusions.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ],
        "not_relevant_errors": category(
            lambda item: (
                item["true_label"] == "NOT_RELEVANT"
                or item["predicted_label"] == "NOT_RELEVANT"
            )
        ),
        "hindi_errors": category(lambda item: item["language"] == "Hindi"),
        "hinglish_errors": category(lambda item: item["language"] == "Hinglish"),
        "hard_negative_errors": category(lambda item: item["hard_negative"]),
        "high_noise_errors": category(lambda item: item["noise_profile"] == "HIGH"),
        "held_out_template_errors": category(
            lambda item: bool(item["base_template_family"])
        ),
    }
    report["analysis_sha256"] = _canonical_hash(report)
    return report


def _config_for_artifact(
    artifact: NLPClassifierArtifact,
    artifact_path: Path,
) -> NLPClassifierConfig:
    return NLPClassifierConfig(
        model_version=artifact.model_version,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        artifact_path=artifact_path,
        metrics_path=DEFAULT_METRICS_PATH,
        char_ngram_range=tuple(artifact.char_space.ngram_range),
        word_ngram_range=tuple(artifact.word_space.ngram_range),
        regularization_grid=(artifact.classifier.regularization_c,),
        regularization_c=artifact.classifier.regularization_c,
        max_iterations=artifact.classifier.max_iterations,
        random_state=artifact.classifier.random_state,
    )


def _validate_v3_golden_contract(scenario: Any, execution: Any) -> None:
    """Validate stable contracts while allowing model-dependent snapshots."""

    expected_statuses = scenario.expected_component_statuses
    if set(execution.unified_results) != set(expected_statuses):
        raise AssertionError("v3 golden report identifiers changed")
    for report_id, result in execution.unified_results.items():
        expected = expected_statuses[report_id]
        actual = {
            "NLP": result.text_prediction.status,
            "DUPLICATE": result.duplicate_prediction.status,
            "EVENT": result.event_prediction.status,
            "CREDIBILITY": result.credibility_prediction.status,
            "IMAGE": result.image_prediction.status,
            "ANOMALY": result.anomaly_prediction.status,
        }
        if actual != expected.model_dump():
            raise AssertionError(f"v3 component status changed for {report_id}")
        if tuple(result.model_dump(mode="json")) != tuple(UnifiedMLResult.model_fields):
            raise AssertionError("UnifiedMLResult field order changed")
        restored = UnifiedMLResult.model_validate_json(result.model_dump_json())
        if restored != result:
            raise AssertionError("UnifiedMLResult serialization changed")
        component_predictions = (
            ("nlp_classifier", result.text_prediction),
            ("duplicate_matcher", result.duplicate_prediction),
            ("event_detector", result.event_prediction),
            ("fake_detector", result.credibility_prediction),
            ("image_analyzer", result.image_prediction),
            ("anomaly_detector", result.anomaly_prediction),
        )
        expected_model_versions = {
            name: prediction.model_version
            for name, prediction in component_predictions
            if prediction.model_version is not None
        }
        if result.model_versions != expected_model_versions:
            raise AssertionError("UnifiedMLResult model-version map changed")
        expected_feature_versions = {
            name: prediction.feature_version
            for name, prediction in component_predictions
            if prediction.feature_version is not None
        }
        if result.feature_versions != expected_feature_versions:
            raise AssertionError("UnifiedMLResult feature-version map changed")
        candidate = result.event_prediction.candidate_event
        if candidate is not None and candidate.lifecycle_state == "CONFIRMED":
            raise AssertionError("single report became a confirmed event")
    if not execution.invariant_checks or not all(execution.invariant_checks.values()):
        raise AssertionError("cross-component semantic invariant failed")
    if execution.event_result is not None and any(
        candidate.status.value == "CONFIRMED"
        for candidate in execution.event_result.candidates
    ):
        raise AssertionError("synthetic golden batch produced a confirmed event")
    if scenario.expected_duplicate_relationship is not None:
        expected_duplicate = scenario.expected_duplicate_relationship
        result = execution.unified_results[str(expected_duplicate.report_id)]
        if (
            result.duplicate_prediction.is_duplicate
            is not expected_duplicate.is_duplicate
            or result.duplicate_prediction.matched_report_id
            != expected_duplicate.matched_report_id
        ):
            raise AssertionError("duplicate semantics changed under v3")
    if scenario.expected_anomaly_outcome is not None:
        expected_anomaly = scenario.expected_anomaly_outcome
        prediction = execution.anomaly_prediction
        if prediction is None or (
            prediction.status is not expected_anomaly.status
            or prediction.anomaly_domain is not expected_anomaly.anomaly_domain
            or prediction.is_anomaly is not expected_anomaly.is_anomaly
            or (prediction.score is not None) is not expected_anomaly.score_present
        ):
            raise AssertionError("anomaly semantics changed under v3")


def run_v3_golden_regression(
    *,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    output_path: Path | str = DEFAULT_GOLDEN_PATH,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    """Run the existing golden scenarios with an opt-in v3 inference engine."""

    artifact_path = local_only_path(artifact_path, description="NLP artifacts")
    development_manifest_path = local_only_path(
        development_manifest_path,
        description="development manifests",
    )
    artifact_manifest_path = local_only_path(
        artifact_manifest_path,
        description="artifact manifests",
    )
    output_path = local_only_path(output_path, description="golden reports")
    _require_absent((output_path,), operation="golden regression")
    development_manifest = _read_json(development_manifest_path)
    artifact = load_nlp_artifact(
        artifact_path,
        manifest_path=artifact_manifest_path,
    )
    artifact_sha256 = file_sha256(artifact_path)
    if artifact_sha256 != development_manifest["artifact"]["sha256"]:
        raise ValueError("v3 artifact changed after development freeze")
    classifier = NLPClassifier(
        _config_for_artifact(artifact, artifact_path),
        artifact_path=artifact_path,
        manifest_path=artifact_manifest_path,
    )
    engine = InferenceEngine(nlp_classifier=classifier)
    suite = load_golden_scenarios()
    scenario_results: list[dict[str, Any]] = []

    def reject_network(*_args, **_kwargs):
        raise AssertionError("network access attempted during v3 golden regression")

    with patch("soc" + "ket.socket", side_effect=reject_network):
        for scenario in suite.scenarios:
            baseline = validate_golden_scenario(scenario)
            first = execute_golden_scenario(scenario, engine=engine)
            second = execute_golden_scenario(scenario, engine=engine)
            _validate_v3_golden_contract(scenario, first)
            _validate_v3_golden_contract(scenario, second)
            if first.semantic_payload() != second.semantic_payload():
                raise AssertionError(
                    f"v3 golden output is not deterministic: {scenario.scenario_id}"
                )
            strict_v1_snapshot_match = True
            try:
                validate_golden_scenario(scenario, first)
            except AssertionError:
                strict_v1_snapshot_match = False
            for result in first.unified_results.values():
                restored = UnifiedMLResult.model_validate_json(result.model_dump_json())
                if restored != result:
                    raise AssertionError("UnifiedMLResult serialization changed")
                if result.text_prediction.model_version != MODEL_VERSION:
                    raise AssertionError("golden engine did not use NLP v3")
            scenario_results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "status": "PASS",
                    "existing_v1_golden_snapshot": "PASS",
                    "v3_contract_regression": "PASS",
                    "strict_v1_model_dependent_snapshot_match": (
                        strict_v1_snapshot_match
                    ),
                    "report_count": len(first.unified_results),
                    "baseline_semantic_sha256": _canonical_hash(
                        baseline.semantic_payload()
                    ),
                    "semantic_sha256": _canonical_hash(first.semantic_payload()),
                    "invariant_checks": first.invariant_checks,
                    "nlp_statuses": {
                        report_id: result.text_prediction.status.value
                        for report_id, result in sorted(first.unified_results.items())
                    },
                }
            )
    timestamp = executed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("golden execution timestamp must include a timezone")
    report = {
        "schema_version": "1.0",
        "status": "PASS",
        "suite_version": suite.suite_version,
        "executed_at": timestamp.isoformat(),
        "artifact_sha256": artifact_sha256,
        "model_version": artifact.model_version,
        "scenario_count": len(scenario_results),
        "scenarios": scenario_results,
        "existing_v1_golden_suite": "PASS",
        "v3_existing_fixture_contract_suite": "PASS",
        "strict_v1_snapshot_mismatch_count": sum(
            not item["strict_v1_model_dependent_snapshot_match"]
            for item in scenario_results
        ),
        "snapshot_interpretation": (
            "Exact v1 label/event snapshots are model-dependent; differences are "
            "recorded, while component statuses, schemas, serialization, lifecycle "
            "safety, and cross-component invariants remain mandatory."
        ),
        "unified_ml_result_schema_unchanged": True,
        "status_semantics_unchanged": True,
        "serialization_round_trip": "PASS",
        "determinism": "PASS",
        "cross_component_invariants": "PASS",
        "network_access": False,
        "live_backend_modified": False,
        "default_configuration_modified": False,
        "evidence_scope": "ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION",
    }
    _write_json(output_path, report)
    return report


def _claim_final_evaluation(
    receipt_path: Path,
    *,
    development_manifest_sha256: str,
    artifact_sha256: str,
    claimed_at: datetime,
) -> None:
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    claim = {
        "schema_version": "1.0",
        "status": "FINAL_EVALUATION_CLAIMED",
        "evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
        "claimed_at": claimed_at.isoformat(),
        "development_manifest_sha256": development_manifest_sha256,
        "artifact_sha256": artifact_sha256,
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
    }
    try:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(claim, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as error:
        raise RuntimeError(
            "v3 final synthetic holdout was already claimed; reevaluation is prohibited"
        ) from error


def _load_protected_test_once(
    binding: SyntheticDatasetBinding,
    descriptor: Mapping[str, Any],
) -> list[SyntheticExample]:
    """Load the protected rows only after the exclusive receipt is claimed."""

    examples: list[SyntheticExample] = []
    record_ids: list[str] = []
    split_hasher = hashlib.sha256()
    with (
        binding.dataset_path.open(encoding="utf-8") as dataset_handle,
        binding.scenario_path.open(encoding="utf-8") as scenario_handle,
    ):
        for line_number, pair in enumerate(
            zip_longest(dataset_handle, scenario_handle),
            start=1,
        ):
            dataset_line, scenario_line = pair
            if dataset_line is None or scenario_line is None:
                raise ValueError("dataset/scenario row counts changed after freeze")
            record = json.loads(dataset_line)
            scenario = json.loads(scenario_line)
            if record.get("record_id") != scenario.get("record_id"):
                raise ValueError(
                    f"dataset/scenario row binding changed at line {line_number}"
                )
            if record.get("split") != "test":
                continue
            split_hasher.update(_canonical_json_bytes(record) + b"\n")
            record_ids.append(str(record["record_id"]))
            examples.append(_example_from_payloads(record, scenario))
    if len(examples) != int(descriptor["sample_count"]):
        raise ValueError("protected v3 test row count changed")
    if split_hasher.hexdigest() != descriptor["split_sha256"]:
        raise ValueError("protected v3 test content hash changed")
    if _hash_string_sequence(record_ids) != descriptor["source_order_sha256"]:
        raise ValueError("protected v3 test source order changed")
    if record_ids != list(descriptor["record_ids_in_source_order"]):
        raise ValueError("protected v3 test identifiers changed")
    return examples


def _probability_metrics(
    labels: Sequence[str],
    probabilities: np.ndarray,
    classes: Sequence[str],
    *,
    bins: int,
) -> dict[str, Any]:
    from sklearn.metrics import log_loss

    indexes = {label: index for index, label in enumerate(classes)}
    label_indexes = np.asarray([indexes[label] for label in labels], dtype=np.int64)
    reliability = _reliability_report(probabilities, label_indexes, bins)
    return {
        "log_loss": float(
            log_loss(
                label_indexes,
                probabilities,
                labels=list(range(len(classes))),
            )
        ),
        "multiclass_brier": _multiclass_brier(probabilities, label_indexes),
        "expected_calibration_error": reliability["expected_calibration_error"],
        "reliability": reliability,
        "calibration_source": "VALIDATION_ONLY",
    }


def _v2_historical_comparison(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    test = payload["test"]
    return {
        "comparison_status": "NOT_DIRECTLY_COMPARABLE",
        "leaderboard_created": False,
        "reason": (
            "NLP v2 and v3 use different synthetic generators, fitted sample sizes, "
            "split construction, and final test sets."
        ),
        "v2_historical_development_result": {
            "model_version": payload["model_version"],
            "source_corpus_rows": 300,
            "fitted_training_rows": payload["n_train"],
            "validation_rows": payload["n_validation"],
            "test_rows": payload["n_test"],
            "test_construction": "original reports_v1 synthetic held-out split",
            "accuracy": test["accuracy"],
            "macro_precision": test["macro_precision"],
            "macro_recall": test["macro_recall"],
            "macro_f1": test["macro_f1"],
            "not_relevant_recall": test["not_relevant_recall"],
        },
        "v3_methodology": {
            "source_corpus_rows": 100_000,
            "fitted_training_rows": 80_000,
            "validation_rows": 10_000,
            "test_rows": 10_000,
            "test_construction": (
                "generator-level held-out templates, lexicons, locations, time range, "
                "parameter combinations, and HIGH noise"
            ),
            "generator_version": EXPECTED_GENERATOR_VERSION,
        },
        "direct_superiority_claim": False,
    }


def finalize_synthetic_v3_evaluation(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    golden_path: Path | str = DEFAULT_GOLDEN_PATH,
    metrics_path: Path | str = DEFAULT_METRICS_PATH,
    receipt_path: Path | str = DEFAULT_FINAL_RECEIPT_PATH,
    error_report_path: Path | str = DEFAULT_ERROR_REPORT_PATH,
    v2_metrics_path: Path | str = DEFAULT_V2_METRICS_PATH,
    config: V3ProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the already-frozen 10,000-row holdout exactly once."""

    artifact_path = local_only_path(artifact_path, description="NLP artifacts")
    development_manifest_path = local_only_path(
        development_manifest_path,
        description="development manifests",
    )
    artifact_manifest_path = local_only_path(
        artifact_manifest_path,
        description="artifact manifests",
    )
    golden_path = local_only_path(golden_path, description="golden reports")
    metrics_path = local_only_path(metrics_path, description="NLP metrics")
    receipt_path = local_only_path(receipt_path, description="final receipts")
    error_report_path = local_only_path(
        error_report_path,
        description="error reports",
    )
    v2_metrics_path = local_only_path(
        v2_metrics_path,
        description="historical NLP metrics",
    )
    if metrics_path.exists():
        raise RuntimeError("v3 final metrics already exist; reevaluation is prohibited")
    if error_report_path.exists():
        raise RuntimeError(
            "v3 final error report already exists; reevaluation is prohibited"
        )
    development_bytes = development_manifest_path.read_bytes()
    development_manifest_sha256 = _sha256_bytes(development_bytes)
    development_manifest = json.loads(development_bytes.decode("utf-8"))
    if development_manifest.get("status") != "FROZEN_FOR_FINAL_TEST":
        raise ValueError("v3 development model is not frozen for final test")
    if development_manifest.get("development_status") != DEVELOPMENT_STATUS:
        raise ValueError("v3 development status changed after freeze")

    artifact = load_nlp_artifact(
        artifact_path,
        manifest_path=artifact_manifest_path,
    )
    artifact_sha256 = file_sha256(artifact_path)
    if artifact_sha256 != development_manifest["artifact"]["sha256"]:
        raise ValueError("v3 artifact changed after development freeze")
    golden = _read_json(golden_path)
    if (
        golden.get("status") != "PASS"
        or golden.get("artifact_sha256") != artifact_sha256
    ):
        raise ValueError("v3 golden regression evidence is absent or stale")
    binding = verify_synthetic_dataset_binding(registry_path=registry_path)
    if str(binding.dataset_path) != development_manifest["dataset"]["dataset_path"]:
        raise ValueError("registered v3 dataset path changed after freeze")

    timestamp = evaluated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("final evaluation timestamp must include a timezone")
    _claim_final_evaluation(
        receipt_path,
        development_manifest_sha256=development_manifest_sha256,
        artifact_sha256=artifact_sha256,
        claimed_at=timestamp,
    )
    try:
        descriptor = development_manifest["final_test"]
        test_examples = _load_protected_test_once(binding, descriptor)
        predictions, probabilities, _ = batch_predict_artifact(
            artifact,
            [example.text for example in test_examples],
        )
        evaluation = _full_evaluation_report(test_examples, predictions)
        errors = deterministic_error_analysis(
            test_examples,
            predictions,
            limit=config.maximum_error_examples_per_category,
        )
        _write_json(error_report_path, errors)
        overall = evaluation["overall"]
        development_gate = {
            "macro_f1": {
                "value": overall["macro_f1"],
                "minimum": config.minimum_development_macro_f1,
                "pass": float(overall["macro_f1"])
                >= config.minimum_development_macro_f1,
            },
            "not_relevant_recall": {
                "value": overall["not_relevant_recall"],
                "minimum": config.minimum_not_relevant_recall,
                "pass": float(overall["not_relevant_recall"])
                >= config.minimum_not_relevant_recall,
            },
        }
        development_gate["passed"] = all(
            item["pass"] for key, item in development_gate.items() if key != "passed"
        )
        metrics = {
            "schema_version": "1.0",
            "evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
            "evaluation_timestamp": timestamp.isoformat(),
            "evaluation_invocation_count": 1,
            "model_version": artifact.model_version,
            "development_status": DEVELOPMENT_STATUS,
            "production_status": PRODUCTION_STATUS,
            "production_validation": PRODUCTION_VALIDATION,
            "field_validation": "NOT_VALIDATED",
            "real_world_validation": "NOT_VALIDATED",
            "dataset_id": EXPECTED_DATASET_ID,
            "dataset_version": EXPECTED_DATASET_VERSION,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "generator_version": EXPECTED_GENERATOR_VERSION,
            "generator_seed": EXPECTED_GENERATOR_SEED,
            "train_split_sha256": artifact.provenance.training_split_sha256,
            "validation_split_sha256": artifact.provenance.validation_split_sha256,
            "final_test_split_sha256": artifact.provenance.final_test_split_sha256,
            "n_train": EXPECTED_COUNTS["train"],
            "n_validation": EXPECTED_COUNTS["validation"],
            "n_test": len(test_examples),
            "configurations_tested": development_manifest["selection"][
                "configuration_count"
            ],
            "selected_configuration": development_manifest["selection"][
                "selected_configuration"
            ],
            "selection_rule": development_manifest["selection"]["selection_rule"],
            "validation": development_manifest["validation_metrics"],
            "calibration": development_manifest["calibration"],
            "test": evaluation,
            "test_probability_metrics": _probability_metrics(
                [example.label for example in test_examples],
                probabilities,
                artifact.classes,
                bins=config.calibration_bins,
            ),
            "development_acceptance_gate": development_gate,
            "v2_comparison": _v2_historical_comparison(v2_metrics_path),
            "artifact_sha256": artifact_sha256,
            "development_manifest_sha256": development_manifest_sha256,
            "frozen_configuration_sha256": development_manifest[
                "frozen_configuration_sha256"
            ],
            "golden_report_sha256": file_sha256(golden_path),
            "error_report_sha256": file_sha256(error_report_path),
            "artifact_integrity": "PASS",
            "test_feature_operation": "TRANSFORM_ONLY",
            "test_fit_calls": 0,
            "test_used_for_retraining": False,
            "configuration_changed_after_test": False,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
            "known_limitations": development_manifest["known_limitations"],
        }
        _write_json(metrics_path, metrics)
        completed_receipt = {
            "schema_version": "1.0",
            "status": "COMPLETED_AND_FROZEN",
            "evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
            "claimed_at": timestamp.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "test_examples_available_to_configuration_selection": False,
            "test_used_for_calibration": False,
            "configuration_changed_after_freeze": False,
            "retrained_after_evaluation": False,
            "development_manifest_sha256": development_manifest_sha256,
            "frozen_configuration_sha256": development_manifest[
                "frozen_configuration_sha256"
            ],
            "artifact_sha256": artifact_sha256,
            "final_test_split_sha256": descriptor["split_sha256"],
            "metrics_sha256": file_sha256(metrics_path),
            "error_report_sha256": file_sha256(error_report_path),
            "golden_report_sha256": file_sha256(golden_path),
            "development_status": DEVELOPMENT_STATUS,
            "production_status": PRODUCTION_STATUS,
            "production_validation": PRODUCTION_VALIDATION,
        }
        _write_json(receipt_path, completed_receipt)
        return metrics
    except Exception as error:
        failed_receipt = {
            "schema_version": "1.0",
            "status": "FAILED_AFTER_CLAIM",
            "evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
            "claimed_at": timestamp.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "error_type": type(error).__name__,
            "error": str(error),
            "development_manifest_sha256": development_manifest_sha256,
            "artifact_sha256": artifact_sha256,
            "development_status": DEVELOPMENT_STATUS,
            "production_status": PRODUCTION_STATUS,
        }
        _write_json(receipt_path, failed_receipt)
        raise


def _paths_from_output_directory(output_directory: Path) -> dict[str, Path]:
    return {
        "artifact_path": output_directory / DEFAULT_ARTIFACT_PATH.name,
        "development_manifest_path": output_directory
        / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "search_path": output_directory / DEFAULT_SEARCH_PATH.name,
        "calibration_path": output_directory / DEFAULT_CALIBRATION_PATH.name,
        "golden_path": output_directory / DEFAULT_GOLDEN_PATH.name,
        "metrics_path": output_directory / DEFAULT_METRICS_PATH.name,
        "receipt_path": output_directory / DEFAULT_FINAL_RECEIPT_PATH.name,
        "error_report_path": output_directory / DEFAULT_ERROR_REPORT_PATH.name,
        "artifact_manifest_path": output_directory / "manifest.json",
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Train and evaluate the Phase 18 synthetic-only NLP v3 model"
    )
    parser.add_argument("action", choices=("freeze", "golden", "finalize"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--output-directory", type=Path, default=ARTIFACT_ROOT)
    args = parser.parse_args(argv)
    paths = _paths_from_output_directory(args.output_directory)
    if args.action == "freeze":
        result = freeze_synthetic_v3_model(
            registry_path=args.registry,
            artifact_path=paths["artifact_path"],
            development_manifest_path=paths["development_manifest_path"],
            search_path=paths["search_path"],
            calibration_path=paths["calibration_path"],
            artifact_manifest_path=paths["artifact_manifest_path"],
        )
    elif args.action == "golden":
        result = run_v3_golden_regression(
            artifact_path=paths["artifact_path"],
            development_manifest_path=paths["development_manifest_path"],
            artifact_manifest_path=paths["artifact_manifest_path"],
            output_path=paths["golden_path"],
        )
    else:
        result = finalize_synthetic_v3_evaluation(
            registry_path=args.registry,
            artifact_path=paths["artifact_path"],
            development_manifest_path=paths["development_manifest_path"],
            artifact_manifest_path=paths["artifact_manifest_path"],
            golden_path=paths["golden_path"],
            metrics_path=paths["metrics_path"],
            receipt_path=paths["receipt_path"],
            error_report_path=paths["error_report_path"],
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEVELOPMENT_STATUS",
    "EXPECTED_DATASET_SHA256",
    "EXPECTED_GENERATOR_SEED",
    "EXPECTED_GENERATOR_VERSION",
    "PRODUCTION_STATUS",
    "SelectionDataset",
    "SyntheticExample",
    "SyntheticV3TrainingBlocked",
    "V3Candidate",
    "V3ProtocolConfig",
    "batch_predict_artifact",
    "controlled_search_space",
    "deterministic_error_analysis",
    "evaluate_validation_calibration",
    "finalize_synthetic_v3_evaluation",
    "fit_selected_configuration",
    "freeze_synthetic_v3_model",
    "prepare_synthetic_selection_data",
    "run_controlled_model_selection",
    "run_v3_golden_regression",
    "select_candidate_result",
    "verify_synthetic_dataset_binding",
]
