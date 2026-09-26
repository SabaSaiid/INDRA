"""Local development-only character/word TF-IDF NLP classifier."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.duplicate_features import FrozenTfidfSpace, normalize_text
from app.ml.config import (
    DEFAULT_NLP_CLASSIFIER_CONFIG,
    NLPClassifierConfig,
    authorize_manifest_artifact,
)
from app.ml.contracts import PredictionStatus, ReportInput, TextPrediction


class NLPLinearClassifierState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["logistic_regression"] = "logistic_regression"
    regularization_c: float = Field(gt=0.0)
    max_iterations: int = Field(gt=0)
    random_state: int
    solver: Literal["lbfgs"] = "lbfgs"
    class_weight: Literal["NONE", "BALANCED"] = "NONE"
    classes: list[str] = Field(min_length=2)
    coefficients: list[list[float]]
    intercept: list[float]

    @model_validator(mode="after")
    def validate_dimensions(self) -> NLPLinearClassifierState:
        if len(set(self.classes)) != len(self.classes):
            raise ValueError("classifier classes must be unique")
        if len(self.coefficients) != len(self.classes):
            raise ValueError("classifier coefficient rows must match classes")
        if len(self.intercept) != len(self.classes):
            raise ValueError("classifier intercept length must match classes")
        widths = {len(row) for row in self.coefficients}
        if len(widths) != 1 or not widths or next(iter(widths)) == 0:
            raise ValueError("classifier coefficient rows must have one nonzero width")
        values = [value for row in self.coefficients for value in row]
        if any(not math.isfinite(value) for value in [*values, *self.intercept]):
            raise ValueError("classifier parameters must be finite")
        return self


class NLPFeatureWeights(BaseModel):
    """Explicit relative contribution of the two interpretable feature blocks."""

    model_config = ConfigDict(extra="forbid")

    character: float = Field(default=1.0, gt=0.0)
    word: float = Field(default=1.0, gt=0.0)


class NLPCalibrationState(BaseModel):
    """Local validation-only probability calibration frozen with the model."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["NONE", "TEMPERATURE_SCALING"] = "NONE"
    status: Literal["NOT_CALIBRATED", "CALIBRATED_ON_VALIDATION"] = (
        "NOT_CALIBRATED"
    )
    temperature: float = Field(default=1.0, gt=0.0)
    validation_split_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    validation_log_loss_before: float | None = Field(default=None, ge=0.0)
    validation_log_loss_after: float | None = Field(default=None, ge=0.0)
    validation_brier_before: float | None = Field(default=None, ge=0.0)
    validation_brier_after: float | None = Field(default=None, ge=0.0)
    validation_ece_before: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_ece_after: float | None = Field(default=None, ge=0.0, le=1.0)
    search_bounds: tuple[float, float] | None = None
    search_boundary_status: Literal[
        "NOT_APPLICABLE",
        "INTERIOR_OPTIMUM",
        "CALIBRATION_SEARCH_BOUNDARY_REACHED",
    ] = "NOT_APPLICABLE"

    @model_validator(mode="after")
    def validate_calibration_state(self) -> NLPCalibrationState:
        metrics = (
            self.validation_log_loss_before,
            self.validation_log_loss_after,
            self.validation_brier_before,
            self.validation_brier_after,
            self.validation_ece_before,
            self.validation_ece_after,
        )
        if self.method == "NONE":
            if self.status != "NOT_CALIBRATED" or self.temperature != 1.0:
                raise ValueError("uncalibrated state must use unit temperature")
            if self.validation_split_sha256 is not None or any(
                value is not None for value in metrics
            ):
                raise ValueError("uncalibrated state cannot contain calibration evidence")
            if self.search_bounds is not None:
                raise ValueError("uncalibrated state cannot contain calibration bounds")
            if self.search_boundary_status != "NOT_APPLICABLE":
                raise ValueError("uncalibrated state cannot report a calibration boundary")
            return self
        if self.status != "CALIBRATED_ON_VALIDATION":
            raise ValueError("temperature scaling must be validation calibrated")
        if self.validation_split_sha256 is None or any(
            value is None for value in metrics
        ):
            raise ValueError("calibrated state requires validation hash and metrics")
        if self.search_bounds is not None:
            lower, upper = self.search_bounds
            if lower <= 0.0 or upper <= lower:
                raise ValueError("calibration search bounds must be positive and ascending")
            if not lower <= self.temperature <= upper:
                raise ValueError("calibration temperature is outside the frozen search bounds")
        return self


class NLPArtifactProvenance(BaseModel):
    """Auditable training provenance embedded in the self-contained artifact."""

    model_config = ConfigDict(extra="forbid")

    dataset_identifier: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    validation_split_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    final_test_split_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    split_version: str | None = Field(default=None, min_length=1)
    training_timestamp: datetime
    dataset_status: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
    scikit_learn_version: str = Field(min_length=1)
    numpy_version: str = Field(min_length=1)
    random_state: int
    classifier_configuration: dict[str, Any] = Field(min_length=1)
    class_distribution: dict[str, int] = Field(min_length=1)
    dataset_generator_version: str | None = Field(default=None, min_length=1)
    dataset_generator_seed: int | None = None
    dataset_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    scenario_metadata_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )

    @model_validator(mode="after")
    def validate_training_metadata(self) -> NLPArtifactProvenance:
        if self.training_timestamp.tzinfo is None:
            raise ValueError("training_timestamp must include a timezone")
        if any(count <= 0 for count in self.class_distribution.values()):
            raise ValueError("class distribution counts must be positive")
        return self


class NLPClassifierArtifact(BaseModel):
    """JSON-safe fitted state; no pickle, pretrained weights, or downloads."""

    model_config = ConfigDict(extra="forbid")

    artifact_version: Literal[
        "nlp-classifier-artifact-v1",
        "nlp-classifier-artifact-v2",
        "nlp-classifier-artifact-v3",
    ] = (
        "nlp-classifier-artifact-v1"
    )
    model_version: str = Field(min_length=1)
    model_status: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    preprocessing_version: str = Field(min_length=1)
    classes: list[str] = Field(min_length=2)
    char_space: FrozenTfidfSpace
    word_space: FrozenTfidfSpace
    feature_weights: NLPFeatureWeights = Field(default_factory=NLPFeatureWeights)
    classifier: NLPLinearClassifierState
    calibration: NLPCalibrationState = Field(default_factory=NLPCalibrationState)
    n_features: int = Field(gt=0)
    provenance: NLPArtifactProvenance

    @model_validator(mode="after")
    def validate_complete_fitted_state(self) -> NLPClassifierArtifact:
        if len(set(self.classes)) != len(self.classes):
            raise ValueError("artifact classes must be unique")
        if self.classes != self.classifier.classes:
            raise ValueError("artifact class mapping is inconsistent")
        if self.char_space.analyzer != "char" or self.word_space.analyzer != "word":
            raise ValueError("artifact TF-IDF analyzers are inconsistent")
        expected_features = len(self.char_space.vocabulary) + len(
            self.word_space.vocabulary
        )
        if self.n_features != expected_features:
            raise ValueError("artifact feature dimension is inconsistent")
        if any(len(row) != self.n_features for row in self.classifier.coefficients):
            raise ValueError("classifier coefficients do not match artifact features")
        if set(self.provenance.class_distribution) != set(self.classes):
            raise ValueError("provenance class distribution does not match classes")
        if self.artifact_version in {
            "nlp-classifier-artifact-v2",
            "nlp-classifier-artifact-v3",
        }:
            required = (
                self.provenance.validation_split_sha256,
                self.provenance.final_test_split_sha256,
                self.provenance.split_version,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "v2/v3 artifact requires complete development split provenance"
                )
            if (
                self.calibration.method != "NONE"
                and self.calibration.validation_split_sha256
                != self.provenance.validation_split_sha256
            ):
                raise ValueError("calibration and provenance validation hashes differ")
        if self.artifact_version == "nlp-classifier-artifact-v3":
            if self.model_status != "DEVELOPMENT_ONLY_SYNTHETIC":
                raise ValueError(
                    "v3 artifact status must remain DEVELOPMENT_ONLY_SYNTHETIC"
                )
            required_v3 = (
                self.provenance.dataset_generator_version,
                self.provenance.dataset_generator_seed,
                self.provenance.dataset_manifest_sha256,
                self.provenance.scenario_metadata_sha256,
            )
            if any(value is None for value in required_v3):
                raise ValueError("v3 artifact requires synthetic generator provenance")
        return self


def load_nlp_artifact(
    path: Path | str,
    *,
    manifest_path: Path | str | None = None,
) -> NLPClassifierArtifact:
    """Load a project-local JSON artifact only after manifest authorization."""

    artifact_path, metadata = authorize_manifest_artifact(
        path,
        intended_component="nlp_classifier",
        manifest_path=manifest_path,
        allowed_suffixes={".json"},
    )
    artifact = NLPClassifierArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    provenance = artifact.provenance
    checks = {
        "model version": artifact.model_version == metadata.artifact_version,
        "dataset hash": provenance.dataset_sha256.casefold()
        == metadata.training_dataset_hash.casefold(),
        "feature version": artifact.feature_version == metadata.feature_version,
        "preprocessing version": artifact.preprocessing_version
        == metadata.preprocessing_version,
        "training timestamp": provenance.training_timestamp
        == metadata.training_timestamp,
        "random seed": provenance.random_state == metadata.random_seed,
        "python version": metadata.framework_versions.get("python")
        == provenance.python_version,
        "numpy version": metadata.framework_versions.get("numpy")
        == provenance.numpy_version,
        "scikit-learn version": metadata.framework_versions.get("scikit_learn")
        == provenance.scikit_learn_version,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("NLP artifact provenance mismatch: " + ", ".join(failed))
    return artifact


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum()


def _vectorize(artifact: NLPClassifierArtifact, text: str) -> tuple[np.ndarray, int]:
    normalized = normalize_text(text)
    vector = np.zeros(artifact.n_features, dtype=np.float64)
    char_values = artifact.char_space.transform(normalized)
    word_values = artifact.word_space.transform(normalized)
    for index, value in char_values.items():
        vector[index] = value * artifact.feature_weights.character
    word_offset = len(artifact.char_space.vocabulary)
    for index, value in word_values.items():
        vector[word_offset + index] = value * artifact.feature_weights.word
    return vector, len(char_values) + len(word_values)


class NLPClassifier:
    """Inference-only wrapper around a locally trained logistic regression."""

    component_name = "nlp_classifier"
    method = "character_tfidf+word_tfidf+logistic_regression"

    def __init__(
        self,
        config: NLPClassifierConfig | None = None,
        *,
        artifact_path: Path | str | None = None,
        manifest_path: Path | str | None = None,
    ) -> None:
        self.config = config or DEFAULT_NLP_CLASSIFIER_CONFIG
        self.artifact_path = artifact_path or self.config.artifact_path
        self.manifest_path = manifest_path or Path(self.artifact_path).parent / "manifest.json"
        self._artifact: NLPClassifierArtifact | None = None
        self._offline_reason: str | None = None

    def _load(self) -> NLPClassifierArtifact | None:
        if self._artifact is not None:
            return self._artifact
        try:
            artifact = load_nlp_artifact(
                self.artifact_path,
                manifest_path=self.manifest_path,
            )
            if artifact.model_version != self.config.model_version:
                raise ValueError("artifact model version does not match configuration")
            if artifact.feature_version != self.config.feature_version:
                raise ValueError("artifact feature version does not match configuration")
            if artifact.preprocessing_version != self.config.preprocessing_version:
                raise ValueError("artifact preprocessing version does not match configuration")
            if tuple(artifact.char_space.ngram_range) != tuple(
                self.config.char_ngram_range
            ):
                raise ValueError("artifact character n-gram range does not match configuration")
            if tuple(artifact.word_space.ngram_range) != tuple(
                self.config.word_ngram_range
            ):
                raise ValueError("artifact word n-gram range does not match configuration")
            if artifact.classifier.random_state != self.config.random_state:
                raise ValueError("artifact random seed does not match configuration")
            self._artifact = artifact
            self._offline_reason = None
            return artifact
        # Loading must fail closed for I/O, manifest, JSON, and validation errors.
        except Exception as error:  # noqa: BLE001
            self._offline_reason = f"artifact unreadable: {type(error).__name__}: {error}"
            return None

    def reset(self) -> None:
        self._artifact = None
        self._offline_reason = None

    @property
    def offline_reason(self) -> str | None:
        return self._offline_reason

    def predict(self, value: str | ReportInput) -> TextPrediction:
        text = value if isinstance(value, str) else value.text
        artifact = self._load()
        if artifact is None:
            return TextPrediction(
                status=PredictionStatus.OFFLINE,
                reason_codes=["MODEL_ARTIFACT_UNAVAILABLE"],
                warnings=[self._offline_reason or "NLP classifier artifact is unavailable."],
            )

        normalized = normalize_text(text)
        if not normalized:
            return TextPrediction(
                status=PredictionStatus.NOT_APPLICABLE,
                model_version=artifact.model_version,
                feature_version=artifact.feature_version,
                preprocessing_version=artifact.preprocessing_version,
                reason_codes=["EMPTY_TEXT"],
                warnings=["Empty text cannot produce a class probability distribution."],
            )

        try:
            vector, nonzero_features = _vectorize(artifact, normalized)
            coefficients = np.asarray(artifact.classifier.coefficients, dtype=np.float64)
            intercept = np.asarray(artifact.classifier.intercept, dtype=np.float64)
            logits = coefficients @ vector + intercept
            probabilities = _softmax(logits / artifact.calibration.temperature)
            probability_map = {
                label: float(probabilities[index])
                for index, label in enumerate(artifact.classes)
            }
            best_index = int(np.argmax(probabilities))
            evidence = [
                f"method={self.method}",
                f"nonzero_features={nonzero_features}",
                f"model_status={artifact.model_status}",
            ]
            if artifact.artifact_version in {
                "nlp-classifier-artifact-v2",
                "nlp-classifier-artifact-v3",
            }:
                evidence.append(
                    f"calibration_status={artifact.calibration.status}"
                )
            return TextPrediction(
                status=PredictionStatus.AVAILABLE,
                model_version=artifact.model_version,
                feature_version=artifact.feature_version,
                preprocessing_version=artifact.preprocessing_version,
                label=artifact.classes[best_index],
                probabilities=probability_map,
                confidence=float(probabilities[best_index]),
                evidence=evidence,
                reason_codes=["DEVELOPMENT_MODEL_INFERENCE"],
                warnings=["Synthetic-data development model; not production validated."],
            )
        # The component contract converts all numerical/runtime failures to ERROR.
        except Exception as error:  # noqa: BLE001
            return TextPrediction(
                status=PredictionStatus.ERROR,
                model_version=artifact.model_version,
                feature_version=artifact.feature_version,
                preprocessing_version=artifact.preprocessing_version,
                reason_codes=["INFERENCE_ERROR"],
                warnings=[f"NLP inference failed: {type(error).__name__}: {error}"],
            )
