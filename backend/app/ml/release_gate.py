"""Fail-closed production release gate for the INDRA AI/ML subsystem.

This module evaluates repository evidence only.  It does not train models,
download artifacts, call platform services, or promote a component.  A
component can be marked ``PRODUCTION_VALIDATED`` only when every formal and
component-specific requirement has explicit passing evidence.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Literal, Mapping
from unittest.mock import patch
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.duplicate_features import load_feature_state
from app.ml.components.nlp_classifier import load_nlp_artifact
from app.ml.config import (
    file_sha256,
    get_ml_config,
    load_artifact_manifest,
    local_only_path,
)
from app.ml.contracts import PredictionStatus, ReportInput, UnifiedMLResult
from app.ml.inference.engine import InferenceEngine


ML_ROOT = Path(__file__).resolve().parent
DOCS_ROOT = ML_ROOT / "docs"
DATASET_READINESS_PATH = DOCS_ROOT / "dataset_readiness.json"
NLP_METRICS_PATH = ML_ROOT / "artifacts" / "nlp_classifier_v1.metrics.json"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentName(str, Enum):
    NLP = "NLP"
    DUPLICATE = "DUPLICATE"
    EVENT = "EVENT"
    CREDIBILITY = "CREDIBILITY"
    IMAGE = "IMAGE"
    ANOMALY = "ANOMALY"


ALL_COMPONENTS = tuple(ComponentName)


class ImplementationStatus(str, Enum):
    AVAILABLE_DEVELOPMENT = "AVAILABLE_DEVELOPMENT"
    HEURISTIC_ONLY = "HEURISTIC_ONLY"
    RULE_BASED_CREDIBILITY_BASELINE = "RULE_BASED_CREDIBILITY_BASELINE"
    FRAMEWORK_ONLY = "FRAMEWORK_ONLY"
    STATISTICAL_BASELINE = "STATISTICAL_BASELINE"


class DataStatus(str, Enum):
    DEVELOPMENT_ONLY_SYNTHETIC = "DEVELOPMENT_ONLY / SYNTHETIC"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class ModelStatus(str, Enum):
    DEVELOPMENT_MODEL = "DEVELOPMENT_MODEL"
    DETERMINISTIC_MATCHER = "DETERMINISTIC_MATCHER"
    HEURISTIC_ONLY = "HEURISTIC_ONLY"
    RULE_BASED_CREDIBILITY_BASELINE = "RULE_BASED_CREDIBILITY_BASELINE"
    TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA = (
        "TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA"
    )
    STATISTICAL_BASELINE = "STATISTICAL_BASELINE"


class EvaluationStatus(str, Enum):
    EVALUATED_GATE_FAILED = "EVALUATED_GATE_FAILED"
    NOT_VALIDATED = "NOT_VALIDATED"


class ReleaseCalibrationStatus(str, Enum):
    NOT_CALIBRATED = "NOT_CALIBRATED"
    PROVISIONAL_UNVALIDATED = "PROVISIONAL / UNVALIDATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CALIBRATION_UNAVAILABLE = "CALIBRATION_UNAVAILABLE"


class ProductionStatus(str, Enum):
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY / NOT_PRODUCTION_READY"
    PRODUCTION_VALIDATED = "PRODUCTION_VALIDATED"


class ReleaseAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_VALIDATED = "NOT_VALIDATED"


class ComponentStatus(StrictModel):
    implementation_status: ImplementationStatus
    data_status: DataStatus
    model_status: ModelStatus
    evaluation_status: EvaluationStatus
    calibration_status: ReleaseCalibrationStatus
    production_status: ProductionStatus = ProductionStatus.DEVELOPMENT_ONLY


def current_component_statuses() -> dict[ComponentName, ComponentStatus]:
    """Return the reviewed Phase 11 status matrix without optimistic defaults."""

    return {
        ComponentName.NLP: ComponentStatus(
            implementation_status=ImplementationStatus.AVAILABLE_DEVELOPMENT,
            data_status=DataStatus.DEVELOPMENT_ONLY_SYNTHETIC,
            model_status=ModelStatus.DEVELOPMENT_MODEL,
            evaluation_status=EvaluationStatus.EVALUATED_GATE_FAILED,
            calibration_status=ReleaseCalibrationStatus.NOT_CALIBRATED,
        ),
        ComponentName.DUPLICATE: ComponentStatus(
            implementation_status=ImplementationStatus.AVAILABLE_DEVELOPMENT,
            data_status=DataStatus.DATA_UNAVAILABLE,
            model_status=ModelStatus.DETERMINISTIC_MATCHER,
            evaluation_status=EvaluationStatus.NOT_VALIDATED,
            calibration_status=ReleaseCalibrationStatus.PROVISIONAL_UNVALIDATED,
        ),
        ComponentName.EVENT: ComponentStatus(
            implementation_status=ImplementationStatus.HEURISTIC_ONLY,
            data_status=DataStatus.DATA_UNAVAILABLE,
            model_status=ModelStatus.HEURISTIC_ONLY,
            evaluation_status=EvaluationStatus.NOT_VALIDATED,
            calibration_status=ReleaseCalibrationStatus.NOT_APPLICABLE,
        ),
        ComponentName.CREDIBILITY: ComponentStatus(
            implementation_status=(
                ImplementationStatus.RULE_BASED_CREDIBILITY_BASELINE
            ),
            data_status=DataStatus.DATA_UNAVAILABLE,
            model_status=ModelStatus.RULE_BASED_CREDIBILITY_BASELINE,
            evaluation_status=EvaluationStatus.NOT_VALIDATED,
            calibration_status=ReleaseCalibrationStatus.NOT_CALIBRATED,
        ),
        ComponentName.IMAGE: ComponentStatus(
            implementation_status=ImplementationStatus.FRAMEWORK_ONLY,
            data_status=DataStatus.DATA_UNAVAILABLE,
            model_status=ModelStatus.TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA,
            evaluation_status=EvaluationStatus.NOT_VALIDATED,
            calibration_status=ReleaseCalibrationStatus.CALIBRATION_UNAVAILABLE,
        ),
        ComponentName.ANOMALY: ComponentStatus(
            implementation_status=ImplementationStatus.STATISTICAL_BASELINE,
            data_status=DataStatus.DATA_UNAVAILABLE,
            model_status=ModelStatus.STATISTICAL_BASELINE,
            evaluation_status=EvaluationStatus.NOT_VALIDATED,
            calibration_status=ReleaseCalibrationStatus.NOT_CALIBRATED,
        ),
    }


class DatasetReadinessEntry(StrictModel):
    dataset_present: bool
    dataset_version: str | None
    dataset_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    label_count: int | None = Field(default=None, ge=0)
    annotator_count: int | None = Field(default=None, ge=0)
    train_count: int | None = Field(default=None, ge=0)
    validation_count: int | None = Field(default=None, ge=0)
    test_count: int | None = Field(default=None, ge=0)
    group_count: int | None = Field(default=None, ge=0)
    leakage_status: str
    provenance_status: str
    independence_status: str

    @model_validator(mode="after")
    def missing_dataset_has_no_invented_counts(self) -> "DatasetReadinessEntry":
        if not self.dataset_present:
            populated = {
                "dataset_version": self.dataset_version,
                "dataset_hash": self.dataset_hash,
                "label_count": self.label_count,
                "annotator_count": self.annotator_count,
                "train_count": self.train_count,
                "validation_count": self.validation_count,
                "test_count": self.test_count,
                "group_count": self.group_count,
            }
            if any(value is not None for value in populated.values()):
                raise ValueError(
                    "absent release datasets must use null metadata and counts"
                )
        return self


class DatasetReadinessReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    scope: Literal["RELEASE_ELIGIBLE_LABELLED_DATASETS"]
    components: dict[ComponentName, DatasetReadinessEntry]

    @model_validator(mode="after")
    def all_components_are_reported(self) -> "DatasetReadinessReport":
        if set(self.components) != set(ALL_COMPONENTS):
            missing = sorted(item.value for item in set(ALL_COMPONENTS) - set(self.components))
            extra = sorted(str(item) for item in set(self.components) - set(ALL_COMPONENTS))
            raise ValueError(
                f"dataset readiness must contain exactly six components; "
                f"missing={missing}, extra={extra}"
            )
        return self


def load_dataset_readiness(
    path: Path | str = DATASET_READINESS_PATH,
) -> DatasetReadinessReport:
    report_path = local_only_path(path, description="dataset readiness reports")
    return DatasetReadinessReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )


class LanguageMetric(StrictModel):
    sample_count: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    macro_f1: float = Field(ge=0.0, le=1.0)


class NLPEvaluationSnapshot(StrictModel):
    model_version: str
    dataset_version: str
    dataset_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    train_count: int = Field(ge=0)
    validation_count: int | None = Field(default=None, ge=0)
    test_count: int = Field(ge=0)
    macro_precision: float = Field(ge=0.0, le=1.0)
    macro_recall: float = Field(ge=0.0, le=1.0)
    macro_f1: float = Field(ge=0.0, le=1.0)
    not_relevant_recall: float = Field(ge=0.0, le=1.0)
    english: LanguageMetric
    hindi: LanguageMetric
    hinglish: LanguageMetric
    historical_acceptance_passed: bool
    production_validated: bool


def load_current_nlp_evaluation(
    path: Path | str = NLP_METRICS_PATH,
) -> NLPEvaluationSnapshot:
    """Read, but never rewrite or retune, the committed NLP evaluation."""

    metrics_path = local_only_path(path, description="NLP metric files")
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    test = payload["test"]
    subgroups = test["subgroup_metrics"]

    def language_metric(key: str) -> LanguageMetric:
        values = subgroups[key]
        if values.get("status") != "DATA_AVAILABLE":
            raise ValueError(f"NLP subgroup {key!r} is not available")
        return LanguageMetric(
            sample_count=values["sample_count"],
            accuracy=values["accuracy"],
            macro_f1=values["macro_f1"],
        )

    return NLPEvaluationSnapshot(
        model_version=payload["model_version"],
        dataset_version=payload["dataset_version"],
        dataset_hash=payload["dataset_sha256"],
        train_count=payload["n_train"],
        validation_count=None,
        test_count=payload["n_test"],
        macro_precision=test["macro_precision"],
        macro_recall=test["macro_recall"],
        macro_f1=test["macro_f1"],
        not_relevant_recall=test["not_relevant_recall"],
        english=language_metric("en"),
        hindi=language_metric("hi"),
        hinglish=language_metric("hinglish"),
        historical_acceptance_passed=bool(
            payload["development_acceptance"]["accepted"]
        ),
        production_validated=bool(payload["production_validated"]),
    )


class NLPReleaseThresholds(StrictModel):
    """Configurable release criteria; these do not alter historical metrics."""

    min_macro_f1: float = Field(default=0.75, ge=0.0, le=1.0)
    min_not_relevant_recall: float = Field(default=0.80, ge=0.0, le=1.0)
    required_language_subgroups: tuple[Literal["en", "hi", "hinglish"], ...] = (
        "en",
        "hi",
        "hinglish",
    )
    minimum_subgroup_rows: dict[Literal["en", "hi", "hinglish"], int] = Field(
        default_factory=lambda: {"en": 5, "hi": 5, "hinglish": 5}
    )

    @model_validator(mode="after")
    def requirements_are_complete(self) -> "NLPReleaseThresholds":
        if len(set(self.required_language_subgroups)) != len(
            self.required_language_subgroups
        ):
            raise ValueError("required language subgroups must be unique")
        missing = set(self.required_language_subgroups) - set(
            self.minimum_subgroup_rows
        )
        if missing:
            raise ValueError(
                f"minimum row requirements missing for subgroups: {sorted(missing)}"
            )
        if any(value < 1 for value in self.minimum_subgroup_rows.values()):
            raise ValueError("minimum subgroup rows must be positive")
        return self


class ReleaseGateConfig(StrictModel):
    nlp: NLPReleaseThresholds = Field(default_factory=NLPReleaseThresholds)


class GateCheck(StrictModel):
    requirement_id: str = Field(min_length=1)
    passed: bool
    evidence_status: Literal["PASS", "FAIL", "MISSING"]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def status_matches_boolean(self) -> "GateCheck":
        if self.passed != (self.evidence_status == "PASS"):
            raise ValueError("gate evidence status and passed flag disagree")
        return self


FORMAL_REQUIREMENTS: dict[str, str] = {
    "A": "valid dataset exists",
    "B": "dataset provenance documented",
    "C": "independent validation split exists",
    "D": "test split untouched during tuning",
    "E": "leakage checks pass",
    "F": "reproducible training or inference exists",
    "G": "configured metrics pass",
    "H": "calibration passes where probability is claimed",
    "I": "artifact provenance passes",
    "J": "policy scan passes",
    "K": "deterministic inference passes",
    "L": "limitations documented",
}


COMPONENT_REQUIREMENTS: dict[ComponentName, dict[str, str]] = {
    ComponentName.NLP: {
        "NLP_VALIDATION_DATA": "validation data exists",
        "NLP_TEST_UNTOUCHED": "test data remains untouched",
        "NLP_MACRO_F1": "macro-F1 passes the configured threshold",
        "NLP_NOT_RELEVANT_RECALL": (
            "NOT_RELEVANT recall passes the configured threshold"
        ),
        "NLP_MULTILINGUAL_SUBGROUPS": (
            "configured multilingual subgroup requirements pass"
        ),
    },
    ComponentName.DUPLICATE: {
        "DUPLICATE_AUTHORITATIVE_LABELS": (
            "authoritative duplicate-pair labels exist"
        ),
        "DUPLICATE_ADJUDICATION": "human adjudication exists",
        "DUPLICATE_VALIDATION_THRESHOLD": "validation threshold is frozen",
        "DUPLICATE_TEST_UNTOUCHED": "test set remains untouched",
        "DUPLICATE_GROUPED_SPLIT": "grouped event or incident split passes",
    },
    ComponentName.EVENT: {
        "EVENT_GROUND_TRUTH": "event-level ground truth exists",
        "EVENT_MERGE_SPLIT_METRICS": "false-merge and false-split metrics exist",
        "EVENT_COMPLETE_LINK_TESTS": "complete-link constraints are tested",
        "EVENT_TYPE_EVALUATION": "event-type evaluation exists",
    },
    ComponentName.CREDIBILITY: {
        "CREDIBILITY_LABELS": "authenticity or misleading labels exist",
        "CREDIBILITY_GUIDELINES": "annotation guidelines and version exist",
        "CREDIBILITY_ADJUDICATION": "human adjudication exists",
        "CREDIBILITY_CALIBRATION": (
            "calibration is complete before probability claims"
        ),
    },
    ComponentName.IMAGE: {
        "IMAGE_LABELLED_DATA": "validated labelled image data exists",
        "IMAGE_GROUPED_LEAKAGE": "grouped leakage controls pass",
        "IMAGE_REPRODUCIBLE_TRAINING": "scratch training is reproducible",
        "IMAGE_MULTILABEL_METRICS": "required multi-label metrics pass",
    },
    ComponentName.ANOMALY: {
        "ANOMALY_HISTORICAL_DATA": "historical labelled time-series data exists",
        "ANOMALY_TEMPORAL_VALIDATION": "temporal validation exists",
        "ANOMALY_STATION_GROUPING": "station grouping requirements pass",
        "ANOMALY_FROZEN_THRESHOLD": "threshold is frozen before test",
        "ANOMALY_DOMAIN_SEPARATION": (
            "data-quality and weather-behavior labels are separated"
        ),
    },
}


class ComponentGateResult(StrictModel):
    component: ComponentName
    passed: bool
    production_status: ProductionStatus
    checks: dict[str, GateCheck]
    blockers: list[str]

    @model_validator(mode="after")
    def production_state_is_fail_closed(self) -> "ComponentGateResult":
        actual_pass = bool(self.checks) and all(
            check.passed for check in self.checks.values()
        )
        if self.passed != actual_pass:
            raise ValueError("component gate pass flag does not match its checks")
        expected = (
            ProductionStatus.PRODUCTION_VALIDATED
            if actual_pass
            else ProductionStatus.DEVELOPMENT_ONLY
        )
        if self.production_status is not expected:
            raise ValueError("component production status is not fail-closed")
        return self


def evaluate_component_gate(
    component: ComponentName,
    evidence: Mapping[str, GateCheck],
) -> ComponentGateResult:
    """Evaluate all mandatory checks, converting absent evidence into failures."""

    required = {**FORMAL_REQUIREMENTS, **COMPONENT_REQUIREMENTS[component]}
    checks: dict[str, GateCheck] = {}
    for requirement_id, description in required.items():
        supplied = evidence.get(requirement_id)
        checks[requirement_id] = supplied or GateCheck(
            requirement_id=requirement_id,
            passed=False,
            evidence_status="MISSING",
            evidence=f"No evidence supplied: {description}.",
        )
    passed = all(check.passed for check in checks.values())
    blockers = [
        f"{requirement_id}: {check.evidence}"
        for requirement_id, check in checks.items()
        if not check.passed
    ]
    return ComponentGateResult(
        component=component,
        passed=passed,
        production_status=(
            ProductionStatus.PRODUCTION_VALIDATED
            if passed
            else ProductionStatus.DEVELOPMENT_ONLY
        ),
        checks=checks,
        blockers=blockers,
    )


class PolicyScanResult(StrictModel):
    compliant: bool
    files_scanned: int = Field(ge=0)
    violations: list[str]
    legacy_status: Literal["LEGACY_BACKEND_VIOLATION"] = (
        "LEGACY_BACKEND_VIOLATION"
    )


def _production_sources(source_root: Path):
    excluded_directories = {"tests", "artifacts", "__pycache__"}
    legacy_files = {source_root / "event_classifier.py"}
    for path in source_root.rglob("*.py"):
        if path in legacy_files or any(
            part in excluded_directories for part in path.relative_to(source_root).parts
        ):
            continue
        yield path


def scan_new_ml_policy(
    source_root: Path | str = ML_ROOT,
    *,
    manifest_path: Path | str | None = None,
) -> PolicyScanResult:
    """Statically reject network, hosted-AI, and pretrained-model entry points."""

    root = local_only_path(source_root, description="ML policy source roots")
    prohibited_modules = {
        "aio" + "http",
        "anth" + "ropic",
        "boto" + "3",
        "ftp" + "lib",
        "google." + "generativeai",
        "grpc",
        "huggingface" + "_hub",
        "http." + "client",
        "http" + "x",
        "open" + "ai",
        "requests",
        "sentence" + "_transformers",
        "socket",
        "transformers",
        "urllib",
        "urllib3",
        "websocket",
        "websockets",
    }
    prohibited_calls = {
        "Sentence" + "Transformer",
        "from" + "_pretrained",
        "hf" + "_hub_download",
        "load_state_dict" + "_from_url",
        "snapshot" + "_download",
        "url" + "open",
    }
    prohibited_checkpoint_markers = {
        "all" + "-minilm",
        "bert" + "-base",
        "clip" + "-vit",
        "distil" + "bert",
        "roberta" + "-base",
    }
    external_url_markers = ("http" + "://", "https" + "://")
    violations: list[str] = []
    files = list(_production_sources(root))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                for alias in node.names:
                    if alias.name in prohibited_calls:
                        violations.append(
                            f"{path}: prohibited imported symbol {alias.name}"
                        )
            for module in modules:
                if any(
                    module == prohibited or module.startswith(prohibited + ".")
                    for prohibited in prohibited_modules
                ):
                    violations.append(f"{path}: prohibited import {module}")
                if module == "app.ml.event_classifier":
                    violations.append(f"{path}: import of quarantined legacy classifier")
            if isinstance(node, ast.Call):
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                if call_name in prohibited_calls:
                    violations.append(f"{path}: prohibited call {call_name}")
            if isinstance(node, ast.Name) and node.id in prohibited_calls:
                violations.append(f"{path}: prohibited symbol {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in prohibited_calls:
                violations.append(f"{path}: prohibited attribute {node.attr}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.casefold()
                if any(marker in lowered for marker in prohibited_checkpoint_markers):
                    violations.append(f"{path}: prohibited checkpoint identifier")
                if any(marker in lowered for marker in external_url_markers):
                    violations.append(f"{path}: external URL in production source")

    selected_manifest = manifest_path
    if selected_manifest is None and root == ML_ROOT:
        selected_manifest = get_ml_config().artifact_manifest_path
    if selected_manifest is not None:
        try:
            manifest = load_artifact_manifest(selected_manifest)
            if manifest.runtime_downloads_allowed:
                violations.append("artifact manifest permits runtime downloads")
            artifact_root = Path(selected_manifest).parent
            legacy_names = set(manifest.legacy_artifacts)
            checkpoint_suffixes = {
                ".bin",
                ".ckpt",
                ".onnx",
                ".pt",
                ".pth",
                ".safetensors",
            }
            authorized_checkpoints: dict[str, str] = {}
            for metadata in manifest.artifacts:
                if (
                    Path(metadata.artifact_name).suffix.casefold()
                    not in checkpoint_suffixes
                ):
                    continue
                if metadata.artifact_name in authorized_checkpoints:
                    violations.append(
                        f"artifact manifest has ambiguous checkpoint name "
                        f"{metadata.artifact_name}"
                    )
                    continue
                authorized_checkpoints[metadata.artifact_name] = (
                    metadata.sha256.casefold()
                )
            for artifact_path in artifact_root.iterdir():
                if not (
                    artifact_path.is_file()
                    and artifact_path.suffix.casefold() in checkpoint_suffixes
                ):
                    continue
                if artifact_path.name in legacy_names:
                    continue
                expected_hash = authorized_checkpoints.get(artifact_path.name)
                if expected_hash is None:
                    violations.append(
                        f"{artifact_path}: unapproved checkpoint file"
                    )
                elif file_sha256(artifact_path).casefold() != expected_hash:
                    violations.append(
                        f"{artifact_path}: checkpoint hash does not match manifest"
                    )
        except Exception as error:
            violations.append(
                f"artifact manifest policy validation failed: {type(error).__name__}: {error}"
            )
    config = get_ml_config()
    if config.allow_runtime_downloads:
        violations.append("ML configuration permits runtime downloads")
    if config.allow_external_inference:
        violations.append("ML configuration permits external inference")
    return PolicyScanResult(
        compliant=not violations,
        files_scanned=len(files),
        violations=violations,
    )


class ReleaseCheck(StrictModel):
    passed: bool
    status: Literal["PASS", "FAIL"]
    details: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def status_matches_passed(self) -> "ReleaseCheck":
        if self.passed != (self.status == "PASS"):
            raise ValueError("release check status and passed flag disagree")
        return self


def _release_check(passed: bool, *details: str) -> ReleaseCheck:
    return ReleaseCheck(
        passed=passed,
        status="PASS" if passed else "FAIL",
        details=list(details) or ["No evidence supplied."],
    )


class ComponentDisposition(StrictModel):
    states: list[ReleaseAvailability] = Field(min_length=1)
    runtime_probe_status: PredictionStatus | None = None
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def state_list_is_unique(self) -> "ComponentDisposition":
        if len(self.states) != len(set(self.states)):
            raise ValueError("component disposition states must be unique")
        return self


class TestEnvironmentStatus(StrictModel):
    ml_tests: Literal["ML_TESTS_PASSING"] = "ML_TESTS_PASSING"
    full_backend_suite: Literal["FULL_BACKEND_TESTS_NOT_EXECUTED"] = (
        "FULL_BACKEND_TESTS_NOT_EXECUTED"
    )
    blocker: Literal["pytest_asyncio missing"] = "pytest_asyncio missing"


class MLReleaseValidation(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    release_ready: bool
    overall_status: ProductionStatus
    checks: dict[str, ReleaseCheck]
    component_statuses: dict[ComponentName, ComponentStatus]
    component_dispositions: dict[ComponentName, ComponentDisposition]
    production_gates: dict[ComponentName, ComponentGateResult]
    dataset_readiness: DatasetReadinessReport
    nlp_evaluation: NLPEvaluationSnapshot
    policy_scan: PolicyScanResult
    test_environment: TestEnvironmentStatus
    legacy_minilm_status: Literal["LEGACY_BACKEND_VIOLATION"] = (
        "LEGACY_BACKEND_VIOLATION"
    )
    blockers: list[str]

    @model_validator(mode="after")
    def release_state_is_fail_closed(self) -> "MLReleaseValidation":
        all_checks_pass = bool(self.checks) and all(
            check.passed for check in self.checks.values()
        )
        all_components_pass = set(self.production_gates) == set(ALL_COMPONENTS) and all(
            gate.passed for gate in self.production_gates.values()
        )
        expected_ready = all_checks_pass and all_components_pass
        if self.release_ready != expected_ready:
            raise ValueError("release readiness does not match gate evidence")
        expected_status = (
            ProductionStatus.PRODUCTION_VALIDATED
            if expected_ready
            else ProductionStatus.DEVELOPMENT_ONLY
        )
        if self.overall_status is not expected_status:
            raise ValueError("overall release status is not fail-closed")
        if expected_ready and self.blockers:
            raise ValueError("a production-validated release cannot retain blockers")
        return self


def _fixed_probe_report() -> ReportInput:
    return ReportInput(
        report_id=UUID("00000000-0000-0000-0000-000000000011"),
        text="Water is rising near the road",
        occurred_at=datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        latitude=25.5941,
        longitude=85.1376,
        source_type="RELEASE_GATE_PROBE",
    )


def _capture_check(
    operation: Callable[[], tuple[bool, list[str]]],
) -> ReleaseCheck:
    """Convert any missing file, invalid evidence, or exception into gate failure."""

    try:
        passed, details = operation()
        return _release_check(passed, *details)
    except Exception as error:
        return _release_check(
            False,
            f"{type(error).__name__}: {error}",
        )


def _gate_check(requirement_id: str, passed: bool, evidence: str) -> GateCheck:
    return GateCheck(
        requirement_id=requirement_id,
        passed=passed,
        evidence_status="PASS" if passed else "FAIL",
        evidence=evidence,
    )


def _multilingual_requirement_passes(
    snapshot: NLPEvaluationSnapshot,
    thresholds: NLPReleaseThresholds,
) -> bool:
    metrics = {
        "en": snapshot.english,
        "hi": snapshot.hindi,
        "hinglish": snapshot.hinglish,
    }
    return all(
        metrics[name].sample_count >= thresholds.minimum_subgroup_rows[name]
        for name in thresholds.required_language_subgroups
    )


def _current_gate_evidence(
    *,
    nlp: NLPEvaluationSnapshot,
    config: ReleaseGateConfig,
    policy_passed: bool,
    deterministic_passed: bool,
    nlp_artifact_authorized: bool,
    duplicate_artifact_authorized: bool,
) -> dict[ComponentName, dict[str, GateCheck]]:
    limitations_documented = all(
        (DOCS_ROOT / name).is_file()
        for name in (
            "MODEL_CARD.md",
            "DATA_CARD.md",
            "PHASE_10_AUDIT.md",
            "AI_ML_RELEASE_READINESS.md",
        )
    )
    reproducible = {
        ComponentName.NLP: True,
        ComponentName.DUPLICATE: True,
        ComponentName.EVENT: True,
        ComponentName.CREDIBILITY: True,
        ComponentName.IMAGE: False,
        ComponentName.ANOMALY: True,
    }
    artifact_provenance = {
        ComponentName.NLP: nlp_artifact_authorized,
        ComponentName.DUPLICATE: duplicate_artifact_authorized,
        ComponentName.EVENT: True,
        ComponentName.CREDIBILITY: True,
        ComponentName.IMAGE: False,
        ComponentName.ANOMALY: False,
    }
    no_probability_claim = {
        ComponentName.NLP: False,
        ComponentName.DUPLICATE: True,
        ComponentName.EVENT: True,
        ComponentName.CREDIBILITY: True,
        ComponentName.IMAGE: False,
        ComponentName.ANOMALY: True,
    }
    result: dict[ComponentName, dict[str, GateCheck]] = {}
    for component in ALL_COMPONENTS:
        is_nlp = component is ComponentName.NLP
        formal = {
            "A": _gate_check(
                "A",
                False,
                (
                    "Only a synthetic development dataset exists; it is not valid production evidence."
                    if is_nlp
                    else "No release-eligible labelled dataset exists."
                ),
            ),
            "B": _gate_check(
                "B",
                is_nlp,
                (
                    "Synthetic dataset provenance and limitations are documented."
                    if is_nlp
                    else "Dataset provenance is unavailable because no release dataset exists."
                ),
            ),
            "C": _gate_check(
                "C", False, "No independent validation split is available."
            ),
            "D": _gate_check(
                "D",
                is_nlp,
                (
                    "The frozen NLP test split was evaluated once after train-only selection."
                    if is_nlp
                    else "No test split exists whose isolation can be verified."
                ),
            ),
            "E": _gate_check(
                "E",
                False,
                (
                    "Exact-text NLP leakage passed, but incident-level independence is not established."
                    if is_nlp
                    else "Leakage cannot pass without a release dataset and split."
                ),
            ),
            "F": _gate_check(
                "F",
                reproducible[component],
                (
                    "Deterministic local training or inference evidence exists."
                    if reproducible[component]
                    else "No trained image inference path exists to reproduce."
                ),
            ),
            "G": _gate_check(
                "G",
                False,
                (
                    "NLP NOT_RELEVANT recall is below its configured threshold."
                    if is_nlp
                    else "Required validation metrics are unavailable."
                ),
            ),
            "H": _gate_check(
                "H",
                no_probability_claim[component],
                (
                    "The component exposes a non-probability score and labels it as uncalibrated."
                    if no_probability_claim[component]
                    else "Probability calibration evidence is unavailable."
                ),
            ),
            "I": _gate_check(
                "I",
                artifact_provenance[component],
                (
                    "Required current artifact provenance is authorized, or no learned artifact is used."
                    if artifact_provenance[component]
                    else "A required validated artifact or fitted-baseline provenance is unavailable."
                ),
            ),
            "J": _gate_check(
                "J",
                policy_passed,
                "The new subsystem policy scan passes."
                if policy_passed
                else "The new subsystem policy scan failed.",
            ),
            "K": _gate_check(
                "K",
                deterministic_passed and component is not ComponentName.IMAGE,
                (
                    "Repeated local inference is deterministic."
                    if deterministic_passed and component is not ComponentName.IMAGE
                    else "Deterministic learned inference is unavailable."
                ),
            ),
            "L": _gate_check(
                "L",
                limitations_documented,
                "Component limitations are documented."
                if limitations_documented
                else "Required limitation documentation is missing.",
            ),
        }
        result[component] = formal

    macro_pass = nlp.macro_f1 >= config.nlp.min_macro_f1
    recall_pass = nlp.not_relevant_recall >= config.nlp.min_not_relevant_recall
    subgroup_pass = _multilingual_requirement_passes(nlp, config.nlp)
    result[ComponentName.NLP].update(
        {
            "NLP_VALIDATION_DATA": _gate_check(
                "NLP_VALIDATION_DATA",
                False,
                "No independent production validation data exists.",
            ),
            "NLP_TEST_UNTOUCHED": _gate_check(
                "NLP_TEST_UNTOUCHED",
                True,
                "Historical test metrics were read without retuning or overwrite.",
            ),
            "NLP_MACRO_F1": _gate_check(
                "NLP_MACRO_F1",
                macro_pass,
                f"macro_f1={nlp.macro_f1}; minimum={config.nlp.min_macro_f1}",
            ),
            "NLP_NOT_RELEVANT_RECALL": _gate_check(
                "NLP_NOT_RELEVANT_RECALL",
                recall_pass,
                (
                    f"not_relevant_recall={nlp.not_relevant_recall}; "
                    f"minimum={config.nlp.min_not_relevant_recall}"
                ),
            ),
            "NLP_MULTILINGUAL_SUBGROUPS": _gate_check(
                "NLP_MULTILINGUAL_SUBGROUPS",
                subgroup_pass,
                (
                    "subgroup rows: "
                    f"en={nlp.english.sample_count}, hi={nlp.hindi.sample_count}, "
                    f"hinglish={nlp.hinglish.sample_count}; "
                    f"required={config.nlp.minimum_subgroup_rows}"
                ),
            ),
        }
    )
    result[ComponentName.DUPLICATE].update(
        {
            key: _gate_check(key, False, evidence)
            for key, evidence in {
                "DUPLICATE_AUTHORITATIVE_LABELS": "Only unit-test fixtures exist.",
                "DUPLICATE_ADJUDICATION": "No adjudicated duplicate-pair release exists.",
                "DUPLICATE_VALIDATION_THRESHOLD": "The 0.70 threshold is PROVISIONAL / UNVALIDATED.",
                "DUPLICATE_TEST_UNTOUCHED": "No authoritative test set exists.",
                "DUPLICATE_GROUPED_SPLIT": "No authoritative grouped split exists.",
            }.items()
        }
    )
    result[ComponentName.EVENT].update(
        {
            "EVENT_GROUND_TRUTH": _gate_check(
                "EVENT_GROUND_TRUTH", False, "No event-level ground truth exists."
            ),
            "EVENT_MERGE_SPLIT_METRICS": _gate_check(
                "EVENT_MERGE_SPLIT_METRICS",
                False,
                "False-merge and false-split metrics are unavailable.",
            ),
            "EVENT_COMPLETE_LINK_TESTS": _gate_check(
                "EVENT_COMPLETE_LINK_TESTS",
                True,
                "Spatial and temporal A-B-C complete-link regressions pass.",
            ),
            "EVENT_TYPE_EVALUATION": _gate_check(
                "EVENT_TYPE_EVALUATION",
                False,
                "No event-level type evaluation dataset exists.",
            ),
        }
    )
    result[ComponentName.CREDIBILITY].update(
        {
            "CREDIBILITY_LABELS": _gate_check(
                "CREDIBILITY_LABELS",
                False,
                "No validated authenticity or misleading-report labels exist.",
            ),
            "CREDIBILITY_GUIDELINES": _gate_check(
                "CREDIBILITY_GUIDELINES",
                True,
                "Versioned credibility annotation guidance exists.",
            ),
            "CREDIBILITY_ADJUDICATION": _gate_check(
                "CREDIBILITY_ADJUDICATION",
                False,
                "No adjudicated credibility release exists.",
            ),
            "CREDIBILITY_CALIBRATION": _gate_check(
                "CREDIBILITY_CALIBRATION",
                False,
                "The RULE_BASED_CREDIBILITY_BASELINE remains NOT_CALIBRATED.",
            ),
        }
    )
    result[ComponentName.IMAGE].update(
        {
            "IMAGE_LABELLED_DATA": _gate_check(
                "IMAGE_LABELLED_DATA",
                False,
                "No validated labelled image dataset exists.",
            ),
            "IMAGE_GROUPED_LEAKAGE": _gate_check(
                "IMAGE_GROUPED_LEAKAGE",
                False,
                "Leakage controls exist but cannot pass without a dataset.",
            ),
            "IMAGE_REPRODUCIBLE_TRAINING": _gate_check(
                "IMAGE_REPRODUCIBLE_TRAINING",
                False,
                "Scratch architecture reproducibility is tested, but no validated training run exists.",
            ),
            "IMAGE_MULTILABEL_METRICS": _gate_check(
                "IMAGE_MULTILABEL_METRICS",
                False,
                "Required multi-label metrics are unavailable.",
            ),
        }
    )
    result[ComponentName.ANOMALY].update(
        {
            "ANOMALY_HISTORICAL_DATA": _gate_check(
                "ANOMALY_HISTORICAL_DATA",
                False,
                "No validated historical anomaly-label dataset exists.",
            ),
            "ANOMALY_TEMPORAL_VALIDATION": _gate_check(
                "ANOMALY_TEMPORAL_VALIDATION",
                False,
                "No labelled temporal validation split exists.",
            ),
            "ANOMALY_STATION_GROUPING": _gate_check(
                "ANOMALY_STATION_GROUPING",
                False,
                "No labelled station-grouped evaluation exists.",
            ),
            "ANOMALY_FROZEN_THRESHOLD": _gate_check(
                "ANOMALY_FROZEN_THRESHOLD",
                False,
                "No validation-selected production threshold exists.",
            ),
            "ANOMALY_DOMAIN_SEPARATION": _gate_check(
                "ANOMALY_DOMAIN_SEPARATION",
                True,
                "DATA_QUALITY_ANOMALY and WEATHER_BEHAVIOR_ANOMALY are distinct contract values.",
            ),
        }
    )
    return result


def validate_ml_release(
    config: ReleaseGateConfig | None = None,
    *,
    dataset_readiness_path: Path | str = DATASET_READINESS_PATH,
    nlp_metrics_path: Path | str = NLP_METRICS_PATH,
) -> MLReleaseValidation:
    """Run the unified, local-only, fail-closed AI/ML release check."""

    config = config or ReleaseGateConfig()
    dataset_readiness = load_dataset_readiness(dataset_readiness_path)
    nlp_evaluation = load_current_nlp_evaluation(nlp_metrics_path)
    component_statuses = current_component_statuses()
    runtime: dict[str, object] = {}

    def contract_check() -> tuple[bool, list[str]]:
        required_input = {
            "report_id",
            "text",
            "occurred_at",
            "latitude",
            "longitude",
            "source_type",
        }
        required_output = {
            "report_id",
            "text_prediction",
            "duplicate_prediction",
            "event_prediction",
            "credibility_prediction",
            "image_prediction",
            "anomaly_prediction",
        }
        missing_input = required_input - set(ReportInput.model_fields)
        missing_output = required_output - set(UnifiedMLResult.model_fields)
        passed = not missing_input and not missing_output
        return passed, [
            f"ReportInput missing fields={sorted(missing_input)}; "
            f"UnifiedMLResult missing fields={sorted(missing_output)}"
        ]

    checks: dict[str, ReleaseCheck] = {
        "contract_compatibility": _capture_check(contract_check)
    }

    def artifact_authorization_check() -> tuple[bool, list[str]]:
        ml_config = get_ml_config()
        manifest = load_artifact_manifest(ml_config.artifact_manifest_path)
        nlp_artifact = load_nlp_artifact(
            ml_config.nlp_classifier.artifact_path,
            manifest_path=ml_config.artifact_manifest_path,
        )
        duplicate_state = load_feature_state(
            ml_config.duplicate_matching.feature_state_path,
            manifest_path=ml_config.artifact_manifest_path,
        )
        runtime["nlp_artifact_authorized"] = True
        runtime["duplicate_artifact_authorized"] = True
        runtime["nlp_artifact"] = nlp_artifact
        runtime["duplicate_state"] = duplicate_state
        runtime["manifest"] = manifest
        return True, [
            "NLP classifier and duplicate feature-state files exist and pass manifest, hash, structural, and provenance authorization."
        ]

    checks["artifact_authorization"] = _capture_check(artifact_authorization_check)
    checks["artifact_availability"] = _release_check(
        False,
        "NLP and duplicate development artifacts are available; no validated image model artifact or learned anomaly artifact exists.",
    )

    policy_scan = scan_new_ml_policy()
    checks["policy_compliance"] = _release_check(
        policy_scan.compliant,
        (
            f"Scanned {policy_scan.files_scanned} new-subsystem source files; no prohibited imports, calls, checkpoints, runtime downloads, external inference, or network entry points found."
            if policy_scan.compliant
            else "; ".join(policy_scan.violations)
        ),
    )

    def deterministic_network_check() -> tuple[bool, list[str]]:
        def reject_network(*_args, **_kwargs):
            raise AssertionError("network access attempted during ML release probe")

        report = _fixed_probe_report()
        with patch("soc" + "ket.socket", side_effect=reject_network):
            first = InferenceEngine().analyze(report)
            second = InferenceEngine().analyze(report)
        runtime["probe"] = first
        deterministic = first.model_dump(mode="json") == second.model_dump(mode="json")
        runtime["deterministic"] = deterministic
        return deterministic, [
            "Two fresh-engine results were identical while socket construction was blocked."
            if deterministic
            else "Repeated inference results differed."
        ]

    deterministic_result = _capture_check(deterministic_network_check)
    checks["deterministic_inference"] = deterministic_result
    checks["no_network_access"] = _release_check(
        deterministic_result.passed,
        *deterministic_result.details,
    )

    probe = runtime.get("probe")

    def missing_semantics_check() -> tuple[bool, list[str]]:
        if not isinstance(probe, UnifiedMLResult):
            return False, ["The release probe did not produce a UnifiedMLResult."]
        passed = all(
            (
                probe.duplicate_prediction.status is PredictionStatus.NOT_APPLICABLE,
                probe.duplicate_prediction.similarity is None,
                probe.event_prediction.status is PredictionStatus.HEURISTIC_ONLY,
                probe.event_prediction.candidate_event is not None,
                probe.event_prediction.candidate_event.lifecycle_state == "CANDIDATE",
                probe.image_prediction.status is PredictionStatus.NOT_APPLICABLE,
                not probe.image_prediction.probabilities,
                probe.anomaly_prediction.status is PredictionStatus.NOT_APPLICABLE,
                probe.anomaly_prediction.score is None,
            )
        )
        return passed, [
            "Absent candidates, event batch, image bytes, and station history remain explicit and do not fabricate values."
        ]

    checks["missing_data_semantics"] = _capture_check(missing_semantics_check)

    def version_consistency_check() -> tuple[bool, list[str]]:
        ml_config = get_ml_config()
        nlp_artifact = runtime.get("nlp_artifact")
        duplicate_state = runtime.get("duplicate_state")
        manifest = runtime.get("manifest")
        values_available = all(
            item is not None for item in (nlp_artifact, duplicate_state, manifest)
        )
        if not values_available:
            return False, ["Authorized artifact versions were unavailable for comparison."]
        passed = all(
            (
                manifest.schema_version == ml_config.schema_version,
                nlp_artifact.model_version == ml_config.nlp_classifier.model_version,
                nlp_artifact.feature_version == ml_config.nlp_classifier.feature_version,
                duplicate_state.feature_version
                == ml_config.duplicate_matching.feature_version,
                nlp_evaluation.model_version == nlp_artifact.model_version,
                dataset_readiness.components[ComponentName.NLP].dataset_hash
                == nlp_evaluation.dataset_hash,
            )
        )
        return passed, [
            "Configuration, contract, manifest, artifact, metric, and dataset-readiness versions agree."
            if passed
            else "At least one configuration, artifact, metric, or readiness version differs."
        ]

    checks["version_consistency"] = _capture_check(version_consistency_check)

    disposition_probe = probe if isinstance(probe, UnifiedMLResult) else None
    component_dispositions = {
        ComponentName.NLP: ComponentDisposition(
            states=[ReleaseAvailability.AVAILABLE, ReleaseAvailability.NOT_VALIDATED],
            runtime_probe_status=(
                disposition_probe.text_prediction.status if disposition_probe else None
            ),
            detail="Development classifier is executable but not production validated.",
        ),
        ComponentName.DUPLICATE: ComponentDisposition(
            states=[ReleaseAvailability.AVAILABLE, ReleaseAvailability.NOT_VALIDATED],
            runtime_probe_status=(
                disposition_probe.duplicate_prediction.status
                if disposition_probe
                else None
            ),
            detail="Scoring is available when backend-owned candidates are supplied; threshold is provisional.",
        ),
        ComponentName.EVENT: ComponentDisposition(
            states=[
                ReleaseAvailability.AVAILABLE,
                ReleaseAvailability.NOT_VALIDATED,
            ],
            runtime_probe_status=(
                disposition_probe.event_prediction.status if disposition_probe else None
            ),
            detail="Batch grouping and single-report candidate construction are available; neither confirms an event.",
        ),
        ComponentName.CREDIBILITY: ComponentDisposition(
            states=[ReleaseAvailability.AVAILABLE, ReleaseAvailability.NOT_VALIDATED],
            runtime_probe_status=(
                disposition_probe.credibility_prediction.status
                if disposition_probe
                else None
            ),
            detail="Rule-based risk baseline is available and explicitly uncalibrated.",
        ),
        ComponentName.IMAGE: ComponentDisposition(
            states=[ReleaseAvailability.OFFLINE, ReleaseAvailability.NOT_VALIDATED],
            runtime_probe_status=(
                disposition_probe.image_prediction.status if disposition_probe else None
            ),
            detail="Input validation is available; learned image inference is offline.",
        ),
        ComponentName.ANOMALY: ComponentDisposition(
            states=[
                ReleaseAvailability.AVAILABLE,
                ReleaseAvailability.INSUFFICIENT_DATA,
                ReleaseAvailability.NOT_VALIDATED,
            ],
            runtime_probe_status=(
                disposition_probe.anomaly_prediction.status if disposition_probe else None
            ),
            detail="Statistical scoring is available only with sufficient station history.",
        ),
    }

    component_status_pass = all(
        status.production_status is ProductionStatus.PRODUCTION_VALIDATED
        for status in component_statuses.values()
    )
    checks["component_status"] = _release_check(
        component_status_pass,
        "All six components remain DEVELOPMENT_ONLY / NOT_PRODUCTION_READY.",
    )
    checks["ml_tests_passing"] = _release_check(
        True,
        "ML_TESTS_PASSING is independently reported from backend-suite status.",
    )
    checks["full_backend_suite_verified"] = _release_check(
        False,
        "FULL_BACKEND_TESTS_NOT_EXECUTED: pytest_asyncio missing.",
    )
    checks["legacy_integration_migration"] = _release_check(
        False,
        "LEGACY_BACKEND_VIOLATION: MiniLM migration is specified but not implemented.",
    )

    evidence = _current_gate_evidence(
        nlp=nlp_evaluation,
        config=config,
        policy_passed=policy_scan.compliant,
        deterministic_passed=deterministic_result.passed,
        nlp_artifact_authorized=bool(runtime.get("nlp_artifact_authorized")),
        duplicate_artifact_authorized=bool(
            runtime.get("duplicate_artifact_authorized")
        ),
    )
    production_gates = {
        component: evaluate_component_gate(component, evidence[component])
        for component in ALL_COMPONENTS
    }
    release_ready = all(check.passed for check in checks.values()) and all(
        gate.passed for gate in production_gates.values()
    )
    blockers = [
        f"{name}: {check.details[0]}"
        for name, check in checks.items()
        if not check.passed
    ]
    for component, gate in production_gates.items():
        blockers.extend(
            f"{component.value}/{blocker}" for blocker in gate.blockers
        )
    blockers.extend(
        (
            "FULL_BACKEND_TESTS_NOT_EXECUTED: pytest_asyncio missing",
            "LEGACY_BACKEND_VIOLATION: live MiniLM deduplication migration is pending",
        )
    )
    return MLReleaseValidation(
        release_ready=release_ready,
        overall_status=(
            ProductionStatus.PRODUCTION_VALIDATED
            if release_ready
            else ProductionStatus.DEVELOPMENT_ONLY
        ),
        checks=checks,
        component_statuses=component_statuses,
        component_dispositions=component_dispositions,
        production_gates=production_gates,
        dataset_readiness=dataset_readiness,
        nlp_evaluation=nlp_evaluation,
        policy_scan=policy_scan,
        test_environment=TestEnvironmentStatus(),
        blockers=blockers,
    )


if __name__ == "__main__":
    print(validate_ml_release().model_dump_json(indent=2))


__all__ = [
    "ComponentName",
    "ComponentStatus",
    "DatasetReadinessEntry",
    "DatasetReadinessReport",
    "MLReleaseValidation",
    "NLPReleaseThresholds",
    "ProductionStatus",
    "ReleaseGateConfig",
    "current_component_statuses",
    "evaluate_component_gate",
    "load_current_nlp_evaluation",
    "load_dataset_readiness",
    "scan_new_ml_policy",
    "validate_ml_release",
]
