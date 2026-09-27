"""Phase 23 synthetic anomaly validation and one-shot governance tests."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from app.ml.components.anomaly_features import extract_anomaly_features
from app.ml.contracts import AnomalyInputWindow, WeatherObservation
from app.ml.data.synthetic_anomaly.generator import (
    SCENARIO_FAMILIES,
    SyntheticAnomalyGeneratorConfig,
    build_synthetic_window,
    generate_synthetic_anomaly_dataset,
    load_hidden_metadata,
    load_model_records,
)
from app.ml.models.anomaly_window_model import (
    FEATURE_NAMES,
    extract_window_feature_vector,
    feature_matrix,
    score_feature_matrix,
)
from app.ml.training.anomaly_synthetic_validation import (
    DEFAULT_ARTIFACT_MANIFEST_PATH,
    finalize_anomaly_evaluation,
    freeze_anomaly_development,
    load_frozen_anomaly_artifact,
)


SMALL_CONFIG = SyntheticAnomalyGeneratorConfig(
    train_count=512,
    validation_count=128,
    test_count=128,
)


@pytest.fixture(scope="module")
def phase23_test_root():
    parent = Path(__file__).resolve().parents[3] / ".phase23-test-tmp"
    root = parent / f"case-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


@pytest.fixture(scope="module")
def small_dataset(phase23_test_root):
    return generate_synthetic_anomaly_dataset(
        phase23_test_root / "dataset",
        config=SMALL_CONFIG,
        register=False,
    )


@pytest.fixture(scope="module")
def frozen_workflow(phase23_test_root, small_dataset):
    artifact_directory = phase23_test_root / "artifacts"
    artifact_directory.mkdir()
    manifest_path = artifact_directory / "manifest.json"
    shutil.copy2(DEFAULT_ARTIFACT_MANIFEST_PATH, manifest_path)
    result = freeze_anomaly_development(
        dataset_root=small_dataset.output_directory,
        output_directory=artifact_directory,
        artifact_manifest_path=manifest_path,
    )
    return {
        "dataset": small_dataset,
        "artifacts": artifact_directory,
        "manifest": manifest_path,
        "freeze": result,
    }


@pytest.fixture(scope="module")
def finalized_workflow(frozen_workflow):
    receipt = finalize_anomaly_evaluation(
        dataset_root=frozen_workflow["dataset"].output_directory,
        output_directory=frozen_workflow["artifacts"],
        artifact_manifest_path=frozen_workflow["manifest"],
    )
    return {**frozen_workflow, "receipt": receipt}


def test_generator_reproducibility_supported_fields_and_scenario_truth():
    for index, scenario in enumerate(SCENARIO_FAMILIES):
        first = build_synthetic_window("validation", index, SMALL_CONFIG)
        second = build_synthetic_window("validation", index, SMALL_CONFIG)
        assert first == second
        record, metadata, annotation = first
        assert metadata.scenario_family == scenario
        assert metadata.overall_anomaly == (
            metadata.data_quality_anomaly or metadata.weather_behavior_anomaly
        )
        assert annotation.target_id == record.window_id
        assert set(record.model_dump()) == {
            "window_id",
            "station_id",
            "timestamps",
            "rainfall_mm",
            "river_level_m",
            "split",
            "window_sha256",
        }
        assert all(
            value is None or np.isfinite(value)
            for value in [*record.rainfall_mm, *record.river_level_m]
        )


def test_dataset_grouped_split_integrity_hidden_label_isolation_and_hashes(
    small_dataset,
):
    quality = json.loads(small_dataset.quality_report_path.read_text(encoding="utf-8"))
    manifest = json.loads(small_dataset.manifest_path.read_text(encoding="utf-8"))
    assert quality["valid"] is True
    assert quality["leakage_checks"]["status"] == "PASS"
    assert quality["hidden_metadata_isolation"]["detector_receives_hidden_metadata"] is False
    assert quality["hidden_metadata_isolation"]["label_derived_from_detector_output"] is False
    assert quality["deterministic_replay"]["status"] == "PASS"
    assert quality["window_integrity"]["unique_window_hashes"] == 768
    assert manifest["split_counts"] == {
        "train": 512,
        "validation": 128,
        "test": 128,
    }
    assert manifest["dataset_sha256"] == small_dataset.dataset_sha256
    assert hashlib.sha256(
        small_dataset.model_input_paths["test"].read_bytes()
    ).hexdigest() == manifest["split_sha256"]["test"]


def test_feature_extraction_is_finite_deterministic_and_has_no_label_input():
    record, metadata, _ = build_synthetic_window("train", 11, SMALL_CONFIG)
    first = extract_window_feature_vector(record)
    second = extract_window_feature_vector(record)
    assert np.array_equal(first, second)
    assert first.shape == (len(FEATURE_NAMES),)
    assert np.isfinite(first).all()
    changed_metadata = metadata.model_copy(
        update={
            "scenario_family": "CHANGED_HIDDEN_VALUE",
            "data_quality_anomaly": False,
            "overall_anomaly": False,
            "anomaly_type": None,
            "anomaly_domain": None,
        }
    )
    assert changed_metadata.scenario_family != metadata.scenario_family
    assert np.array_equal(first, extract_window_feature_vector(record))


def test_causal_temporal_features_and_missingness_handling():
    record, _, _ = build_synthetic_window("train", 0, SMALL_CONFIG)
    observations = [
        WeatherObservation(
            observation_id=f"obs-{index}",
            station_id=record.station_id,
            observed_at=timestamp,
            rainfall_mm=value,
            river_level_m=river,
        )
        for index, (timestamp, value, river) in enumerate(
            zip(record.timestamps, record.rainfall_mm, record.river_level_m)
        )
    ]
    window = AnomalyInputWindow(
        station_id=record.station_id,
        observations=observations,
        start_at=record.timestamps[0],
        end_at=record.timestamps[-1],
    )
    rows = extract_anomaly_features(window)
    assert rows[0].rainfall.reference_count == 0
    assert rows[1].rainfall.rolling_median == observations[0].rainfall_mm
    altered = observations.copy()
    altered[-1] = altered[-1].model_copy(update={"rainfall_mm": 10_000.0})
    altered_rows = extract_anomaly_features(
        window.model_copy(update={"observations": altered})
    )
    assert rows[-1].rainfall.rolling_median == altered_rows[-1].rainfall.rolling_median
    missing_record, _, _ = build_synthetic_window("train", 9, SMALL_CONFIG)
    vector = extract_window_feature_vector(missing_record)
    index = FEATURE_NAMES.index("maximum_missing_run_ratio")
    assert vector[index] == pytest.approx(5 / 24)


def test_baseline_first_candidate_selection_threshold_freeze_and_provenance(
    frozen_workflow,
):
    result = frozen_workflow["freeze"]
    assert result["selected_model"] == "LOCAL_SCRATCH_DUAL_LOGISTIC"
    assert result["baseline_validation_metrics"]["OVERALL_ANOMALY"]["f1"] < (
        result["validation_metrics"]["OVERALL_ANOMALY"]["f1"]
    )
    assert result["test_records_accessed"] is False
    artifact = load_frozen_anomaly_artifact(
        frozen_workflow["artifacts"] / "anomaly_model_v1.json",
        provenance_path=(
            frozen_workflow["artifacts"] / "anomaly_model_v1.provenance.json"
        ),
        manifest_path=frozen_workflow["manifest"],
    )
    assert artifact.initialization == "SCRATCH_NO_PRETRAINED_WEIGHTS"
    assert artifact.pretrained_models == []
    assert artifact.open_weight_models == []
    assert artifact.network_access is False
    thresholds = json.loads(
        (
            frozen_workflow["artifacts"]
            / "anomaly_model_v1.threshold_search.json"
        ).read_text(encoding="utf-8")
    )
    assert thresholds["fit_source"] == "VALIDATION_ONLY"
    assert thresholds["test_records_accessed"] is False


def test_serialization_round_trip_and_deterministic_inference(frozen_workflow):
    artifact = load_frozen_anomaly_artifact(
        frozen_workflow["artifacts"] / "anomaly_model_v1.json",
        provenance_path=(
            frozen_workflow["artifacts"] / "anomaly_model_v1.provenance.json"
        ),
        manifest_path=frozen_workflow["manifest"],
    )
    records = load_model_records(
        frozen_workflow["dataset"].model_input_paths["validation"]
    )[:32]
    matrix = feature_matrix(records)
    first = score_feature_matrix(artifact, matrix)
    second = score_feature_matrix(artifact, matrix)
    assert all(np.array_equal(first[label], second[label]) for label in first)


def test_one_shot_receipt_and_domain_metrics(finalized_workflow):
    receipt = finalized_workflow["receipt"]
    assert receipt["status"] == "FINAL_EVALUATION_COMPLETE"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert all(receipt["frozen_state_checks"].values())
    assert set(receipt["final_metrics"]) == {
        "DATA_QUALITY_ANOMALY",
        "WEATHER_BEHAVIOR_ANOMALY",
        "OVERALL_ANOMALY",
    }
    with pytest.raises(RuntimeError, match="one-shot receipt"):
        finalize_anomaly_evaluation(
            dataset_root=finalized_workflow["dataset"].output_directory,
            output_directory=finalized_workflow["artifacts"],
            artifact_manifest_path=finalized_workflow["manifest"],
        )


def test_hard_negatives_and_error_analysis_are_complete(finalized_workflow):
    metrics = json.loads(
        (
            finalized_workflow["artifacts"] / "anomaly_model_v1.metrics.json"
        ).read_text(encoding="utf-8")
    )
    required = {
        "LEGITIMATE_EXTREME_RAINFALL",
        "LEGITIMATE_EXTREME_RIVER_LEVEL",
        "ABRUPT_BUT_LEGITIMATE_WEATHER_TRANSITION",
        "ISOLATED_LARGE_BUT_LEGITIMATE_MEASUREMENT",
        "NORMAL_HEAVY_RAIN_SEQUENCE",
        "MISSING_DATA_WITHOUT_BEHAVIORAL_ANOMALY",
        "BEHAVIORAL_ANOMALY_WITHOUT_DATA_QUALITY_FAILURE",
        "DATA_QUALITY_FAILURE_WITHOUT_WEATHER_ANOMALY",
    }
    assert set(metrics["hard_negative_results"]) == required
    error_report = json.loads(
        (
            finalized_workflow["artifacts"] / "anomaly_model_v1.error_report.json"
        ).read_text(encoding="utf-8")
    )["final_test_failure_analysis"]
    assert error_report["analysis_method"] == "DETERMINISTIC_LOCAL_NO_EXTERNAL_MODEL"
    assert error_report["configuration_changed_after_error_analysis"] is False
    assert set(error_report["requested_failure_categories"]) == {
        "legitimate_extreme_false_positives",
        "gradual_anomaly_false_negatives",
        "abrupt_anomaly_false_negatives",
        "missingness_related_errors",
    }


def test_phase23_sources_have_no_network_or_external_model_paths():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "data" / "synthetic_anomaly" / "generator.py",
        root / "models" / "anomaly_window_model.py",
        root / "training" / "anomaly_synthetic_validation.py",
        root / "anomaly_artifacts.py",
    )
    forbidden_modules = {
        "httpx",
        "requests",
        "socket",
        "urllib",
        "urllib3",
        "transformers",
        "torchvision",
    }
    forbidden_symbols = {
        "from_pretrained",
        "hf_hub_download",
        "load_state_dict_from_url",
        "urlopen",
    }
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "http://" not in source
        assert "https://" not in source
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.split(".")[0] in forbidden_modules
                    for alias in node.names
                )
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_modules
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_symbols
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_symbols
