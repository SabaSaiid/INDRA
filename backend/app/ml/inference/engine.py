"""Pure local inference engine for the six ML component interfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.ml.components.anomaly_detection import AnomalyDetector
from app.ml.components.credibility_features import credibility_input_from_report
from app.ml.components.duplicate_matching import DuplicateMatcher
from app.ml.components.event_detection import EventDetector
from app.ml.components.fake_detection import FakeDetector
from app.ml.components.image_analysis import ImageAnalyzer
from app.ml.components.nlp_classifier import NLPClassifier
from app.ml.contracts import (
    AnomalyPrediction,
    CredibilityPrediction,
    DuplicatePrediction,
    EventPrediction,
    ImagePrediction,
    PredictionBase,
    PredictionStatus,
    ReportInput,
    TextPrediction,
    UnifiedMLResult,
)


PredictionT = TypeVar("PredictionT", bound=PredictionBase)


def _predict_or_error(
    name: str, prediction_type: type[PredictionT], call: Callable[[], PredictionT]
) -> PredictionT:
    """A broken component is an explicit error, never a negative prediction."""

    try:
        prediction = call()
        if not isinstance(prediction, prediction_type):
            raise TypeError("component returned the wrong prediction contract")
        return prediction
    except Exception as error:
        return prediction_type(
            status=PredictionStatus.ERROR,
            reason_codes=["COMPONENT_INFERENCE_ERROR"],
            warnings=[f"{name} raised {type(error).__name__}"],
        )


class InferenceEngine:
    """Compose components without owning platform I/O or model downloads."""

    def __init__(
        self,
        *,
        nlp_classifier: NLPClassifier | None = None,
        event_detector: EventDetector | None = None,
        fake_detector: FakeDetector | None = None,
        duplicate_matcher: DuplicateMatcher | None = None,
        image_analyzer: ImageAnalyzer | None = None,
        anomaly_detector: AnomalyDetector | None = None,
    ) -> None:
        self.nlp_classifier = nlp_classifier or NLPClassifier()
        self.event_detector = event_detector or EventDetector()
        self.fake_detector = fake_detector or FakeDetector()
        self.duplicate_matcher = duplicate_matcher or DuplicateMatcher()
        self.image_analyzer = image_analyzer or ImageAnalyzer()
        self.anomaly_detector = anomaly_detector or AnomalyDetector()

    def analyze(self, report: ReportInput) -> UnifiedMLResult:
        text_prediction = _predict_or_error(
            "nlp_classifier", TextPrediction,
            lambda: self.nlp_classifier.predict(report),
        )
        duplicate_prediction = _predict_or_error(
            "duplicate_matcher", DuplicatePrediction,
            lambda: self.duplicate_matcher.predict(report),
        )
        event_prediction = _predict_or_error(
            "event_detector", EventPrediction,
            lambda: self.event_detector.predict(
                report,
                text_prediction=text_prediction,
                duplicate_prediction=duplicate_prediction,
            ),
        )
        credibility_prediction = _predict_or_error(
            "fake_detector", CredibilityPrediction,
            lambda: self.fake_detector.predict(
                credibility_input_from_report(
                    report,
                    text_prediction=text_prediction,
                    duplicate_prediction=duplicate_prediction,
                    event_prediction=event_prediction,
                )
            ),
        )
        image_prediction = _predict_or_error(
            "image_analyzer", ImagePrediction,
            lambda: self.image_analyzer.predict(report),
        )
        anomaly_prediction = _predict_or_error(
            "anomaly_detector", AnomalyPrediction,
            lambda: self.anomaly_detector.predict(report),
        )
        component_predictions = [
            ("nlp_classifier", text_prediction),
            ("duplicate_matcher", duplicate_prediction),
            ("event_detector", event_prediction),
            ("fake_detector", credibility_prediction),
            ("image_analyzer", image_prediction),
            ("anomaly_detector", anomaly_prediction),
        ]
        predictions = [prediction for _, prediction in component_predictions]
        warnings = [warning for prediction in predictions for warning in prediction.warnings]
        errors = [
            f"{type(prediction).__name__}: {prediction.reason_codes}"
            for prediction in predictions
            if prediction.status is PredictionStatus.ERROR
        ]

        model_versions: dict[str, str] = {}
        feature_versions: dict[str, str] = {}
        for name, prediction in component_predictions:
            if prediction.model_version:
                model_versions[name] = prediction.model_version
            if prediction.feature_version:
                feature_versions[name] = prediction.feature_version

        return UnifiedMLResult(
            report_id=report.report_id,
            text_prediction=text_prediction,
            duplicate_prediction=duplicate_prediction,
            event_prediction=event_prediction,
            credibility_prediction=credibility_prediction,
            image_prediction=image_prediction,
            anomaly_prediction=anomaly_prediction,
            model_versions=model_versions,
            feature_versions=feature_versions,
            warnings=warnings,
            errors=errors,
        )
