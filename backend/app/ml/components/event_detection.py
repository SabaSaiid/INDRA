"""Deterministic, local-only event grouping and evidence extraction.

This module deliberately does not train a model. It groups already-loaded
report observations using geographic proximity, temporal proximity, supplied
duplicate relationships, and compatible report-level event-type evidence.
The resulting score is an ``EVENT_EVIDENCE_SCORE`` / provisional confidence,
never a calibrated probability that an event is real.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import timezone
from time import perf_counter
from typing import Iterable, Sequence

from app.ml.config import DEFAULT_EVENT_DETECTOR_CONFIG, EventDetectorConfig
from app.ml.contracts import (
    AnomalyPrediction,
    DuplicatePrediction,
    EventCandidate,
    EventDetectionResult,
    EventDetectionStatus,
    EventFeatureSnapshot,
    EventLifecycleStatus,
    EventMergeDecision,
    EventObservation,
    EventPrediction,
    ImagePrediction,
    PredictionStatus,
    ReportInput,
    SingleReportEventCandidate,
    TextPrediction,
)


EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return deterministic great-circle distance in kilometres."""

    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
    )
    return EARTH_RADIUS_KM * 2.0 * math.asin(math.sqrt(min(1.0, value)))


def _utc_seconds(value) -> float:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).timestamp()
    return value.astimezone(timezone.utc).timestamp()


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def _observation_type(observation: EventObservation, config: EventDetectorConfig) -> str | None:
    prediction = observation.text_prediction
    if prediction.status is not PredictionStatus.AVAILABLE:
        return None
    probabilities = prediction.probabilities
    if not probabilities and prediction.label:
        return prediction.label
    if not probabilities:
        return None
    label, probability = max(
        probabilities.items(),
        key=lambda item: (float(item[1]), item[0]),
    )
    if float(probability) < config.minimum_type_probability:
        return None
    return label


def _normalised_probabilities(prediction: TextPrediction) -> dict[str, float]:
    if prediction.status is not PredictionStatus.AVAILABLE or not prediction.probabilities:
        return {}
    values = {label: max(0.0, float(value)) for label, value in prediction.probabilities.items()}
    total = sum(values.values())
    if total <= 0.0:
        return {}
    return {label: value / total for label, value in values.items()}


def event_types_compatible(
    left: str | None,
    right: str | None,
    config: EventDetectorConfig | None = None,
) -> bool:
    """Apply explicit event-type compatibility rules.

    Missing NLP evidence is compatible with a typed observation because the
    geographic and temporal evidence can still be evaluated. Two different
    known types are incompatible by default; callers may opt into a rule.
    """

    if left is None or right is None:
        return True
    if left == right:
        return True
    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    return right in config.compatible_event_type_rules.get(left, ()) or left in config.compatible_event_type_rules.get(right, ())


def _duplicate_pairs(observations: Sequence[EventObservation]) -> set[tuple[str, str]]:
    ids = {str(item.report_id) for item in observations}
    pairs: set[tuple[str, str]] = set()
    for observation in observations:
        duplicate = observation.duplicate_prediction
        if duplicate.is_duplicate is not True:
            continue
        matched = duplicate.matched_report_id or duplicate.candidate_id
        if matched is None or str(matched) not in ids:
            continue
        pairs.add(_pair_key(str(observation.report_id), str(matched)))
    return pairs


def _duplicate_ids(pairs: Iterable[tuple[str, str]]) -> set[str]:
    result: set[str] = set()
    for left, right in pairs:
        result.update((left, right))
    return result


def _aggregate_type(
    observations: Sequence[EventObservation],
    config: EventDetectorConfig,
) -> tuple[str | None, dict[str, float], float | None, list[str]]:
    vectors = [_normalised_probabilities(item.text_prediction) for item in observations]
    vectors = [vector for vector in vectors if vector]
    evidence: list[str] = []
    if not vectors:
        return None, {}, None, ["NLP_EVENT_TYPE_EVIDENCE_UNAVAILABLE"]

    totals: defaultdict[str, float] = defaultdict(float)
    for vector in vectors:
        for label, value in vector.items():
            totals[label] += value
    aggregate = {label: value / len(vectors) for label, value in sorted(totals.items())}
    top_label, top_probability = max(
        aggregate.items(),
        key=lambda item: (item[1], item[0]),
    )
    top_labels = [
        _observation_type(item, config)
        for item in observations
        if _observation_type(item, config) is not None
    ]
    agreement = (
        sum(label == top_label for label in top_labels) / len(top_labels)
        if top_labels
        else None
    )
    if top_label == "NOT_RELEVANT" or top_probability < config.minimum_type_probability:
        evidence.append("EVENT_TYPE_UNCERTAIN")
        event_type = None
    else:
        event_type = top_label
        evidence.append("HEURISTIC_EVENT_TYPE_AGGREGATION")
    evidence.append(f"nlp_observations={len(vectors)}")
    return event_type, aggregate, agreement, evidence


def _weather_consistency(observations: Sequence[EventObservation]) -> float | None:
    values_by_measurement: defaultdict[str, list[float]] = defaultdict(list)
    for observation in observations:
        for station in observation.weather_observations:
            for name, value in station.measurements.items():
                if value is not None and math.isfinite(float(value)):
                    values_by_measurement[name].append(float(value))
    scores: list[float] = []
    for values in values_by_measurement.values():
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        mean_absolute_deviation = sum(abs(value - mean) for value in values) / len(values)
        scores.append(max(0.0, 1.0 - mean_absolute_deviation / (abs(mean) + 1.0)))
    return sum(scores) / len(scores) if scores else None


def extract_event_features(
    observations: Sequence[EventObservation],
    *,
    duplicate_pairs: set[tuple[str, str]] | None = None,
    config: EventDetectorConfig | None = None,
) -> EventFeatureSnapshot:
    """Extract versioned deterministic features from one grouped observation set."""

    if not observations:
        raise ValueError("at least one observation is required")
    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    duplicate_pairs = duplicate_pairs if duplicate_pairs is not None else _duplicate_pairs(observations)
    latitudes = [item.latitude for item in observations]
    longitudes = [item.longitude for item in observations]
    centroid_latitude = sum(latitudes) / len(latitudes)
    centroid_longitude = sum(longitudes) / len(longitudes)
    spatial_dispersion = max(
        haversine_km(item.latitude, item.longitude, centroid_latitude, centroid_longitude)
        for item in observations
    )
    timestamps = [_utc_seconds(item.occurred_at) for item in observations]
    temporal_dispersion = (max(timestamps) - min(timestamps)) / 60.0
    _, _, agreement, _ = _aggregate_type(observations, config)
    duplicate_ids = _duplicate_ids(duplicate_pairs)
    radius = max(spatial_dispersion, 0.001)
    duration_hours = max(temporal_dispersion / 60.0, 1.0 / 60.0)
    return EventFeatureSnapshot(
        feature_version=config.feature_version,
        spatial_dispersion_km=spatial_dispersion,
        temporal_dispersion_minutes=temporal_dispersion,
        report_count=len(observations),
        source_count=len({item.source_type for item in observations}),
        class_agreement=agreement,
        duplicate_ratio=len(duplicate_ids) / len(observations),
        geographic_density=len(observations) / (math.pi * radius * radius),
        time_density=len(observations) / duration_hours,
        weather_consistency=_weather_consistency(observations),
    )


def _candidate_score(
    features: EventFeatureSnapshot,
    independent_report_count: int,
    config: EventDetectorConfig,
) -> float:
    """Calculate an evidence score with documented heuristic factors."""

    report_factor = min(independent_report_count / max(config.minimum_reports, 1), 1.0)
    spatial_factor = max(0.0, 1.0 - features.spatial_dispersion_km / config.spatial_radius_km)
    temporal_factor = max(0.0, 1.0 - features.temporal_dispersion_minutes / config.temporal_window_minutes)
    agreement_factor = features.class_agreement if features.class_agreement is not None else 0.5
    source_factor = min(features.source_count / max(config.minimum_reports, 1), 1.0)
    duplicate_factor = 1.0 - features.duplicate_ratio
    weather_factor = features.weather_consistency if features.weather_consistency is not None else 0.5
    score = (
        0.25 * report_factor
        + 0.15 * spatial_factor
        + 0.15 * temporal_factor
        + 0.20 * agreement_factor
        + 0.15 * source_factor
        + 0.05 * duplicate_factor
        + 0.05 * weather_factor
    )
    return round(max(0.0, min(1.0, score)), 10)


def _event_id(report_ids: Sequence[str]) -> str:
    payload = "|".join(sorted(report_ids)).encode("utf-8")
    return "event-" + hashlib.sha256(payload).hexdigest()[:16]


def build_event_candidate(
    observations: Sequence[EventObservation],
    *,
    duplicate_pairs: set[tuple[str, str]] | None = None,
    config: EventDetectorConfig | None = None,
) -> EventCandidate:
    """Build one candidate from observations already assigned to a group."""

    if not observations:
        raise ValueError("at least one observation is required")
    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    duplicate_pairs = duplicate_pairs if duplicate_pairs is not None else _duplicate_pairs(observations)
    features = extract_event_features(observations, duplicate_pairs=duplicate_pairs, config=config)
    event_type, type_probabilities, _, type_evidence = _aggregate_type(observations, config)
    report_ids = sorted((item.report_id for item in observations), key=str)
    timestamps = [_utc_seconds(item.occurred_at) for item in observations]
    start_time = min(item.occurred_at for item in observations)
    end_time = max(item.occurred_at for item in observations)
    centroid_latitude = sum(item.latitude for item in observations) / len(observations)
    centroid_longitude = sum(item.longitude for item in observations) / len(observations)
    duplicate_ids = _duplicate_ids(duplicate_pairs)
    independent_count = max(1, len(observations) - len(duplicate_ids) + len(duplicate_pairs))
    independent_count = min(len(observations), independent_count)
    evidence = [
        "EVENT_EVIDENCE_SCORE_NOT_CALIBRATED",
        "PROVISIONAL_EVENT_CONFIDENCE",
        f"report_count={len(observations)}",
        f"independent_report_count={independent_count}",
        f"unique_source_count={len({item.source_type for item in observations})}",
        f"spatial_dispersion_km={features.spatial_dispersion_km:.6f}",
        f"temporal_dispersion_minutes={features.temporal_dispersion_minutes:.6f}",
        *type_evidence,
    ]
    nlp_statuses = sorted({item.text_prediction.status.value for item in observations})
    evidence.append("nlp_statuses=" + ",".join(nlp_statuses))
    if any(
        "model_status=EVALUATED" in item
        for observation in observations
        for item in observation.text_prediction.evidence
    ):
        evidence.append("NLP_MODEL_IS_DEVELOPMENT_ONLY")
    warnings = [
        "Heuristic event evidence is not a calibrated probability.",
        "No authoritative event-level ground truth is available.",
    ]
    if len(observations) < config.minimum_reports or independent_count < config.minimum_reports:
        evidence.append("BELOW_MINIMUM_REPORTS")
        warnings.append("Candidate has fewer independent reports than configured minimum.")
    if features.weather_consistency is None:
        evidence.append("WEATHER_EVIDENCE_UNAVAILABLE")
    status = EventLifecycleStatus.UNCERTAIN if event_type is None else EventLifecycleStatus.CANDIDATE
    return EventCandidate(
        event_id=_event_id([str(item) for item in report_ids]),
        event_type=event_type,
        type_probabilities=type_probabilities,
        report_ids=report_ids,
        centroid_latitude=centroid_latitude,
        centroid_longitude=centroid_longitude,
        start_time=start_time,
        end_time=end_time,
        duration=(max(timestamps) - min(timestamps)) / 60.0,
        report_count=len(observations),
        unique_source_count=len({item.source_type for item in observations}),
        independent_report_count=independent_count,
        event_confidence=_candidate_score(features, independent_count, config),
        evidence=evidence,
        status=status,
        feature_version=config.feature_version,
        algorithm_version=config.algorithm_version,
        features=features,
        source_types=sorted({item.source_type for item in observations}),
        warnings=warnings,
    )


def group_event_observations(
    observations: Sequence[EventObservation],
    *,
    config: EventDetectorConfig | None = None,
) -> EventDetectionResult:
    """Group observations with a deterministic temporal sweep and union-find."""

    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    if not observations:
        return EventDetectionResult(
            status=EventDetectionStatus.DATA_UNAVAILABLE,
            feature_version=config.feature_version,
            algorithm_version=config.algorithm_version,
            warnings=["No already-loaded observations were supplied."],
        )
    ids = [str(item.report_id) for item in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("event observations must have unique report IDs")

    total_start = perf_counter()
    ordered = sorted(observations, key=lambda item: (_utc_seconds(item.occurred_at), str(item.report_id)))
    parent = list(range(len(ordered)))
    rank = [0] * len(ordered)
    members = {index: {index} for index in range(len(ordered))}
    timestamps = [_utc_seconds(item.occurred_at) for item in ordered]
    event_types = [_observation_type(item, config) for item in ordered]
    temporal_window_seconds = config.temporal_window_minutes * 60.0
    pair_compatibility: dict[tuple[int, int], bool] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def pair_within_cluster_bounds(left: int, right: int) -> bool:
        key = (left, right) if left < right else (right, left)
        if key not in pair_compatibility:
            left_observation = ordered[key[0]]
            right_observation = ordered[key[1]]
            pair_compatibility[key] = (
                abs(timestamps[key[1]] - timestamps[key[0]])
                <= temporal_window_seconds
                and haversine_km(
                    left_observation.latitude,
                    left_observation.longitude,
                    right_observation.latitude,
                    right_observation.longitude,
                )
                <= config.spatial_radius_km
                and event_types_compatible(
                    event_types[key[0]],
                    event_types[key[1]],
                    config,
                )
            )
        return pair_compatibility[key]

    def clusters_within_bounds(left: int, right: int) -> bool:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return True
        return all(
            pair_within_cluster_bounds(left_member, right_member)
            for left_member in members[left_root]
            for right_member in members[right_root]
        )

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1
        members[left_root].update(members.pop(right_root))

    comparisons = 0
    bounded_merge_rejections = 0
    for left_index in range(len(ordered)):
        left_seconds = timestamps[left_index]
        for right_index in range(left_index + 1, len(ordered)):
            if timestamps[right_index] - left_seconds > temporal_window_seconds:
                break
            comparisons += 1
            if not pair_within_cluster_bounds(left_index, right_index):
                continue
            # Complete-link bounds prevent A-B-C bridge chains from creating a
            # cluster where any member pair exceeds the configured spatial,
            # temporal, or type-compatibility limits.
            if not clusters_within_bounds(left_index, right_index):
                bounded_merge_rejections += 1
                continue
            union(left_index, right_index)

    grouping_seconds = perf_counter() - total_start
    groups: defaultdict[int, list[EventObservation]] = defaultdict(list)
    for index, observation in enumerate(ordered):
        groups[find(index)].append(observation)
    duplicate_pairs = _duplicate_pairs(observations)
    feature_start = perf_counter()
    candidates = [
        build_event_candidate(
            sorted(group, key=lambda item: str(item.report_id)),
            duplicate_pairs={
                pair for pair in duplicate_pairs
                if all(
                    any(str(item.report_id) == member for item in group)
                    for member in pair
                )
            },
            config=config,
        )
        for group in sorted(groups.values(), key=lambda items: min(str(item.report_id) for item in items))
    ]
    feature_seconds = perf_counter() - feature_start
    total_seconds = perf_counter() - total_start
    return EventDetectionResult(
        status=EventDetectionStatus.AVAILABLE,
        candidates=candidates,
        candidate_comparisons=comparisons,
        grouping_seconds=grouping_seconds,
        feature_extraction_seconds=feature_seconds,
        total_seconds=total_seconds,
        feature_version=config.feature_version,
        algorithm_version=config.algorithm_version,
        warnings=[
            "Heuristic grouping is not production event-detection validation.",
            "No authoritative event-level ground truth is available.",
            *(
                [
                    f"Complete-link cluster bounds rejected {bounded_merge_rejections} transitive bridge link(s)."
                ]
                if bounded_merge_rejections
                else []
            ),
        ],
    )


def compare_event_candidates(
    left: EventCandidate,
    right: EventCandidate,
    *,
    config: EventDetectorConfig | None = None,
) -> EventMergeDecision:
    """Decide whether two candidates may merge; same type alone is insufficient."""

    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    distance = haversine_km(
        left.centroid_latitude,
        left.centroid_longitude,
        right.centroid_latitude,
        right.centroid_longitude,
    )
    left_start, left_end = _utc_seconds(left.start_time), _utc_seconds(left.end_time)
    right_start, right_end = _utc_seconds(right.start_time), _utc_seconds(right.end_time)
    if left_end < right_start:
        temporal_gap = (right_start - left_end) / 60.0
    elif right_end < left_start:
        temporal_gap = (left_start - right_end) / 60.0
    else:
        temporal_gap = 0.0
    combined_temporal_span = (
        max(left_end, right_end) - min(left_start, right_start)
    ) / 60.0
    combined_spatial_bound = (
        left.features.spatial_dispersion_km
        + distance
        + right.features.spatial_dispersion_km
    )
    compatible = event_types_compatible(left.event_type, right.event_type, config)
    reasons = []
    if distance > config.spatial_radius_km:
        reasons.append("GEOGRAPHIC_DISTANCE_EXCEEDS_RADIUS")
    if combined_spatial_bound > config.spatial_radius_km:
        reasons.append("CLUSTER_DIAMETER_BOUND_EXCEEDS_RADIUS")
    if temporal_gap > config.temporal_window_minutes:
        reasons.append("TEMPORAL_GAP_EXCEEDS_WINDOW")
    if combined_temporal_span > config.temporal_window_minutes:
        reasons.append("CLUSTER_TEMPORAL_SPAN_EXCEEDS_WINDOW")
    if not compatible:
        reasons.append("EVENT_TYPES_INCOMPATIBLE")
    if not reasons:
        reasons.append("GEOGRAPHIC_TEMPORAL_TYPE_RULES_PASS")
    blocking = {
        "GEOGRAPHIC_DISTANCE_EXCEEDS_RADIUS",
        "CLUSTER_DIAMETER_BOUND_EXCEEDS_RADIUS",
        "TEMPORAL_GAP_EXCEEDS_WINDOW",
        "CLUSTER_TEMPORAL_SPAN_EXCEEDS_WINDOW",
        "EVENT_TYPES_INCOMPATIBLE",
    }
    return EventMergeDecision(
        should_merge=not any(reason in blocking for reason in reasons),
        geographic_distance_km=distance,
        temporal_gap_minutes=temporal_gap,
        event_type_compatible=compatible,
        reason_codes=reasons,
        algorithm_version=config.algorithm_version,
    )


def merge_event_candidates(
    left: EventCandidate,
    right: EventCandidate,
    *,
    config: EventDetectorConfig | None = None,
) -> EventCandidate:
    """Merge two candidates only when the explicit merge decision permits it."""

    config = config or DEFAULT_EVENT_DETECTOR_CONFIG
    decision = compare_event_candidates(left, right, config=config)
    if not decision.should_merge:
        raise ValueError("event candidates are not merge-compatible: " + ", ".join(decision.reason_codes))
    report_ids = sorted(set(left.report_ids + right.report_ids), key=str)
    source_types = sorted(set(left.source_types + right.source_types))
    start_time = min(left.start_time, right.start_time)
    end_time = max(left.end_time, right.end_time)
    weighted_total = max(1, left.report_count + right.report_count)
    type_totals: defaultdict[str, float] = defaultdict(float)
    for candidate in (left, right):
        for label, value in candidate.type_probabilities.items():
            type_totals[label] += value * candidate.report_count / weighted_total
    type_probabilities = dict(sorted(type_totals.items()))
    event_type = left.event_type or right.event_type
    if left.event_type and right.event_type and left.event_type != right.event_type:
        event_type = None
    class_values = [
        value
        for value in (left.features.class_agreement, right.features.class_agreement)
        if value is not None
    ]
    feature = EventFeatureSnapshot(
        feature_version=config.feature_version,
        spatial_dispersion_km=max(
            left.features.spatial_dispersion_km
            + decision.geographic_distance_km * right.report_count / weighted_total,
            right.features.spatial_dispersion_km
            + decision.geographic_distance_km * left.report_count / weighted_total,
        ),
        temporal_dispersion_minutes=(
            _utc_seconds(end_time) - _utc_seconds(start_time)
        ) / 60.0,
        report_count=len(report_ids),
        source_count=max(1, len(source_types)),
        class_agreement=min(class_values) if class_values else None,
        duplicate_ratio=(
            left.features.duplicate_ratio * left.report_count
            + right.features.duplicate_ratio * right.report_count
        ) / weighted_total,
        geographic_density=(left.features.geographic_density + right.features.geographic_density) / 2.0,
        time_density=(left.features.time_density + right.features.time_density) / 2.0,
        weather_consistency=(
            (left.features.weather_consistency + right.features.weather_consistency) / 2.0
            if left.features.weather_consistency is not None and right.features.weather_consistency is not None
            else left.features.weather_consistency or right.features.weather_consistency
        ),
    )
    return EventCandidate(
        event_id=_event_id([str(item) for item in report_ids]),
        event_type=event_type,
        type_probabilities=type_probabilities,
        report_ids=report_ids,
        centroid_latitude=(left.centroid_latitude * left.report_count + right.centroid_latitude * right.report_count) / weighted_total,
        centroid_longitude=(left.centroid_longitude * left.report_count + right.centroid_longitude * right.report_count) / weighted_total,
        start_time=start_time,
        end_time=end_time,
        duration=feature.temporal_dispersion_minutes,
        report_count=len(report_ids),
        unique_source_count=len(source_types),
        independent_report_count=min(
            len(report_ids),
            max(1, left.independent_report_count + right.independent_report_count),
        ),
        event_confidence=round(
            (left.event_confidence or 0.0) * left.report_count / weighted_total
            + (right.event_confidence or 0.0) * right.report_count / weighted_total,
            10,
        ),
        evidence=[
            "EVENT_CANDIDATES_MERGED_BY_EXPLICIT_RULES",
            *decision.reason_codes,
            "MERGED_SCORE_REMAINS_PROVISIONAL",
        ],
        status=EventLifecycleStatus.MERGED,
        feature_version=config.feature_version,
        algorithm_version=config.algorithm_version,
        features=feature,
        source_types=source_types,
        warnings=[
            "Merged event evidence is not a calibrated probability.",
            "Merge does not establish production event truth.",
        ],
    )


def transition_event(
    candidate: EventCandidate,
    target: EventLifecycleStatus,
    *,
    human_confirmed: bool = False,
    reason: str | None = None,
) -> EventCandidate:
    """Apply explicit lifecycle rules; heuristic scoring cannot confirm events."""

    if target is EventLifecycleStatus.CONFIRMED and not human_confirmed:
        raise ValueError("CONFIRMED requires explicit human_confirmed=True")
    if candidate.status is EventLifecycleStatus.CLOSED and target is not EventLifecycleStatus.CLOSED:
        raise ValueError("CLOSED candidates cannot transition without reopening policy")
    if target is EventLifecycleStatus.MERGED:
        raise ValueError("MERGED is produced by merge_event_candidates")
    evidence = list(candidate.evidence)
    evidence.append(f"LIFECYCLE_TRANSITION={candidate.status.value}->{target.value}")
    if reason:
        evidence.append("LIFECYCLE_REASON=" + reason)
    if target is EventLifecycleStatus.CONFIRMED:
        evidence.append("HUMAN_CONFIRMATION_REQUIRED_AND_SUPPLIED")
    return candidate.model_copy(update={"status": target, "evidence": evidence})


class EventDetector:
    """Batch event framework; it intentionally does not query platform state."""

    component_name = "event_detector"

    def __init__(self, config: EventDetectorConfig | None = None) -> None:
        self.config = config or DEFAULT_EVENT_DETECTOR_CONFIG

    def detect(self, observations: Sequence[EventObservation]) -> EventDetectionResult:
        return group_event_observations(observations, config=self.config)

    def predict(
        self,
        report: ReportInput,
        *,
        text_prediction: TextPrediction | None = None,
        duplicate_prediction: DuplicatePrediction | None = None,
    ) -> EventPrediction:
        """Represent one report as a provisional candidate, never confirmation."""

        supplied_text = text_prediction or TextPrediction(
            status=PredictionStatus.NOT_APPLICABLE,
            reason_codes=["NLP_EVENT_TYPE_EVIDENCE_NOT_SUPPLIED"],
        )
        supplied_duplicate = duplicate_prediction or DuplicatePrediction(
            status=PredictionStatus.NOT_APPLICABLE,
            reason_codes=["DUPLICATE_EVIDENCE_NOT_SUPPLIED"],
        )
        observation = observation_from_report(
            report,
            text_prediction=supplied_text,
            duplicate_prediction=supplied_duplicate,
        )
        candidate = build_event_candidate([observation], config=self.config)
        if candidate.event_confidence is None:
            raise RuntimeError("single-report candidate evidence score is unavailable")
        single_report_candidate = SingleReportEventCandidate(
            event_id=candidate.event_id,
            report_ids=candidate.report_ids,
            event_type=candidate.event_type,
            type_probabilities=candidate.type_probabilities,
            candidate_latitude=candidate.centroid_latitude,
            candidate_longitude=candidate.centroid_longitude,
            candidate_timestamp=candidate.start_time,
            evidence_score=candidate.event_confidence,
            lifecycle_state="CANDIDATE",
            feature_version=candidate.feature_version,
            algorithm_version=candidate.algorithm_version,
            evidence=candidate.evidence,
            warnings=candidate.warnings,
        )
        return EventPrediction(
            status=PredictionStatus.HEURISTIC_ONLY,
            model_version=self.config.algorithm_version,
            feature_version=self.config.feature_version,
            event_type=single_report_candidate.event_type,
            probabilities=single_report_candidate.type_probabilities,
            confidence=None,
            candidate_event=single_report_candidate,
            evidence=[
                "SINGLE_REPORT_EVENT_CANDIDATE",
                "EVENT_EVIDENCE_SCORE_NOT_A_PROBABILITY",
                *single_report_candidate.evidence,
            ],
            reason_codes=[
                "SINGLE_REPORT_EVENT_CANDIDATE",
                "NOT_CONFIRMED_EVENT",
            ],
            warnings=[
                "One report creates only a provisional event candidate.",
                "Confirmation requires explicit human-controlled event lifecycle action.",
                *single_report_candidate.warnings,
            ],
        )


def observation_from_report(
    report: ReportInput,
    *,
    text_prediction: TextPrediction,
    duplicate_prediction: DuplicatePrediction | None = None,
    image_prediction: ImagePrediction | None = None,
    credibility_prediction=None,
    anomaly_prediction: AnomalyPrediction | None = None,
) -> EventObservation:
    """Adapt typed engine values without accessing any platform model."""

    duplicate_prediction = duplicate_prediction or DuplicatePrediction(
        status=PredictionStatus.NOT_APPLICABLE,
        reason_codes=["DUPLICATE_EVIDENCE_NOT_SUPPLIED"],
    )
    return EventObservation(
        report_id=report.report_id,
        text_prediction=text_prediction,
        occurred_at=report.occurred_at,
        latitude=report.latitude,
        longitude=report.longitude,
        source_type=report.source_type,
        duplicate_prediction=duplicate_prediction,
        weather_observations=list(report.station_observations),
        image_prediction=image_prediction,
        credibility_prediction=credibility_prediction,
        anomaly_prediction=anomaly_prediction,
    )


__all__ = [
    "EventDetector",
    "build_event_candidate",
    "compare_event_candidates",
    "event_types_compatible",
    "extract_event_features",
    "group_event_observations",
    "haversine_km",
    "merge_event_candidates",
    "observation_from_report",
    "transition_event",
]
