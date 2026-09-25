"""Fail-closed registry authorization required before any model fitting."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.ml.data.dataset_validation import CheckStatus
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    AnomalyDataRole,
    DatasetClassification,
    DatasetComponent,
    DatasetProvenance,
    DatasetRegistryRecord,
    DatasetStatus,
    DatasetUse,
    find_dataset,
    hash_dataset_path,
    load_bound_validation_report,
    load_dataset_registry,
    resolve_registry_path,
)


class TrainingGateReason(str, Enum):
    DATASET_UNREGISTERED = "DATASET_UNREGISTERED"
    DATASET_VERSION_AMBIGUOUS = "DATASET_VERSION_AMBIGUOUS"
    COMPONENT_MISMATCH = "COMPONENT_MISMATCH"
    DATASET_PATH_MISMATCH = "DATASET_PATH_MISMATCH"
    DATASET_HASH_MISMATCH = "DATASET_HASH_MISMATCH"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"
    LEAKAGE_FAILURE = "LEAKAGE_FAILURE"
    LEAKAGE_INSUFFICIENT_EVIDENCE = "LEAKAGE_INSUFFICIENT_EVIDENCE"
    WRONG_SPLIT = "WRONG_SPLIT"
    INSUFFICIENT_LABELS = "INSUFFICIENT_LABELS"
    TEST_CONTAMINATION = "TEST_CONTAMINATION"
    APPROVAL_MISSING = "APPROVAL_MISSING"
    APPROVAL_STALE = "APPROVAL_STALE"
    VALIDATION_REPORT_INVALID = "VALIDATION_REPORT_INVALID"
    DATASET_STATUS_BLOCKED = "DATASET_STATUS_BLOCKED"
    DATASET_CLASSIFICATION_BLOCKED = "DATASET_CLASSIFICATION_BLOCKED"


class TrainingGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    dataset_id: str
    dataset_version: str | None = None
    expected_component: DatasetComponent
    resolved_path: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class DatasetTrainingGateError(ValueError):
    def __init__(self, decision: TrainingGateDecision) -> None:
        self.decision = decision
        super().__init__(
            "TRAINING_DATASET_BLOCKED: "
            + ", ".join(decision.reason_codes or ["UNKNOWN_REASON"])
        )


def evaluate_training_dataset(
    dataset_id: str,
    expected_component: DatasetComponent,
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_version: str | None = None,
    supplied_path: Path | str | None = None,
    require_evaluation_approvals: bool = True,
) -> TrainingGateDecision:
    """Recheck identity, bytes, validation, leakage, and explicit approvals."""

    reasons: list[str] = []
    details: list[str] = []
    record: DatasetRegistryRecord | None = None
    try:
        registry = load_dataset_registry(registry_path)
        record = find_dataset(registry, dataset_id, dataset_version)
    except KeyError as error:
        code = (
            TrainingGateReason.DATASET_VERSION_AMBIGUOUS
            if "ambiguous" in str(error)
            else TrainingGateReason.DATASET_UNREGISTERED
        )
        reasons.append(code.value)
        details.append(str(error))
    except Exception as error:  # noqa: BLE001 - gate must convert registry failures to denial
        reasons.append(TrainingGateReason.DATASET_UNREGISTERED.value)
        details.append(f"registry load failed: {type(error).__name__}: {error}")

    resolved_path: Path | None = None
    if record is not None:
        if record.component is not expected_component:
            reasons.append(TrainingGateReason.COMPONENT_MISMATCH.value)
            details.append(
                f"registered component={record.component.value}; expected={expected_component.value}"
            )
        if record.status in {
            DatasetStatus.DISCOVERED,
            DatasetStatus.VALIDATING,
            DatasetStatus.INVALID,
            DatasetStatus.QUARANTINED,
        }:
            reasons.append(TrainingGateReason.DATASET_STATUS_BLOCKED.value)
            details.append(f"dataset status={record.status.value}")
        if record.data_classification in {
            DatasetClassification.DEVELOPMENT_ONLY,
            DatasetClassification.TEST_FIXTURE_ONLY,
            DatasetClassification.PRODUCTION_TEST,
        }:
            reasons.append(TrainingGateReason.DATASET_CLASSIFICATION_BLOCKED.value)
            details.append(f"dataset classification={record.data_classification.value}")
            if record.data_classification is DatasetClassification.PRODUCTION_TEST:
                reasons.append(TrainingGateReason.TEST_CONTAMINATION.value)
        if record.provenance is DatasetProvenance.PROVENANCE_UNKNOWN:
            reasons.append(TrainingGateReason.PROVENANCE_UNKNOWN.value)
        try:
            resolved_path = resolve_registry_path(record.local_path, registry_path)
            current_hash = hash_dataset_path(resolved_path).content_sha256
            if current_hash != record.content_sha256:
                reasons.append(TrainingGateReason.DATASET_HASH_MISMATCH.value)
            if supplied_path is not None:
                supplied = Path(supplied_path).resolve()
                if supplied != resolved_path:
                    reasons.append(TrainingGateReason.DATASET_PATH_MISMATCH.value)
                    details.append(
                        f"supplied path={supplied}; registered path={resolved_path}"
                    )
        except Exception as error:  # noqa: BLE001 - any hash failure must deny training
            current_hash = None
            reasons.append(TrainingGateReason.DATASET_HASH_MISMATCH.value)
            details.append(
                f"dataset hash check failed: {type(error).__name__}: {error}"
            )

        try:
            report = load_bound_validation_report(record, registry_path)
            checks = {check.code: check for check in report.checks}
            schema_failed = any(
                checks.get(code) is not None and checks[code].status is CheckStatus.FAIL
                for code in (
                    "SCHEMA_AND_REQUIRED_FIELDS",
                    "NULL_AND_REQUIRED_VALUES",
                    "COORDINATE_VALIDITY",
                    "TIMESTAMP_VALIDITY",
                )
            )
            if schema_failed:
                reasons.append(TrainingGateReason.INVALID_SCHEMA.value)
            if not report.valid:
                reasons.append(TrainingGateReason.VALIDATION_REPORT_INVALID.value)
            if report.content_sha256 != record.content_sha256:
                reasons.append(TrainingGateReason.VALIDATION_REPORT_INVALID.value)
            if report.leakage.overall_status is CheckStatus.FAIL:
                reasons.append(TrainingGateReason.LEAKAGE_FAILURE.value)
            elif report.leakage.overall_status is CheckStatus.INSUFFICIENT_EVIDENCE:
                reasons.append(TrainingGateReason.LEAKAGE_INSUFFICIENT_EVIDENCE.value)
            contamination_checks = (
                report.leakage.exact_duplicate_leakage,
                report.leakage.near_duplicate_leakage,
                report.leakage.group_leakage,
                report.leakage.temporal_leakage,
                report.leakage.label_leakage,
                report.leakage.cross_split_overlap,
            )
            if any(
                check.required and check.status is CheckStatus.FAIL
                for check in contamination_checks
            ):
                reasons.append(TrainingGateReason.TEST_CONTAMINATION.value)
            all_blockers = [
                blocker
                for blockers in report.approval_blockers.values()
                for blocker in blockers
            ]
            training_blockers = report.approval_blockers.get(
                DatasetUse.TRAINING.value, []
            )
            if any("INSUFFICIENT_LABELS" in item for item in all_blockers):
                reasons.append(TrainingGateReason.INSUFFICIENT_LABELS.value)
            split_error = (
                any(
                    report.split_counts.get(name, 0) == 0
                    for name in ("train", "validation", "test")
                )
                or any("split" in error.casefold() for error in report.errors)
                or any("SPLIT" in item for item in all_blockers)
                or "INDEPENDENT_VALIDATION_AND_TEST_REQUIRED" in training_blockers
            )
            if split_error:
                reasons.append(TrainingGateReason.WRONG_SPLIT.value)
            details.extend(training_blockers)
        except Exception as error:  # noqa: BLE001 - malformed reports must deny training
            report = None
            reasons.append(TrainingGateReason.VALIDATION_REPORT_INVALID.value)
            details.append(
                f"bound validation report failed: {type(error).__name__}: {error}"
            )

        required_uses = [DatasetUse.TRAINING]
        unsupervised_anomaly_baseline = (
            record.component is DatasetComponent.ANOMALY
            and record.anomaly_data_role is AnomalyDataRole.UNSUPERVISED_BASELINE
        )
        if require_evaluation_approvals and not unsupervised_anomaly_baseline:
            required_uses.extend((DatasetUse.VALIDATION, DatasetUse.TEST))
        approvals = {approval.use: approval for approval in record.approvals}
        for use in required_uses:
            approval = approvals.get(use)
            if approval is None:
                reasons.append(
                    f"{TrainingGateReason.APPROVAL_MISSING.value}:{use.value}"
                )
                continue
            if (
                approval.content_sha256 != record.content_sha256
                or approval.validation_report_sha256 != record.validation_report_sha256
            ):
                reasons.append(f"{TrainingGateReason.APPROVAL_STALE.value}:{use.value}")

    unique_reasons = list(dict.fromkeys(reasons))
    unique_details = list(dict.fromkeys(details))
    return TrainingGateDecision(
        allowed=not unique_reasons,
        dataset_id=dataset_id,
        dataset_version=record.dataset_version if record else dataset_version,
        expected_component=expected_component,
        resolved_path=str(resolved_path) if resolved_path else None,
        reason_codes=unique_reasons,
        details=unique_details,
    )


def require_training_dataset(
    dataset_id: str,
    expected_component: DatasetComponent,
    **kwargs,
) -> TrainingGateDecision:
    decision = evaluate_training_dataset(
        dataset_id,
        expected_component,
        **kwargs,
    )
    if not decision.allowed:
        raise DatasetTrainingGateError(decision)
    return decision


__all__ = [
    "DatasetTrainingGateError",
    "TrainingGateDecision",
    "TrainingGateReason",
    "evaluate_training_dataset",
    "require_training_dataset",
]
