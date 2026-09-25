"""Transparent fake/misleading-report risk framework.

The rule baseline surfaces review signals. It does not establish truth,
authenticate a report, or estimate a calibrated probability of falsity.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.ml.components.credibility_features import (
    credibility_input_from_report,
    extract_credibility_features,
)
from app.ml.config import DEFAULT_CREDIBILITY_RISK_CONFIG, CredibilityRiskConfig
from app.ml.contracts import (
    CalibrationStatus,
    CredibilityEvidence,
    CredibilityPrediction,
    CredibilityRiskInput,
    CredibilityRiskLevel,
    CredibilityTrainingResult,
    EvidenceSeverity,
    PredictionStatus,
    ReportInput,
)


RULE_BASED_CREDIBILITY_BASELINE = "RULE_BASED_CREDIBILITY_BASELINE"


def _evidence(
    feature: str,
    reason_code: str,
    value: Any,
    interpretation: str,
    severity: EvidenceSeverity,
    provenance: str,
) -> CredibilityEvidence:
    return CredibilityEvidence(
        feature=feature,
        reason_code=reason_code,
        value=value,
        interpretation=interpretation,
        severity=severity,
        provenance=provenance,
    )


def _risk_level(score: float, config: CredibilityRiskConfig) -> CredibilityRiskLevel:
    if score >= config.high_risk_threshold:
        return CredibilityRiskLevel.HIGH
    if score >= config.moderate_risk_threshold:
        return CredibilityRiskLevel.MODERATE
    return CredibilityRiskLevel.LOW


def assess_credibility_risk(
    value: ReportInput | CredibilityRiskInput,
    *,
    config: CredibilityRiskConfig | None = None,
) -> CredibilityPrediction:
    """Apply the deterministic evidence baseline to already-loaded inputs."""

    config = config or DEFAULT_CREDIBILITY_RISK_CONFIG
    risk_input = value if isinstance(value, CredibilityRiskInput) else credibility_input_from_report(value)
    features = extract_credibility_features(risk_input, config=config)
    evidence: list[CredibilityEvidence] = [
        _evidence(
            "baseline_scope",
            "RULE_BASED_CREDIBILITY_BASELINE",
            RULE_BASED_CREDIBILITY_BASELINE,
            "Deterministic review signals only; this system does not establish truth by itself.",
            EvidenceSeverity.INFO,
            "project_rule_configuration",
        )
    ]
    weighted_signals: list[tuple[str, float]] = []

    def add(
        feature: str,
        code: str,
        value: Any,
        interpretation: str,
        severity: EvidenceSeverity,
        provenance: str,
        weight: float,
    ) -> None:
        evidence.append(_evidence(feature, code, value, interpretation, severity, provenance))
        if weight > 0.0:
            weighted_signals.append((code, weight))

    if features.metadata_error_count:
        add(
            "metadata_error_count",
            "INVALID_METADATA",
            features.metadata_error_count,
            "One or more supplied metadata fields could not be validated.",
            EvidenceSeverity.MEDIUM,
            "report.source_metadata",
            min(0.30, 0.10 * features.metadata_error_count),
        )
    if features.coordinates_valid is False:
        add(
            "coordinates_valid",
            "INVALID_COORDINATES",
            False,
            "Supplied report coordinates fall outside valid geographic ranges or are incomplete.",
            EvidenceSeverity.HIGH,
            "report_geographic_metadata",
            0.40,
        )
    if features.submission_delay_seconds is not None and features.submission_delay_seconds < -config.future_timestamp_tolerance_seconds:
        add(
            "submission_delay_seconds",
            "CONTRADICTORY_TIMESTAMP",
            features.submission_delay_seconds,
            "The reported occurrence time is later than submission time beyond the configured tolerance.",
            EvidenceSeverity.HIGH,
            "report_temporal_metadata",
            0.35,
        )
    if features.location_consistency is False:
        add(
            "location_consistency",
            "GEOGRAPHIC_INCONSISTENCY",
            False,
            "A caller-supplied deterministic location check conflicts with the report coordinates.",
            EvidenceSeverity.HIGH,
            "caller_supplied_location_check",
            0.25,
        )
    if features.event_type_consistency is False:
        add(
            "event_type_consistency",
            "EVENT_TYPE_INCONSISTENCY",
            False,
            "Report-level type evidence conflicts with the supplied event type; this is not proof of falsity.",
            EvidenceSeverity.MEDIUM,
            "supplied_text_and_event_predictions",
            0.20,
        )
    if features.duplicate_flag is True or (
        features.duplicate_similarity is not None
        and features.duplicate_similarity >= config.duplicate_similarity_threshold
    ):
        add(
            "duplicate_relationship",
            "REPEATED_TEXT",
            features.duplicate_similarity,
            "The report is linked to highly similar content; duplication alone does not mean the report is false.",
            EvidenceSeverity.LOW,
            "supplied_duplicate_prediction",
            0.10,
        )
    if features.duplicate_cluster_size is not None and features.duplicate_cluster_size >= config.duplicate_cluster_size_threshold:
        add(
            "duplicate_cluster_size",
            "EXCESSIVE_DUPLICATE_BEHAVIOR",
            features.duplicate_cluster_size,
            "The supplied duplicate cluster is unusually large and warrants review.",
            EvidenceSeverity.MEDIUM,
            "caller_supplied_duplicate_history",
            0.15,
        )
    if features.source_recent_report_count is not None and features.source_recent_report_count >= config.source_report_burst_threshold:
        add(
            "source_recent_report_count",
            "SOURCE_REPORT_BURST",
            features.source_recent_report_count,
            "The supplied source history shows many reports in the configured recent window.",
            EvidenceSeverity.MEDIUM,
            "caller_supplied_source_history",
            0.15,
        )
    if features.source_recent_duplicate_ratio is not None and features.source_recent_duplicate_ratio >= 0.50:
        add(
            "source_recent_duplicate_ratio",
            "SOURCE_DUPLICATE_PATTERN",
            features.source_recent_duplicate_ratio,
            "At least half of the supplied recent source reports are marked as duplicates.",
            EvidenceSeverity.MEDIUM,
            "caller_supplied_source_history",
            0.15,
        )
    repeated = (
        features.repeated_token_ratio is not None
        and features.repeated_token_ratio >= config.repeated_token_ratio_threshold
    ) or (
        features.repeated_phrase_ratio is not None
        and features.repeated_phrase_ratio >= config.repeated_phrase_ratio_threshold
    )
    if repeated:
        add(
            "text_repetition",
            "UNUSUAL_TEXT_REPETITION",
            {
                "token_ratio": features.repeated_token_ratio,
                "phrase_ratio": features.repeated_phrase_ratio,
            },
            "The report contains unusually repetitive wording under the configured deterministic rule.",
            EvidenceSeverity.MEDIUM,
            "report_text",
            0.15,
        )
    if features.punctuation_ratio is not None and features.punctuation_ratio >= config.punctuation_ratio_threshold:
        add(
            "punctuation_ratio",
            "EXCESSIVE_PUNCTUATION",
            features.punctuation_ratio,
            "Punctuation occupies an unusually large share of the supplied report text.",
            EvidenceSeverity.LOW,
            "report_text",
            0.08,
        )
    if features.url_count > config.url_count_threshold:
        add(
            "url_count",
            "EXCESSIVE_URLS",
            features.url_count,
            "The report contains more URLs than the configured review threshold.",
            EvidenceSeverity.MEDIUM,
            "report_text",
            0.10,
        )
    if features.supplied_phone_count is not None and features.supplied_phone_count > config.phone_count_threshold:
        add(
            "supplied_phone_count",
            "EXCESSIVE_PHONE_REFERENCES",
            features.supplied_phone_count,
            "The backend-supplied phone-reference count exceeds the review threshold.",
            EvidenceSeverity.MEDIUM,
            "caller_supplied_text_metadata",
            0.10,
        )
    if 0 < features.text_length < config.minimum_text_characters:
        add(
            "text_length",
            "VERY_SHORT_TEXT",
            features.text_length,
            "The report is too short to provide much internally checkable evidence.",
            EvidenceSeverity.INFO,
            "report_text",
            0.02,
        )
    if features.claim_density is not None and features.claim_density >= 0.30:
        add(
            "claim_density",
            "HIGH_CLAIM_DENSITY",
            features.claim_density,
            "The text has a high density of numeric or assertive tokens and may merit human verification.",
            EvidenceSeverity.INFO,
            "report_text",
            0.03,
        )
    if features.media_text_consistency is not None:
        add(
            "media_text_consistency",
            "MEDIA_EVIDENCE_RESERVED_NOT_SCORED",
            features.media_text_consistency,
            "A caller supplied media/text consistency value, but Phase 7 does not infer image manipulation.",
            EvidenceSeverity.INFO,
            "caller_supplied_media_interface",
            0.0,
        )

    optional_evidence_available = any(
        value is not None
        for value in (
            features.submission_delay_seconds,
            features.duplicate_flag,
            features.event_type_consistency,
            features.location_consistency,
            features.source_recent_report_count,
        )
    )
    if features.text_length == 0 and not optional_evidence_available and features.metadata_error_count == 0:
        evidence.append(
            _evidence(
                "evidence_availability",
                "INSUFFICIENT_EVIDENCE",
                None,
                "No report text or optional corroborating evidence was supplied for risk assessment.",
                EvidenceSeverity.INFO,
                "credibility_risk_input",
            )
        )
        return CredibilityPrediction(
            status=PredictionStatus.INSUFFICIENT_DATA,
            model_version=config.model_version,
            feature_version=config.feature_version,
            preprocessing_version=config.preprocessing_version,
            risk_level=CredibilityRiskLevel.UNCERTAIN,
            calibration_status=CalibrationStatus.CALIBRATION_UNAVAILABLE,
            baseline_name=config.baseline_name,
            features=features,
            evidence=evidence,
            reason_codes=["INSUFFICIENT_EVIDENCE"],
            warnings=["No credibility-risk score was fabricated from missing evidence."],
        )

    score = round(min(1.0, sum(weight for _, weight in weighted_signals)), 6)
    level = _risk_level(score, config)
    if not weighted_signals:
        evidence.append(
            _evidence(
                "rule_signals",
                "NO_RULE_RISK_SIGNALS",
                0,
                "No configured rule signal fired; this is not verification that the report is authentic.",
                EvidenceSeverity.INFO,
                "project_rule_configuration",
            )
        )
    reason_codes = [code for code, _ in weighted_signals]
    return CredibilityPrediction(
        status=PredictionStatus.AVAILABLE,
        model_version=config.model_version,
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        label=level.value,
        risk_score=score,
        risk_level=level,
        calibration_status=CalibrationStatus.NOT_CALIBRATED,
        baseline_name=config.baseline_name,
        features=features,
        evidence=evidence,
        reason_codes=reason_codes,
        warnings=[
            "THIS SYSTEM DOES NOT ESTABLISH TRUTH BY ITSELF.",
            "Risk score is deterministic and uncalibrated; it is not a probability of falsity.",
        ],
    )


class FakeDetector:
    """Rule baseline plus blocked future-learning interface."""

    component_name = "fake_detector"

    def __init__(self, config: CredibilityRiskConfig | None = None) -> None:
        self.config = config or DEFAULT_CREDIBILITY_RISK_CONFIG

    def predict(self, value: ReportInput | CredibilityRiskInput) -> CredibilityPrediction:
        return assess_credibility_risk(value, config=self.config)

    def fit(self, training_data: Sequence[Any] | None = None) -> CredibilityTrainingResult:
        return CredibilityTrainingResult(
            status="TRAINING_BLOCKED_NO_VALIDATED_LABELS",
            artifact_created=False,
            reason_codes=["NO_VALIDATED_FAKE_REPORT_LABELS"],
            warnings=[
                "The existing spam field is confounded with NOT_RELEVANT and is not valid authenticity ground truth."
            ],
        )

    def evaluate(self, labels=None, predictions=None, **kwargs):
        from app.ml.evaluation.evaluate import evaluate_credibility_predictions

        return evaluate_credibility_predictions(labels or [], predictions or [], **kwargs)


CredibilityRiskDetector = FakeDetector


__all__ = [
    "CredibilityRiskDetector",
    "FakeDetector",
    "RULE_BASED_CREDIBILITY_BASELINE",
    "assess_credibility_risk",
]
