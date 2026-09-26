"""Deterministic features for the credibility-risk framework."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from app.ml.config import DEFAULT_CREDIBILITY_RISK_CONFIG, CredibilityRiskConfig
from app.ml.contracts import (
    CredibilityFeatureSnapshot,
    CredibilityRiskInput,
    DuplicatePrediction,
    EventPrediction,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    TextPrediction,
)


URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"(?u)\b\w+\b")
CLAIM_TERMS = {
    "confirmed",
    "definitely",
    "guaranteed",
    "official",
    "urgent",
    "always",
    "never",
    "proof",
    "claim",
}


def normalize_credibility_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("timestamp must be a datetime or ISO-8601 string")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("value must be non-negative")
    return parsed


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("value must be a boolean")


def credibility_input_from_report(
    report: ReportInput,
    *,
    duplicate_prediction: DuplicatePrediction | None = None,
    event_prediction: EventPrediction | None = None,
    text_prediction: TextPrediction | None = None,
    image_prediction: ImagePrediction | None = None,
) -> CredibilityRiskInput:
    """Adapt report metadata without querying any external or platform service."""

    metadata = report.source_metadata
    errors: list[str] = []

    def parse(name: str, parser):
        try:
            return parser(metadata.get(name))
        except (TypeError, ValueError, OverflowError):
            errors.append(f"invalid source_metadata.{name}")
            return None

    submitted_at = parse("submitted_at", _parse_datetime)
    reported_latitude = parse("reported_latitude", _optional_float)
    reported_longitude = parse("reported_longitude", _optional_float)
    duplicate_cluster_size = parse("duplicate_cluster_size", _optional_nonnegative_int)
    source_recent_report_count = parse("source_recent_report_count", _optional_nonnegative_int)
    source_recent_duplicate_count = parse("source_recent_duplicate_count", _optional_nonnegative_int)
    supplied_phone_count = parse("phone_count", _optional_nonnegative_int)
    location_consistency = parse("location_consistency", _optional_bool)
    event_type_consistency = parse("event_type_consistency", _optional_bool)
    media_text_consistency = parse("media_text_consistency", _optional_bool)
    return CredibilityRiskInput(
        report=report,
        duplicate_prediction=duplicate_prediction,
        event_prediction=event_prediction,
        text_prediction=text_prediction,
        image_prediction=image_prediction,
        submitted_at=submitted_at,
        reported_latitude=reported_latitude,
        reported_longitude=reported_longitude,
        duplicate_cluster_size=duplicate_cluster_size,
        source_recent_report_count=source_recent_report_count,
        source_recent_duplicate_count=source_recent_duplicate_count,
        supplied_phone_count=supplied_phone_count,
        location_consistency=location_consistency,
        event_type_consistency=event_type_consistency,
        media_text_consistency=media_text_consistency,
        metadata_validation_errors=errors,
    )


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).timestamp()
    return value.astimezone(timezone.utc).timestamp()


def extract_credibility_features(
    value: CredibilityRiskInput,
    *,
    config: CredibilityRiskConfig | None = None,
) -> CredibilityFeatureSnapshot:
    """Extract only evidence available when the report is assessed."""

    config = config or DEFAULT_CREDIBILITY_RISK_CONFIG
    text = normalize_credibility_text(value.report.text)
    tokens = TOKEN_PATTERN.findall(text)
    token_count = len(tokens)
    lexical_diversity = len(set(tokens)) / token_count if token_count else None
    repeated_token_ratio = 1.0 - lexical_diversity if lexical_diversity is not None else None
    phrases = list(zip(tokens, tokens[1:]))
    repeated_phrase_ratio = (
        1.0 - len(set(phrases)) / len(phrases)
        if phrases
        else None
    )
    punctuation_count = sum(1 for character in text if not character.isalnum() and not character.isspace())
    punctuation_ratio = punctuation_count / len(text) if text else None
    claim_tokens = sum(token.isdigit() or token in CLAIM_TERMS for token in tokens)
    claim_density = claim_tokens / token_count if token_count else None

    latitude = value.reported_latitude
    longitude = value.reported_longitude
    if latitude is None and longitude is None:
        latitude = value.report.latitude
        longitude = value.report.longitude
    coordinates_valid = (
        latitude is not None
        and longitude is not None
        and math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    )

    submission_delay = None
    if value.submitted_at is not None:
        submission_delay = _timestamp(value.submitted_at) - _timestamp(value.report.occurred_at)

    duplicate = value.duplicate_prediction
    duplicate_flag = duplicate.is_duplicate if duplicate is not None else None
    duplicate_similarity = duplicate.similarity if duplicate is not None else None
    source_duplicate_ratio = None
    if value.source_recent_report_count is not None and value.source_recent_report_count > 0:
        duplicate_count = value.source_recent_duplicate_count or 0
        source_duplicate_ratio = min(1.0, duplicate_count / value.source_recent_report_count)

    event_consistency = value.event_type_consistency
    if event_consistency is None and value.text_prediction and value.event_prediction:
        if (
            value.text_prediction.status is PredictionStatus.AVAILABLE
            and value.event_prediction.status
            in {PredictionStatus.AVAILABLE, PredictionStatus.HEURISTIC_ONLY}
            and value.text_prediction.label
            and value.event_prediction.event_type
        ):
            event_consistency = value.text_prediction.label == value.event_prediction.event_type

    return CredibilityFeatureSnapshot(
        feature_version=config.feature_version,
        text_length=len(text),
        token_count=token_count,
        lexical_diversity=lexical_diversity,
        repeated_token_ratio=repeated_token_ratio,
        repeated_phrase_ratio=repeated_phrase_ratio,
        punctuation_ratio=punctuation_ratio,
        claim_density=claim_density,
        url_count=len(URL_PATTERN.findall(text)),
        supplied_phone_count=value.supplied_phone_count,
        submission_delay_seconds=submission_delay,
        coordinates_valid=coordinates_valid,
        location_consistency=value.location_consistency,
        duplicate_flag=duplicate_flag,
        duplicate_similarity=duplicate_similarity,
        duplicate_cluster_size=value.duplicate_cluster_size,
        source_recent_report_count=value.source_recent_report_count,
        source_recent_duplicate_ratio=source_duplicate_ratio,
        event_type_consistency=event_consistency,
        media_text_consistency=value.media_text_consistency,
        metadata_error_count=len(value.metadata_validation_errors),
    )


__all__ = [
    "credibility_input_from_report",
    "extract_credibility_features",
    "normalize_credibility_text",
]
