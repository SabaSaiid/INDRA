from __future__ import annotations

import ast
import hashlib
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import torch
from PIL import Image
from pydantic import ValidationError

from app.ml.components.image_analysis import ImageAnalyzer
from app.ml.components.image_processing import (
    byte_sha256,
    perceptual_similarity_hash,
    preprocess_image,
    validate_image_input,
)
from app.ml.config import ImageAnalysisConfig
from app.ml.contracts import (
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    ImageInput,
    PredictionStatus,
)
from app.ml.data.image_annotations import (
    ImageAnnotation,
    ImageAnnotationStore,
    ImageVisualLabel,
    adjudicate_image_case,
    build_image_adjudication_case,
    grouped_image_split,
    validate_image_annotations,
    validate_image_leakage,
)
from app.ml.evaluation.evaluate import evaluate_image_predictions
from app.ml.image_artifacts import (
    ImageArtifactProvenance,
    ImageTrainingProvenance,
    authorize_image_artifact,
)
from app.ml.models.custom_cnn import ScratchCNNConfig, build_scratch_cnn
from app.ml.training.train_image_analyzer import train_image_analyzer

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase8-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _encoded_image(
    image_format: str = "PNG",
    *,
    mode: str = "RGB",
    size: tuple[int, int] = (12, 8),
    color=None,
) -> bytes:
    if color is None:
        color = (20, 80, 140, 180) if mode == "RGBA" else 90 if mode == "L" else (20, 80, 140)
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _input(
    payload: bytes | None = None,
    *,
    image_id: str = "image-1",
    mime_type: str = "image/png",
    width: int | None = 12,
    height: int | None = 8,
) -> ImageInput:
    payload = _encoded_image() if payload is None else payload
    return ImageInput(
        image_id=image_id,
        image_bytes=payload,
        mime_type=mime_type,
        file_size=len(payload),
        width=width,
        height=height,
        checksum=byte_sha256(payload) if payload else None,
        capture_timestamp=NOW,
        source_metadata={"fixture": "UNIT_TEST_ONLY"},
    )


def _annotation(
    image_id: str,
    annotator: str,
    *,
    labels: list[ImageVisualLabel] | None = None,
    digest: str | None = None,
    perceptual_hash: str | None = None,
    event_id: str | None = None,
    split: str | None = None,
) -> ImageAnnotation:
    selected = labels or [ImageVisualLabel.FLOODED_SCENE]
    return ImageAnnotation(
        annotation_id=f"annotation-{image_id}-{annotator}-{split or 'none'}",
        image_id=image_id,
        labels=selected,
        annotator_id=annotator,
        annotation_timestamp=NOW,
        annotator_confidence=0.8,
        reason="Visible water covers a normally traversable area.",
        uncertain=selected == [ImageVisualLabel.UNCERTAIN],
        byte_sha256=digest or hashlib.sha256(image_id.encode()).hexdigest(),
        perceptual_similarity_hash=perceptual_hash,
        width=12,
        height=8,
        detected_format="PNG",
        event_id=event_id,
        split=split,
    )


def test_valid_png_and_jpeg_are_verified_from_content():
    png = validate_image_input(_input())
    jpeg_bytes = _encoded_image("JPEG")
    jpeg = validate_image_input(
        _input(jpeg_bytes, mime_type="image/jpeg")
    )
    assert png.valid and png.detected_format == "PNG"
    assert jpeg.valid and jpeg.detected_format == "JPEG"
    assert png.detected_mime_type == "image/png"
    assert jpeg.detected_mime_type == "image/jpeg"


def test_invalid_corrupt_and_zero_byte_images_return_structured_errors():
    invalid = validate_image_input(_input(b"not an image", width=None, height=None))
    truncated = _encoded_image("PNG")[:-15]
    corrupt = validate_image_input(_input(truncated, width=None, height=None))
    empty = validate_image_input(_input(b"", width=None, height=None))
    assert "MALFORMED_IMAGE_HEADER" in {item.code for item in invalid.errors}
    assert "CORRUPTED_IMAGE" in {item.code for item in corrupt.errors}
    assert "ZERO_BYTE_IMAGE" in {item.code for item in empty.errors}
    assert not invalid.valid and not corrupt.valid and not empty.valid


def test_file_size_dimension_mime_and_color_limits_are_enforced():
    payload = _encoded_image(size=(12, 8))
    size_limited = validate_image_input(
        _input(payload),
        config=ImageAnalysisConfig(max_file_size_bytes=len(payload) - 1),
    )
    dimension_limited = validate_image_input(
        _input(payload),
        config=ImageAnalysisConfig(max_width=10),
    )
    mime_mismatch = validate_image_input(_input(payload, mime_type="image/jpeg"))
    cmyk = _encoded_image("JPEG", mode="CMYK", color=(0, 100, 100, 0))
    unsupported_color = validate_image_input(
        _input(cmyk, mime_type="image/jpeg")
    )
    assert "FILE_SIZE_EXCEEDED" in {item.code for item in size_limited.errors}
    assert "DIMENSION_LIMIT_EXCEEDED" in {
        item.code for item in dimension_limited.errors
    }
    assert "MIME_CONTENT_MISMATCH" in {item.code for item in mime_mismatch.errors}
    assert "UNSUPPORTED_COLOR_MODE" in {
        item.code for item in unsupported_color.errors
    }


def test_hashes_and_preprocessing_are_deterministic_with_explicit_channels():
    payload = _encoded_image(mode="RGBA")
    value = _input(payload)
    assert byte_sha256(payload) == byte_sha256(payload)
    assert perceptual_similarity_hash(payload) == perceptual_similarity_hash(payload)
    first = preprocess_image(value)
    second = preprocess_image(value)
    assert np.array_equal(first.pixel_values, second.pixel_values)
    assert first.pixel_values.shape == (3, 224, 224)
    assert first.pixel_values.dtype == np.float32
    assert 0.0 <= float(first.pixel_values.min()) <= float(first.pixel_values.max()) <= 1.0
    assert first.source_file_size_bytes == len(payload)
    assert first.preprocessing_seconds >= 0.0
    grayscale = preprocess_image(_input(_encoded_image(mode="L")))
    assert grayscale.pixel_values.shape[0] == 3
    assert np.array_equal(grayscale.pixel_values[0], grayscale.pixel_values[1])


def test_annotation_schema_supports_multilabel_and_rejects_invalid_states():
    annotation = _annotation(
        "image-1",
        "annotator-1",
        labels=[ImageVisualLabel.FLOODED_SCENE, ImageVisualLabel.STANDING_WATER],
    )
    assert len(annotation.labels) == 2
    with pytest.raises(ValidationError, match="UNCERTAIN"):
        _annotation(
            "image-2",
            "annotator-1",
            labels=[ImageVisualLabel.UNCERTAIN, ImageVisualLabel.STANDING_WATER],
        )
    with pytest.raises(ValidationError, match="NORMAL_SCENE"):
        _annotation(
            "image-3",
            "annotator-1",
            labels=[ImageVisualLabel.NORMAL_SCENE, ImageVisualLabel.STORM_DAMAGE],
        )


def test_annotation_store_is_append_only_and_supports_multiple_annotators(local_tmp_path):
    store = ImageAnnotationStore(local_tmp_path / "image-annotations.jsonl")
    first = _annotation("image-1", "annotator-1")
    second = _annotation("image-1", "annotator-2")
    store.append(first)
    store.append(second)
    assert [item.annotation_id for item in store.load()] == [
        first.annotation_id,
        second.annotation_id,
    ]
    with pytest.raises(ValueError, match="same annotator"):
        store.append(
            _annotation("image-1", "annotator-1").model_copy(
                update={"annotation_id": "annotation-image-1-annotator-1-repeat"}
            )
        )


def test_disagreement_remains_uncertain_until_append_only_adjudication():
    first = _annotation("image-1", "annotator-1")
    second = _annotation(
        "image-1", "annotator-2", labels=[ImageVisualLabel.STANDING_WATER]
    )
    case = build_image_adjudication_case([first, second])
    assert case.disagreement
    assert case.effective_labels == [ImageVisualLabel.UNCERTAIN]
    resolved = adjudicate_image_case(
        case,
        labels=[ImageVisualLabel.FLOODED_SCENE, ImageVisualLabel.STANDING_WATER],
        adjudicator_id="adjudicator-1",
        reason="Both criteria are visible after joint review.",
        timestamp=NOW,
    )
    assert set(resolved.effective_labels) == {
        ImageVisualLabel.FLOODED_SCENE,
        ImageVisualLabel.STANDING_WATER,
    }
    assert len(resolved.annotations) == 2


def test_quality_control_detects_duplicate_hashes_and_only_measures_repeats():
    shared_hash = "a" * 64
    annotations = [
        _annotation("image-1", "annotator-1", digest=shared_hash),
        _annotation("image-1", "annotator-2", digest=shared_hash),
        _annotation("image-2", "annotator-3", digest=shared_hash),
    ]
    quality = validate_image_annotations(annotations)
    assert quality.valid
    assert quality.duplicate_byte_hashes == {
        shared_hash: ["image-1", "image-2"]
    }
    assert quality.agreement_status == "DATA_AVAILABLE"
    assert quality.exact_set_agreement_rate == 1.0
    single = validate_image_annotations([annotations[0]])
    assert single.agreement_status == "DATA_UNAVAILABLE"
    assert single.exact_set_agreement_rate is None


def test_grouped_split_refuses_missing_metadata_and_keeps_groups_together():
    unavailable = grouped_image_split([_annotation("image-1", "annotator-1")])
    assert unavailable.status == "GROUPED_SPLIT_UNAVAILABLE"
    records = [
        _annotation("image-1", "a", event_id="event-1", perceptual_hash="0" * 16),
        _annotation("image-2", "a", event_id="event-1", perceptual_hash="0" * 16),
        _annotation("image-3", "a", event_id="event-2", perceptual_hash="f" * 16),
        _annotation("image-4", "a", event_id="event-3", perceptual_hash="a" * 16),
    ]
    grouped = grouped_image_split(records, perceptual_hamming_threshold=1)
    assert grouped.status == "GROUPED_SPLIT_AVAILABLE"
    assigned = {
        item.image_id: split_name
        for split_name, items in (
            ("train", grouped.train),
            ("validation", grouped.validation),
            ("test", grouped.test),
        )
        for item in items
    }
    assert assigned["image-1"] == assigned["image-2"]


def test_exact_and_perceptual_cross_split_leakage_are_reported():
    shared_hash = "b" * 64
    train = _annotation(
        "image-1",
        "a",
        digest=shared_hash,
        perceptual_hash="0" * 16,
        event_id="event-1",
        split="train",
    )
    test = _annotation(
        "image-2",
        "b",
        digest=shared_hash,
        perceptual_hash=("0" * 15) + "1",
        event_id="event-1",
        split="test",
    )
    report = validate_image_leakage([train, test], perceptual_hamming_threshold=1)
    assert not report.valid
    assert report.byte_hashes_across_splits == [shared_hash]
    assert report.near_duplicate_image_pairs == ["image-1::image-2"]
    assert report.event_ids_across_splits == ["event-1"]


def test_training_is_blocked_and_prediction_never_fabricates_probabilities():
    result = train_image_analyzer()
    assert result.status == "TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA"
    assert result.artifact_created is False
    prediction = ImageAnalyzer().predict(_input())
    assert prediction.status is PredictionStatus.OFFLINE
    assert prediction.reason_codes == ["TRAINING_UNAVAILABLE"]
    assert prediction.labels == []
    assert prediction.probabilities == {}
    assert prediction.confidence is None
    invalid = ImageAnalyzer().predict(_input(b"bad", width=None, height=None))
    assert invalid.status is PredictionStatus.ERROR


def test_scratch_cnn_has_deterministic_random_initialization_and_shape():
    config = ScratchCNNConfig(number_of_classes=5, random_seed=7)
    first = build_scratch_cnn(config)
    second = build_scratch_cnn(config)
    assert all(
        torch.equal(first.state_dict()[name], second.state_dict()[name])
        for name in first.state_dict()
    )
    first.eval()
    output = first(torch.zeros((2, 3, 64, 64)))
    assert output.shape == (2, 5)
    assert first.config.multi_label is True


def test_image_evaluation_excludes_uncertain_and_reports_multilabel_metrics():
    unavailable = evaluate_image_predictions([], [])
    assert unavailable.evaluation_status == "DATA_UNAVAILABLE"
    report = evaluate_image_predictions(
        [
            ["FLOODED_SCENE", "STANDING_WATER"],
            ["NORMAL_SCENE"],
            ["UNCERTAIN"],
        ],
        [["FLOODED_SCENE"], ["NORMAL_SCENE"], []],
        sample_ids=["one", "two", "ambiguous"],
    )
    assert report.evaluation_status == "DATA_AVAILABLE"
    assert report.sample_count == 2
    assert report.excluded_uncertain_samples == 1
    assert report.micro_f1 is not None
    assert set(report.multilabel_confusion_matrices) == set(report.classes)
    assert report.calibration_status == "CALIBRATION_UNAVAILABLE"
    assert report.error_analysis["ambiguous_or_uncertain_samples"] == ["ambiguous"]


def test_artifact_guard_accepts_only_known_project_trained_hashes(local_tmp_path):
    artifact = local_tmp_path / "image_v1.pt"
    artifact.write_bytes(b"UNIT_TEST_ONLY_STATE_DICT_PLACEHOLDER")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = ArtifactMetadata(
        artifact_name=artifact.name,
        artifact_version="image-v1",
        sha256=digest,
        training_dataset_hash="d" * 64,
        feature_version="image-validation-features-v1",
        preprocessing_version="image-preprocessing-v1",
        training_timestamp=NOW,
        random_seed=42,
        framework_versions={"torch": "test-version"},
        intended_component="image_analyzer",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    manifest = ArtifactManifest(
        manifest_version="1.0",
        schema_version="1.0",
        policy_status="SCAFFOLD_ONLY",
        runtime_downloads_allowed=False,
        artifacts=[metadata],
    )
    provenance = ImageArtifactProvenance(
        artifact_name=artifact.name,
        model_version="image-v1",
        architecture_version="scratch-cnn-v1",
        feature_version="image-validation-features-v1",
        dataset_hash="d" * 64,
        preprocessing_version="image-preprocessing-v1",
        training_config=ImageTrainingProvenance(
            dataset_version="images-v1",
            annotation_schema_version="image-annotations-v1",
            optimizer="Adam",
            learning_rate=0.001,
            epochs=10,
            batch_size=8,
            class_distribution={"FLOODED_SCENE": 10},
            training_timestamp=NOW,
        ),
        random_seed=42,
        framework_version="test-version",
        artifact_sha256=digest,
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    assert authorize_image_artifact(artifact, provenance, manifest) == artifact.resolve()
    with pytest.raises(ValueError, match="unknown image artifact"):
        authorize_image_artifact(
            artifact,
            provenance,
            manifest.model_copy(update={"artifacts": []}),
        )
    with pytest.raises(ValueError, match="provenance is required"):
        authorize_image_artifact(artifact, None, manifest)
    with pytest.raises(ValueError, match="remote image artifacts"):
        authorize_image_artifact(
            r"\\example.invalid\share\image.pt",
            provenance,
            manifest,
        )


def test_phase8_source_has_no_pretrained_external_api_or_network_imports():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "components" / "image_analysis.py",
        root / "components" / "image_processing.py",
        root / "data" / "image_annotations.py",
        root / "image_artifacts.py",
        root / "models" / "custom_cnn.py",
        root / "training" / "train_image_analyzer.py",
    ]
    prohibited_roots = {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "transformers",
        "torchvision",
        "openai",
        "anthropic",
    }
    violations: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                modules = []
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
                if name in {"from_pretrained", "load_state_dict_from_url"}:
                    violations.append(f"{path.name}: {name}")
    assert violations == []
