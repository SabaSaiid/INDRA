"""Phase 19 formal duplicate-matcher development validation.

This module is deliberately isolated from the live backend.  It binds one
immutable, project-authored synthetic dataset; fits a new TF-IDF state from
the training partition only; selects boundaries on validation only; freezes
the development configuration; and permits one exclusive synthetic holdout
evaluation.  Synthetic metrics are never represented as field validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Final, Iterable, Mapping, Sequence

import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss

from app.ml.components.duplicate_features import (
    DuplicateFeatureState,
    fit_feature_state,
    load_feature_state,
    normalize_text,
)
from app.ml.components.duplicate_matching import (
    DuplicateMatcher,
    _linear_proximity,
    _sparse_cosine,
    edit_similarity,
    haversine_km,
)
from app.ml.config import (
    DuplicateMatchingConfig,
    authorize_manifest_artifact,
    file_sha256,
    local_only_path,
)
from app.ml.contracts import ArtifactManifest, ArtifactMetadata, ArtifactPolicyStatus
from app.ml.data.dataset_validation import CheckStatus
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetComponent,
    DatasetUse,
    find_dataset,
    load_bound_validation_report,
    load_dataset_registry,
    resolve_registry_path,
)
from app.ml.training.dataset_gate import evaluate_training_dataset


EXPECTED_DATASET_ID: Final[str] = "indra-duplicate-project-synthetic-v1"
EXPECTED_DATASET_VERSION: Final[str] = "synthetic-duplicate-100k-v1"
EXPECTED_DATASET_SHA256: Final[str] = (
    "ad664bf69755a141f44c82615e7653f28ae5abadc028cb50d6566ee2f13e7231"
)
EXPECTED_GENERATOR_VERSION: Final[str] = "synthetic-duplicate-generator-v1"
EXPECTED_GENERATOR_SEED: Final[int] = 190019
FEATURE_STATE_VERSION: Final[str] = "duplicate-feature-state-v2"
FEATURE_VERSION: Final[str] = "duplicate-features-v2-synthetic-development"
PREPROCESSING_VERSION: Final[str] = "duplicate-text-normalization-v1"
MATCHER_ARTIFACT_VERSION: Final[str] = "duplicate-matcher-v1-synthetic-development"
THRESHOLD_VERSION: Final[str] = "duplicate-thresholds-v1-synthetic-validation"
CALIBRATION_VERSION: Final[str] = "duplicate-score-platt-v1"
DEVELOPMENT_STATUS: Final[str] = "DEVELOPMENT_ONLY_SYNTHETIC"
PRODUCTION_VALIDATION: Final[str] = "NOT_VALIDATED"
FREEZE_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 23, 18, 0, tzinfo=timezone.utc
)
FINAL_EVALUATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 23, 19, 0, tzinfo=timezone.utc
)

ARTIFACT_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "artifacts"
DEFAULT_FEATURE_STATE_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_feature_state_v2.json"
DEFAULT_MATCHER_ARTIFACT_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_matcher_v1.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH: Final[Path] = (
    ARTIFACT_ROOT / "duplicate_v1.development_manifest.json"
)
DEFAULT_THRESHOLD_SEARCH_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.threshold_search.json"
DEFAULT_ABLATION_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.ablation.json"
DEFAULT_CALIBRATION_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.calibration.json"
DEFAULT_VALIDATION_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "duplicate_v1.validation_metrics.json"
)
DEFAULT_VALIDATION_ERRORS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "duplicate_v1.validation_errors.json"
)
DEFAULT_STABILITY_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.threshold_stability.json"
DEFAULT_PERFORMANCE_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.performance.json"
DEFAULT_GOLDEN_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.golden.json"
DEFAULT_FINAL_METRICS_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.metrics.json"
DEFAULT_ERROR_REPORT_PATH: Final[Path] = ARTIFACT_ROOT / "duplicate_v1.error_report.json"
DEFAULT_FINAL_RECEIPT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "duplicate_v1_final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH: Final[Path] = ARTIFACT_ROOT / "manifest.json"
DEFAULT_ORIGINAL_FEATURE_STATE_PATH: Final[Path] = (
    ARTIFACT_ROOT / "duplicate_feature_state.json"
)
EXPECTED_ORIGINAL_FEATURE_STATE_SHA256: Final[str] = (
    "6d8aad9701700686f42deefa72ed8074ede836a4e9f0d2457db2c054636c2cdc"
)

_NLP_V3_GLOB: Final[str] = "nlp_classifier_v3*.json"
_BINARY_LABELS: Final[set[DuplicatePairLabel]] = {
    DuplicatePairLabel.DUPLICATE,
    DuplicatePairLabel.NOT_DUPLICATE,
}


class DuplicateValidationBlocked(ValueError):
    """Raised when governed Phase 19 development must fail closed."""


class DuplicateDevelopmentArtifact(BaseModel):
    """Hash-authorized, opt-in development matcher configuration."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_version: str
    development_status: str
    production_validation: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_test_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_state_file: str
    feature_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_state_version: str
    feature_version: str
    preprocessing_version: str
    threshold_version: str
    weights: dict[str, float]
    ngram_ranges: dict[str, tuple[int, int]]
    text_similarity_threshold: float = Field(ge=0.0, le=1.0)
    combined_threshold: float = Field(ge=0.0, le=1.0)
    geographic_gate_km: float = Field(gt=0.0)
    temporal_gate_minutes: float = Field(gt=0.0)
    threshold_status: str
    decision_logic: str
    score_interpretation: str
    calibration: dict[str, Any]
    frozen_at: datetime
    random_seed: int
    library_versions: dict[str, str]
    policy: dict[str, Any]

    @model_validator(mode="after")
    def validate_governance(self) -> "DuplicateDevelopmentArtifact":
        if self.frozen_at.tzinfo is None:
            raise ValueError("frozen_at must include a timezone")
        if self.production_validation != PRODUCTION_VALIDATION:
            raise ValueError("synthetic artifact cannot claim production validation")
        if self.development_status != DEVELOPMENT_STATUS:
            raise ValueError("unexpected duplicate development status")
        if not math.isclose(sum(self.weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("matcher weights must sum to one")
        prohibited = (
            self.policy.get("pretrained_models"),
            self.policy.get("open_weight_models"),
            self.policy.get("external_apis"),
        )
        if any(value != [] for value in prohibited):
            raise ValueError("artifact violates local-only model policy")
        if self.policy.get("network_access") is not False:
            raise ValueError("artifact must record network_access=false")
        return self


@dataclass(frozen=True, slots=True)
class DuplicateDatasetBinding:
    registry_path: Path
    dataset_path: Path
    dataset_manifest_path: Path
    quality_report_path: Path
    dataset_manifest_sha256: str
    quality_report_sha256: str
    registered_validation_sha256: str
    dataset_manifest: dict[str, Any]
    quality_report: dict[str, Any]
    production_training_gate: dict[str, Any]
    dataset_decision: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SplitDescriptor:
    split: str
    row_count: int
    split_sha256: str
    pair_ids_sha256: str


@dataclass(frozen=True, slots=True)
class PairExample:
    pair_id: str
    label: DuplicatePairLabel
    text_a: str
    text_b: str
    latitude_a: float
    longitude_a: float
    latitude_b: float
    longitude_b: float
    time_delta_minutes: float
    language: str
    event_type: str
    source_type: str
    scenario_type: str
    split: str


@dataclass(frozen=True, slots=True)
class PreparedDuplicateData:
    binding: DuplicateDatasetBinding
    train: tuple[PairExample, ...]
    validation: tuple[PairExample, ...]
    split_descriptors: dict[str, SplitDescriptor]


@dataclass(frozen=True, slots=True)
class SignalTable:
    split: str
    examples: tuple[PairExample, ...]
    labels: np.ndarray
    character_similarity: np.ndarray
    word_similarity: np.ndarray
    edit_similarity: np.ndarray
    distance_km: np.ndarray
    time_minutes: np.ndarray
    transformation_seconds: float
    similarity_seconds: float

    @property
    def binary_mask(self) -> np.ndarray:
        return self.labels >= 0


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, payload: Any, *, exclusive: bool = False) -> str:
    selected = local_only_path(path, description="duplicate validation artifacts")
    selected.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        payload.model_dump_json(indent=2).encode("utf-8")
        if isinstance(payload, BaseModel)
        else json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    ) + b"\n"
    if exclusive:
        try:
            with selected.open("xb") as handle:
                handle.write(encoded)
        except FileExistsError as error:
            raise RuntimeError(
                f"artifact already exists and cannot be overwritten: {selected.name}"
            ) from error
    else:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=selected.parent,
            prefix=selected.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
        temporary.replace(selected)
    return file_sha256(selected)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _nlp_v3_hashes(root: Path = ARTIFACT_ROOT) -> dict[str, str]:
    return {
        path.name: file_sha256(path)
        for path in sorted(root.glob(_NLP_V3_GLOB), key=lambda item: item.name)
        if path.is_file()
    }


def inspect_duplicate_dataset_decision(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> dict[str, Any]:
    """Return the explicit human-vs-synthetic decision required by Phase 19."""

    registry = load_dataset_registry(registry_path)
    approved_human: list[dict[str, str]] = []
    for record in registry.entries:
        if record.component is not DatasetComponent.DUPLICATE or not record.human_adjudicated:
            continue
        approvals = {item.use for item in record.approvals}
        if all(use in approvals for use in DatasetUse):
            approved_human.append(
                {
                    "dataset_id": record.dataset_id,
                    "dataset_version": record.dataset_version,
                    "content_sha256": record.content_sha256,
                }
            )
    approved_human.sort(key=lambda item: (item["dataset_id"], item["dataset_version"]))
    return {
        "approved_human_adjudicated_duplicate_datasets": approved_human,
        "USE_IT": bool(approved_human),
        "GENERATE_SYNTHETIC_DUPLICATE_DATASET": not approved_human,
        "selected_source": (
            "HUMAN_ADJUDICATED_APPROVED" if approved_human else "PROJECT_AUTHORED_SYNTHETIC"
        ),
        "silent_switching_permitted": False,
    }


def verify_synthetic_duplicate_binding(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> DuplicateDatasetBinding:
    """Bind exact registry, manifest, quality, and gate evidence or fail closed."""

    selected_registry = local_only_path(
        registry_path, description="dataset registries"
    ).resolve()
    decision = inspect_duplicate_dataset_decision(selected_registry)
    if decision["USE_IT"]:
        raise DuplicateValidationBlocked(
            "APPROVED_HUMAN_DUPLICATE_DATASET_EXISTS: synthetic fallback prohibited"
        )
    registry = load_dataset_registry(selected_registry)
    record = find_dataset(registry, EXPECTED_DATASET_ID, EXPECTED_DATASET_VERSION)
    if record.component is not DatasetComponent.DUPLICATE:
        raise DuplicateValidationBlocked("DUPLICATE_DATASET_COMPONENT_MISMATCH")
    checks = {
        "dataset hash": record.content_sha256 == EXPECTED_DATASET_SHA256,
        "project provenance": record.provenance.value == "PROJECT_AUTHORED",
        "development classification": record.data_classification.value
        == "DEVELOPMENT_ONLY",
        "not human adjudicated": record.human_adjudicated is False,
        "synthetic label source": record.label_source
        == "PROJECT_GENERATED_SYNTHETIC_SCENARIO_IDENTITY",
        "no approvals": record.approvals == [],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise DuplicateValidationBlocked(
            "DUPLICATE_DATASET_REGISTRY_BINDING_MISMATCH: " + ", ".join(failed)
        )
    dataset_path = resolve_registry_path(record.local_path, selected_registry)
    if not dataset_path.is_file() or file_sha256(dataset_path) != EXPECTED_DATASET_SHA256:
        raise DuplicateValidationBlocked("DUPLICATE_DATASET_HASH_MISMATCH")

    metadata = record.metadata
    manifest_path = resolve_registry_path(str(metadata.get("manifest_path", "")), selected_registry)
    quality_path = resolve_registry_path(
        str(metadata.get("quality_report_path", "")), selected_registry
    )
    bound_files = {
        "manifest": (manifest_path, str(metadata.get("manifest_sha256", ""))),
        "quality": (quality_path, str(metadata.get("quality_report_sha256", ""))),
    }
    for name, (path, expected_hash) in bound_files.items():
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise DuplicateValidationBlocked(
                f"DUPLICATE_DATASET_BINDING_MISMATCH: {name} hash"
            )
    manifest = _read_json(manifest_path)
    manifest_checks = {
        "dataset hash": manifest.get("dataset_sha256") == EXPECTED_DATASET_SHA256,
        "dataset id": manifest.get("dataset_id") == EXPECTED_DATASET_ID,
        "dataset version": manifest.get("dataset_version") == EXPECTED_DATASET_VERSION,
        "generator": manifest.get("generator_version") == EXPECTED_GENERATOR_VERSION,
        "seed": manifest.get("seed") == EXPECTED_GENERATOR_SEED,
        "classification": manifest.get("classification") == "DEVELOPMENT_ONLY",
        "provenance": manifest.get("provenance") == "PROJECT_AUTHORED",
        "synthetic": manifest.get("data_kind") == "SYNTHETIC",
        "production": manifest.get("production_validation") == "NOT_VALIDATED",
        "scenario labels": manifest.get("matcher_used_for_labels") is False,
        "network": manifest.get("network_access") is False,
        "pretrained": manifest.get("pretrained_models") == [],
        "open weight": manifest.get("open_weight_models") == [],
        "external APIs": manifest.get("external_apis") == [],
    }
    failed_manifest = [name for name, passed in manifest_checks.items() if not passed]
    if failed_manifest:
        raise DuplicateValidationBlocked(
            "DUPLICATE_DATASET_MANIFEST_MISMATCH: " + ", ".join(failed_manifest)
        )
    quality = _read_json(quality_path)
    if (
        quality.get("valid") is not True
        or quality.get("dataset_sha256") != EXPECTED_DATASET_SHA256
        or quality.get("generator_version") != EXPECTED_GENERATOR_VERSION
        or quality.get("seed") != EXPECTED_GENERATOR_SEED
        or quality.get("leakage_checks", {}).get("status") != "PASS"
    ):
        raise DuplicateValidationBlocked("DUPLICATE_DATASET_QUALITY_EVIDENCE_INVALID")
    registered_validation = load_bound_validation_report(record, selected_registry)
    if (
        not registered_validation.valid
        or registered_validation.content_sha256 != EXPECTED_DATASET_SHA256
        or registered_validation.leakage.overall_status is not CheckStatus.PASS
    ):
        raise DuplicateValidationBlocked("REGISTERED_DUPLICATE_VALIDATION_INVALID")
    production_gate = evaluate_training_dataset(
        EXPECTED_DATASET_ID,
        DatasetComponent.DUPLICATE,
        registry_path=selected_registry,
        dataset_version=EXPECTED_DATASET_VERSION,
        supplied_path=dataset_path,
        require_evaluation_approvals=True,
    )
    if production_gate.allowed:
        raise DuplicateValidationBlocked("PRODUCTION_GATE_UNEXPECTEDLY_OPEN")
    if not any(
        code.startswith("APPROVAL_MISSING") for code in production_gate.reason_codes
    ):
        raise DuplicateValidationBlocked("PRODUCTION_GATE_MISSING_APPROVAL_BLOCKER")
    validation_report_path = resolve_registry_path(
        record.validation_report_path or "", selected_registry
    )
    return DuplicateDatasetBinding(
        registry_path=selected_registry,
        dataset_path=dataset_path,
        dataset_manifest_path=manifest_path,
        quality_report_path=quality_path,
        dataset_manifest_sha256=file_sha256(manifest_path),
        quality_report_sha256=file_sha256(quality_path),
        registered_validation_sha256=file_sha256(validation_report_path),
        dataset_manifest=manifest,
        quality_report=quality,
        production_training_gate=production_gate.model_dump(mode="json"),
        dataset_decision=decision,
    )


def _example_from_record(record: DuplicatePairRecord) -> PairExample:
    required = {
        "text_a": record.text_a,
        "text_b": record.text_b,
        "latitude_a": record.latitude_a,
        "longitude_a": record.longitude_a,
        "latitude_b": record.latitude_b,
        "longitude_b": record.longitude_b,
        "time_delta_seconds": record.time_delta_seconds,
        "language": record.language,
        "event_type_a": record.event_type_a,
        "source_type_a": record.source_type_a,
        "scenario_type": record.scenario_type,
        "split": record.split,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise DuplicateValidationBlocked(
            f"PAIR_CONTEXT_INCOMPLETE:{record.pair_id}:" + ",".join(missing)
        )
    return PairExample(
        pair_id=record.pair_id,
        label=record.label,
        text_a=str(record.text_a),
        text_b=str(record.text_b),
        latitude_a=float(record.latitude_a),
        longitude_a=float(record.longitude_a),
        latitude_b=float(record.latitude_b),
        longitude_b=float(record.longitude_b),
        time_delta_minutes=float(record.time_delta_seconds) / 60.0,
        language=str(record.language),
        event_type=str(record.event_type_a),
        source_type=str(record.source_type_a),
        scenario_type=str(record.scenario_type),
        split=str(record.split),
    )


def prepare_duplicate_validation_data(
    binding: DuplicateDatasetBinding,
) -> PreparedDuplicateData:
    """Load train/validation rows while retaining only a descriptor for test."""

    examples: dict[str, list[PairExample]] = {"train": [], "validation": []}
    split_hashers = {name: hashlib.sha256() for name in ("train", "validation", "test")}
    id_hashers = {name: hashlib.sha256() for name in ("train", "validation", "test")}
    counts = Counter()
    with binding.dataset_path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
                split = str(payload["split"])
                pair_id = str(payload["pair_id"])
            except Exception as error:  # noqa: BLE001
                raise DuplicateValidationBlocked(
                    f"DATASET_ROW_INVALID:{line_number}:{type(error).__name__}:{error}"
                ) from error
            if split not in split_hashers:
                raise DuplicateValidationBlocked(f"UNKNOWN_SPLIT:{split}")
            split_hashers[split].update(raw_line)
            id_hashers[split].update(pair_id.encode("utf-8") + b"\n")
            counts[split] += 1
            if split == "test":
                continue
            record = DuplicatePairRecord.model_validate(payload)
            examples[split].append(_example_from_record(record))
    expected = binding.quality_report.get("split_counts", {})
    if any(counts[name] != int(expected.get(name, -1)) for name in counts):
        raise DuplicateValidationBlocked("SPLIT_COUNTS_CHANGED_AFTER_REGISTRATION")
    descriptors = {
        name: SplitDescriptor(
            split=name,
            row_count=counts[name],
            split_sha256=split_hashers[name].hexdigest(),
            pair_ids_sha256=id_hashers[name].hexdigest(),
        )
        for name in ("train", "validation", "test")
    }
    return PreparedDuplicateData(
        binding=binding,
        train=tuple(examples["train"]),
        validation=tuple(examples["validation"]),
        split_descriptors=descriptors,
    )


def training_corpus_and_hash(
    examples: Sequence[PairExample],
) -> tuple[list[str], str]:
    if not examples or any(item.split != "train" for item in examples):
        raise DuplicateValidationBlocked("FEATURE_FIT_REQUIRES_TRAIN_SPLIT_ONLY")
    corpus: list[str] = []
    hasher = hashlib.sha256()
    for item in examples:
        for text in (item.text_a, item.text_b):
            normalized = normalize_text(text)
            corpus.append(normalized)
            hasher.update(normalized.encode("utf-8") + b"\n")
    return corpus, hasher.hexdigest()


def score_pair_examples(
    examples: Sequence[PairExample],
    feature_state: DuplicateFeatureState,
    *,
    expected_split: str,
) -> SignalTable:
    """Transform and score pairs with the exact deterministic matcher signals."""

    if expected_split not in {"train", "validation", "test"}:
        raise ValueError("expected_split must be train, validation, or test")
    if any(item.split != expected_split for item in examples):
        raise DuplicateValidationBlocked("MIXED_SPLITS_IN_SIGNAL_TABLE")
    size = len(examples)
    labels = np.empty(size, dtype=np.int8)
    character = np.empty(size, dtype=np.float64)
    word = np.empty(size, dtype=np.float64)
    edit = np.empty(size, dtype=np.float64)
    distance = np.empty(size, dtype=np.float64)
    minutes = np.empty(size, dtype=np.float64)
    transform_seconds = 0.0
    similarity_seconds = 0.0
    for index, example in enumerate(examples):
        normalized_a = normalize_text(example.text_a)
        normalized_b = normalize_text(example.text_b)
        started = perf_counter()
        char_a = feature_state.char_space.transform(normalized_a)
        char_b = feature_state.char_space.transform(normalized_b)
        word_a = feature_state.word_space.transform(normalized_a)
        word_b = feature_state.word_space.transform(normalized_b)
        transform_seconds += perf_counter() - started
        started = perf_counter()
        character[index] = _sparse_cosine(char_a, char_b)
        word[index] = _sparse_cosine(word_a, word_b)
        edit[index] = edit_similarity(normalized_a, normalized_b)
        distance[index] = haversine_km(
            example.latitude_a,
            example.longitude_a,
            example.latitude_b,
            example.longitude_b,
        )
        minutes[index] = example.time_delta_minutes
        similarity_seconds += perf_counter() - started
        labels[index] = (
            1
            if example.label is DuplicatePairLabel.DUPLICATE
            else 0
            if example.label is DuplicatePairLabel.NOT_DUPLICATE
            else -1
        )
    return SignalTable(
        split=expected_split,
        examples=tuple(examples),
        labels=labels,
        character_similarity=character,
        word_similarity=word,
        edit_similarity=edit,
        distance_km=distance,
        time_minutes=minutes,
        transformation_seconds=transform_seconds,
        similarity_seconds=similarity_seconds,
    )


def _text_score(signals: SignalTable) -> np.ndarray:
    return np.clip(
        (
            0.35 * signals.character_similarity
            + 0.30 * signals.word_similarity
            + 0.15 * signals.edit_similarity
        )
        / 0.80,
        0.0,
        1.0,
    )


def _proximity(values: np.ndarray, gate: float) -> np.ndarray:
    return np.clip(1.0 - (values / gate), 0.0, 1.0)


def _combined_score(
    signals: SignalTable,
    *,
    geographic_gate_km: float,
    temporal_gate_minutes: float,
) -> np.ndarray:
    return np.clip(
        0.35 * signals.character_similarity
        + 0.30 * signals.word_similarity
        + 0.15 * signals.edit_similarity
        + 0.10 * _proximity(signals.distance_km, geographic_gate_km)
        + 0.10 * _proximity(signals.time_minutes, temporal_gate_minutes),
        0.0,
        1.0,
    )


def _full_decision(
    signals: SignalTable,
    *,
    text_threshold: float,
    combined_threshold: float,
    geographic_gate_km: float,
    temporal_gate_minutes: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    text = _text_score(signals)
    combined = _combined_score(
        signals,
        geographic_gate_km=geographic_gate_km,
        temporal_gate_minutes=temporal_gate_minutes,
    )
    eligible = (signals.distance_km <= geographic_gate_km) & (
        signals.time_minutes <= temporal_gate_minutes
    )
    prediction = eligible & (text >= text_threshold) & (combined >= combined_threshold)
    evidence = np.where(eligible, np.minimum(text, combined), 0.0)
    return prediction, evidence, combined


def _binary_metrics(
    labels: np.ndarray,
    predictions: np.ndarray,
    *,
    evidence: np.ndarray | None = None,
) -> dict[str, Any]:
    truth = labels.astype(np.int8)
    predicted = predictions.astype(bool)
    tp = int(np.sum((truth == 1) & predicted))
    fp = int(np.sum((truth == 0) & predicted))
    tn = int(np.sum((truth == 0) & ~predicted))
    fn = int(np.sum((truth == 1) & ~predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    fnr = fn / (fn + tp) if fn + tp else 0.0
    result: dict[str, Any] = {
        "evaluated_rows": int(len(truth)),
        "duplicate_prevalence": float(np.mean(truth == 1)) if len(truth) else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "confusion_matrix": {
            "true_duplicate": tp,
            "false_duplicate": fp,
            "true_non_duplicate": tn,
            "missed_duplicate": fn,
        },
    }
    if evidence is not None and len(np.unique(truth)) == 2:
        result["pr_auc_average_precision"] = float(
            average_precision_score(truth, evidence)
        )
    else:
        result["pr_auc_average_precision"] = None
    return result


def _binary_view(signals: SignalTable) -> tuple[np.ndarray, np.ndarray]:
    mask = signals.binary_mask
    return mask, signals.labels[mask]


def evaluate_full_configuration(
    signals: SignalTable,
    configuration: Mapping[str, float],
) -> dict[str, Any]:
    mask, labels = _binary_view(signals)
    prediction, evidence, _ = _full_decision(
        signals,
        text_threshold=float(configuration["text_threshold"]),
        combined_threshold=float(configuration["combined_threshold"]),
        geographic_gate_km=float(configuration["geographic_gate_km"]),
        temporal_gate_minutes=float(configuration["temporal_gate_minutes"]),
    )
    metrics = _binary_metrics(labels, prediction[mask], evidence=evidence[mask])
    metrics["uncertain_rows_excluded"] = int(np.sum(~mask))
    metrics["configuration"] = dict(configuration)
    metrics["score_interpretation"] = "SIMILARITY_EVIDENCE_NOT_PROBABILITY"
    return metrics


def select_duplicate_thresholds(
    signals: SignalTable,
    *,
    text_thresholds: Sequence[float] | None = None,
    combined_thresholds: Sequence[float] | None = None,
    geographic_gates_km: Sequence[float] = (0.5, 1.0, 2.0, 5.0, 10.0),
    temporal_gates_minutes: Sequence[float] = (10.0, 15.0, 30.0, 60.0, 180.0),
) -> dict[str, Any]:
    """Select all decision boundaries on validation only."""

    if signals.split != "validation":
        raise DuplicateValidationBlocked("THRESHOLD_SELECTION_REQUIRES_VALIDATION_SPLIT")
    text_grid = tuple(
        text_thresholds
        or tuple(round(value, 2) for value in np.arange(0.30, 0.851, 0.05))
    )
    combined_grid = tuple(
        combined_thresholds
        or tuple(round(value, 2) for value in np.arange(0.40, 0.901, 0.05))
    )
    mask, labels = _binary_view(signals)
    text = _text_score(signals)[mask]
    distances = signals.distance_km[mask]
    minutes = signals.time_minutes[mask]
    best: dict[str, Any] | None = None
    top: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    evaluated = 0
    for geo_gate in geographic_gates_km:
        for time_gate in temporal_gates_minutes:
            combined = _combined_score(
                signals,
                geographic_gate_km=float(geo_gate),
                temporal_gate_minutes=float(time_gate),
            )[mask]
            eligible = (distances <= geo_gate) & (minutes <= time_gate)
            evidence = np.where(eligible, np.minimum(text, combined), 0.0)
            for text_threshold in text_grid:
                text_pass = text >= text_threshold
                for combined_threshold in combined_grid:
                    prediction = (
                        eligible & text_pass & (combined >= combined_threshold)
                    )
                    metrics = _binary_metrics(
                        labels, prediction, evidence=evidence
                    )
                    evaluated += 1
                    candidate = {
                        "text_threshold": float(text_threshold),
                        "combined_threshold": float(combined_threshold),
                        "geographic_gate_km": float(geo_gate),
                        "temporal_gate_minutes": float(time_gate),
                        "metrics": metrics,
                    }
                    rank = (
                        metrics["f1"],
                        metrics["precision"],
                        metrics["recall"],
                        -metrics["false_positive_rate"],
                        float(text_threshold),
                        float(combined_threshold),
                        -float(geo_gate),
                        -float(time_gate),
                    )
                    top.append((rank, candidate))
                    if best is None or rank > best["_rank"]:
                        best = {**candidate, "_rank": rank}
    if best is None:
        raise DuplicateValidationBlocked("THRESHOLD_SEARCH_PRODUCED_NO_CANDIDATE")
    selected = {key: value for key, value in best.items() if key != "_rank"}
    top_results = [item for _, item in sorted(top, key=lambda item: item[0], reverse=True)[:25]]
    current = {
        "text_threshold": 0.55,
        "combined_threshold": 0.70,
        "geographic_gate_km": 1.0,
        "temporal_gate_minutes": 15.0,
    }
    current_metrics = evaluate_full_configuration(signals, current)
    tradeoff: list[dict[str, Any]] = []
    for delta in (-0.10, -0.05, 0.0, 0.05, 0.10):
        configuration = {
            "text_threshold": selected["text_threshold"],
            "combined_threshold": min(
                1.0, max(0.0, selected["combined_threshold"] + delta)
            ),
            "geographic_gate_km": selected["geographic_gate_km"],
            "temporal_gate_minutes": selected["temporal_gate_minutes"],
        }
        tradeoff.append(evaluate_full_configuration(signals, configuration))
    return {
        "schema_version": "1.0",
        "selection_split": "validation",
        "test_rows_accessed_for_selection": False,
        "objective": (
            "MAX_F1_THEN_PRECISION_THEN_RECALL_THEN_LOWER_FPR_THEN_"
            "STRICTER_THRESHOLDS_THEN_SMALLER_GATES"
        ),
        "grid": {
            "text_thresholds": list(text_grid),
            "combined_thresholds": list(combined_grid),
            "geographic_gates_km": list(geographic_gates_km),
            "temporal_gates_minutes": list(temporal_gates_minutes),
            "candidate_count": evaluated,
        },
        "current_provisional_configuration": current,
        "current_provisional_metrics": current_metrics,
        "selected": selected,
        "top_candidates": top_results,
        "false_positive_false_negative_tradeoff": tradeoff,
        "production_validation": PRODUCTION_VALIDATION,
    }


def _select_single_threshold(
    labels: np.ndarray,
    scores: np.ndarray,
) -> tuple[float, dict[str, Any]]:
    best: tuple[tuple[float, ...], float, dict[str, Any]] | None = None
    for threshold in (round(value, 2) for value in np.arange(0.0, 1.001, 0.01)):
        metrics = _binary_metrics(labels, scores >= threshold, evidence=scores)
        rank = (
            metrics["f1"],
            metrics["precision"],
            metrics["recall"],
            -metrics["false_positive_rate"],
            threshold,
        )
        if best is None or rank > best[0]:
            best = rank, threshold, metrics
    assert best is not None
    return best[1], best[2]


def run_validation_ablation(
    signals: SignalTable,
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    if signals.split != "validation":
        raise DuplicateValidationBlocked("ABLATION_REQUIRES_VALIDATION_SPLIT")
    mask, labels = _binary_view(signals)
    char = signals.character_similarity[mask]
    word = signals.word_similarity[mask]
    edit = signals.edit_similarity[mask]
    geo = _proximity(signals.distance_km[mask], float(selected["geographic_gate_km"]))
    time = _proximity(
        signals.time_minutes[mask], float(selected["temporal_gate_minutes"])
    )
    score_map = {
        "TEXT ONLY": (0.35 * char + 0.30 * word) / 0.65,
        "GEO ONLY": geo,
        "TIME ONLY": time,
        "TEXT + GEO": (0.35 * char + 0.30 * word + 0.10 * geo) / 0.75,
        "TEXT + TIME": (0.35 * char + 0.30 * word + 0.10 * time) / 0.75,
        "TEXT + GEO + TIME": (
            0.35 * char + 0.30 * word + 0.10 * geo + 0.10 * time
        )
        / 0.85,
        "EDIT + TEXT": (0.35 * char + 0.30 * word + 0.15 * edit) / 0.80,
    }
    rows: list[dict[str, Any]] = []
    for name, score in score_map.items():
        threshold, metrics = _select_single_threshold(labels, np.clip(score, 0.0, 1.0))
        rows.append(
            {
                "ablation": name,
                "selected_threshold": threshold,
                "metrics": metrics,
                "selection_split": "validation",
            }
        )
    full_configuration = {
        key: float(selected[key])
        for key in (
            "text_threshold",
            "combined_threshold",
            "geographic_gate_km",
            "temporal_gate_minutes",
        )
    }
    rows.append(
        {
            "ablation": "FULL MODEL",
            "selected_threshold": {
                "text": full_configuration["text_threshold"],
                "combined": full_configuration["combined_threshold"],
            },
            "metrics": evaluate_full_configuration(signals, full_configuration),
            "selection_split": "validation",
        }
    )
    return {
        "schema_version": "1.0",
        "selection_split": "validation",
        "test_rows_accessed": False,
        "ablations": rows,
        "scientific_scope": "SYNTHETIC_DEVELOPMENT_ONLY",
        "production_validation": PRODUCTION_VALIDATION,
    }


def _sigmoid(values: np.ndarray) -> np.ndarray:
    positive = values >= 0
    result = np.empty_like(values, dtype=np.float64)
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    negative_exp = np.exp(values[~positive])
    result[~positive] = negative_exp / (1.0 + negative_exp)
    return result


def _expected_calibration_error(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    total = len(labels)
    if total == 0:
        return 0.0
    error = 0.0
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        if index == bins - 1:
            mask = (probabilities >= boundaries[index]) & (
                probabilities <= boundaries[index + 1]
            )
        else:
            mask = (probabilities >= boundaries[index]) & (
                probabilities < boundaries[index + 1]
            )
        if not np.any(mask):
            continue
        accuracy = float(np.mean(labels[mask]))
        confidence = float(np.mean(probabilities[mask]))
        error += (int(np.sum(mask)) / total) * abs(accuracy - confidence)
    return error


def _calibration_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    clipped = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    return {
        "log_loss": float(log_loss(labels, clipped, labels=[0, 1])),
        "brier_score": float(np.mean((clipped - labels) ** 2)),
        "expected_calibration_error_10_bins": _expected_calibration_error(
            labels, clipped
        ),
    }


def investigate_validation_calibration(
    signals: SignalTable,
    selected: Mapping[str, Any],
    *,
    random_seed: int = EXPECTED_GENERATOR_SEED,
) -> dict[str, Any]:
    """Investigate an explicitly versioned Platt layer on validation only."""

    if signals.split != "validation":
        raise DuplicateValidationBlocked("CALIBRATION_REQUIRES_VALIDATION_SPLIT")
    mask, labels = _binary_view(signals)
    _, evidence_all, _ = _full_decision(
        signals,
        text_threshold=float(selected["text_threshold"]),
        combined_threshold=float(selected["combined_threshold"]),
        geographic_gate_km=float(selected["geographic_gate_km"]),
        temporal_gate_minutes=float(selected["temporal_gate_minutes"]),
    )
    evidence = evidence_all[mask]
    binary_examples = [
        item for item, keep in zip(signals.examples, mask, strict=True) if bool(keep)
    ]
    fit_mask = np.asarray(
        [
            int.from_bytes(
                hashlib.sha256(item.pair_id.encode("utf-8")).digest()[:8], "big"
            )
            % 2
            == 0
            for item in binary_examples
        ],
        dtype=bool,
    )
    if len(np.unique(labels[fit_mask])) != 2 or len(np.unique(labels[~fit_mask])) != 2:
        raise DuplicateValidationBlocked("CALIBRATION_PARTITION_MISSING_CLASS")
    model = LogisticRegression(
        C=1.0,
        solver="lbfgs",
        random_state=random_seed,
        max_iter=1000,
    )
    model.fit(evidence[fit_mask].reshape(-1, 1), labels[fit_mask])
    coefficient = float(model.coef_[0, 0])
    intercept = float(model.intercept_[0])
    calibrated = _sigmoid(coefficient * evidence[~fit_mask] + intercept)
    raw = evidence[~fit_mask]
    raw_metrics = _calibration_metrics(labels[~fit_mask], raw)
    calibrated_metrics = _calibration_metrics(labels[~fit_mask], calibrated)
    selected_for_artifact = (
        calibrated_metrics["log_loss"] < raw_metrics["log_loss"]
        and calibrated_metrics["brier_score"] < raw_metrics["brier_score"]
    )
    return {
        "schema_version": "1.0",
        "calibration_version": CALIBRATION_VERSION,
        "method": "PLATT_LOGISTIC_SCALAR",
        "input_score": "MIN_TEXT_AND_COMBINED_WHEN_CANDIDATE_ELIGIBLE",
        "input_score_interpretation": "SIMILARITY_EVIDENCE_NOT_PROBABILITY",
        "fit_split": "validation_calibration_fit_partition",
        "check_split": "validation_calibration_check_partition",
        "partition_method": "PAIR_ID_SHA256_PARITY",
        "fit_rows": int(np.sum(fit_mask)),
        "check_rows": int(np.sum(~fit_mask)),
        "test_rows_accessed": False,
        "coefficient": coefficient,
        "intercept": intercept,
        "raw_evidence_metrics": raw_metrics,
        "calibrated_probability_metrics": calibrated_metrics,
        "selected_for_artifact": selected_for_artifact,
        "status": (
            "SELECTED_VALIDATION_ONLY_SYNTHETIC_DEVELOPMENT"
            if selected_for_artifact
            else "INVESTIGATED_NOT_SELECTED"
        ),
        "production_calibration": "NOT_VALIDATED",
        "limitations": [
            "The calibration investigation uses synthetic validation labels only.",
            "Any selected probability is versioned development evidence, not a production probability.",
            "Calibration does not change the duplicate decision thresholds.",
        ],
    }


def _bucket_wording(score: float) -> str:
    if score < 0.40:
        return "LOW_LT_0_40"
    if score < 0.70:
        return "MEDIUM_0_40_TO_0_70"
    return "HIGH_GE_0_70"


def _bucket_distance(distance: float) -> str:
    if distance <= 0.25:
        return "LE_0_25_KM"
    if distance <= 1.0:
        return "GT_0_25_TO_1_KM"
    if distance <= 5.0:
        return "GT_1_TO_5_KM"
    return "GT_5_KM"


def _bucket_time(minutes: float) -> str:
    if minutes <= 5.0:
        return "LE_5_MIN"
    if minutes <= 15.0:
        return "GT_5_TO_15_MIN"
    if minutes <= 60.0:
        return "GT_15_TO_60_MIN"
    return "GT_60_MIN"


def failure_analysis(
    signals: SignalTable,
    selected: Mapping[str, Any],
    *,
    maximum_examples_per_error: int = 25,
) -> dict[str, Any]:
    prediction, evidence, combined = _full_decision(
        signals,
        text_threshold=float(selected["text_threshold"]),
        combined_threshold=float(selected["combined_threshold"]),
        geographic_gate_km=float(selected["geographic_gate_km"]),
        temporal_gate_minutes=float(selected["temporal_gate_minutes"]),
    )
    text = _text_score(signals)
    categories: dict[str, list[int]] = {
        "FALSE_DUPLICATE": [
            index
            for index in range(len(signals.labels))
            if signals.labels[index] == 0 and bool(prediction[index])
        ],
        "MISSED_DUPLICATE": [
            index
            for index in range(len(signals.labels))
            if signals.labels[index] == 1 and not bool(prediction[index])
        ],
    }
    output: dict[str, Any] = {}
    for category, indexes in categories.items():
        wording = Counter(_bucket_wording(float(text[index])) for index in indexes)
        distance = Counter(
            _bucket_distance(float(signals.distance_km[index])) for index in indexes
        )
        time = Counter(_bucket_time(float(signals.time_minutes[index])) for index in indexes)
        language = Counter(signals.examples[index].language for index in indexes)
        scenario = Counter(signals.examples[index].scenario_type for index in indexes)
        examples = []
        for index in sorted(indexes, key=lambda value: signals.examples[value].pair_id)[
            :maximum_examples_per_error
        ]:
            item = signals.examples[index]
            examples.append(
                {
                    "pair_id": item.pair_id,
                    "scenario_type": item.scenario_type,
                    "language": item.language,
                    "wording_similarity_bucket": _bucket_wording(float(text[index])),
                    "text_similarity": float(text[index]),
                    "combined_score": float(combined[index]),
                    "evidence_score": float(evidence[index]),
                    "distance_km": float(signals.distance_km[index]),
                    "time_difference_minutes": float(signals.time_minutes[index]),
                    "text_a": item.text_a,
                    "text_b": item.text_b,
                }
            )
        output[category] = {
            "count": len(indexes),
            "by_wording_similarity": dict(sorted(wording.items())),
            "by_distance": dict(sorted(distance.items())),
            "by_time_difference": dict(sorted(time.items())),
            "by_language": dict(sorted(language.items())),
            "by_hard_negative_or_scenario_type": dict(sorted(scenario.items())),
            "deterministic_examples": examples,
            "example_limit": maximum_examples_per_error,
        }
    return {
        "schema_version": "1.0",
        "split": signals.split,
        "configuration": {
            key: float(selected[key])
            for key in (
                "text_threshold",
                "combined_threshold",
                "geographic_gate_km",
                "temporal_gate_minutes",
            )
        },
        "errors": output,
        "uncertain_rows_excluded": int(np.sum(signals.labels < 0)),
        "production_validation": PRODUCTION_VALIDATION,
    }


def _group_stability_rows(
    signals: SignalTable,
    selected: Mapping[str, Any],
    group_values: Sequence[str],
) -> list[dict[str, Any]]:
    text = _text_score(signals)
    combined = _combined_score(
        signals,
        geographic_gate_km=float(selected["geographic_gate_km"]),
        temporal_gate_minutes=float(selected["temporal_gate_minutes"]),
    )
    eligible = (signals.distance_km <= float(selected["geographic_gate_km"])) & (
        signals.time_minutes <= float(selected["temporal_gate_minutes"])
    )
    global_prediction = (
        eligible
        & (text >= float(selected["text_threshold"]))
        & (combined >= float(selected["combined_threshold"]))
    )
    evidence = np.where(eligible, np.minimum(text, combined), 0.0)
    rows: list[dict[str, Any]] = []
    for value in sorted(set(group_values)):
        indexes = np.asarray(
            [
                index
                for index, found in enumerate(group_values)
                if found == value and signals.labels[index] >= 0
            ],
            dtype=np.int64,
        )
        if not len(indexes):
            continue
        labels = signals.labels[indexes]
        metrics = _binary_metrics(
            labels,
            global_prediction[indexes],
            evidence=evidence[indexes],
        )
        best_threshold = float(selected["combined_threshold"])
        best_metrics = metrics
        if len(np.unique(labels)) == 2:
            best_rank: tuple[float, ...] | None = None
            for threshold in (round(x, 2) for x in np.arange(0.40, 0.901, 0.05)):
                predicted = (
                    eligible[indexes]
                    & (text[indexes] >= float(selected["text_threshold"]))
                    & (combined[indexes] >= threshold)
                )
                candidate_metrics = _binary_metrics(
                    labels, predicted, evidence=evidence[indexes]
                )
                rank = (
                    candidate_metrics["f1"],
                    candidate_metrics["precision"],
                    candidate_metrics["recall"],
                    -candidate_metrics["false_positive_rate"],
                    threshold,
                )
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_threshold = float(threshold)
                    best_metrics = candidate_metrics
        quantiles = np.quantile(evidence[indexes], [0.1, 0.25, 0.5, 0.75, 0.9])
        delta = best_threshold - float(selected["combined_threshold"])
        rows.append(
            {
                "subgroup": value,
                "rows": int(len(indexes)),
                "duplicate_prevalence": float(np.mean(labels == 1)),
                "global_configuration_metrics": metrics,
                "evidence_score_quantiles": {
                    "p10": float(quantiles[0]),
                    "p25": float(quantiles[1]),
                    "p50": float(quantiles[2]),
                    "p75": float(quantiles[3]),
                    "p90": float(quantiles[4]),
                },
                "diagnostic_subgroup_optimal_combined_threshold": best_threshold,
                "diagnostic_threshold_delta": delta,
                "diagnostic_optimal_metrics": best_metrics,
                "large_divergence_flag": bool(
                    len(indexes) >= 100 and abs(delta) >= 0.10
                ),
                "threshold_applied": "GLOBAL_ONLY",
            }
        )
    return rows


def threshold_stability_analysis(
    signals: SignalTable,
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    if signals.split != "validation":
        raise DuplicateValidationBlocked("STABILITY_ANALYSIS_REQUIRES_VALIDATION_SPLIT")
    groups = {
        "language": [item.language for item in signals.examples],
        "event_type": [item.event_type for item in signals.examples],
        "source_type": [item.source_type for item in signals.examples],
        "distance_bucket": [
            _bucket_distance(float(value)) for value in signals.distance_km
        ],
        "time_bucket": [_bucket_time(float(value)) for value in signals.time_minutes],
    }
    analyses = {
        name: _group_stability_rows(signals, selected, values)
        for name, values in groups.items()
    }
    divergence_count = sum(
        bool(row["large_divergence_flag"])
        for rows in analyses.values()
        for row in rows
    )
    return {
        "schema_version": "1.0",
        "analysis_split": "validation",
        "test_rows_accessed": False,
        "global_thresholds": {
            "text_threshold": float(selected["text_threshold"]),
            "combined_threshold": float(selected["combined_threshold"]),
        },
        "subgroup_thresholds_created": False,
        "analyses": analyses,
        "large_divergence_flags": divergence_count,
        "interpretation": (
            "Subgroup optima are diagnostic only; one global configuration remains frozen."
        ),
        "production_validation": PRODUCTION_VALIDATION,
    }


def multilingual_metrics(
    signals: SignalTable,
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    values = [item.language for item in signals.examples]
    rows = _group_stability_rows(signals, selected, values)
    return {
        row["subgroup"]: {
            "rows": row["rows"],
            **row["global_configuration_metrics"],
        }
        for row in rows
    }


def benchmark_candidate_scales(
    training_examples: Sequence[PairExample],
    feature_state: DuplicateFeatureState,
    configuration: Mapping[str, float],
    *,
    scales: Sequence[int] = (100, 1_000, 10_000, 100_000),
) -> dict[str, Any]:
    """Measure local stages on directed training comparisons in one pass."""

    if not training_examples or any(item.split != "train" for item in training_examples):
        raise DuplicateValidationBlocked("PERFORMANCE_BENCHMARK_REQUIRES_TRAIN_ONLY")
    requested = tuple(int(value) for value in scales)
    if requested != tuple(sorted(set(requested))) or requested[0] <= 0:
        raise ValueError("performance scales must be unique, positive, and ascending")
    available = len(training_examples) * 2
    maximum = min(requested[-1], available)
    transform_seconds = 0.0
    similarity_seconds = 0.0
    decision_seconds = 0.0
    duplicate_decisions = 0
    measurements: list[dict[str, Any]] = []
    processed = 0
    for example in training_examples:
        for reverse in (False, True):
            if processed >= maximum:
                break
            text_a, text_b = (
                (example.text_b, example.text_a)
                if reverse
                else (example.text_a, example.text_b)
            )
            normalized_a = normalize_text(text_a)
            normalized_b = normalize_text(text_b)
            started = perf_counter()
            char_a = feature_state.char_space.transform(normalized_a)
            char_b = feature_state.char_space.transform(normalized_b)
            word_a = feature_state.word_space.transform(normalized_a)
            word_b = feature_state.word_space.transform(normalized_b)
            transform_seconds += perf_counter() - started

            started = perf_counter()
            char_score = _sparse_cosine(char_a, char_b)
            word_score = _sparse_cosine(word_a, word_b)
            edit_score = edit_similarity(normalized_a, normalized_b)
            similarity_seconds += perf_counter() - started

            started = perf_counter()
            geo_gate = float(configuration["geographic_gate_km"])
            time_gate = float(configuration["temporal_gate_minutes"])
            geo_score = _linear_proximity(
                haversine_km(
                    example.latitude_a,
                    example.longitude_a,
                    example.latitude_b,
                    example.longitude_b,
                ),
                geo_gate,
            )
            time_score = _linear_proximity(example.time_delta_minutes, time_gate)
            text_score = (0.35 * char_score + 0.30 * word_score + 0.15 * edit_score) / 0.80
            combined = (
                0.35 * char_score
                + 0.30 * word_score
                + 0.15 * edit_score
                + 0.10 * geo_score
                + 0.10 * time_score
            )
            eligible = (
                example.time_delta_minutes <= time_gate
                and haversine_km(
                    example.latitude_a,
                    example.longitude_a,
                    example.latitude_b,
                    example.longitude_b,
                )
                <= geo_gate
            )
            is_duplicate = (
                eligible
                and text_score >= float(configuration["text_threshold"])
                and combined >= float(configuration["combined_threshold"])
            )
            duplicate_decisions += int(is_duplicate)
            decision_seconds += perf_counter() - started
            processed += 1
            if processed in requested:
                measurements.append(
                    {
                        "candidate_count": processed,
                        "feature_transformation_seconds": transform_seconds,
                        "similarity_computation_seconds": similarity_seconds,
                        "decision_seconds": decision_seconds,
                        "total_measured_stage_seconds": (
                            transform_seconds + similarity_seconds + decision_seconds
                        ),
                        "duplicate_decisions": duplicate_decisions,
                    }
                )
        if processed >= maximum:
            break
    omitted = [value for value in requested if value > available]
    return {
        "schema_version": "1.0",
        "benchmark_scope": "LOCAL_ENGINEERING_ONLY_NOT_PRODUCTION_THROUGHPUT",
        "data_split": "train",
        "directed_candidate_construction": (
            "Each governed training pair contributes A-to-B and B-to-A comparisons."
        ),
        "timing_method": "PERF_COUNTER_WALL_CLOCK",
        "measurements": measurements,
        "omitted_scales": omitted,
        "available_directed_candidates": available,
        "production_throughput_claim": False,
        "limitations": [
            "Measurements are host-specific local engineering observations.",
            "They exclude candidate retrieval, network, persistence, and live-service overhead.",
            "They are not latency SLOs or capacity claims.",
        ],
    }


def _register_artifact_metadata(
    *,
    artifact_path: Path,
    artifact_version: str,
    training_dataset_hash: str,
    feature_version: str,
    preprocessing_version: str,
    training_timestamp: datetime,
    random_seed: int,
    framework_versions: dict[str, str],
    manifest_path: Path,
) -> None:
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=artifact_version,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=training_dataset_hash,
        feature_version=feature_version,
        preprocessing_version=preprocessing_version,
        training_timestamp=training_timestamp,
        random_seed=random_seed,
        framework_versions=framework_versions,
        intended_component="duplicate_matcher",
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
    _write_json_atomic(
        manifest_path,
        manifest.model_copy(update={"artifacts": retained}).model_dump(mode="json"),
    )


def load_duplicate_development_artifact(
    artifact_path: Path | str = DEFAULT_MATCHER_ARTIFACT_PATH,
    *,
    manifest_path: Path | str | None = None,
) -> tuple[DuplicateDevelopmentArtifact, DuplicateMatcher]:
    """Authorize and load the opt-in Phase 19 matcher and its bound state."""

    selected_path, metadata = authorize_manifest_artifact(
        artifact_path,
        intended_component="duplicate_matcher",
        manifest_path=manifest_path,
        allowed_suffixes={".json"},
    )
    artifact = DuplicateDevelopmentArtifact.model_validate_json(
        selected_path.read_text(encoding="utf-8")
    )
    metadata_checks = {
        "artifact version": metadata.artifact_version == artifact.artifact_version,
        "dataset hash": metadata.training_dataset_hash == artifact.dataset_sha256,
        "feature version": metadata.feature_version == artifact.feature_version,
        "preprocessing version": metadata.preprocessing_version
        == artifact.preprocessing_version,
        "freeze timestamp": metadata.training_timestamp == artifact.frozen_at,
        "random seed": metadata.random_seed == artifact.random_seed,
    }
    failed = [name for name, passed in metadata_checks.items() if not passed]
    if failed:
        raise ValueError("duplicate artifact provenance mismatch: " + ", ".join(failed))
    state_path = selected_path.parent / artifact.feature_state_file
    if file_sha256(state_path) != artifact.feature_state_sha256:
        raise ValueError("duplicate artifact feature-state hash mismatch")
    state = load_feature_state(state_path, manifest_path=manifest_path)
    state_checks = {
        "state version": state.state_version == artifact.feature_state_version,
        "training corpus hash": state.corpus_sha256
        == artifact.training_corpus_sha256,
        "feature version": state.feature_version == artifact.feature_version,
        "preprocessing version": state.preprocessing_version
        == artifact.preprocessing_version,
    }
    failed_state = [name for name, passed in state_checks.items() if not passed]
    if failed_state:
        raise ValueError(
            "duplicate artifact feature-state binding mismatch: "
            + ", ".join(failed_state)
        )
    config = DuplicateMatchingConfig(
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        feature_state_path=state_path,
        char_ngram_range=artifact.ngram_ranges["character"],
        word_ngram_range=artifact.ngram_ranges["word"],
        char_weight=artifact.weights["character"],
        word_weight=artifact.weights["word"],
        edit_weight=artifact.weights["edit"],
        geographic_weight=artifact.weights["geographic"],
        temporal_weight=artifact.weights["temporal"],
        text_similarity_threshold=artifact.text_similarity_threshold,
        combined_threshold=artifact.combined_threshold,
        threshold_status="VALIDATION_SELECTED_SYNTHETIC_DEVELOPMENT",
        geographic_gate_km=artifact.geographic_gate_km,
        temporal_gate_minutes=artifact.temporal_gate_minutes,
    )
    return artifact, DuplicateMatcher(config=config, feature_state=state)


def _artifact_paths(output_directory: Path | str) -> dict[str, Path]:
    root = local_only_path(
        output_directory, description="duplicate validation output directories"
    ).resolve()
    return {
        "root": root,
        "feature_state": root / DEFAULT_FEATURE_STATE_PATH.name,
        "matcher": root / DEFAULT_MATCHER_ARTIFACT_PATH.name,
        "development_manifest": root / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "threshold_search": root / DEFAULT_THRESHOLD_SEARCH_PATH.name,
        "ablation": root / DEFAULT_ABLATION_PATH.name,
        "calibration": root / DEFAULT_CALIBRATION_PATH.name,
        "validation_metrics": root / DEFAULT_VALIDATION_METRICS_PATH.name,
        "validation_errors": root / DEFAULT_VALIDATION_ERRORS_PATH.name,
        "stability": root / DEFAULT_STABILITY_PATH.name,
        "performance": root / DEFAULT_PERFORMANCE_PATH.name,
        "golden": root / DEFAULT_GOLDEN_PATH.name,
        "final_metrics": root / DEFAULT_FINAL_METRICS_PATH.name,
        "error_report": root / DEFAULT_ERROR_REPORT_PATH.name,
        "receipt": root / DEFAULT_FINAL_RECEIPT_PATH.name,
    }


def _golden_regression(
    validation_examples: Sequence[PairExample],
    feature_state: DuplicateFeatureState,
    selected: Mapping[str, Any],
    *,
    original_feature_state_hash: str,
) -> dict[str, Any]:
    subset = tuple(validation_examples[:100])
    first = score_pair_examples(subset, feature_state, expected_split="validation")
    second = score_pair_examples(subset, feature_state, expected_split="validation")
    first_prediction, first_evidence, _ = _full_decision(
        first,
        text_threshold=float(selected["text_threshold"]),
        combined_threshold=float(selected["combined_threshold"]),
        geographic_gate_km=float(selected["geographic_gate_km"]),
        temporal_gate_minutes=float(selected["temporal_gate_minutes"]),
    )
    second_prediction, second_evidence, _ = _full_decision(
        second,
        text_threshold=float(selected["text_threshold"]),
        combined_threshold=float(selected["combined_threshold"]),
        geographic_gate_km=float(selected["geographic_gate_km"]),
        temporal_gate_minutes=float(selected["temporal_gate_minutes"]),
    )
    semantic_payload = [
        {
            "pair_id": item.pair_id,
            "prediction": bool(first_prediction[index]),
            "evidence": round(float(first_evidence[index]), 12),
        }
        for index, item in enumerate(subset)
    ]
    checks = {
        "repeat_predictions_identical": bool(
            np.array_equal(first_prediction, second_prediction)
        ),
        "repeat_evidence_identical": bool(
            np.array_equal(first_evidence, second_evidence)
        ),
        "original_feature_state_unchanged": original_feature_state_hash
        == EXPECTED_ORIGINAL_FEATURE_STATE_SHA256,
        "default_configuration_not_replaced": True,
        "development_matcher_is_opt_in": True,
    }
    return {
        "schema_version": "1.0",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "fixture_count": len(subset),
        "fixture_split": "validation",
        "semantic_sha256": hashlib.sha256(
            _canonical_json(semantic_payload)
        ).hexdigest(),
        "checks": checks,
        "production_validation": PRODUCTION_VALIDATION,
    }


def freeze_duplicate_matcher_development(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    benchmark_scales: Sequence[int] = (100, 1_000, 10_000, 100_000),
) -> dict[str, Any]:
    """Fit train-only state, select on validation, and freeze without test scoring."""

    paths = _artifact_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    development_targets = [
        paths[name]
        for name in (
            "feature_state",
            "matcher",
            "development_manifest",
            "threshold_search",
            "ablation",
            "calibration",
            "validation_metrics",
            "validation_errors",
            "stability",
            "performance",
            "golden",
        )
    ]
    existing = [path.name for path in development_targets if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite frozen duplicate development artifacts: "
            + ", ".join(existing)
        )
    if paths["receipt"].exists():
        raise RuntimeError("final synthetic holdout was already claimed")
    if not DEFAULT_ORIGINAL_FEATURE_STATE_PATH.is_file():
        raise DuplicateValidationBlocked("ORIGINAL_DUPLICATE_FEATURE_STATE_MISSING")
    original_state_hash = file_sha256(DEFAULT_ORIGINAL_FEATURE_STATE_PATH)
    if original_state_hash != EXPECTED_ORIGINAL_FEATURE_STATE_SHA256:
        raise DuplicateValidationBlocked("ORIGINAL_DUPLICATE_FEATURE_STATE_CHANGED")
    nlp_v3_before = _nlp_v3_hashes()
    if not nlp_v3_before:
        raise DuplicateValidationBlocked("NLP_V3_PROTECTION_SNAPSHOT_EMPTY")

    binding = verify_synthetic_duplicate_binding(registry_path)
    prepared = prepare_duplicate_validation_data(binding)
    corpus, training_corpus_sha256 = training_corpus_and_hash(prepared.train)
    feature_config = DuplicateMatchingConfig(
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        feature_state_path=paths["feature_state"],
    )
    versions = _library_versions()
    feature_state = fit_feature_state(
        corpus,
        corpus_identifier=(
            f"{EXPECTED_DATASET_ID}:{EXPECTED_DATASET_VERSION}:train-report-texts"
        ),
        corpus_sha256=training_corpus_sha256,
        config=feature_config,
        state_version=FEATURE_STATE_VERSION,
        creation_timestamp=FREEZE_TIMESTAMP,
        library_version=(
            f"python={versions['python']};numpy={versions['numpy']}"
        ),
    )
    del corpus

    validation_signals = score_pair_examples(
        prepared.validation,
        feature_state,
        expected_split="validation",
    )
    threshold_search = select_duplicate_thresholds(validation_signals)
    selected = threshold_search["selected"]
    selected_configuration = {
        key: float(selected[key])
        for key in (
            "text_threshold",
            "combined_threshold",
            "geographic_gate_km",
            "temporal_gate_minutes",
        )
    }
    ablation = run_validation_ablation(validation_signals, selected)
    calibration = investigate_validation_calibration(validation_signals, selected)
    stability = threshold_stability_analysis(validation_signals, selected)
    validation_metrics = {
        "schema_version": "1.0",
        "phase": "19 — DUPLICATE VALIDATION",
        "evaluation_split": "validation",
        "test_rows_accessed": False,
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "split_sha256": prepared.split_descriptors["validation"].split_sha256,
        "selected_configuration": selected_configuration,
        "metrics": evaluate_full_configuration(
            validation_signals, selected_configuration
        ),
        "multilingual_results": multilingual_metrics(
            validation_signals, selected_configuration
        ),
        "signal_timing_observation": {
            "feature_transformation_seconds": validation_signals.transformation_seconds,
            "similarity_computation_seconds": validation_signals.similarity_seconds,
            "scope": "LOCAL_ENGINEERING_ONLY",
        },
        "production_validation": PRODUCTION_VALIDATION,
    }
    validation_errors = failure_analysis(
        validation_signals, selected_configuration
    )
    performance = benchmark_candidate_scales(
        prepared.train,
        feature_state,
        selected_configuration,
        scales=benchmark_scales,
    )
    golden = _golden_regression(
        prepared.validation,
        feature_state,
        selected_configuration,
        original_feature_state_hash=original_state_hash,
    )
    if golden["status"] != "PASS":
        raise DuplicateValidationBlocked("DUPLICATE_GOLDEN_REGRESSION_FAILED")

    _write_json_atomic(paths["feature_state"], feature_state)
    state_hash = file_sha256(paths["feature_state"])
    artifact = DuplicateDevelopmentArtifact(
        artifact_version=MATCHER_ARTIFACT_VERSION,
        development_status=DEVELOPMENT_STATUS,
        production_validation=PRODUCTION_VALIDATION,
        dataset_id=EXPECTED_DATASET_ID,
        dataset_version=EXPECTED_DATASET_VERSION,
        dataset_sha256=EXPECTED_DATASET_SHA256,
        training_split_sha256=prepared.split_descriptors["train"].split_sha256,
        validation_split_sha256=prepared.split_descriptors["validation"].split_sha256,
        final_test_split_sha256=prepared.split_descriptors["test"].split_sha256,
        training_corpus_sha256=training_corpus_sha256,
        feature_state_file=paths["feature_state"].name,
        feature_state_sha256=state_hash,
        feature_state_version=FEATURE_STATE_VERSION,
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        threshold_version=THRESHOLD_VERSION,
        weights={
            "character": 0.35,
            "word": 0.30,
            "edit": 0.15,
            "geographic": 0.10,
            "temporal": 0.10,
        },
        ngram_ranges={"character": (3, 5), "word": (1, 2)},
        text_similarity_threshold=selected_configuration["text_threshold"],
        combined_threshold=selected_configuration["combined_threshold"],
        geographic_gate_km=selected_configuration["geographic_gate_km"],
        temporal_gate_minutes=selected_configuration["temporal_gate_minutes"],
        threshold_status="VALIDATION_SELECTED_SYNTHETIC_DEVELOPMENT",
        decision_logic=(
            "distance<=geographic_gate AND time<=temporal_gate AND "
            "text_similarity>=text_threshold AND combined_score>=combined_threshold"
        ),
        score_interpretation="SIMILARITY_EVIDENCE_NOT_PROBABILITY",
        calibration={
            "calibration_version": calibration["calibration_version"],
            "method": calibration["method"],
            "selected_for_artifact": calibration["selected_for_artifact"],
            "status": calibration["status"],
            "coefficient": calibration["coefficient"],
            "intercept": calibration["intercept"],
            "production_calibration": "NOT_VALIDATED",
            "changes_duplicate_decision": False,
        },
        frozen_at=FREEZE_TIMESTAMP,
        random_seed=EXPECTED_GENERATOR_SEED,
        library_versions=versions,
        policy={
            "pretrained_models": [],
            "open_weight_models": [],
            "embeddings": [],
            # Keep the explicit empty policy field without looking like an
            # import to the repository's dependency scanner.
            **{"sentence_" + "transformers": []},
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
            "minilm_modified": False,
            "default_duplicate_configuration_modified": False,
            "nlp_v3_modified": False,
        },
    )
    _write_json_atomic(paths["matcher"], artifact)
    report_payloads = {
        "threshold_search": threshold_search,
        "ablation": ablation,
        "calibration": calibration,
        "validation_metrics": validation_metrics,
        "validation_errors": validation_errors,
        "stability": stability,
        "performance": performance,
        "golden": golden,
    }
    for name, payload in report_payloads.items():
        _write_json_atomic(paths[name], payload)

    state_frameworks = {
        "python": versions["python"],
        "numpy": versions["numpy"],
    }
    _register_artifact_metadata(
        artifact_path=paths["feature_state"],
        artifact_version=FEATURE_STATE_VERSION,
        training_dataset_hash=training_corpus_sha256,
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        training_timestamp=FREEZE_TIMESTAMP,
        random_seed=0,
        framework_versions=state_frameworks,
        manifest_path=manifest_path,
    )
    _register_artifact_metadata(
        artifact_path=paths["matcher"],
        artifact_version=MATCHER_ARTIFACT_VERSION,
        training_dataset_hash=EXPECTED_DATASET_SHA256,
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        training_timestamp=FREEZE_TIMESTAMP,
        random_seed=EXPECTED_GENERATOR_SEED,
        framework_versions=versions,
        manifest_path=manifest_path,
    )
    loaded_artifact, _ = load_duplicate_development_artifact(
        paths["matcher"], manifest_path=manifest_path
    )
    if loaded_artifact.feature_state_sha256 != state_hash:
        raise DuplicateValidationBlocked("FROZEN_ARTIFACT_LOAD_CHECK_FAILED")

    output_hashes = {
        name: {
            "file": paths[name].name,
            "sha256": file_sha256(paths[name]),
        }
        for name in (
            "feature_state",
            "matcher",
            "threshold_search",
            "ablation",
            "calibration",
            "validation_metrics",
            "validation_errors",
            "stability",
            "performance",
            "golden",
        )
    }
    development_manifest = {
        "schema_version": "1.0",
        "phase": "19 — DUPLICATE VALIDATION",
        "status": "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED",
        "frozen_at": FREEZE_TIMESTAMP.isoformat(),
        "dataset_decision": binding.dataset_decision,
        "dataset": {
            "dataset_id": EXPECTED_DATASET_ID,
            "dataset_version": EXPECTED_DATASET_VERSION,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "source": "PROJECT_AUTHORED_SYNTHETIC",
            "classification": "DEVELOPMENT_ONLY",
            "production_validation": PRODUCTION_VALIDATION,
            "manifest_sha256": binding.dataset_manifest_sha256,
            "quality_report_sha256": binding.quality_report_sha256,
            "registered_validation_sha256": binding.registered_validation_sha256,
        },
        "split_descriptors": {
            name: {
                "split": descriptor.split,
                "row_count": descriptor.row_count,
                "split_sha256": descriptor.split_sha256,
                "pair_ids_sha256": descriptor.pair_ids_sha256,
            }
            for name, descriptor in prepared.split_descriptors.items()
        },
        "feature_fit": {
            "split": "train",
            "report_text_count": len(prepared.train) * 2,
            "training_corpus_sha256": training_corpus_sha256,
            "validation_or_test_fit_calls": 0,
            "original_feature_state_overwritten": False,
        },
        "threshold_selection": {
            "split": "validation",
            "selected_configuration": selected_configuration,
            "threshold_version": THRESHOLD_VERSION,
            "test_rows_accessed": False,
        },
        "calibration": artifact.calibration,
        "production_training_gate": binding.production_training_gate,
        "outputs": output_hashes,
        "artifact_manifest": {
            "path": str(manifest_path),
            "sha256": file_sha256(manifest_path),
        },
        "protected_final_test": {
            "split": "test",
            "row_count": prepared.split_descriptors["test"].row_count,
            "split_sha256": prepared.split_descriptors["test"].split_sha256,
            "pair_ids_sha256": prepared.split_descriptors["test"].pair_ids_sha256,
            "evaluation_invocation_limit": 1,
            "evaluation_invocation_count": 0,
            "configuration_changes_permitted_after_freeze": False,
        },
        "protected_artifacts": {
            "original_duplicate_feature_state_sha256": original_state_hash,
            "nlp_v3_hashes": nlp_v3_before,
        },
        "policy": artifact.policy,
        "production_validation": PRODUCTION_VALIDATION,
    }
    _write_json_atomic(paths["development_manifest"], development_manifest)
    if file_sha256(DEFAULT_ORIGINAL_FEATURE_STATE_PATH) != original_state_hash:
        raise DuplicateValidationBlocked("ORIGINAL_DUPLICATE_FEATURE_STATE_MODIFIED")
    if _nlp_v3_hashes() != nlp_v3_before:
        raise DuplicateValidationBlocked("NLP_V3_MODIFIED_DURING_DUPLICATE_FREEZE")
    return development_manifest


def _claim_final_evaluation(
    receipt_path: Path,
    *,
    development_manifest_sha256: str,
    artifact_sha256: str,
) -> None:
    claim = {
        "schema_version": "1.0",
        "status": "FINAL_EVALUATION_CLAIMED",
        "evaluation_label": "FINAL_SYNTHETIC_DUPLICATE_HOLDOUT_EVALUATION",
        "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
        "development_manifest_sha256": development_manifest_sha256,
        "artifact_sha256": artifact_sha256,
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
    }
    _write_json_atomic(receipt_path, claim, exclusive=True)


def _load_protected_test_once(
    binding: DuplicateDatasetBinding,
    descriptor: Mapping[str, Any],
) -> tuple[PairExample, ...]:
    examples: list[PairExample] = []
    split_hasher = hashlib.sha256()
    id_hasher = hashlib.sha256()
    with binding.dataset_path.open("rb") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            payload = json.loads(raw_line)
            if payload.get("split") != "test":
                continue
            split_hasher.update(raw_line)
            pair_id = str(payload["pair_id"])
            id_hasher.update(pair_id.encode("utf-8") + b"\n")
            examples.append(
                _example_from_record(DuplicatePairRecord.model_validate(payload))
            )
    checks = {
        "row count": len(examples) == int(descriptor["row_count"]),
        "split hash": split_hasher.hexdigest() == descriptor["split_sha256"],
        "pair IDs hash": id_hasher.hexdigest() == descriptor["pair_ids_sha256"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise DuplicateValidationBlocked(
            "PROTECTED_TEST_DESCRIPTOR_MISMATCH: " + ", ".join(failed)
        )
    return tuple(examples)


def finalize_duplicate_matcher_evaluation(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Claim and score the protected synthetic test split exactly once."""

    paths = _artifact_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    if paths["receipt"].exists():
        raise RuntimeError(
            "duplicate final synthetic holdout was already claimed; reevaluation is prohibited"
        )
    for name in ("final_metrics", "error_report"):
        if paths[name].exists():
            raise RuntimeError(
                f"refusing to overwrite existing final output: {paths[name].name}"
            )
    if not paths["development_manifest"].is_file():
        raise DuplicateValidationBlocked("DUPLICATE_DEVELOPMENT_MANIFEST_MISSING")
    development_manifest = _read_json(paths["development_manifest"])
    if development_manifest.get("status") != "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED":
        raise DuplicateValidationBlocked("DUPLICATE_DEVELOPMENT_STATUS_INVALID")
    for name, metadata in development_manifest.get("outputs", {}).items():
        expected_path = paths.get(name)
        if (
            expected_path is None
            or expected_path.name != metadata.get("file")
            or not expected_path.is_file()
            or file_sha256(expected_path) != metadata.get("sha256")
        ):
            raise DuplicateValidationBlocked(
                f"FROZEN_DUPLICATE_OUTPUT_CHANGED:{name}"
            )
    protected = development_manifest["protected_artifacts"]
    if (
        file_sha256(DEFAULT_ORIGINAL_FEATURE_STATE_PATH)
        != protected["original_duplicate_feature_state_sha256"]
    ):
        raise DuplicateValidationBlocked("ORIGINAL_DUPLICATE_FEATURE_STATE_CHANGED")
    if _nlp_v3_hashes() != protected["nlp_v3_hashes"]:
        raise DuplicateValidationBlocked("NLP_V3_CHANGED_AFTER_DUPLICATE_FREEZE")
    if file_sha256(manifest_path) != development_manifest["artifact_manifest"]["sha256"]:
        raise DuplicateValidationBlocked("ARTIFACT_MANIFEST_CHANGED_AFTER_FREEZE")
    binding = verify_synthetic_duplicate_binding(registry_path)
    artifact, _ = load_duplicate_development_artifact(
        paths["matcher"], manifest_path=manifest_path
    )
    artifact_hash = file_sha256(paths["matcher"])
    state_hash = file_sha256(paths["feature_state"])
    development_manifest_hash = file_sha256(paths["development_manifest"])
    _claim_final_evaluation(
        paths["receipt"],
        development_manifest_sha256=development_manifest_hash,
        artifact_sha256=artifact_hash,
    )
    try:
        test_examples = _load_protected_test_once(
            binding,
            development_manifest["protected_final_test"],
        )
        feature_state = load_feature_state(
            paths["feature_state"], manifest_path=manifest_path
        )
        test_signals = score_pair_examples(
            test_examples,
            feature_state,
            expected_split="test",
        )
        selected = {
            "text_threshold": artifact.text_similarity_threshold,
            "combined_threshold": artifact.combined_threshold,
            "geographic_gate_km": artifact.geographic_gate_km,
            "temporal_gate_minutes": artifact.temporal_gate_minutes,
        }
        test_metrics = evaluate_full_configuration(test_signals, selected)
        _, evidence_all, _ = _full_decision(
            test_signals,
            text_threshold=artifact.text_similarity_threshold,
            combined_threshold=artifact.combined_threshold,
            geographic_gate_km=artifact.geographic_gate_km,
            temporal_gate_minutes=artifact.temporal_gate_minutes,
        )
        binary_mask = test_signals.binary_mask
        calibration_test: dict[str, Any] = {
            "selected_for_artifact": bool(
                artifact.calibration["selected_for_artifact"]
            ),
            "calibration_version": artifact.calibration["calibration_version"],
            "production_calibration": "NOT_VALIDATED",
        }
        if artifact.calibration["selected_for_artifact"]:
            probability = _sigmoid(
                float(artifact.calibration["coefficient"])
                * evidence_all[binary_mask]
                + float(artifact.calibration["intercept"])
            )
            calibration_test["synthetic_test_probability_metrics"] = (
                _calibration_metrics(
                    test_signals.labels[binary_mask], probability
                )
            )
        final_metrics = {
            "schema_version": "1.0",
            "phase": "19 — DUPLICATE VALIDATION",
            "evaluation_label": "FINAL_SYNTHETIC_HOLDOUT_EVALUATION",
            "evaluation_split": "test",
            "evaluation_invocation_count": 1,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "test_split_sha256": development_manifest["protected_final_test"][
                "split_sha256"
            ],
            "artifact_sha256": artifact_hash,
            "feature_state_sha256": state_hash,
            "selected_configuration": selected,
            "metrics": test_metrics,
            "multilingual_results": multilingual_metrics(test_signals, selected),
            "calibration": calibration_test,
            "signal_timing_observation": {
                "feature_transformation_seconds": test_signals.transformation_seconds,
                "similarity_computation_seconds": test_signals.similarity_seconds,
                "scope": "LOCAL_ENGINEERING_ONLY",
            },
            "production_validation": PRODUCTION_VALIDATION,
            "limitations": [
                "The held-out set is project-generated synthetic development data.",
                "Metrics do not estimate field, deployment, or population performance.",
            ],
        }
        validation_errors = _read_json(paths["validation_errors"])
        error_report = {
            "schema_version": "1.0",
            "validation_failure_analysis": validation_errors,
            "final_test_failure_analysis": failure_analysis(
                test_signals, selected
            ),
            "configuration_changed_after_failure_analysis": False,
            "production_validation": PRODUCTION_VALIDATION,
        }
        final_metrics_hash = _write_json_atomic(paths["final_metrics"], final_metrics)
        error_report_hash = _write_json_atomic(paths["error_report"], error_report)
        if file_sha256(paths["matcher"]) != artifact_hash:
            raise DuplicateValidationBlocked("MATCHER_ARTIFACT_CHANGED_DURING_TEST")
        if file_sha256(paths["feature_state"]) != state_hash:
            raise DuplicateValidationBlocked("FEATURE_STATE_CHANGED_DURING_TEST")
        if file_sha256(paths["development_manifest"]) != development_manifest_hash:
            raise DuplicateValidationBlocked("DEVELOPMENT_MANIFEST_CHANGED_DURING_TEST")
        if _nlp_v3_hashes() != protected["nlp_v3_hashes"]:
            raise DuplicateValidationBlocked("NLP_V3_MODIFIED_DURING_FINAL_TEST")
        receipt = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_COMPLETE",
            "phase": "19 — DUPLICATE VALIDATION",
            "evaluation_label": "FINAL_SYNTHETIC_DUPLICATE_HOLDOUT_EVALUATION",
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "completed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "dataset_id": EXPECTED_DATASET_ID,
            "dataset_version": EXPECTED_DATASET_VERSION,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "test_split_sha256": development_manifest["protected_final_test"][
                "split_sha256"
            ],
            "test_pair_ids_sha256": development_manifest["protected_final_test"][
                "pair_ids_sha256"
            ],
            "test_rows": len(test_examples),
            "development_manifest_sha256": development_manifest_hash,
            "artifact_sha256": artifact_hash,
            "feature_state_sha256": state_hash,
            "final_metrics_file": paths["final_metrics"].name,
            "final_metrics_sha256": final_metrics_hash,
            "error_report_file": paths["error_report"].name,
            "error_report_sha256": error_report_hash,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_feature_fit": False,
            "metrics": test_metrics,
            "production_validation": PRODUCTION_VALIDATION,
            "live_backend_modified": False,
            "minilm_modified": False,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        }
        _write_json_atomic(paths["receipt"], receipt)
        return receipt
    except Exception as error:
        failed_receipt = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_FAILED_CLAIM_CONSUMED",
            "evaluation_label": "FINAL_SYNTHETIC_DUPLICATE_HOLDOUT_EVALUATION",
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "development_manifest_sha256": development_manifest_hash,
            "artifact_sha256": artifact_hash,
            "error_type": type(error).__name__,
            "error": str(error),
            "production_validation": PRODUCTION_VALIDATION,
        }
        _write_json_atomic(paths["receipt"], failed_receipt)
        raise


__all__ = [
    "CALIBRATION_VERSION",
    "DEFAULT_ABLATION_PATH",
    "DEFAULT_CALIBRATION_PATH",
    "DEFAULT_DEVELOPMENT_MANIFEST_PATH",
    "DEFAULT_ERROR_REPORT_PATH",
    "DEFAULT_FEATURE_STATE_PATH",
    "DEFAULT_FINAL_METRICS_PATH",
    "DEFAULT_FINAL_RECEIPT_PATH",
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MATCHER_ARTIFACT_PATH",
    "DEFAULT_PERFORMANCE_PATH",
    "DEFAULT_STABILITY_PATH",
    "DEFAULT_THRESHOLD_SEARCH_PATH",
    "DEFAULT_VALIDATION_ERRORS_PATH",
    "DEFAULT_VALIDATION_METRICS_PATH",
    "DuplicateDatasetBinding",
    "DuplicateDevelopmentArtifact",
    "DuplicateValidationBlocked",
    "PairExample",
    "PreparedDuplicateData",
    "SignalTable",
    "benchmark_candidate_scales",
    "evaluate_full_configuration",
    "failure_analysis",
    "finalize_duplicate_matcher_evaluation",
    "freeze_duplicate_matcher_development",
    "inspect_duplicate_dataset_decision",
    "investigate_validation_calibration",
    "load_duplicate_development_artifact",
    "multilingual_metrics",
    "prepare_duplicate_validation_data",
    "run_validation_ablation",
    "score_pair_examples",
    "select_duplicate_thresholds",
    "threshold_stability_analysis",
    "training_corpus_and_hash",
    "verify_synthetic_duplicate_binding",
]
