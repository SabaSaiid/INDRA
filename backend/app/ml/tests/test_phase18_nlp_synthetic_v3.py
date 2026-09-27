from __future__ import annotations

import hashlib
import inspect
import json
from types import SimpleNamespace

import numpy as np
import pytest

from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact
from app.ml.config import DEFAULT_NLP_CLASSIFIER_CONFIG, load_artifact_manifest
from app.ml.training import nlp_synthetic_v3
from app.ml.training.nlp_synthetic_v3 import (
    DEVELOPMENT_STATUS,
    EXPECTED_DATASET_SHA256,
    EXPECTED_GENERATOR_SEED,
    EXPECTED_GENERATOR_VERSION,
    PRODUCTION_STATUS,
    SelectedFit,
    SyntheticV3TrainingBlocked,
    V3Candidate,
    batch_predict_artifact,
    controlled_search_space,
    evaluate_validation_calibration,
    finalize_synthetic_v3_evaluation,
    prepare_synthetic_selection_data,
    select_candidate_result,
    verify_synthetic_dataset_binding,
)


def _selection_result(
    configuration_id: str,
    *,
    macro_f1: float,
    not_relevant_recall: float,
    hard_negative_macro_f1: float,
    multilingual_floor: float,
    rank: int,
) -> dict:
    return {
        "configuration": V3Candidate(
            configuration_id=configuration_id,
            feature_space_id="A",
            char_ngram_range=(3, 5),
            deterministic_tie_rank=rank,
        ).model_dump(mode="json"),
        "training_status": "CONVERGED",
        "validation": {
            "overall": {"macro_f1": macro_f1},
            "not_relevant_recall": not_relevant_recall,
            "hard_negative_macro_f1": hard_negative_macro_f1,
            "minimum_language_macro_f1": multilingual_floor,
        },
    }


def test_controlled_search_is_small_explicit_and_covers_required_axes():
    candidates = controlled_search_space()
    assert len(candidates) == 11
    assert len(candidates) <= 12
    assert {candidate.char_ngram_range for candidate in candidates} == {
        (2, 5),
        (3, 5),
        (3, 6),
    }
    assert {candidate.word_ngram_range for candidate in candidates} == {(1, 2)}
    assert {candidate.regularization_c for candidate in candidates} >= {
        0.25,
        0.5,
        1.0,
        2.0,
    }
    assert {candidate.class_weight for candidate in candidates} == {
        "NONE",
        "BALANCED",
    }
    assert {
        (candidate.character_weight, candidate.word_weight) for candidate in candidates
    } >= {(1.0, 1.0), (1.25, 0.75), (1.5, 0.5)}
    assert len({candidate.configuration_id for candidate in candidates}) == len(
        candidates
    )


def test_exact_synthetic_registry_binding_keeps_production_training_gate_closed():
    binding = verify_synthetic_dataset_binding()
    assert hashlib.sha256(binding.dataset_path.read_bytes()).hexdigest() == (
        EXPECTED_DATASET_SHA256
    )
    assert binding.dataset_manifest["generator_version"] == (EXPECTED_GENERATOR_VERSION)
    assert binding.dataset_manifest["seed"] == EXPECTED_GENERATOR_SEED
    assert binding.production_training_gate["allowed"] is False
    assert (
        "DATASET_CLASSIFICATION_BLOCKED"
        in binding.production_training_gate["reason_codes"]
    )


def test_hash_mismatch_uses_the_required_stable_block_reason(monkeypatch):
    monkeypatch.setattr(nlp_synthetic_v3, "file_sha256", lambda _path: "0" * 64)
    with pytest.raises(
        SyntheticV3TrainingBlocked,
        match="^TRAINING_BLOCKED_DATASET_HASH_MISMATCH$",
    ):
        verify_synthetic_dataset_binding()


def test_prepared_split_is_exact_and_selection_api_cannot_receive_test_rows():
    prepared = prepare_synthetic_selection_data()
    assert len(prepared.selection.train_examples) == 80_000
    assert len(prepared.selection.validation_examples) == 10_000
    assert prepared.protected_test.sample_count == 10_000
    assert prepared.split_manifest["base_template_overlap"] == {
        "train_vs_validation": 0,
        "train_vs_test": 0,
        "validation_vs_test": 0,
    }
    assert all(
        value == 0
        for value in prepared.split_manifest["parameter_combination_overlap"].values()
    )
    assert prepared.split_manifest["noise_distribution"]["validation"]["HIGH"] == 0
    assert prepared.split_manifest["noise_distribution"]["test"] == {
        "NONE": 0,
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 10_000,
    }
    parameters = inspect.signature(
        nlp_synthetic_v3.run_controlled_model_selection
    ).parameters
    assert all("test" not in name for name in parameters)


def test_selection_rule_uses_macro_f1_then_required_ties_without_test():
    results = [
        _selection_result(
            "fails-floor",
            macro_f1=0.99,
            not_relevant_recall=0.79,
            hard_negative_macro_f1=0.99,
            multilingual_floor=0.99,
            rank=0,
        ),
        _selection_result(
            "lower-hard-negative",
            macro_f1=0.95,
            not_relevant_recall=0.90,
            hard_negative_macro_f1=0.80,
            multilingual_floor=0.95,
            rank=1,
        ),
        _selection_result(
            "selected",
            macro_f1=0.95,
            not_relevant_recall=0.90,
            hard_negative_macro_f1=0.90,
            multilingual_floor=0.91,
            rank=2,
        ),
    ]
    selected, details = select_candidate_result(
        results,
        minimum_not_relevant_recall=0.80,
    )
    assert selected["configuration"]["configuration_id"] == "selected"
    assert details["selection_path"] == "NOT_RELEVANT_FLOOR_SATISFIED"
    assert details["test_set_used"] is False
    assert details["constraint"]["threshold_altered_after_results"] is False


def test_temperature_calibration_reports_search_boundary_without_expansion():
    labels = list(nlp_synthetic_v3.V3_CLASSES) * 10
    logits = np.zeros((len(labels), len(nlp_synthetic_v3.V3_CLASSES)))
    for row, label in enumerate(labels):
        logits[row, nlp_synthetic_v3.V3_CLASSES.index(label)] = 2.0
    fit = SelectedFit(
        candidate=controlled_search_space()[0],
        char_vectorizer=None,
        word_vectorizer=None,
        classifier=SimpleNamespace(classes_=np.asarray(nlp_synthetic_v3.V3_CLASSES)),
        train_predictions=[],
        validation_predictions=labels,
        validation_logits=logits,
        feature_count=1,
        classifier_iterations=[1],
    )
    state, report = evaluate_validation_calibration(
        fit,
        labels,
        "a" * 64,
    )
    assert state.status == "CALIBRATED_ON_VALIDATION"
    assert report["optimization"]["boundary_status"] == (
        "CALIBRATION_SEARCH_BOUNDARY_REACHED"
    )
    assert report["optimization"]["search_expanded"] is False
    assert (
        report["metrics"]["post_calibration_log_loss"]
        < report["metrics"]["pre_calibration_log_loss"]
    )


def test_committed_v3_artifact_and_evidence_are_hash_bound_and_synthetic_only():
    paths = (
        nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH,
        nlp_synthetic_v3.DEFAULT_DEVELOPMENT_MANIFEST_PATH,
        nlp_synthetic_v3.DEFAULT_SEARCH_PATH,
        nlp_synthetic_v3.DEFAULT_CALIBRATION_PATH,
        nlp_synthetic_v3.DEFAULT_GOLDEN_PATH,
        nlp_synthetic_v3.DEFAULT_METRICS_PATH,
        nlp_synthetic_v3.DEFAULT_FINAL_RECEIPT_PATH,
        nlp_synthetic_v3.DEFAULT_ERROR_REPORT_PATH,
    )
    assert all(path.is_file() for path in paths)
    artifact = load_nlp_artifact(nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH)
    development = json.loads(
        nlp_synthetic_v3.DEFAULT_DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    metrics = json.loads(
        nlp_synthetic_v3.DEFAULT_METRICS_PATH.read_text(encoding="utf-8")
    )
    receipt = json.loads(
        nlp_synthetic_v3.DEFAULT_FINAL_RECEIPT_PATH.read_text(encoding="utf-8")
    )
    artifact_hash = hashlib.sha256(
        nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH.read_bytes()
    ).hexdigest()
    assert artifact.artifact_version == "nlp-classifier-artifact-v3"
    assert artifact.model_status == DEVELOPMENT_STATUS
    assert artifact.provenance.dataset_sha256 == EXPECTED_DATASET_SHA256
    assert artifact.provenance.dataset_generator_version == (EXPECTED_GENERATOR_VERSION)
    assert artifact.provenance.dataset_generator_seed == EXPECTED_GENERATOR_SEED
    assert artifact_hash == development["artifact"]["sha256"]
    assert artifact_hash == metrics["artifact_sha256"]
    assert artifact_hash == receipt["artifact_sha256"]
    assert development["production_status"] == PRODUCTION_STATUS
    assert metrics["development_status"] == DEVELOPMENT_STATUS
    assert metrics["production_validation"] == "NOT_VALIDATED"
    assert receipt["status"] == "COMPLETED_AND_FROZEN"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["retrained_after_evaluation"] is False
    assert set(metrics["test"]["languages"]) == set(nlp_synthetic_v3.V3_LANGUAGES)
    assert set(metrics["test"]["noise"]) == set(nlp_synthetic_v3.V3_NOISE_PROFILES)
    assert metrics["v2_comparison"]["comparison_status"] == ("NOT_DIRECTLY_COMPARABLE")
    assert metrics["v2_comparison"]["direct_superiority_claim"] is False


def test_v3_manifest_authorization_and_transform_only_inference_are_deterministic():
    manifest = load_artifact_manifest()
    entry = next(
        item
        for item in manifest.artifacts
        if item.artifact_name == "nlp_classifier_v3.json"
    )
    artifact = load_nlp_artifact(nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH)
    assert (
        entry.sha256
        == hashlib.sha256(
            nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH.read_bytes()
        ).hexdigest()
    )
    prepared = prepare_synthetic_selection_data()
    examples = prepared.selection.validation_examples[:5]
    batch_labels, batch_probabilities, _ = batch_predict_artifact(
        artifact,
        [example.text for example in examples],
    )
    classifier = NLPClassifier(
        nlp_synthetic_v3._config_for_artifact(
            artifact,
            nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH,
        ),
        artifact_path=nlp_synthetic_v3.DEFAULT_ARTIFACT_PATH,
    )
    scalar = [classifier.predict(example.text) for example in examples]
    assert batch_labels == [prediction.label for prediction in scalar]
    for row, prediction in zip(batch_probabilities, scalar, strict=True):
        assert row.tolist() == pytest.approx(
            [prediction.probabilities[label] for label in artifact.classes],
            abs=1e-12,
        )
    assert DEFAULT_NLP_CLASSIFIER_CONFIG.model_version == "nlp-classifier-v1"


def test_v3_golden_report_preserves_unified_contract_and_live_default():
    report = json.loads(
        nlp_synthetic_v3.DEFAULT_GOLDEN_PATH.read_text(encoding="utf-8")
    )
    assert report["status"] == "PASS"
    assert report["scenario_count"] == 10
    assert report["unified_ml_result_schema_unchanged"] is True
    assert report["status_semantics_unchanged"] is True
    assert report["serialization_round_trip"] == "PASS"
    assert report["determinism"] == "PASS"
    assert report["network_access"] is False
    assert report["live_backend_modified"] is False


def test_final_holdout_cannot_be_evaluated_a_second_time():
    with pytest.raises(RuntimeError, match="final metrics already exist"):
        finalize_synthetic_v3_evaluation()
