"""Metric interfaces that refuse to imply production validity without labels."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ml.contracts import AnomalyDomain, AnomalyPrediction
from app.ml.data.anomaly_annotations import (
    AnomalyAnnotation,
    AnomalyAnnotationLabel,
)
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord

MetricFamily = Literal[
    "classification",
    "binary_credibility",
    "duplicate_matching",
    "event_detection",
    "image",
    "anomaly",
]

EvaluationStatus = Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE", "INSUFFICIENT_DATA"]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    metric_family: MetricFamily
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DuplicateThresholdMetrics(BaseModel):
    threshold: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    false_negative_rate: float
    confusion_matrix: dict[str, int]


class DuplicateEvaluationReport(BaseModel):
    component: str = "duplicate_matcher"
    evaluation_status: EvaluationStatus
    number_labeled_pairs: int = Field(default=0, ge=0)
    number_duplicate: int = Field(default=0, ge=0)
    number_not_duplicate: int = Field(default=0, ge=0)
    number_uncertain: int = Field(default=0, ge=0)
    excluded_uncertain_pairs: int = Field(default=0, ge=0)
    duplicate_prevalence: float | None = Field(default=None, ge=0.0, le=1.0)
    group_counts: dict[str, int] = Field(default_factory=dict)
    train_count: int = Field(default=0, ge=0)
    validation_count: int = Field(default=0, ge=0)
    test_count: int = Field(default=0, ge=0)
    threshold_sweep: list[DuplicateThresholdMetrics] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NlpEvaluationReport(BaseModel):
    component: str = "nlp_classifier"
    evaluation_status: EvaluationStatus
    classes: list[str] = Field(default_factory=list)
    sample_count: int = Field(default=0, ge=0)
    accuracy: float | None = None
    macro_precision: float | None = None
    macro_recall: float | None = None
    macro_f1: float | None = None
    per_class_metrics: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    confusion_matrix: list[list[int]] = Field(default_factory=list)
    not_relevant_recall: float | None = None
    subgroup_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error_analysis: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EventEvaluationReport(BaseModel):
    component: str = "event_detector"
    evaluation_status: EvaluationStatus
    sample_count: int = Field(default=0, ge=0)
    event_matching_precision: float | None = None
    event_matching_recall: float | None = None
    event_matching_f1: float | None = None
    false_merge_rate: float | None = None
    false_split_rate: float | None = None
    event_type_agreement: float | None = None
    mean_detection_latency_minutes: float | None = None
    warnings: list[str] = Field(default_factory=list)


class CredibilityEvaluationReport(BaseModel):
    component: str = "fake_detector"
    evaluation_status: EvaluationStatus
    sample_count: int = Field(default=0, ge=0)
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    macro_f1: float | None = None
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    confusion_matrix: list[list[int]] = Field(default_factory=list)
    pr_auc: float | None = None
    threshold_analysis: list[dict[str, float]] = Field(default_factory=list)
    calibration_status: str = "CALIBRATION_UNAVAILABLE"
    calibration_metrics: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ImageEvaluationReport(BaseModel):
    """Measured multi-label image metrics, available only with resolved labels."""

    component: str = "image_analyzer"
    evaluation_status: EvaluationStatus
    task_type: Literal["MULTI_LABEL"] = "MULTI_LABEL"
    classes: list[str] = Field(default_factory=list)
    sample_count: int = Field(default=0, ge=0)
    excluded_uncertain_samples: int = Field(default=0, ge=0)
    micro_precision: float | None = None
    micro_recall: float | None = None
    micro_f1: float | None = None
    macro_precision: float | None = None
    macro_recall: float | None = None
    macro_f1: float | None = None
    per_label_metrics: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    multilabel_confusion_matrices: dict[str, list[list[int]]] = Field(
        default_factory=dict
    )
    subgroup_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    calibration_status: Literal[
        "CALIBRATION_UNAVAILABLE", "CALIBRATION_EVALUATED"
    ] = "CALIBRATION_UNAVAILABLE"
    calibration_metrics: dict[str, float] = Field(default_factory=dict)
    error_analysis: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AnomalyMetricSet(BaseModel):
    sample_count: int = Field(ge=0)
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    false_negative_rate: float
    confusion_matrix: dict[str, int]


class AnomalyEvaluationReport(BaseModel):
    component: str = "anomaly_detector"
    evaluation_status: EvaluationStatus
    sample_count: int = Field(default=0, ge=0)
    excluded_uncertain_count: int = Field(default=0, ge=0)
    overall_metrics: AnomalyMetricSet | None = None
    metrics_by_domain: dict[str, AnomalyMetricSet] = Field(default_factory=dict)
    mean_detection_delay_minutes: float | None = Field(default=None, ge=0.0)
    false_alarm_rate_per_day: float | None = Field(default=None, ge=0.0)
    event_level_metrics: dict[str, float | int] = Field(default_factory=dict)
    threshold: float | None = Field(default=None, ge=0.0)
    calibration_status: Literal[
        "CALIBRATION_UNAVAILABLE", "THRESHOLD_SELECTED_ON_VALIDATION"
    ] = "CALIBRATION_UNAVAILABLE"
    warnings: list[str] = Field(default_factory=list)


class FrozenAnomalyThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: float = Field(ge=0.0)
    selected_on: Literal["validation"] = "validation"
    selection_metric: Literal["F1"] = "F1"
    validation_sample_count: int = Field(ge=1)
    frozen: Literal[True] = True


def _duplicate_metrics(
    labels: Sequence[bool],
    scores: Sequence[float],
    threshold: float,
) -> DuplicateThresholdMetrics:
    predictions = [score >= threshold for score in scores]
    tp = sum(label and prediction for label, prediction in zip(labels, predictions))
    tn = sum((not label) and (not prediction) for label, prediction in zip(labels, predictions))
    fp = sum((not label) and prediction for label, prediction in zip(labels, predictions))
    fn = sum(label and (not prediction) for label, prediction in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return DuplicateThresholdMetrics(
        threshold=threshold,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=fp / (fp + tn) if fp + tn else 0.0,
        false_negative_rate=fn / (fn + tp) if fn + tp else 0.0,
        confusion_matrix={"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
    )


def evaluate_duplicate_scores(
    labels: Sequence[bool],
    scores: Sequence[float],
    thresholds: Sequence[float],
    *,
    minimum_labeled_pairs: int = 2,
) -> DuplicateEvaluationReport:
    """Backward-compatible score evaluator for already-filtered binary labels."""

    if not labels:
        return DuplicateEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            warnings=["No authoritative labeled duplicate-pair dataset exists."],
        )
    if len(labels) != len(scores):
        raise ValueError("labels and scores must have the same length")
    if len(labels) < minimum_labeled_pairs:
        return DuplicateEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            number_labeled_pairs=len(labels),
            number_duplicate=sum(labels),
            number_not_duplicate=sum(not label for label in labels),
            warnings=[
                f"Only {len(labels)} labeled pairs are available; "
                f"at least {minimum_labeled_pairs} are required for this evaluation."
            ],
        )
    return DuplicateEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        number_labeled_pairs=len(labels),
        number_duplicate=sum(labels),
        number_not_duplicate=sum(not label for label in labels),
        duplicate_prevalence=sum(labels) / len(labels),
        threshold_sweep=[
            _duplicate_metrics(labels, scores, threshold) for threshold in thresholds
        ],
    )


def evaluate_duplicate_pairs(
    records: Sequence[DuplicatePairRecord],
    scores: Mapping[str, float],
    thresholds: Sequence[float],
    *,
    minimum_labeled_pairs: int = 2,
) -> DuplicateEvaluationReport:
    """Evaluate only DUPLICATE/NOT_DUPLICATE records; UNCERTAIN is excluded."""

    train_count = sum(record.split == "train" for record in records)
    validation_count = sum(record.split == "validation" for record in records)
    test_count = sum(record.split == "test" for record in records)
    uncertain = [record for record in records if record.label is DuplicatePairLabel.UNCERTAIN]
    labeled = [
        record
        for record in records
        if record.label in {DuplicatePairLabel.DUPLICATE, DuplicatePairLabel.NOT_DUPLICATE}
    ]
    base = dict(
        number_labeled_pairs=len(labeled),
        number_duplicate=sum(record.label is DuplicatePairLabel.DUPLICATE for record in labeled),
        number_not_duplicate=sum(record.label is DuplicatePairLabel.NOT_DUPLICATE for record in labeled),
        number_uncertain=len(uncertain),
        excluded_uncertain_pairs=len(uncertain),
        duplicate_prevalence=(len([record for record in labeled if record.label is DuplicatePairLabel.DUPLICATE]) / len(labeled)) if labeled else None,
        group_counts={
            "event_groups": len({record.event_id_when_known or record.event_id for record in records if record.event_id_when_known or record.event_id}),
            "incident_groups": len({record.incident_id_when_known or record.incident_id for record in records if record.incident_id_when_known or record.incident_id}),
        },
        train_count=train_count,
        validation_count=validation_count,
        test_count=test_count,
    )
    if not labeled:
        return DuplicateEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            **base,
            warnings=["No DUPLICATE or NOT_DUPLICATE labels are available; UNCERTAIN is excluded."],
        )
    missing_scores = [record.pair_id for record in labeled if record.pair_id not in scores]
    if missing_scores:
        raise ValueError("missing scores for pair IDs: " + ", ".join(missing_scores))
    if len(labeled) < minimum_labeled_pairs:
        return DuplicateEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            **base,
            warnings=[
                f"Only {len(labeled)} labeled pairs are available; "
                f"at least {minimum_labeled_pairs} are required for this evaluation."
            ],
        )
    labels = [record.label is DuplicatePairLabel.DUPLICATE for record in labeled]
    pair_scores = [scores[record.pair_id] for record in labeled]
    return DuplicateEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        **base,
        threshold_sweep=[
            _duplicate_metrics(labels, pair_scores, threshold) for threshold in thresholds
        ],
    )


def evaluate_duplicate_test(
    records: Sequence[DuplicatePairRecord],
    scores: Mapping[str, float],
    *,
    frozen_threshold: float,
    minimum_labeled_pairs: int = 2,
) -> DuplicateEvaluationReport:
    """Evaluate a held-out test split with a pre-frozen threshold only."""

    if any(record.split != "test" for record in records):
        raise ValueError("final duplicate evaluation requires test-split records only")
    return evaluate_duplicate_pairs(
        records,
        scores,
        [frozen_threshold],
        minimum_labeled_pairs=minimum_labeled_pairs,
    )


def _classification_error_analysis(
    labels: Sequence[str],
    predictions: Sequence[str],
    record_ids: Sequence[str] | None = None,
    texts: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
) -> dict[str, Any]:
    from collections import Counter

    ids = list(record_ids or [str(index) for index in range(len(labels))])
    content = list(texts or [""] * len(labels))
    langs = list(languages or ["unknown"] * len(labels))
    false_positives: list[dict[str, str]] = []
    false_negatives: list[dict[str, str]] = []
    confused_pairs: Counter[tuple[str, str]] = Counter()
    not_relevant_errors: list[dict[str, str]] = []
    multilingual_errors: dict[str, list[dict[str, str]]] = {}
    grouped_errors: dict[str, list[dict[str, str]]] = {}
    for index, (truth, prediction) in enumerate(zip(labels, predictions)):
        if truth == prediction:
            continue
        item = {
            "record_id": ids[index],
            "true_label": truth,
            "predicted_label": prediction,
            "language": langs[index],
            "text": content[index],
        }
        false_positives.append(item)
        false_negatives.append(item)
        confused_pairs[(truth, prediction)] += 1
        grouped_errors.setdefault(f"{truth} -> {prediction}", []).append(item)
        if prediction == "NOT_RELEVANT" or truth == "NOT_RELEVANT":
            not_relevant_errors.append(item)
        if langs[index] in {"en", "hi", "hinglish"}:
            multilingual_errors.setdefault(langs[index], []).append(item)
    deterministic_key = lambda item: (
        item["true_label"],
        item["predicted_label"],
        item["record_id"],
    )
    false_positives.sort(key=deterministic_key)
    false_negatives.sort(key=deterministic_key)
    not_relevant_errors.sort(key=deterministic_key)
    for items in multilingual_errors.values():
        items.sort(key=deterministic_key)
    for items in grouped_errors.values():
        items.sort(key=deterministic_key)
    ordered_confusions = sorted(
        confused_pairs.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    return {
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "most_confused_class_pairs": [
            {"true_label": pair[0], "predicted_label": pair[1], "count": count}
            for pair, count in ordered_confusions
        ],
        "not_relevant_errors": not_relevant_errors,
        "hindi_errors": multilingual_errors.get("hi", []),
        "hinglish_errors": multilingual_errors.get("hinglish", []),
        "hindi_hinglish_errors": {
            language: items
            for language, items in multilingual_errors.items()
            if language in {"hi", "hinglish"}
        },
        "examples_grouped_by_actual_and_predicted": {
            key: grouped_errors[key] for key in sorted(grouped_errors)
        },
    }


def evaluate_nlp_predictions(
    labels: Sequence[str],
    predictions: Sequence[str],
    classes: Sequence[str],
    *,
    record_ids: Sequence[str] | None = None,
    texts: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
    minimum_subgroup_rows: int = 5,
    expected_languages: Sequence[str] | None = None,
) -> NlpEvaluationReport:
    """Calculate measured multiclass metrics without fabricating empty results."""

    if not labels:
        return NlpEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            classes=list(classes),
            warnings=["No labeled NLP evaluation rows are available."],
        )
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have the same length")
    auxiliary = {
        "record_ids": record_ids,
        "texts": texts,
        "languages": languages,
    }
    for name, values in auxiliary.items():
        if values is not None and len(values) != len(labels):
            raise ValueError(f"{name} must have the same length as labels")
    if len(labels) < 2:
        return NlpEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            classes=list(classes),
            sample_count=len(labels),
            warnings=["At least two labeled rows are required for evaluation."],
        )
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        precision_recall_fscore_support,
    )

    precision, recall, f1, support = precision_recall_fscore_support(
        labels,
        predictions,
        labels=list(classes),
        zero_division=0,
    )
    per_class = {
        label: {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
        for index, label in enumerate(classes)
    }
    subgroup_metrics: dict[str, dict[str, Any]] = {}
    if languages is not None:
        language_names = set(languages)
        language_names.update(expected_languages or ())
        for language in sorted(language_names):
            indexes = [index for index, value in enumerate(languages) if value == language]
            if len(indexes) < minimum_subgroup_rows:
                subgroup_metrics[language] = {
                    "status": "INSUFFICIENT_DATA",
                    "sample_count": len(indexes),
                }
                continue
            subgroup_labels = [labels[i] for i in indexes]
            subgroup_predictions = [predictions[i] for i in indexes]
            subgroup_precision, subgroup_recall, subgroup_f1, _ = (
                precision_recall_fscore_support(
                    subgroup_labels,
                    subgroup_predictions,
                    labels=list(classes),
                    zero_division=0,
                )
            )
            subgroup_metrics[language] = {
                "status": "DATA_AVAILABLE",
                "sample_count": len(indexes),
                "accuracy": float(
                    accuracy_score(subgroup_labels, subgroup_predictions)
                ),
                "macro_precision": float(subgroup_precision.mean()),
                "macro_recall": float(subgroup_recall.mean()),
                "macro_f1": float(subgroup_f1.mean()),
                "confusion_matrix": confusion_matrix(
                    subgroup_labels,
                    subgroup_predictions,
                    labels=list(classes),
                ).tolist(),
            }
    return NlpEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        classes=list(classes),
        sample_count=len(labels),
        accuracy=float(accuracy_score(labels, predictions)),
        macro_precision=float(precision.mean()),
        macro_recall=float(recall.mean()),
        macro_f1=float(f1.mean()),
        per_class_metrics=per_class,
        confusion_matrix=confusion_matrix(labels, predictions, labels=list(classes)).tolist(),
        not_relevant_recall=(
            per_class["NOT_RELEVANT"]["recall"] if "NOT_RELEVANT" in per_class else None
        ),
        subgroup_metrics=subgroup_metrics,
        error_analysis=_classification_error_analysis(
            labels,
            predictions,
            record_ids,
            texts,
            languages,
        ),
    )


def evaluate_event_matching(
    labels: Sequence[str | bool],
    predictions: Sequence[str | bool],
    *,
    true_event_types: Sequence[str | None] | None = None,
    predicted_event_types: Sequence[str | None] | None = None,
    detection_latency_minutes: Sequence[float | None] | None = None,
    minimum_labeled_pairs: int = 2,
) -> EventEvaluationReport:
    """Evaluate event matching only when human event labels are supplied."""

    if len(labels) != len(predictions):
        raise ValueError("event labels and predictions must have the same length")
    if true_event_types is not None and len(true_event_types) != len(labels):
        raise ValueError("true_event_types must match labels length")
    if predicted_event_types is not None and len(predicted_event_types) != len(labels):
        raise ValueError("predicted_event_types must match labels length")
    if detection_latency_minutes is not None and len(detection_latency_minutes) != len(labels):
        raise ValueError("detection_latency_minutes must match labels length")

    def as_match(value: str | bool) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value).upper()
        if normalized in {"EVENT_MATCH", "MATCH", "TRUE", "1"}:
            return True
        if normalized in {"EVENT_NOT_MATCH", "NOT_MATCH", "FALSE", "0"}:
            return False
        if normalized == "UNCERTAIN":
            return None
        raise ValueError(f"unsupported event matching label: {value!r}")

    pairs = []
    for index, (label, prediction) in enumerate(zip(labels, predictions)):
        truth = as_match(label)
        predicted = as_match(prediction)
        if truth is not None and predicted is not None:
            pairs.append((truth, predicted, index))
    if not pairs:
        return EventEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            warnings=["No authoritative labeled event pairs are available."],
        )
    if len(pairs) < minimum_labeled_pairs:
        return EventEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            sample_count=len(pairs),
            warnings=[
                f"Only {len(pairs)} labeled event pairs are available; "
                f"at least {minimum_labeled_pairs} are required."
            ],
        )
    true_values = [label for label, _, _ in pairs]
    predicted_values = [prediction for _, prediction, _ in pairs]
    true_values = [bool(value) for value in true_values]
    predicted_values = [bool(value) for value in predicted_values]
    true_positive = sum(truth and prediction for truth, prediction in zip(true_values, predicted_values))
    true_negative = sum(not truth and not prediction for truth, prediction in zip(true_values, predicted_values))
    false_positive = sum(not truth and prediction for truth, prediction in zip(true_values, predicted_values))
    false_negative = sum(truth and not prediction for truth, prediction in zip(true_values, predicted_values))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    type_agreement = None
    if true_event_types is not None and predicted_event_types is not None:
        type_pairs = [
            (true_event_types[index], predicted_event_types[index])
            for _, _, index in pairs
            if true_event_types[index] is not None and predicted_event_types[index] is not None
        ]
        if type_pairs:
            type_agreement = sum(left == right for left, right in type_pairs) / len(type_pairs)
    mean_latency = None
    if detection_latency_minutes is not None:
        latencies = [
            float(detection_latency_minutes[index])
            for _, _, index in pairs
            if detection_latency_minutes[index] is not None
        ]
        if latencies:
            mean_latency = sum(latencies) / len(latencies)
    return EventEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        sample_count=len(pairs),
        event_matching_precision=precision,
        event_matching_recall=recall,
        event_matching_f1=f1,
        false_merge_rate=false_positive / (false_positive + true_negative) if false_positive + true_negative else 0.0,
        false_split_rate=false_negative / (false_negative + true_positive) if false_negative + true_positive else 0.0,
        event_type_agreement=type_agreement,
        mean_detection_latency_minutes=mean_latency,
    )


def evaluate_credibility_predictions(
    labels: Sequence[str],
    predictions: Sequence[str | bool],
    *,
    risk_scores: Sequence[float] | None = None,
    calibrated_probabilities: Sequence[float] | None = None,
    thresholds: Sequence[float] = (0.25, 0.50, 0.75),
    minimum_labeled_reports: int = 2,
) -> CredibilityEvaluationReport:
    """Evaluate only authoritative labels; UNCERTAIN annotations are excluded."""

    if len(labels) != len(predictions):
        raise ValueError("credibility labels and predictions must have the same length")
    if risk_scores is not None and len(risk_scores) != len(labels):
        raise ValueError("risk_scores must match labels length")
    if calibrated_probabilities is not None and len(calibrated_probabilities) != len(labels):
        raise ValueError("calibrated_probabilities must match labels length")
    if not labels:
        return CredibilityEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            warnings=["No validated fake/misleading-report labels are available."],
        )

    def truth_value(value: str) -> bool | None:
        normalized = str(value).upper()
        if normalized == "MISLEADING":
            return True
        if normalized == "AUTHENTIC":
            return False
        if normalized == "UNCERTAIN":
            return None
        raise ValueError(f"unsupported credibility label: {value!r}")

    def prediction_value(value: str | bool) -> bool | None:
        if isinstance(value, bool):
            return value
        return truth_value(value)

    rows = []
    for index, (label, prediction) in enumerate(zip(labels, predictions)):
        truth = truth_value(label)
        predicted = prediction_value(prediction)
        if truth is not None and predicted is not None:
            rows.append((truth, predicted, index))
    if len(rows) < minimum_labeled_reports:
        return CredibilityEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            sample_count=len(rows),
            warnings=[
                f"Only {len(rows)} resolved labeled reports are available; "
                f"at least {minimum_labeled_reports} are required."
            ],
        )

    truths = [truth for truth, _, _ in rows]
    predicted = [value for _, value, _ in rows]
    tp = sum(truth and value for truth, value in zip(truths, predicted))
    tn = sum(not truth and not value for truth, value in zip(truths, predicted))
    fp = sum(not truth and value for truth, value in zip(truths, predicted))
    fn = sum(truth and not value for truth, value in zip(truths, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    authentic_precision = tn / (tn + fn) if tn + fn else 0.0
    authentic_recall = tn / (tn + fp) if tn + fp else 0.0
    authentic_f1 = (
        2.0 * authentic_precision * authentic_recall / (authentic_precision + authentic_recall)
        if authentic_precision + authentic_recall
        else 0.0
    )
    resolved_scores = (
        [float(risk_scores[index]) for _, _, index in rows]
        if risk_scores is not None
        else None
    )
    pr_auc = None
    threshold_results: list[dict[str, float]] = []
    if resolved_scores is not None:
        from sklearn.metrics import average_precision_score

        pr_auc = float(average_precision_score(truths, resolved_scores))
        for threshold in thresholds:
            threshold_predictions = [score >= threshold for score in resolved_scores]
            threshold_tp = sum(truth and value for truth, value in zip(truths, threshold_predictions))
            threshold_fp = sum(not truth and value for truth, value in zip(truths, threshold_predictions))
            threshold_fn = sum(truth and not value for truth, value in zip(truths, threshold_predictions))
            threshold_precision = threshold_tp / (threshold_tp + threshold_fp) if threshold_tp + threshold_fp else 0.0
            threshold_recall = threshold_tp / (threshold_tp + threshold_fn) if threshold_tp + threshold_fn else 0.0
            threshold_f1 = (
                2.0 * threshold_precision * threshold_recall / (threshold_precision + threshold_recall)
                if threshold_precision + threshold_recall
                else 0.0
            )
            threshold_results.append(
                {
                    "threshold": float(threshold),
                    "precision": threshold_precision,
                    "recall": threshold_recall,
                    "f1": threshold_f1,
                }
            )
    calibration_status = "CALIBRATION_UNAVAILABLE"
    calibration_metrics: dict[str, float] = {}
    if calibrated_probabilities is not None:
        resolved_probabilities = [
            float(calibrated_probabilities[index]) for _, _, index in rows
        ]
        if any(not 0.0 <= value <= 1.0 for value in resolved_probabilities):
            raise ValueError("calibrated probabilities must be between zero and one")
        calibration_status = "CALIBRATION_EVALUATED"
        calibration_metrics["brier_score"] = sum(
            (value - float(truth)) ** 2
            for value, truth in zip(resolved_probabilities, truths)
        ) / len(truths)
    return CredibilityEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        sample_count=len(rows),
        precision=precision,
        recall=recall,
        f1=f1,
        macro_f1=(f1 + authentic_f1) / 2.0,
        false_positive_rate=fp / (fp + tn) if fp + tn else 0.0,
        false_negative_rate=fn / (fn + tp) if fn + tp else 0.0,
        confusion_matrix=[[tn, fp], [fn, tp]],
        pr_auc=pr_auc,
        threshold_analysis=threshold_results,
        calibration_status=calibration_status,
        calibration_metrics=calibration_metrics,
    )


def evaluate_image_predictions(
    labels: Sequence[Sequence[str]],
    predictions: Sequence[Sequence[str]],
    *,
    classes: Sequence[str] | None = None,
    sample_ids: Sequence[str] | None = None,
    subgroups: Mapping[str, Sequence[str]] | None = None,
    probabilities: Sequence[Mapping[str, float]] | None = None,
    minimum_labeled_samples: int = 2,
    minimum_subgroup_samples: int = 2,
) -> ImageEvaluationReport:
    """Evaluate resolved multi-label annotations without inventing metrics.

    Samples whose ground truth contains ``UNCERTAIN`` are excluded. Probability
    calibration is measured only when explicit per-label probabilities are
    supplied; otherwise its status remains ``CALIBRATION_UNAVAILABLE``.
    """

    from app.ml.data.image_annotations import IMAGE_MODEL_LABELS

    if len(labels) != len(predictions):
        raise ValueError("image labels and predictions must have the same length")
    if sample_ids is not None and len(sample_ids) != len(labels):
        raise ValueError("sample_ids must match labels length")
    if probabilities is not None and len(probabilities) != len(labels):
        raise ValueError("probabilities must match labels length")
    for name, values in (subgroups or {}).items():
        if len(values) != len(labels):
            raise ValueError(f"subgroup {name!r} must match labels length")
    if minimum_labeled_samples < 1 or minimum_subgroup_samples < 1:
        raise ValueError("minimum sample counts must be positive")

    def value_of(item: Any) -> str:
        value = getattr(item, "value", item)
        return str(value)

    class_names = (
        [value_of(item) for item in classes]
        if classes is not None
        else [item.value for item in IMAGE_MODEL_LABELS]
    )
    if not class_names or len(class_names) != len(set(class_names)):
        raise ValueError("classes must be non-empty and unique")
    if "UNCERTAIN" in class_names:
        raise ValueError("UNCERTAIN is an annotation state, not a model output class")
    allowed = set(class_names)
    if not labels:
        return ImageEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            classes=class_names,
            warnings=["No validated image labels are available."],
        )

    rows: list[tuple[set[str], set[str], int]] = []
    uncertain_indexes: list[int] = []
    for index, (true_items, predicted_items) in enumerate(zip(labels, predictions)):
        truth = {value_of(item) for item in true_items}
        predicted = {value_of(item) for item in predicted_items}
        if not truth:
            raise ValueError(f"image sample {index} has no ground-truth labels")
        if "UNCERTAIN" in truth:
            uncertain_indexes.append(index)
            continue
        unknown_truth = truth - allowed
        unknown_predictions = predicted - allowed
        if unknown_truth:
            raise ValueError(f"unknown image truth labels: {sorted(unknown_truth)}")
        if unknown_predictions:
            raise ValueError(
                f"unknown image prediction labels: {sorted(unknown_predictions)}"
            )
        rows.append((truth, predicted, index))

    ambiguous_ids = [
        sample_ids[index] if sample_ids is not None else str(index)
        for index in uncertain_indexes
    ]
    if not rows:
        return ImageEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            classes=class_names,
            excluded_uncertain_samples=len(uncertain_indexes),
            error_analysis={"ambiguous_or_uncertain_samples": ambiguous_ids},
            warnings=[
                "No resolved image labels remain after excluding UNCERTAIN annotations."
            ],
        )
    if len(rows) < minimum_labeled_samples:
        return ImageEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            classes=class_names,
            sample_count=len(rows),
            excluded_uncertain_samples=len(uncertain_indexes),
            error_analysis={"ambiguous_or_uncertain_samples": ambiguous_ids},
            warnings=[
                (
                    f"Only {len(rows)} resolved image samples are available; at least "
                    f"{minimum_labeled_samples} are required."
                )
            ],
        )

    from sklearn.metrics import (
        multilabel_confusion_matrix,
        precision_recall_fscore_support,
    )
    from sklearn.preprocessing import MultiLabelBinarizer

    binarizer = MultiLabelBinarizer(classes=class_names)
    binarizer.fit([class_names])
    true_sets = [truth for truth, _, _ in rows]
    predicted_sets = [predicted for _, predicted, _ in rows]
    true_matrix = binarizer.transform(true_sets)
    predicted_matrix = binarizer.transform(predicted_sets)
    per_precision, per_recall, per_f1, support = precision_recall_fscore_support(
        true_matrix,
        predicted_matrix,
        average=None,
        zero_division=0,
    )
    micro = precision_recall_fscore_support(
        true_matrix,
        predicted_matrix,
        average="micro",
        zero_division=0,
    )
    macro = precision_recall_fscore_support(
        true_matrix,
        predicted_matrix,
        average="macro",
        zero_division=0,
    )
    matrices = multilabel_confusion_matrix(true_matrix, predicted_matrix)
    per_label = {
        label: {
            "precision": float(per_precision[index]),
            "recall": float(per_recall[index]),
            "f1": float(per_f1[index]),
            "support": int(support[index]),
        }
        for index, label in enumerate(class_names)
    }
    matrix_by_label = {
        label: matrices[index].astype(int).tolist()
        for index, label in enumerate(class_names)
    }

    false_positives: list[dict[str, str]] = []
    false_negatives: list[dict[str, str]] = []
    confused: Counter[str] = Counter()
    for truth, predicted, original_index in rows:
        sample_id = (
            sample_ids[original_index] if sample_ids is not None else str(original_index)
        )
        extras = sorted(predicted - truth)
        missing = sorted(truth - predicted)
        false_positives.extend(
            {"sample_id": sample_id, "label": label} for label in extras
        )
        false_negatives.extend(
            {"sample_id": sample_id, "label": label} for label in missing
        )
        for missed_label in missing:
            for extra_label in extras:
                confused[f"{missed_label}->{extra_label}"] += 1

    subgroup_metrics: dict[str, dict[str, Any]] = {}
    resolved_original_indexes = [original_index for _, _, original_index in rows]
    for dimension, values in sorted((subgroups or {}).items()):
        for subgroup_value in sorted(set(values)):
            row_indexes = [
                row_index
                for row_index, original_index in enumerate(resolved_original_indexes)
                if values[original_index] == subgroup_value
            ]
            key = f"{dimension}={subgroup_value}"
            if len(row_indexes) < minimum_subgroup_samples:
                subgroup_metrics[key] = {
                    "status": "INSUFFICIENT_DATA",
                    "sample_count": len(row_indexes),
                }
                continue
            subgroup_score = precision_recall_fscore_support(
                true_matrix[row_indexes],
                predicted_matrix[row_indexes],
                average="micro",
                zero_division=0,
            )
            subgroup_metrics[key] = {
                "status": "DATA_AVAILABLE",
                "sample_count": len(row_indexes),
                "micro_precision": float(subgroup_score[0]),
                "micro_recall": float(subgroup_score[1]),
                "micro_f1": float(subgroup_score[2]),
            }

    calibration_status: Literal[
        "CALIBRATION_UNAVAILABLE", "CALIBRATION_EVALUATED"
    ] = "CALIBRATION_UNAVAILABLE"
    calibration_metrics: dict[str, float] = {}
    if probabilities is not None:
        for _, _, original_index in rows:
            supplied = {value_of(key) for key in probabilities[original_index]}
            missing = allowed - supplied
            unknown = supplied - allowed
            if missing or unknown:
                raise ValueError(
                    "image probability keys must exactly match classes; "
                    f"missing={sorted(missing)}, unknown={sorted(unknown)}"
                )
        brier_by_label: dict[str, float] = {}
        for class_index, label in enumerate(class_names):
            predicted_probabilities: list[float] = []
            for _, _, original_index in rows:
                normalized_probabilities = {
                    value_of(key): value
                    for key, value in probabilities[original_index].items()
                }
                probability = float(normalized_probabilities[label])
                if not 0.0 <= probability <= 1.0:
                    raise ValueError("image probabilities must be between zero and one")
                predicted_probabilities.append(probability)
            brier_by_label[label] = sum(
                (probability - float(target)) ** 2
                for probability, target in zip(
                    predicted_probabilities, true_matrix[:, class_index]
                )
            ) / len(rows)
        calibration_status = "CALIBRATION_EVALUATED"
        calibration_metrics = {
            **{f"brier_{label}": value for label, value in brier_by_label.items()},
            "mean_brier": sum(brier_by_label.values()) / len(brier_by_label),
        }

    return ImageEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        classes=class_names,
        sample_count=len(rows),
        excluded_uncertain_samples=len(uncertain_indexes),
        micro_precision=float(micro[0]),
        micro_recall=float(micro[1]),
        micro_f1=float(micro[2]),
        macro_precision=float(macro[0]),
        macro_recall=float(macro[1]),
        macro_f1=float(macro[2]),
        per_label_metrics=per_label,
        multilabel_confusion_matrices=matrix_by_label,
        subgroup_metrics=subgroup_metrics,
        calibration_status=calibration_status,
        calibration_metrics=calibration_metrics,
        error_analysis={
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "confused_classes": [
                {"pair": pair, "count": count}
                for pair, count in confused.most_common()
            ],
            "ambiguous_or_uncertain_samples": ambiguous_ids,
            "subgroup_failures": [
                name
                for name, metrics in subgroup_metrics.items()
                if metrics.get("status") == "DATA_AVAILABLE"
                and float(metrics.get("micro_f1", 0.0)) < float(micro[2])
            ],
        },
    )


def _anomaly_metric_set(
    labels: Sequence[bool],
    predictions: Sequence[bool],
) -> AnomalyMetricSet:
    true_positive = sum(label and prediction for label, prediction in zip(labels, predictions))
    true_negative = sum(
        not label and not prediction for label, prediction in zip(labels, predictions)
    )
    false_positive = sum(
        not label and prediction for label, prediction in zip(labels, predictions)
    )
    false_negative = sum(
        label and not prediction for label, prediction in zip(labels, predictions)
    )
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return AnomalyMetricSet(
        sample_count=len(labels),
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=(
            false_positive / (false_positive + true_negative)
            if false_positive + true_negative
            else 0.0
        ),
        false_negative_rate=(
            false_negative / (false_negative + true_positive)
            if false_negative + true_positive
            else 0.0
        ),
        confusion_matrix={
            "true_positive": true_positive,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
        },
    )


def evaluate_anomaly_predictions(
    annotations: Sequence[AnomalyAnnotation],
    predictions: Sequence[AnomalyPrediction],
    *,
    detection_delay_minutes: Sequence[float | None] | None = None,
    observation_period_hours: float | None = None,
    event_ids: Sequence[str | None] | None = None,
    threshold: float | None = None,
    threshold_selected_on_validation: bool = False,
    minimum_resolved_samples: int = 2,
) -> AnomalyEvaluationReport:
    """Evaluate authoritative resolved labels; never infer labels from scores."""

    if len(annotations) != len(predictions):
        raise ValueError("anomaly annotations and predictions must have the same length")
    if minimum_resolved_samples < 1:
        raise ValueError("minimum_resolved_samples must be positive")
    if detection_delay_minutes is not None and len(detection_delay_minutes) != len(annotations):
        raise ValueError("detection_delay_minutes must match annotations length")
    if event_ids is not None and len(event_ids) != len(annotations):
        raise ValueError("event_ids must match annotations length")
    if observation_period_hours is not None and (
        not math.isfinite(observation_period_hours)
        or observation_period_hours <= 0.0
    ):
        raise ValueError("observation_period_hours must be finite and positive")
    if threshold_selected_on_validation and threshold is None:
        raise ValueError("a frozen validation threshold is required")
    if not annotations:
        return AnomalyEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            warnings=["No validated anomaly annotations are available."],
        )

    uncertain_count = sum(
        item.label is AnomalyAnnotationLabel.UNCERTAIN for item in annotations
    )
    rows: list[tuple[AnomalyAnnotation, AnomalyPrediction, int]] = []
    unavailable_predictions = 0
    for index, (annotation, prediction) in enumerate(zip(annotations, predictions)):
        if annotation.label is AnomalyAnnotationLabel.UNCERTAIN:
            continue
        if prediction.is_anomaly is None:
            unavailable_predictions += 1
            continue
        rows.append((annotation, prediction, index))
    if not rows:
        return AnomalyEvaluationReport(
            evaluation_status="DATA_UNAVAILABLE",
            excluded_uncertain_count=uncertain_count,
            warnings=[
                "No resolved label/prediction pairs are available after exclusions."
            ],
        )
    if len(rows) < minimum_resolved_samples:
        return AnomalyEvaluationReport(
            evaluation_status="INSUFFICIENT_DATA",
            sample_count=len(rows),
            excluded_uncertain_count=uncertain_count,
            warnings=[
                f"Only {len(rows)} resolved prediction pairs are available; at least {minimum_resolved_samples} are required."
            ],
        )

    truth = [
        annotation.label is AnomalyAnnotationLabel.ANOMALY
        for annotation, _, _ in rows
    ]
    predicted = [bool(prediction.is_anomaly) for _, prediction, _ in rows]
    overall = _anomaly_metric_set(truth, predicted)
    domain_metrics: dict[str, AnomalyMetricSet] = {}
    resolved_domain_rows = [
        row
        for row in rows
        if row[0].label is AnomalyAnnotationLabel.NORMAL
        or row[0].anomaly_domain
        in {
            AnomalyDomain.DATA_QUALITY_ANOMALY,
            AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY,
        }
    ]
    for domain in (
        AnomalyDomain.DATA_QUALITY_ANOMALY,
        AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY,
    ):
        domain_truth = [
            annotation.label is AnomalyAnnotationLabel.ANOMALY
            and annotation.anomaly_domain is domain
            for annotation, _, _ in resolved_domain_rows
        ]
        domain_predictions = [
            bool(prediction.is_anomaly) and prediction.anomaly_domain is domain
            for _, prediction, _ in resolved_domain_rows
        ]
        domain_metrics[domain.value] = _anomaly_metric_set(
            domain_truth,
            domain_predictions,
        )

    mean_delay = None
    if detection_delay_minutes is not None:
        delays = [
            float(detection_delay_minutes[index])
            for annotation, prediction, index in rows
            if annotation.label is AnomalyAnnotationLabel.ANOMALY
            and prediction.is_anomaly
            and detection_delay_minutes[index] is not None
        ]
        if any(not math.isfinite(value) or value < 0.0 for value in delays):
            raise ValueError("detection delays must be finite and non-negative")
        if delays:
            mean_delay = sum(delays) / len(delays)

    false_alarm_rate = None
    if observation_period_hours is not None:
        false_positives = overall.confusion_matrix["false_positive"]
        false_alarm_rate = false_positives / (observation_period_hours / 24.0)

    event_metrics: dict[str, float | int] = {}
    if event_ids is not None:
        event_rows: defaultdict[str, list[tuple[bool, bool]]] = defaultdict(list)
        for annotation, prediction, index in rows:
            event_id = event_ids[index]
            if event_id:
                event_rows[event_id].append(
                    (
                        annotation.label is AnomalyAnnotationLabel.ANOMALY,
                        bool(prediction.is_anomaly),
                    )
                )
        true_events = {
            event_id
            for event_id, values in event_rows.items()
            if any(label for label, _ in values)
        }
        predicted_events = {
            event_id
            for event_id, values in event_rows.items()
            if any(prediction for _, prediction in values)
        }
        event_true_positive = len(true_events & predicted_events)
        event_false_positive = len(predicted_events - true_events)
        event_false_negative = len(true_events - predicted_events)
        if event_rows:
            event_precision = (
                event_true_positive / (event_true_positive + event_false_positive)
                if event_true_positive + event_false_positive
                else 0.0
            )
            event_recall = (
                event_true_positive / (event_true_positive + event_false_negative)
                if event_true_positive + event_false_negative
                else 0.0
            )
            event_f1 = (
                2.0 * event_precision * event_recall
                / (event_precision + event_recall)
                if event_precision + event_recall
                else 0.0
            )
            event_metrics = {
                "labeled_event_count": len(event_rows),
                "labeled_anomaly_event_count": len(true_events),
                "predicted_anomaly_event_count": len(predicted_events),
                "event_precision": event_precision,
                "event_recall": event_recall,
                "event_f1": event_f1,
                "event_true_positive": event_true_positive,
                "event_false_positive": event_false_positive,
                "event_false_negative": event_false_negative,
            }

    warnings: list[str] = []
    if unavailable_predictions:
        warnings.append(
            f"Excluded {unavailable_predictions} resolved labels with unavailable detector decisions."
        )
    unresolved_domain_count = len(rows) - len(resolved_domain_rows)
    if unresolved_domain_count:
        warnings.append(
            f"Excluded {unresolved_domain_count} anomaly labels with unresolved domains from per-domain metrics."
        )
    return AnomalyEvaluationReport(
        evaluation_status="DATA_AVAILABLE",
        sample_count=len(rows),
        excluded_uncertain_count=uncertain_count,
        overall_metrics=overall,
        metrics_by_domain=domain_metrics,
        mean_detection_delay_minutes=mean_delay,
        false_alarm_rate_per_day=false_alarm_rate,
        event_level_metrics=event_metrics,
        threshold=threshold,
        calibration_status=(
            "THRESHOLD_SELECTED_ON_VALIDATION"
            if threshold_selected_on_validation
            else "CALIBRATION_UNAVAILABLE"
        ),
        warnings=warnings,
    )


def _coerce_anomaly_label(value: str | bool | AnomalyAnnotationLabel) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = value.value if isinstance(value, AnomalyAnnotationLabel) else str(value).upper()
    if normalized == "ANOMALY":
        return True
    if normalized == "NORMAL":
        return False
    if normalized == "UNCERTAIN":
        return None
    raise ValueError(f"unsupported anomaly label: {value!r}")


def calibrate_anomaly_threshold(
    labels: Sequence[str | bool | AnomalyAnnotationLabel],
    scores: Sequence[float],
    thresholds: Sequence[float],
    *,
    split_name: str,
) -> FrozenAnomalyThreshold:
    """Select on validation only and return an explicitly frozen threshold."""

    if split_name != "validation":
        raise ValueError("anomaly threshold selection is validation-only; test tuning is prohibited")
    if len(labels) != len(scores):
        raise ValueError("anomaly labels and scores must have the same length")
    if not thresholds:
        raise ValueError("at least one threshold candidate is required")
    rows = [
        (truth, float(score))
        for label, score in zip(labels, scores)
        if (truth := _coerce_anomaly_label(label)) is not None
    ]
    if not rows:
        raise ValueError("no resolved validation labels are available")
    if any(not math.isfinite(score) or score < 0.0 for _, score in rows):
        raise ValueError("anomaly scores must be finite and non-negative")
    candidates: list[tuple[float, AnomalyMetricSet]] = []
    for threshold_value in thresholds:
        if not math.isfinite(threshold_value) or threshold_value < 0.0:
            raise ValueError("anomaly thresholds must be finite and non-negative")
        metric = _anomaly_metric_set(
            [truth for truth, _ in rows],
            [score >= threshold_value for _, score in rows],
        )
        candidates.append((float(threshold_value), metric))
    selected, _ = max(
        candidates,
        key=lambda item: (item[1].f1, item[1].recall, -item[0]),
    )
    return FrozenAnomalyThreshold(
        threshold=selected,
        validation_sample_count=len(rows),
    )


def evaluate_anomaly_test(
    annotations: Sequence[AnomalyAnnotation],
    scores: Mapping[str, float],
    frozen_threshold: FrozenAnomalyThreshold,
    *,
    predicted_domains: Mapping[str, AnomalyDomain] | None = None,
    **kwargs,
) -> AnomalyEvaluationReport:
    """Apply one validation-selected threshold to the final test period once."""

    if any(item.split != "test" for item in annotations):
        raise ValueError("final anomaly evaluation accepts test annotations only")
    missing = [item.target_id for item in annotations if item.target_id not in scores]
    if missing:
        raise ValueError("missing anomaly scores for target IDs: " + ", ".join(missing))
    predictions = [
        AnomalyPrediction(
            status="HEURISTIC_ONLY",
            is_anomaly=scores[item.target_id] >= frozen_threshold.threshold,
            anomaly_domain=(predicted_domains or {}).get(item.target_id),
            score=scores[item.target_id],
            score_type="STATISTICAL_OUTLIER_SCORE",
            threshold=frozen_threshold.threshold,
        )
        for item in annotations
    ]
    return evaluate_anomaly_predictions(
        annotations,
        predictions,
        threshold=frozen_threshold.threshold,
        threshold_selected_on_validation=True,
        **kwargs,
    )


def calibrate_duplicate_threshold(
    labels: Sequence[bool],
    scores: Sequence[float],
    thresholds: Sequence[float],
    *,
    split_name: str,
) -> float:
    """Select a threshold from validation only; test tuning is rejected."""

    if split_name != "validation":
        raise ValueError("duplicate threshold selection is validation-only; test tuning is prohibited")
    report = evaluate_duplicate_scores(labels, scores, thresholds)
    if report.evaluation_status != "DATA_AVAILABLE" or not report.threshold_sweep:
        raise ValueError("validation data is unavailable for threshold selection")
    return max(report.threshold_sweep, key=lambda metric: (metric.f1, -metric.threshold)).threshold


def evaluate_predictions(
    *,
    component: str,
    metric_family: MetricFamily,
    metrics: dict[str, Any],
) -> EvaluationReport:
    """Accept explicitly calculated metrics; never invent metrics by default."""

    return EvaluationReport(
        component=component,
        metric_family=metric_family,
        metrics=metrics,
    )
