"""Phase 22 scratch-CNN training on project-authored synthetic images.

This workflow is isolated from the live inference path.  It trains only from
local pixels, selects/calibrates on validation, freezes a governed state dict,
and permits exactly one protected synthetic holdout evaluation.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import tempfile
import tracemalloc
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Final, Literal
from uuid import UUID

import numpy as np
import torch
from PIL import Image, ImageEnhance, ImageFilter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from torch import nn
from torch.utils.data import DataLoader, Dataset

from app.ml.components.image_analysis import ImageAnalyzer, image_input_from_report
from app.ml.components.image_processing import (
    ImageValidationException,
    byte_sha256,
    preprocess_image,
)
from app.ml.config import ImageAnalysisConfig, file_sha256, local_only_path
from app.ml.contracts import (
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    CalibrationStatus,
    ImageInput,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    UnifiedMLResult,
)
from app.ml.data.image_annotations import IMAGE_ANNOTATION_SCHEMA_VERSION
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetClassification,
    DatasetComponent,
    DatasetProvenance,
    DatasetStatus,
    find_dataset,
    hash_dataset_path,
    load_bound_validation_report,
    load_dataset_registry,
    resolve_registry_path,
)
from app.ml.data.synthetic_image import (
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_VERSION,
    DEFAULT_SEED,
    GENERATOR_VERSION,
    HARD_NEGATIVE_SCENES,
    IMAGE_LABELS,
    SyntheticImageGroundTruth,
    SyntheticImageModelRecord,
)
from app.ml.image_artifacts import (
    ImageArtifactProvenance,
    ImageTrainingProvenance,
    authorize_image_artifact,
    load_image_state_dict,
)
from app.ml.models.custom_cnn import (
    ScratchCNNConfig,
    build_scratch_cnn_v2,
)
from app.ml.training.dataset_gate import evaluate_training_dataset

PHASE: Final[str] = "22 — IMAGE MODEL SYNTHETIC VALIDATION"
MODEL_VERSION: Final[str] = "image-model-v1-synthetic-development"
ARCHITECTURE_VERSION: Final[str] = "scratch-cnn-v2-dual-pool"
FEATURE_VERSION: Final[str] = "image-pixel-features-v1"
PREPROCESSING_VERSION: Final[str] = "image-preprocessing-v2-64x64"
AUGMENTATION_VERSION: Final[str] = "image-local-augmentation-v1"
CALIBRATION_VERSION: Final[str] = "image-validation-temperature-v1"
THRESHOLD_VERSION: Final[str] = "image-validation-per-label-thresholds-v1"
DEVELOPMENT_STATUS: Final[str] = "DEVELOPMENT_ONLY_SYNTHETIC"
PRODUCTION_VALIDATION: Final[str] = "NOT_VALIDATED"
INITIALIZATION: Final[str] = "SCRATCH_INITIALIZED"
FREEZE_TIMESTAMP: Final[datetime] = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)
FINAL_EVALUATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 24, 8, 0, tzinfo=timezone.utc
)

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "artifacts"
DEFAULT_DATASET_ROOT: Final[Path] = (
    REPOSITORY_ROOT / "data" / "labelled" / "image" / "synthetic_v1"
)
DEFAULT_ARTIFACT_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.pt"
DEFAULT_PROVENANCE_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.provenance.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1.development_manifest.json"
)
DEFAULT_TRAINING_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1.training_metrics.json"
)
DEFAULT_VALIDATION_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1.validation_metrics.json"
)
DEFAULT_CALIBRATION_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1.calibration.json"
)
DEFAULT_VALIDATION_ERRORS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1.validation_errors.json"
)
DEFAULT_PERFORMANCE_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.performance.json"
DEFAULT_GOLDEN_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.golden.json"
DEFAULT_FINAL_METRICS_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.metrics.json"
DEFAULT_ERROR_REPORT_PATH: Final[Path] = ARTIFACT_ROOT / "image_model_v1.error_report.json"
DEFAULT_FINAL_RECEIPT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "image_model_v1_final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH: Final[Path] = ARTIFACT_ROOT / "manifest.json"

EXPECTED_FROZEN_CORE_HASHES: Final[dict[str, str]] = {
    "nlp_classifier_v3.json": "7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca",
    "nlp_classifier_v3.final_test_receipt.json": "ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b",
    "duplicate_feature_state_v2.json": "d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731",
    "duplicate_matcher_v1.json": "85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b",
    "duplicate_v1_final_test_receipt.json": "4b97fa5b617c0bf2c93383a8d031be5a9fd6dcd5c08c9b2c229cec9d57ead405",
    "event_grouping_v1.json": "10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973",
    "event_grouping_v1_final_test_receipt.json": "c6ae828fc435275f031175f47500beccada675fb5ad7bd5559c6de8c58e1d913",
    "credibility_v1.json": "8bbd16727be2ba639e031db37a84f0ca92a2a14220fd1819e45dbf689bab7052",
    "credibility_v1_final_test_receipt.json": "d9f3dc044bf57722180ee70fd459f7208233c3e3cd12bac5b35abe557e4c39dc",
}


class ImageValidationBlocked(ValueError):
    """Raised whenever the governed Phase 22 workflow must fail closed."""


class Phase22Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageTrainingConfig(Phase22Model):
    seed: int = DEFAULT_SEED
    image_size: int = Field(default=64, ge=32, le=224)
    batch_size: int = Field(default=256, ge=1)
    epochs: int = Field(default=10, ge=1)
    learning_rate: float = Field(default=0.0015, gt=0.0)
    weight_decay: float = Field(default=0.0001, ge=0.0)
    optimizer: Literal["Adam"] = "Adam"
    scheduler: Literal["CosineAnnealingLR"] = "CosineAnnealingLR"
    torch_threads: int = Field(default=12, ge=1)
    num_workers: Literal[0] = 0
    horizontal_flip_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    crop_min_scale: float = Field(default=0.92, gt=0.0, le=1.0)
    brightness_delta: float = Field(default=0.10, ge=0.0, le=0.5)
    contrast_delta: float = Field(default=0.10, ge=0.0, le=0.5)
    blur_probability: float = Field(default=0.08, ge=0.0, le=1.0)
    noise_probability: float = Field(default=0.10, ge=0.0, le=1.0)
    class_weighting_trigger_ratio: float = Field(default=3.0, ge=1.0)
    min_validation_micro_f1: float = Field(default=0.75, ge=0.0, le=1.0)
    min_validation_macro_f1: float = Field(default=0.72, ge=0.0, le=1.0)
    min_validation_per_label_f1: float = Field(default=0.55, ge=0.0, le=1.0)

    @property
    def augmentations(self) -> list[str]:
        return [
            "deterministic_horizontal_flip",
            "deterministic_random_resized_crop",
            "deterministic_brightness",
            "deterministic_contrast",
            "deterministic_gaussian_blur",
            "deterministic_sensor_noise",
        ]


class LoadedImageSplit(Phase22Model):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    split: Literal["train", "validation", "test"]
    records: list[SyntheticImageModelRecord]
    hidden: list[SyntheticImageGroundTruth] | None = None
    model_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)


class FrozenImageDevelopmentManifest(Phase22Model):
    schema_version: Literal["1.0"] = "1.0"
    phase: str
    model_version: str
    development_status: str
    production_validation: str
    artifact_name: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_name: str
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: str
    dataset_version: str
    dataset_root: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    architecture_version: str
    feature_version: str
    preprocessing_version: str
    augmentation_version: str
    initialization: str
    label_mapping: dict[str, int]
    training_configuration: dict[str, Any]
    selected_epoch: int = Field(ge=1)
    calibration: dict[str, Any]
    thresholds: dict[str, float]
    validation_metrics: dict[str, Any]
    validation_release_checks: dict[str, bool]
    protected_final_test: dict[str, Any]
    source_hashes: dict[str, str]
    protected_artifacts: dict[str, str]
    test_images_accessed_for_selection: bool
    frozen_at: datetime
    policy: dict[str, Any]

    @model_validator(mode="after")
    def validate_governance(self) -> "FrozenImageDevelopmentManifest":
        if self.phase != PHASE or self.model_version != MODEL_VERSION:
            raise ValueError("unexpected Phase 22 model identity")
        if self.development_status != DEVELOPMENT_STATUS:
            raise ValueError("image model must remain development-only synthetic")
        if self.production_validation != PRODUCTION_VALIDATION:
            raise ValueError("synthetic image evidence cannot claim production validation")
        if self.initialization != INITIALIZATION:
            raise ValueError("image model initialization must remain scratch initialized")
        if self.test_images_accessed_for_selection:
            raise ValueError("test images cannot be used for selection")
        if self.label_mapping != {label: index for index, label in enumerate(IMAGE_LABELS)}:
            raise ValueError("frozen image label mapping mismatch")
        if not all(self.validation_release_checks.values()):
            raise ValueError("validation release checks did not all pass")
        if self.calibration.get("fit_source") != "VALIDATION_ONLY":
            raise ValueError("calibration must be validation-only")
        if self.policy.get("network_access") is not False:
            raise ValueError("network access must remain disabled")
        for key in ("pretrained_models", "open_weight_models", "external_apis"):
            if self.policy.get(key) != []:
                raise ValueError(f"{key} must remain empty")
        return self


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _round(value: float) -> float:
    return round(float(value), 10)


def _write_json_atomic(path: Path, value: Any, *, exclusive: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(f"refusing to overwrite locked output: {path.name}")
    payload = (
        value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    if exclusive and path.exists():
        temporary.unlink(missing_ok=True)
        raise FileExistsError(f"refusing to overwrite locked output: {path.name}")
    temporary.replace(path)
    return file_sha256(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _phase22_paths(output_directory: Path | str) -> dict[str, Path]:
    root = local_only_path(output_directory, description="image artifact directories").resolve()
    return {
        "root": root,
        "artifact": root / DEFAULT_ARTIFACT_PATH.name,
        "provenance": root / DEFAULT_PROVENANCE_PATH.name,
        "development_manifest": root / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "training_metrics": root / DEFAULT_TRAINING_METRICS_PATH.name,
        "validation_metrics": root / DEFAULT_VALIDATION_METRICS_PATH.name,
        "calibration": root / DEFAULT_CALIBRATION_PATH.name,
        "validation_errors": root / DEFAULT_VALIDATION_ERRORS_PATH.name,
        "performance": root / DEFAULT_PERFORMANCE_PATH.name,
        "golden": root / DEFAULT_GOLDEN_PATH.name,
        "final_metrics": root / DEFAULT_FINAL_METRICS_PATH.name,
        "error_report": root / DEFAULT_ERROR_REPORT_PATH.name,
        "receipt": root / DEFAULT_FINAL_RECEIPT_PATH.name,
    }


def protected_artifact_snapshot(
    artifact_root: Path | str = ARTIFACT_ROOT,
) -> dict[str, str]:
    root = local_only_path(artifact_root, description="artifact directories").resolve()
    return {
        name: file_sha256(root / name)
        for name in sorted(EXPECTED_FROZEN_CORE_HASHES)
        if (root / name).is_file()
    }


def _assert_frozen_core(snapshot: Mapping[str, str]) -> None:
    mismatches = [
        name
        for name, expected in EXPECTED_FROZEN_CORE_HASHES.items()
        if snapshot.get(name) != expected
    ]
    if mismatches:
        raise ImageValidationBlocked(
            "FROZEN_COMPONENT_HASH_MISMATCH:" + ",".join(sorted(mismatches))
        )


def _source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__),
        Path(__file__).resolve().parents[1] / "data" / "synthetic_image" / "generator.py",
        Path(__file__).resolve().parents[1] / "models" / "custom_cnn.py",
        Path(__file__).resolve().parents[1] / "components" / "image_processing.py",
        Path(__file__).resolve().parents[1] / "image_artifacts.py",
    )
    return {str(path.relative_to(REPOSITORY_ROOT)): file_sha256(path) for path in paths}


def bind_synthetic_image_dataset(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
) -> dict[str, Any]:
    selected_registry = local_only_path(registry_path, description="dataset registries").resolve()
    registry = load_dataset_registry(selected_registry)
    record = find_dataset(registry, DEFAULT_DATASET_ID, DEFAULT_DATASET_VERSION)
    root = local_only_path(dataset_root, description="synthetic image datasets").resolve()
    blockers: list[str] = []
    if record.component is not DatasetComponent.IMAGE:
        blockers.append("COMPONENT_MISMATCH")
    if record.provenance is not DatasetProvenance.PROJECT_AUTHORED:
        blockers.append("PROVENANCE_NOT_PROJECT_AUTHORED")
    if record.data_classification is not DatasetClassification.DEVELOPMENT_ONLY:
        blockers.append("CLASSIFICATION_NOT_DEVELOPMENT_ONLY")
    if record.status is not DatasetStatus.VALID:
        blockers.append("REGISTRY_STATUS_NOT_VALID")
    if resolve_registry_path(record.local_path, selected_registry) != root:
        blockers.append("DATASET_PATH_MISMATCH")
    current_directory_hash = hash_dataset_path(root).content_sha256
    if current_directory_hash != record.content_sha256:
        blockers.append("DIRECTORY_HASH_MISMATCH")
    validation = load_bound_validation_report(record, selected_registry)
    if not validation.valid or validation.leakage.overall_status.value != "PASS":
        blockers.append("COMMON_VALIDATION_FAILED")
    manifest_path = root / "manifest.json"
    quality_path = root / "quality_report.json"
    if not manifest_path.is_file() or not quality_path.is_file():
        blockers.append("SYNTHETIC_EVIDENCE_MISSING")
        manifest: dict[str, Any] = {}
        quality: dict[str, Any] = {}
    else:
        manifest = _read_json(manifest_path)
        quality = _read_json(quality_path)
        if manifest.get("dataset_sha256") != record.metadata.get("dataset_hash"):
            blockers.append("DATASET_HASH_BINDING_MISMATCH")
        if not quality.get("valid"):
            blockers.append("SYNTHETIC_QUALITY_REPORT_FAILED")
        if manifest.get("policy", {}).get("production_validation") != PRODUCTION_VALIDATION:
            blockers.append("PRODUCTION_STATUS_MISMATCH")
    production_gate = evaluate_training_dataset(
        DEFAULT_DATASET_ID,
        DatasetComponent.IMAGE,
        registry_path=selected_registry,
        dataset_version=DEFAULT_DATASET_VERSION,
        supplied_path=root,
    )
    if production_gate.allowed:
        blockers.append("DEVELOPMENT_ONLY_DATA_UNEXPECTEDLY_PASSED_PRODUCTION_GATE")
    if blockers:
        raise ImageValidationBlocked(";".join(blockers))
    return {
        "registry_path": selected_registry,
        "record": record,
        "root": root,
        "manifest_path": manifest_path,
        "quality_path": quality_path,
        "manifest": manifest,
        "quality": quality,
        "common_validation": validation,
        "production_training_gate": production_gate.model_dump(mode="json"),
        "development_gate": {
            "allowed": True,
            "scope": "SYNTHETIC_DEVELOPMENT_ONLY",
            "reason": "Explicit Phase 22 project-authored synthetic workflow",
        },
    }


def load_image_split(
    dataset_root: Path | str,
    split: Literal["train", "validation", "test"],
    *,
    include_hidden: bool,
) -> LoadedImageSplit:
    root = local_only_path(dataset_root, description="synthetic image datasets").resolve()
    model_path = root / "model_inputs" / f"{split}.jsonl"
    records = [
        SyntheticImageModelRecord.model_validate_json(line)
        for line in model_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hidden = None
    if include_hidden:
        hidden_path = root / "hidden_generator_metadata" / f"{split}.jsonl"
        hidden = [
            SyntheticImageGroundTruth.model_validate_json(line)
            for line in hidden_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(hidden) != len(records) or any(
            left.image_id != right.image_id for left, right in zip(records, hidden)
        ):
            raise ImageValidationBlocked(f"{split.upper()}_MODEL_HIDDEN_BINDING_MISMATCH")
    if any(record.split != split for record in records):
        raise ImageValidationBlocked(f"{split.upper()}_SPLIT_LABEL_MISMATCH")
    return LoadedImageSplit(
        split=split,
        records=records,
        hidden=hidden,
        model_input_sha256=file_sha256(model_path),
        row_count=len(records),
    )


def _augmentation_seed(seed: int, epoch: int, image_id: str) -> int:
    payload = f"{seed}|{epoch}|{image_id}|{AUGMENTATION_VERSION}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def apply_local_augmentation(
    image: Image.Image,
    *,
    image_id: str,
    epoch: int,
    config: ImageTrainingConfig,
) -> np.ndarray:
    """Apply deterministic, project-defined pixel transforms only."""

    random = np.random.default_rng(_augmentation_seed(config.seed, epoch, image_id))
    image = image.convert("RGB").resize(
        (config.image_size, config.image_size), Image.Resampling.BILINEAR
    )
    if random.random() < config.horizontal_flip_probability:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    scale = float(random.uniform(config.crop_min_scale, 1.0))
    crop_size = max(2, round(config.image_size * scale))
    left = int(random.integers(0, config.image_size - crop_size + 1))
    top = int(random.integers(0, config.image_size - crop_size + 1))
    image = image.crop((left, top, left + crop_size, top + crop_size)).resize(
        (config.image_size, config.image_size), Image.Resampling.BILINEAR
    )
    image = ImageEnhance.Brightness(image).enhance(
        float(random.uniform(1.0 - config.brightness_delta, 1.0 + config.brightness_delta))
    )
    image = ImageEnhance.Contrast(image).enhance(
        float(random.uniform(1.0 - config.contrast_delta, 1.0 + config.contrast_delta))
    )
    if random.random() < config.blur_probability:
        image = image.filter(ImageFilter.GaussianBlur(radius=float(random.uniform(0.15, 0.75))))
    values = np.asarray(image, dtype=np.float32)
    if random.random() < config.noise_probability:
        values = np.clip(
            values + random.normal(0.0, 3.0, size=values.shape), 0, 255
        ).astype(np.float32)
    return np.ascontiguousarray(
        values.transpose(2, 0, 1) / np.float32(255.0), dtype=np.float32
    )


def _plain_pixels(image: Image.Image, size: int) -> np.ndarray:
    resized = image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
    values = np.asarray(resized, dtype=np.float32) / np.float32(255.0)
    return np.ascontiguousarray(values.transpose(2, 0, 1))


class SyntheticImageTensorDataset(Dataset):
    """Pixel/label dataset; hidden generator records are intentionally absent."""

    def __init__(
        self,
        root: Path,
        records: Sequence[SyntheticImageModelRecord],
        config: ImageTrainingConfig,
        *,
        training: bool,
    ) -> None:
        self.root = root
        self.records = list(records)
        self.config = config
        self.training = training
        self.epoch = 0
        self.label_mapping = {label: index for index, label in enumerate(IMAGE_LABELS)}

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        record = self.records[index]
        with Image.open(self.root / record.image_path) as source:
            pixels = (
                apply_local_augmentation(
                    source,
                    image_id=record.image_id,
                    epoch=self.epoch,
                    config=self.config,
                )
                if self.training
                else _plain_pixels(source, self.config.image_size)
            )
        target = np.zeros(len(IMAGE_LABELS), dtype=np.float32)
        for label in record.labels:
            target[self.label_mapping[label]] = 1.0
        return torch.from_numpy(pixels), torch.from_numpy(target), index


def _state_dict_digest(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(_canonical_json(list(tensor.shape)))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _pos_weight(records: Sequence[SyntheticImageModelRecord], trigger: float) -> tuple[torch.Tensor | None, dict[str, Any]]:
    counts = Counter(label for record in records for label in record.labels)
    values = np.asarray([counts[label] for label in IMAGE_LABELS], dtype=np.float64)
    imbalance_ratio = float(values.max() / max(values.min(), 1.0))
    applied = imbalance_ratio > trigger
    weights = (len(records) - values) / np.maximum(values, 1.0)
    return (
        torch.tensor(weights, dtype=torch.float32) if applied else None,
        {
            "applied": applied,
            "rule": f"apply when max/min positive-label count > {trigger}",
            "imbalance_ratio": _round(imbalance_ratio),
            "positive_counts": {label: int(counts[label]) for label in IMAGE_LABELS},
            "pos_weight": {
                label: _round(weights[index]) for index, label in enumerate(IMAGE_LABELS)
            }
            if applied
            else {},
        },
    )


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _resolve_predictions(probabilities: np.ndarray, thresholds: Sequence[float]) -> np.ndarray:
    threshold_values = np.asarray(thresholds, dtype=np.float64)
    predictions = probabilities >= threshold_values[None, :]
    normal_index = IMAGE_LABELS.index("NORMAL_SCENE")
    for row_index in range(len(predictions)):
        hazard_indexes = np.flatnonzero(predictions[row_index, :normal_index])
        if predictions[row_index, normal_index] and len(hazard_indexes):
            normal_margin = probabilities[row_index, normal_index] - threshold_values[normal_index]
            hazard_margins = probabilities[row_index, hazard_indexes] - threshold_values[hazard_indexes]
            if normal_margin >= float(hazard_margins.max()):
                predictions[row_index, :normal_index] = False
            else:
                predictions[row_index, normal_index] = False
        if not predictions[row_index].any():
            predictions[row_index, int(np.argmax(probabilities[row_index] - threshold_values))] = True
    return predictions


def _metric_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def multilabel_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    threshold_values = [thresholds[label] for label in IMAGE_LABELS]
    predictions = _resolve_predictions(probabilities, threshold_values)
    truth = targets.astype(bool)
    per_label: dict[str, dict[str, Any]] = {}
    totals = Counter()
    for index, label in enumerate(IMAGE_LABELS):
        tp = int(np.sum(truth[:, index] & predictions[:, index]))
        tn = int(np.sum(~truth[:, index] & ~predictions[:, index]))
        fp = int(np.sum(~truth[:, index] & predictions[:, index]))
        fn = int(np.sum(truth[:, index] & ~predictions[:, index]))
        precision = _metric_ratio(tp, tp + fp)
        recall = _metric_ratio(tp, tp + fn)
        f1 = _metric_ratio(2 * tp, 2 * tp + fp + fn)
        per_label[label] = {
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(f1),
            "support": int(np.sum(truth[:, index])),
            "confusion": {"true_negative": tn, "false_positive": fp, "false_negative": fn, "true_positive": tp},
        }
        totals.update(tp=tp, tn=tn, fp=fp, fn=fn)
    micro_precision = _metric_ratio(totals["tp"], totals["tp"] + totals["fp"])
    micro_recall = _metric_ratio(totals["tp"], totals["tp"] + totals["fn"])
    micro_f1 = _metric_ratio(2 * totals["tp"], 2 * totals["tp"] + totals["fp"] + totals["fn"])
    return {
        "sample_count": int(len(targets)),
        "micro_precision": _round(micro_precision),
        "micro_recall": _round(micro_recall),
        "micro_f1": _round(micro_f1),
        "macro_f1": _round(np.mean([item["f1"] for item in per_label.values()])),
        "subset_accuracy": _round(np.mean(np.all(truth == predictions, axis=1))),
        "hamming_loss": _round(np.mean(truth != predictions)),
        "per_label": per_label,
        "predicted_matrix": predictions,
    }


def calibration_metrics(targets: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> dict[str, Any]:
    flat_targets = targets.astype(np.float64).ravel()
    flat_probabilities = probabilities.astype(np.float64).ravel()
    brier = float(np.mean((flat_probabilities - flat_targets) ** 2))
    ece = 0.0
    bin_details: list[dict[str, Any]] = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = (flat_probabilities >= lower) & (
            flat_probabilities <= upper if index == bins - 1 else flat_probabilities < upper
        )
        count = int(selected.sum())
        if not count:
            continue
        confidence = float(flat_probabilities[selected].mean())
        accuracy = float(flat_targets[selected].mean())
        ece += count / len(flat_targets) * abs(confidence - accuracy)
        bin_details.append(
            {
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_score": _round(confidence),
                "positive_rate": _round(accuracy),
            }
        )
    per_label_brier = {
        label: _round(np.mean((probabilities[:, index] - targets[:, index]) ** 2))
        for index, label in enumerate(IMAGE_LABELS)
    }
    return {
        "brier_score": _round(brier),
        "expected_calibration_error": _round(ece),
        "per_label_brier": per_label_brier,
        "bins": bin_details,
    }


def fit_validation_temperature(logits: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    candidates = np.round(np.arange(0.5, 3.01, 0.1), 2)
    temperatures = np.ones(len(IMAGE_LABELS), dtype=np.float64)
    searches: dict[str, Any] = {}
    for index, label in enumerate(IMAGE_LABELS):
        losses = []
        label_targets = targets[:, index]
        for temperature in candidates:
            probabilities = _sigmoid(logits[:, index] / temperature)
            loss = -np.mean(
                label_targets * np.log(np.clip(probabilities, 1e-8, 1.0))
                + (1.0 - label_targets) * np.log(np.clip(1.0 - probabilities, 1e-8, 1.0))
            )
            losses.append(float(loss))
        selected_index = min(
            range(len(candidates)),
            key=lambda item: (losses[item], abs(float(candidates[item]) - 1.0), float(candidates[item])),
        )
        temperatures[index] = float(candidates[selected_index])
        searches[label] = {
            "selected_temperature": _round(temperatures[index]),
            "selected_binary_cross_entropy": _round(losses[selected_index]),
            "candidate_count": len(candidates),
        }
    before = _sigmoid(logits)
    after = _sigmoid(logits / temperatures[None, :])
    return temperatures, {
        "version": CALIBRATION_VERSION,
        "fit_source": "VALIDATION_ONLY",
        "test_images_accessed": False,
        "method": "PER_LABEL_TEMPERATURE_GRID_MINIMUM_BINARY_CROSS_ENTROPY",
        "temperatures": {label: _round(temperatures[index]) for index, label in enumerate(IMAGE_LABELS)},
        "search": searches,
        "before": calibration_metrics(targets, before),
        "after": calibration_metrics(targets, after),
        "score_interpretation": "VALIDATION_TEMPERATURE_CALIBRATED_SYNTHETIC_CONFIDENCE_SCORE",
        "field_probability_claim": False,
    }


def select_validation_thresholds(probabilities: np.ndarray, targets: np.ndarray) -> tuple[dict[str, float], dict[str, Any]]:
    candidates = np.round(np.arange(0.20, 0.801, 0.02), 2)
    thresholds: dict[str, float] = {}
    searches: dict[str, Any] = {}
    for index, label in enumerate(IMAGE_LABELS):
        target = targets[:, index].astype(bool)
        rows: list[tuple[float, float, float, float]] = []
        for threshold in candidates:
            predicted = probabilities[:, index] >= threshold
            tp = int(np.sum(target & predicted))
            fp = int(np.sum(~target & predicted))
            fn = int(np.sum(target & ~predicted))
            f1 = _metric_ratio(2 * tp, 2 * tp + fp + fn)
            precision = _metric_ratio(tp, tp + fp)
            recall = _metric_ratio(tp, tp + fn)
            rows.append((float(threshold), f1, recall, precision))
        selected = max(rows, key=lambda item: (item[1], item[2], item[3], -abs(item[0] - 0.5), -item[0]))
        thresholds[label] = selected[0]
        searches[label] = {
            "selected_threshold": _round(selected[0]),
            "validation_f1": _round(selected[1]),
            "validation_recall": _round(selected[2]),
            "validation_precision": _round(selected[3]),
            "candidate_count": len(candidates),
        }
    return thresholds, {
        "version": THRESHOLD_VERSION,
        "selection_source": "VALIDATION_ONLY",
        "test_images_accessed": False,
        "selection_rule": "MAX_F1_THEN_RECALL_THEN_PRECISION_THEN_CLOSEST_TO_0.5_THEN_LOWER_THRESHOLD",
        "search": searches,
        "selected_thresholds": thresholds,
    }


def _evaluate_model(
    model: nn.Module,
    dataset: SyntheticImageTensorDataset,
    *,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, list[int], float]:
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    logits: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    indexes: list[int] = []
    started = perf_counter()
    model.eval()
    with torch.inference_mode():
        for pixels, target, index in loader:
            logits.append(model(pixels).cpu().numpy())
            targets.append(target.cpu().numpy())
            indexes.extend(int(item) for item in index)
    elapsed = perf_counter() - started
    return np.concatenate(logits), np.concatenate(targets), indexes, elapsed


def train_scratch_cnn(
    dataset_root: Path,
    train: LoadedImageSplit,
    validation: LoadedImageSplit,
    config: ImageTrainingConfig,
) -> dict[str, Any]:
    """Train from local random parameters and select an epoch on validation."""

    torch.set_num_threads(config.torch_threads)
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    torch.use_deterministic_algorithms(True)
    model = build_scratch_cnn_v2(
        ScratchCNNConfig(number_of_classes=len(IMAGE_LABELS), random_seed=config.seed)
    )
    initial_state_hash = _state_dict_digest(model.state_dict())
    train_dataset = SyntheticImageTensorDataset(dataset_root, train.records, config, training=True)
    validation_dataset = SyntheticImageTensorDataset(
        dataset_root, validation.records, config, training=False
    )
    positive_weight, weighting = _pos_weight(
        train.records, config.class_weighting_trigger_ratio
    )
    criterion = nn.BCEWithLogitsLoss(pos_weight=positive_weight)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=config.epochs, eta_min=config.learning_rate * 0.1
    )
    epoch_history: list[dict[str, Any]] = []
    best_key: tuple[float, float, float, int] | None = None
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    samples_processed = 0
    tracemalloc.start()
    training_started = perf_counter()
    for epoch in range(1, config.epochs + 1):
        train_dataset.epoch = epoch
        generator = torch.Generator().manual_seed(config.seed + epoch)
        loader = DataLoader(
            train_dataset,
            batch_size=config.batch_size,
            shuffle=True,
            generator=generator,
            num_workers=config.num_workers,
        )
        model.train()
        total_loss = 0.0
        epoch_started = perf_counter()
        for pixels, targets, _ in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(pixels)
            loss = criterion(logits, targets)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(pixels)
            samples_processed += len(pixels)
        validation_logits, validation_targets, _, validation_seconds = _evaluate_model(
            model, validation_dataset, batch_size=config.batch_size
        )
        fixed_thresholds = {label: 0.5 for label in IMAGE_LABELS}
        metrics = multilabel_metrics(
            validation_targets, _sigmoid(validation_logits), fixed_thresholds
        )
        elapsed = perf_counter() - epoch_started
        row = {
            "epoch": epoch,
            "learning_rate": _round(optimizer.param_groups[0]["lr"]),
            "train_loss": _round(total_loss / len(train_dataset)),
            "validation_micro_f1_at_0.5": metrics["micro_f1"],
            "validation_macro_f1_at_0.5": metrics["macro_f1"],
            "epoch_seconds": _round(elapsed),
            "validation_seconds": _round(validation_seconds),
        }
        epoch_history.append(row)
        selection_key = (
            float(metrics["macro_f1"]),
            float(metrics["micro_f1"]),
            -float(row["train_loss"]),
            -epoch,
        )
        if best_key is None or selection_key > best_key:
            best_key = selection_key
            best_epoch = epoch
            best_state = {
                name: tensor.detach().cpu().clone()
                for name, tensor in model.state_dict().items()
            }
        scheduler.step()
    training_seconds = perf_counter() - training_started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if best_state is None:
        raise ImageValidationBlocked("NO_VALIDATION_SELECTED_STATE")
    model.load_state_dict(best_state, strict=True)
    final_logits, validation_targets, validation_indexes, validation_seconds = _evaluate_model(
        model, validation_dataset, batch_size=config.batch_size
    )
    return {
        "model": model,
        "best_state": best_state,
        "best_epoch": best_epoch,
        "initial_state_hash": initial_state_hash,
        "trained_state_hash": _state_dict_digest(best_state),
        "epoch_history": epoch_history,
        "class_weighting": weighting,
        "validation_logits": final_logits,
        "validation_targets": validation_targets,
        "validation_indexes": validation_indexes,
        "training_performance": {
            "epochs": config.epochs,
            "selected_epoch": best_epoch,
            "total_training_seconds": _round(training_seconds),
            "training_samples_processed": samples_processed,
            "samples_per_second": _round(samples_processed / training_seconds),
            "peak_python_tracemalloc_mb": _round(peak_bytes / (1024 * 1024)),
            "validation_inference_seconds": _round(validation_seconds),
            "measurement_scope": "LOCAL_ENGINEERING_MEASUREMENT_NOT_PRODUCTION_THROUGHPUT",
        },
    }


def _subset_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
    thresholds: Mapping[str, float],
    indexes: Sequence[int],
) -> dict[str, Any]:
    if not indexes:
        return {"sample_count": 0, "status": "INSUFFICIENT_DATA"}
    selected = np.asarray(indexes, dtype=np.int64)
    result = multilabel_metrics(targets[selected], probabilities[selected], thresholds)
    result.pop("predicted_matrix", None)
    result["status"] = "DATA_AVAILABLE"
    return result


def error_analysis(
    split: LoadedImageSplit,
    targets: np.ndarray,
    probabilities: np.ndarray,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    if split.hidden is None:
        raise ValueError("hidden metadata is required only for post-prediction error analysis")
    predicted = _resolve_predictions(probabilities, [thresholds[label] for label in IMAGE_LABELS])
    truth = targets.astype(bool)
    false_positives: dict[str, list[dict[str, Any]]] = {}
    false_negatives: dict[str, list[dict[str, Any]]] = {}
    confusion = Counter()
    for label_index, label in enumerate(IMAGE_LABELS):
        fp_indexes = np.flatnonzero(~truth[:, label_index] & predicted[:, label_index])
        fn_indexes = np.flatnonzero(truth[:, label_index] & ~predicted[:, label_index])
        false_positives[label] = [
            {
                "image_id": split.records[index].image_id,
                "score": _round(probabilities[index, label_index]),
                "scene_class": split.hidden[index].scene_class,
            }
            for index in sorted(fp_indexes, key=lambda item: (-probabilities[item, label_index], split.records[item].image_id))[:50]
        ]
        false_negatives[label] = [
            {
                "image_id": split.records[index].image_id,
                "score": _round(probabilities[index, label_index]),
                "scene_class": split.hidden[index].scene_class,
            }
            for index in sorted(fn_indexes, key=lambda item: (probabilities[item, label_index], split.records[item].image_id))[:50]
        ]
    for row in range(len(truth)):
        missing = np.flatnonzero(truth[row] & ~predicted[row])
        extras = np.flatnonzero(~truth[row] & predicted[row])
        for left in missing:
            for right in extras:
                confusion[f"{IMAGE_LABELS[left]}->{IMAGE_LABELS[right]}"] += 1

    hard_results: dict[str, Any] = {}
    for category in HARD_NEGATIVE_SCENES:
        indexes = [
            index
            for index, hidden in enumerate(split.hidden)
            if hidden.hard_negative_category == category
        ]
        hard_results[category] = _subset_metrics(targets, probabilities, thresholds, indexes)
    subgroup_rules = {
        "low_light": lambda item: item.lighting == "LOW_LIGHT",
        "blurred": lambda item: item.domain_randomization.blur_radius >= 0.5,
        "compressed": lambda item: item.domain_randomization.compression_applied and item.domain_randomization.jpeg_quality <= 65,
        "occluded": lambda item: item.domain_randomization.occlusion_fraction >= 0.08,
    }
    subgroup_results = {
        name: _subset_metrics(
            targets,
            probabilities,
            thresholds,
            [index for index, hidden in enumerate(split.hidden) if predicate(hidden)],
        )
        for name, predicate in subgroup_rules.items()
    }
    return {
        "method": "DETERMINISTIC_LOCAL_LABEL_COMPARISON_NO_EXTERNAL_MODEL",
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "label_confusions": [
            {"pair": pair, "count": count} for pair, count in confusion.most_common()
        ],
        "hard_negative_results": hard_results,
        "degradation_subgroups": subgroup_results,
        "configuration_changed_after_error_analysis": False,
    }


def _inference_benchmark(
    model: nn.Module,
    dataset: SyntheticImageTensorDataset,
    batch_size: int,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    model.eval()
    for count in (1, 100, 1000):
        actual = min(count, len(dataset))
        subset = torch.utils.data.Subset(dataset, range(actual))
        loader = DataLoader(subset, batch_size=batch_size, shuffle=False, num_workers=0)
        started = perf_counter()
        with torch.inference_mode():
            for pixels, _, _ in loader:
                model(pixels)
        elapsed = perf_counter() - started
        results[str(count)] = {
            "images_measured": actual,
            "total_seconds": _round(elapsed),
            "milliseconds_per_image": _round(elapsed * 1000.0 / actual),
            "images_per_second": _round(actual / elapsed),
        }
    return {
        "scope": "LOCAL_ENGINEERING_MEASUREMENT_NOT_PRODUCTION_THROUGHPUT",
        "includes_local_file_decode": True,
        "measurements": results,
    }


def _image_config(training: ImageTrainingConfig) -> ImageAnalysisConfig:
    return ImageAnalysisConfig(
        preprocessing_version=PREPROCESSING_VERSION,
        feature_version=FEATURE_VERSION,
        architecture_version=ARCHITECTURE_VERSION,
        model_version=MODEL_VERSION,
        target_width=training.image_size,
        target_height=training.image_size,
        random_seed=training.seed,
        num_classes=len(IMAGE_LABELS),
        optimizer=training.optimizer,
        learning_rate=training.learning_rate,
        epochs=training.epochs,
        batch_size=training.batch_size,
    )


def _update_artifact_manifest(
    manifest_path: Path,
    *,
    artifact_path: Path,
    dataset_hash: str,
    config: ImageTrainingConfig,
) -> str:
    manifest = ArtifactManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    entries = [
        item
        for item in manifest.artifacts
        if not (
            item.artifact_name == artifact_path.name
            and item.intended_component == "image_analyzer"
        )
    ]
    entries.append(
        ArtifactMetadata(
            artifact_name=artifact_path.name,
            artifact_version=MODEL_VERSION,
            sha256=file_sha256(artifact_path),
            training_dataset_hash=dataset_hash,
            feature_version=FEATURE_VERSION,
            preprocessing_version=PREPROCESSING_VERSION,
            training_timestamp=FREEZE_TIMESTAMP,
            random_seed=config.seed,
            framework_versions={
                "python": platform.python_version(),
                "torch": torch.__version__,
                "numpy": np.__version__,
                "pillow": Image.__version__,
            },
            intended_component="image_analyzer",
            policy_status=ArtifactPolicyStatus.COMPLIANT,
        )
    )
    updated = manifest.model_copy(update={"artifacts": entries})
    return _write_json_atomic(manifest_path, updated)


def _provenance(
    artifact_path: Path,
    dataset_manifest: Mapping[str, Any],
    train: LoadedImageSplit,
    validation: LoadedImageSplit,
    config: ImageTrainingConfig,
) -> ImageArtifactProvenance:
    class_distribution = Counter(label for record in train.records for label in record.labels)
    return ImageArtifactProvenance(
        artifact_name=artifact_path.name,
        model_version=MODEL_VERSION,
        architecture_version=ARCHITECTURE_VERSION,
        feature_version=FEATURE_VERSION,
        dataset_hash=str(dataset_manifest["dataset_sha256"]),
        preprocessing_version=PREPROCESSING_VERSION,
        training_config=ImageTrainingProvenance(
            dataset_version=DEFAULT_DATASET_VERSION,
            annotation_schema_version=IMAGE_ANNOTATION_SCHEMA_VERSION,
            optimizer=config.optimizer,
            learning_rate=config.learning_rate,
            scheduler=config.scheduler,
            epochs=config.epochs,
            batch_size=config.batch_size,
            weight_initialization="LOCAL_RANDOM_KAIMING_XAVIER",
            validation_dataset_hash=validation.model_input_sha256,
            augmentations=config.augmentations,
            class_distribution={label: int(class_distribution[label]) for label in IMAGE_LABELS},
            training_timestamp=FREEZE_TIMESTAMP,
        ),
        random_seed=config.seed,
        framework_version=torch.__version__,
        artifact_sha256=file_sha256(artifact_path),
        policy_status=ArtifactPolicyStatus.COMPLIANT,
        source="PROJECT_TRAINED",
        initialization="SCRATCH_INITIALIZED",
        development_status="DEVELOPMENT_ONLY",
        project_controlled_dataset=True,
        pretrained_weights_used=False,
        external_weights_used=False,
        label_mapping={label: index for index, label in enumerate(IMAGE_LABELS)},
    )


def load_image_development_manifest(
    path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
) -> FrozenImageDevelopmentManifest:
    selected = local_only_path(path, description="image development manifests")
    return FrozenImageDevelopmentManifest.model_validate_json(
        selected.read_text(encoding="utf-8")
    )


class ProjectTrainedImageAnalyzer:
    """Explicit opt-in development analyzer; the live default remains offline."""

    component_name = "image_analyzer"

    def __init__(
        self,
        *,
        artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
        provenance_path: Path | str = DEFAULT_PROVENANCE_PATH,
        development_manifest_path: Path | str = DEFAULT_DEVELOPMENT_MANIFEST_PATH,
        artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    ) -> None:
        self.development = load_image_development_manifest(development_manifest_path)
        self.provenance = ImageArtifactProvenance.model_validate_json(
            local_only_path(provenance_path, description="image provenance files").read_text(
                encoding="utf-8"
            )
        )
        self.config = ImageAnalysisConfig(
            preprocessing_version=self.development.preprocessing_version,
            feature_version=self.development.feature_version,
            architecture_version=self.development.architecture_version,
            model_version=self.development.model_version,
            target_width=int(self.development.training_configuration["image_size"]),
            target_height=int(self.development.training_configuration["image_size"]),
            random_seed=int(self.development.training_configuration["seed"]),
            num_classes=len(IMAGE_LABELS),
        )
        manifest = ArtifactManifest.model_validate_json(
            local_only_path(artifact_manifest_path, description="artifact manifests").read_text(
                encoding="utf-8"
            )
        )
        state = load_image_state_dict(
            artifact_path,
            self.provenance,
            manifest,
            config=self.config,
        )
        self.model = build_scratch_cnn_v2(
            ScratchCNNConfig(
                number_of_classes=len(IMAGE_LABELS),
                random_seed=self.provenance.random_seed,
            )
        )
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        self.thresholds = np.asarray(
            [self.development.thresholds[label] for label in IMAGE_LABELS],
            dtype=np.float64,
        )
        self.temperatures = np.asarray(
            [self.development.calibration["temperatures"][label] for label in IMAGE_LABELS],
            dtype=np.float64,
        )

    def predict(self, value: ImageInput | ReportInput) -> ImagePrediction:
        image = image_input_from_report(value) if isinstance(value, ReportInput) else value
        if image is None:
            return ImagePrediction(
                status=PredictionStatus.NOT_APPLICABLE,
                model_version=MODEL_VERSION,
                feature_version=FEATURE_VERSION,
                preprocessing_version=PREPROCESSING_VERSION,
                task_type="MULTI_LABEL",
                calibration_status=CalibrationStatus.CALIBRATED,
                reason_codes=["IMAGE_NOT_SUPPLIED"],
                warnings=["No already-loaded image bytes were supplied."],
            )
        try:
            processed = preprocess_image(image, config=self.config)
        except ImageValidationException as error:
            return ImagePrediction(
                status=PredictionStatus.ERROR,
                image_id=image.image_id,
                model_version=MODEL_VERSION,
                feature_version=FEATURE_VERSION,
                preprocessing_version=PREPROCESSING_VERSION,
                task_type="MULTI_LABEL",
                calibration_status=CalibrationStatus.CALIBRATED,
                reason_codes=[item.code for item in error.result.errors],
                warnings=[item.message for item in error.result.warnings],
            )
        tensor = torch.from_numpy(processed.pixel_values).unsqueeze(0)
        with torch.inference_mode():
            logits = self.model(tensor).cpu().numpy()
        scores = _sigmoid(logits / self.temperatures[None, :])
        predicted = _resolve_predictions(scores, self.thresholds)[0]
        score_mapping = {
            label: _round(scores[0, index]) for index, label in enumerate(IMAGE_LABELS)
        }
        labels = [label for index, label in enumerate(IMAGE_LABELS) if predicted[index]]
        return ImagePrediction(
            status=PredictionStatus.AVAILABLE,
            image_id=image.image_id,
            model_version=MODEL_VERSION,
            feature_version=FEATURE_VERSION,
            preprocessing_version=PREPROCESSING_VERSION,
            labels=labels,
            probabilities=score_mapping,
            confidence=max(score_mapping.values()),
            task_type="MULTI_LABEL",
            calibration_status=CalibrationStatus.CALIBRATED,
            evidence=[
                f"BYTE_HASH:{byte_sha256(image.image_bytes)}",
                "PROJECT_TRAINED:SYNTHETIC_DEVELOPMENT_ONLY",
                "INITIALIZATION:SCRATCH_NO_PRETRAINED_WEIGHTS",
            ],
            reason_codes=["SYNTHETIC_DEVELOPMENT_MODEL"],
            warnings=[
                "Scores are validation-temperature calibrated only on project-authored synthetic data.",
                "Production and field visual-performance validation are NOT_VALIDATED.",
            ],
        )


def _golden_integration(
    analyzer: ProjectTrainedImageAnalyzer,
    validation: LoadedImageSplit,
    dataset_root: Path,
) -> dict[str, Any]:
    from app.ml.golden.runner import execute_golden_scenario, validate_golden_scenario
    from app.ml.golden.schema import load_golden_scenarios
    from app.ml.inference.engine import InferenceEngine

    trained_engine = InferenceEngine(image_analyzer=analyzer)  # explicit opt-in only
    suite = load_golden_scenarios()
    scenario_results = [
        validate_golden_scenario(
            scenario,
            execute_golden_scenario(scenario, engine=trained_engine),
        )
        for scenario in suite.scenarios
    ]
    record = validation.records[0]
    payload = (dataset_root / record.image_path).read_bytes()
    report = ReportInput(
        report_id=UUID(int=22_000),
        text="Synthetic golden image-present engineering regression report.",
        occurred_at=FREEZE_TIMESTAMP,
        latitude=25.5941,
        longitude=85.1376,
        source_type="TEST_FIXTURE",
        source_metadata={
            "fixture_status": "TEST_FIXTURE_ONLY",
            "data_origin": "PROJECT_AUTHORED_SYNTHETIC",
            "image_id": record.image_id,
            "image_mime_type": "image/png",
            "image_width": 64,
            "image_height": 64,
            "image_checksum": record.byte_sha256,
        },
        image_bytes=payload,
    )
    available = trained_engine.analyze(report)
    offline = InferenceEngine(image_analyzer=ImageAnalyzer()).analyze(report)
    absent_report = report.model_copy(
        update={"image_bytes": None, "source_metadata": {"fixture_status": "TEST_FIXTURE_ONLY"}}
    )
    absent = trained_engine.analyze(absent_report)
    other_fields = (
        "text_prediction",
        "duplicate_prediction",
        "event_prediction",
        "credibility_prediction",
        "anomaly_prediction",
    )
    no_cross_effects = all(
        getattr(available, field) == getattr(offline, field) for field in other_fields
    )
    round_trip = UnifiedMLResult.model_validate_json(available.model_dump_json()) == available
    checks = {
        "existing_golden_scenarios_pass": len(scenario_results) == len(suite.scenarios),
        "schema_compatibility": tuple(available.model_dump(mode="json")) == tuple(UnifiedMLResult.model_fields),
        "serialization_round_trip": round_trip,
        "version_consistency": (
            available.image_prediction.model_version == MODEL_VERSION
            and available.model_versions.get("image_analyzer") == MODEL_VERSION
            and available.feature_versions.get("image_analyzer") == FEATURE_VERSION
        ),
        "missing_image_behavior": absent.image_prediction.status is PredictionStatus.NOT_APPLICABLE,
        "image_present_behavior": (
            available.image_prediction.status is PredictionStatus.AVAILABLE
            and set(available.image_prediction.probabilities) == set(IMAGE_LABELS)
            and bool(available.image_prediction.labels)
        ),
        "no_effect_on_other_components": no_cross_effects,
    }
    if not all(checks.values()):
        raise ImageValidationBlocked("GOLDEN_INTEGRATION_FAILED")
    return {
        "scope": "SYNTHETIC_ENGINEERING_REGRESSION_ONLY",
        "scenario_count": len(suite.scenarios),
        "checks": checks,
        "image_present_prediction": available.image_prediction.model_dump(mode="json"),
        "missing_image_prediction": absent.image_prediction.model_dump(mode="json"),
        "production_validation": PRODUCTION_VALIDATION,
    }


def freeze_image_development(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
    training_config: ImageTrainingConfig | None = None,
) -> dict[str, Any]:
    """Train/select/calibrate/freeze without opening protected test records."""

    config = training_config or ImageTrainingConfig()
    paths = _phase22_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    guarded = [path for name, path in paths.items() if name != "root"]
    existing = [path.name for path in guarded if path.exists()]
    if existing:
        raise ImageValidationBlocked("PHASE22_FREEZE_OUTPUT_ALREADY_EXISTS:" + ",".join(existing))
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    _assert_frozen_core(protected_before)
    binding = bind_synthetic_image_dataset(
        registry_path=registry_path, dataset_root=dataset_root
    )
    root: Path = binding["root"]
    dataset_manifest = binding["manifest"]
    train = load_image_split(root, "train", include_hidden=False)
    validation = load_image_split(root, "validation", include_hidden=True)
    if train.model_input_sha256 != dataset_manifest["split_sha256"]["train"]:
        raise ImageValidationBlocked("TRAIN_SPLIT_HASH_MISMATCH")
    if validation.model_input_sha256 != dataset_manifest["split_sha256"]["validation"]:
        raise ImageValidationBlocked("VALIDATION_SPLIT_HASH_MISMATCH")
    # Test content is not loaded here.  Only its generator-recorded descriptor is bound.
    test_path = root / "model_inputs" / "test.jsonl"
    protected_test = {
        "model_input_path": str(test_path),
        "model_input_sha256": file_sha256(test_path),
        "hidden_metadata_sha256": file_sha256(
            root / "hidden_generator_metadata" / "test.jsonl"
        ),
        "row_count": int(dataset_manifest["split_counts"]["test"]),
        "accessed_for_selection": False,
        "accessed_for_calibration": False,
        "accessed_for_threshold_selection": False,
    }

    result = train_scratch_cnn(root, train, validation, config)
    temperatures, calibration = fit_validation_temperature(
        result["validation_logits"], result["validation_targets"]
    )
    validation_probabilities = _sigmoid(
        result["validation_logits"] / temperatures[None, :]
    )
    thresholds, threshold_search = select_validation_thresholds(
        validation_probabilities, result["validation_targets"]
    )
    metrics = multilabel_metrics(
        result["validation_targets"], validation_probabilities, thresholds
    )
    metrics.pop("predicted_matrix", None)
    errors = error_analysis(
        validation,
        result["validation_targets"],
        validation_probabilities,
        thresholds,
    )
    release_checks = {
        "micro_f1": float(metrics["micro_f1"]) >= config.min_validation_micro_f1,
        "macro_f1": float(metrics["macro_f1"]) >= config.min_validation_macro_f1,
        "per_label_f1": all(
            float(item["f1"]) >= config.min_validation_per_label_f1
            for item in metrics["per_label"].values()
        ),
        "all_labels_present": set(dataset_manifest["label_distribution"]) == set(IMAGE_LABELS),
        "held_out_test": all(binding["quality"]["holdout_checks"].values()),
        "leakage": binding["quality"]["leakage_checks"]["status"] == "PASS",
        "scratch_initialization": result["initial_state_hash"] != result["trained_state_hash"],
        "test_not_accessed": True,
    }
    if not all(release_checks.values()):
        raise ImageValidationBlocked(
            "VALIDATION_RELEASE_CHECK_FAILED:"
            + ",".join(name for name, passed in release_checks.items() if not passed)
        )

    performance = {
        "training": result["training_performance"],
        "inference": _inference_benchmark(
            result["model"],
            SyntheticImageTensorDataset(root, validation.records, config, training=False),
            config.batch_size,
        ),
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "device": "CPU",
            "torch_threads": torch.get_num_threads(),
        },
    }
    training_report = {
        "phase": PHASE,
        "architecture": ARCHITECTURE_VERSION,
        "initialization": "SCRATCH / NO PRETRAINED WEIGHTS",
        "loss": "BCEWithLogitsLoss",
        "output_activation_for_scoring": "SIGMOID",
        "softmax_used": False,
        "seed": config.seed,
        "optimizer": config.optimizer,
        "learning_rate": config.learning_rate,
        "scheduler": config.scheduler,
        "batch_size": config.batch_size,
        "epochs": config.epochs,
        "weight_initialization": "Kaiming uniform convolution / Xavier uniform linear / local RNG only",
        "training_dataset_sha256": train.model_input_sha256,
        "validation_dataset_sha256": validation.model_input_sha256,
        "augmentation_version": AUGMENTATION_VERSION,
        "augmentations": config.augmentations,
        "class_weighting": result["class_weighting"],
        "selection_rule": "MAX_VALIDATION_MACRO_F1_THEN_MICRO_F1_THEN_LOWER_TRAIN_LOSS_THEN_EARLIER_EPOCH",
        "selected_epoch": result["best_epoch"],
        "epoch_history": result["epoch_history"],
        "initial_state_sha256": result["initial_state_hash"],
        "trained_state_sha256": result["trained_state_hash"],
        "test_images_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }
    validation_report = {
        "phase": PHASE,
        "evaluation_label": "SYNTHETIC_VALIDATION_MODEL_SELECTION_CALIBRATION_THRESHOLD_SELECTION",
        "metrics": metrics,
        "thresholds": thresholds,
        "threshold_search": threshold_search,
        "calibration": calibration,
        "hard_negative_results": errors["hard_negative_results"],
        "degradation_subgroups": errors["degradation_subgroups"],
        "release_checks": release_checks,
        "test_images_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }
    paths["root"].mkdir(parents=True, exist_ok=True)
    _write_json_atomic(paths["training_metrics"], training_report, exclusive=True)
    _write_json_atomic(paths["validation_metrics"], validation_report, exclusive=True)
    _write_json_atomic(paths["calibration"], calibration, exclusive=True)
    _write_json_atomic(paths["validation_errors"], errors, exclusive=True)
    _write_json_atomic(paths["performance"], performance, exclusive=True)

    # The .pt file is created only after every validation release check passes.
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=paths["root"], prefix=paths["artifact"].name + ".", suffix=".tmp", delete=False
    ) as handle:
        temporary_artifact = Path(handle.name)
    try:
        torch.save(result["best_state"], temporary_artifact)
        if paths["artifact"].exists():
            raise FileExistsError(f"refusing to overwrite locked output: {paths['artifact'].name}")
        temporary_artifact.replace(paths["artifact"])
    finally:
        temporary_artifact.unlink(missing_ok=True)
    artifact_hash = file_sha256(paths["artifact"])
    provenance = _provenance(
        paths["artifact"], dataset_manifest, train, validation, config
    )
    provenance_hash = _write_json_atomic(paths["provenance"], provenance, exclusive=True)
    artifact_manifest_hash = _update_artifact_manifest(
        manifest_path,
        artifact_path=paths["artifact"],
        dataset_hash=dataset_manifest["dataset_sha256"],
        config=config,
    )
    authorized = authorize_image_artifact(
        paths["artifact"],
        provenance,
        ArtifactManifest.model_validate_json(manifest_path.read_text(encoding="utf-8")),
        config=_image_config(config),
    )
    if authorized != paths["artifact"].resolve():
        raise ImageValidationBlocked("ARTIFACT_AUTHORIZATION_PATH_MISMATCH")

    source_hashes = _source_hashes()
    development_payload = FrozenImageDevelopmentManifest(
        phase=PHASE,
        model_version=MODEL_VERSION,
        development_status=DEVELOPMENT_STATUS,
        production_validation=PRODUCTION_VALIDATION,
        artifact_name=paths["artifact"].name,
        artifact_sha256=artifact_hash,
        provenance_name=paths["provenance"].name,
        provenance_sha256=provenance_hash,
        artifact_manifest_sha256=artifact_manifest_hash,
        dataset_id=DEFAULT_DATASET_ID,
        dataset_version=DEFAULT_DATASET_VERSION,
        dataset_root=str(root),
        dataset_sha256=dataset_manifest["dataset_sha256"],
        dataset_manifest_sha256=file_sha256(binding["manifest_path"]),
        training_dataset_sha256=train.model_input_sha256,
        validation_dataset_sha256=validation.model_input_sha256,
        generator_version=GENERATOR_VERSION,
        architecture_version=ARCHITECTURE_VERSION,
        feature_version=FEATURE_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        augmentation_version=AUGMENTATION_VERSION,
        initialization=INITIALIZATION,
        label_mapping={label: index for index, label in enumerate(IMAGE_LABELS)},
        training_configuration=config.model_dump(mode="json"),
        selected_epoch=result["best_epoch"],
        calibration=calibration,
        thresholds=thresholds,
        validation_metrics=metrics,
        validation_release_checks=release_checks,
        protected_final_test=protected_test,
        source_hashes=source_hashes,
        protected_artifacts=protected_before,
        test_images_accessed_for_selection=False,
        frozen_at=FREEZE_TIMESTAMP,
        policy={
            "project_trained": True,
            "scratch_initialized": True,
            "development_only": True,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "runtime_downloads": False,
            "live_backend_modified": False,
        },
    )
    _write_json_atomic(paths["development_manifest"], development_payload, exclusive=True)
    analyzer = ProjectTrainedImageAnalyzer(
        artifact_path=paths["artifact"],
        provenance_path=paths["provenance"],
        development_manifest_path=paths["development_manifest"],
        artifact_manifest_path=manifest_path,
    )
    golden = _golden_integration(analyzer, validation, root)
    _write_json_atomic(paths["golden"], golden, exclusive=True)
    if protected_artifact_snapshot(ARTIFACT_ROOT) != protected_before:
        raise ImageValidationBlocked("FROZEN_CORE_CHANGED_DURING_IMAGE_FREEZE")
    return {
        "status": "DEVELOPMENT_FREEZE_COMPLETE",
        "artifact": str(paths["artifact"]),
        "artifact_sha256": artifact_hash,
        "dataset_sha256": dataset_manifest["dataset_sha256"],
        "selected_epoch": result["best_epoch"],
        "validation_metrics": metrics,
        "production_validation": PRODUCTION_VALIDATION,
        "test_images_accessed": False,
    }


def _verify_frozen_development(
    paths: Mapping[str, Path],
    *,
    artifact_manifest_path: Path,
) -> tuple[FrozenImageDevelopmentManifest, ImageArtifactProvenance]:
    development = load_image_development_manifest(paths["development_manifest"])
    provenance = ImageArtifactProvenance.model_validate_json(
        paths["provenance"].read_text(encoding="utf-8")
    )
    checks = {
        "artifact": file_sha256(paths["artifact"]) == development.artifact_sha256,
        "provenance": file_sha256(paths["provenance"]) == development.provenance_sha256,
        "artifact_manifest": file_sha256(artifact_manifest_path)
        == development.artifact_manifest_sha256,
        "dataset_manifest": file_sha256(Path(development.dataset_root) / "manifest.json")
        == development.dataset_manifest_sha256,
        "sources": _source_hashes() == development.source_hashes,
        "protected_artifacts": protected_artifact_snapshot(ARTIFACT_ROOT)
        == development.protected_artifacts,
    }
    if not all(checks.values()):
        raise ImageValidationBlocked(
            "FROZEN_DEVELOPMENT_VERIFICATION_FAILED:"
            + ",".join(name for name, passed in checks.items() if not passed)
        )
    manifest = ArtifactManifest.model_validate_json(
        artifact_manifest_path.read_text(encoding="utf-8")
    )
    authorize_image_artifact(
        paths["artifact"],
        provenance,
        manifest,
        config=ImageAnalysisConfig(
            preprocessing_version=development.preprocessing_version,
            feature_version=development.feature_version,
            architecture_version=development.architecture_version,
            model_version=development.model_version,
            target_width=int(development.training_configuration["image_size"]),
            target_height=int(development.training_configuration["image_size"]),
        ),
    )
    return development, provenance


def _claim_final_evaluation(
    receipt_path: Path,
    *,
    development_manifest_sha256: str,
    artifact_sha256: str,
) -> None:
    if receipt_path.exists():
        raise RuntimeError("image final reevaluation is prohibited by the one-shot receipt")
    claim = {
        "schema_version": "1.0",
        "status": "FINAL_EVALUATION_CLAIMED",
        "phase": PHASE,
        "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
        "development_manifest_sha256": development_manifest_sha256,
        "artifact_sha256": artifact_sha256,
    }
    _write_json_atomic(receipt_path, claim, exclusive=True)


def finalize_image_evaluation(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Consume the protected synthetic image test partition exactly once."""

    paths = _phase22_paths(output_directory)
    manifest_path = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    if paths["receipt"].exists():
        raise RuntimeError("image final reevaluation is prohibited by the one-shot receipt")
    if paths["final_metrics"].exists() or paths["error_report"].exists():
        raise ImageValidationBlocked("UNRECEIPTED_FINAL_OUTPUT_EXISTS")
    development, provenance = _verify_frozen_development(
        paths, artifact_manifest_path=manifest_path
    )
    binding = bind_synthetic_image_dataset(
        registry_path=registry_path, dataset_root=dataset_root
    )
    if binding["manifest"]["dataset_sha256"] != development.dataset_sha256:
        raise ImageValidationBlocked("FINAL_DATASET_HASH_MISMATCH")
    descriptor = development.protected_final_test
    test_model_path = binding["root"] / "model_inputs" / "test.jsonl"
    test_hidden_path = binding["root"] / "hidden_generator_metadata" / "test.jsonl"
    if (
        file_sha256(test_model_path) != descriptor["model_input_sha256"]
        or file_sha256(test_hidden_path) != descriptor["hidden_metadata_sha256"]
    ):
        raise ImageValidationBlocked("PROTECTED_TEST_DESCRIPTOR_MISMATCH")
    development_hash = file_sha256(paths["development_manifest"])
    artifact_hash = file_sha256(paths["artifact"])
    manifest_hash = file_sha256(manifest_path)
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    source_before = _source_hashes()
    _claim_final_evaluation(
        paths["receipt"],
        development_manifest_sha256=development_hash,
        artifact_sha256=artifact_hash,
    )
    try:
        test = load_image_split(binding["root"], "test", include_hidden=True)
        if test.row_count != int(descriptor["row_count"]):
            raise ImageValidationBlocked("PROTECTED_TEST_ROW_COUNT_MISMATCH")
        config = ImageTrainingConfig.model_validate(development.training_configuration)
        model = build_scratch_cnn_v2(
            ScratchCNNConfig(number_of_classes=len(IMAGE_LABELS), random_seed=provenance.random_seed)
        )
        state = load_image_state_dict(
            paths["artifact"],
            provenance,
            ArtifactManifest.model_validate_json(manifest_path.read_text(encoding="utf-8")),
            config=_image_config(config),
        )
        model.load_state_dict(state, strict=True)
        dataset = SyntheticImageTensorDataset(binding["root"], test.records, config, training=False)
        logits, targets, _, inference_seconds = _evaluate_model(
            model, dataset, batch_size=config.batch_size
        )
        temperatures = np.asarray(
            [development.calibration["temperatures"][label] for label in IMAGE_LABELS]
        )
        probabilities = _sigmoid(logits / temperatures[None, :])
        metrics = multilabel_metrics(targets, probabilities, development.thresholds)
        metrics.pop("predicted_matrix", None)
        calibration = calibration_metrics(targets, probabilities)
        errors = error_analysis(test, targets, probabilities, development.thresholds)
        final_metrics = {
            "schema_version": "1.0",
            "phase": PHASE,
            "evaluation_label": "FINAL_SYNTHETIC_IMAGE_HOLDOUT_EVALUATION",
            "evaluation_split": "test",
            "evaluation_invocation_count": 1,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_model_selection": False,
            "test_used_for_calibration": False,
            "test_used_for_threshold_selection": False,
            "dataset_sha256": development.dataset_sha256,
            "test_model_input_sha256": test.model_input_sha256,
            "artifact_sha256": artifact_hash,
            "thresholds": development.thresholds,
            "calibration": {
                "status": "VALIDATION_TEMPERATURE_CALIBRATED",
                "fit_source": "VALIDATION_ONLY",
                "test_metrics": calibration,
                "field_probability_claim": False,
            },
            "metrics": metrics,
            "hard_negative_results": errors["hard_negative_results"],
            "degradation_subgroups": errors["degradation_subgroups"],
            "inference_seconds": _round(inference_seconds),
            "production_validation": PRODUCTION_VALIDATION,
            "limitations": [
                "The holdout is project-authored synthetic development data.",
                "Metrics do not estimate field visual performance or production behavior.",
                "Calibration is synthetic-validation calibration, not field probability calibration.",
            ],
        }
        error_report = {
            "schema_version": "1.0",
            "phase": PHASE,
            "validation_failure_analysis": _read_json(paths["validation_errors"]),
            "final_test_failure_analysis": errors,
            "analysis_method": "DETERMINISTIC_LOCAL_NO_EXTERNAL_MODEL",
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
            "source_files": _source_hashes() == source_before,
            "protected_components": protected_artifact_snapshot(ARTIFACT_ROOT)
            == protected_before,
        }
        if not all(frozen_checks.values()):
            raise ImageValidationBlocked("FROZEN_STATE_CHANGED_DURING_FINAL_TEST")
        receipt = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_COMPLETE",
            "phase": PHASE,
            "evaluation_label": "FINAL_SYNTHETIC_IMAGE_HOLDOUT_EVALUATION",
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "completed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "dataset_id": DEFAULT_DATASET_ID,
            "dataset_version": DEFAULT_DATASET_VERSION,
            "dataset_sha256": development.dataset_sha256,
            "test_model_input_sha256": test.model_input_sha256,
            "test_images": test.row_count,
            "development_manifest_sha256": development_hash,
            "artifact_sha256": artifact_hash,
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
            "metrics": metrics,
            "calibration": final_metrics["calibration"],
            "production_validation": PRODUCTION_VALIDATION,
            "live_backend_modified": False,
            "nlp_modified": False,
            "duplicate_modified": False,
            "event_modified": False,
            "credibility_modified": False,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        }
        _write_json_atomic(paths["receipt"], receipt)
        return receipt
    except Exception as error:
        failure = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_FAILED_LOCKED",
            "phase": PHASE,
            "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "development_manifest_sha256": development_hash,
            "artifact_sha256": artifact_hash,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        _write_json_atomic(paths["receipt"], failure)
        raise


__all__ = [
    "ARCHITECTURE_VERSION",
    "ARTIFACT_ROOT",
    "DEFAULT_ARTIFACT_MANIFEST_PATH",
    "DEFAULT_ARTIFACT_PATH",
    "DEFAULT_DATASET_ROOT",
    "DEFAULT_DEVELOPMENT_MANIFEST_PATH",
    "DEFAULT_FINAL_METRICS_PATH",
    "DEFAULT_FINAL_RECEIPT_PATH",
    "DEFAULT_PROVENANCE_PATH",
    "EXPECTED_FROZEN_CORE_HASHES",
    "FrozenImageDevelopmentManifest",
    "ImageTrainingConfig",
    "ImageValidationBlocked",
    "ProjectTrainedImageAnalyzer",
    "apply_local_augmentation",
    "bind_synthetic_image_dataset",
    "calibration_metrics",
    "error_analysis",
    "finalize_image_evaluation",
    "fit_validation_temperature",
    "freeze_image_development",
    "load_image_development_manifest",
    "load_image_split",
    "multilabel_metrics",
    "protected_artifact_snapshot",
    "select_validation_thresholds",
    "train_scratch_cnn",
]
