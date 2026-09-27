"""Phase 20 synthetic validation for deterministic event-grouping-v2.

This module does not train a model and is not imported by the live backend.
It selects explicit grouping thresholds on the synthetic validation partition,
freezes a configuration, and permits one locked synthetic test evaluation.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Final

import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.event_detection import (
    build_event_candidate,
    event_types_compatible,
    group_event_observations,
    haversine_km,
)
from app.ml.config import EventDetectorConfig, file_sha256, local_only_path
from app.ml.contracts import (
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    EventCandidate,
    EventLifecycleStatus,
    PredictionStatus,
)
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetClassification,
    DatasetComponent,
    DatasetStatus,
    find_dataset,
    load_bound_validation_report,
    load_dataset_registry,
    resolve_registry_path,
)
from app.ml.data.synthetic_event.generator import (
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_VERSION,
    EVENT_SCENARIOS,
    FORBIDDEN_DETECTOR_FIELDS,
    GENERATOR_VERSION,
    SCENARIO_VERSION,
    SPLITS,
    SyntheticDetectorInput,
    SyntheticEventGroundTruth,
    SyntheticEventQualityReport,
)

ARTIFACT_VERSION: Final[str] = "event-grouping-v1-synthetic-development"
FEATURE_VERSION: Final[str] = "event-features-v1"
ALGORITHM_VERSION: Final[str] = "event-grouping-v2"
PREPROCESSING_VERSION: Final[str] = "event-observation-normalization-v1"
DEVELOPMENT_STATUS: Final[str] = "DEVELOPMENT_ONLY_SYNTHETIC"
PRODUCTION_VALIDATION: Final[str] = "NOT_VALIDATED"
FREEZE_TIMESTAMP: Final[datetime] = datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)
FINAL_EVALUATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 23, 22, 0, tzinfo=timezone.utc
)

ARTIFACT_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "artifacts"
DEFAULT_EVENT_ARTIFACT_PATH: Final[Path] = ARTIFACT_ROOT / "event_grouping_v1.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.development_manifest.json"
)
DEFAULT_THRESHOLD_SEARCH_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.threshold_search.json"
)
DEFAULT_ABLATION_PATH: Final[Path] = ARTIFACT_ROOT / "event_grouping_v1.ablation.json"
DEFAULT_VALIDATION_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.validation_metrics.json"
)
DEFAULT_VALIDATION_ERRORS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.validation_errors.json"
)
DEFAULT_PERFORMANCE_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.performance.json"
)
DEFAULT_GOLDEN_PATH: Final[Path] = ARTIFACT_ROOT / "event_grouping_v1.golden.json"
DEFAULT_FINAL_METRICS_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.metrics.json"
)
DEFAULT_ERROR_REPORT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1.error_report.json"
)
DEFAULT_FINAL_RECEIPT_PATH: Final[Path] = (
    ARTIFACT_ROOT / "event_grouping_v1_final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH: Final[Path] = ARTIFACT_ROOT / "manifest.json"

EXPECTED_PROTECTED_HASHES: Final[dict[str, str]] = {
    "duplicate_feature_state_v2.json": "d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731",
    "duplicate_matcher_v1.json": "85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b",
    "duplicate_v1_final_test_receipt.json": "4b97fa5b617c0bf2c93383a8d031be5a9fd6dcd5c08c9b2c229cec9d57ead405",
    "nlp_classifier_v3.json": "7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca",
    "nlp_classifier_v3.final_test_receipt.json": "ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b",
}


class EventValidationBlocked(ValueError):
    """Raised when the Phase 20 governed workflow must fail closed."""


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 10)


def _artifact_payload_hash(payload: Mapping[str, Any]) -> str:
    selected = dict(payload)
    selected.pop("artifact_hash", None)
    return _sha256_payload(selected)


class EventGroupingDevelopmentArtifact(BaseModel):
    """Versioned non-learned event configuration with hash-bound provenance."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_version: str
    artifact_kind: str
    development_status: str
    production_validation: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    scenario_version: str
    random_seed: int
    feature_version: str
    algorithm_version: str
    preprocessing_version: str
    thresholds: dict[str, float | int]
    event_type_compatibility: dict[str, list[str]]
    cluster_constraints: dict[str, Any]
    merge_logic: str
    evidence_score_interpretation: str
    selection_split: str
    test_rows_accessed_for_selection: bool
    frozen_at: datetime
    library_versions: dict[str, str]
    policy: dict[str, Any]
    artifact_hash_scope: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_governance(self) -> EventGroupingDevelopmentArtifact:
        if self.artifact_kind != "DETERMINISTIC_CONFIGURATION_NOT_LEARNED_MODEL":
            raise ValueError("event artifact must not claim to be a learned model")
        if self.development_status != DEVELOPMENT_STATUS:
            raise ValueError("unexpected event development status")
        if self.production_validation != PRODUCTION_VALIDATION:
            raise ValueError("synthetic validation cannot claim production validation")
        if (
            self.selection_split != "validation"
            or self.test_rows_accessed_for_selection
        ):
            raise ValueError("event configuration must be selected on validation only")
        if self.frozen_at.tzinfo is None:
            raise ValueError("frozen_at must include a timezone")
        if (
            self.evidence_score_interpretation
            != "HEURISTIC_EVIDENCE_SCORE_NOT_PROBABILITY"
        ):
            raise ValueError(
                "event evidence score cannot be represented as probability"
            )
        if self.policy.get("network_access") is not False:
            raise ValueError("network_access must be false")
        for key in ("pretrained_models", "open_weight_models", "external_apis"):
            if self.policy.get(key) != []:
                raise ValueError(f"{key} must remain empty")
        expected = _artifact_payload_hash(self.model_dump(mode="json"))
        if self.artifact_hash != expected:
            raise ValueError("event artifact_hash does not match canonical payload")
        return self


@dataclass(frozen=True, slots=True)
class EventDatasetBinding:
    registry_path: Path
    pair_path: Path
    ground_truth_paths: dict[str, Path]
    detector_input_paths: dict[str, Path]
    manifest_path: Path
    quality_report_path: Path
    manifest: dict[str, Any]
    quality_report: SyntheticEventQualityReport
    registered_validation_sha256: str


@dataclass(frozen=True, slots=True)
class EventBatch:
    split: str
    batch_id: str
    scenario_family: str
    truth: tuple[SyntheticEventGroundTruth, ...]
    detector_inputs: tuple[SyntheticDetectorInput, ...]

    @property
    def report_count(self) -> int:
        return len(self.truth)


@dataclass(frozen=True, slots=True)
class PredictedBatch:
    clusters: tuple[frozenset[str], ...]
    candidates: tuple[EventCandidate, ...]
    candidate_comparisons: int
    grouping_seconds: float


def inspect_event_dataset_decision(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> dict[str, Any]:
    """Make the human-data versus synthetic-fallback decision explicit."""

    registry = load_dataset_registry(registry_path)
    human = [
        record
        for record in registry.entries
        if record.component is DatasetComponent.EVENT
        and record.human_adjudicated
        and record.status
        in {
            DatasetStatus.APPROVED_TRAINING,
            DatasetStatus.APPROVED_VALIDATION,
            DatasetStatus.APPROVED_TEST,
        }
    ]
    return {
        "approved_human_event_datasets": [
            f"{item.dataset_id}:{item.dataset_version}" for item in human
        ],
        "USE_IT": bool(human),
        "GENERATE_SYNTHETIC_EVENT_DATASET": not human,
        "selected_source": (
            "HUMAN_ADJUDICATED" if human else "PROJECT_AUTHORED_SYNTHETIC"
        ),
        "silent_switching_permitted": False,
        "production_validation": "NOT_VALIDATED"
        if not human
        else "SEPARATE_REVIEW_REQUIRED",
    }


def bind_synthetic_event_dataset(
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
) -> EventDatasetBinding:
    selected_registry = local_only_path(
        registry_path, description="dataset registries"
    ).resolve()
    registry = load_dataset_registry(selected_registry)
    record = find_dataset(registry, DEFAULT_DATASET_ID, DEFAULT_DATASET_VERSION)
    if record.component is not DatasetComponent.EVENT:
        raise EventValidationBlocked("EVENT_DATASET_COMPONENT_MISMATCH")
    if record.status is not DatasetStatus.VALID:
        raise EventValidationBlocked("SYNTHETIC_EVENT_DATASET_NOT_VALID")
    if record.data_classification is not DatasetClassification.DEVELOPMENT_ONLY:
        raise EventValidationBlocked("SYNTHETIC_EVENT_CLASSIFICATION_MISMATCH")
    if record.human_adjudicated:
        raise EventValidationBlocked("SYNTHETIC_EVENT_DATASET_CLAIMS_HUMAN_LABELS")
    metadata = record.metadata
    if metadata.get("production_validation") != PRODUCTION_VALIDATION:
        raise EventValidationBlocked("EVENT_DATASET_PRODUCTION_STATUS_INVALID")
    if metadata.get("random_row_split") is not False:
        raise EventValidationBlocked("EVENT_DATASET_RANDOM_ROW_SPLIT_DETECTED")
    if metadata.get("detector_used_for_labels") is not False:
        raise EventValidationBlocked("EVENT_LABEL_SOURCE_INVALID")
    pair_path = resolve_registry_path(record.local_path, selected_registry)
    if file_sha256(pair_path) != record.content_sha256:
        raise EventValidationBlocked("EVENT_PAIR_DATASET_HASH_MISMATCH")
    validation = load_bound_validation_report(record, selected_registry)
    if not validation.valid:
        raise EventValidationBlocked("REGISTERED_EVENT_VALIDATION_INVALID")
    manifest_path = resolve_registry_path(
        str(metadata.get("manifest_path", "")), selected_registry
    )
    quality_path = resolve_registry_path(
        str(metadata.get("quality_report_path", "")), selected_registry
    )
    if file_sha256(manifest_path) != metadata.get("manifest_sha256"):
        raise EventValidationBlocked("EVENT_DATASET_MANIFEST_HASH_MISMATCH")
    if file_sha256(quality_path) != metadata.get("quality_report_sha256"):
        raise EventValidationBlocked("EVENT_DATASET_QUALITY_HASH_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality = SyntheticEventQualityReport.model_validate_json(
        quality_path.read_text(encoding="utf-8")
    )
    if not quality.valid:
        raise EventValidationBlocked("EVENT_DATASET_QUALITY_INVALID")
    if manifest.get("dataset_sha256") != metadata.get("dataset_hash"):
        raise EventValidationBlocked("EVENT_DATASET_COMPOSITE_HASH_MISMATCH")
    if manifest.get("dataset_sha256") != quality.dataset_sha256:
        raise EventValidationBlocked("EVENT_DATASET_QUALITY_BINDING_MISMATCH")
    if manifest.get("split_sha256") != quality.split_sha256:
        raise EventValidationBlocked("EVENT_SPLIT_HASH_MISMATCH")
    ground_truth_paths = {
        split: resolve_registry_path(
            metadata["ground_truth_paths"][split], selected_registry
        )
        for split in SPLITS
    }
    detector_input_paths = {
        split: resolve_registry_path(
            metadata["detector_input_paths"][split], selected_registry
        )
        for split in SPLITS
    }
    for split in SPLITS:
        expected_truth = quality.file_hashes[f"ground_truth_{split}"]
        expected_input = quality.file_hashes[f"detector_inputs_{split}"]
        if file_sha256(ground_truth_paths[split]) != expected_truth:
            raise EventValidationBlocked(
                f"EVENT_GROUND_TRUTH_{split.upper()}_HASH_MISMATCH"
            )
        if file_sha256(detector_input_paths[split]) != expected_input:
            raise EventValidationBlocked(f"EVENT_INPUT_{split.upper()}_HASH_MISMATCH")
    return EventDatasetBinding(
        registry_path=selected_registry,
        pair_path=pair_path,
        ground_truth_paths=ground_truth_paths,
        detector_input_paths=detector_input_paths,
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        manifest=manifest,
        quality_report=quality,
        registered_validation_sha256=record.validation_report_sha256 or "",
    )


def load_event_split(
    binding: EventDatasetBinding,
    split: str,
) -> tuple[EventBatch, ...]:
    """Load exactly one physically separated split and re-check isolation."""

    if split not in SPLITS:
        raise EventValidationBlocked(f"UNKNOWN_EVENT_SPLIT:{split}")
    grouped_truth: defaultdict[str, list[SyntheticEventGroundTruth]] = defaultdict(list)
    grouped_inputs: defaultdict[str, list[SyntheticDetectorInput]] = defaultdict(list)
    batch_order: list[str] = []
    with (
        binding.ground_truth_paths[split].open("r", encoding="utf-8") as truth_handle,
        binding.detector_input_paths[split].open("r", encoding="utf-8") as input_handle,
    ):
        line_number = 0
        while True:
            truth_line = truth_handle.readline()
            input_line = input_handle.readline()
            if not truth_line and not input_line:
                break
            line_number += 1
            if not truth_line or not input_line:
                raise EventValidationBlocked("EVENT_TRUTH_INPUT_LENGTH_MISMATCH")
            truth = SyntheticEventGroundTruth.model_validate_json(truth_line)
            raw_input = json.loads(input_line)
            hidden = sorted(FORBIDDEN_DETECTOR_FIELDS.intersection(raw_input))
            if hidden:
                raise EventValidationBlocked(
                    "EVENT_GROUND_TRUTH_LEAKED_TO_DETECTOR:" + ",".join(hidden)
                )
            detector_input = SyntheticDetectorInput.model_validate(raw_input)
            if truth.split != split or truth.report_id != detector_input.report_id:
                raise EventValidationBlocked(
                    f"EVENT_SPLIT_ALIGNMENT_FAILED:{split}:{line_number}"
                )
            if truth.batch_id not in grouped_truth:
                batch_order.append(truth.batch_id)
            grouped_truth[truth.batch_id].append(truth)
            grouped_inputs[truth.batch_id].append(detector_input)
    batches: list[EventBatch] = []
    for batch_id in batch_order:
        truth = tuple(grouped_truth[batch_id])
        inputs = tuple(grouped_inputs[batch_id])
        scenarios = {item.scenario_family for item in truth}
        if len(scenarios) != 1 or len(truth) != len(inputs):
            raise EventValidationBlocked(f"EVENT_BATCH_INVALID:{batch_id}")
        batches.append(
            EventBatch(
                split=split,
                batch_id=batch_id,
                scenario_family=next(iter(scenarios)),
                truth=truth,
                detector_inputs=inputs,
            )
        )
    expected = binding.quality_report.split_report_counts[split]
    if sum(item.report_count for item in batches) != expected:
        raise EventValidationBlocked("EVENT_SPLIT_COUNT_CHANGED_AFTER_REGISTRATION")
    return tuple(batches)


def _observation_type(
    detector_input: SyntheticDetectorInput,
    config: EventDetectorConfig,
) -> str | None:
    prediction = detector_input.text_prediction
    if prediction.status is not PredictionStatus.AVAILABLE:
        return None
    if not prediction.probabilities:
        return prediction.label
    label, probability = max(
        prediction.probabilities.items(), key=lambda item: (float(item[1]), item[0])
    )
    return label if probability >= config.minimum_type_probability else None


def cluster_event_batch(
    batch: EventBatch,
    config: EventDetectorConfig,
    *,
    use_spatial: bool = True,
    use_temporal: bool = True,
    use_type: bool = True,
) -> tuple[frozenset[str], ...]:
    """Validation-only complete-link clustering used for search and ablation."""

    ordered = sorted(
        batch.detector_inputs,
        key=lambda item: (item.occurred_at.timestamp(), str(item.report_id)),
    )
    parent = list(range(len(ordered)))
    members = {index: {index} for index in range(len(ordered))}
    types = [_observation_type(item, config) for item in ordered]

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def compatible(left: int, right: int) -> bool:
        first, second = ordered[left], ordered[right]
        if use_temporal:
            delta = abs((second.occurred_at - first.occurred_at).total_seconds()) / 60.0
            if delta > config.temporal_window_minutes:
                return False
        if (
            use_spatial
            and haversine_km(
                first.latitude,
                first.longitude,
                second.latitude,
                second.longitude,
            )
            > config.spatial_radius_km
        ):
            return False
        return not use_type or event_types_compatible(types[left], types[right], config)

    def complete_link(left: int, right: int) -> bool:
        left_root, right_root = find(left), find(right)
        return all(
            compatible(left_member, right_member)
            for left_member in members[left_root]
            for right_member in members[right_root]
        )

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        members[left_root].update(members.pop(right_root))

    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if compatible(left, right) and complete_link(left, right):
                union(left, right)
    groups: defaultdict[int, set[str]] = defaultdict(set)
    for index, item in enumerate(ordered):
        groups[find(index)].add(str(item.report_id))
    return tuple(
        sorted(
            (frozenset(value) for value in groups.values()),
            key=lambda value: min(value),
        )
    )


def _true_clusters(batch: EventBatch) -> tuple[frozenset[str], ...]:
    grouped: defaultdict[str, set[str]] = defaultdict(set)
    for item in batch.truth:
        grouped[item.canonical_event_id].add(str(item.report_id))
    return tuple(
        sorted(
            (frozenset(value) for value in grouped.values()),
            key=lambda value: min(value),
        )
    )


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def calculate_grouping_metrics(
    batches: Sequence[EventBatch],
    predicted_clusters: Mapping[str, Sequence[frozenset[str]]],
) -> dict[str, Any]:
    """Calculate explicitly defined pairwise and exact-event metrics."""

    tp = tn = fp = fn = 0
    true_event_count = predicted_event_count = exact_events = 0
    exact_predicted = 0
    purity_numerator = completeness_numerator = 0
    report_count = 0
    absolute_batch_count_error = 0
    signed_batch_count_error = 0
    for batch in batches:
        truth = _true_clusters(batch)
        predicted = tuple(predicted_clusters[batch.batch_id])
        truth_index = {
            report_id: index
            for index, cluster in enumerate(truth)
            for report_id in cluster
        }
        predicted_index = {
            report_id: index
            for index, cluster in enumerate(predicted)
            for report_id in cluster
        }
        report_ids = sorted(truth_index)
        for left, right in combinations(report_ids, 2):
            same_truth = truth_index[left] == truth_index[right]
            same_prediction = predicted_index[left] == predicted_index[right]
            if same_truth and same_prediction:
                tp += 1
            elif not same_truth and not same_prediction:
                tn += 1
            elif not same_truth and same_prediction:
                fp += 1
            else:
                fn += 1
        true_sets, predicted_sets = set(truth), set(predicted)
        exact_events += len(true_sets & predicted_sets)
        exact_predicted += len(true_sets & predicted_sets)
        true_event_count += len(truth)
        predicted_event_count += len(predicted)
        signed = len(predicted) - len(truth)
        signed_batch_count_error += signed
        absolute_batch_count_error += abs(signed)
        for cluster in predicted:
            purity_numerator += max((len(cluster & item) for item in truth), default=0)
        for cluster in truth:
            completeness_numerator += max(
                (len(cluster & item) for item in predicted), default=0
            )
        report_count += len(report_ids)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    event_precision = _safe_ratio(exact_predicted, predicted_event_count)
    event_recall = _safe_ratio(exact_events, true_event_count)
    event_f1 = _safe_ratio(
        2 * event_precision * event_recall, event_precision + event_recall
    )
    return {
        "metric_definitions": {
            "event_match_precision": "same-canonical-event report pairs correctly grouped / all report pairs grouped together",
            "event_match_recall": "same-canonical-event report pairs correctly grouped / all same-canonical-event report pairs",
            "event_match_f1": "harmonic mean of event-match precision and recall",
            "false_merge_rate": "different-canonical-event pairs grouped together / all pairs grouped together",
            "false_split_rate": "same-canonical-event pairs separated / all same-canonical-event pairs",
            "event_count_error": "predicted event count minus canonical event count",
            "average_cluster_purity": "report-weighted majority canonical identity within predicted clusters",
            "average_cluster_completeness": "report-weighted largest recovered predicted fragment per canonical event",
            "event_level_precision": "exact canonical clusters recovered / predicted clusters",
            "event_level_recall": "exact canonical clusters recovered / canonical clusters",
        },
        "batch_count": len(batches),
        "report_count": report_count,
        "canonical_event_count": true_event_count,
        "predicted_event_count": predicted_event_count,
        "true_positive_pairs": tp,
        "true_negative_pairs": tn,
        "false_merge_pairs": fp,
        "false_split_pairs": fn,
        "event_matching_precision": _round(precision),
        "event_matching_recall": _round(recall),
        "event_matching_f1": _round(f1),
        "pairwise_precision": _round(precision),
        "pairwise_recall": _round(recall),
        "pairwise_f1": _round(f1),
        "false_merge_rate": _round(_safe_ratio(fp, tp + fp)),
        "false_split_rate": _round(_safe_ratio(fn, tp + fn)),
        "event_count_error": predicted_event_count - true_event_count,
        "normalized_event_count_error": _round(
            _safe_ratio(predicted_event_count - true_event_count, true_event_count)
        ),
        "mean_absolute_batch_event_count_error": _round(
            _safe_ratio(absolute_batch_count_error, len(batches))
        ),
        "mean_signed_batch_event_count_error": _round(
            _safe_ratio(signed_batch_count_error, len(batches))
        ),
        "average_cluster_purity": _round(_safe_ratio(purity_numerator, report_count)),
        "average_cluster_completeness": _round(
            _safe_ratio(completeness_numerator, report_count)
        ),
        "event_level_precision": _round(event_precision),
        "event_level_recall": _round(event_recall),
        "event_level_f1": _round(event_f1),
    }


def predict_batches(
    batches: Sequence[EventBatch],
    config: EventDetectorConfig,
    *,
    actual_detector: bool,
    use_spatial: bool = True,
    use_temporal: bool = True,
    use_type: bool = True,
) -> dict[str, PredictedBatch]:
    results: dict[str, PredictedBatch] = {}
    for batch in batches:
        if actual_detector:
            result = group_event_observations(
                [item.to_observation() for item in batch.detector_inputs],
                config=config,
            )
            clusters = tuple(
                frozenset(str(report_id) for report_id in candidate.report_ids)
                for candidate in result.candidates
            )
            results[batch.batch_id] = PredictedBatch(
                clusters=clusters,
                candidates=tuple(result.candidates),
                candidate_comparisons=result.candidate_comparisons,
                grouping_seconds=float(result.grouping_seconds or 0.0),
            )
        else:
            clusters = cluster_event_batch(
                batch,
                config,
                use_spatial=use_spatial,
                use_temporal=use_temporal,
                use_type=use_type,
            )
            results[batch.batch_id] = PredictedBatch(
                clusters=clusters,
                candidates=(),
                candidate_comparisons=0,
                grouping_seconds=0.0,
            )
    return results


def _metric_view(
    batches: Sequence[EventBatch], results: Mapping[str, PredictedBatch]
) -> dict[str, Any]:
    return calculate_grouping_metrics(
        batches, {key: value.clusters for key, value in results.items()}
    )


def select_event_thresholds(
    validation_batches: Sequence[EventBatch],
    *,
    spatial_radii_km: Sequence[float] = (3.0, 5.0, 8.0),
    temporal_windows_minutes: Sequence[float] = (90.0, 180.0, 300.0),
    minimum_type_probabilities: Sequence[float] = (0.35, 0.40, 0.60),
) -> dict[str, Any]:
    if not validation_batches or {item.split for item in validation_batches} != {
        "validation"
    }:
        raise EventValidationBlocked("THRESHOLD_SELECTION_REQUIRES_VALIDATION_SPLIT")
    candidates: list[dict[str, Any]] = []
    for spatial in spatial_radii_km:
        for temporal in temporal_windows_minutes:
            for type_probability in minimum_type_probabilities:
                config = EventDetectorConfig(
                    spatial_radius_km=spatial,
                    temporal_window_minutes=temporal,
                    minimum_reports=2,
                    minimum_type_probability=type_probability,
                )
                results = predict_batches(
                    validation_batches, config, actual_detector=False
                )
                metrics = _metric_view(validation_batches, results)
                candidates.append(
                    {
                        "spatial_radius_km": spatial,
                        "temporal_window_minutes": temporal,
                        "minimum_type_probability": type_probability,
                        "metrics": {
                            key: metrics[key]
                            for key in (
                                "event_matching_precision",
                                "event_matching_recall",
                                "event_matching_f1",
                                "false_merge_rate",
                                "false_split_rate",
                                "event_level_precision",
                                "event_level_recall",
                                "event_level_f1",
                                "normalized_event_count_error",
                            )
                        },
                    }
                )
    if not candidates:
        raise EventValidationBlocked("EVENT_THRESHOLD_SEARCH_EMPTY")
    candidates.sort(
        key=lambda item: (
            -item["metrics"]["event_matching_f1"],
            -item["metrics"]["event_level_f1"],
            item["metrics"]["false_merge_rate"],
            item["metrics"]["false_split_rate"],
            abs(item["metrics"]["normalized_event_count_error"]),
            item["spatial_radius_km"],
            item["temporal_window_minutes"],
            -item["minimum_type_probability"],
        )
    )
    selected = candidates[0]
    return {
        "search_version": "event-threshold-search-v1",
        "selection_split": "validation",
        "validation_report_count": sum(
            item.report_count for item in validation_batches
        ),
        "validation_batch_count": len(validation_batches),
        "objective": (
            "maximize pairwise F1, then exact-event F1; minimize false merges, "
            "false splits, and count error; prefer tighter gates"
        ),
        "selected": selected,
        "candidates": candidates,
        "minimum_independent_reports_frozen_not_tuned": 2,
        "cluster_constraint_frozen_not_tuned": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
        "merge_logic_frozen_not_tuned": "SPATIAL_AND_TEMPORAL_AND_TYPE_COMPATIBILITY",
        "test_rows_accessed_for_selection": False,
    }


def config_from_selection(selected: Mapping[str, Any]) -> EventDetectorConfig:
    return EventDetectorConfig(
        feature_version=FEATURE_VERSION,
        algorithm_version=ALGORITHM_VERSION,
        spatial_radius_km=float(selected["spatial_radius_km"]),
        temporal_window_minutes=float(selected["temporal_window_minutes"]),
        minimum_reports=2,
        minimum_type_probability=float(selected["minimum_type_probability"]),
    )


def run_validation_ablation(
    validation_batches: Sequence[EventBatch],
    config: EventDetectorConfig,
) -> dict[str, Any]:
    if not validation_batches or {item.split for item in validation_batches} != {
        "validation"
    }:
        raise EventValidationBlocked("ABLATION_REQUIRES_VALIDATION_SPLIT")
    definitions = (
        ("spatial only", True, False, False),
        ("temporal only", False, True, False),
        ("type compatibility only", False, False, True),
        ("spatial + temporal", True, True, False),
        ("spatial + type", True, False, True),
        ("temporal + type", False, True, True),
        ("full system", True, True, True),
    )
    rows: list[dict[str, Any]] = []
    for name, spatial, temporal, type_signal in definitions:
        results = predict_batches(
            validation_batches,
            config,
            actual_detector=False,
            use_spatial=spatial,
            use_temporal=temporal,
            use_type=type_signal,
        )
        metrics = _metric_view(validation_batches, results)
        rows.append(
            {
                "ablation": name,
                "signals": {
                    "spatial": spatial,
                    "temporal": temporal,
                    "type_compatibility": type_signal,
                },
                "metrics": {
                    key: metrics[key]
                    for key in (
                        "event_matching_precision",
                        "event_matching_recall",
                        "event_matching_f1",
                        "false_merge_rate",
                        "false_split_rate",
                        "event_level_f1",
                        "event_count_error",
                    )
                },
            }
        )
    return {
        "ablation_version": "event-grouping-ablation-v1",
        "selection_split": "validation",
        "ablations": rows,
        "test_rows_accessed": False,
    }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _distance_bin(value: float) -> str:
    if value <= 2.0:
        return "0-2_km"
    if value <= 5.0:
        return "2-5_km"
    if value <= 8.0:
        return "5-8_km"
    return "over_8_km"


def _time_bin(value: float) -> str:
    if value <= 30.0:
        return "0-30_minutes"
    if value <= 180.0:
        return "30-180_minutes"
    if value <= 300.0:
        return "180-300_minutes"
    return "over_300_minutes"


def _density_bin(value: float) -> str:
    if value == 0.0:
        return "zero"
    if value <= 0.25:
        return "low"
    if value <= 0.50:
        return "medium"
    return "high"


def _candidate_for_event(
    true_reports: frozenset[str],
    predicted: PredictedBatch,
) -> tuple[frozenset[str], EventCandidate | None]:
    best = max(
        predicted.clusters,
        key=lambda cluster: (len(cluster & true_reports), -len(cluster), min(cluster)),
    )
    candidate = next(
        (
            item
            for item in predicted.candidates
            if frozenset(str(report_id) for report_id in item.report_ids) == best
        ),
        None,
    )
    return best, candidate


def _failure_analysis(
    batches: Sequence[EventBatch],
    results: Mapping[str, PredictedBatch],
) -> dict[str, Any]:
    error_counts: Counter[str] = Counter()
    breakdowns: dict[str, defaultdict[str, Counter[str]]] = {
        error_type: defaultdict(Counter)
        for error_type in ("FALSE_MERGE", "FALSE_SPLIT", "WRONG_EVENT_TYPE")
    }
    examples: dict[str, list[dict[str, Any]]] = {
        error_type: []
        for error_type in ("FALSE_MERGE", "FALSE_SPLIT", "WRONG_EVENT_TYPE")
    }

    def record(
        error_type: str,
        *,
        batch: EventBatch,
        truth_items: Sequence[SyntheticEventGroundTruth],
        distance: float | None = None,
        time_minutes: float | None = None,
        predicted_type: str | None = None,
    ) -> None:
        error_counts[error_type] += 1
        true_types = sorted({item.event_type for item in truth_items})
        languages = sorted({item.language for item in truth_items})
        canonical_ids = sorted({item.canonical_event_id for item in truth_items})
        relevant = [
            item for item in batch.truth if item.canonical_event_id in canonical_ids
        ]
        source_diversity = len({item.source_family for item in relevant})
        duplicate_density = _safe_ratio(
            sum(item.duplicate_of_report_id is not None for item in relevant),
            len(relevant),
        )
        values = {
            "event_type": "+".join(true_types),
            "language": "+".join(languages),
            "distance": _distance_bin(distance)
            if distance is not None
            else "not_applicable",
            "time_separation": _time_bin(time_minutes)
            if time_minutes is not None
            else "not_applicable",
            "report_count": str(len(relevant)),
            "source_diversity": str(source_diversity),
            "duplicate_density": _density_bin(duplicate_density),
            "scenario_family": batch.scenario_family,
        }
        for key, value in values.items():
            breakdowns[error_type][key][value] += 1
        if len(examples[error_type]) < 100:
            examples[error_type].append(
                {
                    "batch_id": batch.batch_id,
                    "scenario_family": batch.scenario_family,
                    "canonical_event_ids": canonical_ids,
                    "report_ids": sorted(str(item.report_id) for item in truth_items),
                    "true_event_types": true_types,
                    "predicted_event_type": predicted_type,
                    "distance_km": _round(distance),
                    "time_separation_minutes": _round(time_minutes),
                    "language": languages,
                    "report_count": len(relevant),
                    "source_diversity": source_diversity,
                    "duplicate_density": _round(duplicate_density),
                }
            )

    for batch in batches:
        predicted = results[batch.batch_id]
        truth_by_report = {str(item.report_id): item for item in batch.truth}
        predicted_index = {
            report_id: index
            for index, cluster in enumerate(predicted.clusters)
            for report_id in cluster
        }
        for left, right in combinations(sorted(truth_by_report), 2):
            first, second = truth_by_report[left], truth_by_report[right]
            same_truth = first.canonical_event_id == second.canonical_event_id
            same_prediction = predicted_index[left] == predicted_index[right]
            if same_truth == same_prediction:
                continue
            distance = haversine_km(
                first.latitude, first.longitude, second.latitude, second.longitude
            )
            delta = abs((second.timestamp - first.timestamp).total_seconds()) / 60.0
            record(
                "FALSE_SPLIT" if same_truth else "FALSE_MERGE",
                batch=batch,
                truth_items=(first, second),
                distance=distance,
                time_minutes=delta,
            )
        by_event: defaultdict[str, list[SyntheticEventGroundTruth]] = defaultdict(list)
        for item in batch.truth:
            by_event[item.canonical_event_id].append(item)
        for truth_items in by_event.values():
            reports = frozenset(str(item.report_id) for item in truth_items)
            _, candidate = _candidate_for_event(reports, predicted)
            predicted_type = candidate.event_type if candidate is not None else None
            true_type = truth_items[0].event_type
            if predicted_type != true_type:
                record(
                    "WRONG_EVENT_TYPE",
                    batch=batch,
                    truth_items=truth_items,
                    predicted_type=predicted_type,
                )
    return {
        "analysis_version": "event-failure-analysis-v1",
        "error_counts": {
            name: error_counts[name]
            for name in ("FALSE_MERGE", "FALSE_SPLIT", "WRONG_EVENT_TYPE")
        },
        "breakdowns": {
            error_type: {
                dimension: dict(sorted(counter.items()))
                for dimension, counter in sorted(dimensions.items())
            }
            for error_type, dimensions in breakdowns.items()
        },
        "examples": examples,
        "example_cap_per_error_type": 100,
    }


def _event_type_results(
    batches: Sequence[EventBatch],
    results: Mapping[str, PredictedBatch],
) -> dict[str, Any]:
    confusion: defaultdict[str, Counter[str]] = defaultdict(Counter)
    by_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
    correct = evaluated = 0
    for batch in batches:
        predicted = results[batch.batch_id]
        by_event: defaultdict[str, list[SyntheticEventGroundTruth]] = defaultdict(list)
        for item in batch.truth:
            by_event[item.canonical_event_id].append(item)
        predicted_sets = set(predicted.clusters)
        for truth_items in by_event.values():
            truth_set = frozenset(str(item.report_id) for item in truth_items)
            best, candidate = _candidate_for_event(truth_set, predicted)
            true_type = truth_items[0].event_type
            predicted_type = candidate.event_type if candidate is not None else None
            predicted_label = predicted_type or "UNRESOLVED"
            confusion[true_type][predicted_label] += 1
            by_type[true_type]["canonical_events"] += 1
            by_type[true_type]["exactly_grouped_events"] += int(
                truth_set in predicted_sets
            )
            by_type[true_type]["fragmented_events"] += int(best != truth_set)
            evaluated += 1
            if predicted_type == true_type:
                correct += 1
                by_type[true_type]["correct_event_type"] += 1
    return {
        "separation_note": (
            "Event-type agreement compares controlled TextPrediction aggregation; "
            "grouping recovery is reported independently."
        ),
        "evaluated_canonical_events": evaluated,
        "event_type_agreement": _round(_safe_ratio(correct, evaluated)),
        "event_type_confusion": {
            true_type: dict(sorted(values.items()))
            for true_type, values in sorted(confusion.items())
        },
        "grouping_accuracy_by_event_type": {
            event_type: {
                "canonical_events": values["canonical_events"],
                "exactly_grouped_events": values["exactly_grouped_events"],
                "exact_grouping_recall": _round(
                    _safe_ratio(
                        values["exactly_grouped_events"], values["canonical_events"]
                    )
                ),
                "fragmented_events": values["fragmented_events"],
                "event_type_agreement": _round(
                    _safe_ratio(
                        values["correct_event_type"], values["canonical_events"]
                    )
                ),
            }
            for event_type, values in sorted(by_type.items())
        },
    }


def _latency_results(
    batches: Sequence[EventBatch],
    results: Mapping[str, PredictedBatch],
    minimum_reports: int,
) -> dict[str, Any]:
    first_candidate: list[float] = []
    stable_cluster: list[float] = []
    detection_delay: list[float] = []
    unresolved_minimum_evidence = 0
    for batch in batches:
        predicted = results[batch.batch_id]
        by_event: defaultdict[str, list[SyntheticEventGroundTruth]] = defaultdict(list)
        for item in batch.truth:
            by_event[item.canonical_event_id].append(item)
        for truth_items in by_event.values():
            ordered = sorted(
                truth_items, key=lambda item: (item.timestamp, str(item.report_id))
            )
            start = ordered[0].timestamp
            # A single observation is explicitly a candidate, never confirmation.
            first_candidate.append(0.0)
            true_ids = frozenset(str(item.report_id) for item in ordered)
            best, _ = _candidate_for_event(true_ids, predicted)
            recovered_times = [
                item.timestamp for item in ordered if str(item.report_id) in best
            ]
            stable_cluster.append(
                max((value - start).total_seconds() / 60.0 for value in recovered_times)
            )
            independent_seen = 0
            reached: float | None = None
            for item in ordered:
                if item.duplicate_of_report_id is None:
                    independent_seen += 1
                if independent_seen >= minimum_reports:
                    reached = (item.timestamp - start).total_seconds() / 60.0
                    break
            if reached is None:
                unresolved_minimum_evidence += 1
            else:
                detection_delay.append(reached)

    def summary(values: Sequence[float]) -> dict[str, float | int | None]:
        return {
            "count": len(values),
            "mean_minutes": _round(mean(values)) if values else None,
            "median_minutes": _round(median(values)) if values else None,
            "p95_minutes": _round(_percentile(values, 0.95)),
            "max_minutes": _round(max(values)) if values else None,
        }

    return {
        "latency_scope": "ORDERED_SYNTHETIC_EVENT_STREAM_NOT_OPERATIONAL_LATENCY",
        "definitions": {
            "time_to_first_event_candidate": "minutes from first canonical report to the first one-report CANDIDATE",
            "time_to_stable_cluster": "minutes from first canonical report until the final recovered cluster membership is present",
            "detection_delay": "minutes from first canonical report until configured minimum independent evidence is present",
        },
        "time_to_first_event_candidate": summary(first_candidate),
        "time_to_stable_cluster": summary(stable_cluster),
        "detection_delay": summary(detection_delay),
        "events_without_minimum_independent_evidence": unresolved_minimum_evidence,
    }


def _special_case_results(
    batches: Sequence[EventBatch],
    results: Mapping[str, PredictedBatch],
    config: EventDetectorConfig,
) -> dict[str, Any]:
    chain_batches = elongated_batches = single_events = duplicate_events = 0
    chain_all_merged = chain_expected_partition = elongated_recovered = 0
    single_candidate = single_confirmed = 0
    independent_inflation = source_inflation = evidence_inflation = 0
    duplicate_details: list[dict[str, Any]] = []
    for batch in batches:
        predicted = results[batch.batch_id]
        true_clusters = _true_clusters(batch)
        predicted_sets = set(predicted.clusters)
        if batch.scenario_family == "H_CHAIN_BRIDGE":
            chain_batches += 1
            chain_all_merged += int(
                any(len(item) == batch.report_count for item in predicted.clusters)
            )
            chain_expected_partition += int(set(true_clusters) == predicted_sets)
        if batch.scenario_family == "K_LEGITIMATE_ELONGATED_EVENT":
            elongated_batches += 1
            elongated_recovered += int(set(true_clusters) == predicted_sets)
        if batch.scenario_family == "J_SINGLE_REPORT_EVENT_CANDIDATE":
            for true_cluster in true_clusters:
                if len(true_cluster) != 1:
                    continue
                single_events += 1
                _, candidate = _candidate_for_event(true_cluster, predicted)
                if (
                    candidate is not None
                    and candidate.status is EventLifecycleStatus.CANDIDATE
                ):
                    single_candidate += 1
                if (
                    candidate is not None
                    and candidate.status is EventLifecycleStatus.CONFIRMED
                ):
                    single_confirmed += 1
        if batch.scenario_family == "E_DUPLICATE_REPORTS_WITHIN_EVENT":
            duplicate_events += 1
            true_cluster = true_clusters[0]
            _, candidate = _candidate_for_event(true_cluster, predicted)
            heads = [
                (truth, detector_input)
                for truth, detector_input in zip(batch.truth, batch.detector_inputs)
                if truth.duplicate_of_report_id is None
            ]
            expected_independent = len(heads)
            expected_sources = len({truth.source_family for truth, _ in heads})
            counterfactual = build_event_candidate(
                [item.to_observation() for _, item in heads], config=config
            )
            if candidate is None:
                independent_inflation += 1
                source_inflation += 1
                evidence_inflation += 1
                continue
            independent_inflation += int(
                candidate.independent_report_count > expected_independent
            )
            source_inflation += int(candidate.unique_source_count > expected_sources)
            evidence_inflation += int(
                float(candidate.event_confidence or 0.0)
                > float(counterfactual.event_confidence or 0.0) + 1e-12
            )
            if len(duplicate_details) < 20:
                duplicate_details.append(
                    {
                        "batch_id": batch.batch_id,
                        "report_count": candidate.report_count,
                        "expected_independent_report_count": expected_independent,
                        "actual_independent_report_count": candidate.independent_report_count,
                        "expected_source_diversity": expected_sources,
                        "actual_source_diversity": candidate.unique_source_count,
                        "candidate_evidence_score": candidate.event_confidence,
                        "counterfactual_without_duplicate_copies": counterfactual.event_confidence,
                    }
                )
    return {
        "chain_bridge": {
            "batch_count": chain_batches,
            "all_reports_in_one_event_count": chain_all_merged,
            "not_all_one_event_rate": _round(
                _safe_ratio(chain_batches - chain_all_merged, chain_batches)
            ),
            "expected_partition_recovery_rate": _round(
                _safe_ratio(chain_expected_partition, chain_batches)
            ),
            "constraint": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
        },
        "legitimate_elongated_event": {
            "batch_count": elongated_batches,
            "exact_recovery_rate": _round(
                _safe_ratio(elongated_recovered, elongated_batches)
            ),
        },
        "single_report_event": {
            "event_count": single_events,
            "candidate_count": single_candidate,
            "candidate_rate": _round(_safe_ratio(single_candidate, single_events)),
            "confirmed_count": single_confirmed,
            "required_lifecycle": "CANDIDATE",
            "automatic_confirmation_permitted": False,
        },
        "duplicate_interaction": {
            "event_count": duplicate_events,
            "independent_report_inflation_violations": independent_inflation,
            "source_diversity_inflation_violations": source_inflation,
            "event_evidence_inflation_violations": evidence_inflation,
            "duplicate_model_invoked": False,
            "relationship_source": "PROJECT_GENERATED_RELATIONSHIPS",
            "sample_details": duplicate_details,
        },
    }


def evaluate_event_configuration(
    batches: Sequence[EventBatch],
    config: EventDetectorConfig,
) -> dict[str, Any]:
    """Run the frozen detector and report grouping/type/latency separately."""

    if not batches:
        raise EventValidationBlocked("EVENT_EVALUATION_REQUIRES_BATCHES")
    started = perf_counter()
    results = predict_batches(batches, config, actual_detector=True)
    wall_seconds = perf_counter() - started
    lightweight = predict_batches(batches, config, actual_detector=False)
    parity_failures = [
        batch.batch_id
        for batch in batches
        if set(results[batch.batch_id].clusters)
        != set(lightweight[batch.batch_id].clusters)
    ]
    if parity_failures:
        raise EventValidationBlocked(
            "VALIDATION_CLUSTER_IMPLEMENTATION_PARITY_FAILED:" + parity_failures[0]
        )
    overall = _metric_view(batches, results)
    by_scenario: dict[str, Any] = {}
    for scenario in EVENT_SCENARIOS:
        selected = [item for item in batches if item.scenario_family == scenario]
        if selected:
            by_scenario[scenario] = _metric_view(selected, results)
    event_type = _event_type_results(batches, results)
    latency = _latency_results(batches, results, config.minimum_reports)
    special = _special_case_results(batches, results, config)
    failures = _failure_analysis(batches, results)
    metrics = {
        "evaluation_version": "event-grouping-evaluation-v1",
        "evaluation_split": batches[0].split,
        "development_status": DEVELOPMENT_STATUS,
        "production_validation": PRODUCTION_VALIDATION,
        "configuration": {
            "spatial_radius_km": config.spatial_radius_km,
            "temporal_window_minutes": config.temporal_window_minutes,
            "minimum_type_probability": config.minimum_type_probability,
            "minimum_independent_reports": config.minimum_reports,
            "feature_version": config.feature_version,
            "algorithm_version": config.algorithm_version,
            "cluster_constraint": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
            "merge_logic": "SPATIAL_AND_TEMPORAL_AND_TYPE_COMPATIBILITY",
        },
        "grouping_metrics": overall,
        "grouping_metrics_by_scenario": by_scenario,
        "event_type_results": event_type,
        "latency_results": latency,
        "special_case_results": special,
        "controlled_text_predictions": True,
        "frozen_nlp_model_invoked": False,
        "duplicate_matcher_invoked": False,
        "detector_parity": {
            "status": "PASS",
            "validation_only_clusterer_matches_detector": True,
            "failure_count": 0,
        },
        "policy": {
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        },
    }
    performance = {
        "benchmark_scope": "LOCAL_SYNTHETIC_GROUPING_EXECUTION_NOT_OPERATIONAL_LATENCY",
        "batch_count": len(batches),
        "report_count": sum(item.report_count for item in batches),
        "candidate_comparisons": sum(
            item.candidate_comparisons for item in results.values()
        ),
        "detector_reported_grouping_seconds": _round(
            sum(item.grouping_seconds for item in results.values())
        ),
        "evaluation_wall_seconds": _round(wall_seconds),
        "reports_per_wall_second": _round(
            _safe_ratio(sum(item.report_count for item in batches), wall_seconds)
        ),
        "operational_latency_claimed": False,
    }
    return {
        "metrics": metrics,
        "error_report": failures,
        "performance": performance,
    }


def _framework_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pydantic": pydantic.__version__,
    }


def protected_artifact_snapshot(
    artifact_root: Path | str = ARTIFACT_ROOT,
) -> dict[str, str]:
    root = local_only_path(
        artifact_root, description="ML artifact directories"
    ).resolve()
    snapshot: dict[str, str] = {}
    for name, expected in EXPECTED_PROTECTED_HASHES.items():
        path = root / name
        if not path.is_file():
            raise EventValidationBlocked(f"PROTECTED_ARTIFACT_MISSING:{name}")
        actual = file_sha256(path)
        if actual != expected:
            raise EventValidationBlocked(f"PROTECTED_ARTIFACT_CHANGED:{name}")
        snapshot[name] = actual
    for path in sorted(root.glob("nlp_classifier_v3*.json")):
        snapshot[path.name] = file_sha256(path)
    if not any(name.startswith("nlp_classifier_v3") for name in snapshot):
        raise EventValidationBlocked("NLP_V3_PROTECTION_SNAPSHOT_EMPTY")
    return snapshot


def _write_json_atomic(
    payload: Any,
    path: Path,
    *,
    exclusive: bool = False,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    if exclusive:
        with path.open("xb") as handle:
            handle.write(encoded)
        return file_sha256(path)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    temporary.replace(path)
    return file_sha256(path)


def _phase20_paths(output_directory: Path | str) -> dict[str, Path]:
    root = local_only_path(
        output_directory, description="Phase 20 output directories"
    ).resolve()
    return {
        "root": root,
        "artifact": root / DEFAULT_EVENT_ARTIFACT_PATH.name,
        "development_manifest": root / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "threshold_search": root / DEFAULT_THRESHOLD_SEARCH_PATH.name,
        "ablation": root / DEFAULT_ABLATION_PATH.name,
        "validation_metrics": root / DEFAULT_VALIDATION_METRICS_PATH.name,
        "validation_errors": root / DEFAULT_VALIDATION_ERRORS_PATH.name,
        "performance": root / DEFAULT_PERFORMANCE_PATH.name,
        "golden": root / DEFAULT_GOLDEN_PATH.name,
        "final_metrics": root / DEFAULT_FINAL_METRICS_PATH.name,
        "error_report": root / DEFAULT_ERROR_REPORT_PATH.name,
        "receipt": root / DEFAULT_FINAL_RECEIPT_PATH.name,
    }


def _append_event_artifact_manifest(
    *,
    artifact_path: Path,
    artifact: EventGroupingDevelopmentArtifact,
    manifest_path: Path | str,
) -> str:
    selected_manifest = local_only_path(
        manifest_path, description="artifact manifests"
    ).resolve()
    manifest = ArtifactManifest.model_validate_json(
        selected_manifest.read_text(encoding="utf-8")
    )
    if any(item.artifact_name == artifact_path.name for item in manifest.artifacts):
        raise EventValidationBlocked("EVENT_ARTIFACT_ALREADY_REGISTERED")
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=artifact.artifact_version,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=artifact.dataset_sha256,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        training_timestamp=artifact.frozen_at,
        random_seed=artifact.random_seed,
        framework_versions=artifact.library_versions,
        intended_component="event_detector",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    updated = manifest.model_copy(update={"artifacts": [*manifest.artifacts, metadata]})
    return _write_json_atomic(updated.model_dump(mode="json"), selected_manifest)


def load_event_development_artifact(
    artifact_path: Path | str = DEFAULT_EVENT_ARTIFACT_PATH,
    *,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> tuple[EventGroupingDevelopmentArtifact, EventDetectorConfig]:
    selected_artifact = local_only_path(
        artifact_path, description="event configuration artifacts"
    ).resolve()
    artifact = EventGroupingDevelopmentArtifact.model_validate_json(
        selected_artifact.read_text(encoding="utf-8")
    )
    manifest = ArtifactManifest.model_validate_json(
        local_only_path(
            artifact_manifest_path, description="artifact manifests"
        ).read_text(encoding="utf-8")
    )
    entries = [
        item
        for item in manifest.artifacts
        if item.artifact_name == selected_artifact.name
        and item.intended_component == "event_detector"
    ]
    if len(entries) != 1:
        raise EventValidationBlocked("EVENT_ARTIFACT_MANIFEST_ENTRY_MISSING")
    metadata = entries[0]
    if metadata.sha256 != file_sha256(selected_artifact):
        raise EventValidationBlocked("EVENT_ARTIFACT_FILE_HASH_MISMATCH")
    if metadata.training_dataset_hash != artifact.dataset_sha256:
        raise EventValidationBlocked("EVENT_ARTIFACT_DATASET_HASH_MISMATCH")
    config = EventDetectorConfig(
        feature_version=artifact.feature_version,
        algorithm_version=artifact.algorithm_version,
        spatial_radius_km=float(artifact.thresholds["spatial_radius_km"]),
        temporal_window_minutes=float(artifact.thresholds["temporal_window_minutes"]),
        minimum_reports=int(artifact.thresholds["minimum_independent_reports"]),
        minimum_type_probability=float(artifact.thresholds["minimum_type_probability"]),
        compatible_event_type_rules={
            key: tuple(values)
            for key, values in artifact.event_type_compatibility.items()
        },
    )
    return artifact, config


def _artifact_payload(
    binding: EventDatasetBinding,
    config: EventDetectorConfig,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_version": ARTIFACT_VERSION,
        "artifact_kind": "DETERMINISTIC_CONFIGURATION_NOT_LEARNED_MODEL",
        "development_status": DEVELOPMENT_STATUS,
        "production_validation": PRODUCTION_VALIDATION,
        "dataset_id": binding.manifest["dataset_id"],
        "dataset_version": binding.manifest["dataset_version"],
        "dataset_sha256": binding.quality_report.dataset_sha256,
        "split_sha256": binding.quality_report.split_sha256,
        "dataset_manifest_sha256": file_sha256(binding.manifest_path),
        "generator_version": binding.quality_report.generator_version,
        "scenario_version": binding.quality_report.scenario_version,
        "random_seed": binding.quality_report.seed,
        "feature_version": config.feature_version,
        "algorithm_version": config.algorithm_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "thresholds": {
            "spatial_radius_km": config.spatial_radius_km,
            "temporal_window_minutes": config.temporal_window_minutes,
            "minimum_type_probability": config.minimum_type_probability,
            "minimum_independent_reports": config.minimum_reports,
        },
        "event_type_compatibility": {
            key: list(values)
            for key, values in sorted(config.compatible_event_type_rules.items())
        },
        "cluster_constraints": {
            "method": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
            "spatial_span_limit_km": config.spatial_radius_km,
            "temporal_span_limit_minutes": config.temporal_window_minutes,
            "type_compatibility_required_for_every_member_pair": True,
            "transitive_bridge_merge_permitted": False,
        },
        "merge_logic": "SPATIAL_AND_TEMPORAL_AND_TYPE_COMPATIBILITY",
        "evidence_score_interpretation": "HEURISTIC_EVIDENCE_SCORE_NOT_PROBABILITY",
        "selection_split": "validation",
        "test_rows_accessed_for_selection": False,
        "frozen_at": FREEZE_TIMESTAMP.isoformat().replace("+00:00", "Z"),
        "library_versions": _framework_versions(),
        "policy": {
            "learned_model_created": False,
            "duplicate_model_modified": False,
            "nlp_model_modified": False,
            "live_backend_modified": False,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "runtime_downloads": False,
        },
        "artifact_hash_scope": "CANONICAL_JSON_EXCLUDING_ARTIFACT_HASH",
    }
    payload["artifact_hash"] = _artifact_payload_hash(payload)
    return payload


def _assert_special_cases(metrics: Mapping[str, Any]) -> None:
    special = metrics["special_case_results"]
    if special["chain_bridge"]["all_reports_in_one_event_count"] != 0:
        raise EventValidationBlocked("CHAIN_BRIDGE_SAFEGUARD_FAILED")
    if special["legitimate_elongated_event"]["exact_recovery_rate"] != 1.0:
        raise EventValidationBlocked("ELONGATED_EVENT_RECOVERY_FAILED")
    if special["single_report_event"]["confirmed_count"] != 0:
        raise EventValidationBlocked("SINGLE_REPORT_AUTOMATICALLY_CONFIRMED")
    if special["single_report_event"]["candidate_rate"] != 1.0:
        raise EventValidationBlocked("SINGLE_REPORT_CANDIDATE_FAILED")
    duplicate = special["duplicate_interaction"]
    if any(
        duplicate[key] != 0
        for key in (
            "independent_report_inflation_violations",
            "source_diversity_inflation_violations",
            "event_evidence_inflation_violations",
        )
    ):
        raise EventValidationBlocked("DUPLICATE_EVIDENCE_INFLATION_DETECTED")


def freeze_event_grouping_development(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Select on validation only and freeze the non-learned configuration."""

    paths = _phase20_paths(output_directory)
    paths["root"].mkdir(parents=True, exist_ok=True)
    if paths["receipt"].exists():
        raise EventValidationBlocked("FINAL_TEST_ALREADY_LOCKED")
    freeze_targets = [
        paths[key]
        for key in (
            "artifact",
            "development_manifest",
            "threshold_search",
            "ablation",
            "validation_metrics",
            "validation_errors",
            "performance",
            "golden",
        )
    ]
    existing = [path.name for path in freeze_targets if path.exists()]
    if existing:
        raise EventValidationBlocked(
            "PHASE20_FREEZE_OUTPUT_ALREADY_EXISTS:" + ",".join(existing)
        )
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    decision = inspect_event_dataset_decision(registry_path)
    if decision["USE_IT"]:
        raise EventValidationBlocked("APPROVED_HUMAN_EVENT_DATA_REQUIRES_SEPARATE_PLAN")
    binding = bind_synthetic_event_dataset(registry_path)
    validation_batches = load_event_split(binding, "validation")
    search = select_event_thresholds(validation_batches)
    config = config_from_selection(search["selected"])
    ablation = run_validation_ablation(validation_batches, config)
    evaluation = evaluate_event_configuration(validation_batches, config)
    _assert_special_cases(evaluation["metrics"])

    artifact_payload = _artifact_payload(binding, config)
    artifact = EventGroupingDevelopmentArtifact.model_validate(artifact_payload)
    artifact_file_hash = _write_json_atomic(artifact_payload, paths["artifact"])
    threshold_hash = _write_json_atomic(search, paths["threshold_search"])
    ablation_hash = _write_json_atomic(ablation, paths["ablation"])
    validation_metrics_hash = _write_json_atomic(
        evaluation["metrics"], paths["validation_metrics"]
    )
    validation_errors_hash = _write_json_atomic(
        evaluation["error_report"], paths["validation_errors"]
    )
    performance_hash = _write_json_atomic(
        evaluation["performance"], paths["performance"]
    )
    golden = {
        "golden_version": "event-grouping-v1-golden",
        "configuration_artifact_hash": artifact.artifact_hash,
        "validation_grouping_metrics_sha256": _sha256_payload(
            evaluation["metrics"]["grouping_metrics"]
        ),
        "selected_configuration": artifact.thresholds,
        "expected_chain_all_merged_count": 0,
        "expected_elongated_recovery_rate": 1.0,
        "expected_single_confirmed_count": 0,
        "expected_duplicate_inflation_violations": 0,
        "production_validation": PRODUCTION_VALIDATION,
    }
    golden_hash = _write_json_atomic(golden, paths["golden"])
    artifact_manifest_hash = _append_event_artifact_manifest(
        artifact_path=paths["artifact"],
        artifact=artifact,
        manifest_path=artifact_manifest_path,
    )
    protected_after = protected_artifact_snapshot(ARTIFACT_ROOT)
    if protected_after != protected_before:
        raise EventValidationBlocked("PROTECTED_MODELS_MODIFIED_DURING_EVENT_FREEZE")
    frozen_files = {
        paths["artifact"].name: artifact_file_hash,
        paths["threshold_search"].name: threshold_hash,
        paths["ablation"].name: ablation_hash,
        paths["validation_metrics"].name: validation_metrics_hash,
        paths["validation_errors"].name: validation_errors_hash,
        paths["performance"].name: performance_hash,
        paths["golden"].name: golden_hash,
    }
    development_manifest = {
        "manifest_version": "event-grouping-development-manifest-v1",
        "status": "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED",
        "frozen_at": FREEZE_TIMESTAMP.isoformat(),
        "dataset_id": artifact.dataset_id,
        "dataset_version": artifact.dataset_version,
        "dataset_sha256": artifact.dataset_sha256,
        "split_sha256": artifact.split_sha256,
        "dataset_manifest_sha256": artifact.dataset_manifest_sha256,
        "registered_validation_sha256": binding.registered_validation_sha256,
        "dataset_decision": decision,
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "random_seed": artifact.random_seed,
        "selected_configuration": artifact.thresholds,
        "feature_version": artifact.feature_version,
        "algorithm_version": artifact.algorithm_version,
        "cluster_constraints": artifact.cluster_constraints,
        "merge_logic": artifact.merge_logic,
        "minimum_evidence": artifact.thresholds["minimum_independent_reports"],
        "selection_split": "validation",
        "validation_report_count": sum(
            item.report_count for item in validation_batches
        ),
        "test_rows_accessed": False,
        "test_evaluation_invocation_count": 0,
        "frozen_files": frozen_files,
        "shared_artifact_manifest_sha256": artifact_manifest_hash,
        "protected_artifact_hashes": protected_after,
        "production_validation": PRODUCTION_VALIDATION,
        "policy": artifact.policy,
    }
    development_manifest_hash = _write_json_atomic(
        development_manifest, paths["development_manifest"]
    )
    loaded, loaded_config = load_event_development_artifact(
        paths["artifact"], artifact_manifest_path=artifact_manifest_path
    )
    if loaded.artifact_hash != artifact.artifact_hash or loaded_config != config:
        raise EventValidationBlocked("FROZEN_EVENT_ARTIFACT_LOAD_CHECK_FAILED")
    return {
        "status": "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED",
        "artifact_path": str(paths["artifact"]),
        "artifact_file_sha256": artifact_file_hash,
        "artifact_hash": artifact.artifact_hash,
        "development_manifest_path": str(paths["development_manifest"]),
        "development_manifest_sha256": development_manifest_hash,
        "dataset_sha256": artifact.dataset_sha256,
        "selected_configuration": artifact.thresholds,
        "validation_metrics": evaluation["metrics"]["grouping_metrics"],
        "test_rows_accessed": False,
        "production_validation": PRODUCTION_VALIDATION,
    }


def _verify_frozen_development(
    paths: Mapping[str, Path],
    artifact_manifest_path: Path | str,
) -> tuple[dict[str, Any], EventGroupingDevelopmentArtifact, EventDetectorConfig]:
    manifest = json.loads(paths["development_manifest"].read_text(encoding="utf-8"))
    if manifest.get("status") != "CONFIGURATION_FROZEN_TEST_NOT_ACCESSED":
        raise EventValidationBlocked("EVENT_DEVELOPMENT_MANIFEST_STATUS_INVALID")
    for name, expected_hash in manifest.get("frozen_files", {}).items():
        path = paths["root"] / name
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise EventValidationBlocked(f"FROZEN_EVENT_FILE_CHANGED:{name}")
    selected_manifest = local_only_path(
        artifact_manifest_path, description="artifact manifests"
    ).resolve()
    if file_sha256(selected_manifest) != manifest.get(
        "shared_artifact_manifest_sha256"
    ):
        raise EventValidationBlocked("ARTIFACT_MANIFEST_CHANGED_AFTER_EVENT_FREEZE")
    protected = protected_artifact_snapshot(ARTIFACT_ROOT)
    if protected != manifest.get("protected_artifact_hashes"):
        raise EventValidationBlocked("PROTECTED_MODELS_CHANGED_AFTER_EVENT_FREEZE")
    artifact, config = load_event_development_artifact(
        paths["artifact"], artifact_manifest_path=selected_manifest
    )
    return manifest, artifact, config


def finalize_event_grouping_evaluation(
    *,
    registry_path: Path | str = DEFAULT_DATASET_REGISTRY_PATH,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Consume the synthetic test split exactly once after configuration freeze."""

    paths = _phase20_paths(output_directory)
    if paths["receipt"].exists():
        raise RuntimeError(
            "event grouping final reevaluation is prohibited by the one-shot receipt"
        )
    development, artifact, config = _verify_frozen_development(
        paths, artifact_manifest_path
    )
    claim = {
        "receipt_version": "event-grouping-final-test-receipt-v1",
        "status": "FINAL_EVALUATION_IN_PROGRESS",
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
        "claimed_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
        "artifact_hash": artifact.artifact_hash,
        "dataset_sha256": artifact.dataset_sha256,
        "production_validation": PRODUCTION_VALIDATION,
    }
    _write_json_atomic(claim, paths["receipt"], exclusive=True)
    try:
        binding = bind_synthetic_event_dataset(registry_path)
        if binding.quality_report.dataset_sha256 != artifact.dataset_sha256:
            raise EventValidationBlocked("FINAL_TEST_DATASET_HASH_MISMATCH")
        test_batches = load_event_split(binding, "test")
        evaluation = evaluate_event_configuration(test_batches, config)
        _assert_special_cases(evaluation["metrics"])
        protected_after = protected_artifact_snapshot(ARTIFACT_ROOT)
        if protected_after != development["protected_artifact_hashes"]:
            raise EventValidationBlocked("PROTECTED_MODELS_MODIFIED_DURING_FINAL_TEST")
        final_metrics = {
            **evaluation["metrics"],
            "final_test": True,
            "final_test_invocation_count": 1,
            "configuration_frozen_before_test": True,
            "test_used_for_tuning": False,
            "artifact_hash": artifact.artifact_hash,
            "artifact_file_sha256": file_sha256(paths["artifact"]),
            "dataset_sha256": artifact.dataset_sha256,
            "split_sha256": artifact.split_sha256,
            "evaluated_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
        }
        final_metrics_hash = _write_json_atomic(final_metrics, paths["final_metrics"])
        error_report = {
            **evaluation["error_report"],
            "evaluation_split": "test",
            "artifact_hash": artifact.artifact_hash,
            "dataset_sha256": artifact.dataset_sha256,
            "production_validation": PRODUCTION_VALIDATION,
        }
        error_report_hash = _write_json_atomic(error_report, paths["error_report"])
        receipt = {
            "receipt_version": "event-grouping-final-test-receipt-v1",
            "status": "FINAL_EVALUATION_COMPLETE",
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "evaluated_at": FINAL_EVALUATION_TIMESTAMP.isoformat(),
            "dataset_id": artifact.dataset_id,
            "dataset_version": artifact.dataset_version,
            "dataset_sha256": artifact.dataset_sha256,
            "split_sha256": artifact.split_sha256,
            "test_ground_truth_sha256": binding.quality_report.file_hashes[
                "ground_truth_test"
            ],
            "test_detector_inputs_sha256": binding.quality_report.file_hashes[
                "detector_inputs_test"
            ],
            "test_report_count": sum(item.report_count for item in test_batches),
            "test_canonical_event_count": binding.quality_report.split_event_counts[
                "test"
            ],
            "artifact_hash": artifact.artifact_hash,
            "artifact_file_sha256": file_sha256(paths["artifact"]),
            "development_manifest_sha256": file_sha256(paths["development_manifest"]),
            "final_metrics_file": paths["final_metrics"].name,
            "final_metrics_sha256": final_metrics_hash,
            "error_report_file": paths["error_report"].name,
            "error_report_sha256": error_report_hash,
            "frozen_configuration": artifact.thresholds,
            "frozen_cluster_constraints": artifact.cluster_constraints,
            "frozen_merge_logic": artifact.merge_logic,
            "configuration_frozen_before_test": True,
            "test_used_for_tuning": False,
            "production_validation": PRODUCTION_VALIDATION,
            "duplicate_model_modified": False,
            "nlp_model_modified": False,
            "live_backend_modified": False,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        }
        _write_json_atomic(receipt, paths["receipt"])
        return receipt
    except Exception as error:
        failed_receipt = {
            **claim,
            "status": "FINAL_EVALUATION_FAILED_LOCKED",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_type": type(error).__name__,
            "failure": str(error),
        }
        _write_json_atomic(failed_receipt, paths["receipt"])
        raise


__all__ = [
    "ALGORITHM_VERSION",
    "ARTIFACT_ROOT",
    "ARTIFACT_VERSION",
    "DEFAULT_ABLATION_PATH",
    "DEFAULT_ARTIFACT_MANIFEST_PATH",
    "DEFAULT_DEVELOPMENT_MANIFEST_PATH",
    "DEFAULT_ERROR_REPORT_PATH",
    "DEFAULT_EVENT_ARTIFACT_PATH",
    "DEFAULT_FINAL_METRICS_PATH",
    "DEFAULT_FINAL_RECEIPT_PATH",
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_PERFORMANCE_PATH",
    "DEFAULT_THRESHOLD_SEARCH_PATH",
    "DEFAULT_VALIDATION_ERRORS_PATH",
    "DEFAULT_VALIDATION_METRICS_PATH",
    "DEVELOPMENT_STATUS",
    "FEATURE_VERSION",
    "PRODUCTION_VALIDATION",
    "EventBatch",
    "EventDatasetBinding",
    "EventGroupingDevelopmentArtifact",
    "EventValidationBlocked",
    "bind_synthetic_event_dataset",
    "calculate_grouping_metrics",
    "cluster_event_batch",
    "config_from_selection",
    "evaluate_event_configuration",
    "finalize_event_grouping_evaluation",
    "freeze_event_grouping_development",
    "inspect_event_dataset_decision",
    "load_event_development_artifact",
    "load_event_split",
    "predict_batches",
    "protected_artifact_snapshot",
    "run_validation_ablation",
    "select_event_thresholds",
]
