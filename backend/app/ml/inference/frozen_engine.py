"""Opt-in, locally authorized Phase 18–23 inference composition.

These artifacts contain synthetic-development evidence, not production
validation. Their outputs are advisory and must never decide human review.
No platform I/O or remote resource is accessed by this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ml.components.anomaly_detection import AnomalyDetector
from app.ml.components.event_detection import EventDetector, observation_from_report
from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact
from app.ml.config import NLPClassifierConfig
from app.ml.contracts import (
    AnomalyDomain,
    AnomalyPrediction,
    AnomalyScope,
    AnomalyType,
    CalibrationStatus,
    CredibilityPrediction,
    CredibilityRiskInput,
    CredibilityRiskLevel,
    DuplicatePrediction,
    EventDetectionResult,
    EventDetectionStatus,
    EventPrediction,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    TextPrediction,
)
from app.ml.inference.engine import InferenceEngine
from app.ml.models.anomaly_window_model import (
    extract_window_feature_vector,
    score_feature_matrix,
)
from app.ml.training.anomaly_synthetic_validation import load_frozen_anomaly_artifact
from app.ml.training.credibility_validation import (
    load_credibility_development_artifact,
    predict_credibility_development,
)
from app.ml.training.duplicate_validation import load_duplicate_development_artifact
from app.ml.training.event_validation import load_event_development_artifact
from app.ml.training.image_synthetic_validation import ProjectTrainedImageAnalyzer
from app.ml.data.synthetic_credibility.generator import SyntheticCredibilityDetectorInput


ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts"


class _UnavailablePredictor:
    def __init__(self, component: str, prediction_type: type, error: Exception) -> None:
        self.component = component
        self.prediction_type = prediction_type
        self.error_type = type(error).__name__

    def predict(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.prediction_type(
            status=PredictionStatus.ERROR,
            reason_codes=["FROZEN_ARTIFACT_UNAVAILABLE"],
            warnings=[f"{self.component} could not load: {self.error_type}"],
        )


def _authorize(component: str, prediction_type: type, loader: Any) -> Any:
    try:
        return loader()
    except Exception as error:
        return _UnavailablePredictor(component, prediction_type, error)


class _FrozenDuplicatePredictor:
    def __init__(self) -> None:
        self.artifact, self.matcher = load_duplicate_development_artifact()

    def predict(self, report: ReportInput) -> DuplicatePrediction:
        if not report.candidate_reports:
            return DuplicatePrediction(
                status=PredictionStatus.NOT_RUN,
                model_version=self.artifact.artifact_version,
                feature_version=self.artifact.feature_version,
                preprocessing_version=self.artifact.preprocessing_version,
                reason_codes=["MISSING_INPUT", "NO_CANDIDATE_REPORTS"],
            )
        prediction = self.matcher.predict(report)
        return prediction.model_copy(
            update={"model_version": self.artifact.artifact_version}
        )


class _FrozenEventPredictor:
    def __init__(self) -> None:
        self.artifact, config = load_event_development_artifact()
        self.detector = EventDetector(config=config)

    def predict(self, report: ReportInput, **kwargs: Any) -> EventPrediction:
        prediction = self.detector.predict(report, **kwargs)
        return prediction.model_copy(
            update={"model_version": self.artifact.artifact_version}
        )

    def detect(self, observations: list[Any]) -> EventDetectionResult:
        return self.detector.detect(observations)


class _FrozenCredibilityPredictor:
    def __init__(self) -> None:
        self.artifact = load_credibility_development_artifact()

    def predict(self, value: CredibilityRiskInput) -> CredibilityPrediction:
        duplicate = value.duplicate_prediction
        if duplicate is not None and duplicate.status is PredictionStatus.ERROR:
            return CredibilityPrediction(
                status=PredictionStatus.NOT_RUN,
                model_version=self.artifact.artifact_version,
                feature_version=self.artifact.feature_version,
                preprocessing_version=self.artifact.preprocessing_version,
                reason_codes=["UPSTREAM_DUPLICATE_ERROR"],
                warnings=["Missing duplicate inference was not treated as a negative."],
            )
        report = value.report
        detector_input = SyntheticCredibilityDetectorInput(
            report_id=report.report_id,
            report_text=report.text,
            occurred_at=report.occurred_at,
            latitude=report.latitude,
            longitude=report.longitude,
            source_type=report.source_type,
            source_metadata=report.source_metadata,
            duplicate_prediction=(
                duplicate if duplicate is not None and duplicate.status is PredictionStatus.AVAILABLE
                else None
            ),
        )
        prediction = predict_credibility_development(detector_input, self.artifact)
        level = {
            "AUTHENTIC": CredibilityRiskLevel.LOW,
            "MISLEADING": CredibilityRiskLevel.HIGH,
            "UNCERTAIN": CredibilityRiskLevel.UNCERTAIN,
        }[prediction.label]
        return CredibilityPrediction(
            status=PredictionStatus.AVAILABLE,
            model_version=prediction.artifact_version,
            feature_version=prediction.feature_version,
            preprocessing_version=self.artifact.preprocessing_version,
            score=prediction.misleading_risk_probability,
            risk_score=prediction.misleading_risk_probability,
            risk_level=level,
            label=prediction.label,
            calibration_status=CalibrationStatus.CALIBRATED,
            evidence=[
                f"{item['feature']}={item['contribution']}"
                for item in prediction.top_feature_contributions
            ],
            reason_codes=["SYNTHETIC_DEVELOPMENT_ONLY"],
            warnings=[
                *prediction.warnings,
                "Duplicate evidence is not proof that a report is false.",
                "This advisory output must not automatically quarantine a report.",
            ],
        )


class _FrozenImagePredictor:
    def __init__(self) -> None:
        self.analyzer = ProjectTrainedImageAnalyzer()
        self.model_version = self.analyzer.development.model_version

    def predict(self, report: ReportInput) -> ImagePrediction:
        if report.image_bytes is None:
            return ImagePrediction(
                status=PredictionStatus.NOT_RUN,
                model_version=self.model_version,
                feature_version=self.analyzer.development.feature_version,
                preprocessing_version=self.analyzer.development.preprocessing_version,
                task_type="MULTI_LABEL",
                reason_codes=["MISSING_INPUT", "IMAGE_NOT_SUPPLIED"],
            )
        return self.analyzer.predict(report)


@dataclass(frozen=True)
class _DetectorVisibleWindow:
    timestamps: list[datetime]
    rainfall_mm: list[float | None]
    river_level_m: list[float | None]


class _FrozenAnomalyPredictor:
    def __init__(self) -> None:
        self.artifact = load_frozen_anomaly_artifact()
        self.statistical = AnomalyDetector()

    def predict(self, report: ReportInput) -> AnomalyPrediction:
        observations = report.station_observations
        base = {
            "model_version": self.artifact.artifact_version,
            "feature_version": self.artifact.feature_version,
            "preprocessing_version": self.artifact.preprocessing_version,
        }
        if not observations:
            return AnomalyPrediction(
                status=PredictionStatus.NOT_RUN,
                reason_codes=["MISSING_INPUT", "STATION_HISTORY_NOT_SUPPLIED"],
                **base,
            )
        station_ids = {item.station_id for item in observations}
        if len(station_ids) != 1:
            return AnomalyPrediction(
                status=PredictionStatus.ERROR,
                reason_codes=["MIXED_STATION_HISTORY"],
                **base,
            )
        causal = sorted(
            (item for item in observations if item.observed_at <= report.occurred_at),
            key=lambda item: item.observed_at,
        )
        if len(causal) < 24:
            return AnomalyPrediction(
                status=PredictionStatus.NOT_RUN,
                station_id=next(iter(station_ids)),
                reason_codes=["MISSING_INPUT", "INSUFFICIENT_HISTORY"],
                warnings=["The frozen model requires 24 prior station observations."],
                **base,
            )
        window = causal[-24:]
        timestamps = [item.observed_at for item in window]
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            return AnomalyPrediction(
                status=PredictionStatus.ERROR,
                station_id=next(iter(station_ids)),
                reason_codes=["INVALID_STATION_TIMESTAMPS"],
                **base,
            )
        visible = _DetectorVisibleWindow(
            timestamps=timestamps,
            rainfall_mm=[item.measurements.get("rainfall_mm") for item in window],
            river_level_m=[item.measurements.get("river_level_m") for item in window],
        )
        vector = extract_window_feature_vector(visible)  # type: ignore[arg-type]
        scores = score_feature_matrix(self.artifact, vector.reshape(1, -1))
        probabilities = {name: float(values[0]) for name, values in scores.items()}
        if not all(math.isfinite(value) for value in probabilities.values()):
            raise ValueError("anomaly model produced a non-finite score")
        highest = max(probabilities, key=probabilities.get)
        positive = [
            name for name, score in probabilities.items()
            if score >= self.artifact.thresholds[name]
        ]
        selected = max(positive, key=probabilities.get) if positive else None
        baseline = self.statistical.predict(
            report.model_copy(update={"station_observations": window})
        )
        return AnomalyPrediction(
            status=PredictionStatus.AVAILABLE,
            station_id=next(iter(station_ids)),
            observation_ids=[window[-1].station_id + ":" + window[-1].observed_at.isoformat()],
            is_anomaly=bool(positive),
            anomaly_type=AnomalyType.UNCERTAIN if positive else None,
            anomaly_scope=AnomalyScope.WINDOW_ANOMALY if positive else None,
            anomaly_domain=AnomalyDomain(selected) if selected else None,
            score=probabilities[highest],
            score_type="SYNTHETIC_DEVELOPMENT_MODEL_SCORE",
            threshold=self.artifact.thresholds[highest],
            baseline_id=baseline.baseline_id,
            baseline_version=baseline.baseline_version,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            evidence=[
                *(f"{name}={score:.12f}" for name, score in sorted(probabilities.items())),
                f"STATISTICAL_BASELINE_STATUS={baseline.status.value}",
                f"STATISTICAL_BASELINE_SCORE={baseline.score}"
                if baseline.score is not None else "STATISTICAL_BASELINE_SCORE=UNAVAILABLE",
            ],
            reason_codes=["SYNTHETIC_DEVELOPMENT_ONLY"],
            warnings=[
                "Synthetic-development scores are not field probabilities.",
                "Anomaly evidence is not evidence that a report is fake.",
            ],
            **base,
        )


def build_frozen_inference_engine() -> InferenceEngine:
    """Authorize each committed artifact independently; failures stay typed."""

    def nlp() -> NLPClassifier:
        path = ARTIFACT_ROOT / "nlp_classifier_v3.json"
        artifact = load_nlp_artifact(path)
        config = NLPClassifierConfig(
            model_version=artifact.model_version,
            feature_version=artifact.feature_version,
            preprocessing_version=artifact.preprocessing_version,
            artifact_path=path,
            char_ngram_range=tuple(artifact.char_space.ngram_range),
            word_ngram_range=tuple(artifact.word_space.ngram_range),
            random_state=artifact.classifier.random_state,
        )
        return NLPClassifier(config=config)

    return InferenceEngine(
        nlp_classifier=_authorize("nlp_classifier", TextPrediction, nlp),
        duplicate_matcher=_authorize("duplicate_matcher", DuplicatePrediction, _FrozenDuplicatePredictor),
        event_detector=_authorize("event_detector", EventPrediction, _FrozenEventPredictor),
        fake_detector=_authorize("fake_detector", CredibilityPrediction, _FrozenCredibilityPredictor),
        image_analyzer=_authorize("image_analyzer", ImagePrediction, _FrozenImagePredictor),
        anomaly_detector=_authorize("anomaly_detector", AnomalyPrediction, _FrozenAnomalyPredictor),
    )


@lru_cache(maxsize=1)
def get_frozen_inference_engine() -> InferenceEngine:
    return build_frozen_inference_engine()


def group_report_candidates(
    reports: list[ReportInput], *, engine: InferenceEngine | None = None
) -> EventDetectionResult:
    """Group caller-loaded reports without allowing errors to imply no event."""

    selected = engine or get_frozen_inference_engine()
    if not reports:
        return EventDetectionResult(
            status=EventDetectionStatus.DATA_UNAVAILABLE,
            warnings=["No already-loaded reports were supplied."],
        )
    observations = []
    for report in reports:
        result = selected.analyze(report)
        if result.text_prediction.status is PredictionStatus.ERROR or result.duplicate_prediction.status is PredictionStatus.ERROR:
            return EventDetectionResult(
                status=EventDetectionStatus.ERROR,
                warnings=["Upstream component error; no negative event decision was inferred."],
            )
        observations.append(
            observation_from_report(
                report,
                text_prediction=result.text_prediction,
                duplicate_prediction=result.duplicate_prediction,
            )
        )
    try:
        return selected.event_detector.detect(observations)
    except Exception as error:
        return EventDetectionResult(
            status=EventDetectionStatus.ERROR,
            warnings=[f"event_detector raised {type(error).__name__}"],
        )


__all__ = ["build_frozen_inference_engine", "get_frozen_inference_engine", "group_report_candidates"]
