"""Governance gate for any future project-trained ``.pt`` image artifact.

No image artifact exists in Phase 8.  These functions are intentionally local:
they accept a resolved filesystem path and never download or discover models.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import (
    DEFAULT_IMAGE_ANALYSIS_CONFIG,
    ImageAnalysisConfig,
    local_only_path,
    validate_artifact_manifest,
    validate_artifact_metadata,
)
from app.ml.contracts import ArtifactManifest, ArtifactPolicyStatus


class ImageTrainingProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    annotation_schema_version: str = Field(min_length=1)
    optimizer: str = Field(min_length=1)
    learning_rate: float = Field(gt=0.0)
    scheduler: str = "NONE"
    epochs: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    weight_initialization: Literal["LOCAL_RANDOM_KAIMING_XAVIER"] = (
        "LOCAL_RANDOM_KAIMING_XAVIER"
    )
    validation_dataset_hash: str = Field(
        default="0" * 64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    augmentations: list[str] = Field(default_factory=list)
    class_distribution: dict[str, int] = Field(min_length=1)
    training_timestamp: datetime

    @model_validator(mode="after")
    def validate_class_distribution(self) -> ImageTrainingProvenance:
        if any(count < 0 for count in self.class_distribution.values()):
            raise ValueError("class distribution counts cannot be negative")
        if sum(self.class_distribution.values()) <= 0:
            raise ValueError("class distribution must contain labeled samples")
        if "UNCERTAIN" in self.class_distribution:
            raise ValueError("UNCERTAIN cannot be an image model target")
        return self


class ImageArtifactProvenance(BaseModel):
    """Image-specific fields required in addition to the shared manifest."""

    model_config = ConfigDict(extra="forbid")

    artifact_name: str = Field(pattern=r"^[^/\\]+\.pt$")
    model_version: str = Field(min_length=1)
    architecture_version: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    preprocessing_version: str = Field(min_length=1)
    training_config: ImageTrainingProvenance
    random_seed: int
    framework_version: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    policy_status: ArtifactPolicyStatus
    source: Literal["PROJECT_TRAINED"] = "PROJECT_TRAINED"
    initialization: Literal["SCRATCH_INITIALIZED"] = "SCRATCH_INITIALIZED"
    development_status: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    project_controlled_dataset: Literal[True] = True
    pretrained_weights_used: Literal[False] = False
    external_weights_used: Literal[False] = False
    label_mapping: dict[str, int] = Field(
        default_factory=lambda: {
            "FLOODED_SCENE": 0,
            "HEAVY_RAIN_VISUAL": 1,
            "STANDING_WATER": 2,
            "STORM_DAMAGE": 3,
            "NORMAL_SCENE": 4,
        }
    )

    @model_validator(mode="after")
    def validate_scratch_governance(self) -> "ImageArtifactProvenance":
        expected_labels = {
            "FLOODED_SCENE": 0,
            "HEAVY_RAIN_VISUAL": 1,
            "STANDING_WATER": 2,
            "STORM_DAMAGE": 3,
            "NORMAL_SCENE": 4,
        }
        if self.label_mapping != expected_labels:
            raise ValueError("image artifact label mapping does not match the frozen taxonomy")
        return self


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authorize_image_artifact(
    path: Path | str,
    provenance: ImageArtifactProvenance | None,
    manifest: ArtifactManifest,
    *,
    config: ImageAnalysisConfig | None = None,
) -> Path:
    """Reject unknown, external, incomplete, or hash-mismatched weights."""

    config = config or DEFAULT_IMAGE_ANALYSIS_CONFIG
    artifact_path = local_only_path(path, description="image artifacts")
    if artifact_path.suffix.casefold() != ".pt":
        raise ValueError("image artifacts must use the .pt extension")
    if provenance is None:
        raise ValueError("image artifact provenance is required")
    if provenance.policy_status is not ArtifactPolicyStatus.COMPLIANT:
        raise ValueError("image artifact policy status is not COMPLIANT")
    if provenance.source != "PROJECT_TRAINED":
        raise ValueError("externally sourced image weights are prohibited")
    if provenance.pretrained_weights_used or provenance.external_weights_used:
        raise ValueError("pretrained or externally sourced image weights are prohibited")
    if not provenance.project_controlled_dataset:
        raise ValueError("image training data must be project controlled")
    if artifact_path.name != provenance.artifact_name:
        raise ValueError("artifact filename does not match image provenance")
    if not artifact_path.is_file():
        raise ValueError("image artifact does not exist as a local file")

    validated_manifest = validate_artifact_manifest(manifest)
    candidates = [
        validate_artifact_metadata(item)
        for item in validated_manifest.artifacts
        if item.artifact_name == artifact_path.name
        and item.intended_component == "image_analyzer"
    ]
    if len(candidates) != 1:
        raise ValueError("unknown image artifact or ambiguous manifest entry")
    metadata = candidates[0]
    digest = _file_sha256(artifact_path)
    if digest.casefold() != provenance.artifact_sha256.casefold():
        raise ValueError("image artifact hash does not match image provenance")
    if digest.casefold() != metadata.sha256.casefold():
        raise ValueError("image artifact hash does not match shared manifest")
    checks = {
        "model version": metadata.artifact_version == provenance.model_version,
        "dataset hash": metadata.training_dataset_hash.casefold()
        == provenance.dataset_hash.casefold(),
        "feature version": metadata.feature_version == provenance.feature_version,
        "preprocessing version": metadata.preprocessing_version
        == provenance.preprocessing_version,
        "configured architecture version": provenance.architecture_version
        == config.architecture_version,
        "configured feature version": provenance.feature_version
        == config.feature_version,
        "configured preprocessing version": provenance.preprocessing_version
        == config.preprocessing_version,
        "random seed": metadata.random_seed == provenance.random_seed,
        "framework version": provenance.framework_version
        in metadata.framework_versions.values(),
    }
    failed = [name for name, matches in checks.items() if not matches]
    if failed:
        raise ValueError("image artifact provenance mismatch: " + ", ".join(failed))
    return artifact_path.resolve()


def load_image_state_dict(
    path: Path | str,
    provenance: ImageArtifactProvenance | None,
    manifest: ArtifactManifest,
    *,
    config: ImageAnalysisConfig | None = None,
) -> Mapping[str, Any]:
    """Load tensors only after policy authorization; never load arbitrary code."""

    artifact_path = authorize_image_artifact(
        path,
        provenance,
        manifest,
        config=config,
    )
    import torch

    state = torch.load(artifact_path, map_location="cpu", weights_only=True)
    if not isinstance(state, Mapping):
        raise TypeError("authorized image artifact must contain a state-dict mapping")
    return state


__all__ = [
    "ImageArtifactProvenance",
    "ImageTrainingProvenance",
    "authorize_image_artifact",
    "load_image_state_dict",
]
