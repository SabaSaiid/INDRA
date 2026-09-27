"""Fail-closed local dataset registry, hashing, and explicit approval records."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.config import local_only_path

DEFAULT_DATASET_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "registry" / "datasets.json"
)


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetComponent(str, Enum):
    NLP = "NLP"
    DUPLICATE = "DUPLICATE"
    EVENT = "EVENT"
    CREDIBILITY = "CREDIBILITY"
    IMAGE = "IMAGE"
    ANOMALY = "ANOMALY"


class DatasetFormat(str, Enum):
    CSV = "CSV"
    JSON = "JSON"
    JSONL = "JSONL"
    PARQUET = "PARQUET"
    JPEG = "JPEG"
    PNG = "PNG"
    DIRECTORY = "DIRECTORY"
    ZIP = "ZIP"


class DatasetStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    APPROVED_TRAINING = "APPROVED_TRAINING"
    APPROVED_VALIDATION = "APPROVED_VALIDATION"
    APPROVED_TEST = "APPROVED_TEST"
    QUARANTINED = "QUARANTINED"


class DatasetProvenance(str, Enum):
    PROJECT_AUTHORED = "PROJECT_AUTHORED"
    USER_SUPPLIED = "USER_SUPPLIED"
    PUBLIC_DATASET_MANUALLY_ACQUIRED = "PUBLIC_DATASET_MANUALLY_ACQUIRED"
    OPERATIONAL_EXPORT = "OPERATIONAL_EXPORT"
    PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"


class DatasetClassification(str, Enum):
    CANDIDATE_DATA = "CANDIDATE_DATA"
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
    TEST_FIXTURE_ONLY = "TEST_FIXTURE_ONLY"
    PRODUCTION_TEST = "PRODUCTION_TEST"


class DatasetUse(str, Enum):
    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class AnomalyDataRole(str, Enum):
    UNSUPERVISED_BASELINE = "UNSUPERVISED_BASELINE"
    SUPERVISED_EVALUATION = "SUPERVISED_EVALUATION"


USE_TO_STATUS = {
    DatasetUse.TRAINING: DatasetStatus.APPROVED_TRAINING,
    DatasetUse.VALIDATION: DatasetStatus.APPROVED_VALIDATION,
    DatasetUse.TEST: DatasetStatus.APPROVED_TEST,
}
USE_TO_SPLIT = {
    DatasetUse.TRAINING: "train",
    DatasetUse.VALIDATION: "validation",
    DatasetUse.TEST: "test",
}


class DatasetHashEntry(RegistryModel):
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DatasetHashResult(RegistryModel):
    path: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    entries: list[DatasetHashEntry] = Field(default_factory=list)


class DatasetApproval(RegistryModel):
    use: DatasetUse
    approved_split: str
    approver_id: str = Field(min_length=1)
    approval_timestamp: datetime
    approval_note: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approver_id", "approval_note")
    @classmethod
    def explicit_approval_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval identity and note cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def approval_is_explicit_and_split_bound(self) -> DatasetApproval:
        if self.approval_timestamp.tzinfo is None:
            raise ValueError("approval timestamp must include a timezone")
        if self.approved_split != USE_TO_SPLIT[self.use]:
            raise ValueError("dataset approval use and split do not match")
        return self


class DatasetRegistryRecord(RegistryModel):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(min_length=1)
    component: DatasetComponent
    local_path: str = Field(min_length=1)
    format: DatasetFormat
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)
    label_schema_version: str = Field(min_length=1)
    creation_timestamp: datetime
    source_description: str = Field(min_length=1)
    provenance: DatasetProvenance
    license_or_usage_note: str = Field(min_length=1)
    grouping_field: str | None = Field(default=None, min_length=1)
    time_field: str | None = Field(default=None, min_length=1)
    split_field: str = Field(default="split", min_length=1)
    label_count: int = Field(ge=0)
    row_or_image_count: int = Field(ge=0)
    status: DatasetStatus = DatasetStatus.DISCOVERED
    data_classification: DatasetClassification = DatasetClassification.CANDIDATE_DATA
    human_adjudicated: bool = False
    label_source: str = Field(default="UNSPECIFIED", min_length=1)
    anomaly_data_role: AnomalyDataRole | None = None
    validation_report_path: str | None = None
    validation_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    approvals: list[DatasetApproval] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "dataset_version",
        "schema_version",
        "label_schema_version",
        "source_description",
        "license_or_usage_note",
        "split_field",
        "label_source",
        "grouping_field",
        "time_field",
    )
    @classmethod
    def descriptive_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("dataset registry text fields cannot be blank")
        return value.strip()

    @field_validator("local_path", "validation_report_path")
    @classmethod
    def paths_must_be_local(cls, value: str | None) -> str | None:
        if value is None:
            return None
        local_only_path(value, description="dataset registry paths")
        return value

    @model_validator(mode="after")
    def record_is_coherent(self) -> DatasetRegistryRecord:
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("dataset creation timestamp must include a timezone")
        uses = [approval.use for approval in self.approvals]
        if len(uses) != len(set(uses)):
            raise ValueError("a dataset may have at most one approval per use")
        if self.validation_report_sha256 and not self.validation_report_path:
            raise ValueError("validation report hash requires a report path")
        if self.component is not DatasetComponent.ANOMALY and self.anomaly_data_role:
            raise ValueError("anomaly_data_role is valid only for ANOMALY datasets")
        return self


class DatasetRegistry(RegistryModel):
    registry_version: str = "dataset-registry-v1"
    schema_version: str = "1.0"
    last_modified_at: datetime
    entries: list[DatasetRegistryRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def registry_is_coherent(self) -> DatasetRegistry:
        if self.last_modified_at.tzinfo is None:
            raise ValueError("registry timestamp must include a timezone")
        identities = [
            (record.dataset_id, record.dataset_version) for record in self.entries
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("dataset registry contains duplicate identities")
        return self


class DatasetApprovalError(ValueError):
    """Raised when an explicit dataset approval fails closed."""


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_dataset_path(path: Path | str) -> DatasetHashResult:
    """Hash one local file or a canonical, ordering-independent directory manifest."""

    selected = local_only_path(path, description="dataset paths").resolve()
    if selected.is_symlink():
        raise ValueError("dataset root cannot be a symbolic link")
    if selected.is_file():
        size = selected.stat().st_size
        return DatasetHashResult(
            path=str(selected),
            kind="FILE_SHA256",
            content_sha256=_file_sha256(selected),
            file_count=1,
            total_bytes=size,
        )
    if not selected.is_dir():
        raise ValueError("dataset path does not exist as a local file or directory")

    entries: list[DatasetHashEntry] = []
    for child in sorted(selected.rglob("*"), key=lambda item: item.as_posix()):
        if child.is_symlink():
            raise ValueError(f"dataset directory contains a symbolic link: {child}")
        if not child.is_file():
            continue
        relative_path = child.relative_to(selected).as_posix()
        entries.append(
            DatasetHashEntry(
                relative_path=relative_path,
                size_bytes=child.stat().st_size,
                sha256=_file_sha256(child),
            )
        )
    payload = [entry.model_dump(mode="json") for entry in entries]
    return DatasetHashResult(
        path=str(selected),
        kind="CANONICAL_DIRECTORY_MANIFEST_SHA256",
        content_sha256=hashlib.sha256(_canonical_json(payload)).hexdigest(),
        file_count=len(entries),
        total_bytes=sum(entry.size_bytes for entry in entries),
        entries=entries,
    )


def safe_extract_local_zip(
    archive_path: Path | str,
    destination: Path | str,
    *,
    maximum_members: int = 100_000,
    maximum_uncompressed_bytes: int = 20 * 1024 * 1024 * 1024,
) -> list[Path]:
    """Extract a local ZIP after traversal, link, count, and size checks."""

    archive = local_only_path(archive_path, description="dataset archives").resolve()
    target_root = local_only_path(
        destination,
        description="dataset extraction destinations",
    ).resolve()
    if archive.suffix.casefold() != ".zip" or not archive.is_file():
        raise ValueError("only existing local .zip archives are supported")
    target_root.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        if len(members) > maximum_members:
            raise ValueError("archive exceeds the configured member limit")
        if sum(member.file_size for member in members) > maximum_uncompressed_bytes:
            raise ValueError("archive exceeds the configured uncompressed-size limit")
        extraction_plan: list[tuple[zipfile.ZipInfo, Path]] = []
        planned_paths: set[Path] = set()
        for member in members:
            normalized_name = member.filename.replace("\\", "/")
            relative = PurePosixPath(normalized_name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or ":" in relative.parts[0]
            ):
                raise ValueError(f"unsafe archive member path: {member.filename}")
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(
                    f"archive symbolic links are prohibited: {member.filename}"
                )
            destination_path = target_root.joinpath(*relative.parts).resolve()
            if os.path.commonpath((str(target_root), str(destination_path))) != str(
                target_root
            ):
                raise ValueError(
                    f"archive member escapes destination: {member.filename}"
                )
            if destination_path in planned_paths:
                raise ValueError(
                    f"archive contains a duplicate destination: {member.filename}"
                )
            if destination_path.exists():
                raise ValueError(
                    f"archive extraction would overwrite: {destination_path}"
                )
            planned_paths.add(destination_path)
            extraction_plan.append((member, destination_path))

        for member, destination_path in extraction_plan:
            if member.is_dir():
                destination_path.mkdir(parents=True, exist_ok=True)
                continue
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            with (
                handle.open(member, "r") as source,
                destination_path.open("xb") as sink,
            ):
                shutil.copyfileobj(source, sink)
            extracted.append(destination_path)
    return extracted


def load_dataset_registry(
    path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> DatasetRegistry:
    registry_path = local_only_path(path, description="dataset registries")
    if not registry_path.is_file():
        raise ValueError("dataset registry does not exist as a local file")
    return DatasetRegistry.model_validate_json(
        registry_path.read_text(encoding="utf-8")
    )


def save_dataset_registry(
    registry: DatasetRegistry,
    path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    *,
    modified_at: datetime | None = None,
) -> DatasetRegistry:
    registry_path = local_only_path(path, description="dataset registries")
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        registry.entries,
        key=lambda record: (record.dataset_id, record.dataset_version),
    )
    updated = registry.model_copy(
        update={
            "last_modified_at": modified_at or datetime.now(timezone.utc),
            "entries": ordered,
        }
    )
    payload = updated.model_dump_json(indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=registry_path.parent,
        prefix=registry_path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(payload)
    temporary_path.replace(registry_path)
    return updated


def find_dataset(
    registry: DatasetRegistry,
    dataset_id: str,
    dataset_version: str | None = None,
) -> DatasetRegistryRecord:
    matches = [
        record
        for record in registry.entries
        if record.dataset_id == dataset_id
        and (dataset_version is None or record.dataset_version == dataset_version)
    ]
    if not matches:
        raise KeyError(f"dataset is not registered: {dataset_id}")
    if len(matches) != 1:
        raise KeyError(
            f"dataset version is required because {dataset_id!r} is ambiguous"
        )
    return matches[0]


def resolve_registry_path(
    stored_path: str,
    registry_path: Path | str,
) -> Path:
    selected = local_only_path(stored_path, description="dataset registry paths")
    if not selected.is_absolute():
        selected = (
            local_only_path(
                registry_path,
                description="dataset registries",
            )
            .resolve()
            .parent
            / selected
        )
    resolved = selected.resolve()
    local_only_path(resolved, description="resolved dataset registry paths")
    return resolved


def register_dataset(
    record: DatasetRegistryRecord,
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    replace_existing: bool = False,
    modified_at: datetime | None = None,
) -> DatasetRegistry:
    registry = load_dataset_registry(registry_path)
    identity = (record.dataset_id, record.dataset_version)
    existing = [
        item
        for item in registry.entries
        if (item.dataset_id, item.dataset_version) == identity
    ]
    if existing and not replace_existing:
        raise ValueError(f"dataset is already registered: {identity}")
    entries = [
        item
        for item in registry.entries
        if (item.dataset_id, item.dataset_version) != identity
    ]
    entries.append(record)
    return save_dataset_registry(
        registry.model_copy(update={"entries": entries}),
        registry_path,
        modified_at=modified_at,
    )


def _validation_report(record: DatasetRegistryRecord, registry_path: Path | str):
    from app.ml.data.dataset_validation import RegisteredDatasetValidationReport

    if not record.validation_report_path or not record.validation_report_sha256:
        raise DatasetApprovalError("VALIDATION_REPORT_MISSING")
    report_path = resolve_registry_path(record.validation_report_path, registry_path)
    if not report_path.is_file():
        raise DatasetApprovalError("VALIDATION_REPORT_MISSING")
    actual_hash = _file_sha256(report_path)
    if actual_hash != record.validation_report_sha256:
        raise DatasetApprovalError("VALIDATION_REPORT_HASH_MISMATCH")
    report = RegisteredDatasetValidationReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if (
        report.dataset_id != record.dataset_id
        or report.dataset_version != record.dataset_version
        or report.component is not record.component
        or report.local_path != record.local_path
        or report.format is not record.format
        or report.registered_content_sha256 != record.content_sha256
    ):
        raise DatasetApprovalError("VALIDATION_REPORT_REGISTRY_BINDING_MISMATCH")
    return report


def load_bound_validation_report(
    record: DatasetRegistryRecord,
    registry_path: Path | str,
):
    """Load a report only when its registered file hash still matches."""

    return _validation_report(record, registry_path)


def approve_dataset(
    dataset_id: str,
    use: DatasetUse,
    *,
    approver_id: str,
    approval_note: str,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_version: str | None = None,
    approved_at: datetime | None = None,
) -> DatasetRegistryRecord:
    """Record one explicit split-scoped approval, failing closed on every gate."""

    registry = load_dataset_registry(registry_path)
    record = find_dataset(registry, dataset_id, dataset_version)
    if record.status not in {
        DatasetStatus.VALID,
        DatasetStatus.APPROVED_TRAINING,
        DatasetStatus.APPROVED_VALIDATION,
        DatasetStatus.APPROVED_TEST,
    }:
        raise DatasetApprovalError(f"DATASET_STATUS_{record.status.value}")
    if record.provenance is DatasetProvenance.PROVENANCE_UNKNOWN:
        raise DatasetApprovalError("PROVENANCE_UNKNOWN")
    if record.data_classification is DatasetClassification.DEVELOPMENT_ONLY:
        raise DatasetApprovalError("DEVELOPMENT_ONLY_DATASET")
    if record.data_classification is DatasetClassification.TEST_FIXTURE_ONLY:
        raise DatasetApprovalError("TEST_FIXTURE_ONLY_DATASET")
    if (
        use is DatasetUse.TRAINING
        and record.data_classification is DatasetClassification.PRODUCTION_TEST
    ):
        raise DatasetApprovalError("PRODUCTION_TEST_DATA_CANNOT_BE_TRAINING_DATA")

    dataset_path = resolve_registry_path(record.local_path, registry_path)
    current_hash = hash_dataset_path(dataset_path).content_sha256
    if current_hash != record.content_sha256:
        raise DatasetApprovalError("DATASET_HASH_MISMATCH")
    if record.schema_version == "nlp-human-adjudicated-dataset-v1":
        if record.metadata.get("dataset_hash") != current_hash:
            raise DatasetApprovalError("RECORDED_DATASET_HASH_MISMATCH")
        if not record.metadata.get("source_manifest_hash"):
            raise DatasetApprovalError("SOURCE_MANIFEST_HASH_MISSING")
        evidence_fields = (
            ("manifest_path", "manifest_sha256", "MANIFEST"),
            ("leakage_report_path", "leakage_report_sha256", "LEAKAGE_REPORT"),
        )
        for path_field, hash_field, label in evidence_fields:
            stored_path = record.metadata.get(path_field)
            stored_hash = record.metadata.get(hash_field)
            if not stored_path or not stored_hash:
                raise DatasetApprovalError(f"{label}_EVIDENCE_MISSING")
            evidence_path = resolve_registry_path(str(stored_path), registry_path)
            if not evidence_path.is_file():
                raise DatasetApprovalError(f"{label}_EVIDENCE_MISSING")
            if _file_sha256(evidence_path) != stored_hash:
                raise DatasetApprovalError(f"{label}_HASH_MISMATCH")
        source_manifest_path = record.metadata.get("source_manifest_path")
        source_manifest_sha256 = record.metadata.get("source_manifest_sha256")
        if source_manifest_path is not None or source_manifest_sha256 is not None:
            if not source_manifest_path or not source_manifest_sha256:
                raise DatasetApprovalError("SOURCE_MANIFEST_EVIDENCE_MISSING")
            evidence_path = resolve_registry_path(
                str(source_manifest_path),
                registry_path,
            )
            if not evidence_path.is_file():
                raise DatasetApprovalError("SOURCE_MANIFEST_EVIDENCE_MISSING")
            actual_source_manifest_hash = _file_sha256(evidence_path)
            if actual_source_manifest_hash != source_manifest_sha256:
                raise DatasetApprovalError("SOURCE_MANIFEST_HASH_MISMATCH")
            if actual_source_manifest_hash != record.metadata["source_manifest_hash"]:
                raise DatasetApprovalError("SOURCE_MANIFEST_BINDING_MISMATCH")
            from app.ml.data.nlp_corpus import NLPCorpusSourceManifest

            try:
                source_manifest = NLPCorpusSourceManifest.model_validate_json(
                    evidence_path.read_text(encoding="utf-8", errors="strict")
                )
            except (OSError, UnicodeError, ValueError) as error:
                raise DatasetApprovalError("SOURCE_MANIFEST_INVALID") from error
            if source_manifest.provenance_classification is not record.provenance:
                raise DatasetApprovalError("SOURCE_MANIFEST_PROVENANCE_MISMATCH")
            enrolled_source_path = local_only_path(
                source_manifest.local_path,
                description="NLP corpus source paths",
            )
            if not enrolled_source_path.is_file():
                raise DatasetApprovalError("ENROLLED_SOURCE_MISSING")
            if (
                hash_dataset_path(enrolled_source_path).content_sha256
                != source_manifest.content_hash
            ):
                raise DatasetApprovalError("ENROLLED_SOURCE_HASH_MISMATCH")
    report = _validation_report(record, registry_path)
    if report.content_sha256 != current_hash:
        raise DatasetApprovalError("VALIDATION_REPORT_DATASET_HASH_MISMATCH")
    if not report.valid:
        raise DatasetApprovalError("DATASET_VALIDATION_FAILED")
    if report.leakage.overall_status != "PASS":
        raise DatasetApprovalError(f"LEAKAGE_{report.leakage.overall_status}")
    blockers = report.approval_blockers.get(use.value, [])
    if blockers:
        raise DatasetApprovalError(";".join(blockers))

    timestamp = approved_at or datetime.now(timezone.utc)
    approval = DatasetApproval(
        use=use,
        approved_split=USE_TO_SPLIT[use],
        approver_id=approver_id,
        approval_timestamp=timestamp,
        approval_note=approval_note,
        content_sha256=current_hash,
        validation_report_sha256=record.validation_report_sha256,
    )
    approvals = [item for item in record.approvals if item.use is not use]
    approvals.append(approval)
    updated_record = record.model_copy(
        update={
            "status": USE_TO_STATUS[use],
            "approvals": sorted(approvals, key=lambda item: item.use.value),
        }
    )
    entries = [
        updated_record
        if (item.dataset_id, item.dataset_version)
        == (record.dataset_id, record.dataset_version)
        else item
        for item in registry.entries
    ]
    save_dataset_registry(
        registry.model_copy(update={"entries": entries}),
        registry_path,
        modified_at=timestamp,
    )
    return updated_record


__all__ = [
    "DEFAULT_DATASET_REGISTRY_PATH",
    "AnomalyDataRole",
    "DatasetApproval",
    "DatasetApprovalError",
    "DatasetClassification",
    "DatasetComponent",
    "DatasetFormat",
    "DatasetHashEntry",
    "DatasetHashResult",
    "DatasetProvenance",
    "DatasetRegistry",
    "DatasetRegistryRecord",
    "DatasetStatus",
    "DatasetUse",
    "approve_dataset",
    "find_dataset",
    "hash_dataset_path",
    "load_bound_validation_report",
    "load_dataset_registry",
    "register_dataset",
    "resolve_registry_path",
    "safe_extract_local_zip",
    "save_dataset_registry",
]
