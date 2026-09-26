"""Phase 23 synthetic anomaly development, freeze, and one-shot evaluation.

The live anomaly detector remains unchanged.  This module evaluates it as the
named statistical baseline, trains one transparent local candidate from
project-authored data, freezes all validation decisions, and permits exactly
one protected synthetic test evaluation.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field
from sklearn.metrics import average_precision_score

from app.ml.anomaly_artifacts import (
    AnomalyArtifactProvenance,
    authorize_anomaly_artifact,
)
from app.ml.components.anomaly_detection import score_statistical_window
from app.ml.config import AnomalyDetectionConfig
from app.ml.contracts import (
    AnomalyDomain,
    AnomalyInputWindow,
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactPolicyStatus,
    WeatherObservation,
)
from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH
from app.ml.data.synthetic_anomaly.generator import (
    DATASET_ID,
    DATASET_VERSION,
    GENERATOR_VERSION,
    SyntheticAnomalyMetadata,
    SyntheticAnomalyModelRecord,
    load_hidden_metadata,
    load_model_records,
)
from app.ml.models.anomaly_window_model import (
    DOMAIN_LABELS,
    FEATURE_NAMES,
    FEATURE_VERSION,
    MODEL_FAMILY,
    MODEL_VERSION,
    PREPROCESSING_VERSION,
    ScratchDualLogisticArtifact,
    feature_matrix,
    fit_scratch_dual_logistic,
    score_feature_matrix,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts"
DEFAULT_DATASET_ROOT = (
    REPOSITORY_ROOT / "data" / "labelled" / "anomaly" / "synthetic_v1"
)
DEFAULT_ARTIFACT_PATH = ARTIFACT_ROOT / "anomaly_model_v1.json"
DEFAULT_PROVENANCE_PATH = ARTIFACT_ROOT / "anomaly_model_v1.provenance.json"
DEFAULT_DEVELOPMENT_MANIFEST_PATH = (
    ARTIFACT_ROOT / "anomaly_model_v1.development_manifest.json"
)
DEFAULT_FINAL_RECEIPT_PATH = (
    ARTIFACT_ROOT / "anomaly_model_v1_final_test_receipt.json"
)
DEFAULT_ARTIFACT_MANIFEST_PATH = ARTIFACT_ROOT / "manifest.json"
RANDOM_SEED = 230023
CONFIGURATION_VERSION = "anomaly-synthetic-validation-config-v1"

PROTECTED_ARTIFACTS = {
    "nlp_classifier_v3.json": (
        "7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca"
    ),
    "nlp_classifier_v3.final_test_receipt.json": (
        "ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b"
    ),
    "duplicate_feature_state_v2.json": (
        "d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731"
    ),
    "duplicate_matcher_v1.json": (
        "85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b"
    ),
    "duplicate_v1_final_test_receipt.json": (
        "4b97fa5b617c0bf2c93383a8d031be5a9fd6dcd5c08c9b2c229cec9d57ead405"
    ),
    "event_grouping_v1.json": (
        "10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973"
    ),
    "event_grouping_v1_final_test_receipt.json": (
        "c6ae828fc435275f031175f47500beccada675fb5ad7bd5559c6de8c58e1d913"
    ),
    "credibility_v1.json": (
        "8bbd16727be2ba639e031db37a84f0ca92a2a14220fd1819e45dbf689bab7052"
    ),
    "credibility_v1_final_test_receipt.json": (
        "d9f3dc044bf57722180ee70fd459f7208233c3e3cd12bac5b35abe557e4c39dc"
    ),
    "image_model_v1.pt": (
        "6daf6e9dc41783c7d30b19b5c0cc2a0fb20871733f9ab714a7b99552424f9248"
    ),
    "image_model_v1_final_test_receipt.json": (
        "4627f84a82282090caa22b75acbfdbd585b92720fe1a1ff7824dbf830e3385ad"
    ),
}


class FrozenAnomalyDevelopment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    phase: str = "23 — ANOMALY MODEL SYNTHETIC VALIDATION"
    development_status: str = "DEVELOPMENT_ONLY"
    production_validation: str = "NOT_VALIDATED"
    dataset_id: str
    dataset_version: str
    dataset_root: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    artifact_name: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_name: str
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_version: str
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_model: str
    thresholds: dict[str, float]
    validation_metrics: dict[str, Any]
    validation_release_checks: dict[str, bool]
    protected_final_test: dict[str, Any]
    source_hashes: dict[str, str]
    protected_artifacts: dict[str, str]
    artifact_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: str
    test_records_loaded_for_selection: bool = False
    calibration: str = "NONE_VALIDATION_THRESHOLDS_ONLY"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Any, *, exclusive: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(value) + b"\n"
    if exclusive:
        with path.open("xb") as handle:
            handle.write(payload)
        return hashlib.sha256(payload).hexdigest()
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()


def _paths(root: Path) -> dict[str, Path]:
    return {
        "artifact": root / DEFAULT_ARTIFACT_PATH.name,
        "provenance": root / DEFAULT_PROVENANCE_PATH.name,
        "development": root / DEFAULT_DEVELOPMENT_MANIFEST_PATH.name,
        "baseline": root / "anomaly_model_v1.baseline_validation.json",
        "validation": root / "anomaly_model_v1.validation_metrics.json",
        "thresholds": root / "anomaly_model_v1.threshold_search.json",
        "calibration": root / "anomaly_model_v1.calibration.json",
        "validation_errors": root / "anomaly_model_v1.validation_errors.json",
        "performance": root / "anomaly_model_v1.performance.json",
        "metrics": root / "anomaly_model_v1.metrics.json",
        "error_report": root / "anomaly_model_v1.error_report.json",
        "receipt": root / DEFAULT_FINAL_RECEIPT_PATH.name,
    }


def _source_hashes() -> dict[str, str]:
    paths = (
        REPOSITORY_ROOT / "backend/app/ml/data/synthetic_anomaly/generator.py",
        REPOSITORY_ROOT / "backend/app/ml/models/anomaly_window_model.py",
        REPOSITORY_ROOT / "backend/app/ml/training/anomaly_synthetic_validation.py",
        REPOSITORY_ROOT / "backend/app/ml/anomaly_artifacts.py",
        REPOSITORY_ROOT / "backend/app/ml/components/anomaly_features.py",
        REPOSITORY_ROOT / "backend/app/ml/components/anomaly_detection.py",
    )
    return {
        path.relative_to(REPOSITORY_ROOT).as_posix(): file_sha256(path)
        for path in paths
    }


def protected_artifact_snapshot(root: Path = ARTIFACT_ROOT) -> dict[str, str]:
    return {
        name: file_sha256(root / name)
        for name in PROTECTED_ARTIFACTS
        if (root / name).is_file()
    }


def _assert_frozen_core(snapshot: dict[str, str]) -> None:
    if snapshot != PROTECTED_ARTIFACTS:
        missing = sorted(set(PROTECTED_ARTIFACTS) - set(snapshot))
        changed = sorted(
            name
            for name in set(snapshot) & set(PROTECTED_ARTIFACTS)
            if snapshot[name] != PROTECTED_ARTIFACTS[name]
        )
        raise RuntimeError(
            f"protected Phase 18–22 artifacts changed; missing={missing}, changed={changed}"
        )


def _load_manifest(dataset_root: Path) -> dict[str, Any]:
    manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    quality_path = dataset_root / "quality_report.json"
    quality = json.loads(
        quality_path.read_text(encoding="utf-8")
    )
    if manifest.get("dataset_id") != DATASET_ID or manifest.get("dataset_version") != DATASET_VERSION:
        raise ValueError("unexpected synthetic anomaly dataset identity")
    if manifest.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("unexpected synthetic anomaly generator version")
    generator_path = (
        REPOSITORY_ROOT / "backend/app/ml/data/synthetic_anomaly/generator.py"
    )
    if manifest.get("generator_source_sha256") != file_sha256(generator_path):
        raise ValueError("synthetic anomaly generator source hash does not match")
    if manifest.get("quality_report_sha256") != file_sha256(quality_path):
        raise ValueError("synthetic anomaly quality report hash does not match")
    dataset_payload = {
        key: manifest[key]
        for key in (
            "dataset_id",
            "dataset_version",
            "schema_version",
            "generator_version",
            "generator_source_sha256",
            "seed",
            "split_counts",
            "split_sha256",
            "hidden_metadata_sha256",
            "annotation_sha256",
        )
    }
    if manifest.get("dataset_sha256") != hashlib.sha256(
        _canonical_json(dataset_payload)
    ).hexdigest():
        raise ValueError("synthetic anomaly dataset manifest hash does not match")
    if manifest.get("window_count") != sum(manifest["split_counts"].values()):
        raise ValueError("dataset count and split counts disagree")
    if not quality.get("valid") or quality.get("leakage_checks", {}).get("status") != "PASS":
        raise ValueError("synthetic anomaly dataset quality gates are not valid")
    if not quality["hidden_metadata_isolation"]["physically_separate"]:
        raise ValueError("hidden generator metadata is not physically isolated")
    return manifest


def _verify_development_split_hashes(
    dataset_root: Path,
    manifest: dict[str, Any],
) -> None:
    for split in ("train", "validation"):
        model_input = dataset_root / "model_inputs" / f"{split}.jsonl"
        hidden_metadata = (
            dataset_root / "hidden_generator_metadata" / f"{split}.jsonl"
        )
        if file_sha256(model_input) != manifest["split_sha256"][split]:
            raise ValueError(f"{split} model-input hash does not match manifest")
        if (
            file_sha256(hidden_metadata)
            != manifest["hidden_metadata_sha256"][split]
        ):
            raise ValueError(f"{split} hidden-metadata hash does not match manifest")


def _load_split(
    dataset_root: Path,
    split: str,
) -> tuple[list[SyntheticAnomalyModelRecord], list[SyntheticAnomalyMetadata]]:
    records = load_model_records(dataset_root / "model_inputs" / f"{split}.jsonl")
    labels = load_hidden_metadata(
        dataset_root / "hidden_generator_metadata" / f"{split}.jsonl"
    )
    if len(records) != len(labels):
        raise ValueError(f"{split} model inputs and hidden labels have different sizes")
    if any(record.split != split for record in records) or any(
        item.split != split for item in labels
    ):
        raise ValueError(f"{split} records carry an incorrect split")
    if [item.window_id for item in records] != [item.window_id for item in labels]:
        raise ValueError(f"{split} records and hidden labels are not aligned")
    return records, labels


def _record_to_window(record: SyntheticAnomalyModelRecord) -> AnomalyInputWindow:
    observations = [
        WeatherObservation(
            observation_id=f"{record.window_id}-observation-{index:03d}",
            station_id=record.station_id,
            observed_at=timestamp,
            rainfall_mm=rainfall,
            river_level_m=river,
        )
        for index, (timestamp, rainfall, river) in enumerate(
            zip(record.timestamps, record.rainfall_mm, record.river_level_m)
        )
    ]
    return AnomalyInputWindow(
        station_id=record.station_id,
        observations=observations,
        start_at=record.timestamps[0],
        end_at=record.timestamps[-1],
    )


def _binary_metrics(
    truth: np.ndarray,
    scores: np.ndarray,
    predictions: np.ndarray,
) -> dict[str, Any]:
    truth = truth.astype(bool)
    predictions = predictions.astype(bool)
    tp = int(np.sum(truth & predictions))
    tn = int(np.sum(~truth & ~predictions))
    fp = int(np.sum(~truth & predictions))
    fn = int(np.sum(truth & ~predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    fnr = fn / (fn + tp) if fn + tp else 0.0
    pr_auc = (
        float(average_precision_score(truth.astype(np.int64), scores))
        if len(set(truth.tolist())) > 1
        else None
    )
    return {
        "sample_count": len(truth),
        "precision": round(precision, 10),
        "recall": round(recall, 10),
        "f1": round(f1, 10),
        "false_positive_rate": round(fpr, 10),
        "false_negative_rate": round(fnr, 10),
        "pr_auc_average_precision": round(pr_auc, 10) if pr_auc is not None else None,
        "confusion": {
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "true_positive": tp,
        },
        "support": int(np.sum(truth)),
    }


def _truth_arrays(
    labels: list[SyntheticAnomalyMetadata],
) -> dict[str, np.ndarray]:
    data_quality = np.asarray(
        [item.data_quality_anomaly for item in labels], dtype=bool
    )
    weather = np.asarray(
        [item.weather_behavior_anomaly for item in labels], dtype=bool
    )
    return {
        "DATA_QUALITY_ANOMALY": data_quality,
        "WEATHER_BEHAVIOR_ANOMALY": weather,
        "OVERALL_ANOMALY": data_quality | weather,
    }


def _evaluate(
    labels: list[SyntheticAnomalyMetadata],
    scores: dict[str, np.ndarray],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    truth = _truth_arrays(labels)
    predictions = {
        label: scores[label] >= thresholds[label] for label in DOMAIN_LABELS
    }
    overall_scores = np.maximum(
        scores["DATA_QUALITY_ANOMALY"],
        scores["WEATHER_BEHAVIOR_ANOMALY"],
    )
    overall_predictions = (
        predictions["DATA_QUALITY_ANOMALY"]
        | predictions["WEATHER_BEHAVIOR_ANOMALY"]
    )
    metrics = {
        label: _binary_metrics(truth[label], scores[label], predictions[label])
        for label in DOMAIN_LABELS
    }
    metrics["OVERALL_ANOMALY"] = _binary_metrics(
        truth["OVERALL_ANOMALY"],
        overall_scores,
        overall_predictions,
    )
    normal_mask = ~truth["OVERALL_ANOMALY"]
    normal_fpr = (
        float(np.mean(overall_predictions[normal_mask])) if np.any(normal_mask) else 0.0
    )

    def subgroup(indices: np.ndarray) -> dict[str, Any]:
        if not np.any(indices):
            return {"sample_count": 0, "status": "DATA_UNAVAILABLE"}
        result = {
            "sample_count": int(np.sum(indices)),
            "status": "DATA_AVAILABLE",
        }
        for label in DOMAIN_LABELS:
            result[label] = _binary_metrics(
                truth[label][indices],
                scores[label][indices],
                predictions[label][indices],
            )
        result["OVERALL_ANOMALY"] = _binary_metrics(
            truth["OVERALL_ANOMALY"][indices],
            overall_scores[indices],
            overall_predictions[indices],
        )
        return result

    scenario_results = {
        name: subgroup(
            np.asarray([item.scenario_family == name for item in labels], dtype=bool)
        )
        for name in sorted({item.scenario_family for item in labels})
    }
    station_results = {
        name: subgroup(
            np.asarray([item.station_family == name for item in labels], dtype=bool)
        )
        for name in sorted({item.station_family for item in labels})
    }
    parameter_results = {
        name: subgroup(
            np.asarray(
                [item.anomaly_parameter_family == name for item in labels],
                dtype=bool,
            )
        )
        for name in sorted({item.anomaly_parameter_family for item in labels})
    }
    hard_names = sorted(
        {
            category
            for item in labels
            for category in item.hard_negative_categories
        }
    )
    hard_results = {
        name: subgroup(
            np.asarray(
                [name in item.hard_negative_categories for item in labels],
                dtype=bool,
            )
        )
        for name in hard_names
    }
    confusion = Counter()
    for index, item in enumerate(labels):
        true_domain = (
            "DATA_QUALITY_ANOMALY"
            if item.data_quality_anomaly
            else "WEATHER_BEHAVIOR_ANOMALY"
            if item.weather_behavior_anomaly
            else "NORMAL"
        )
        predicted_domains = [
            label for label in DOMAIN_LABELS if predictions[label][index]
        ]
        predicted_domain = "+".join(predicted_domains) if predicted_domains else "NORMAL"
        confusion[f"{true_domain}->{predicted_domain}"] += 1
    return {
        "sample_count": len(labels),
        "metrics": metrics,
        "normal_condition_false_positive_rate": round(normal_fpr, 10),
        "domain_confusion": dict(sorted(confusion.items())),
        "per_anomaly_family": scenario_results,
        "per_station_family": station_results,
        "per_parameter_family": parameter_results,
        "hard_negative_results": hard_results,
        "thresholds": {key: round(float(value), 10) for key, value in thresholds.items()},
    }


def _threshold_search(
    labels: list[SyntheticAnomalyMetadata],
    scores: dict[str, np.ndarray],
) -> tuple[dict[str, float], dict[str, Any]]:
    truth = _truth_arrays(labels)
    thresholds: dict[str, float] = {}
    searches: dict[str, Any] = {}
    candidates = np.round(np.arange(0.05, 0.951, 0.01), 2)
    for label in DOMAIN_LABELS:
        rows = []
        for threshold in candidates:
            metric = _binary_metrics(
                truth[label],
                scores[label],
                scores[label] >= threshold,
            )
            rows.append(
                {
                    "threshold": float(threshold),
                    "f1": metric["f1"],
                    "false_positive_rate": metric["false_positive_rate"],
                    "recall": metric["recall"],
                }
            )
        selected = max(
            rows,
            key=lambda row: (
                row["f1"],
                -row["false_positive_rate"],
                row["recall"],
                -abs(row["threshold"] - 0.5),
                row["threshold"],
            ),
        )
        thresholds[label] = selected["threshold"]
        searches[label] = {
            "selection_rule": (
                "MAX_F1_THEN_LOWER_FPR_THEN_HIGHER_RECALL_THEN_CLOSER_TO_0.5"
            ),
            "candidate_count": len(rows),
            "selected": selected,
            "top_candidates": sorted(
                rows,
                key=lambda row: (
                    -row["f1"],
                    row["false_positive_rate"],
                    -row["recall"],
                    abs(row["threshold"] - 0.5),
                ),
            )[:10],
        }
    return thresholds, searches


def _baseline_scores(
    records: list[SyntheticAnomalyModelRecord],
) -> tuple[dict[str, np.ndarray], float]:
    data_quality = np.zeros(len(records), dtype=np.float64)
    weather = np.zeros(len(records), dtype=np.float64)
    started = perf_counter()
    for index, record in enumerate(records):
        prediction = score_statistical_window(_record_to_window(record))
        if prediction.anomaly_domain is AnomalyDomain.DATA_QUALITY_ANOMALY:
            data_quality[index] = 1.0
        if prediction.anomaly_domain is AnomalyDomain.WEATHER_BEHAVIOR_ANOMALY:
            weather[index] = max(float(prediction.score or 0.0), 3.5)
        elif prediction.score is not None:
            weather[index] = float(prediction.score)
    return {
        "DATA_QUALITY_ANOMALY": data_quality,
        "WEATHER_BEHAVIOR_ANOMALY": weather,
    }, perf_counter() - started


def _selection_score(report: dict[str, Any]) -> float:
    metrics = report["metrics"]
    domain_f1 = np.mean(
        [
            metrics["DATA_QUALITY_ANOMALY"]["f1"],
            metrics["WEATHER_BEHAVIOR_ANOMALY"]["f1"],
            metrics["OVERALL_ANOMALY"]["f1"],
        ]
    )
    return float(
        domain_f1 - 0.25 * report["normal_condition_false_positive_rate"]
    )


def _calibration_diagnostics(
    labels: list[SyntheticAnomalyMetadata],
    scores: dict[str, np.ndarray],
) -> dict[str, Any]:
    truth = _truth_arrays(labels)
    result: dict[str, Any] = {
        "method": "NONE",
        "fit_source": "NOT_APPLICABLE",
        "field_calibration_claim": False,
        "score_interpretation": (
            "SYNTHETIC_DEVELOPMENT_MODEL_SCORE_NOT_FIELD_PROBABILITY"
        ),
        "diagnostics_on_validation_only": {},
    }
    for label in DOMAIN_LABELS:
        target = truth[label].astype(np.float64)
        score = scores[label]
        bins = []
        ece = 0.0
        for lower in np.arange(0.0, 1.0, 0.1):
            upper = lower + 0.1
            mask = (score >= lower) & (
                score <= upper if upper >= 1.0 else score < upper
            )
            if not np.any(mask):
                continue
            mean_score = float(np.mean(score[mask]))
            positive_rate = float(np.mean(target[mask]))
            count = int(np.sum(mask))
            ece += count / len(score) * abs(mean_score - positive_rate)
            bins.append(
                {
                    "lower": round(float(lower), 2),
                    "upper": round(float(upper), 2),
                    "count": count,
                    "mean_score": round(mean_score, 10),
                    "positive_rate": round(positive_rate, 10),
                }
            )
        result["diagnostics_on_validation_only"][label] = {
            "brier_score": round(float(np.mean((score - target) ** 2)), 10),
            "expected_calibration_error": round(ece, 10),
            "bins": bins,
        }
    return result


def _error_analysis(
    labels: list[SyntheticAnomalyMetadata],
    scores: dict[str, np.ndarray],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    truth = _truth_arrays(labels)
    predicted = {
        label: scores[label] >= thresholds[label] for label in DOMAIN_LABELS
    }
    examples: dict[str, Any] = {}
    for label in DOMAIN_LABELS:
        false_positive_indexes = np.flatnonzero(~truth[label] & predicted[label])
        false_negative_indexes = np.flatnonzero(truth[label] & ~predicted[label])
        examples[label] = {
            "false_positives": [
                {
                    "window_id": labels[index].window_id,
                    "scenario_family": labels[index].scenario_family,
                    "score": round(float(scores[label][index]), 10),
                }
                for index in false_positive_indexes[:50]
            ],
            "false_negatives": [
                {
                    "window_id": labels[index].window_id,
                    "scenario_family": labels[index].scenario_family,
                    "score": round(float(scores[label][index]), 10),
                }
                for index in false_negative_indexes[:50]
            ],
            "false_positive_count": len(false_positive_indexes),
            "false_negative_count": len(false_negative_indexes),
        }
    dq = predicted["DATA_QUALITY_ANOMALY"]
    weather = predicted["WEATHER_BEHAVIOR_ANOMALY"]
    domain_confusions = Counter()
    for index, item in enumerate(labels):
        if item.data_quality_anomaly and weather[index]:
            domain_confusions["DATA_QUALITY_AS_WEATHER"] += 1
        if item.weather_behavior_anomaly and dq[index]:
            domain_confusions["WEATHER_AS_DATA_QUALITY"] += 1
    scenario_failures: dict[str, dict[str, int]] = {}
    for scenario in sorted({item.scenario_family for item in labels}):
        indexes = np.asarray(
            [item.scenario_family == scenario for item in labels], dtype=bool
        )
        overall_truth = truth["OVERALL_ANOMALY"][indexes]
        overall_predicted = (dq | weather)[indexes]
        scenario_failures[scenario] = {
            "sample_count": int(np.sum(indexes)),
            "false_positive_count": int(
                np.sum(~overall_truth & overall_predicted)
            ),
            "false_negative_count": int(
                np.sum(overall_truth & ~overall_predicted)
            ),
        }
    return {
        "analysis_method": "DETERMINISTIC_LOCAL_NO_EXTERNAL_MODEL",
        "configuration_changed_after_error_analysis": False,
        "examples": examples,
        "domain_confusions": dict(sorted(domain_confusions.items())),
        "scenario_failures": scenario_failures,
        "requested_failure_categories": {
            "legitimate_extreme_false_positives": sum(
                scenario_failures[name]["false_positive_count"]
                for name in (
                    "LEGITIMATE_EXTREME_RAINFALL",
                    "LEGITIMATE_RIVER_LEVEL_EXTREME",
                )
            ),
            "gradual_anomaly_false_negatives": scenario_failures[
                "PERSISTENT_RAINFALL_DEVIATION"
            ]["false_negative_count"],
            "abrupt_anomaly_false_negatives": sum(
                scenario_failures[name]["false_negative_count"]
                for name in (
                    "RAINFALL_VALUE_OUTLIER",
                    "RAINFALL_RATE_CHANGE",
                    "RIVER_LEVEL_CHANGE_ANOMALY",
                    "SENSOR_DISCONTINUITY",
                )
            ),
            "missingness_related_errors": (
                scenario_failures["MISSINGNESS_BURST"]["false_negative_count"]
                + scenario_failures["BENIGN_MISSING_DATA"]["false_positive_count"]
            ),
        },
        "production_validation": "NOT_VALIDATED",
    }


def _configuration_hash(artifact: ScratchDualLogisticArtifact) -> str:
    payload = {
        "configuration_version": CONFIGURATION_VERSION,
        "feature_version": artifact.feature_version,
        "preprocessing_version": artifact.preprocessing_version,
        "feature_names": artifact.feature_names,
        "scaler_mean": artifact.scaler_mean,
        "scaler_scale": artifact.scaler_scale,
        "heads": {
            name: head.model_dump(mode="json")
            for name, head in sorted(artifact.heads.items())
        },
        "thresholds": artifact.thresholds,
        "training_configuration": artifact.training_configuration,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _register_artifact(
    artifact_path: Path,
    artifact: ScratchDualLogisticArtifact,
    manifest_path: Path,
) -> ArtifactManifest:
    manifest = ArtifactManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=artifact.artifact_version,
        sha256=file_sha256(artifact_path),
        training_dataset_hash=artifact.dataset_hash,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        training_timestamp=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        random_seed=artifact.training_seed,
        framework_versions={
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        intended_component="anomaly_detector",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    artifacts = [
        item
        for item in manifest.artifacts
        if not (
            item.artifact_name == artifact_path.name
            and item.intended_component == "anomaly_detector"
        )
    ]
    artifacts.append(metadata)
    updated = manifest.model_copy(
        update={
            "artifacts": sorted(
                artifacts,
                key=lambda item: (item.intended_component, item.artifact_name),
            )
        }
    )
    _write_json_atomic(manifest_path, updated.model_dump(mode="json"))
    return updated


def _provenance(
    artifact_path: Path,
    artifact: ScratchDualLogisticArtifact,
    configuration_hash: str,
    training_records: list[SyntheticAnomalyModelRecord],
) -> AnomalyArtifactProvenance:
    return AnomalyArtifactProvenance(
        artifact_name=artifact_path.name,
        model_version=artifact.artifact_version,
        model_family="CUSTOM_PROJECT_MODEL",
        dataset_hash=artifact.dataset_hash,
        training_dataset_hash=artifact.training_dataset_hash,
        validation_dataset_hash=artifact.validation_dataset_hash,
        feature_version=artifact.feature_version,
        baseline_version=artifact.preprocessing_version,
        generator_version=artifact.generator_version,
        configuration_version=CONFIGURATION_VERSION,
        configuration_sha256=configuration_hash,
        threshold_configuration=artifact.thresholds,
        library_version=sklearn.__version__,
        random_seed=artifact.training_seed,
        artifact_hash=file_sha256(artifact_path),
        training_start_at=min(item.timestamps[0] for item in training_records),
        training_end_at=max(item.timestamps[-1] for item in training_records),
        station_scope=sorted({item.station_id for item in training_records}),
        policy_status=ArtifactPolicyStatus.COMPLIANT,
        source="PROJECT_TRAINED",
        development_status="DEVELOPMENT_ONLY",
        pretrained_model_used=False,
        external_model_used=False,
    )


def load_frozen_anomaly_artifact(
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    *,
    provenance_path: Path | str = DEFAULT_PROVENANCE_PATH,
    manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> ScratchDualLogisticArtifact:
    artifact_file = Path(artifact_path)
    provenance = AnomalyArtifactProvenance.model_validate_json(
        Path(provenance_path).read_text(encoding="utf-8")
    )
    manifest = ArtifactManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8")
    )
    config = AnomalyDetectionConfig(
        feature_version=FEATURE_VERSION,
        model_version=MODEL_VERSION,
    )
    authorize_anomaly_artifact(
        artifact_file,
        provenance,
        manifest,
        config=config,
    )
    artifact = ScratchDualLogisticArtifact.model_validate_json(
        artifact_file.read_text(encoding="utf-8")
    )
    if provenance.configuration_sha256 != _configuration_hash(artifact):
        raise ValueError("anomaly artifact configuration hash does not match provenance")
    return artifact


def freeze_anomaly_development(
    *,
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Evaluate baseline, train/select candidate, and freeze without test access."""

    root = Path(output_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    paths = _paths(root)
    if any(path.exists() for path in paths.values()):
        existing = sorted(path.name for path in paths.values() if path.exists())
        raise RuntimeError(f"anomaly development outputs already exist: {existing}")
    dataset = Path(dataset_root).resolve()
    manifest = _load_manifest(dataset)
    _verify_development_split_hashes(dataset, manifest)
    protected_before = protected_artifact_snapshot(ARTIFACT_ROOT)
    _assert_frozen_core(protected_before)
    train_records, train_labels = _load_split(dataset, "train")
    validation_records, validation_labels = _load_split(dataset, "validation")
    if len(train_records) != manifest["split_counts"]["train"] or len(
        validation_records
    ) != manifest["split_counts"]["validation"]:
        raise ValueError("development split counts do not match manifest")

    baseline_scores, baseline_seconds = _baseline_scores(validation_records)
    baseline_thresholds = {
        "DATA_QUALITY_ANOMALY": 0.5,
        "WEATHER_BEHAVIOR_ANOMALY": 3.5,
    }
    baseline_report = _evaluate(
        validation_labels,
        baseline_scores,
        baseline_thresholds,
    )
    baseline_report.update(
        {
            "baseline": "STATISTICAL_ANOMALY_BASELINE",
            "baseline_version": "statistical-anomaly-detector-v1",
            "evaluation_split": "validation",
            "inference_seconds": round(baseline_seconds, 10),
            "test_records_accessed": False,
        }
    )

    training_started = perf_counter()
    artifact = fit_scratch_dual_logistic(
        train_records,
        train_labels,
        dataset_hash=manifest["dataset_sha256"],
        training_dataset_hash=manifest["split_sha256"]["train"],
        validation_dataset_hash=manifest["split_sha256"]["validation"],
        seed=RANDOM_SEED,
    )
    training_seconds = perf_counter() - training_started
    validation_matrix_started = perf_counter()
    validation_matrix = feature_matrix(validation_records)
    validation_feature_seconds = perf_counter() - validation_matrix_started
    score_started = perf_counter()
    candidate_scores = score_feature_matrix(artifact, validation_matrix)
    candidate_score_seconds = perf_counter() - score_started
    thresholds, threshold_search = _threshold_search(
        validation_labels,
        candidate_scores,
    )
    artifact = artifact.model_copy(update={"thresholds": thresholds})
    candidate_report = _evaluate(validation_labels, candidate_scores, thresholds)
    candidate_report.update(
        {
            "model": MODEL_FAMILY,
            "model_version": MODEL_VERSION,
            "evaluation_split": "validation",
            "test_records_accessed": False,
        }
    )
    baseline_objective = _selection_score(baseline_report)
    candidate_objective = _selection_score(candidate_report)
    selected_model = (
        MODEL_FAMILY
        if candidate_objective > baseline_objective
        else "STATISTICAL_ANOMALY_BASELINE"
    )
    if selected_model != MODEL_FAMILY:
        raise RuntimeError(
            "scratch learned candidate did not outperform the statistical baseline"
        )
    release_checks = {
        "overall_f1": candidate_report["metrics"]["OVERALL_ANOMALY"]["f1"]
        >= 0.75,
        "data_quality_f1": candidate_report["metrics"]["DATA_QUALITY_ANOMALY"][
            "f1"
        ]
        >= 0.65,
        "weather_behavior_f1": candidate_report["metrics"][
            "WEATHER_BEHAVIOR_ANOMALY"
        ]["f1"]
        >= 0.65,
        "normal_false_positive_rate": candidate_report[
            "normal_condition_false_positive_rate"
        ]
        <= 0.15,
        "hidden_label_isolation": True,
        "validation_only_selection": True,
        "test_records_not_accessed": True,
        "no_pretrained_models": not artifact.pretrained_models,
        "no_external_models": not artifact.open_weight_models,
        "network_access_disabled": artifact.network_access is False,
    }
    if not all(release_checks.values()):
        failed = [name for name, passed in release_checks.items() if not passed]
        raise RuntimeError(f"anomaly validation release checks failed: {failed}")

    calibration = _calibration_diagnostics(validation_labels, candidate_scores)
    validation_errors = _error_analysis(
        validation_labels,
        candidate_scores,
        thresholds,
    )
    performance = {
        "hardware": {
            "device": "CPU",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "training": {
            "samples": len(train_records),
            "seconds": round(training_seconds, 10),
            "samples_per_second": round(
                len(train_records) / training_seconds, 10
            ),
        },
        "validation": {
            "samples": len(validation_records),
            "feature_extraction_seconds": round(validation_feature_seconds, 10),
            "model_scoring_seconds": round(candidate_score_seconds, 10),
            "windows_per_second": round(
                len(validation_records)
                / max(validation_feature_seconds + candidate_score_seconds, 1e-12),
                10,
            ),
        },
        "scope": "LOCAL_ENGINEERING_MEASUREMENT_NOT_PRODUCTION_THROUGHPUT",
    }
    artifact_path = paths["artifact"]
    _write_json_atomic(artifact_path, artifact.model_dump(mode="json"))
    configuration_hash = _configuration_hash(artifact)
    artifact_manifest = _register_artifact(
        artifact_path,
        artifact,
        Path(artifact_manifest_path).resolve(),
    )
    provenance = _provenance(
        artifact_path,
        artifact,
        configuration_hash,
        train_records,
    )
    _write_json_atomic(paths["provenance"], provenance.model_dump(mode="json"))
    load_frozen_anomaly_artifact(
        artifact_path,
        provenance_path=paths["provenance"],
        manifest_path=Path(artifact_manifest_path).resolve(),
    )
    _write_json_atomic(paths["baseline"], baseline_report)
    _write_json_atomic(
        paths["validation"],
        {
            **candidate_report,
            "baseline_selection_score": round(baseline_objective, 10),
            "candidate_selection_score": round(candidate_objective, 10),
            "selected_model": selected_model,
            "selection_rule": (
                "MEAN_DOMAIN_AND_OVERALL_F1_MINUS_QUARTER_NORMAL_FPR"
            ),
            "release_checks": release_checks,
            "production_validation": "NOT_VALIDATED",
        },
    )
    _write_json_atomic(
        paths["thresholds"],
        {
            "fit_source": "VALIDATION_ONLY",
            "thresholds": thresholds,
            "search": threshold_search,
            "test_records_accessed": False,
        },
    )
    _write_json_atomic(paths["calibration"], calibration)
    _write_json_atomic(paths["validation_errors"], validation_errors)
    _write_json_atomic(paths["performance"], performance)
    protected_test = {
        "model_input_relative_path": "model_inputs/test.jsonl",
        "model_input_sha256": manifest["split_sha256"]["test"],
        "hidden_metadata_relative_path": "hidden_generator_metadata/test.jsonl",
        "hidden_metadata_sha256": manifest["hidden_metadata_sha256"]["test"],
        "sample_count": manifest["split_counts"]["test"],
        "evaluation_invocation_count": 0,
    }
    development = FrozenAnomalyDevelopment(
        dataset_id=manifest["dataset_id"],
        dataset_version=manifest["dataset_version"],
        dataset_root=str(dataset),
        dataset_sha256=manifest["dataset_sha256"],
        generator_version=manifest["generator_version"],
        artifact_name=artifact_path.name,
        artifact_sha256=file_sha256(artifact_path),
        provenance_name=paths["provenance"].name,
        provenance_sha256=file_sha256(paths["provenance"]),
        configuration_version=CONFIGURATION_VERSION,
        configuration_sha256=configuration_hash,
        selected_model=selected_model,
        thresholds=thresholds,
        validation_metrics=candidate_report["metrics"],
        validation_release_checks=release_checks,
        protected_final_test=protected_test,
        source_hashes=_source_hashes(),
        protected_artifacts=protected_before,
        artifact_manifest_sha256=file_sha256(
            Path(artifact_manifest_path).resolve()
        ),
        frozen_at="2026-09-24T10:00:00Z",
        test_records_loaded_for_selection=False,
    )
    _write_json_atomic(paths["development"], development.model_dump(mode="json"))
    if protected_artifact_snapshot(ARTIFACT_ROOT) != protected_before:
        raise RuntimeError("a protected earlier-phase artifact changed during freeze")
    del train_records, train_labels, validation_records, validation_labels
    return {
        "status": "DEVELOPMENT_FREEZE_COMPLETE",
        "artifact": str(artifact_path),
        "artifact_sha256": file_sha256(artifact_path),
        "dataset_sha256": manifest["dataset_sha256"],
        "selected_model": selected_model,
        "thresholds": thresholds,
        "baseline_validation_metrics": baseline_report["metrics"],
        "validation_metrics": candidate_report["metrics"],
        "normal_condition_false_positive_rate": candidate_report[
            "normal_condition_false_positive_rate"
        ],
        "production_validation": "NOT_VALIDATED",
        "test_records_accessed": False,
    }


def _verify_frozen_state(
    development: FrozenAnomalyDevelopment,
    paths: dict[str, Path],
    artifact_manifest_path: Path,
) -> dict[str, bool]:
    return {
        "artifact": file_sha256(paths["artifact"])
        == development.artifact_sha256,
        "provenance": file_sha256(paths["provenance"])
        == development.provenance_sha256,
        "configuration": _configuration_hash(
            ScratchDualLogisticArtifact.model_validate_json(
                paths["artifact"].read_text(encoding="utf-8")
            )
        )
        == development.configuration_sha256,
        "artifact_manifest": file_sha256(artifact_manifest_path)
        == development.artifact_manifest_sha256,
        "source_files": _source_hashes() == development.source_hashes,
        "protected_components": protected_artifact_snapshot(ARTIFACT_ROOT)
        == development.protected_artifacts,
    }


def _claim_receipt(path: Path, development: FrozenAnomalyDevelopment) -> None:
    if path.exists():
        raise RuntimeError("anomaly final reevaluation is prohibited by one-shot receipt")
    claim = {
        "schema_version": "1.0",
        "status": "FINAL_EVALUATION_CLAIMED",
        "phase": development.phase,
        "dataset_sha256": development.dataset_sha256,
        "model_sha256": development.artifact_sha256,
        "configuration_sha256": development.configuration_sha256,
        "generator_version": development.generator_version,
        "test_set_sha256": development.protected_final_test[
            "model_input_sha256"
        ],
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
        "timestamp": "2026-09-24T11:00:00Z",
        "final_metrics": None,
    }
    _write_json_atomic(path, claim, exclusive=True)


def finalize_anomaly_evaluation(
    *,
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
    output_directory: Path | str = ARTIFACT_ROOT,
    artifact_manifest_path: Path | str = DEFAULT_ARTIFACT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Claim and score the protected synthetic anomaly test exactly once."""

    root = Path(output_directory).resolve()
    paths = _paths(root)
    if paths["receipt"].exists():
        raise RuntimeError("anomaly final reevaluation is prohibited by one-shot receipt")
    development = FrozenAnomalyDevelopment.model_validate_json(
        paths["development"].read_text(encoding="utf-8")
    )
    dataset = Path(dataset_root).resolve()
    if dataset != Path(development.dataset_root).resolve():
        raise ValueError("dataset root differs from frozen development manifest")
    manifest = _load_manifest(dataset)
    artifact_manifest = Path(artifact_manifest_path).resolve()
    checks = _verify_frozen_state(development, paths, artifact_manifest)
    if not all(checks.values()):
        raise RuntimeError(
            "frozen anomaly state changed before final test: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    descriptor = development.protected_final_test
    model_input_path = dataset / descriptor["model_input_relative_path"]
    metadata_path = dataset / descriptor["hidden_metadata_relative_path"]
    if (
        file_sha256(model_input_path) != descriptor["model_input_sha256"]
        or file_sha256(metadata_path) != descriptor["hidden_metadata_sha256"]
    ):
        raise RuntimeError("protected anomaly test files changed before evaluation")
    _claim_receipt(paths["receipt"], development)
    try:
        artifact = load_frozen_anomaly_artifact(
            paths["artifact"],
            provenance_path=paths["provenance"],
            manifest_path=artifact_manifest,
        )
        test_records, test_labels = _load_split(dataset, "test")
        if len(test_records) != descriptor["sample_count"]:
            raise ValueError("protected anomaly test count changed")
        feature_started = perf_counter()
        test_matrix = feature_matrix(test_records)
        feature_seconds = perf_counter() - feature_started
        score_started = perf_counter()
        scores = score_feature_matrix(artifact, test_matrix)
        scoring_seconds = perf_counter() - score_started
        report = _evaluate(test_labels, scores, artifact.thresholds)
        errors = _error_analysis(test_labels, scores, artifact.thresholds)
        final_metrics = {
            "schema_version": "1.0",
            "phase": development.phase,
            "evaluation_label": "FINAL_SYNTHETIC_ANOMALY_HOLDOUT_EVALUATION",
            "evaluation_split": "test",
            "evaluation_invocation_count": 1,
            "dataset_sha256": development.dataset_sha256,
            "test_set_sha256": descriptor["model_input_sha256"],
            "artifact_sha256": development.artifact_sha256,
            "configuration_sha256": development.configuration_sha256,
            "selected_model": development.selected_model,
            "thresholds": development.thresholds,
            **report,
            "performance": {
                "feature_extraction_seconds": round(feature_seconds, 10),
                "model_scoring_seconds": round(scoring_seconds, 10),
                "windows_per_second": round(
                    len(test_records)
                    / max(feature_seconds + scoring_seconds, 1e-12),
                    10,
                ),
                "scope": "LOCAL_ENGINEERING_MEASUREMENT_NOT_PRODUCTION_THROUGHPUT",
            },
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_model_selection": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_calibration": False,
            "calibration": "NONE_VALIDATION_THRESHOLDS_ONLY",
            "score_interpretation": (
                "SYNTHETIC_DEVELOPMENT_MODEL_SCORE_NOT_FIELD_PROBABILITY"
            ),
            "production_validation": "NOT_VALIDATED",
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
        }
        _write_json_atomic(paths["metrics"], final_metrics)
        _write_json_atomic(
            paths["error_report"],
            {
                "schema_version": "1.0",
                "phase": development.phase,
                "final_test_failure_analysis": errors,
                "configuration_changed_after_failure_analysis": False,
                "production_validation": "NOT_VALIDATED",
            },
        )
        final_checks = _verify_frozen_state(
            development,
            paths,
            artifact_manifest,
        )
        receipt = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_COMPLETE",
            "phase": development.phase,
            "dataset_sha256": development.dataset_sha256,
            "model_sha256": development.artifact_sha256,
            "configuration_sha256": development.configuration_sha256,
            "generator_version": development.generator_version,
            "test_set_sha256": descriptor["model_input_sha256"],
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "timestamp": "2026-09-24T11:00:00Z",
            "final_metrics_file": paths["metrics"].name,
            "final_metrics_sha256": file_sha256(paths["metrics"]),
            "error_report_file": paths["error_report"].name,
            "error_report_sha256": file_sha256(paths["error_report"]),
            "frozen_state_checks": final_checks,
            "configuration_frozen_before_test": True,
            "configuration_changed_after_freeze": False,
            "test_used_for_model_selection": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_calibration": False,
            "final_metrics": report["metrics"],
            "normal_condition_false_positive_rate": report[
                "normal_condition_false_positive_rate"
            ],
            "production_validation": "NOT_VALIDATED",
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
        }
        _write_json_atomic(paths["receipt"], receipt)
        return receipt
    except Exception as error:
        failure = {
            "schema_version": "1.0",
            "status": "FINAL_EVALUATION_FAILED_AFTER_CLAIM",
            "phase": development.phase,
            "dataset_sha256": development.dataset_sha256,
            "model_sha256": development.artifact_sha256,
            "configuration_sha256": development.configuration_sha256,
            "generator_version": development.generator_version,
            "test_set_sha256": descriptor["model_input_sha256"],
            "evaluation_invocation_count": 1,
            "rerun_permitted": False,
            "timestamp": "2026-09-24T11:00:00Z",
            "error_type": type(error).__name__,
            "error": str(error),
            "final_metrics": None,
            "production_validation": "NOT_VALIDATED",
        }
        _write_json_atomic(paths["receipt"], failure)
        raise


__all__ = [
    "ARTIFACT_ROOT",
    "CONFIGURATION_VERSION",
    "DEFAULT_ARTIFACT_MANIFEST_PATH",
    "DEFAULT_ARTIFACT_PATH",
    "DEFAULT_DATASET_ROOT",
    "DEFAULT_DEVELOPMENT_MANIFEST_PATH",
    "DEFAULT_FINAL_RECEIPT_PATH",
    "FrozenAnomalyDevelopment",
    "file_sha256",
    "finalize_anomaly_evaluation",
    "freeze_anomaly_development",
    "load_frozen_anomaly_artifact",
    "protected_artifact_snapshot",
]
