"""Phase 22 procedural image, scratch training, and one-shot governance tests."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import socket
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import torch
from PIL import Image

from app.ml.components.image_processing import preprocess_image
from app.ml.contracts import ImageInput, PredictionStatus
from app.ml.data.registry import DatasetRegistry, save_dataset_registry
from app.ml.data.synthetic_image import (
    HARD_NEGATIVE_SCENES,
    IMAGE_LABELS,
    SCENE_CLASS_LABELS,
    SyntheticImageGeneratorConfig,
    SyntheticImageModelRecord,
    generate_synthetic_scene,
    register_synthetic_image_dataset,
    write_synthetic_image_dataset,
)
from app.ml.image_artifacts import (
    ImageArtifactProvenance,
    authorize_image_artifact,
    load_image_state_dict,
)
from app.ml.models.custom_cnn import ScratchCNNConfig, build_scratch_cnn_v2
from app.ml.training.image_synthetic_validation import (
    DEFAULT_ARTIFACT_MANIFEST_PATH,
    ImageTrainingConfig,
    ProjectTrainedImageAnalyzer,
    apply_local_augmentation,
    finalize_image_evaluation,
    freeze_image_development,
    load_image_development_manifest,
)


SMALL_GENERATOR_CONFIG = SyntheticImageGeneratorConfig(
    train_images=240,
    validation_images=120,
    test_images=120,
    generator_workers=4,
)


@pytest.fixture(scope="module")
def phase22_test_root():
    parent = Path(__file__).resolve().parents[3] / ".phase22-test-tmp"
    root = parent / f"case-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


@pytest.fixture(scope="module")
def small_dataset(phase22_test_root):
    root = phase22_test_root / "dataset" / "synthetic_v1"
    return write_synthetic_image_dataset(root, config=SMALL_GENERATOR_CONFIG)


@pytest.fixture(scope="module")
def frozen_workflow(phase22_test_root, small_dataset):
    workspace = phase22_test_root / "freeze"
    registry_path = workspace / "registry" / "datasets.json"
    save_dataset_registry(
        DatasetRegistry(
            last_modified_at=SMALL_GENERATOR_CONFIG.creation_timestamp,
            entries=[],
        ),
        registry_path,
        modified_at=SMALL_GENERATOR_CONFIG.creation_timestamp,
    )
    register_synthetic_image_dataset(
        small_dataset,
        config=SMALL_GENERATOR_CONFIG,
        registry_path=registry_path,
    )
    artifact_directory = workspace / "artifacts"
    artifact_directory.mkdir(parents=True)
    manifest_path = artifact_directory / "manifest.json"
    shutil.copy2(DEFAULT_ARTIFACT_MANIFEST_PATH, manifest_path)
    result = freeze_image_development(
        registry_path=registry_path,
        dataset_root=small_dataset.output_directory,
        output_directory=artifact_directory,
        artifact_manifest_path=manifest_path,
        training_config=ImageTrainingConfig(
            epochs=2,
            batch_size=64,
            min_validation_micro_f1=0.0,
            min_validation_macro_f1=0.0,
            min_validation_per_label_f1=0.0,
        ),
    )
    return {
        "workspace": workspace,
        "registry": registry_path,
        "artifacts": artifact_directory,
        "manifest": manifest_path,
        "dataset": small_dataset,
        "freeze": result,
    }


def test_generator_reproducibility_and_scene_label_consistency():
    first = generate_synthetic_scene(
        SMALL_GENERATOR_CONFIG, split="validation", ordinal=37
    )
    second = generate_synthetic_scene(
        SMALL_GENERATOR_CONFIG, split="validation", ordinal=37
    )
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] == second[2]
    truth = first[1]
    assert tuple(truth.labels) == SCENE_CLASS_LABELS[truth.scene_class]
    assert hashlib.sha256(first[0]).hexdigest() == truth.byte_sha256
    assert set(first[2].model_dump()) == {
        "image_id",
        "image_path",
        "labels",
        "split",
        "byte_sha256",
    }


def test_dataset_split_leakage_hashes_and_hard_negatives(small_dataset):
    report = small_dataset.report
    assert report.valid is True
    assert report.image_count == 480
    assert report.leakage_checks["status"] == "PASS"
    assert report.leakage_checks["byte_hash_cross_split"] == 0
    assert report.leakage_checks["direct_template_cross_split"] == 0
    assert all(report.holdout_checks.values())
    assert set(report.label_counts) == set(IMAGE_LABELS)
    assert set(report.hard_negative_counts) == set(HARD_NEGATIVE_SCENES)
    assert report.image_integrity["unique_byte_hashes"] == 480


def test_preprocessing_and_local_augmentation_are_deterministic(small_dataset):
    record = SyntheticImageModelRecord.model_validate_json(
        small_dataset.model_input_paths["train"].read_text(encoding="utf-8").splitlines()[0]
    )
    payload = (small_dataset.output_directory / record.image_path).read_bytes()
    value = ImageInput(
        image_id=record.image_id,
        image_bytes=payload,
        mime_type="image/png",
        file_size=len(payload),
        width=64,
        height=64,
        checksum=record.byte_sha256,
    )
    processed = preprocess_image(value)
    assert processed.pixel_values.shape == (3, 224, 224)
    with Image.open(small_dataset.output_directory / record.image_path) as image:
        first = apply_local_augmentation(
            image, image_id=record.image_id, epoch=3, config=ImageTrainingConfig()
        )
    with Image.open(small_dataset.output_directory / record.image_path) as image:
        second = apply_local_augmentation(
            image, image_id=record.image_id, epoch=3, config=ImageTrainingConfig()
        )
    assert first.dtype == np.float32
    assert np.array_equal(first, second)


def test_successor_is_scratch_initialized_and_has_no_loaded_weights():
    config = ScratchCNNConfig(number_of_classes=5, random_seed=220022)
    first = build_scratch_cnn_v2(config)
    second = build_scratch_cnn_v2(config)
    assert first.architecture_version == "scratch-cnn-v2-dual-pool"
    assert all(
        torch.equal(first.state_dict()[name], second.state_dict()[name])
        for name in first.state_dict()
    )
    assert first(torch.zeros((2, 3, 64, 64))).shape == (2, 5)


def test_frozen_model_save_load_artifact_governance_and_inference(frozen_workflow):
    root = frozen_workflow["artifacts"]
    development = load_image_development_manifest(
        root / "image_model_v1.development_manifest.json"
    )
    provenance = ImageArtifactProvenance.model_validate_json(
        (root / "image_model_v1.provenance.json").read_text(encoding="utf-8")
    )
    from app.ml.contracts import ArtifactManifest

    manifest = ArtifactManifest.model_validate_json(
        frozen_workflow["manifest"].read_text(encoding="utf-8")
    )
    artifact = authorize_image_artifact(
        root / "image_model_v1.pt",
        provenance,
        manifest,
        config=ProjectTrainedImageAnalyzer(
            artifact_path=root / "image_model_v1.pt",
            provenance_path=root / "image_model_v1.provenance.json",
            development_manifest_path=root / "image_model_v1.development_manifest.json",
            artifact_manifest_path=frozen_workflow["manifest"],
        ).config,
    )
    state = load_image_state_dict(
        artifact,
        provenance,
        manifest,
        config=ProjectTrainedImageAnalyzer(
            artifact_path=artifact,
            provenance_path=root / "image_model_v1.provenance.json",
            development_manifest_path=root / "image_model_v1.development_manifest.json",
            artifact_manifest_path=frozen_workflow["manifest"],
        ).config,
    )
    assert state
    assert development.initialization == "SCRATCH_INITIALIZED"
    assert provenance.pretrained_weights_used is False
    analyzer = ProjectTrainedImageAnalyzer(
        artifact_path=artifact,
        provenance_path=root / "image_model_v1.provenance.json",
        development_manifest_path=root / "image_model_v1.development_manifest.json",
        artifact_manifest_path=frozen_workflow["manifest"],
    )
    record = SyntheticImageModelRecord.model_validate_json(
        frozen_workflow["dataset"].model_input_paths["validation"]
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    payload = (
        frozen_workflow["dataset"].output_directory / record.image_path
    ).read_bytes()
    image = ImageInput(
        image_id=record.image_id,
        image_bytes=payload,
        mime_type="image/png",
        file_size=len(payload),
        width=64,
        height=64,
        checksum=record.byte_sha256,
    )
    first = analyzer.predict(image)
    second = analyzer.predict(image)
    assert first == second
    assert first.status is PredictionStatus.AVAILABLE
    assert set(first.probabilities) == set(IMAGE_LABELS)


def test_golden_integration_and_one_shot_enforcement(frozen_workflow):
    golden = json.loads(
        (frozen_workflow["artifacts"] / "image_model_v1.golden.json").read_text(
            encoding="utf-8"
        )
    )
    assert golden["checks"] and all(golden["checks"].values())
    receipt = finalize_image_evaluation(
        registry_path=frozen_workflow["registry"],
        dataset_root=frozen_workflow["dataset"].output_directory,
        output_directory=frozen_workflow["artifacts"],
        artifact_manifest_path=frozen_workflow["manifest"],
    )
    assert receipt["status"] == "FINAL_EVALUATION_COMPLETE"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["test_used_for_model_selection"] is False
    assert receipt["production_validation"] == "NOT_VALIDATED"
    with pytest.raises(RuntimeError, match="reevaluation is prohibited"):
        finalize_image_evaluation(
            registry_path=frozen_workflow["registry"],
            dataset_root=frozen_workflow["dataset"].output_directory,
            output_directory=frozen_workflow["artifacts"],
            artifact_manifest_path=frozen_workflow["manifest"],
        )


def test_generator_operates_with_network_disabled(monkeypatch):
    def prohibited_socket(*_args, **_kwargs):
        raise AssertionError("network access is prohibited")

    monkeypatch.setattr(socket, "socket", prohibited_socket)
    payload, truth, _, _ = generate_synthetic_scene(
        SMALL_GENERATOR_CONFIG, split="test", ordinal=11
    )
    assert payload and truth.split == "test"


def test_phase22_sources_have_no_network_pretrained_or_external_model_calls():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "data" / "synthetic_image" / "generator.py",
        root / "training" / "image_synthetic_validation.py",
        root / "models" / "custom_cnn.py",
        root.parents[2] / "scripts" / "generate_synthetic_image_dataset.py",
        root.parents[2] / "scripts" / "validate_image_model.py",
    )
    prohibited_roots = {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "transformers",
        "torchvision",
        "tensorflow",
        "openai",
        "anthropic",
    }
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in modules:
                if module.split(".")[0] in prohibited_roots:
                    violations.append(f"{path.name}: {module}")
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in {"from_pretrained", "load_state_dict_from_url", "hub.load"}:
                    violations.append(f"{path.name}: {name}")
    assert violations == []
