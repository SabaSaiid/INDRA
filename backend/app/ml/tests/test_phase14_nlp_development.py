from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact
from app.ml.config import DEFAULT_NLP_CLASSIFIER_CONFIG, NLPClassifierConfig
from app.ml.data.loaders import load_csv
from app.ml.data.schemas import DatasetRecord, DatasetSplit
from app.ml.evaluation.evaluate import evaluate_nlp_predictions
from app.ml.training import nlp_development
from app.ml.training.nlp_development import (
    CandidateFit,
    DevelopmentCandidate,
    DevelopmentProtocolConfig,
    SelectionDataset,
    _claim_final_evaluation,
    canonical_record_hash,
    controlled_search_space,
    create_development_split,
    evaluate_validation_calibration,
    finalize_frozen_nlp_evaluation,
    prepare_registered_development_data,
    run_controlled_model_selection,
    select_result_by_rule,
)


FIXED_TIME = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
CLASSES = (
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
    "NOT_RELEVANT",
    "RIVER_BREACH",
    "URBAN_FLOOD",
)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase14-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _record(index: int, label: str, split: DatasetSplit, language: str = "en"):
    return DatasetRecord(
        record_id=f"phase14-{index:03d}",
        text=f"{label.lower().replace('_', ' ')} local report number {index}",
        split=split,
        event_type=label,
        language=language,
    )


def _selection_fixture() -> SelectionDataset:
    train: list[DatasetRecord] = []
    validation: list[DatasetRecord] = []
    index = 0
    for label in CLASSES:
        for _ in range(3):
            index += 1
            train.append(_record(index, label, DatasetSplit.TRAIN))
        index += 1
        validation.append(_record(index, label, DatasetSplit.VALIDATION))
    return SelectionDataset(
        train_records=tuple(train),
        validation_records=tuple(validation),
        train_sha256=canonical_record_hash(train),
        validation_sha256=canonical_record_hash(validation),
    )


def _selection_result(
    configuration_id: str,
    not_relevant_recall: float,
    macro_f1: float,
    accuracy: float,
):
    return {
        "configuration": {"configuration_id": configuration_id},
        "validation": {
            "not_relevant_recall": not_relevant_recall,
            "macro_f1": macro_f1,
            "accuracy": accuracy,
        },
    }


def test_controlled_search_space_is_small_explicit_and_covers_required_comparisons():
    candidates = controlled_search_space()
    assert len(candidates) == 12
    assert len(candidates) <= 20
    assert {candidate.char_ngram_range for candidate in candidates} >= {
        (2, 5),
        (3, 5),
        (3, 6),
    }
    assert {candidate.word_ngram_range for candidate in candidates} == {(1, 2)}
    assert {candidate.class_weight for candidate in candidates} == {
        "NONE",
        "BALANCED",
    }
    assert {candidate.regularization_c for candidate in candidates} >= {0.5, 1.0, 2.0}
    assert {
        (candidate.character_weight, candidate.word_weight)
        for candidate in candidates
    } >= {(1.0, 1.0), (1.25, 0.75), (0.75, 1.25)}


def test_registered_split_is_deterministic_stratified_and_preserves_final_test_order():
    first = prepare_registered_development_data()
    second = prepare_registered_development_data()
    assert first.selection.train_sha256 == second.selection.train_sha256
    assert first.selection.validation_sha256 == second.selection.validation_sha256
    assert first.final_test == second.final_test
    assert len(first.selection.train_records) == 168
    assert len(first.selection.validation_records) == 42
    assert first.final_test.sample_count == 90
    assert first.split_manifest["random_seed"] == 42
    assert first.split_manifest["split_version"] == "nlp-development-split-v1"
    assert set(first.split_manifest["class_distribution"]["train"]) == set(CLASSES)
    assert set(first.split_manifest["class_distribution"]["validation"]) == set(
        CLASSES
    )
    source_records = load_csv(first.dataset_path)
    source_test_ids = tuple(
        record.record_id
        for record in source_records
        if record.split is DatasetSplit.TEST
    )
    assert first.final_test.record_ids_in_source_order == source_test_ids


def test_stratification_fails_clearly_when_any_class_has_only_one_row():
    records: list[DatasetRecord] = []
    index = 0
    for label in CLASSES:
        repetitions = 1 if label == "NOT_RELEVANT" else 2
        for _ in range(repetitions):
            index += 1
            records.append(_record(index, label, DatasetSplit.TRAIN))
    with pytest.raises(ValueError, match="stratification is impossible"):
        create_development_split(records)


def test_configuration_selection_cannot_load_or_receive_final_test_examples(monkeypatch):
    signature = inspect.signature(run_controlled_model_selection)
    assert all("test" not in name for name in signature.parameters)

    def fail_if_any_dataset_is_loaded(*args, **kwargs):
        raise AssertionError("selection attempted to load a dataset or protected test rows")

    monkeypatch.setattr(nlp_development, "load_csv", fail_if_any_dataset_is_loaded)
    result = run_controlled_model_selection(
        _selection_fixture(),
        candidates=(
            DevelopmentCandidate(
                configuration_id="UNIT_SELECTION_ONLY",
                char_ngram_range=(3, 5),
            ),
        ),
    )
    assert result.selected_fit.candidate.configuration_id == "UNIT_SELECTION_ONLY"
    assert result.selection_details["test_set_used"] is False


def test_selection_rule_enforces_not_relevant_constraint_then_macro_f1():
    results = [
        _selection_result("high-f1-fails-recall", 0.79, 0.95, 0.95),
        _selection_result("eligible-lower-f1", 0.90, 0.81, 0.82),
        _selection_result("eligible-higher-f1", 0.80, 0.88, 0.87),
    ]
    selected, details = select_result_by_rule(
        results,
        minimum_not_relevant_recall=0.80,
        minimum_macro_f1=0.75,
    )
    assert selected["configuration"]["configuration_id"] == "eligible-higher-f1"
    assert details["selection_path"] == "PRIMARY_CONSTRAINT_SATISFIED"
    assert details["test_set_used"] is False


def test_selection_rule_reports_fallback_without_lowering_the_gate():
    results = [
        _selection_result("best-recall", 0.75, 0.80, 0.80),
        _selection_result("best-f1", 0.70, 0.90, 0.90),
    ]
    selected, details = select_result_by_rule(
        results,
        minimum_not_relevant_recall=0.80,
        minimum_macro_f1=0.75,
    )
    assert selected["configuration"]["configuration_id"] == "best-recall"
    assert (
        details["selection_path"]
        == "NO_CONFIGURATION_MET_NOT_RELEVANT_CONSTRAINT"
    )
    assert details["primary_constraint"]["minimum"] == 0.80


def test_multilingual_metrics_and_error_groups_are_complete_and_deterministic():
    labels = [CLASSES[index % len(CLASSES)] for index in range(20)]
    predictions = list(labels)
    predictions[2] = "NOT_RELEVANT"
    predictions[13] = "URBAN_FLOOD"
    languages = ["en"] * 10 + ["hinglish"] * 10
    report = evaluate_nlp_predictions(
        labels,
        predictions,
        CLASSES,
        record_ids=[f"row-{index:02d}" for index in range(20)],
        texts=[f"example {index}" for index in range(20)],
        languages=languages,
        minimum_subgroup_rows=10,
        expected_languages=("en", "hi", "hinglish"),
    )
    for language in ("en", "hinglish"):
        metrics = report.subgroup_metrics[language]
        assert metrics["status"] == "DATA_AVAILABLE"
        assert set(metrics) >= {
            "sample_count",
            "accuracy",
            "macro_precision",
            "macro_recall",
            "macro_f1",
            "confusion_matrix",
        }
    assert report.subgroup_metrics["hi"] == {
        "status": "INSUFFICIENT_DATA",
        "sample_count": 0,
    }
    errors = report.error_analysis
    assert set(errors) >= {
        "false_positives",
        "false_negatives",
        "most_confused_class_pairs",
        "not_relevant_errors",
        "hindi_errors",
        "hinglish_errors",
        "examples_grouped_by_actual_and_predicted",
    }
    assert json.dumps(errors, sort_keys=True) == json.dumps(
        evaluate_nlp_predictions(
            labels,
            predictions,
            CLASSES,
            record_ids=[f"row-{index:02d}" for index in range(20)],
            texts=[f"example {index}" for index in range(20)],
            languages=languages,
            minimum_subgroup_rows=10,
            expected_languages=("en", "hi", "hinglish"),
        ).error_analysis,
        sort_keys=True,
    )


def test_temperature_calibration_uses_validation_logits_and_reports_reliability():
    labels = list(CLASSES) * 2
    logits = np.zeros((len(labels), len(CLASSES)), dtype=np.float64)
    for row, label in enumerate(labels):
        logits[row, CLASSES.index(label)] = 1.0
    fit = CandidateFit(
        candidate=DevelopmentCandidate(
            configuration_id="CALIBRATION_FIXTURE",
            char_ngram_range=(3, 5),
        ),
        vectorizers=(None, None),
        classifier=SimpleNamespace(classes_=np.asarray(CLASSES)),
        train_predictions=[],
        validation_predictions=labels,
        validation_logits=logits,
        compact_train_metrics={},
        compact_validation_metrics={},
        feature_count=1,
    )
    split_hash = "a" * 64
    state, report = evaluate_validation_calibration(
        fit,
        labels,
        split_hash,
        bins=5,
    )
    assert state.status == "CALIBRATED_ON_VALIDATION"
    assert state.validation_split_sha256 == split_hash
    assert report["evaluation_scope"] == "VALIDATION_ONLY"
    assert report["production_calibration"] == "NOT_VALIDATED"
    assert report["metrics"]["log_loss_after_candidate"] < report["metrics"][
        "log_loss_before"
    ]
    assert len(report["reliability_before"]["bins"]) == 5


def test_final_evaluation_claim_is_exclusive(local_tmp_path):
    receipt = local_tmp_path / "receipt.json"
    _claim_final_evaluation(
        receipt,
        development_manifest_sha256="a" * 64,
        artifact_sha256="b" * 64,
        claimed_at=FIXED_TIME,
    )
    with pytest.raises(RuntimeError, match="already claimed"):
        _claim_final_evaluation(
            receipt,
            development_manifest_sha256="a" * 64,
            artifact_sha256="b" * 64,
            claimed_at=FIXED_TIME,
        )
    assert json.loads(receipt.read_text(encoding="utf-8"))[
        "evaluation_invocation_count"
    ] == 1


def test_committed_phase14_artifact_manifest_metrics_and_receipt_are_hash_bound():
    paths = {
        "artifact": nlp_development.DEFAULT_ARTIFACT_PATH,
        "development_manifest": nlp_development.DEFAULT_DEVELOPMENT_MANIFEST_PATH,
        "metrics": nlp_development.DEFAULT_METRICS_PATH,
        "receipt": nlp_development.DEFAULT_FINAL_RECEIPT_PATH,
        "split": nlp_development.DEFAULT_SPLIT_PATH,
        "search": nlp_development.DEFAULT_SEARCH_PATH,
        "errors": nlp_development.DEFAULT_VALIDATION_ERRORS_PATH,
        "calibration": nlp_development.DEFAULT_CALIBRATION_PATH,
    }
    assert all(path.is_file() for path in paths.values())
    artifact = load_nlp_artifact(paths["artifact"])
    development_manifest = json.loads(
        paths["development_manifest"].read_text(encoding="utf-8")
    )
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
    assert artifact.artifact_version == "nlp-classifier-artifact-v2"
    assert artifact.model_status == "DEVELOPMENT_ONLY_FROZEN"
    assert development_manifest["production_status"] == "NOT_PRODUCTION_READY"
    assert metrics["evaluation_label"] == "FINAL_UNTOUCHED_TEST_EVALUATION"
    assert metrics["production_validation"] == "NOT_VALIDATED"
    assert metrics["n_test"] == 90
    assert receipt["status"] == "COMPLETED"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["retrained_after_evaluation"] is False
    artifact_hash = hashlib.sha256(paths["artifact"].read_bytes()).hexdigest()
    assert artifact_hash == development_manifest["artifact"]["sha256"]
    assert artifact_hash == metrics["artifact_sha256"]
    assert artifact_hash == receipt["artifact_sha256"]


def test_committed_phase14_artifact_inference_is_deterministic_and_not_default():
    development_manifest = json.loads(
        nlp_development.DEFAULT_DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    selected = development_manifest["selected_configuration"]
    artifact = load_nlp_artifact(nlp_development.DEFAULT_ARTIFACT_PATH)
    config = NLPClassifierConfig(
        model_version=artifact.model_version,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        artifact_path=nlp_development.DEFAULT_ARTIFACT_PATH,
        metrics_path=nlp_development.DEFAULT_METRICS_PATH,
        char_ngram_range=tuple(selected["char_ngram_range"]),
        word_ngram_range=tuple(selected["word_ngram_range"]),
        regularization_grid=(selected["regularization_c"],),
        regularization_c=selected["regularization_c"],
        random_state=artifact.classifier.random_state,
    )
    classifier = NLPClassifier(config)
    text = "नदी का तटबंध टूटने से गांव में पानी आया"
    assert classifier.predict(text).model_dump() == classifier.predict(text).model_dump()
    assert classifier.predict(text).model_version == "nlp-classifier-v2-development"
    assert DEFAULT_NLP_CLASSIFIER_CONFIG.model_version == "nlp-classifier-v1"


def test_committed_phase14_finalization_refuses_a_second_run_before_test_access():
    with pytest.raises(RuntimeError, match="final metrics already exist"):
        finalize_frozen_nlp_evaluation()
