"""Phase 19 duplicate validation, calibration, and governance tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ml.components.duplicate_features import fit_feature_state
from app.ml.config import DuplicateMatchingConfig, file_sha256
from app.ml.data.duplicate_pairs import (
    DuplicatePairLabel,
    validate_duplicate_pairs,
)
from app.ml.data.synthetic_duplicates.generator import (
    DUPLICATE_SCENARIOS,
    HARD_NEGATIVE_SCENARIOS,
    SCENARIO_LABEL,
    UNCERTAIN_SCENARIOS,
    SyntheticDuplicateGeneratorConfig,
    generate_pair_records,
    validate_synthetic_duplicate_dataset,
    write_synthetic_duplicate_dataset,
)
from app.ml.training.duplicate_validation import (
    DEFAULT_FINAL_RECEIPT_PATH,
    DEFAULT_MATCHER_ARTIFACT_PATH,
    EXPECTED_ORIGINAL_FEATURE_STATE_SHA256,
    PairExample,
    DuplicateDevelopmentArtifact,
    DuplicateValidationBlocked,
    _example_from_record,
    failure_analysis,
    finalize_duplicate_matcher_evaluation,
    inspect_duplicate_dataset_decision,
    load_duplicate_development_artifact,
    multilingual_metrics,
    run_validation_ablation,
    score_pair_examples,
    select_duplicate_thresholds,
    training_corpus_and_hash,
)


@pytest.fixture(scope="module")
def generated_rows():
    return tuple(
        generate_pair_records(SyntheticDuplicateGeneratorConfig(total_pairs=600))
    )


@pytest.fixture(scope="module")
def fitted_state_and_examples(generated_rows):
    train = tuple(
        _example_from_record(item) for item in generated_rows if item.split == "train"
    )
    validation = tuple(
        _example_from_record(item)
        for item in generated_rows
        if item.split == "validation"
    )
    corpus, corpus_hash = training_corpus_and_hash(train)
    config = DuplicateMatchingConfig(
        feature_version="duplicate-features-v2-synthetic-development"
    )
    state = fit_feature_state(
        corpus,
        corpus_identifier="phase19-test-train-only",
        corpus_sha256=corpus_hash,
        config=config,
        state_version="duplicate-feature-state-v2",
    )
    return state, train, validation


def test_registry_decision_is_explicit_synthetic_fallback():
    decision = inspect_duplicate_dataset_decision()
    assert decision["USE_IT"] is False
    assert decision["GENERATE_SYNTHETIC_DUPLICATE_DATASET"] is True
    assert decision["selected_source"] == "PROJECT_AUTHORED_SYNTHETIC"
    assert decision["silent_switching_permitted"] is False


def test_generator_is_deterministic_and_labels_come_from_scenario_identity():
    config = SyntheticDuplicateGeneratorConfig(total_pairs=600)
    first = tuple(generate_pair_records(config))
    second = tuple(generate_pair_records(config))
    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    assert all(SCENARIO_LABEL[item.scenario_type] is item.label for item in first)
    assert {item.scenario_type for item in first} == set(
        DUPLICATE_SCENARIOS + HARD_NEGATIVE_SCENARIOS + UNCERTAIN_SCENARIOS
    )


def test_generator_is_configurable_and_multilingual(generated_rows):
    assert {item.label for item in generated_rows} == set(DuplicatePairLabel)
    assert {item.language for item in generated_rows} == {"en", "hi", "hinglish"}
    assert all(item.label_provenance.endswith("SCENARIO_IDENTITY") for item in generated_rows)
    assert all("matcher- or model-derived" in item.annotation_reason for item in generated_rows)


def test_reversed_pair_detection(generated_rows):
    original = generated_rows[0]
    reversed_record = original.model_copy(
        update={
            "pair_id": original.pair_id + "-reversed",
            "report_a_id": original.report_b_id,
            "report_b_id": original.report_a_id,
        }
    )
    report = validate_duplicate_pairs([original, reversed_record])
    assert report.valid is False
    assert reversed_record.pair_id in report.reversed_pair_ids


def test_split_integrity_and_custom_leakage_detection(tmp_path: Path):
    config = SyntheticDuplicateGeneratorConfig(total_pairs=600)
    artifacts = write_synthetic_duplicate_dataset(tmp_path, config=config)
    assert artifacts.report.valid is True
    assert artifacts.report.leakage_checks["status"] == "PASS"
    assert artifacts.report.held_out_combination_count > 0

    rows = artifacts.dataset_path.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in rows]
    train_text = next(item["text_a"] for item in payloads if item["split"] == "train")
    test_row = next(item for item in payloads if item["split"] == "test")
    test_row["text_a"] = train_text
    artifacts.dataset_path.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in payloads
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = validate_synthetic_duplicate_dataset(
        artifacts.dataset_path, config=config
    )
    assert report.valid is False
    assert report.leakage_checks["exact_text_cross_split"] >= 1


def test_feature_state_fit_is_train_only(fitted_state_and_examples):
    state, train, validation = fitted_state_and_examples
    assert state.state_version == "duplicate-feature-state-v2"
    assert state.feature_version == "duplicate-features-v2-synthetic-development"
    with pytest.raises(DuplicateValidationBlocked, match="TRAIN_SPLIT_ONLY"):
        training_corpus_and_hash(validation)
    assert len(train) == 420


def test_threshold_selection_and_test_protection(fitted_state_and_examples):
    state, _, validation = fitted_state_and_examples
    validation_signals = score_pair_examples(
        validation, state, expected_split="validation"
    )
    search = select_duplicate_thresholds(
        validation_signals,
        text_thresholds=(0.40, 0.55, 0.70),
        combined_thresholds=(0.50, 0.70, 0.80),
        geographic_gates_km=(1.0, 5.0),
        temporal_gates_minutes=(15.0, 180.0),
    )
    assert search["selection_split"] == "validation"
    assert search["test_rows_accessed_for_selection"] is False
    test_examples = tuple(replace(item, split="test") for item in validation)
    test_signals = score_pair_examples(test_examples, state, expected_split="test")
    with pytest.raises(DuplicateValidationBlocked, match="VALIDATION_SPLIT"):
        select_duplicate_thresholds(test_signals)


def test_ablation_exact_set_and_multilingual_failure_analysis(
    fitted_state_and_examples,
):
    state, _, validation = fitted_state_and_examples
    signals = score_pair_examples(validation, state, expected_split="validation")
    search = select_duplicate_thresholds(
        signals,
        text_thresholds=(0.40, 0.55),
        combined_thresholds=(0.50, 0.70),
        geographic_gates_km=(1.0,),
        temporal_gates_minutes=(15.0, 180.0),
    )
    selected = search["selected"]
    ablation = run_validation_ablation(signals, selected)
    assert {item["ablation"] for item in ablation["ablations"]} == {
        "TEXT ONLY",
        "GEO ONLY",
        "TIME ONLY",
        "TEXT + GEO",
        "TEXT + TIME",
        "TEXT + GEO + TIME",
        "EDIT + TEXT",
        "FULL MODEL",
    }
    assert ablation["test_rows_accessed"] is False
    assert set(multilingual_metrics(signals, selected)) == {"en", "hi", "hinglish"}
    failures = failure_analysis(signals, selected)
    assert set(failures["errors"]) == {"FALSE_DUPLICATE", "MISSED_DUPLICATE"}


def test_artifact_governance_and_original_state_are_protected():
    original = DEFAULT_MATCHER_ARTIFACT_PATH.parent / "duplicate_feature_state.json"
    assert file_sha256(original) == EXPECTED_ORIGINAL_FEATURE_STATE_SHA256
    artifact, matcher = load_duplicate_development_artifact()
    assert artifact.production_validation == "NOT_VALIDATED"
    assert artifact.policy["network_access"] is False
    assert artifact.policy["pretrained_models"] == []
    assert matcher.config.threshold_status == "VALIDATION_SELECTED_SYNTHETIC_DEVELOPMENT"

    payload = artifact.model_dump(mode="json")
    payload["policy"]["network_access"] = True
    with pytest.raises(ValidationError, match="network_access"):
        DuplicateDevelopmentArtifact.model_validate(payload)


def test_final_receipt_is_one_shot_and_policy_closed():
    receipt = json.loads(DEFAULT_FINAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "FINAL_EVALUATION_COMPLETE"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["production_validation"] == "NOT_VALIDATED"
    assert receipt["pretrained_models"] == []
    assert receipt["open_weight_models"] == []
    assert receipt["external_apis"] == []
    assert receipt["network_access"] is False
    with pytest.raises(RuntimeError, match="reevaluation is prohibited"):
        finalize_duplicate_matcher_evaluation()
