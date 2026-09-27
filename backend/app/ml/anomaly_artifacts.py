"""Governance authorization for locally project-trained anomaly artifacts.

Authorization is local, hash-bound, and independent of the live anomaly path.
No model discovery, download, or external inference is performed here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import (
    DEFAULT_ANOMALY_DETECTION_CONFIG,
    AnomalyDetectionConfig,
    local_only_path,
    validate_artifact_manifest,
    validate_artifact_metadata,
)
from app.ml.contracts import ArtifactManifest, ArtifactPolicyStatus


class AnomalyArtifactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_name: str = Field(pattern=r"^[^/\\]+\.(json|joblib)$")
    model_version: str = Field(min_length=1)
    model_family: Literal["ISOLATION_FOREST", "CUSTOM_PROJECT_MODEL"]
    dataset_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    training_dataset_hash: str = Field(
        default="0" * 64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    validation_dataset_hash: str = Field(
        default="0" * 64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    feature_version: str = Field(min_length=1)
    baseline_version: str = Field(min_length=1)
    generator_version: str = "UNSPECIFIED"
    configuration_version: str = "UNSPECIFIED"
    configuration_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    threshold_configuration: dict[str, float] = Field(default_factory=dict)
    library_version: str = Field(min_length=1)
    random_seed: int
    artifact_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    training_start_at: datetime
    training_end_at: datetime
    station_scope: list[str] = Field(min_length=1)
    policy_status: ArtifactPolicyStatus
    source: Literal["PROJECT_TRAINED"] = "PROJECT_TRAINED"
    development_status: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    pretrained_model_used: Literal[False] = False
    external_model_used: Literal[False] = False

    @model_validator(mode="after")
    def validate_training_scope(self) -> AnomalyArtifactProvenance:
        if self.training_start_at >= self.training_end_at:
            raise ValueError("training_start_at must precede training_end_at")
        if len(set(self.station_scope)) != len(self.station_scope):
            raise ValueError("station_scope must contain unique station IDs")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authorize_anomaly_artifact(
    path: Path | str,
    provenance: AnomalyArtifactProvenance | None,
    manifest: ArtifactManifest,
    *,
    config: AnomalyDetectionConfig | None = None,
) -> Path:
    """Reject remote, unknown, external, or provenance-mismatched artifacts."""

    config = config or DEFAULT_ANOMALY_DETECTION_CONFIG
    artifact_path = local_only_path(path, description="anomaly artifacts")
    if artifact_path.suffix.casefold() not in {".json", ".joblib"}:
        raise ValueError("unsupported anomaly artifact extension")
    if provenance is None:
        raise ValueError("anomaly artifact provenance is required")
    if provenance.policy_status is not ArtifactPolicyStatus.COMPLIANT:
        raise ValueError("anomaly artifact policy status is not COMPLIANT")
    if (
        provenance.source != "PROJECT_TRAINED"
        or provenance.pretrained_model_used
        or provenance.external_model_used
    ):
        raise ValueError(
            "pretrained or externally sourced anomaly models are prohibited"
        )
    if artifact_path.name != provenance.artifact_name:
        raise ValueError("artifact filename does not match anomaly provenance")
    if not artifact_path.is_file():
        raise ValueError("anomaly artifact does not exist as a local file")

    validated_manifest = validate_artifact_manifest(manifest)
    candidates = [
        validate_artifact_metadata(item)
        for item in validated_manifest.artifacts
        if item.artifact_name == artifact_path.name
        and item.intended_component == "anomaly_detector"
    ]
    if len(candidates) != 1:
        raise ValueError("unknown anomaly artifact or ambiguous manifest entry")
    metadata = candidates[0]
    digest = _sha256(artifact_path)
    checks = {
        "artifact provenance hash": digest.casefold()
        == provenance.artifact_hash.casefold(),
        "shared manifest hash": digest.casefold() == metadata.sha256.casefold(),
        "model version": provenance.model_version == metadata.artifact_version,
        "dataset hash": provenance.dataset_hash.casefold()
        == metadata.training_dataset_hash.casefold(),
        "feature version": provenance.feature_version == metadata.feature_version,
        "configured feature version": provenance.feature_version
        == config.feature_version,
        "baseline version": provenance.baseline_version
        == metadata.preprocessing_version,
        "random seed": provenance.random_seed == metadata.random_seed,
        "library version": provenance.library_version
        in metadata.framework_versions.values(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("anomaly artifact provenance mismatch: " + ", ".join(failed))
    return artifact_path.resolve()


__all__ = ["AnomalyArtifactProvenance", "authorize_anomaly_artifact"]
