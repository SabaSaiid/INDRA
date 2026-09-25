"""Typed contracts for the local INDRA AI/ML subsystem.

This module deliberately contains data contracts only.  It does not import a
model library, access the database, consume Kafka, or perform network I/O.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PredictionStatus(str, Enum):
    """Explicit state for every component result."""

    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    HEURISTIC_ONLY = "HEURISTIC_ONLY"
    NOT_RUN = "NOT_RUN"


class ArtifactPolicyStatus(str, Enum):
    """Policy state for a locally produced artifact."""

    COMPLIANT = "COMPLIANT"
    LEGACY_NON_COMPLIANT = "LEGACY_NON_COMPLIANT"
    UNKNOWN = "UNKNOWN"


class MLModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CredibilityRiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNCERTAIN = "UNCERTAIN"


class CalibrationStatus(str, Enum):
    NOT_CALIBRATED = "NOT_CALIBRATED"
    CALIBRATION_UNAVAILABLE = "CALIBRATION_UNAVAILABLE"
    CALIBRATED = "CALIBRATED"


class AnomalyType(str, Enum):
    VALUE_OUTLIER = "VALUE_OUTLIER"
    RATE_OF_CHANGE = "RATE_OF_CHANGE"
    PERSISTENT_DEVIATION = "PERSISTENT_DEVIATION"
    MISSINGNESS_PATTERN = "MISSINGNESS_PATTERN"
    UNCERTAIN = "UNCERTAIN"


class AnomalyScope(str, Enum):
    POINT_ANOMALY = "POINT_ANOMALY"
    WINDOW_ANOMALY = "WINDOW_ANOMALY"


class AnomalyDomain(str, Enum):
    DATA_QUALITY_ANOMALY = "DATA_QUALITY_ANOMALY"
    WEATHER_BEHAVIOR_ANOMALY = "WEATHER_BEHAVIOR_ANOMALY"
    UNCERTAIN = "UNCERTAIN"


class MissingDataState(str, Enum):
    MISSING_INPUT = "MISSING_INPUT"
    SEASONALLY_UNAVAILABLE = "SEASONALLY_UNAVAILABLE"
    SENSOR_GAP = "SENSOR_GAP"
    UNKNOWN = "UNKNOWN"


class CredibilityEvidence(MLModel):
    """One inspectable risk signal; never a conclusion that a report is false."""

    feature: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    value: Any | None = None
    interpretation: str = Field(min_length=1)
    severity: EvidenceSeverity
    provenance: str = Field(min_length=1)


class CandidateReport(MLModel):
    report_id: UUID
    text: str
    occurred_at: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_type: str = Field(min_length=1)


class StationObservation(MLModel):
    station_id: str = Field(min_length=1)
    observed_at: datetime
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    measurements: dict[str, float | None] = Field(default_factory=dict)


class WeatherObservation(MLModel):
    """One already-loaded station observation using repository-approved fields.

    The production station table currently contains only 24-hour rainfall and
    optional river level. Temperature, humidity, pressure, and wind are not
    included because the repository has no such station measurements.
    """

    observation_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    observed_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    rainfall_mm: float | None = None
    river_level_m: float | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class AnomalyInputWindow(MLModel):
    """Ordered, already-loaded observations for exactly one station."""

    station_id: str = Field(min_length=1)
    observations: list[WeatherObservation] = Field(default_factory=list)
    start_at: datetime | None = None
    end_at: datetime | None = None
    station_metadata: dict[str, Any] = Field(default_factory=dict)
    event_context: dict[str, Any] = Field(default_factory=dict)


class AnomalyValidationIssue(MLModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["ERROR", "WARNING"]
    observation_id: str | None = None
    field: str | None = None
    value: Any | None = None


class AnomalyWindowValidationResult(MLModel):
    valid: bool
    station_id: str
    observation_count: int = Field(ge=0)
    errors: list[AnomalyValidationIssue] = Field(default_factory=list)
    warnings: list[AnomalyValidationIssue] = Field(default_factory=list)
    duplicate_timestamps: list[datetime] = Field(default_factory=list)
    median_interval_seconds: float | None = Field(default=None, gt=0.0)
    irregular_interval_count: int = Field(default=0, ge=0)
    missing_measurement_count: int = Field(default=0, ge=0)


class WeatherMeasurementFeatures(MLModel):
    value: float | None = None
    previous_value: float | None = None
    delta: float | None = None
    rate_per_hour: float | None = None
    rolling_mean: float | None = None
    rolling_median: float | None = None
    rolling_standard_deviation: float | None = None
    rolling_lower_quantile: float | None = None
    rolling_upper_quantile: float | None = None
    rolling_mad: float | None = None
    rolling_change_mean: float | None = None
    reference_count: int = Field(default=0, ge=0)
    missing: bool


class AnomalyFeatureRow(MLModel):
    feature_version: str = "anomaly-features-v1"
    observation_id: str
    station_id: str
    observed_at: datetime
    hour_of_day: int = Field(ge=0, le=23)
    day_of_year: int = Field(ge=1, le=366)
    interval_seconds: float | None = Field(default=None, gt=0.0)
    observation_density_per_hour: float | None = Field(default=None, ge=0.0)
    cumulative_missingness_ratio: float = Field(ge=0.0, le=1.0)
    lower_quantile_probability: float = Field(gt=0.0, lt=1.0)
    upper_quantile_probability: float = Field(gt=0.0, lt=1.0)
    rainfall: WeatherMeasurementFeatures
    river_level: WeatherMeasurementFeatures

    @model_validator(mode="after")
    def validate_quantile_probabilities(self) -> AnomalyFeatureRow:
        if self.lower_quantile_probability >= self.upper_quantile_probability:
            raise ValueError("lower quantile probability must be below upper")
        return self


class AnomalyBaselineStatistics(MLModel):
    measurement: Literal["rainfall_mm", "river_level_m"]
    count: int = Field(ge=1)
    median: float
    mad: float = Field(ge=0.0)
    lower_quantile_probability: float = Field(gt=0.0, lt=1.0)
    upper_quantile_probability: float = Field(gt=0.0, lt=1.0)
    lower_quantile: float
    upper_quantile: float
    robust_scale: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_quantiles(self) -> AnomalyBaselineStatistics:
        if self.lower_quantile_probability >= self.upper_quantile_probability:
            raise ValueError("lower quantile probability must be below upper")
        if self.lower_quantile > self.upper_quantile:
            raise ValueError("lower quantile value must not exceed upper")
        return self


class StatisticalAnomalyBaseline(MLModel):
    baseline_name: Literal["STATISTICAL_ANOMALY_BASELINE"] = (
        "STATISTICAL_ANOMALY_BASELINE"
    )
    baseline_version: str = Field(min_length=1)
    baseline_dataset_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    baseline_start_at: datetime
    baseline_end_at: datetime
    feature_version: str
    fitting_parameters: dict[str, Any] = Field(default_factory=dict)
    measurement_statistics: dict[str, AnomalyBaselineStatistics] = Field(
        default_factory=dict
    )
    seasonal_statistics: dict[str, dict[str, AnomalyBaselineStatistics]] = Field(
        default_factory=dict
    )
    station_scope: list[str] = Field(min_length=1)
    observation_count: int = Field(ge=1)
    seasonality_mode: Literal["NONE", "HOUR_OF_DAY"] = "NONE"


class AnomalyBaselineFitResult(MLModel):
    status: Literal["AVAILABLE", "INSUFFICIENT_DATA"]
    baseline: StatisticalAnomalyBaseline | None = None
    warnings: list[str] = Field(default_factory=list)


class AnomalyPerformanceBenchmark(MLModel):
    observation_count: int = Field(ge=0)
    feature_computation_seconds: float = Field(ge=0.0)
    baseline_fitting_seconds: float = Field(ge=0.0)
    baseline_scoring_seconds: float = Field(ge=0.0)
    detector_inference_seconds: float = Field(ge=0.0)
    benchmark_scope: Literal["LOCAL_PREPROCESSING_AND_INFERENCE_ONLY"] = (
        "LOCAL_PREPROCESSING_AND_INFERENCE_ONLY"
    )


class ImageInput(MLModel):
    """Already-loaded image bytes and caller-supplied identity metadata."""

    image_id: str = Field(min_length=1)
    report_id: UUID | None = None
    image_bytes: bytes
    mime_type: str = Field(min_length=1)
    file_size: int = Field(ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    capture_timestamp: datetime | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class ImageValidationError(MLModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["ERROR", "WARNING"] = "ERROR"
    details: dict[str, Any] = Field(default_factory=dict)


class ImageValidationResult(MLModel):
    image_id: str
    valid: bool
    byte_sha256: str | None = None
    detected_mime_type: str | None = None
    detected_format: str | None = None
    detected_width: int | None = None
    detected_height: int | None = None
    detected_color_mode: str | None = None
    errors: list[ImageValidationError] = Field(default_factory=list)
    warnings: list[ImageValidationError] = Field(default_factory=list)


class ReportInput(MLModel):
    """Already-loaded values supplied by the surrounding backend."""

    report_id: UUID
    text: str
    occurred_at: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_type: str = Field(min_length=1)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    candidate_reports: list[CandidateReport] = Field(default_factory=list)
    station_observations: list[StationObservation] = Field(default_factory=list)
    image_bytes: bytes | None = None


class PredictionBase(MLModel):
    status: PredictionStatus
    model_version: str | None = None
    feature_version: str | None = None
    preprocessing_version: str | None = None
    evidence: list[str | CredibilityEvidence] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _validate_probability_mapping(
    probabilities: dict[str, float],
    *,
    require_normalized: bool,
) -> None:
    if any(not label for label in probabilities):
        raise ValueError("probability labels cannot be empty")
    if any(
        not math.isfinite(value) or value < 0.0 or value > 1.0
        for value in probabilities.values()
    ):
        raise ValueError("probability values must be finite and in [0, 1]")
    if require_normalized and probabilities and not math.isclose(
        sum(probabilities.values()),
        1.0,
        rel_tol=1e-6,
        abs_tol=1e-6,
    ):
        raise ValueError("multiclass probabilities must sum to 1")


class TextPrediction(PredictionBase):
    label: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_probabilities(self) -> "TextPrediction":
        _validate_probability_mapping(self.probabilities, require_normalized=True)
        if self.label is not None and self.probabilities and self.label not in self.probabilities:
            raise ValueError("text label must exist in the probability mapping")
        return self


class SingleReportEventCandidate(MLModel):
    """A one-report event hypothesis; never a confirmed real-world event."""

    event_id: str = Field(min_length=1)
    report_ids: list[UUID] = Field(min_length=1, max_length=1)
    event_type: str | None = None
    type_probabilities: dict[str, float] = Field(default_factory=dict)
    candidate_latitude: float = Field(ge=-90.0, le=90.0)
    candidate_longitude: float = Field(ge=-180.0, le=180.0)
    candidate_timestamp: datetime
    evidence_score: float = Field(ge=0.0, le=1.0)
    score_type: Literal["EVENT_EVIDENCE_SCORE"] = "EVENT_EVIDENCE_SCORE"
    lifecycle_state: Literal["CANDIDATE"] = "CANDIDATE"
    feature_version: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_type_evidence(self) -> "SingleReportEventCandidate":
        _validate_probability_mapping(
            self.type_probabilities,
            require_normalized=True,
        )
        if (
            self.event_type is not None
            and self.type_probabilities
            and self.event_type not in self.type_probabilities
        ):
            raise ValueError(
                "single-report candidate event type must exist in type probabilities"
            )
        return self


class EventPrediction(PredictionBase):
    event_type: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_event: SingleReportEventCandidate | None = None

    @model_validator(mode="after")
    def validate_probabilities(self) -> "EventPrediction":
        _validate_probability_mapping(self.probabilities, require_normalized=True)
        if (
            self.event_type is not None
            and self.probabilities
            and self.event_type not in self.probabilities
        ):
            raise ValueError("event type must exist in the probability mapping")
        if self.candidate_event is not None:
            if self.status is not PredictionStatus.HEURISTIC_ONLY:
                raise ValueError(
                    "single-report event candidates must use HEURISTIC_ONLY status"
                )
            if self.confidence is not None:
                raise ValueError(
                    "candidate evidence score must not populate generic confidence"
                )
            if self.event_type != self.candidate_event.event_type:
                raise ValueError("event prediction and candidate event types disagree")
            if self.probabilities != self.candidate_event.type_probabilities:
                raise ValueError(
                    "event prediction and candidate type evidence disagree"
                )
        return self


class CredibilityPrediction(PredictionBase):
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    label: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: CredibilityRiskLevel | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.CALIBRATION_UNAVAILABLE
    baseline_name: str | None = None
    features: CredibilityFeatureSnapshot | None = None

    @model_validator(mode="after")
    def validate_score_aliases(self) -> "CredibilityPrediction":
        if (
            self.score is not None
            and self.risk_score is not None
            and not math.isclose(self.score, self.risk_score, abs_tol=1e-12)
        ):
            raise ValueError("generic score and risk_score cannot disagree")
        return self


class DuplicatePrediction(PredictionBase):
    is_duplicate: bool | None = None
    candidate_id: UUID | None = None
    matched_report_id: UUID | None = None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    text_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    character_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    word_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    edit_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    geographic_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    temporal_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    geographic_distance_km: float | None = Field(default=None, ge=0.0)
    temporal_distance_minutes: float | None = Field(default=None, ge=0.0)
    text_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold_status: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    comparisons_performed: int = Field(default=0, ge=0)
    method: str | None = None


class ImagePrediction(PredictionBase):
    image_id: str | None = None
    label: str | None = None
    labels: list[str] = Field(default_factory=list)
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    task_type: Literal["MULTI_LABEL"] | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.CALIBRATION_UNAVAILABLE

    @model_validator(mode="after")
    def validate_probabilities(self) -> "ImagePrediction":
        _validate_probability_mapping(self.probabilities, require_normalized=False)
        if any(label not in self.probabilities for label in self.labels):
            raise ValueError("image labels must exist in the probability mapping")
        return self


class AnomalyPrediction(PredictionBase):
    is_anomaly: bool | None = None
    station_id: str | None = None
    observation_ids: list[str] = Field(default_factory=list)
    anomaly_type: AnomalyType | None = None
    anomaly_types: list[AnomalyType] = Field(default_factory=list)
    anomaly_scope: AnomalyScope | None = None
    anomaly_domain: AnomalyDomain | None = None
    score: float | None = Field(default=None, ge=0.0)
    score_type: Literal[
        "STATISTICAL_OUTLIER_SCORE", "SYNTHETIC_DEVELOPMENT_MODEL_SCORE"
    ] | None = None
    threshold: float | None = Field(default=None, ge=0.0)
    baseline_id: str | None = None
    baseline_version: str | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.CALIBRATION_UNAVAILABLE
    missing_data_state: MissingDataState | None = None


class CredibilityFeatureSnapshot(MLModel):
    """Features available at report-assessment time only."""

    feature_version: str = "credibility-risk-features-v1"
    text_length: int = Field(ge=0)
    token_count: int = Field(ge=0)
    lexical_diversity: float | None = Field(default=None, ge=0.0, le=1.0)
    repeated_token_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    repeated_phrase_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    punctuation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    claim_density: float | None = Field(default=None, ge=0.0, le=1.0)
    url_count: int = Field(ge=0)
    supplied_phone_count: int | None = Field(default=None, ge=0)
    submission_delay_seconds: float | None = None
    coordinates_valid: bool | None = None
    location_consistency: bool | None = None
    duplicate_flag: bool | None = None
    duplicate_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    duplicate_cluster_size: int | None = Field(default=None, ge=0)
    source_recent_report_count: int | None = Field(default=None, ge=0)
    source_recent_duplicate_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    event_type_consistency: bool | None = None
    media_text_consistency: bool | None = None
    metadata_error_count: int = Field(default=0, ge=0)


class CredibilityRiskInput(MLModel):
    """Already-loaded local evidence supplied to credibility-risk assessment."""

    report: ReportInput
    duplicate_prediction: DuplicatePrediction | None = None
    event_prediction: EventPrediction | None = None
    text_prediction: TextPrediction | None = None
    image_prediction: ImagePrediction | None = None
    submitted_at: datetime | None = None
    reported_latitude: float | None = None
    reported_longitude: float | None = None
    duplicate_cluster_size: int | None = Field(default=None, ge=0)
    source_recent_report_count: int | None = Field(default=None, ge=0)
    source_recent_duplicate_count: int | None = Field(default=None, ge=0)
    supplied_phone_count: int | None = Field(default=None, ge=0)
    location_consistency: bool | None = None
    event_type_consistency: bool | None = None
    media_text_consistency: bool | None = None
    metadata_validation_errors: list[str] = Field(default_factory=list)


class CredibilityTrainingResult(MLModel):
    status: Literal["DATA_UNAVAILABLE", "TRAINING_BLOCKED_NO_VALIDATED_LABELS"]
    artifact_created: Literal[False] = False
    reason_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImageTrainingResult(MLModel):
    status: Literal["DATA_UNAVAILABLE", "TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA"]
    artifact_created: Literal[False] = False
    task_type: Literal["MULTI_LABEL"] = "MULTI_LABEL"
    reason_codes: list[str] = Field(default_factory=list)
    required_provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnomalyTrainingResult(MLModel):
    status: Literal["DATA_UNAVAILABLE", "TRAINING_BLOCKED_NO_VALIDATED_ANOMALY_DATA"]
    artifact_created: Literal[False] = False
    reason_codes: list[str] = Field(default_factory=list)
    required_provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EventLifecycleStatus(str, Enum):
    """Lifecycle state for a heuristic event candidate."""

    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    UNCERTAIN = "UNCERTAIN"


class EventDetectionStatus(str, Enum):
    """Availability of a local event-grouping run."""

    AVAILABLE = "AVAILABLE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR = "ERROR"


class EventObservation(MLModel):
    """Already-loaded report evidence supplied to the event detector."""

    report_id: UUID
    text_prediction: TextPrediction
    occurred_at: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    source_type: str = Field(min_length=1)
    duplicate_prediction: DuplicatePrediction
    weather_observations: list[StationObservation] = Field(default_factory=list)
    image_prediction: ImagePrediction | None = None
    credibility_prediction: CredibilityPrediction | None = None
    anomaly_prediction: AnomalyPrediction | None = None


class EventFeatureSnapshot(MLModel):
    """Deterministic, inspectable features for one event candidate."""

    feature_version: str = "event-features-v1"
    spatial_dispersion_km: float = Field(ge=0.0)
    temporal_dispersion_minutes: float = Field(ge=0.0)
    report_count: int = Field(ge=1)
    source_count: int = Field(ge=1)
    class_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    duplicate_ratio: float = Field(ge=0.0, le=1.0)
    geographic_density: float = Field(ge=0.0)
    time_density: float = Field(ge=0.0)
    weather_consistency: float | None = Field(default=None, ge=0.0, le=1.0)


class EventCandidate(MLModel):
    """A grouped event hypothesis, not a calibrated event probability."""

    event_id: str = Field(min_length=1)
    event_type: str | None = None
    type_probabilities: dict[str, float] = Field(default_factory=dict)
    report_ids: list[UUID] = Field(min_length=1)
    centroid_latitude: float = Field(ge=-90.0, le=90.0)
    centroid_longitude: float = Field(ge=-180.0, le=180.0)
    start_time: datetime
    end_time: datetime
    duration: float = Field(ge=0.0)
    report_count: int = Field(ge=1)
    unique_source_count: int = Field(ge=1)
    independent_report_count: int = Field(ge=1)
    event_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    status: EventLifecycleStatus = EventLifecycleStatus.CANDIDATE
    feature_version: str = "event-features-v1"
    algorithm_version: str = "event-grouping-v2"
    features: EventFeatureSnapshot
    source_types: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_type_probabilities(self) -> "EventCandidate":
        _validate_probability_mapping(
            self.type_probabilities,
            require_normalized=True,
        )
        if (
            self.event_type is not None
            and self.type_probabilities
            and self.event_type not in self.type_probabilities
        ):
            raise ValueError("candidate event type must exist in type probabilities")
        return self


class EventDetectionResult(MLModel):
    """Result of a pure local event-grouping run."""

    component: str = "event_detector"
    status: EventDetectionStatus
    candidates: list[EventCandidate] = Field(default_factory=list)
    candidate_comparisons: int = Field(default=0, ge=0)
    grouping_seconds: float | None = Field(default=None, ge=0.0)
    feature_extraction_seconds: float | None = Field(default=None, ge=0.0)
    total_seconds: float | None = Field(default=None, ge=0.0)
    feature_version: str = "event-features-v1"
    algorithm_version: str = "event-grouping-v2"
    warnings: list[str] = Field(default_factory=list)


class EventMergeDecision(MLModel):
    """Transparent merge recommendation for two event candidates."""

    should_merge: bool
    geographic_distance_km: float
    temporal_gap_minutes: float
    event_type_compatible: bool
    reason_codes: list[str] = Field(default_factory=list)
    algorithm_version: str = "event-grouping-v2"


class UnifiedMLResult(MLModel):
    schema_version: str = "1.0"
    report_id: UUID
    text_prediction: TextPrediction
    duplicate_prediction: DuplicatePrediction
    event_prediction: EventPrediction
    credibility_prediction: CredibilityPrediction
    image_prediction: ImagePrediction
    anomaly_prediction: AnomalyPrediction
    model_versions: dict[str, str] = Field(default_factory=dict)
    feature_versions: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ArtifactMetadata(MLModel):
    """Provenance required before an artifact may be loaded."""

    artifact_name: str = Field(pattern=r"^[^/\\]+$")
    artifact_version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    training_dataset_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    feature_version: str = Field(min_length=1)
    preprocessing_version: str = Field(min_length=1)
    training_timestamp: datetime
    random_seed: int
    framework_versions: dict[str, str] = Field(min_length=1)
    intended_component: str = Field(min_length=1)
    policy_status: ArtifactPolicyStatus


class ArtifactManifest(MLModel):
    manifest_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    policy_status: Literal["SCAFFOLD_ONLY"]
    runtime_downloads_allowed: Literal[False] = False
    artifacts: list[ArtifactMetadata] = Field(default_factory=list)
    legacy_artifacts: list[str] = Field(default_factory=list)
