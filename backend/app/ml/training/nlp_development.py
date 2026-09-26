"""Phase 14 local NLP development validation and one-shot final evaluation.

This module deliberately separates validation-driven model selection from the
protected final-test access path.  It is a development protocol for the one
registered synthetic corpus; it does not relax the general dataset approval
gate and it does not activate the resulting model in the live backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
from app.ml.contracts import ArtifactManifest, ArtifactMetadata, ArtifactPolicyStatus
from app.ml.data.loaders import load_csv
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetClassification,
    DatasetComponent,
    DatasetStatus,
    find_dataset,
    load_dataset_registry,
    resolve_registry_path,
)
from app.ml.data.schemas import DatasetRecord, DatasetSplit
from app.ml.evaluation.evaluate import NlpEvaluationReport, evaluate_nlp_predictions
from app.ml.training.train_nlp_classifier import EXPECTED_CLASSES, FLOOD_CLASSES, _audit_dataset


ML_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ML_ROOT / "artifacts"

DEFAULT_DATASET_ID = "indra-nlp-reports-v1-synthetic"
DEFAULT_DATASET_VERSION = "reports-v1-development-synthetic"
DEFAULT_MODEL_VERSION = "nlp-classifier-v2-development"
DEFAULT_FEATURE_VERSION = "nlp-features-v2"
DEFAULT_PREPROCESSING_VERSION = "nlp-text-normalization-v1"

DEFAULT_ARTIFACT_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH = (
    ARTIFACT_ROOT / "nlp_classifier_v2.development_manifest.json"
)
DEFAULT_SPLIT_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.split.json"
DEFAULT_SEARCH_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.search.json"
DEFAULT_VALIDATION_ERRORS_PATH = (
    ARTIFACT_ROOT / "nlp_classifier_v2.validation_errors.json"
)
DEFAULT_CALIBRATION_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.calibration.json"
DEFAULT_METRICS_PATH = ARTIFACT_ROOT / "nlp_classifier_v2.metrics.json"
DEFAULT_FINAL_RECEIPT_PATH = (
    ARTIFACT_ROOT / "nlp_classifier_v2.final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH = ARTIFACT_ROOT / "manifest.json"
DEFAULT_HISTORICAL_METRICS_PATH = ARTIFACT_ROOT / "nlp_classifier_v1.metrics.json"


class DevelopmentProtocolConfig(BaseModel):
    """Frozen controls for the small, validation-only development experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = "nlp-development-validation-v1"
    split_version: str = "nlp-development-split-v1"
    model_version: str = DEFAULT_MODEL_VERSION
    feature_version: str = DEFAULT_FEATURE_VERSION
    preprocessing_version: str = DEFAULT_PREPROCESSING_VERSION
    random_seed: int = 42
    validation_fraction: float = Field(default=0.20, gt=0.0, lt=1.0)
    max_iterations: int = Field(default=2000, gt=0)
    minimum_not_relevant_recall: float = Field(default=0.80, ge=0.0, le=1.0)
    minimum_macro_f1: float = Field(default=0.75, ge=0.0, le=1.0)
    maximum_flood_to_not_relevant_errors: int = Field(default=4, ge=0)
    minimum_subgroup_rows: int = Field(default=10, ge=2)
    expected_source_development_rows: int = Field(default=210, ge=1)
    expected_final_test_rows: int = Field(default=90, ge=1)
    calibration_bins: int = Field(default=5, ge=2, le=20)


DEFAULT_PROTOCOL_CONFIG = DevelopmentProtocolConfig()


class DevelopmentCandidate(BaseModel):
    """One explicitly enumerated, reproducible configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    configuration_id: str = Field(min_length=1)
    char_ngram_range: tuple[int, int]
    word_ngram_range: tuple[int, int] = (1, 2)
    character_weight: float = Field(default=1.0, gt=0.0)
    word_weight: float = Field(default=1.0, gt=0.0)
    class_weight: Literal["NONE", "BALANCED"] = "NONE"
    regularization_c: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def ranges_are_valid(self) -> "DevelopmentCandidate":
        if self.char_ngram_range[0] > self.char_ngram_range[1]:
            raise ValueError("character n-gram range must be ascending")
        if self.word_ngram_range[0] > self.word_ngram_range[1]:
            raise ValueError("word n-gram range must be ascending")
        return self


def controlled_search_space() -> tuple[DevelopmentCandidate, ...]:
    """Return the fixed 12-candidate search; this is not a generated grid."""

    candidates = (
        DevelopmentCandidate(
            configuration_id="A_EQUAL_NONE_C1",
            char_ngram_range=(3, 5),
        ),
        DevelopmentCandidate(
            configuration_id="A_EQUAL_BALANCED_C1",
            char_ngram_range=(3, 5),
            class_weight="BALANCED",
        ),
        DevelopmentCandidate(
            configuration_id="B_EQUAL_NONE_C1",
            char_ngram_range=(2, 5),
        ),
        DevelopmentCandidate(
            configuration_id="B_EQUAL_BALANCED_C1",
            char_ngram_range=(2, 5),
            class_weight="BALANCED",
        ),
        DevelopmentCandidate(
            configuration_id="C_EQUAL_NONE_C1",
            char_ngram_range=(3, 6),
        ),
        DevelopmentCandidate(
            configuration_id="C_EQUAL_BALANCED_C1",
            char_ngram_range=(3, 6),
            class_weight="BALANCED",
        ),
        DevelopmentCandidate(
            configuration_id="D_CHAR125_NONE_C1",
            char_ngram_range=(3, 5),
            character_weight=1.25,
            word_weight=0.75,
        ),
        DevelopmentCandidate(
            configuration_id="D_CHAR125_BALANCED_C1",
            char_ngram_range=(3, 5),
            character_weight=1.25,
            word_weight=0.75,
            class_weight="BALANCED",
        ),
        DevelopmentCandidate(
            configuration_id="E_WORD125_NONE_C1",
            char_ngram_range=(3, 5),
            character_weight=0.75,
            word_weight=1.25,
        ),
        DevelopmentCandidate(
            configuration_id="E_WORD125_BALANCED_C1",
            char_ngram_range=(3, 5),
            character_weight=0.75,
            word_weight=1.25,
            class_weight="BALANCED",
        ),
        DevelopmentCandidate(
            configuration_id="F_EQUAL_NONE_C0_5",
            char_ngram_range=(3, 5),
            regularization_c=0.5,
        ),
        DevelopmentCandidate(
            configuration_id="G_EQUAL_NONE_C2",
            char_ngram_range=(3, 5),
            regularization_c=2.0,
        ),
    )
    if len({candidate.configuration_id for candidate in candidates}) != len(candidates):
        raise RuntimeError("development configuration identifiers must be unique")
    return candidates


@dataclass(frozen=True)
class SelectionDataset:
    """Only records that configuration selection is permitted to receive."""

    train_records: tuple[DatasetRecord, ...]
    validation_records: tuple[DatasetRecord, ...]
    train_sha256: str
    validation_sha256: str


@dataclass(frozen=True)
class FinalTestDescriptor:
    """Integrity metadata only; it carries no test text or labels."""

    record_ids_in_source_order: tuple[str, ...]
    split_sha256: str
    source_order_sha256: str
    sample_count: int


@dataclass(frozen=True)
class PreparedDevelopmentData:
    selection: SelectionDataset
    final_test: FinalTestDescriptor
    dataset_path: Path
    dataset_sha256: str
    dataset_id: str
    dataset_version: str
    split_manifest: dict[str, Any]


@dataclass
class CandidateFit:
    candidate: DevelopmentCandidate
    vectorizers: tuple[Any, Any]
    classifier: Any
    train_predictions: list[str]
    validation_predictions: list[str]
    validation_logits: np.ndarray
    compact_train_metrics: dict[str, Any]
    compact_validation_metrics: dict[str, Any]
    feature_count: int


@dataclass(frozen=True)
class ModelSelectionResult:
    selected_fit: CandidateFit
    candidate_results: tuple[dict[str, Any], ...]
    selection_details: dict[str, Any]
    class_weight_result: dict[str, Any]


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


def canonical_record_hash(records: Sequence[DatasetRecord]) -> str:
    payload = [
        record.model_dump(mode="json")
        for record in sorted(records, key=lambda item: item.record_id)
    ]
    return _canonical_hash(payload)


def _source_order_hash(records: Sequence[DatasetRecord]) -> str:
    return _canonical_hash([record.record_id for record in records])


def _distribution(
    records: Sequence[DatasetRecord], field: Literal["event_type", "language"]
) -> dict[str, int]:
    return dict(
        sorted(
            Counter(str(getattr(record, field) or "unknown") for record in records).items()
        )
    )


def _ensure_valid_labels(records: Sequence[DatasetRecord], split_name: str) -> None:
    missing = [record.record_id for record in records if not record.event_type]
    if missing:
        raise ValueError(f"{split_name} has rows without event labels: {missing}")


def create_development_split(
    source_development_records: Sequence[DatasetRecord],
    *,
    config: DevelopmentProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
) -> SelectionDataset:
    """Create one deterministic stratified train/validation split or fail closed."""

    from sklearn.model_selection import train_test_split

    records = sorted(source_development_records, key=lambda item: item.record_id)
    if not records:
        raise ValueError("source development split is empty")
    _ensure_valid_labels(records, "source development split")
    counts = Counter(str(record.event_type) for record in records)
    if set(counts) != EXPECTED_CLASSES:
        raise ValueError(
            "source development classes do not match the audited class set: "
            f"{sorted(counts)}"
        )
    too_small = {label: count for label, count in counts.items() if count < 2}
    if too_small:
        raise ValueError(
            "deterministic stratification is impossible because each class needs "
            f"at least two rows: {too_small}"
        )
    validation_count = int(np.ceil(len(records) * config.validation_fraction))
    class_count = len(counts)
    if validation_count < class_count or len(records) - validation_count < class_count:
        raise ValueError(
            "deterministic stratification is impossible for the configured split size"
        )

    indexes = np.arange(len(records))
    labels = np.asarray([str(record.event_type) for record in records])
    try:
        train_indexes, validation_indexes = train_test_split(
            indexes,
            test_size=config.validation_fraction,
            random_state=config.random_seed,
            shuffle=True,
            stratify=labels,
        )
    except ValueError as error:
        raise ValueError(f"deterministic stratification failed: {error}") from error

    train_records = tuple(sorted((records[index] for index in train_indexes), key=lambda item: item.record_id))
    validation_records = tuple(
        sorted((records[index] for index in validation_indexes), key=lambda item: item.record_id)
    )
    if set(record.record_id for record in train_records) & set(
        record.record_id for record in validation_records
    ):
        raise RuntimeError("development train and validation identifiers overlap")
    if set(record.event_type for record in train_records) != EXPECTED_CLASSES:
        raise ValueError("stratified training split lost one or more classes")
    if set(record.event_type for record in validation_records) != EXPECTED_CLASSES:
        raise ValueError("stratified validation split lost one or more classes")
    return SelectionDataset(
        train_records=train_records,
        validation_records=validation_records,
        train_sha256=canonical_record_hash(train_records),
        validation_sha256=canonical_record_hash(validation_records),
    )


def prepare_registered_development_data(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    config: DevelopmentProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
) -> PreparedDevelopmentData:
    """Validate and partition the one registered Phase 14 development corpus."""

    registry_path = local_only_path(registry_path, description="dataset registries")
    registry = load_dataset_registry(registry_path)
    registered = find_dataset(registry, dataset_id, dataset_version)
    if registered.component is not DatasetComponent.NLP:
        raise ValueError("Phase 14 requires a registered NLP dataset")
    if registered.status is not DatasetStatus.VALID:
        raise ValueError("Phase 14 requires structurally VALID registered data")
    if registered.data_classification is not DatasetClassification.DEVELOPMENT_ONLY:
        raise ValueError("Phase 14 protocol is restricted to DEVELOPMENT_ONLY data")
    dataset_path = resolve_registry_path(registered.local_path, registry_path)
    if not dataset_path.is_file():
        raise ValueError("registered NLP dataset file is unavailable")
    dataset_hash = file_sha256(dataset_path)
    if dataset_hash != registered.content_sha256:
        raise ValueError("registered NLP dataset hash mismatch")

    records = load_csv(dataset_path)
    audit = _audit_dataset(records)
    if audit["status"] != "VALID":
        raise ValueError("Phase 14 dataset audit failed: " + json.dumps(audit, sort_keys=True))
    source_development = [
        record for record in records if record.split is DatasetSplit.TRAIN
    ]
    final_test_records = [
        record for record in records if record.split is DatasetSplit.TEST
    ]
    if len(source_development) != config.expected_source_development_rows:
        raise ValueError(
            "unexpected source development row count: "
            f"{len(source_development)} != {config.expected_source_development_rows}"
        )
    if len(final_test_records) != config.expected_final_test_rows:
        raise ValueError(
            "unexpected protected final-test row count: "
            f"{len(final_test_records)} != {config.expected_final_test_rows}"
        )
    _ensure_valid_labels(final_test_records, "protected final test")
    selection = create_development_split(source_development, config=config)
    final_descriptor = FinalTestDescriptor(
        record_ids_in_source_order=tuple(record.record_id for record in final_test_records),
        split_sha256=canonical_record_hash(final_test_records),
        source_order_sha256=_source_order_hash(final_test_records),
        sample_count=len(final_test_records),
    )
    split_manifest = {
        "schema_version": "1.0",
        "split_version": config.split_version,
        "method": "deterministic sklearn train_test_split with event_type stratification",
        "source_split": "existing train rows only",
        "random_seed": config.random_seed,
        "validation_fraction": config.validation_fraction,
        "dataset_sha256": dataset_hash,
        "source_development_count": len(source_development),
        "train_count": len(selection.train_records),
        "validation_count": len(selection.validation_records),
        "final_test_count": final_descriptor.sample_count,
        "train_sha256": selection.train_sha256,
        "validation_sha256": selection.validation_sha256,
        "final_test_sha256": final_descriptor.split_sha256,
        "final_test_source_order_sha256": final_descriptor.source_order_sha256,
        "train_record_ids": [record.record_id for record in selection.train_records],
        "validation_record_ids": [
            record.record_id for record in selection.validation_records
        ],
        "final_test_record_ids_in_source_order": list(
            final_descriptor.record_ids_in_source_order
        ),
        "class_distribution": {
            "source_development": _distribution(source_development, "event_type"),
            "train": _distribution(selection.train_records, "event_type"),
            "validation": _distribution(selection.validation_records, "event_type"),
            "final_test": _distribution(final_test_records, "event_type"),
        },
        "language_distribution": {
            "train": _distribution(selection.train_records, "language"),
            "validation": _distribution(selection.validation_records, "language"),
            "final_test": _distribution(final_test_records, "language"),
        },
        "final_test_policy": "PROTECTED / NOT AVAILABLE TO CONFIGURATION_SELECTION",
    }
    split_manifest["split_definition_sha256"] = _canonical_hash(split_manifest)
    return PreparedDevelopmentData(
        selection=selection,
        final_test=final_descriptor,
        dataset_path=dataset_path,
        dataset_sha256=dataset_hash,
        dataset_id=registered.dataset_id,
        dataset_version=registered.dataset_version,
        split_manifest=split_manifest,
    )


def _fit_vectorizers(
    texts: Sequence[str], candidate: DevelopmentCandidate
) -> tuple[Any, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    normalized = [normalize_text(text) for text in texts]
    char_vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=candidate.char_ngram_range,
        sublinear_tf=True,
        lowercase=False,
        norm="l2",
    )
    word_vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=candidate.word_ngram_range,
        sublinear_tf=True,
        lowercase=False,
        token_pattern=r"(?u)\b\w+\b",
        norm="l2",
    )
    char_vectorizer.fit(normalized)
    word_vectorizer.fit(normalized)
    return char_vectorizer, word_vectorizer


def _transform(
    vectorizers: tuple[Any, Any],
    texts: Sequence[str],
    candidate: DevelopmentCandidate,
):
    from scipy.sparse import hstack

    normalized = [normalize_text(text) for text in texts]
    char_vectorizer, word_vectorizer = vectorizers
    char_features = char_vectorizer.transform(normalized) * candidate.character_weight
    word_features = word_vectorizer.transform(normalized) * candidate.word_weight
    return hstack([char_features, word_features], format="csr")


def _compact_metrics(report: NlpEvaluationReport) -> dict[str, Any]:
    return {
        "sample_count": report.sample_count,
        "accuracy": report.accuracy,
        "macro_precision": report.macro_precision,
        "macro_recall": report.macro_recall,
        "macro_f1": report.macro_f1,
        "not_relevant_recall": report.not_relevant_recall,
        "confusion_matrix": report.confusion_matrix,
    }


def _fit_candidate(
    selection: SelectionDataset,
    candidate: DevelopmentCandidate,
    config: DevelopmentProtocolConfig,
) -> CandidateFit:
    from sklearn.linear_model import LogisticRegression

    train_texts = [record.text for record in selection.train_records]
    validation_texts = [record.text for record in selection.validation_records]
    train_labels = [str(record.event_type) for record in selection.train_records]
    validation_labels = [
        str(record.event_type) for record in selection.validation_records
    ]
    classes = sorted(EXPECTED_CLASSES)
    vectorizers = _fit_vectorizers(train_texts, candidate)
    train_features = _transform(vectorizers, train_texts, candidate)
    validation_features = _transform(vectorizers, validation_texts, candidate)
    classifier = LogisticRegression(
        C=candidate.regularization_c,
        max_iter=config.max_iterations,
        random_state=config.random_seed,
        solver="lbfgs",
        class_weight=("balanced" if candidate.class_weight == "BALANCED" else None),
    )
    classifier.fit(train_features, train_labels)
    train_predictions = classifier.predict(train_features).tolist()
    validation_predictions = classifier.predict(validation_features).tolist()
    validation_logits = np.asarray(
        classifier.decision_function(validation_features), dtype=np.float64
    )
    train_report = evaluate_nlp_predictions(train_labels, train_predictions, classes)
    validation_report = evaluate_nlp_predictions(
        validation_labels,
        validation_predictions,
        classes,
    )
    return CandidateFit(
        candidate=candidate,
        vectorizers=vectorizers,
        classifier=classifier,
        train_predictions=train_predictions,
        validation_predictions=validation_predictions,
        validation_logits=validation_logits,
        compact_train_metrics=_compact_metrics(train_report),
        compact_validation_metrics=_compact_metrics(validation_report),
        feature_count=int(train_features.shape[1]),
    )


def _selection_sort_key(result: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = result["validation"]
    return (
        -float(metrics["macro_f1"]),
        -float(metrics["not_relevant_recall"]),
        -float(metrics["accuracy"]),
        str(result["configuration"]["configuration_id"]),
    )


def select_result_by_rule(
    results: Sequence[Mapping[str, Any]],
    *,
    minimum_not_relevant_recall: float,
    minimum_macro_f1: float,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Apply the frozen constrained rule, including its explicit fallback."""

    if not results:
        raise ValueError("at least one model result is required for selection")
    eligible = [
        result
        for result in results
        if float(result["validation"]["not_relevant_recall"])
        >= minimum_not_relevant_recall
        and float(result["validation"]["macro_f1"]) >= minimum_macro_f1
    ]
    if eligible:
        selected = sorted(eligible, key=_selection_sort_key)[0]
        return selected, {
            "rule_version": "constrained-not-relevant-recall-v1",
            "primary_constraint": {
                "metric": "validation NOT_RELEVANT recall",
                "minimum": minimum_not_relevant_recall,
            },
            "preservation_constraint": {
                "metric": "validation macro F1",
                "minimum": minimum_macro_f1,
            },
            "optimization": "maximize validation macro F1; then NOT_RELEVANT recall; then accuracy; then configuration ID",
            "selection_path": "PRIMARY_CONSTRAINT_SATISFIED",
            "eligible_configuration_ids": [
                item["configuration"]["configuration_id"]
                for item in sorted(eligible, key=_selection_sort_key)
            ],
            "test_set_used": False,
        }

    macro_preserving = [
        result
        for result in results
        if float(result["validation"]["macro_f1"]) >= minimum_macro_f1
    ]
    if macro_preserving:
        selected = sorted(
            macro_preserving,
            key=lambda result: (
                -float(result["validation"]["not_relevant_recall"]),
                -float(result["validation"]["macro_f1"]),
                -float(result["validation"]["accuracy"]),
                str(result["configuration"]["configuration_id"]),
            ),
        )[0]
        fallback = "NO_CONFIGURATION_MET_NOT_RELEVANT_CONSTRAINT"
    else:
        selected = sorted(results, key=_selection_sort_key)[0]
        fallback = "NO_CONFIGURATION_MET_MACRO_F1_PRESERVATION_FLOOR"
    return selected, {
        "rule_version": "constrained-not-relevant-recall-v1",
        "primary_constraint": {
            "metric": "validation NOT_RELEVANT recall",
            "minimum": minimum_not_relevant_recall,
        },
        "preservation_constraint": {
            "metric": "validation macro F1",
            "minimum": minimum_macro_f1,
        },
        "optimization": "fallback maximizes NOT_RELEVANT recall among macro-F1-preserving candidates; otherwise maximizes macro F1",
        "selection_path": fallback,
        "eligible_configuration_ids": [],
        "test_set_used": False,
    }


def _candidate_result(fit: CandidateFit, config: DevelopmentProtocolConfig) -> dict[str, Any]:
    validation = fit.compact_validation_metrics
    return {
        "configuration": fit.candidate.model_dump(mode="json"),
        "feature_count": fit.feature_count,
        "train": fit.compact_train_metrics,
        "validation": validation,
        "passes_not_relevant_constraint": (
            float(validation["not_relevant_recall"])
            >= config.minimum_not_relevant_recall
        ),
        "passes_macro_f1_floor": (
            float(validation["macro_f1"]) >= config.minimum_macro_f1
        ),
    }


def _best_weight_result(
    results: Sequence[dict[str, Any]], weight: Literal["NONE", "BALANCED"]
) -> dict[str, Any] | None:
    matching = [
        result
        for result in results
        if result["configuration"]["class_weight"] == weight
    ]
    return sorted(matching, key=_selection_sort_key)[0] if matching else None


def run_controlled_model_selection(
    selection: SelectionDataset,
    *,
    config: DevelopmentProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    candidates: Sequence[DevelopmentCandidate] | None = None,
) -> ModelSelectionResult:
    """Select from train/validation data only; no final-test argument exists."""

    selected_candidates = tuple(candidates or controlled_search_space())
    if not selected_candidates:
        raise ValueError("controlled search space is empty")
    if len(selected_candidates) > 20:
        raise ValueError("controlled search space exceeds the 20-configuration ceiling")
    fits: dict[str, CandidateFit] = {}
    results: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        fit = _fit_candidate(selection, candidate, config)
        fits[candidate.configuration_id] = fit
        results.append(_candidate_result(fit, config))
    selected_result, selection_details = select_result_by_rule(
        results,
        minimum_not_relevant_recall=config.minimum_not_relevant_recall,
        minimum_macro_f1=config.minimum_macro_f1,
    )
    selected_id = str(selected_result["configuration"]["configuration_id"])
    best_none = _best_weight_result(results, "NONE")
    best_balanced = _best_weight_result(results, "BALANCED")

    def weight_summary(result: dict[str, Any] | None) -> dict[str, Any]:
        if result is None:
            return {"status": "NOT_TESTED_IN_SUPPLIED_SEARCH_SPACE"}
        return {
            "status": "EVALUATED",
            "configuration_id": result["configuration"]["configuration_id"],
            "validation": result["validation"],
        }

    class_weight_result = {
        "comparison": {
            "best_none": weight_summary(best_none),
            "best_balanced": weight_summary(best_balanced),
        },
        "selected_class_weight": selected_result["configuration"]["class_weight"],
        "conclusion": (
            "BALANCED_SELECTED_BY_FROZEN_VALIDATION_RULE"
            if selected_result["configuration"]["class_weight"] == "BALANCED"
            else "NONE_SELECTED_BY_FROZEN_VALIDATION_RULE"
        ),
        "automatic_preference_for_balanced": False,
    }
    return ModelSelectionResult(
        selected_fit=fits[selected_id],
        candidate_results=tuple(results),
        selection_details=selection_details,
        class_weight_result=class_weight_result,
    )


def _row_softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    scaled = logits / temperature
    shifted = scaled - np.max(scaled, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _multiclass_brier(probabilities: np.ndarray, label_indexes: np.ndarray) -> float:
    targets = np.zeros_like(probabilities)
    targets[np.arange(len(label_indexes)), label_indexes] = 1.0
    return float(np.mean(np.sum((probabilities - targets) ** 2, axis=1)))


def _reliability(
    probabilities: np.ndarray,
    label_indexes: np.ndarray,
    bins: int,
) -> dict[str, Any]:
    confidences = np.max(probabilities, axis=1)
    predictions = np.argmax(probabilities, axis=1)
    correct = predictions == label_indexes
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, Any]] = []
    expected_calibration_error = 0.0
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
            expected_calibration_error += (count / len(label_indexes)) * gap
        else:
            mean_confidence = None
            empirical_accuracy = None
            gap = None
        rows.append(
            {
                "lower_inclusive": lower,
                "upper_inclusive": upper if index == bins - 1 else None,
                "upper_exclusive": upper if index < bins - 1 else None,
                "sample_count": count,
                "mean_confidence": mean_confidence,
                "empirical_accuracy": empirical_accuracy,
                "absolute_gap": gap,
            }
        )
    return {
        "bin_count": bins,
        "expected_calibration_error": float(expected_calibration_error),
        "bins": rows,
    }


def evaluate_validation_calibration(
    fit: CandidateFit,
    validation_labels: Sequence[str],
    validation_split_sha256: str,
    *,
    bins: int,
) -> tuple[NLPCalibrationState, dict[str, Any]]:
    """Fit scalar temperature using validation logits only."""

    from scipy.optimize import minimize_scalar
    from sklearn.metrics import log_loss

    classes = [str(value) for value in fit.classifier.classes_]
    class_indexes = {label: index for index, label in enumerate(classes)}
    try:
        label_indexes = np.asarray(
            [class_indexes[label] for label in validation_labels], dtype=np.int64
        )
    except KeyError as error:
        raise ValueError(f"validation label absent from fitted classes: {error}") from error
    logits = fit.validation_logits
    before_probabilities = _row_softmax(logits)
    before_log_loss = float(
        log_loss(label_indexes, before_probabilities, labels=list(range(len(classes))))
    )
    before_brier = _multiclass_brier(before_probabilities, label_indexes)
    before_reliability = _reliability(before_probabilities, label_indexes, bins)

    def objective(temperature: float) -> float:
        probabilities = _row_softmax(logits, float(temperature))
        return float(
            log_loss(label_indexes, probabilities, labels=list(range(len(classes))))
        )

    optimization = minimize_scalar(
        objective,
        bounds=(0.25, 4.0),
        method="bounded",
        options={"xatol": 1e-8},
    )
    temperature = float(optimization.x)
    after_probabilities = _row_softmax(logits, temperature)
    after_log_loss = objective(temperature)
    after_brier = _multiclass_brier(after_probabilities, label_indexes)
    after_reliability = _reliability(after_probabilities, label_indexes, bins)
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
            validation_ece_before=before_reliability[
                "expected_calibration_error"
            ],
            validation_ece_after=after_reliability[
                "expected_calibration_error"
            ],
        )
        status = "CALIBRATED_ON_VALIDATION"
    else:
        state = NLPCalibrationState()
        status = "NOT_CALIBRATED"
    report = {
        "schema_version": "1.0",
        "evaluation_scope": "VALIDATION_ONLY",
        "status": status,
        "production_calibration": "NOT_VALIDATED",
        "candidate_method": "scalar temperature scaling",
        "selected_method": state.method,
        "temperature": state.temperature,
        "optimization": {
            "success": bool(optimization.success),
            "message": str(optimization.message),
            "bounds": [0.25, 4.0],
            "objective": "multiclass log loss",
        },
        "validation_split_sha256": validation_split_sha256,
        "metrics": {
            "log_loss_before": before_log_loss,
            "log_loss_after_candidate": after_log_loss,
            "multiclass_brier_before": before_brier,
            "multiclass_brier_after_candidate": after_brier,
        },
        "reliability_before": before_reliability,
        "reliability_after_candidate": after_reliability,
        "label_predictions_unchanged": True,
        "limitations": [
            "Calibration was fitted and measured on the same small validation split.",
            "This is development evidence and not field or production calibration.",
        ],
    }
    return state, report


def _full_selected_reports(
    selection: SelectionDataset,
    fit: CandidateFit,
    config: DevelopmentProtocolConfig,
) -> tuple[NlpEvaluationReport, NlpEvaluationReport]:
    classes = [str(value) for value in fit.classifier.classes_]
    train_records = selection.train_records
    validation_records = selection.validation_records
    train_report = evaluate_nlp_predictions(
        [str(record.event_type) for record in train_records],
        fit.train_predictions,
        classes,
        record_ids=[record.record_id for record in train_records],
        texts=[record.text for record in train_records],
        languages=[record.language or "unknown" for record in train_records],
        minimum_subgroup_rows=config.minimum_subgroup_rows,
        expected_languages=("en", "hi", "hinglish"),
    )
    validation_report = evaluate_nlp_predictions(
        [str(record.event_type) for record in validation_records],
        fit.validation_predictions,
        classes,
        record_ids=[record.record_id for record in validation_records],
        texts=[record.text for record in validation_records],
        languages=[record.language or "unknown" for record in validation_records],
        minimum_subgroup_rows=config.minimum_subgroup_rows,
        expected_languages=("en", "hi", "hinglish"),
    )
    return train_report, validation_report


def _frozen_space(
    vectorizer: Any,
    analyzer: Literal["char", "word"],
    ngram_range: tuple[int, int],
) -> FrozenTfidfSpace:
    return FrozenTfidfSpace(
        analyzer=analyzer,
        ngram_range=ngram_range,
        vocabulary={
            term: int(index) for term, index in vectorizer.vocabulary_.items()
        },
        idf=[float(value) for value in vectorizer.idf_],
        vectorizer_config={
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
            "token_pattern": r"(?u)\b\w+\b" if analyzer == "word" else None,
            "local_only": True,
        },
    )


def _library_versions() -> dict[str, str]:
    import scipy
    import sklearn

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


def _create_artifact(
    prepared: PreparedDevelopmentData,
    selection_result: ModelSelectionResult,
    calibration_state: NLPCalibrationState,
    config: DevelopmentProtocolConfig,
    created_at: datetime,
) -> NLPClassifierArtifact:
    fit = selection_result.selected_fit
    candidate = fit.candidate
    versions = _library_versions()
    classes = [str(value) for value in fit.classifier.classes_]
    return NLPClassifierArtifact(
        artifact_version="nlp-classifier-artifact-v2",
        model_version=config.model_version,
        model_status="DEVELOPMENT_ONLY_FROZEN",
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        classes=classes,
        char_space=_frozen_space(
            fit.vectorizers[0], "char", candidate.char_ngram_range
        ),
        word_space=_frozen_space(
            fit.vectorizers[1], "word", candidate.word_ngram_range
        ),
        feature_weights=NLPFeatureWeights(
            character=candidate.character_weight,
            word=candidate.word_weight,
        ),
        classifier=NLPLinearClassifierState(
            regularization_c=candidate.regularization_c,
            max_iterations=config.max_iterations,
            random_state=config.random_seed,
            solver="lbfgs",
            class_weight=candidate.class_weight,
            classes=classes,
            coefficients=fit.classifier.coef_.tolist(),
            intercept=fit.classifier.intercept_.tolist(),
        ),
        calibration=calibration_state,
        n_features=fit.feature_count,
        provenance={
            "dataset_identifier": prepared.dataset_id,
            "dataset_version": prepared.dataset_version,
            "dataset_sha256": prepared.dataset_sha256,
            "training_split_sha256": prepared.selection.train_sha256,
            "validation_split_sha256": prepared.selection.validation_sha256,
            "final_test_split_sha256": prepared.final_test.split_sha256,
            "split_version": config.split_version,
            "training_timestamp": created_at.isoformat(),
            "dataset_status": "DEVELOPMENT_ONLY / SYNTHETIC / NOT_PRODUCTION_VALIDATED",
            "python_version": versions["python"],
            "scikit_learn_version": versions["scikit_learn"],
            "numpy_version": versions["numpy"],
            "random_state": config.random_seed,
            "classifier_configuration": {
                **candidate.model_dump(mode="json"),
                "max_iterations": config.max_iterations,
                "solver": "lbfgs",
                "selection_rule_version": selection_result.selection_details[
                    "rule_version"
                ],
                "calibration_method": calibration_state.method,
            },
            "class_distribution": _distribution(
                prepared.selection.train_records, "event_type"
            ),
        },
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _register_development_artifact(
    artifact_path: Path,
    artifact: NLPClassifierArtifact,
    manifest_path: Path,
) -> None:
    versions = _library_versions()
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=artifact.model_version,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=artifact.provenance.dataset_sha256,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        training_timestamp=artifact.provenance.training_timestamp,
        random_seed=artifact.provenance.random_state,
        framework_versions=versions,
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


def _require_absent(paths: Sequence[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Phase 14 freeze is immutable; refusing to overwrite: " + ", ".join(existing)
        )


def freeze_nlp_development_model(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    split_path: Path | str = DEFAULT_SPLIT_PATH,
    search_path: Path | str = DEFAULT_SEARCH_PATH,
    validation_errors_path: Path | str = DEFAULT_VALIDATION_ERRORS_PATH,
    calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    config: DevelopmentProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Select, calibrate, serialize, and freeze without final-test inference."""

    artifact_path = local_only_path(artifact_path, description="NLP artifacts")
    development_manifest_path = local_only_path(
        development_manifest_path, description="development manifests"
    )
    split_path = local_only_path(split_path, description="development split files")
    search_path = local_only_path(search_path, description="development search files")
    validation_errors_path = local_only_path(
        validation_errors_path, description="validation error reports"
    )
    calibration_path = local_only_path(
        calibration_path, description="calibration reports"
    )
    artifact_manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    )
    _require_absent(
        (
            artifact_path,
            development_manifest_path,
            split_path,
            search_path,
            validation_errors_path,
            calibration_path,
        )
    )
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("creation timestamp must include a timezone")

    prepared = prepare_registered_development_data(
        registry_path=registry_path,
        config=config,
    )
    selection_result = run_controlled_model_selection(
        prepared.selection,
        config=config,
    )
    fit = selection_result.selected_fit
    train_report, validation_report = _full_selected_reports(
        prepared.selection,
        fit,
        config,
    )
    calibration_state, calibration_report = evaluate_validation_calibration(
        fit,
        [str(record.event_type) for record in prepared.selection.validation_records],
        prepared.selection.validation_sha256,
        bins=config.calibration_bins,
    )
    artifact = _create_artifact(
        prepared,
        selection_result,
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
    artifact_hash = file_sha256(artifact_path)
    selected_configuration = fit.candidate.model_dump(mode="json")
    baseline_result = next(
        result
        for result in selection_result.candidate_results
        if result["configuration"]["configuration_id"] == "A_EQUAL_NONE_C1"
    )
    selected_result = next(
        result
        for result in selection_result.candidate_results
        if result["configuration"]["configuration_id"]
        == selected_configuration["configuration_id"]
    )
    same_protocol_comparison = {
        "comparison_status": "VALID_SAME_SPLIT_RECREATION",
        "previous_configuration_proxy": "A_EQUAL_NONE_C1",
        "note": (
            "The committed v1 model used all 210 development rows, so it cannot "
            "be evaluated on this derived validation split without leakage. Its "
            "feature/classifier configuration was therefore recreated on the "
            "Phase 14 train split for the valid validation comparison."
        ),
        "previous_configuration_validation": baseline_result["validation"],
        "selected_configuration_validation": selected_result["validation"],
    }
    search_report = {
        "schema_version": "1.0",
        "protocol_version": config.protocol_version,
        "search_scope": "DEVELOPMENT_TRAIN_AND_VALIDATION_ONLY",
        "configuration_count": len(selection_result.candidate_results),
        "configurations": list(selection_result.candidate_results),
        "selection_rule": selection_result.selection_details,
        "selected_configuration_id": selected_configuration["configuration_id"],
        "class_weight_result": selection_result.class_weight_result,
        "same_protocol_previous_configuration_comparison": same_protocol_comparison,
        "final_test_accessed": False,
    }
    validation_errors = {
        "schema_version": "1.0",
        "report_scope": "VALIDATION_ONLY",
        "split_sha256": prepared.selection.validation_sha256,
        "selected_configuration_id": selected_configuration["configuration_id"],
        **validation_report.error_analysis,
    }
    validation_errors["report_sha256"] = _canonical_hash(validation_errors)

    frozen_configuration = {
        "preprocessing_version": config.preprocessing_version,
        "feature_version": config.feature_version,
        "feature_configuration": {
            "character_tfidf_ngram_range": selected_configuration[
                "char_ngram_range"
            ],
            "word_tfidf_ngram_range": selected_configuration["word_ngram_range"],
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
        },
        "feature_weights": {
            "character": selected_configuration["character_weight"],
            "word": selected_configuration["word_weight"],
        },
        "classifier": {
            "kind": "logistic_regression",
            "solver": "lbfgs",
            "regularization_c": selected_configuration["regularization_c"],
            "class_weight": selected_configuration["class_weight"],
            "max_iterations": config.max_iterations,
        },
        "calibration": calibration_state.model_dump(mode="json"),
        "random_seed": config.random_seed,
        "split_version": config.split_version,
        "split_definition_sha256": prepared.split_manifest[
            "split_definition_sha256"
        ],
    }
    frozen_configuration_hash = _canonical_hash(frozen_configuration)
    development_manifest = {
        "schema_version": "1.0",
        "protocol_version": config.protocol_version,
        "status": "FROZEN_FOR_FINAL_TEST",
        "development_only": True,
        "production_status": "NOT_PRODUCTION_READY",
        "production_validation": "NOT_VALIDATED",
        "created_at": timestamp.isoformat(),
        "dataset": {
            "dataset_id": prepared.dataset_id,
            "dataset_version": prepared.dataset_version,
            "dataset_sha256": prepared.dataset_sha256,
            "registry_path": str(Path(registry_path).resolve()),
            "classification": "DEVELOPMENT_ONLY",
            "synthetic": True,
        },
        "split": prepared.split_manifest,
        "selection_rule": selection_result.selection_details,
        "selected_configuration": selected_configuration,
        "selected_validation_metrics": validation_report.model_dump(mode="json"),
        "selected_train_metrics": train_report.model_dump(mode="json"),
        "multilingual_train": train_report.subgroup_metrics,
        "multilingual_validation": validation_report.subgroup_metrics,
        "class_weight_result": selection_result.class_weight_result,
        "same_protocol_previous_configuration_comparison": (
            same_protocol_comparison
        ),
        "calibration": calibration_report,
        "frozen_configuration": frozen_configuration,
        "frozen_configuration_sha256": frozen_configuration_hash,
        "artifact": {
            "path": str(artifact_path.resolve()),
            "artifact_name": artifact_path.name,
            "artifact_version": artifact.artifact_version,
            "model_version": artifact.model_version,
            "sha256": artifact_hash,
            "creation_timestamp": timestamp.isoformat(),
            "library_versions": _library_versions(),
        },
        "validation_error_report": {
            "path": str(validation_errors_path.resolve()),
            "sha256": validation_errors["report_sha256"],
        },
        "final_test": {
            "status": "NOT_ACCESSED_FOR_EVALUATION",
            "required_evaluation_label": "FINAL_UNTOUCHED_TEST_EVALUATION",
            "sample_count": prepared.final_test.sample_count,
            "split_sha256": prepared.final_test.split_sha256,
            "source_order_sha256": prepared.final_test.source_order_sha256,
            "configuration_changes_permitted_after_freeze": False,
        },
        "policy": {
            "local_libraries_only": True,
            "runtime_downloads": False,
            "external_inference": False,
            "live_backend_modified": False,
        },
        "known_limitations": [
            "The 300-row corpus is synthetic and has no incident grouping field.",
            "The validation split is small, especially for Hindi and Hinglish.",
            "Calibration uses the same validation split used for configuration selection.",
            "No independent real-world or multilingual field validation exists.",
        ],
    }

    _write_json(split_path, prepared.split_manifest)
    _write_json(search_path, search_report)
    _write_json(validation_errors_path, validation_errors)
    _write_json(calibration_path, calibration_report)
    _register_development_artifact(
        artifact_path,
        artifact,
        artifact_manifest_path,
    )
    _write_json(development_manifest_path, development_manifest)
    return {
        "status": "FROZEN_FOR_FINAL_TEST",
        "artifact_path": str(artifact_path),
        "development_manifest_path": str(development_manifest_path),
        "artifact_sha256": artifact_hash,
        "frozen_configuration_sha256": frozen_configuration_hash,
        "selected_configuration_id": selected_configuration["configuration_id"],
        "validation": _compact_metrics(validation_report),
        "calibration_status": calibration_state.status,
        "final_test_accessed": False,
    }


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
        "evaluation_label": "FINAL_UNTOUCHED_TEST_EVALUATION",
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
            "final evaluation was already claimed; a second access is prohibited"
        ) from error


def _load_protected_final_test_once(
    dataset_path: Path,
    descriptor: Mapping[str, Any],
) -> list[DatasetRecord]:
    records = load_csv(dataset_path)
    final_test = [record for record in records if record.split is DatasetSplit.TEST]
    expected_ids = tuple(descriptor["record_ids"])
    actual_ids = tuple(record.record_id for record in final_test)
    if actual_ids != expected_ids:
        raise ValueError("protected final-test source order or identifiers changed")
    if canonical_record_hash(final_test) != descriptor["split_sha256"]:
        raise ValueError("protected final-test content hash changed")
    if _source_order_hash(final_test) != descriptor["source_order_sha256"]:
        raise ValueError("protected final-test order hash changed")
    return final_test


def _historical_reference(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    test = payload["test"]
    return {
        "status": "HISTORICAL_TEST_REFERENCE_ONLY / NOT_USED_FOR_SELECTION",
        "model_version": payload["model_version"],
        "protocol_compatibility": "NOT_DIRECTLY_COMPARABLE",
        "reason": (
            "The previous model trained on all 210 development rows and had no "
            "independent Phase 14 validation split."
        ),
        "accuracy": test["accuracy"],
        "macro_precision": test["macro_precision"],
        "macro_recall": test["macro_recall"],
        "macro_f1": test["macro_f1"],
        "not_relevant_recall": test["not_relevant_recall"],
    }


def finalize_frozen_nlp_evaluation(
    *,
    registry_path: Path | str | None = None,
    development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    metrics_path: Path | str = DEFAULT_METRICS_PATH,
    receipt_path: Path | str = DEFAULT_FINAL_RECEIPT_PATH,
    historical_metrics_path: Path | str = DEFAULT_HISTORICAL_METRICS_PATH,
    config: DevelopmentProtocolConfig = DEFAULT_PROTOCOL_CONFIG,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Claim and execute exactly one evaluation of the already-frozen model."""

    development_manifest_path = local_only_path(
        development_manifest_path, description="development manifests"
    )
    artifact_path = local_only_path(artifact_path, description="NLP artifacts")
    artifact_manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    )
    metrics_path = local_only_path(metrics_path, description="NLP metric files")
    receipt_path = local_only_path(receipt_path, description="final evaluation receipts")
    historical_metrics_path = local_only_path(
        historical_metrics_path, description="historical NLP metric files"
    )
    if metrics_path.exists():
        raise RuntimeError("final metrics already exist; reevaluation is prohibited")
    if not development_manifest_path.is_file():
        raise ValueError("frozen development manifest is unavailable")
    development_manifest_bytes = development_manifest_path.read_bytes()
    development_manifest_hash = _sha256_bytes(development_manifest_bytes)
    development_manifest = json.loads(development_manifest_bytes.decode("utf-8"))
    if development_manifest.get("status") != "FROZEN_FOR_FINAL_TEST":
        raise ValueError("development model is not frozen for final evaluation")
    artifact = load_nlp_artifact(
        artifact_path,
        manifest_path=artifact_manifest_path,
    )
    artifact_hash = file_sha256(artifact_path)
    if artifact_hash != development_manifest["artifact"]["sha256"]:
        raise ValueError("frozen artifact hash differs from development manifest")
    selected_registry_path = local_only_path(
        registry_path or development_manifest["dataset"]["registry_path"],
        description="dataset registries",
    )
    dataset_path = resolve_registry_path(
        find_dataset(
            load_dataset_registry(selected_registry_path),
            development_manifest["dataset"]["dataset_id"],
            development_manifest["dataset"]["dataset_version"],
        ).local_path,
        selected_registry_path,
    )
    if file_sha256(dataset_path) != development_manifest["dataset"]["dataset_sha256"]:
        raise ValueError("dataset changed after model freeze")

    timestamp = evaluated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("evaluation timestamp must include a timezone")
    _claim_final_evaluation(
        receipt_path,
        development_manifest_sha256=development_manifest_hash,
        artifact_sha256=artifact_hash,
        claimed_at=timestamp,
    )
    try:
        descriptor = {
            "record_ids": development_manifest["split"][
                "final_test_record_ids_in_source_order"
            ],
            "split_sha256": development_manifest["final_test"]["split_sha256"],
            "source_order_sha256": development_manifest["final_test"][
                "source_order_sha256"
            ],
        }
        final_test = _load_protected_final_test_once(dataset_path, descriptor)
        selected = development_manifest["selected_configuration"]
        inference_config = NLPClassifierConfig(
            model_version=artifact.model_version,
            feature_version=artifact.feature_version,
            preprocessing_version=artifact.preprocessing_version,
            dataset_path=dataset_path,
            artifact_path=artifact_path,
            metrics_path=metrics_path,
            char_ngram_range=tuple(selected["char_ngram_range"]),
            word_ngram_range=tuple(selected["word_ngram_range"]),
            regularization_grid=(selected["regularization_c"],),
            regularization_c=selected["regularization_c"],
            max_iterations=artifact.classifier.max_iterations,
            random_state=artifact.classifier.random_state,
            minimum_subgroup_rows=config.minimum_subgroup_rows,
        )
        classifier = NLPClassifier(
            inference_config,
            artifact_path=artifact_path,
            manifest_path=artifact_manifest_path,
        )
        inference_outputs = [classifier.predict(record.text) for record in final_test]
        unavailable = [
            record.record_id
            for record, output in zip(final_test, inference_outputs)
            if output.label is None
        ]
        if unavailable:
            raise RuntimeError(f"frozen artifact failed final inference: {unavailable}")
        predictions = [str(output.label) for output in inference_outputs]
        labels = [str(record.event_type) for record in final_test]
        evaluation = evaluate_nlp_predictions(
            labels,
            predictions,
            artifact.classes,
            record_ids=[record.record_id for record in final_test],
            texts=[record.text for record in final_test],
            languages=[record.language or "unknown" for record in final_test],
            minimum_subgroup_rows=config.minimum_subgroup_rows,
            expected_languages=("en", "hi", "hinglish"),
        )
        flood_to_not_relevant = sum(
            truth in FLOOD_CLASSES and prediction == "NOT_RELEVANT"
            for truth, prediction in zip(labels, predictions)
        )
        acceptance_gate = {
            "macro_f1": {
                "value": evaluation.macro_f1,
                "minimum": config.minimum_macro_f1,
                "pass": evaluation.macro_f1 is not None
                and evaluation.macro_f1 >= config.minimum_macro_f1,
            },
            "not_relevant_recall": {
                "value": evaluation.not_relevant_recall,
                "minimum": config.minimum_not_relevant_recall,
                "pass": evaluation.not_relevant_recall is not None
                and evaluation.not_relevant_recall
                >= config.minimum_not_relevant_recall,
            },
            "flood_to_not_relevant_errors": {
                "value": flood_to_not_relevant,
                "maximum": config.maximum_flood_to_not_relevant_errors,
                "pass": flood_to_not_relevant
                <= config.maximum_flood_to_not_relevant_errors,
            },
        }
        accepted = all(item["pass"] for item in acceptance_gate.values())
        result_status = "DEVELOPMENT_ACCEPTED" if accepted else "DEVELOPMENT_GATE_FAILED"
        metrics = {
            "schema_version": "1.0",
            "evaluation_label": "FINAL_UNTOUCHED_TEST_EVALUATION",
            "evaluation_timestamp": timestamp.isoformat(),
            "evaluation_invocation_count": 1,
            "model_version": artifact.model_version,
            "model_status": "DEVELOPMENT_ONLY",
            "dataset_id": development_manifest["dataset"]["dataset_id"],
            "dataset_version": development_manifest["dataset"]["dataset_version"],
            "dataset_sha256": development_manifest["dataset"]["dataset_sha256"],
            "train_split_sha256": development_manifest["split"]["train_sha256"],
            "validation_split_sha256": development_manifest["split"][
                "validation_sha256"
            ],
            "final_test_split_sha256": development_manifest["final_test"][
                "split_sha256"
            ],
            "artifact_sha256": artifact_hash,
            "development_manifest_sha256": development_manifest_hash,
            "frozen_configuration_sha256": development_manifest[
                "frozen_configuration_sha256"
            ],
            "n_train": development_manifest["split"]["train_count"],
            "n_validation": development_manifest["split"]["validation_count"],
            "n_test": len(final_test),
            "selected_configuration": selected,
            "selection_rule": development_manifest["selection_rule"],
            "validation": {
                key: development_manifest["selected_validation_metrics"][key]
                for key in (
                    "sample_count",
                    "accuracy",
                    "macro_precision",
                    "macro_recall",
                    "macro_f1",
                    "not_relevant_recall",
                    "confusion_matrix",
                    "subgroup_metrics",
                )
            },
            "calibration": development_manifest["calibration"],
            "test": evaluation.model_dump(mode="json"),
            "flood_to_not_relevant_errors": flood_to_not_relevant,
            "acceptance_gate": acceptance_gate,
            "development_acceptance": {
                "accepted": accepted,
                "status": result_status,
            },
            "comparison": {
                "valid_phase14_validation": development_manifest[
                    "same_protocol_previous_configuration_comparison"
                ],
                "historical_v1_test_reference": _historical_reference(
                    historical_metrics_path
                ),
            },
            "production_validation": "NOT_VALIDATED",
            "production_status": "NOT_PRODUCTION_READY",
            "retraining_after_final_test": False,
        }
        _write_json(metrics_path, metrics)
        completed_receipt = {
            "schema_version": "1.0",
            "status": "COMPLETED",
            "evaluation_label": "FINAL_UNTOUCHED_TEST_EVALUATION",
            "claimed_at": timestamp.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "test_examples_available_to_configuration_selection": False,
            "configuration_changed_after_freeze": False,
            "retrained_after_evaluation": False,
            "development_manifest_sha256": development_manifest_hash,
            "frozen_configuration_sha256": development_manifest[
                "frozen_configuration_sha256"
            ],
            "artifact_sha256": artifact_hash,
            "final_test_split_sha256": descriptor["split_sha256"],
            "metrics_sha256": file_sha256(metrics_path),
            "development_acceptance": result_status,
            "production_validation": "NOT_VALIDATED",
        }
        _write_json(receipt_path, completed_receipt)
        return metrics
    except Exception as error:
        failed_receipt = {
            "schema_version": "1.0",
            "status": "FAILED_AFTER_CLAIM",
            "evaluation_label": "FINAL_UNTOUCHED_TEST_EVALUATION",
            "claimed_at": timestamp.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "error_type": type(error).__name__,
            "error": str(error),
            "development_manifest_sha256": development_manifest_hash,
            "artifact_sha256": artifact_hash,
        }
        _write_json(receipt_path, failed_receipt)
        raise


def _paths_from_output_directory(output_directory: Path) -> dict[str, Path]:
    return {
        "artifact_path": output_directory / DEFAULT_ARTIFACT_PATH.name,
        "development_manifest_path": output_directory
        / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "split_path": output_directory / DEFAULT_SPLIT_PATH.name,
        "search_path": output_directory / DEFAULT_SEARCH_PATH.name,
        "validation_errors_path": output_directory
        / DEFAULT_VALIDATION_ERRORS_PATH.name,
        "calibration_path": output_directory / DEFAULT_CALIBRATION_PATH.name,
        "metrics_path": output_directory / DEFAULT_METRICS_PATH.name,
        "receipt_path": output_directory / DEFAULT_FINAL_RECEIPT_PATH.name,
        "artifact_manifest_path": output_directory / "manifest.json",
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Freeze or finalize the Phase 14 NLP development model"
    )
    parser.add_argument("action", choices=("freeze", "finalize"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--output-directory", type=Path, default=ARTIFACT_ROOT)
    args = parser.parse_args(argv)
    paths = _paths_from_output_directory(args.output_directory)
    if args.action == "freeze":
        result = freeze_nlp_development_model(
            registry_path=args.registry,
            artifact_path=paths["artifact_path"],
            development_manifest_path=paths["development_manifest_path"],
            split_path=paths["split_path"],
            search_path=paths["search_path"],
            validation_errors_path=paths["validation_errors_path"],
            calibration_path=paths["calibration_path"],
            artifact_manifest_path=paths["artifact_manifest_path"],
        )
    else:
        result = finalize_frozen_nlp_evaluation(
            registry_path=args.registry,
            development_manifest_path=paths["development_manifest_path"],
            artifact_path=paths["artifact_path"],
            artifact_manifest_path=paths["artifact_manifest_path"],
            metrics_path=paths["metrics_path"],
            receipt_path=paths["receipt_path"],
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
