"""Configuration and artifact governance for the local ML subsystem."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.contracts import ArtifactManifest, ArtifactMetadata, ArtifactPolicyStatus


class DuplicateMatchingConfig(BaseModel):
    """Explicit, provisional settings for local duplicate matching."""

    model_config = ConfigDict(extra="forbid")

    feature_version: str = "duplicate-features-v1"
    preprocessing_version: str = "duplicate-text-normalization-v1"
    feature_state_path: Path = (
        Path(__file__).resolve().parent / "artifacts" / "duplicate_feature_state.json"
    )
    char_ngram_range: tuple[int, int] = (3, 5)
    word_ngram_range: tuple[int, int] = (1, 2)
    char_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    word_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    edit_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    geographic_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    temporal_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    text_similarity_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    combined_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    threshold_status: Literal[
        "PROVISIONAL / UNVALIDATED",
        "VALIDATION_SELECTED_SYNTHETIC_DEVELOPMENT",
    ] = "PROVISIONAL / UNVALIDATED"
    geographic_gate_km: float = Field(default=1.0, gt=0.0)
    temporal_gate_minutes: float = Field(default=15.0, gt=0.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self):
        total = (
            self.char_weight
            + self.word_weight
            + self.edit_weight
            + self.geographic_weight
            + self.temporal_weight
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError("duplicate matching weights must sum to 1.0")
        if self.char_ngram_range[0] > self.char_ngram_range[1]:
            raise ValueError("char_ngram_range must be ascending")
        if self.word_ngram_range[0] > self.word_ngram_range[1]:
            raise ValueError("word_ngram_range must be ascending")
        return self


DEFAULT_DUPLICATE_MATCHING_CONFIG = DuplicateMatchingConfig()


class NLPClassifierConfig(BaseModel):
    """Development-only local NLP classifier configuration."""

    model_config = ConfigDict(extra="forbid")

    model_version: str = "nlp-classifier-v1"
    feature_version: str = "nlp-features-v1"
    preprocessing_version: str = "nlp-text-normalization-v1"
    dataset_path: Path = (
        Path(__file__).resolve().parents[3] / "data" / "labelled" / "reports_v1.csv"
    )
    artifact_path: Path = (
        Path(__file__).resolve().parent / "artifacts" / "nlp_classifier_v1.json"
    )
    metrics_path: Path = (
        Path(__file__).resolve().parent / "artifacts" / "nlp_classifier_v1.metrics.json"
    )
    char_ngram_range: tuple[int, int] = (3, 5)
    word_ngram_range: tuple[int, int] = (1, 2)
    sublinear_tf: bool = True
    norm: Literal["l2"] = "l2"
    regularization_grid: tuple[float, ...] = (0.1, 1.0, 10.0)
    regularization_c: float = Field(default=1.0, gt=0.0)
    max_iterations: int = Field(default=2000, gt=0)
    random_state: int = 42
    cross_validation_folds: int = Field(default=5, ge=2)
    min_macro_f1: float = Field(default=0.75, ge=0.0, le=1.0)
    min_not_relevant_recall: float = Field(default=0.80, ge=0.0, le=1.0)
    max_flood_to_not_relevant_errors: int = Field(default=4, ge=0)
    minimum_subgroup_rows: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_feature_and_search_settings(self):
        if self.char_ngram_range[0] > self.char_ngram_range[1]:
            raise ValueError("char_ngram_range must be ascending")
        if self.word_ngram_range[0] > self.word_ngram_range[1]:
            raise ValueError("word_ngram_range must be ascending")
        if not self.regularization_grid or any(
            value <= 0.0 for value in self.regularization_grid
        ):
            raise ValueError("regularization_grid must contain positive values")
        return self


DEFAULT_NLP_CLASSIFIER_CONFIG = NLPClassifierConfig()


def _default_event_type_rules() -> dict[str, tuple[str, ...]]:
    labels = (
        "URBAN_FLOOD",
        "RIVER_BREACH",
        "CLOUDBURST",
        "CYCLONE_INUNDATION",
        "NOT_RELEVANT",
    )
    return {label: (label,) for label in labels}


class EventDetectorConfig(BaseModel):
    """Deterministic heuristic event-grouping configuration."""

    model_config = ConfigDict(extra="forbid")

    feature_version: str = "event-features-v1"
    algorithm_version: str = "event-grouping-v2"
    spatial_radius_km: float = Field(default=5.0, gt=0.0)
    temporal_window_minutes: float = Field(default=180.0, gt=0.0)
    minimum_reports: int = Field(default=2, ge=1)
    minimum_type_probability: float = Field(default=0.40, ge=0.0, le=1.0)
    compatible_event_type_rules: dict[str, tuple[str, ...]] = Field(
        default_factory=_default_event_type_rules
    )


DEFAULT_EVENT_DETECTOR_CONFIG = EventDetectorConfig()


class CredibilityRiskConfig(BaseModel):
    """Transparent rule-baseline thresholds and risk contributions."""

    model_config = ConfigDict(extra="forbid")

    baseline_name: Literal["RULE_BASED_CREDIBILITY_BASELINE"] = (
        "RULE_BASED_CREDIBILITY_BASELINE"
    )
    model_version: str = "rule-based-credibility-baseline-v1"
    feature_version: str = "credibility-risk-features-v1"
    preprocessing_version: str = "credibility-risk-normalization-v1"
    minimum_text_characters: int = Field(default=5, ge=1)
    repeated_token_ratio_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    repeated_phrase_ratio_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    punctuation_ratio_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    url_count_threshold: int = Field(default=2, ge=0)
    phone_count_threshold: int = Field(default=2, ge=0)
    duplicate_similarity_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    duplicate_cluster_size_threshold: int = Field(default=5, ge=1)
    source_report_burst_threshold: int = Field(default=10, ge=1)
    future_timestamp_tolerance_seconds: float = Field(default=300.0, ge=0.0)
    moderate_risk_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    high_risk_threshold: float = Field(default=0.55, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_risk_thresholds(self):
        if self.moderate_risk_threshold >= self.high_risk_threshold:
            raise ValueError(
                "moderate risk threshold must be below high risk threshold"
            )
        return self


DEFAULT_CREDIBILITY_RISK_CONFIG = CredibilityRiskConfig()


class AnomalyDetectionConfig(BaseModel):
    """Transparent local statistical anomaly configuration."""

    model_config = ConfigDict(extra="forbid")

    baseline_name: Literal["STATISTICAL_ANOMALY_BASELINE"] = (
        "STATISTICAL_ANOMALY_BASELINE"
    )
    baseline_version_prefix: str = "statistical-anomaly-baseline-v1"
    feature_version: str = "anomaly-features-v1"
    model_version: str = "statistical-anomaly-detector-v1"
    rolling_window_size: int = Field(default=12, ge=3)
    minimum_reference_observations: int = Field(default=5, ge=3)
    robust_z_threshold: float = Field(default=3.5, gt=0.0)
    persistent_points: int = Field(default=3, ge=2)
    missingness_pattern_points: int = Field(default=3, ge=2)
    irregular_interval_tolerance_ratio: float = Field(default=0.25, ge=0.0)
    rainfall_minimum_scale_mm: float = Field(default=0.1, gt=0.0)
    river_level_minimum_scale_m: float = Field(default=0.01, gt=0.0)
    rainfall_rate_threshold_mm_per_hour: float = Field(default=25.0, gt=0.0)
    river_level_rate_threshold_m_per_hour: float = Field(default=1.0, gt=0.0)
    lower_quantile: float = Field(default=0.25, gt=0.0, lt=1.0)
    upper_quantile: float = Field(default=0.75, gt=0.0, lt=1.0)
    seasonality_mode: Literal["NONE", "HOUR_OF_DAY"] = "NONE"
    minimum_temporal_split_observations: int = Field(default=6, ge=3)
    random_seed: int = 42
    isolation_forest_estimators: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def validate_anomaly_settings(self):
        if self.lower_quantile >= self.upper_quantile:
            raise ValueError("lower_quantile must be below upper_quantile")
        if self.minimum_reference_observations > self.rolling_window_size:
            raise ValueError(
                "minimum_reference_observations cannot exceed rolling_window_size"
            )
        return self


DEFAULT_ANOMALY_DETECTION_CONFIG = AnomalyDetectionConfig()


class ImageAnalysisConfig(BaseModel):
    """Local image validation, preprocessing, and future-training settings."""

    model_config = ConfigDict(extra="forbid")

    preprocessing_version: str = "image-preprocessing-v1"
    feature_version: str = "image-validation-features-v1"
    architecture_version: str = "scratch-cnn-v1"
    model_version: str = "image-analyzer-untrained-v1"
    target_width: int = Field(default=224, gt=0)
    target_height: int = Field(default=224, gt=0)
    aspect_ratio_policy: Literal["LETTERBOX"] = "LETTERBOX"
    color_space: Literal["RGB"] = "RGB"
    channel_order: Literal["CHW"] = "CHW"
    alpha_handling: Literal["COMPOSITE_ON_SOLID_RGB"] = "COMPOSITE_ON_SOLID_RGB"
    alpha_background_rgb: tuple[int, int, int] = (0, 0, 0)
    letterbox_fill_rgb: tuple[int, int, int] = (0, 0, 0)
    normalization: Literal["ZERO_TO_ONE"] = "ZERO_TO_ONE"
    interpolation: Literal["BILINEAR"] = "BILINEAR"
    supported_mime_types: tuple[str, ...] = ("image/jpeg", "image/png")
    supported_formats: tuple[str, ...] = ("JPEG", "PNG")
    supported_color_modes: tuple[str, ...] = ("RGB", "RGBA", "L")
    max_file_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_width: int = Field(default=12000, gt=0)
    max_height: int = Field(default=12000, gt=0)
    max_pixels: int = Field(default=40_000_000, gt=0)
    random_seed: int = 42
    # Five learnable visual labels; UNCERTAIN is an annotation state excluded
    # from training and evaluation targets.
    num_classes: int = Field(default=5, gt=0)
    multi_label: Literal[True] = True
    optimizer: str = "Adam"
    learning_rate: float = Field(default=0.001, gt=0.0)
    epochs: int = Field(default=20, gt=0)
    batch_size: int = Field(default=32, gt=0)

    @model_validator(mode="after")
    def validate_rgb_values(self):
        for name in ("alpha_background_rgb", "letterbox_fill_rgb"):
            if any(channel < 0 or channel > 255 for channel in getattr(self, name)):
                raise ValueError(f"{name} channels must be in [0, 255]")
        return self


DEFAULT_IMAGE_ANALYSIS_CONFIG = ImageAnalysisConfig()


class MLConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_manifest_path: Path = (
        Path(__file__).resolve().parent / "artifacts" / "manifest.json"
    )
    allow_runtime_downloads: bool = False
    allow_external_inference: bool = False
    feature_version: str = "unimplemented"
    preprocessing_version: str = "unimplemented"
    duplicate_matching: DuplicateMatchingConfig = Field(
        default_factory=DuplicateMatchingConfig
    )
    nlp_classifier: NLPClassifierConfig = Field(default_factory=NLPClassifierConfig)
    event_detector: EventDetectorConfig = Field(default_factory=EventDetectorConfig)
    credibility_risk: CredibilityRiskConfig = Field(
        default_factory=CredibilityRiskConfig
    )
    anomaly_detection: AnomalyDetectionConfig = Field(
        default_factory=AnomalyDetectionConfig
    )
    image_analysis: ImageAnalysisConfig = Field(default_factory=ImageAnalysisConfig)


REQUIRED_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_name",
        "artifact_version",
        "sha256",
        "training_dataset_hash",
        "feature_version",
        "preprocessing_version",
        "training_timestamp",
        "random_seed",
        "framework_versions",
        "intended_component",
        "policy_status",
    }
)


def local_only_path(path: Path | str, *, description: str = "artifacts") -> Path:
    """Return a filesystem path after rejecting URL and UNC/network forms."""

    raw_path = str(path)
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        raise ValueError(f"remote {description} are prohibited")
    return Path(path)


def file_sha256(path: Path) -> str:
    """Hash a local file without loading the whole artifact into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache()
def get_ml_config() -> MLConfig:
    return MLConfig()


def validate_artifact_metadata(metadata: ArtifactMetadata) -> ArtifactMetadata:
    """Reject artifacts that do not carry complete compliant provenance."""

    if metadata.policy_status is not ArtifactPolicyStatus.COMPLIANT:
        raise ValueError(
            f"artifact {metadata.artifact_name!r} is not policy-compliant: "
            f"{metadata.policy_status.value}"
        )
    return metadata


def validate_artifact_manifest(manifest: ArtifactManifest) -> ArtifactManifest:
    """Validate the manifest structure and every loadable artifact entry."""

    if manifest.runtime_downloads_allowed is not False:
        raise ValueError("runtime model downloads must remain disabled")
    identities = [
        (artifact.artifact_name, artifact.intended_component)
        for artifact in manifest.artifacts
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("artifact manifest contains duplicate component entries")
    for artifact in manifest.artifacts:
        validate_artifact_metadata(artifact)
    return manifest


def load_artifact_manifest(path: Path | str | None = None) -> ArtifactManifest:
    """Load a local manifest; this function never performs network I/O."""

    manifest_path = local_only_path(
        path or get_ml_config().artifact_manifest_path,
        description="artifact manifests",
    )
    payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return validate_artifact_manifest(ArtifactManifest.model_validate(payload))


def authorize_manifest_artifact(
    path: Path | str,
    *,
    intended_component: str,
    manifest_path: Path | str | None = None,
    allowed_suffixes: set[str] | None = None,
) -> tuple[Path, ArtifactMetadata]:
    """Authorize one local artifact by component identity and exact SHA-256."""

    artifact_path = local_only_path(path, description=f"{intended_component} artifacts")
    if allowed_suffixes is not None and artifact_path.suffix.casefold() not in {
        suffix.casefold() for suffix in allowed_suffixes
    }:
        raise ValueError(
            f"unsupported {intended_component} artifact extension: "
            f"{artifact_path.suffix or '<none>'}"
        )
    if not artifact_path.is_file():
        raise ValueError(f"{intended_component} artifact does not exist as a local file")
    selected_manifest_path = manifest_path or artifact_path.parent / "manifest.json"
    manifest = load_artifact_manifest(selected_manifest_path)
    candidates = [
        item
        for item in manifest.artifacts
        if item.artifact_name == artifact_path.name
        and item.intended_component == intended_component
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"unknown {intended_component} artifact or ambiguous manifest entry"
        )
    metadata = validate_artifact_metadata(candidates[0])
    if file_sha256(artifact_path).casefold() != metadata.sha256.casefold():
        raise ValueError(f"{intended_component} artifact hash does not match manifest")
    return artifact_path.resolve(), metadata
