"""Local image-analysis interface with deliberately unavailable inference.

Phase 8 validates and preprocesses caller-loaded bytes, but it does not have a
validated image dataset or a trained image model. A successful validation is
therefore not a prediction: it returns ``OFFLINE`` with empty labels and
probabilities.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.ml.components.image_processing import validate_image_input
from app.ml.config import DEFAULT_IMAGE_ANALYSIS_CONFIG, ImageAnalysisConfig
from app.ml.contracts import (
    CalibrationStatus,
    ImageInput,
    ImagePrediction,
    ImageTrainingResult,
    PredictionStatus,
    ReportInput,
)


def _optional_int(metadata: Mapping[str, Any], name: str) -> int | None:
    value = metadata.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def image_input_from_report(report: ReportInput) -> ImageInput | None:
    """Adapt the legacy report contract without performing any I/O.

    Image metadata remains caller supplied. Missing MIME metadata is retained
    as an unsupported value so validation fails explicitly instead of guessing
    from a filename or contacting a media source.
    """

    if report.image_bytes is None:
        return None
    metadata = report.source_metadata
    capture_timestamp = metadata.get("image_capture_timestamp")
    if not isinstance(capture_timestamp, datetime):
        capture_timestamp = None
    checksum = metadata.get("image_checksum")
    if not isinstance(checksum, str):
        checksum = None
    image_id = metadata.get("image_id")
    if not isinstance(image_id, str) or not image_id.strip():
        image_id = f"{report.report_id}:image"
    mime_type = metadata.get("image_mime_type", metadata.get("mime_type"))
    if not isinstance(mime_type, str) or not mime_type.strip():
        mime_type = "application/octet-stream"
    return ImageInput(
        image_id=image_id,
        report_id=report.report_id,
        image_bytes=report.image_bytes,
        mime_type=mime_type,
        file_size=len(report.image_bytes),
        width=_optional_int(metadata, "image_width"),
        height=_optional_int(metadata, "image_height"),
        checksum=checksum,
        capture_timestamp=capture_timestamp,
        source_metadata=dict(metadata),
    )


class ImageAnalyzer:
    """Validate local input and expose future fit/evaluate interfaces."""

    component_name = "image_analyzer"

    def __init__(self, config: ImageAnalysisConfig | None = None) -> None:
        self.config = config or DEFAULT_IMAGE_ANALYSIS_CONFIG

    def predict(self, value: ImageInput | ReportInput) -> ImagePrediction:
        image = image_input_from_report(value) if isinstance(value, ReportInput) else value
        if image is None:
            return ImagePrediction(
                status=PredictionStatus.NOT_APPLICABLE,
                task_type="MULTI_LABEL",
                feature_version=self.config.feature_version,
                preprocessing_version=self.config.preprocessing_version,
                calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                reason_codes=["IMAGE_NOT_SUPPLIED"],
                warnings=["No already-loaded image bytes were supplied."],
            )

        validation = validate_image_input(image, config=self.config)
        if not validation.valid:
            return ImagePrediction(
                status=PredictionStatus.ERROR,
                image_id=image.image_id,
                task_type="MULTI_LABEL",
                feature_version=self.config.feature_version,
                preprocessing_version=self.config.preprocessing_version,
                calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
                evidence=[
                    f"BYTE_HASH:{validation.byte_sha256}"
                    if validation.byte_sha256
                    else "BYTE_HASH:UNAVAILABLE"
                ],
                reason_codes=[item.code for item in validation.errors],
                warnings=[item.message for item in validation.warnings],
            )

        return ImagePrediction(
            status=PredictionStatus.OFFLINE,
            image_id=image.image_id,
            task_type="MULTI_LABEL",
            feature_version=self.config.feature_version,
            preprocessing_version=self.config.preprocessing_version,
            labels=[],
            probabilities={},
            confidence=None,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            evidence=[
                f"BYTE_HASH:{validation.byte_sha256}",
                f"DETECTED_FORMAT:{validation.detected_format}",
                f"DETECTED_DIMENSIONS:{validation.detected_width}x{validation.detected_height}",
            ],
            reason_codes=["TRAINING_UNAVAILABLE"],
            warnings=[
                "No validated image dataset or project-trained image model is available; no prediction was fabricated.",
                *[item.message for item in validation.warnings],
            ],
        )

    def fit(
        self,
        training_data: Sequence[Any] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> ImageTrainingResult:
        del training_data, config
        return ImageTrainingResult(
            status="TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA",
            artifact_created=False,
            reason_codes=["NO_VALIDATED_IMAGE_DATASET"],
            required_provenance=[
                "dataset_hash",
                "dataset_version",
                "annotation_schema_version",
                "preprocessing_version",
                "architecture_version",
                "random_seed",
                "optimizer",
                "learning_rate",
                "epochs",
                "batch_size",
                "framework_version",
                "class_distribution",
                "training_timestamp",
                "artifact_sha256",
                "policy_status",
            ],
            warnings=[
                "Training is blocked until approved project-controlled images have validated multi-label annotations and grouped splits."
            ],
        )

    def evaluate(self, labels=None, predictions=None, **kwargs):
        from app.ml.evaluation.evaluate import evaluate_image_predictions

        supplied_labels = [] if labels is None else labels
        supplied_predictions = [] if predictions is None else predictions
        return evaluate_image_predictions(
            supplied_labels,
            supplied_predictions,
            **kwargs,
        )


__all__ = ["ImageAnalyzer", "image_input_from_report"]
