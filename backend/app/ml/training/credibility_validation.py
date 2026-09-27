"""Phase 21 synthetic-only credibility-risk model validation.

This module is deliberately outside the live inference path.  It consumes the
existing credibility feature snapshot, evaluates the existing deterministic
baseline, fits an interpretable local logistic-regression development model,
and enforces a one-shot protected synthetic test protocol.  The target is
``MISLEADING_RISK_EVIDENCE``; no output is a truth probability.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Final, Literal

import numpy as np
import pydantic
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.linear_model import LogisticRegression

from app.ml.components.credibility_features import extract_credibility_features
from app.ml.components.fake_detection import (
    RULE_BASED_CREDIBILITY_BASELINE,
    assess_credibility_risk,
)
from app.ml.config import file_sha256, local_only_path
from app.ml.contracts import (
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    CredibilityFeatureSnapshot,
    CredibilityRiskLevel,
)
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
from app.ml.data.synthetic_credibility.generator import (
    CREDIBILITY_SCENARIOS,
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_VERSION,
    DEFAULT_SEED,
    FORBIDDEN_DETECTOR_FIELDS,
    GENERATOR_VERSION,
    LANGUAGES,
    SCENARIO_VERSION,
    SPLIT_VERSION,
    SPLITS,
    TEMPLATE_VERSION,
    SyntheticCredibilityDetectorInput,
    SyntheticCredibilityGroundTruth,
    SyntheticCredibilityQualityReport,
)
from app.ml.training.dataset_gate import evaluate_training_dataset

ARTIFACT_VERSION: Final[str] = "credibility-v1-synthetic-development"
FEATURE_VERSION: Final[str] = "credibility-risk-features-v1"
PREPROCESSING_VERSION: Final[str] = "credibility-v1-feature-standardization-v1"
CALIBRATION_VERSION: Final[str] = "credibility-v1-validation-temperature-v1"
THRESHOLD_VERSION: Final[str] = "credibility-v1-abstention-thresholds-v1"
DEVELOPMENT_STATUS: Final[str] = "DEVELOPMENT_ONLY_SYNTHETIC"
PRODUCTION_VALIDATION: Final[str] = "NOT_VALIDATED"
SEMANTIC_TARGET: Final[str] = "MISLEADING_RISK_EVIDENCE"
FREEZE_TIMESTAMP: Final[datetime] = datetime(2026, 9, 24, 4, 0, tzinfo=timezone.utc)
FINAL_EVALUATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 24, 5, 0, tzinfo=timezone.utc
)

ARTIFACT_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "artifacts"
DEFAULT_ARTIFACT_PATH: Final[Path] = ARTIFACT_ROOT / "credibility_v1.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.development_manifest.json"
)
DEFAULT_SEARCH_PATH: Final[Path] = ARTIFACT_ROOT / "credibility_v1.search.json"
DEFAULT_CALIBRATION_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.calibration.json"
)
DEFAULT_ABLATION_PATH: Final[Path] = ARTIFACT_ROOT / "credibility_v1.ablation.json"
DEFAULT_BASELINE_VALIDATION_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.baseline_validation.json"
)
DEFAULT_VALIDATION_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.validation_metrics.json"
)
DEFAULT_VALIDATION_ERRORS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.validation_errors.json"
)
DEFAULT_PERFORMANCE_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.performance.json"
)
DEFAULT_GOLDEN_PATH: Final[Path] = ARTIFACT_ROOT / "credibility_v1.golden.json"
DEFAULT_FINAL_METRICS_PATH: Final[Path] = ARTIFACT_ROOT / "credibility_v1.metrics.json"
DEFAULT_ERROR_REPORT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1.error_report.json"
)
DEFAULT_FINAL_RECEIPT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "credibility_v1_final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH: Final[Path] = ARTIFACT_ROOT / "manifest.json"

LABELS: Final[tuple[str, ...]] = ("AUTHENTIC", "MISLEADING", "UNCERTAIN")
RESOLVED_LABELS: Final[tuple[str, ...]] = ("AUTHENTIC", "MISLEADING")
VALIDATION_ROLES: Final[tuple[str, ...]] = (
    "model_selection",
    "calibration",
    "threshold_selection",
)
EXPECTED_FROZEN_CORE_HASHES: Final[dict[str, str]] = {
    "nlp_classifier_v3.json": "7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca",
    "nlp_classifier_v3.final_test_receipt.json": "ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b",
    "duplicate_feature_state_v2.json": "d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731",
    "duplicate_matcher_v1.json": "85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b",
    "duplicate_v1_final_test_receipt.json": "4b97fa5b617c0bf2c93383a8d031be5a9fd6dcd5c08c9b2c229cec9d57ead405",
    "event_grouping_v1.json": "10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973",
    "event_grouping_v1_final_test_receipt.json": "c6ae828fc435275f031175f47500beccada675fb5ad7bd5559c6de8c58e1d913",
}


class CredibilityValidationBlocked(ValueError):
    """Raised when the governed Phase 21 protocol must fail closed."""


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _artifact_payload_hash(payload: Mapping[str, Any]) -> str:
    selected = dict(payload)
    selected.pop("artifact_hash", None)
    return _sha256_payload(selected)


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 10)


class CredibilityDevelopmentArtifact(BaseModel):
    """Portable local linear model plus frozen governance and preprocessing."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_version: str
    artifact_kind: Literal["INTERPRETABLE_LOCAL_LOGISTIC_REGRESSION"]
    development_status: str
    production_validation: str
    semantic_target: Literal["MISLEADING_RISK_EVIDENCE"]
    prohibited_interpretation: Literal["TRUTH_PROBABILITY"]
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    scenario_version: str
    split_version: str
    template_version: str
    feature_version: str
    preprocessing_version: str
    model_classes: list[str]
    output_labels: list[str]
    base_feature_names: list[str]
    feature_names: list[str]
    feature_families: dict[str, list[str]]
    transformations: dict[str, str]
    medians: list[float]
    means: list[float]
    scales: list[float]
    coefficients: list[float]
    intercept: float
    selected_configuration: dict[str, Any]
    calibration: dict[str, Any]
    thresholds: dict[str, float]
    decision_logic: str
    selection_split: str
    calibration_split: str
    threshold_selection_split: str
    test_rows_accessed_for_selection: bool
    frozen_at: datetime
    random_seed: int
    library_versions: dict[str, str]
    policy: dict[str, Any]
    artifact_hash_scope: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_governance(self) -> CredibilityDevelopmentArtifact:
        if self.development_status != DEVELOPMENT_STATUS:
            raise ValueError("unexpected credibility development status")
        if self.production_validation != PRODUCTION_VALIDATION:
            raise ValueError("synthetic evidence cannot claim production validation")
        if self.model_classes != list(RESOLVED_LABELS):
            raise ValueError("UNCERTAIN must not be a fitted target class")
        if self.output_labels != list(LABELS):
            raise ValueError("credibility output taxonomy mismatch")
        if self.test_rows_accessed_for_selection:
            raise ValueError("protected test rows cannot be used for model selection")
        if self.selection_split != "validation:model_selection":
            raise ValueError("model selection must use its validation partition")
        if self.calibration_split != "validation:calibration":
            raise ValueError("calibration must use its validation partition")
        if self.threshold_selection_split != "validation:threshold_selection":
            raise ValueError("thresholds must use their validation partition")
        if not (
            0.0
            < self.thresholds.get("authentic_max_probability", 0.0)
            < self.thresholds.get("misleading_min_probability", 0.0)
            < 1.0
        ):
            raise ValueError("abstention thresholds must be ordered inside (0, 1)")
        length = len(self.feature_names)
        if len(self.medians) != len(self.base_feature_names) or not all(
            len(values) == length
            for values in (self.means, self.scales, self.coefficients)
        ):
            raise ValueError("preprocessing and coefficient dimensions disagree")
        if any(value <= 0.0 for value in self.scales):
            raise ValueError("all feature scales must be positive")
        if self.calibration.get("fit_source") != "VALIDATION_ONLY":
            raise ValueError("calibration source must remain validation-only")
        if self.policy.get("network_access") is not False:
            raise ValueError("network access must remain disabled")
        for key in ("pretrained_models", "open_weight_models", "external_apis"):
            if self.policy.get(key) != []:
                raise ValueError(f"{key} must remain empty")
        expected = _artifact_payload_hash(self.model_dump(mode="json"))
        if self.artifact_hash != expected:
            raise ValueError("credibility artifact_hash does not match payload")
        return self


class CredibilityDevelopmentPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["AUTHENTIC", "MISLEADING", "UNCERTAIN"]
    misleading_risk_probability: float = Field(ge=0.0, le=1.0)
    semantic_target: Literal["MISLEADING_RISK_EVIDENCE"] = SEMANTIC_TARGET
    truth_probability: Literal[False] = False
    calibration_source: Literal["VALIDATION_ONLY"] = "VALIDATION_ONLY"
    artifact_version: str
    feature_version: str
    top_feature_contributions: list[dict[str, str | float]] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CredibilityDatasetBinding:
    registry_path: Path
    annotation_path: Path
    ground_truth_paths: dict[str, Path]
    detector_input_paths: dict[str, Path]
    manifest_path: Path
    quality_report_path: Path
    manifest: dict[str, Any]
    quality_report: SyntheticCredibilityQualityReport
    registered_validation_sha256: str
    production_training_gate: dict[str, Any]
    development_gate: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CredibilitySplitData:
    split: str
    report_ids: np.ndarray
    labels: np.ndarray
    scenarios: np.ndarray
    languages: np.ndarray
    family_ids: np.ndarray
    reason_groups: np.ndarray
    snippets: np.ndarray
    validation_roles: np.ndarray
    raw_features: np.ndarray
    baseline_labels: np.ndarray
    baseline_scores: np.ndarray
    feature_extraction_seconds: float

    @property
    def row_count(self) -> int:
        return int(self.labels.shape[0])


class PreprocessorState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_feature_names: list[str]
    feature_names: list[str]
    medians: list[float]
    means: list[float]
    scales: list[float]


class ModelCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configuration_id: str
    regularization_c: float = Field(gt=0.0)
    class_weight: Literal["NONE", "BALANCED"]
    tie_rank: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class FittedCandidate:
    candidate: ModelCandidate
    model: LogisticRegression
    metrics: dict[str, Any]
    fit_seconds: float


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    family: str
    optional: bool
    transformation: Literal["IDENTITY", "LOG1P_NONNEGATIVE", "SIGNED_LOG1P"]


FEATURE_SPECS: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec("text_length", "TEXT", False, "LOG1P_NONNEGATIVE"),
    FeatureSpec("token_count", "TEXT", False, "LOG1P_NONNEGATIVE"),
    FeatureSpec("lexical_diversity", "TEXT", True, "IDENTITY"),
    FeatureSpec("repeated_token_ratio", "TEXT", True, "IDENTITY"),
    FeatureSpec("repeated_phrase_ratio", "TEXT", True, "IDENTITY"),
    FeatureSpec("punctuation_ratio", "TEXT", True, "IDENTITY"),
    FeatureSpec("claim_density", "TEXT", True, "IDENTITY"),
    FeatureSpec("url_count", "TEXT", False, "LOG1P_NONNEGATIVE"),
    FeatureSpec("supplied_phone_count", "METADATA", True, "LOG1P_NONNEGATIVE"),
    FeatureSpec("submission_delay_seconds", "METADATA", True, "SIGNED_LOG1P"),
    FeatureSpec("coordinates_valid", "METADATA", True, "IDENTITY"),
    FeatureSpec("location_consistency", "METADATA", True, "IDENTITY"),
    FeatureSpec("metadata_error_count", "METADATA", False, "LOG1P_NONNEGATIVE"),
    FeatureSpec("duplicate_flag", "DUPLICATE", True, "IDENTITY"),
    FeatureSpec("duplicate_similarity", "DUPLICATE", True, "IDENTITY"),
    FeatureSpec("duplicate_cluster_size", "DUPLICATE", True, "LOG1P_NONNEGATIVE"),
    FeatureSpec("event_type_consistency", "EVENT", True, "IDENTITY"),
    FeatureSpec("source_recent_report_count", "SOURCE", True, "LOG1P_NONNEGATIVE"),
    FeatureSpec("source_recent_duplicate_ratio", "SOURCE", True, "IDENTITY"),
)
BASE_FEATURE_NAMES: Final[tuple[str, ...]] = tuple(spec.name for spec in FEATURE_SPECS)
FEATURE_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    family: tuple(spec.name for spec in FEATURE_SPECS if spec.family == family)
    for family in ("TEXT", "METADATA", "DUPLICATE", "EVENT", "SOURCE")
}
ABLATION_FAMILIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("TEXT", ("TEXT",)),
    ("METADATA", ("METADATA",)),
    ("DUPLICATE", ("DUPLICATE",)),
    ("EVENT", ("EVENT",)),
    ("SOURCE", ("SOURCE",)),
    ("TEXT + METADATA", ("TEXT", "METADATA")),
    ("TEXT + DUPLICATE + EVENT", ("TEXT", "DUPLICATE", "EVENT")),
    ("FULL", ("TEXT", "METADATA", "DUPLICATE", "EVENT", "SOURCE")),
)

CONTROLLED_CANDIDATES: Final[tuple[ModelCandidate, ...]] = tuple(
    ModelCandidate(
        configuration_id=f"LOGREG_C{str(c_value).replace('.', '_')}_{weight}",
        regularization_c=c_value,
        class_weight=weight,  # type: ignore[arg-type]
        tie_rank=index,
    )
    for index, (c_value, weight) in enumerate(
        (
            (0.10, "NONE"),
            (0.10, "BALANCED"),
            (1.00, "NONE"),
            (1.00, "BALANCED"),
            (10.0, "NONE"),
            (10.0, "BALANCED"),
        )
    )
)


def inspect_credibility_dataset_decision(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> dict[str, Any]:
    registry = load_dataset_registry(registry_path)
    human = [
        record
        for record in registry.entries
        if record.component is DatasetComponent.CREDIBILITY
        and record.human_adjudicated
        and record.status
        in {
            DatasetStatus.APPROVED_TRAINING,
            DatasetStatus.APPROVED_VALIDATION,
            DatasetStatus.APPROVED_TEST,
        }
    ]
    synthetic = [
        record
        for record in registry.entries
        if record.component is DatasetComponent.CREDIBILITY
        and record.dataset_id == DEFAULT_DATASET_ID
        and record.dataset_version == DEFAULT_DATASET_VERSION
    ]
    return {
        "human_adjudicated_approved_dataset_count": len(human),
        "selected_source": (
            "HUMAN_ADJUDICATED" if human else "PROJECT_AUTHORED_SYNTHETIC_FALLBACK"
        ),
        "synthetic_fallback_registered": len(synthetic) == 1,
        "production_validation": PRODUCTION_VALIDATION,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return payload


def _resolve_metadata_path(
    value: str,
    registry_path: Path,
) -> Path:
    return resolve_registry_path(value, registry_path).resolve()


def bind_synthetic_credibility_dataset(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> CredibilityDatasetBinding:
    """Verify exact local bytes and the synthetic-only development gate."""

    selected_registry = local_only_path(
        registry_path, description="dataset registries"
    ).resolve()
    registry = load_dataset_registry(selected_registry)
    try:
        record = find_dataset(
            registry,
            DEFAULT_DATASET_ID,
            DEFAULT_DATASET_VERSION,
        )
    except KeyError as error:
        raise CredibilityValidationBlocked("CREDIBILITY_DATASET_NOT_REGISTERED") from error
    blockers: list[str] = []
    if record.component is not DatasetComponent.CREDIBILITY:
        blockers.append("COMPONENT_MISMATCH")
    if record.status is not DatasetStatus.VALID:
        blockers.append("REGISTERED_DATASET_NOT_VALID")
    if record.data_classification is not DatasetClassification.DEVELOPMENT_ONLY:
        blockers.append("CLASSIFICATION_NOT_DEVELOPMENT_ONLY")
    if record.provenance is not DatasetProvenance.PROJECT_AUTHORED:
        blockers.append("PROVENANCE_NOT_PROJECT_AUTHORED")
    if record.human_adjudicated:
        blockers.append("SYNTHETIC_DATASET_MUST_NOT_CLAIM_HUMAN_ADJUDICATION")
    metadata = record.metadata
    expected_metadata = {
        "synthetic": True,
        "synthetic_classification": "SYNTHETIC",
        "semantic_target": SEMANTIC_TARGET,
        "truth_probability_claimed": False,
        "production_validation": PRODUCTION_VALIDATION,
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "split_version": SPLIT_VERSION,
        "template_version": TEMPLATE_VERSION,
        "seed": DEFAULT_SEED,
        "detector_used_for_labels": False,
        "random_row_split": False,
        "network_access": False,
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            blockers.append(f"METADATA_MISMATCH:{key}")
    try:
        annotation_path = resolve_registry_path(record.local_path, selected_registry)
        manifest_path = _resolve_metadata_path(metadata["manifest_path"], selected_registry)
        quality_path = _resolve_metadata_path(
            metadata["quality_report_path"], selected_registry
        )
        ground_truth_paths = {
            split: _resolve_metadata_path(
                metadata["ground_truth_paths"][split], selected_registry
            )
            for split in SPLITS
        }
        detector_input_paths = {
            split: _resolve_metadata_path(
                metadata["detector_input_paths"][split], selected_registry
            )
            for split in SPLITS
        }
    except (KeyError, TypeError, ValueError) as error:
        raise CredibilityValidationBlocked("CREDIBILITY_DATASET_PATH_BINDING_FAILED") from error
    manifest = _read_json(manifest_path)
    quality_report = SyntheticCredibilityQualityReport.model_validate(
        _read_json(quality_path)
    )
    hash_checks = {
        "annotation": file_sha256(annotation_path) == record.content_sha256,
        "annotation_metadata": file_sha256(annotation_path)
        == metadata.get("annotation_hash"),
        "manifest": file_sha256(manifest_path) == metadata.get("manifest_sha256"),
        "quality": file_sha256(quality_path) == metadata.get("quality_report_sha256"),
        "dataset": quality_report.dataset_sha256 == metadata.get("dataset_hash"),
        "split": quality_report.split_sha256 == metadata.get("split_hash"),
    }
    descriptors = manifest.get("split_descriptors", {})
    for split in SPLITS:
        descriptor = descriptors.get(split, {})
        hash_checks[f"truth:{split}"] = (
            file_sha256(ground_truth_paths[split])
            == descriptor.get("ground_truth_sha256")
            == quality_report.file_hashes.get(f"ground_truth_{split}")
        )
        hash_checks[f"input:{split}"] = (
            file_sha256(detector_input_paths[split])
            == descriptor.get("detector_input_sha256")
            == quality_report.file_hashes.get(f"detector_inputs_{split}")
        )
    blockers.extend(f"HASH_BINDING_FAILED:{name}" for name, passed in hash_checks.items() if not passed)
    try:
        registered_validation = load_bound_validation_report(record, selected_registry)
    except Exception as error:
        raise CredibilityValidationBlocked(
            "REGISTERED_VALIDATION_REPORT_BINDING_FAILED"
        ) from error
    if not registered_validation.valid:
        blockers.append("REGISTERED_STRUCTURAL_VALIDATION_FAILED")
    if registered_validation.content_sha256 != record.content_sha256:
        blockers.append("REGISTERED_VALIDATION_CONTENT_HASH_MISMATCH")
    if not quality_report.valid:
        blockers.append("SYNTHETIC_QUALITY_REPORT_INVALID")
    if quality_report.leakage_checks.get("status") != "PASS":
        blockers.append("SYNTHETIC_LEAKAGE_CHECK_FAILED")
    if quality_report.isolation_checks.get("status") != "PASS":
        blockers.append("DETECTOR_INPUT_ISOLATION_FAILED")
    if set(quality_report.scenario_counts) != set(CREDIBILITY_SCENARIOS):
        blockers.append("SCENARIO_COVERAGE_MISMATCH")
    if set(quality_report.language_counts) != set(LANGUAGES):
        blockers.append("MULTILINGUAL_COVERAGE_MISMATCH")

    production_gate = evaluate_training_dataset(
        DEFAULT_DATASET_ID,
        DatasetComponent.CREDIBILITY,
        registry_path=selected_registry,
        dataset_version=DEFAULT_DATASET_VERSION,
        supplied_path=annotation_path,
    )
    if production_gate.allowed:
        blockers.append("PRODUCTION_GATE_MUST_REMAIN_CLOSED_FOR_SYNTHETIC_DATA")
    development_gate = {
        "gate": "PHASE21_PROJECT_SYNTHETIC_DEVELOPMENT_GATE",
        "allowed": not blockers,
        "scope": "DEVELOPMENT_ONLY_SYNTHETIC",
        "requires_registered_valid_bytes": True,
        "requires_project_authored_provenance": True,
        "requires_scenario_identity_ground_truth": True,
        "requires_custom_grouped_leakage_pass": True,
        "requires_detector_input_isolation": True,
        "production_gate_overridden": False,
        "production_gate_allowed": production_gate.allowed,
        "production_gate_reason_codes": production_gate.reason_codes,
        "blockers": sorted(set(blockers)),
    }
    if blockers:
        raise CredibilityValidationBlocked(
            "CREDIBILITY_SYNTHETIC_DEVELOPMENT_GATE_FAILED: "
            + ", ".join(sorted(set(blockers)))
        )
    return CredibilityDatasetBinding(
        registry_path=selected_registry,
        annotation_path=annotation_path.resolve(),
        ground_truth_paths=ground_truth_paths,
        detector_input_paths=detector_input_paths,
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        manifest=manifest,
        quality_report=quality_report,
        registered_validation_sha256=file_sha256(
            resolve_registry_path(record.validation_report_path or "", selected_registry)
        ),
        production_training_gate=production_gate.model_dump(mode="json"),
        development_gate=development_gate,
    )


def _transform_value(spec: FeatureSpec, value: Any) -> float:
    if value is None:
        return math.nan
    if isinstance(value, bool):
        numeric = float(value)
    else:
        numeric = float(value)
    if spec.transformation == "LOG1P_NONNEGATIVE":
        return math.log1p(max(0.0, numeric))
    if spec.transformation == "SIGNED_LOG1P":
        return math.copysign(math.log1p(abs(numeric)), numeric)
    return numeric


def raw_feature_row(snapshot: CredibilityFeatureSnapshot) -> list[float]:
    return [
        _transform_value(spec, getattr(snapshot, spec.name)) for spec in FEATURE_SPECS
    ]


def fit_preprocessor(raw_features: np.ndarray) -> PreprocessorState:
    if raw_features.ndim != 2 or raw_features.shape[1] != len(FEATURE_SPECS):
        raise ValueError("raw credibility feature matrix has unexpected dimensions")
    medians: list[float] = []
    value_columns: list[np.ndarray] = []
    missing_columns: list[np.ndarray] = []
    feature_names = list(BASE_FEATURE_NAMES)
    for index, spec in enumerate(FEATURE_SPECS):
        column = raw_features[:, index].astype(float)
        missing = ~np.isfinite(column)
        finite = column[~missing]
        median_value = float(np.median(finite)) if finite.size else 0.0
        medians.append(median_value)
        value_columns.append(np.where(missing, median_value, column))
        if spec.optional:
            missing_columns.append(missing.astype(float))
            feature_names.append(f"{spec.name}__missing")
    expanded = np.column_stack((*value_columns, *missing_columns))
    means = np.mean(expanded, axis=0)
    scales = np.std(expanded, axis=0)
    scales = np.where(scales <= 1e-12, 1.0, scales)
    return PreprocessorState(
        base_feature_names=list(BASE_FEATURE_NAMES),
        feature_names=feature_names,
        medians=[float(value) for value in medians],
        means=[float(value) for value in means],
        scales=[float(value) for value in scales],
    )


def apply_preprocessor(
    raw_features: np.ndarray,
    state: PreprocessorState,
) -> np.ndarray:
    if state.base_feature_names != list(BASE_FEATURE_NAMES):
        raise ValueError("artifact base feature order does not match implementation")
    values: list[np.ndarray] = []
    missing_columns: list[np.ndarray] = []
    for index, spec in enumerate(FEATURE_SPECS):
        column = raw_features[:, index].astype(float)
        missing = ~np.isfinite(column)
        values.append(np.where(missing, state.medians[index], column))
        if spec.optional:
            missing_columns.append(missing.astype(float))
    expanded = np.column_stack((*values, *missing_columns))
    if expanded.shape[1] != len(state.feature_names):
        raise ValueError("expanded feature dimensions do not match preprocessor")
    return (expanded - np.asarray(state.means)) / np.asarray(state.scales)


def _validation_role(family_id: str) -> str:
    bucket = int(hashlib.sha256(family_id.encode("utf-8")).hexdigest()[:8], 16) % 4
    if bucket in {0, 1}:
        return "model_selection"
    if bucket == 2:
        return "calibration"
    return "threshold_selection"


def _baseline_label(level: CredibilityRiskLevel | None) -> str:
    if level is CredibilityRiskLevel.HIGH:
        return "MISLEADING"
    if level is CredibilityRiskLevel.LOW:
        return "AUTHENTIC"
    return "UNCERTAIN"


def _jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise CredibilityValidationBlocked(
                    f"INVALID_JSONL:{path.name}:{line_number}"
                ) from error
            if not isinstance(payload, dict):
                raise CredibilityValidationBlocked(
                    f"NON_OBJECT_JSONL_ROW:{path.name}:{line_number}"
                )
            yield payload


def load_credibility_split(
    binding: CredibilityDatasetBinding,
    split: Literal["train", "validation", "test"],
) -> CredibilitySplitData:
    """Load one physically isolated split and derive existing features only."""

    descriptor = binding.manifest["split_descriptors"][split]
    if file_sha256(binding.ground_truth_paths[split]) != descriptor["ground_truth_sha256"]:
        raise CredibilityValidationBlocked(f"GROUND_TRUTH_HASH_CHANGED:{split}")
    if file_sha256(binding.detector_input_paths[split]) != descriptor["detector_input_sha256"]:
        raise CredibilityValidationBlocked(f"DETECTOR_INPUT_HASH_CHANGED:{split}")
    report_ids: list[str] = []
    labels: list[str] = []
    scenarios: list[str] = []
    languages: list[str] = []
    family_ids: list[str] = []
    reason_groups: list[str] = []
    snippets: list[str] = []
    validation_roles: list[str] = []
    feature_rows: list[list[float]] = []
    baseline_labels: list[str] = []
    baseline_scores: list[float] = []
    started = perf_counter()
    truth_iterator = _jsonl_rows(binding.ground_truth_paths[split])
    input_iterator = _jsonl_rows(binding.detector_input_paths[split])
    row_count = 0
    while True:
        truth_payload = next(truth_iterator, None)
        input_payload = next(input_iterator, None)
        if truth_payload is None and input_payload is None:
            break
        if truth_payload is None or input_payload is None:
            raise CredibilityValidationBlocked(f"TRUTH_INPUT_COUNT_MISMATCH:{split}")
        if FORBIDDEN_DETECTOR_FIELDS.intersection(input_payload):
            raise CredibilityValidationBlocked(f"HIDDEN_FIELD_IN_DETECTOR_INPUT:{split}")
        truth = SyntheticCredibilityGroundTruth.model_validate(truth_payload)
        detector_input = SyntheticCredibilityDetectorInput.model_validate(input_payload)
        if truth.report_id != detector_input.report_id or truth.split != split:
            raise CredibilityValidationBlocked(f"TRUTH_INPUT_IDENTITY_MISMATCH:{split}")
        risk_input = detector_input.to_risk_input()
        snapshot = extract_credibility_features(risk_input)
        baseline = assess_credibility_risk(risk_input)
        report_ids.append(str(truth.report_id))
        labels.append(truth.ground_truth_label.value)
        scenarios.append(truth.scenario_category)
        languages.append(truth.language)
        family_ids.append(truth.report_family_id)
        reason_groups.append(truth.failure_reason_group)
        snippets.append(detector_input.report_text[:240])
        validation_roles.append(
            _validation_role(truth.report_family_id) if split == "validation" else split
        )
        feature_rows.append(raw_feature_row(snapshot))
        baseline_labels.append(_baseline_label(baseline.risk_level))
        baseline_scores.append(
            float(baseline.risk_score) if baseline.risk_score is not None else math.nan
        )
        row_count += 1
    if row_count != int(descriptor["row_count"]):
        raise CredibilityValidationBlocked(f"SPLIT_ROW_COUNT_MISMATCH:{split}")
    return CredibilitySplitData(
        split=split,
        report_ids=np.asarray(report_ids, dtype=object),
        labels=np.asarray(labels, dtype=object),
        scenarios=np.asarray(scenarios, dtype=object),
        languages=np.asarray(languages, dtype=object),
        family_ids=np.asarray(family_ids, dtype=object),
        reason_groups=np.asarray(reason_groups, dtype=object),
        snippets=np.asarray(snippets, dtype=object),
        validation_roles=np.asarray(validation_roles, dtype=object),
        raw_features=np.asarray(feature_rows, dtype=float),
        baseline_labels=np.asarray(baseline_labels, dtype=object),
        baseline_scores=np.asarray(baseline_scores, dtype=float),
        feature_extraction_seconds=perf_counter() - started,
    )


def _safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def classification_metrics(
    labels: np.ndarray,
    predictions: np.ndarray,
) -> dict[str, Any]:
    if labels.shape != predictions.shape:
        raise ValueError("labels and predictions must have identical shapes")
    per_label: dict[str, dict[str, float | int]] = {}
    confusion: dict[str, dict[str, int]] = {}
    for actual in LABELS:
        confusion[actual] = {
            predicted: int(np.sum((labels == actual) & (predictions == predicted)))
            for predicted in LABELS
        }
    for label in LABELS:
        true_positive = int(np.sum((labels == label) & (predictions == label)))
        false_positive = int(np.sum((labels != label) & (predictions == label)))
        false_negative = int(np.sum((labels == label) & (predictions != label)))
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        f1 = _safe_ratio(2.0 * precision * recall, precision + recall)
        per_label[label] = {
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(f1),
            "support": int(np.sum(labels == label)),
        }
    authentic_count = int(np.sum(labels == "AUTHENTIC"))
    misleading_count = int(np.sum(labels == "MISLEADING"))
    false_positive_rate = _safe_ratio(
        int(np.sum((labels == "AUTHENTIC") & (predictions == "MISLEADING"))),
        authentic_count,
    )
    false_negative_rate = _safe_ratio(
        int(np.sum((labels == "MISLEADING") & (predictions != "MISLEADING"))),
        misleading_count,
    )
    return {
        "row_count": int(labels.size),
        "accuracy": _round(float(np.mean(labels == predictions))) if labels.size else 0.0,
        "macro_f1": _round(
            float(np.mean([float(per_label[label]["f1"]) for label in LABELS]))
        ),
        "misleading_precision": per_label["MISLEADING"]["precision"],
        "misleading_recall": per_label["MISLEADING"]["recall"],
        "false_positive_rate": _round(false_positive_rate),
        "false_negative_rate": _round(false_negative_rate),
        "per_label": per_label,
        "confusion_matrix": confusion,
    }


def _sigmoid(values: np.ndarray | float) -> np.ndarray:
    selected = np.asarray(values, dtype=float)
    clipped = np.clip(selected, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def probability_labels(
    probabilities: np.ndarray,
    *,
    authentic_max_probability: float,
    misleading_min_probability: float,
) -> np.ndarray:
    if not 0.0 < authentic_max_probability < misleading_min_probability < 1.0:
        raise ValueError("credibility probability thresholds must be ordered")
    return np.where(
        probabilities <= authentic_max_probability,
        "AUTHENTIC",
        np.where(probabilities >= misleading_min_probability, "MISLEADING", "UNCERTAIN"),
    ).astype(object)


def calibration_metrics(
    binary_labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, float]:
    labels = binary_labels.astype(float)
    clipped = np.clip(probabilities.astype(float), 1e-12, 1.0 - 1e-12)
    log_loss = -float(np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped)))
    brier = float(np.mean((clipped - labels) ** 2))
    ece = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (clipped >= lower) & (
            clipped <= upper if index == bins - 1 else clipped < upper
        )
        if not np.any(mask):
            continue
        ece += float(np.mean(mask)) * abs(
            float(np.mean(clipped[mask])) - float(np.mean(labels[mask]))
        )
    return {
        "log_loss": _round(log_loss),
        "brier_score": _round(brier),
        "expected_calibration_error_10_bins": _round(ece),
    }


def _fit_logistic(
    features: np.ndarray,
    labels: np.ndarray,
    candidate: ModelCandidate,
    *,
    feature_indices: Sequence[int] | None = None,
) -> tuple[LogisticRegression, float]:
    resolved = np.isin(labels, RESOLVED_LABELS)
    if not np.any(resolved) or len(set(labels[resolved])) != 2:
        raise CredibilityValidationBlocked("RESOLVED_TRAINING_CLASSES_UNAVAILABLE")
    selected_features = (
        features[resolved]
        if feature_indices is None
        else features[resolved][:, list(feature_indices)]
    )
    targets = (labels[resolved] == "MISLEADING").astype(int)
    started = perf_counter()
    model = LogisticRegression(
        C=candidate.regularization_c,
        class_weight=("balanced" if candidate.class_weight == "BALANCED" else None),
        solver="liblinear",
        max_iter=500,
        random_state=DEFAULT_SEED,
    )
    model.fit(selected_features, targets)
    return model, perf_counter() - started


def _model_probabilities(
    model: LogisticRegression,
    features: np.ndarray,
    *,
    temperature: float = 1.0,
    feature_indices: Sequence[int] | None = None,
) -> np.ndarray:
    selected = features if feature_indices is None else features[:, list(feature_indices)]
    logits = np.asarray(model.decision_function(selected), dtype=float)
    return _sigmoid(logits / temperature)


def select_logistic_model(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    validation_features: np.ndarray,
    validation: CredibilitySplitData,
) -> tuple[FittedCandidate, dict[str, Any]]:
    """Select only model hyperparameters on the model-selection partition."""

    selection_mask = validation.validation_roles == "model_selection"
    if not np.any(selection_mask):
        raise CredibilityValidationBlocked("VALIDATION_MODEL_SELECTION_PARTITION_EMPTY")
    candidates: list[FittedCandidate] = []
    rows: list[dict[str, Any]] = []
    for candidate in CONTROLLED_CANDIDATES:
        model, fit_seconds = _fit_logistic(train_features, train_labels, candidate)
        probabilities = _model_probabilities(model, validation_features[selection_mask])
        predictions = probability_labels(
            probabilities,
            authentic_max_probability=0.40,
            misleading_min_probability=0.60,
        )
        metrics = classification_metrics(validation.labels[selection_mask], predictions)
        fitted = FittedCandidate(
            candidate=candidate,
            model=model,
            metrics=metrics,
            fit_seconds=fit_seconds,
        )
        candidates.append(fitted)
        rows.append(
            {
                "configuration": candidate.model_dump(mode="json"),
                "selection_partition_metrics": metrics,
                "fit_seconds": _round(fit_seconds),
                "default_abstention_thresholds": {
                    "authentic_max_probability": 0.40,
                    "misleading_min_probability": 0.60,
                },
            }
        )

    def rank(item: FittedCandidate) -> tuple[float, float, float, float, int]:
        metrics = item.metrics
        return (
            -float(metrics["macro_f1"]),
            -float(metrics["misleading_recall"]),
            -float(metrics["misleading_precision"]),
            float(metrics["false_positive_rate"]),
            item.candidate.tie_rank,
        )

    selected = min(candidates, key=rank)
    report = {
        "schema_version": "1.0",
        "selection_method": "DETERMINISTIC_VALIDATION_ONLY_LEXICOGRAPHIC",
        "selection_partition": "validation:model_selection",
        "selection_rows": int(np.sum(selection_mask)),
        "training_rows": int(train_labels.size),
        "resolved_training_rows": int(np.sum(np.isin(train_labels, RESOLVED_LABELS))),
        "primary_metric": "macro_f1",
        "tie_break_order": [
            "macro_f1_desc",
            "misleading_recall_desc",
            "misleading_precision_desc",
            "false_positive_rate_asc",
            "fixed_candidate_rank_asc",
        ],
        "candidate_count": len(rows),
        "candidates": rows,
        "selected_configuration": selected.candidate.model_dump(mode="json"),
        "selected_metrics": selected.metrics,
        "test_rows_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }
    return selected, report


def calibrate_on_validation(
    fitted: FittedCandidate,
    validation_features: np.ndarray,
    validation: CredibilitySplitData,
) -> tuple[float, dict[str, Any]]:
    """Fit a scalar temperature on the dedicated validation partition only."""

    fit_mask = (validation.validation_roles == "calibration") & np.isin(
        validation.labels, RESOLVED_LABELS
    )
    if int(np.sum(fit_mask)) < 20:
        raise CredibilityValidationBlocked("VALIDATION_CALIBRATION_PARTITION_TOO_SMALL")
    labels = (validation.labels[fit_mask] == "MISLEADING").astype(int)
    logits = np.asarray(
        fitted.model.decision_function(validation_features[fit_mask]), dtype=float
    )
    temperatures = np.linspace(0.50, 3.00, 101)
    candidates: list[tuple[float, dict[str, float]]] = []
    for temperature in temperatures:
        metrics = calibration_metrics(labels, _sigmoid(logits / float(temperature)))
        candidates.append((float(temperature), metrics))
    temperature, selected_metrics = min(
        candidates,
        key=lambda item: (
            float(item[1]["log_loss"]),
            float(item[1]["brier_score"]),
            abs(item[0] - 1.0),
            item[0],
        ),
    )
    before_metrics = calibration_metrics(labels, _sigmoid(logits))
    report = {
        "schema_version": "1.0",
        "calibration_version": CALIBRATION_VERSION,
        "method": "SCALAR_TEMPERATURE_GRID_SEARCH",
        "fit_source": "VALIDATION_ONLY",
        "fit_partition": "validation:calibration",
        "fit_rows": int(labels.size),
        "temperature_candidates": [0.50, 3.00, 0.025],
        "selected_temperature": _round(temperature),
        "pre_calibration": before_metrics,
        "post_calibration": selected_metrics,
        "selection_rule": "log_loss, then Brier score, then distance from 1, then temperature",
        "test_rows_accessed": False,
        "production_calibration": PRODUCTION_VALIDATION,
        "limitations": [
            "Calibration uses project-authored synthetic validation labels only.",
            "The probability estimates misleading-risk evidence, never factual truth.",
        ],
    }
    return temperature, report


def _scenario_error_rate(
    labels: np.ndarray,
    predictions: np.ndarray,
    scenarios: np.ndarray,
    scenario_names: set[str],
    *,
    actual_label: str,
    error_label: str,
) -> float:
    mask = np.isin(scenarios, list(scenario_names)) & (labels == actual_label)
    return _safe_ratio(int(np.sum(mask & (predictions == error_label))), int(np.sum(mask)))


def select_abstention_thresholds(
    probabilities: np.ndarray,
    validation: CredibilitySplitData,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Select AUTHENTIC/UNCERTAIN/MISLEADING cutoffs on validation only."""

    selection_mask = validation.validation_roles == "threshold_selection"
    if not np.any(selection_mask):
        raise CredibilityValidationBlocked("VALIDATION_THRESHOLD_PARTITION_EMPTY")
    labels = validation.labels[selection_mask]
    scenarios = validation.scenarios[selection_mask]
    selected_probabilities = probabilities[selection_mask]
    authentic_hard_negatives = {
        "AUTHENTIC_EXTREME_BUT_PLAUSIBLE",
        "AUTHENTIC_WITH_INCOMPLETE_METADATA",
        "LEGITIMATE_DUPLICATE",
        "LEGITIMATE_EVENT_CONFLICT",
    }
    rows: list[dict[str, Any]] = []
    for authentic_max in (
        0.0000001,
        0.00001,
        0.001,
        0.01,
        0.05,
        0.10,
        0.20,
        0.30,
        0.40,
        0.45,
    ):
        for misleading_min in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
            predictions = probability_labels(
                selected_probabilities,
                authentic_max_probability=authentic_max,
                misleading_min_probability=misleading_min,
            )
            metrics = classification_metrics(labels, predictions)
            hard_negative_false_misleading_rate = _scenario_error_rate(
                labels,
                predictions,
                scenarios,
                authentic_hard_negatives,
                actual_label="AUTHENTIC",
                error_label="MISLEADING",
            )
            rows.append(
                {
                    "authentic_max_probability": authentic_max,
                    "misleading_min_probability": misleading_min,
                    "metrics": metrics,
                    "authentic_hard_negative_false_misleading_rate": _round(
                        hard_negative_false_misleading_rate
                    ),
                    "constraint_satisfied": hard_negative_false_misleading_rate <= 0.10,
                }
            )
    eligible = [row for row in rows if row["constraint_satisfied"]] or rows

    def rank(row: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        metrics = row["metrics"]
        return (
            -float(metrics["macro_f1"]),
            -float(metrics["misleading_recall"]),
            -float(metrics["misleading_precision"]),
            float(metrics["false_positive_rate"]),
            float(row["authentic_hard_negative_false_misleading_rate"]),
            float(row["misleading_min_probability"])
            - float(row["authentic_max_probability"]),
        )

    selected = min(eligible, key=rank)
    thresholds = {
        "authentic_max_probability": float(selected["authentic_max_probability"]),
        "misleading_min_probability": float(selected["misleading_min_probability"]),
    }
    report = {
        "schema_version": "1.0",
        "threshold_version": THRESHOLD_VERSION,
        "selection_partition": "validation:threshold_selection",
        "selection_rows": int(np.sum(selection_mask)),
        "candidate_count": len(rows),
        "hard_negative_constraint": {
            "metric": "false_misleading_rate",
            "maximum": 0.10,
            "scenarios": sorted(authentic_hard_negatives),
        },
        "selection_rule": [
            "constraint_satisfied_first",
            "macro_f1_desc",
            "misleading_recall_desc",
            "misleading_precision_desc",
            "false_positive_rate_asc",
            "hard_negative_false_misleading_rate_asc",
            "abstention_band_width_asc",
        ],
        "selected_thresholds": thresholds,
        "selected_metrics": selected["metrics"],
        "selected_hard_negative_false_misleading_rate": selected[
            "authentic_hard_negative_false_misleading_rate"
        ],
        "candidates": rows,
        "test_rows_accessed": False,
    }
    return thresholds, report


def _feature_family_for_name(name: str) -> str:
    base = name.removesuffix("__missing")
    for spec in FEATURE_SPECS:
        if spec.name == base:
            return spec.family
    raise KeyError(name)


def feature_indices_for_families(
    state: PreprocessorState,
    families: Sequence[str],
) -> list[int]:
    selected = set(families)
    return [
        index
        for index, name in enumerate(state.feature_names)
        if _feature_family_for_name(name) in selected
    ]


def run_validation_ablation(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    validation_features: np.ndarray,
    validation: CredibilitySplitData,
    preprocessor: PreprocessorState,
    selected_candidate: ModelCandidate,
) -> dict[str, Any]:
    """Fit family-restricted models and evaluate on validation only."""

    mask = validation.validation_roles == "model_selection"
    results: dict[str, Any] = {}
    for display_name, families in ABLATION_FAMILIES:
        indices = feature_indices_for_families(preprocessor, families)
        model, fit_seconds = _fit_logistic(
            train_features,
            train_labels,
            selected_candidate,
            feature_indices=indices,
        )
        probabilities = _model_probabilities(
            model,
            validation_features[mask],
            feature_indices=indices,
        )
        predictions = probability_labels(
            probabilities,
            authentic_max_probability=0.40,
            misleading_min_probability=0.60,
        )
        results[display_name] = {
            "feature_families": list(families),
            "feature_count": len(indices),
            "metrics": classification_metrics(validation.labels[mask], predictions),
            "fit_seconds": _round(fit_seconds),
        }
    return {
        "schema_version": "1.0",
        "evaluation_scope": "VALIDATION_ONLY",
        "evaluation_partition": "validation:model_selection",
        "fixed_abstention_thresholds": {
            "authentic_max_probability": 0.40,
            "misleading_min_probability": 0.60,
        },
        "selected_model_hyperparameters_reused": selected_candidate.model_dump(
            mode="json"
        ),
        "ablation_results": results,
        "test_rows_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }


def hard_negative_results(
    data: CredibilitySplitData,
    predictions: np.ndarray,
) -> dict[str, Any]:
    scenarios = (
        "AUTHENTIC_EXTREME_BUT_PLAUSIBLE",
        "AUTHENTIC_WITH_INCOMPLETE_METADATA",
        "MISLEADING_OMISSION",
        "MISLEADING_CONTEXT",
        "LEGITIMATE_DUPLICATE",
        "LEGITIMATE_EVENT_CONFLICT",
        "SOURCE_BEHAVIOR_ANOMALY",
    )
    results: dict[str, Any] = {}
    for scenario in scenarios:
        mask = data.scenarios == scenario
        actual = str(data.labels[mask][0]) if np.any(mask) else "UNAVAILABLE"
        predicted_counts = Counter(str(value) for value in predictions[mask])
        row = {
            "row_count": int(np.sum(mask)),
            "actual_label": actual,
            "predicted_distribution": dict(sorted(predicted_counts.items())),
            "correct_rate": _round(float(np.mean(predictions[mask] == data.labels[mask])))
            if np.any(mask)
            else None,
        }
        if actual == "AUTHENTIC":
            row["false_misleading_rate"] = _round(
                float(np.mean(predictions[mask] == "MISLEADING"))
            )
        elif actual == "MISLEADING":
            row["misleading_recall"] = _round(
                float(np.mean(predictions[mask] == "MISLEADING"))
            )
        results[scenario] = row
    return {
        "scope": data.split,
        "duplicate_not_equated_with_misleading": (
            float(results["LEGITIMATE_DUPLICATE"].get("false_misleading_rate") or 0.0)
            <= 0.10
        ),
        "extreme_not_equated_with_misleading": (
            float(
                results["AUTHENTIC_EXTREME_BUT_PLAUSIBLE"].get(
                    "false_misleading_rate"
                )
                or 0.0
            )
            <= 0.10
        ),
        "scenarios": results,
    }


def multilingual_results(
    data: CredibilitySplitData,
    predictions: np.ndarray,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for language in LANGUAGES:
        mask = data.languages == language
        results[language] = classification_metrics(data.labels[mask], predictions[mask])
    macro_values = [float(results[language]["macro_f1"]) for language in LANGUAGES]
    return {
        "scope": data.split,
        "languages": results,
        "macro_f1_range": _round(max(macro_values) - min(macro_values)),
        "weakest_language": min(
            LANGUAGES, key=lambda language: (results[language]["macro_f1"], language)
        ),
    }


def failure_analysis(
    data: CredibilitySplitData,
    predictions: np.ndarray,
    probabilities: np.ndarray,
    *,
    maximum_examples_per_category: int = 25,
) -> dict[str, Any]:
    categories = {
        "FALSE_MISLEADING": (data.labels == "AUTHENTIC")
        & (predictions == "MISLEADING"),
        "MISSED_MISLEADING": (data.labels == "MISLEADING")
        & (predictions != "MISLEADING"),
    }
    result: dict[str, Any] = {}
    for category, mask in categories.items():
        indexes = np.flatnonzero(mask)
        reason_counts = Counter(str(value) for value in data.reason_groups[indexes])
        scenario_counts = Counter(str(value) for value in data.scenarios[indexes])
        examples = [
            {
                "report_id": str(data.report_ids[index]),
                "scenario": str(data.scenarios[index]),
                "language": str(data.languages[index]),
                "reason_group": str(data.reason_groups[index]),
                "actual_label": str(data.labels[index]),
                "predicted_label": str(predictions[index]),
                "misleading_risk_probability": _round(float(probabilities[index])),
                "text": str(data.snippets[index]),
            }
            for index in indexes[:maximum_examples_per_category]
        ]
        result[category] = {
            "count": int(indexes.size),
            "rate": _round(_safe_ratio(int(indexes.size), data.row_count)),
            "reason_groups": dict(sorted(reason_counts.items())),
            "scenarios": dict(sorted(scenario_counts.items())),
            "examples": examples,
        }
    return {
        "scope": data.split,
        "method": "DETERMINISTIC_LOCAL_GROUPING_NO_EXTERNAL_AI",
        "categories": result,
    }


def protected_artifact_snapshot(
    artifact_root: Path | str = ARTIFACT_ROOT,
) -> dict[str, str]:
    root = local_only_path(artifact_root, description="artifact directories").resolve()
    names: set[str] = set()
    for pattern in (
        "nlp_classifier_v3*.json",
        "duplicate_feature_state_v2.json",
        "duplicate_matcher_v1.json",
        "duplicate_v1*.json",
        "event_grouping_v1*.json",
    ):
        names.update(path.name for path in root.glob(pattern) if path.is_file())
    return {name: file_sha256(root / name) for name in sorted(names)}


def _assert_frozen_core(snapshot: Mapping[str, str]) -> None:
    mismatches = [
        name
        for name, expected in EXPECTED_FROZEN_CORE_HASHES.items()
        if snapshot.get(name) != expected
    ]
    if mismatches:
        raise CredibilityValidationBlocked(
            "FROZEN_COMPONENT_HASH_MISMATCH:" + ",".join(sorted(mismatches))
        )


def _write_json_atomic(
    path: Path,
    payload: Any,
    *,
    exclusive: bool = False,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(f"refusing to overwrite locked output: {path.name}")
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
    if exclusive and path.exists():
        temporary.unlink(missing_ok=True)
        raise FileExistsError(f"refusing to overwrite locked output: {path.name}")
    temporary.replace(path)
    return file_sha256(path)


def _phase21_paths(output_directory: Path | str) -> dict[str, Path]:
    root = local_only_path(
        output_directory, description="credibility artifact directories"
    ).resolve()
    return {
        "artifact": root / DEFAULT_ARTIFACT_PATH.name,
        "development_manifest": root / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "search": root / DEFAULT_SEARCH_PATH.name,
        "calibration": root / DEFAULT_CALIBRATION_PATH.name,
        "ablation": root / DEFAULT_ABLATION_PATH.name,
        "baseline_validation": root / DEFAULT_BASELINE_VALIDATION_PATH.name,
        "validation_metrics": root / DEFAULT_VALIDATION_METRICS_PATH.name,
        "validation_errors": root / DEFAULT_VALIDATION_ERRORS_PATH.name,
        "performance": root / DEFAULT_PERFORMANCE_PATH.name,
        "golden": root / DEFAULT_GOLDEN_PATH.name,
        "final_metrics": root / DEFAULT_FINAL_METRICS_PATH.name,
        "error_report": root / DEFAULT_ERROR_REPORT_PATH.name,
        "receipt": root / DEFAULT_FINAL_RECEIPT_PATH.name,
    }


def _framework_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pydantic": pydantic.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _append_artifact_manifest(
    artifact_path: Path,
    *,
    training_dataset_hash: str,
    manifest_path: Path,
) -> ArtifactMetadata:
    if not manifest_path.is_file():
        raise CredibilityValidationBlocked("ARTIFACT_MANIFEST_MISSING")
    manifest = ArtifactManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if any(item.artifact_name == artifact_path.name for item in manifest.artifacts):
        raise CredibilityValidationBlocked("CREDIBILITY_ARTIFACT_ALREADY_REGISTERED")
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=ARTIFACT_VERSION,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=training_dataset_hash,
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        training_timestamp=FREEZE_TIMESTAMP,
        random_seed=DEFAULT_SEED,
        framework_versions=_framework_versions(),
        intended_component="fake_detector",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    updated = manifest.model_copy(
        update={"artifacts": [*manifest.artifacts, metadata]}
    )
    _write_json_atomic(manifest_path, updated.model_dump(mode="json"))
    return metadata


def load_credibility_development_artifact(
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    *,
    manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> CredibilityDevelopmentArtifact:
    selected_artifact = local_only_path(
        artifact_path, description="credibility model artifacts"
    ).resolve()
    selected_manifest = local_only_path(
        manifest_path, description="artifact manifests"
    ).resolve()
    artifact = CredibilityDevelopmentArtifact.model_validate_json(
        selected_artifact.read_text(encoding="utf-8")
    )
    manifest = ArtifactManifest.model_validate_json(
        selected_manifest.read_text(encoding="utf-8")
    )
    matches = [
        item for item in manifest.artifacts if item.artifact_name == selected_artifact.name
    ]
    if len(matches) != 1:
        raise CredibilityValidationBlocked("CREDIBILITY_ARTIFACT_MANIFEST_ENTRY_INVALID")
    metadata = matches[0]
    if (
        metadata.sha256 != file_sha256(selected_artifact)
        or metadata.artifact_version != artifact.artifact_version
        or metadata.training_dataset_hash != artifact.dataset_sha256
        or metadata.feature_version != artifact.feature_version
        or metadata.preprocessing_version != artifact.preprocessing_version
        or metadata.intended_component != "fake_detector"
        or metadata.policy_status is not ArtifactPolicyStatus.COMPLIANT
    ):
        raise CredibilityValidationBlocked("CREDIBILITY_ARTIFACT_MANIFEST_MISMATCH")
    return artifact


def _artifact_preprocessor(
    artifact: CredibilityDevelopmentArtifact,
) -> PreprocessorState:
    return PreprocessorState(
        base_feature_names=artifact.base_feature_names,
        feature_names=artifact.feature_names,
        medians=artifact.medians,
        means=artifact.means,
        scales=artifact.scales,
    )


def _artifact_probabilities(
    artifact: CredibilityDevelopmentArtifact,
    raw_features: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    transformed = apply_preprocessor(raw_features, _artifact_preprocessor(artifact))
    logits = transformed @ np.asarray(artifact.coefficients, dtype=float) + float(
        artifact.intercept
    )
    temperature = float(artifact.calibration["temperature"])
    return _sigmoid(logits / temperature), transformed


def predict_credibility_development(
    value: SyntheticCredibilityDetectorInput,
    artifact: CredibilityDevelopmentArtifact,
) -> CredibilityDevelopmentPrediction:
    """Run deterministic local inference without changing the live backend."""

    snapshot = extract_credibility_features(value.to_risk_input())
    raw = np.asarray([raw_feature_row(snapshot)], dtype=float)
    probabilities, transformed = _artifact_probabilities(artifact, raw)
    probability = float(probabilities[0])
    label = str(
        probability_labels(
            probabilities,
            authentic_max_probability=artifact.thresholds[
                "authentic_max_probability"
            ],
            misleading_min_probability=artifact.thresholds[
                "misleading_min_probability"
            ],
        )[0]
    )
    contributions = transformed[0] * np.asarray(artifact.coefficients, dtype=float)
    indexes = sorted(
        range(len(contributions)),
        key=lambda index: (-abs(float(contributions[index])), artifact.feature_names[index]),
    )[:8]
    return CredibilityDevelopmentPrediction(
        label=label,  # type: ignore[arg-type]
        misleading_risk_probability=round(probability, 12),
        artifact_version=artifact.artifact_version,
        feature_version=artifact.feature_version,
        top_feature_contributions=[
            {
                "feature": artifact.feature_names[index],
                "contribution": round(float(contributions[index]), 12),
            }
            for index in indexes
        ],
        warnings=[
            "DEVELOPMENT_ONLY synthetic evidence; production validation is NOT_VALIDATED.",
            "This is a probability of modeled misleading-risk evidence, not truth probability.",
        ],
    )


def _feature_family_payload(state: PreprocessorState) -> dict[str, list[str]]:
    return {
        family: [
            name
            for name in state.feature_names
            if _feature_family_for_name(name) == family
        ]
        for family in ("TEXT", "METADATA", "DUPLICATE", "EVENT", "SOURCE")
    }


def _artifact_payload(
    *,
    binding: CredibilityDatasetBinding,
    preprocessor: PreprocessorState,
    fitted: FittedCandidate,
    temperature: float,
    calibration: Mapping[str, Any],
    thresholds: Mapping[str, float],
) -> CredibilityDevelopmentArtifact:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_version": ARTIFACT_VERSION,
        "artifact_kind": "INTERPRETABLE_LOCAL_LOGISTIC_REGRESSION",
        "development_status": DEVELOPMENT_STATUS,
        "production_validation": PRODUCTION_VALIDATION,
        "semantic_target": SEMANTIC_TARGET,
        "prohibited_interpretation": "TRUTH_PROBABILITY",
        "dataset_id": DEFAULT_DATASET_ID,
        "dataset_version": DEFAULT_DATASET_VERSION,
        "dataset_sha256": binding.quality_report.dataset_sha256,
        "split_sha256": binding.quality_report.split_sha256,
        "dataset_manifest_sha256": file_sha256(binding.manifest_path),
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "split_version": SPLIT_VERSION,
        "template_version": TEMPLATE_VERSION,
        "feature_version": FEATURE_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "model_classes": list(RESOLVED_LABELS),
        "output_labels": list(LABELS),
        "base_feature_names": preprocessor.base_feature_names,
        "feature_names": preprocessor.feature_names,
        "feature_families": _feature_family_payload(preprocessor),
        "transformations": {
            spec.name: spec.transformation for spec in FEATURE_SPECS
        },
        "medians": preprocessor.medians,
        "means": preprocessor.means,
        "scales": preprocessor.scales,
        "coefficients": [float(value) for value in fitted.model.coef_[0]],
        "intercept": float(fitted.model.intercept_[0]),
        "selected_configuration": fitted.candidate.model_dump(mode="json"),
        "calibration": {
            "calibration_version": CALIBRATION_VERSION,
            "method": calibration["method"],
            "fit_source": "VALIDATION_ONLY",
            "fit_partition": calibration["fit_partition"],
            "temperature": float(temperature),
            "validation_metrics": calibration["post_calibration"],
            "production_calibration": PRODUCTION_VALIDATION,
        },
        "thresholds": dict(thresholds),
        "decision_logic": (
            "p<=authentic_max -> AUTHENTIC; p>=misleading_min -> MISLEADING; "
            "otherwise UNCERTAIN"
        ),
        "selection_split": "validation:model_selection",
        "calibration_split": "validation:calibration",
        "threshold_selection_split": "validation:threshold_selection",
        "test_rows_accessed_for_selection": False,
        "frozen_at": FREEZE_TIMESTAMP.isoformat().replace("+00:00", "Z"),
        "random_seed": DEFAULT_SEED,
        "library_versions": _framework_versions(),
        "policy": {
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
            "nlp_v3_modified": False,
            "duplicate_matcher_v1_modified": False,
            "event_grouping_v1_modified": False,
            "future_human_review_features": False,
        },
        "artifact_hash_scope": "CANONICAL_JSON_EXCLUDING_ARTIFACT_HASH",
    }
    payload["artifact_hash"] = _artifact_payload_hash(payload)
    return CredibilityDevelopmentArtifact.model_validate(payload)


def _split_model_evaluation(
    data: CredibilitySplitData,
    probabilities: np.ndarray,
    thresholds: Mapping[str, float],
) -> tuple[np.ndarray, dict[str, Any]]:
    predictions = probability_labels(
        probabilities,
        authentic_max_probability=float(thresholds["authentic_max_probability"]),
        misleading_min_probability=float(thresholds["misleading_min_probability"]),
    )
    resolved = np.isin(data.labels, RESOLVED_LABELS)
    binary = (data.labels[resolved] == "MISLEADING").astype(int)
    return predictions, {
        "classification": classification_metrics(data.labels, predictions),
        "calibration": calibration_metrics(binary, probabilities[resolved]),
        "hard_negative_results": hard_negative_results(data, predictions),
        "multilingual_results": multilingual_results(data, predictions),
        "score_semantics": "CALIBRATED_MISLEADING_RISK_EVIDENCE_PROBABILITY",
        "truth_probability": False,
    }


def _baseline_evaluation(data: CredibilitySplitData) -> dict[str, Any]:
    return {
        "baseline_name": RULE_BASED_CREDIBILITY_BASELINE,
        "split": data.split,
        "metrics": classification_metrics(data.labels, data.baseline_labels),
        "hard_negative_results": hard_negative_results(data, data.baseline_labels),
        "multilingual_results": multilingual_results(data, data.baseline_labels),
        "score_semantics": "DETERMINISTIC_RISK_SCORE_NOT_PROBABILITY",
        "calibrated": False,
        "truth_probability": False,
    }


def _development_performance_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    classification = metrics["classification"]
    hard = metrics["hard_negative_results"]
    checks = {
        "macro_f1_at_least_0_75": float(classification["macro_f1"]) >= 0.75,
        "misleading_recall_at_least_0_80": float(
            classification["misleading_recall"]
        )
        >= 0.80,
        "misleading_precision_at_least_0_80": float(
            classification["misleading_precision"]
        )
        >= 0.80,
        "false_positive_rate_at_most_0_15": float(
            classification["false_positive_rate"]
        )
        <= 0.15,
        "duplicate_not_equated_with_misleading": bool(
            hard["duplicate_not_equated_with_misleading"]
        ),
        "extreme_not_equated_with_misleading": bool(
            hard["extreme_not_equated_with_misleading"]
        ),
    }
    return {
        "scope": "SYNTHETIC_DEVELOPMENT_ONLY",
        "passed": all(checks.values()),
        "checks": checks,
        "production_validation": PRODUCTION_VALIDATION,
    }


def freeze_credibility_development(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Train/validate/freeze without loading protected test examples."""

    paths = _phase21_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    guarded_outputs = [
        paths[name]
        for name in (
            "artifact",
            "development_manifest",
            "search",
            "calibration",
            "ablation",
            "baseline_validation",
            "validation_metrics",
            "validation_errors",
            "performance",
            "golden",
            "final_metrics",
            "error_report",
            "receipt",
        )
    ]
    existing = [path.name for path in guarded_outputs if path.exists()]
    if existing:
        raise CredibilityValidationBlocked(
            "CREDIBILITY_PHASE21_OUTPUT_ALREADY_EXISTS:" + ",".join(existing)
        )
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    _assert_frozen_core(protected_before)
    binding = bind_synthetic_credibility_dataset(registry_path)

    training_started = perf_counter()
    train = load_credibility_split(binding, "train")
    validation = load_credibility_split(binding, "validation")
    preprocessor = fit_preprocessor(train.raw_features)
    train_features = apply_preprocessor(train.raw_features, preprocessor)
    validation_features = apply_preprocessor(validation.raw_features, preprocessor)
    selected, model_search = select_logistic_model(
        train_features,
        train.labels,
        validation_features,
        validation,
    )
    temperature, calibration = calibrate_on_validation(
        selected,
        validation_features,
        validation,
    )
    validation_probabilities = _model_probabilities(
        selected.model,
        validation_features,
        temperature=temperature,
    )
    thresholds, threshold_search = select_abstention_thresholds(
        validation_probabilities,
        validation,
    )
    validation_predictions, validation_evaluation = _split_model_evaluation(
        validation,
        validation_probabilities,
        thresholds,
    )
    performance_gate = _development_performance_gate(validation_evaluation)
    if not performance_gate["passed"]:
        raise CredibilityValidationBlocked(
            "SYNTHETIC_DEVELOPMENT_PERFORMANCE_GATE_FAILED"
        )
    baseline_validation = _baseline_evaluation(validation)
    ablation = run_validation_ablation(
        train_features,
        train.labels,
        validation_features,
        validation,
        preprocessor,
        selected.candidate,
    )
    validation_errors = failure_analysis(
        validation,
        validation_predictions,
        validation_probabilities,
    )
    elapsed = perf_counter() - training_started
    performance = {
        "schema_version": "1.0",
        "scope": "LOCAL_SYNTHETIC_ENGINEERING_OBSERVATION",
        "operational_latency_claimed": False,
        "train_rows": train.row_count,
        "validation_rows": validation.row_count,
        "train_feature_extraction_seconds": _round(train.feature_extraction_seconds),
        "validation_feature_extraction_seconds": _round(
            validation.feature_extraction_seconds
        ),
        "selected_model_fit_seconds": _round(selected.fit_seconds),
        "complete_freeze_workflow_seconds": _round(elapsed),
        "rows_per_second_complete_workflow": _round(
            _safe_ratio(train.row_count + validation.row_count, elapsed)
        ),
        "production_validation": PRODUCTION_VALIDATION,
    }
    artifact = _artifact_payload(
        binding=binding,
        preprocessor=preprocessor,
        fitted=selected,
        temperature=temperature,
        calibration=calibration,
        thresholds=thresholds,
    )
    _write_json_atomic(paths["artifact"], artifact)
    search = {
        "schema_version": "1.0",
        "model_selection": model_search,
        "threshold_selection": threshold_search,
        "test_rows_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }
    validation_metrics = {
        "schema_version": "1.0",
        "phase": "21 — CREDIBILITY VALIDATION",
        "split": "validation",
        "model": validation_evaluation,
        "baseline_reference": DEFAULT_BASELINE_VALIDATION_PATH.name,
        "development_performance_gate": performance_gate,
        "validation_role_counts": dict(
            sorted(Counter(str(value) for value in validation.validation_roles).items())
        ),
        "configuration_selected_without_test": True,
        "semantic_target": SEMANTIC_TARGET,
        "truth_probability": False,
        "production_validation": PRODUCTION_VALIDATION,
    }
    golden_checks = {
        "semantic_target_is_misleading_risk_evidence": artifact.semantic_target
        == SEMANTIC_TARGET,
        "truth_probability_is_prohibited": artifact.prohibited_interpretation
        == "TRUTH_PROBABILITY",
        "hidden_label_isolation_passed": binding.quality_report.isolation_checks.get(
            "status"
        )
        == "PASS",
        "grouped_leakage_checks_passed": binding.quality_report.leakage_checks.get(
            "status"
        )
        == "PASS",
        "production_training_gate_closed": not binding.production_training_gate[
            "allowed"
        ],
        "synthetic_development_gate_open": binding.development_gate["allowed"],
        "uncertain_not_fitted_as_target": artifact.model_classes
        == list(RESOLVED_LABELS),
        "duplicate_not_equated_with_misleading": validation_evaluation[
            "hard_negative_results"
        ]["duplicate_not_equated_with_misleading"],
        "extreme_not_equated_with_misleading": validation_evaluation[
            "hard_negative_results"
        ]["extreme_not_equated_with_misleading"],
        "multilingual_results_present": set(
            validation_evaluation["multilingual_results"]["languages"]
        )
        == set(LANGUAGES),
        "test_not_accessed_for_selection": True,
        "pretrained_models_absent": artifact.policy["pretrained_models"] == [],
        "open_weight_models_absent": artifact.policy["open_weight_models"] == [],
        "external_apis_absent": artifact.policy["external_apis"] == [],
        "network_access_disabled": artifact.policy["network_access"] is False,
    }
    golden = {
        "schema_version": "1.0",
        "status": "PASS" if all(golden_checks.values()) else "FAIL",
        "checks": golden_checks,
        "production_validation": PRODUCTION_VALIDATION,
    }
    if golden["status"] != "PASS":
        raise CredibilityValidationBlocked("CREDIBILITY_GOLDEN_CHECK_FAILED")
    report_payloads = {
        "search": search,
        "calibration": calibration,
        "ablation": ablation,
        "baseline_validation": baseline_validation,
        "validation_metrics": validation_metrics,
        "validation_errors": validation_errors,
        "performance": performance,
        "golden": golden,
    }
    for name, payload in report_payloads.items():
        _write_json_atomic(paths[name], payload)

    _append_artifact_manifest(
        paths["artifact"],
        training_dataset_hash=binding.quality_report.dataset_sha256,
        manifest_path=manifest_path,
    )
    loaded = load_credibility_development_artifact(
        paths["artifact"], manifest_path=manifest_path
    )
    repeated_probabilities, _ = _artifact_probabilities(
        loaded, validation.raw_features[:32]
    )
    repeated_probabilities_again, _ = _artifact_probabilities(
        loaded, validation.raw_features[:32]
    )
    if not np.array_equal(repeated_probabilities, repeated_probabilities_again):
        raise CredibilityValidationBlocked("CREDIBILITY_INFERENCE_NOT_DETERMINISTIC")

    output_hashes = {
        name: {"file": paths[name].name, "sha256": file_sha256(paths[name])}
        for name in (
            "artifact",
            "search",
            "calibration",
            "ablation",
            "baseline_validation",
            "validation_metrics",
            "validation_errors",
            "performance",
            "golden",
        )
    }
    test_descriptor = binding.manifest["split_descriptors"]["test"]
    development_manifest = {
        "schema_version": "1.0",
        "phase": "21 — CREDIBILITY VALIDATION",
        "status": "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED",
        "frozen_at": FREEZE_TIMESTAMP.isoformat(),
        "dataset_decision": inspect_credibility_dataset_decision(registry_path),
        "dataset": {
            "dataset_id": DEFAULT_DATASET_ID,
            "dataset_version": DEFAULT_DATASET_VERSION,
            "dataset_sha256": binding.quality_report.dataset_sha256,
            "split_sha256": binding.quality_report.split_sha256,
            "source": "PROJECT_AUTHORED",
            "kind": "SYNTHETIC",
            "classification": "DEVELOPMENT_ONLY",
            "semantic_target": SEMANTIC_TARGET,
            "truth_probability": False,
            "production_validation": PRODUCTION_VALIDATION,
            "manifest_sha256": file_sha256(binding.manifest_path),
            "quality_report_sha256": file_sha256(binding.quality_report_path),
            "registered_validation_sha256": binding.registered_validation_sha256,
        },
        "counts": {
            "total": binding.quality_report.report_count,
            "splits": binding.quality_report.split_counts,
            "labels": binding.quality_report.label_counts,
            "scenarios": binding.quality_report.scenario_counts,
            "languages": binding.quality_report.language_counts,
        },
        "gates": {
            "production_training_gate": binding.production_training_gate,
            "synthetic_development_gate": binding.development_gate,
            "development_performance_gate": performance_gate,
        },
        "model_selection": {
            "split": "validation:model_selection",
            "selected_configuration": selected.candidate.model_dump(mode="json"),
            "test_rows_accessed": False,
        },
        "calibration": {
            "split": "validation:calibration",
            "temperature": temperature,
            "report_sha256": output_hashes["calibration"]["sha256"],
            "test_rows_accessed": False,
        },
        "thresholds": {
            "split": "validation:threshold_selection",
            "values": thresholds,
            "test_rows_accessed": False,
        },
        "outputs": output_hashes,
        "artifact_manifest": {
            "path": str(manifest_path),
            "sha256": file_sha256(manifest_path),
        },
        "protected_final_test": {
            "split": "test",
            "row_count": test_descriptor["row_count"],
            "ground_truth_sha256": test_descriptor["ground_truth_sha256"],
            "detector_input_sha256": test_descriptor["detector_input_sha256"],
            "content_accessed_for_selection": False,
            "integrity_hash_verified": True,
            "evaluation_invocation_limit": 1,
            "evaluation_invocation_count": 0,
            "configuration_changes_permitted_after_freeze": False,
        },
        "protected_artifacts": protected_before,
        "policy": artifact.policy,
        "production_validation": PRODUCTION_VALIDATION,
    }
    _write_json_atomic(paths["development_manifest"], development_manifest)
    protected_after = protected_artifact_snapshot(ARTIFACT_ROOT)
    if protected_after != protected_before:
        raise CredibilityValidationBlocked("FROZEN_COMPONENTS_MODIFIED_DURING_PHASE21")
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
        "phase": "21 — CREDIBILITY VALIDATION",
        "evaluation_label": "FINAL_SYNTHETIC_CREDIBILITY_HOLDOUT_EVALUATION",
        "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
        "development_manifest_sha256": development_manifest_sha256,
        "artifact_sha256": artifact_sha256,
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
        "semantic_target": SEMANTIC_TARGET,
        "truth_probability": False,
    }
    _write_json_atomic(receipt_path, claim, exclusive=True)


def _verify_frozen_development(
    paths: Mapping[str, Path],
    *,
    manifest_path: Path,
) -> tuple[dict[str, Any], CredibilityDevelopmentArtifact]:
    if not paths["development_manifest"].is_file():
        raise CredibilityValidationBlocked("CREDIBILITY_DEVELOPMENT_MANIFEST_MISSING")
    development = _read_json(paths["development_manifest"])
    if development.get("status") != "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED":
        raise CredibilityValidationBlocked("CREDIBILITY_DEVELOPMENT_STATUS_INVALID")
    for name, metadata in development.get("outputs", {}).items():
        expected = paths.get(name)
        if (
            expected is None
            or expected.name != metadata.get("file")
            or not expected.is_file()
            or file_sha256(expected) != metadata.get("sha256")
        ):
            raise CredibilityValidationBlocked(f"FROZEN_CREDIBILITY_OUTPUT_CHANGED:{name}")
    if file_sha256(manifest_path) != development["artifact_manifest"]["sha256"]:
        raise CredibilityValidationBlocked("ARTIFACT_MANIFEST_CHANGED_AFTER_FREEZE")
    if protected_artifact_snapshot(ARTIFACT_ROOT) != development["protected_artifacts"]:
        raise CredibilityValidationBlocked("FROZEN_COMPONENT_CHANGED_AFTER_FREEZE")
    artifact = load_credibility_development_artifact(
        paths["artifact"], manifest_path=manifest_path
    )
    if artifact.dataset_sha256 != development["dataset"]["dataset_sha256"]:
        raise CredibilityValidationBlocked("FROZEN_DATASET_BINDING_CHANGED")
    return development, artifact


def finalize_credibility_evaluation(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Claim and score the protected synthetic credibility test exactly once."""

    paths = _phase21_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    if paths["receipt"].exists():
        raise RuntimeError(
            "credibility final synthetic holdout was already claimed; reevaluation is prohibited"
        )
    for name in ("final_metrics", "error_report"):
        if paths[name].exists():
            raise RuntimeError(f"refusing to overwrite final output: {paths[name].name}")
    development, artifact = _verify_frozen_development(paths, manifest_path=manifest_path)
    binding = bind_synthetic_credibility_dataset(registry_path)
    if binding.quality_report.dataset_sha256 != artifact.dataset_sha256:
        raise CredibilityValidationBlocked("FINAL_DATASET_HASH_MISMATCH")
    descriptor = development["protected_final_test"]
    if (
        file_sha256(binding.ground_truth_paths["test"])
        != descriptor["ground_truth_sha256"]
        or file_sha256(binding.detector_input_paths["test"])
        != descriptor["detector_input_sha256"]
    ):
        raise CredibilityValidationBlocked("PROTECTED_TEST_DESCRIPTOR_MISMATCH")
    development_hash = file_sha256(paths["development_manifest"])
    artifact_hash = file_sha256(paths["artifact"])
    manifest_hash = file_sha256(manifest_path)
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    _claim_final_evaluation(
        paths["receipt"],
        development_manifest_sha256=development_hash,
        artifact_sha256=artifact_hash,
    )
    try:
        test = load_credibility_split(binding, "test")
        if test.row_count != int(descriptor["row_count"]):
            raise CredibilityValidationBlocked("PROTECTED_TEST_ROW_COUNT_MISMATCH")
        probabilities, _ = _artifact_probabilities(artifact, test.raw_features)
        predictions, model_evaluation = _split_model_evaluation(
            test,
            probabilities,
            artifact.thresholds,
        )
        baseline_evaluation = _baseline_evaluation(test)
        final_errors = failure_analysis(test, predictions, probabilities)
        final_metrics = {
            "schema_version": "1.0",
            "phase": "21 — CREDIBILITY VALIDATION",
            "evaluation_label": "FINAL_SYNTHETIC_CREDIBILITY_HOLDOUT_EVALUATION",
            "evaluation_split": "test",
            "evaluation_invocation_count": 1,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_model_selection": False,
            "test_used_for_calibration": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_preprocessing_fit": False,
            "dataset_sha256": artifact.dataset_sha256,
            "split_sha256": artifact.split_sha256,
            "test_ground_truth_sha256": descriptor["ground_truth_sha256"],
            "test_detector_input_sha256": descriptor["detector_input_sha256"],
            "artifact_sha256": artifact_hash,
            "artifact_hash": artifact.artifact_hash,
            "selected_model": artifact.selected_configuration,
            "thresholds": artifact.thresholds,
            "model_results": model_evaluation,
            "baseline_results": baseline_evaluation,
            "semantic_target": SEMANTIC_TARGET,
            "truth_probability": False,
            "production_validation": PRODUCTION_VALIDATION,
            "limitations": [
                "The holdout is project-authored synthetic development data.",
                "Metrics do not estimate field authenticity, deployment, or population performance.",
                "The learned probability concerns modeled misleading-risk evidence, not truth.",
            ],
        }
        error_report = {
            "schema_version": "1.0",
            "phase": "21 — CREDIBILITY VALIDATION",
            "validation_failure_analysis": _read_json(paths["validation_errors"]),
            "final_test_failure_analysis": final_errors,
            "analysis_method": "DETERMINISTIC_LOCAL_NO_EXTERNAL_AI",
            "configuration_changed_after_failure_analysis": False,
            "production_validation": PRODUCTION_VALIDATION,
        }
        final_metrics_hash = _write_json_atomic(paths["final_metrics"], final_metrics)
        error_report_hash = _write_json_atomic(paths["error_report"], error_report)
        frozen_checks = {
            "artifact": file_sha256(paths["artifact"]) == artifact_hash,
            "development_manifest": file_sha256(paths["development_manifest"])
            == development_hash,
            "artifact_manifest": file_sha256(manifest_path) == manifest_hash,
            "protected_components": protected_artifact_snapshot(ARTIFACT_ROOT)
            == protected_before,
        }
        if not all(frozen_checks.values()):
            raise CredibilityValidationBlocked("FROZEN_STATE_CHANGED_DURING_FINAL_TEST")
        receipt = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_COMPLETE",
            "phase": "21 — CREDIBILITY VALIDATION",
            "evaluation_label": "FINAL_SYNTHETIC_CREDIBILITY_HOLDOUT_EVALUATION",
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "completed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "dataset_id": DEFAULT_DATASET_ID,
            "dataset_version": DEFAULT_DATASET_VERSION,
            "dataset_sha256": artifact.dataset_sha256,
            "split_sha256": artifact.split_sha256,
            "test_ground_truth_sha256": descriptor["ground_truth_sha256"],
            "test_detector_input_sha256": descriptor["detector_input_sha256"],
            "test_rows": test.row_count,
            "development_manifest_sha256": development_hash,
            "artifact_sha256": artifact_hash,
            "artifact_hash": artifact.artifact_hash,
            "final_metrics_file": paths["final_metrics"].name,
            "final_metrics_sha256": final_metrics_hash,
            "error_report_file": paths["error_report"].name,
            "error_report_sha256": error_report_hash,
            "frozen_state_checks": frozen_checks,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_model_selection": False,
            "test_used_for_calibration": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_preprocessing_fit": False,
            "metrics": model_evaluation["classification"],
            "calibration": model_evaluation["calibration"],
            "semantic_target": SEMANTIC_TARGET,
            "truth_probability": False,
            "production_validation": PRODUCTION_VALIDATION,
            "live_backend_modified": False,
            "nlp_modified": False,
            "duplicate_modified": False,
            "event_modified": False,
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
            "phase": "21 — CREDIBILITY VALIDATION",
            "evaluation_label": "FINAL_SYNTHETIC_CREDIBILITY_HOLDOUT_EVALUATION",
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "development_manifest_sha256": development_hash,
            "artifact_sha256": artifact_hash,
            "error_type": type(error).__name__,
            "error": str(error),
            "semantic_target": SEMANTIC_TARGET,
            "truth_probability": False,
            "production_validation": PRODUCTION_VALIDATION,
        }
        _write_json_atomic(paths["receipt"], failed_receipt)
        raise


__all__ = [
    "ARTIFACT_ROOT",
    "ARTIFACT_VERSION",
    "CALIBRATION_VERSION",
    "DEFAULT_ABLATION_PATH",
    "DEFAULT_ARTIFACT_MANIFEST_PATH",
    "DEFAULT_ARTIFACT_PATH",
    "DEFAULT_BASELINE_VALIDATION_PATH",
    "DEFAULT_CALIBRATION_PATH",
    "DEFAULT_DEVELOPMENT_MANIFEST_PATH",
    "DEFAULT_ERROR_REPORT_PATH",
    "DEFAULT_FINAL_METRICS_PATH",
    "DEFAULT_FINAL_RECEIPT_PATH",
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_PERFORMANCE_PATH",
    "DEFAULT_SEARCH_PATH",
    "DEFAULT_VALIDATION_ERRORS_PATH",
    "DEFAULT_VALIDATION_METRICS_PATH",
    "EXPECTED_FROZEN_CORE_HASHES",
    "FEATURE_FAMILIES",
    "FEATURE_SPECS",
    "LABELS",
    "PRODUCTION_VALIDATION",
    "SEMANTIC_TARGET",
    "CredibilityDatasetBinding",
    "CredibilityDevelopmentArtifact",
    "CredibilityDevelopmentPrediction",
    "CredibilitySplitData",
    "CredibilityValidationBlocked",
    "apply_preprocessor",
    "bind_synthetic_credibility_dataset",
    "calibrate_on_validation",
    "calibration_metrics",
    "classification_metrics",
    "failure_analysis",
    "finalize_credibility_evaluation",
    "fit_preprocessor",
    "freeze_credibility_development",
    "hard_negative_results",
    "inspect_credibility_dataset_decision",
    "load_credibility_development_artifact",
    "load_credibility_split",
    "multilingual_results",
    "predict_credibility_development",
    "probability_labels",
    "protected_artifact_snapshot",
    "raw_feature_row",
    "run_validation_ablation",
    "select_abstention_thresholds",
    "select_logistic_model",
]
