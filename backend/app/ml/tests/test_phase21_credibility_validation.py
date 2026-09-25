"""Phase 21 synthetic credibility benchmark, model, and governance tests."""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.ml.components.fake_detection import assess_credibility_risk
from app.ml.config import file_sha256
from app.ml.data.synthetic_credibility import (
    CREDIBILITY_SCENARIOS,
    FORBIDDEN_DETECTOR_FIELDS,
    LANGUAGES,
    SCENARIO_LABELS,
    SyntheticCredibilityDetectorInput,
    SyntheticCredibilityGeneratorConfig,
    generate_report_family,
    validate_synthetic_credibility_dataset,
    write_synthetic_credibility_dataset,
)
from app.ml.training.credibility_validation import (
    DEFAULT_ARTIFACT_PATH,
    DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    DEFAULT_FINAL_METRICS_PATH,
    DEFAULT_FINAL_RECEIPT_PATH,
    EXPECTED_FROZEN_CORE_HASHES,
    CredibilityDatasetBinding,
    CredibilityDevelopmentArtifact,
    apply_preprocessor,
    calibrate_on_validation,
    classification_metrics,
    finalize_credibility_evaluation,
    fit_preprocessor,
    hard_negative_results,
    load_credibility_development_artifact,
    load_credibility_split,
    multilingual_results,
    predict_credibility_development,
    probability_labels,
    protected_artifact_snapshot,
    select_abstention_thresholds,
    select_logistic_model,
)

SMALL_CONFIG = SyntheticCredibilityGeneratorConfig(reports_per_scenario=80)


@pytest.fixture(scope="module")
def small_artifacts(tmp_path_factory):
    return write_synthetic_credibility_dataset(
        tmp_path_factory.mktemp("synthetic-credibility-v1"),
        config=SMALL_CONFIG,
    )


@pytest.fixture(scope="module")
def small_binding(small_artifacts):
    return CredibilityDatasetBinding(
        registry_path=small_artifacts.output_directory / "unused-registry.json",
        annotation_path=small_artifacts.annotation_path,
        ground_truth_paths=small_artifacts.ground_truth_paths,
        detector_input_paths=small_artifacts.detector_input_paths,
        manifest_path=small_artifacts.manifest_path,
        quality_report_path=small_artifacts.quality_report_path,
        manifest=small_artifacts.manifest,
        quality_report=small_artifacts.report,
        registered_validation_sha256="0" * 64,
        production_training_gate={"allowed": False},
        development_gate={"allowed": True},
    )


@pytest.fixture(scope="module")
def small_model(small_binding):
    train = load_credibility_split(small_binding, "train")
    validation = load_credibility_split(small_binding, "validation")
    preprocessor = fit_preprocessor(train.raw_features)
    train_features = apply_preprocessor(train.raw_features, preprocessor)
    validation_features = apply_preprocessor(validation.raw_features, preprocessor)
    selected, search = select_logistic_model(
        train_features,
        train.labels,
        validation_features,
        validation,
    )
    temperature, calibration = calibrate_on_validation(
        selected,
        validation_features,
        validation,
    )
    logits = selected.model.decision_function(validation_features)
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits / temperature, -40, 40)))
    thresholds, threshold_search = select_abstention_thresholds(
        probabilities,
        validation,
    )
    predictions = probability_labels(
        probabilities,
        authentic_max_probability=thresholds["authentic_max_probability"],
        misleading_min_probability=thresholds["misleading_min_probability"],
    )
    return {
        "train": train,
        "validation": validation,
        "preprocessor": preprocessor,
        "selected": selected,
        "search": search,
        "calibration": calibration,
        "threshold_search": threshold_search,
        "probabilities": probabilities,
        "predictions": predictions,
    }


def test_generator_reproducibility_and_scenario_ground_truth():
    first = generate_report_family(
        SMALL_CONFIG,
        split="validation",
        scenario="LEGITIMATE_DUPLICATE",
        family_ordinal=3,
    )
    second = generate_report_family(
        SMALL_CONFIG,
        split="validation",
        scenario="LEGITIMATE_DUPLICATE",
        family_ordinal=3,
    )
    assert [item.model_dump(mode="json") for item in first[0]] == [
        item.model_dump(mode="json") for item in second[0]
    ]
    assert [item.model_dump(mode="json") for item in first[1]] == [
        item.model_dump(mode="json") for item in second[1]
    ]
    assert all(
        item.ground_truth_label is SCENARIO_LABELS[item.scenario_category]
        for item in first[0]
    )
    assert all(
        not FORBIDDEN_DETECTOR_FIELDS.intersection(item.model_dump())
        for item in first[1]
    )


def test_hidden_label_isolation_schema_rejects_generator_truth():
    truth, detector_inputs, _ = generate_report_family(
        SMALL_CONFIG,
        split="validation",
        scenario="MISLEADING_CONTEXT",
        family_ordinal=4,
    )
    payload = detector_inputs[0].model_dump(mode="json")
    payload["ground_truth_label"] = truth[0].ground_truth_label.value
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SyntheticCredibilityDetectorInput.model_validate(payload)


def test_grouped_split_and_all_required_leakage_checks(small_artifacts):
    report = validate_synthetic_credibility_dataset(
        small_artifacts.ground_truth_paths,
        small_artifacts.detector_input_paths,
        small_artifacts.annotation_path,
        config=SMALL_CONFIG,
    )
    assert report.valid is True
    assert report.report_count == 1_120
    assert set(report.scenario_counts) == set(CREDIBILITY_SCENARIOS)
    assert set(report.language_counts) == set(LANGUAGES)
    assert report.leakage_checks == {
        "status": "PASS",
        "report_family_cross_split": 0,
        "canonical_event_cross_split": 0,
        "template_cross_split": 0,
        "parameter_combination_cross_split": 0,
        "exact_normalized_text_cross_split": 0,
        "grouped_split": True,
        "random_row_split": False,
    }
    assert report.isolation_checks["forbidden_field_occurrences"] == 0


def test_rule_baseline_is_evaluated_separately_and_not_used_as_truth():
    truth, detector_inputs, _ = generate_report_family(
        SMALL_CONFIG,
        split="validation",
        scenario="AUTHENTIC_EXTREME_BUT_PLAUSIBLE",
        family_ordinal=5,
    )
    prediction = assess_credibility_risk(detector_inputs[0].to_risk_input())
    assert truth[0].ground_truth_label.value == "AUTHENTIC"
    assert prediction.baseline_name == "RULE_BASED_CREDIBILITY_BASELINE"
    assert prediction.calibration_status.value == "NOT_CALIBRATED"
    assert any("does not establish truth" in item.casefold() for item in prediction.warnings)


def test_learned_model_selection_calibration_and_determinism(small_model):
    metrics = classification_metrics(
        small_model["validation"].labels,
        small_model["predictions"],
    )
    assert small_model["search"]["selection_partition"] == (
        "validation:model_selection"
    )
    assert small_model["search"]["test_rows_accessed"] is False
    assert small_model["calibration"]["fit_source"] == "VALIDATION_ONLY"
    assert small_model["calibration"]["test_rows_accessed"] is False
    assert small_model["threshold_search"]["test_rows_accessed"] is False
    assert metrics["misleading_recall"] >= 0.75
    assert metrics["misleading_precision"] >= 0.75
    repeated = probability_labels(
        small_model["probabilities"],
        authentic_max_probability=small_model["threshold_search"][
            "selected_thresholds"
        ]["authentic_max_probability"],
        misleading_min_probability=small_model["threshold_search"][
            "selected_thresholds"
        ]["misleading_min_probability"],
    )
    assert np.array_equal(repeated, small_model["predictions"])


def test_hard_negatives_and_multilingual_metrics_are_explicit(small_model):
    hard = hard_negative_results(
        small_model["validation"], small_model["predictions"]
    )
    multilingual = multilingual_results(
        small_model["validation"], small_model["predictions"]
    )
    assert hard["duplicate_not_equated_with_misleading"] is True
    assert hard["extreme_not_equated_with_misleading"] is True
    assert set(multilingual["languages"]) == set(LANGUAGES)
    assert all(
        multilingual["languages"][language]["row_count"] > 0
        for language in LANGUAGES
    )


def test_generator_operates_with_network_disabled(monkeypatch):
    def prohibited_socket(*_args, **_kwargs):
        raise AssertionError("network access is prohibited")

    monkeypatch.setattr(socket, "socket", prohibited_socket)
    truth, detector_inputs, annotations = generate_report_family(
        SMALL_CONFIG,
        split="test",
        scenario="SOURCE_BEHAVIOR_ANOMALY",
        family_ordinal=8,
    )
    assert len(truth) == len(detector_inputs) == len(annotations) == 4


def test_frozen_artifact_governance_and_deterministic_loader():
    artifact = load_credibility_development_artifact()
    assert artifact.artifact_kind == "INTERPRETABLE_LOCAL_LOGISTIC_REGRESSION"
    assert artifact.semantic_target == "MISLEADING_RISK_EVIDENCE"
    assert artifact.prohibited_interpretation == "TRUTH_PROBABILITY"
    assert artifact.production_validation == "NOT_VALIDATED"
    assert artifact.model_classes == ["AUTHENTIC", "MISLEADING"]
    assert artifact.output_labels == ["AUTHENTIC", "MISLEADING", "UNCERTAIN"]
    payload = artifact.model_dump(mode="json")
    payload["policy"]["network_access"] = True
    with pytest.raises(ValidationError, match="network access"):
        CredibilityDevelopmentArtifact.model_validate(payload)


def test_frozen_inference_is_deterministic_and_not_truth_probability(
    small_artifacts,
):
    with small_artifacts.detector_input_paths["validation"].open(
        encoding="utf-8"
    ) as handle:
        first_line = next(handle)
    detector_input = SyntheticCredibilityDetectorInput.model_validate_json(first_line)
    artifact = load_credibility_development_artifact()
    first = predict_credibility_development(detector_input, artifact)
    second = predict_credibility_development(detector_input, artifact)
    assert first == second
    assert first.semantic_target == "MISLEADING_RISK_EVIDENCE"
    assert first.truth_probability is False
    assert first.label in {"AUTHENTIC", "MISLEADING", "UNCERTAIN"}


def test_final_test_receipt_is_one_shot_and_test_was_not_tuned():
    receipt = json.loads(DEFAULT_FINAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    final_metrics = json.loads(DEFAULT_FINAL_METRICS_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "FINAL_EVALUATION_COMPLETE"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["test_used_for_model_selection"] is False
    assert receipt["test_used_for_calibration"] is False
    assert receipt["test_used_for_threshold_selection"] is False
    assert receipt["production_validation"] == "NOT_VALIDATED"
    assert final_metrics["truth_probability"] is False
    with pytest.raises(RuntimeError, match="reevaluation is prohibited"):
        finalize_credibility_evaluation()


def test_frozen_components_are_byte_identical_to_phase21_snapshot():
    development = json.loads(
        DEFAULT_DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    snapshot = protected_artifact_snapshot()
    assert snapshot == development["protected_artifacts"]
    for name, expected in EXPECTED_FROZEN_CORE_HASHES.items():
        assert snapshot[name] == expected
        assert file_sha256(DEFAULT_ARTIFACT_PATH.parent / name) == expected


def test_phase21_sources_have_no_network_or_pretrained_model_dependencies():
    roots = (
        Path(__file__).parents[1] / "data" / "synthetic_credibility" / "generator.py",
        Path(__file__).parents[1] / "training" / "credibility_validation.py",
        Path(__file__).parents[4] / "scripts" / "generate_synthetic_credibility_dataset.py",
        Path(__file__).parents[4] / "scripts" / "validate_credibility.py",
    )
    prohibited_imports = re.compile(
        r"^\s*(?:from|import)\s+(?:requests|httpx|urllib|transformers|torch|sentence_transformers|tensorflow)\b",
        re.MULTILINE,
    )
    prohibited_calls = re.compile(r"\b(?:urlopen|requests\.|httpx\.|from_pretrained)\b")
    for path in roots:
        source = path.read_text(encoding="utf-8")
        assert prohibited_imports.search(source) is None
        assert prohibited_calls.search(source) is None
