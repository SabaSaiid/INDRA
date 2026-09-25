"""Phase 20 synthetic event benchmark, evaluation, and governance tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ml.config import EventDetectorConfig, file_sha256
from app.ml.data.synthetic_event.generator import (
    EVENT_SCENARIOS,
    FORBIDDEN_DETECTOR_FIELDS,
    SyntheticDetectorInput,
    SyntheticEventGeneratorConfig,
    generate_scenario_batch,
    validate_synthetic_event_dataset,
    write_synthetic_event_dataset,
)
from app.ml.training.event_validation import (
    DEFAULT_DEVELOPMENT_MANIFEST_PATH,
    DEFAULT_EVENT_ARTIFACT_PATH,
    DEFAULT_FINAL_RECEIPT_PATH,
    EXPECTED_PROTECTED_HASHES,
    EventBatch,
    EventGroupingDevelopmentArtifact,
    EventValidationBlocked,
    calculate_grouping_metrics,
    evaluate_event_configuration,
    finalize_event_grouping_evaluation,
    load_event_development_artifact,
    predict_batches,
    protected_artifact_snapshot,
    run_validation_ablation,
    select_event_thresholds,
)

SMALL_CONFIG = SyntheticEventGeneratorConfig(batches_per_scenario=20)
FROZEN_CONFIG = EventDetectorConfig(
    spatial_radius_km=5.0,
    temporal_window_minutes=180.0,
    minimum_reports=2,
    minimum_type_probability=0.4,
)


def _batch(scenario: str, ordinal: int = 0, *, split: str = "validation") -> EventBatch:
    truth, detector_inputs, _ = generate_scenario_batch(
        SMALL_CONFIG,
        split=split,  # type: ignore[arg-type]
        scenario=scenario,
        scenario_ordinal=ordinal,
        split_batch_ordinal=EVENT_SCENARIOS.index(scenario) * 10 + ordinal,
    )
    return EventBatch(
        split=split,
        batch_id=truth[0].batch_id,
        scenario_family=scenario,
        truth=truth,
        detector_inputs=detector_inputs,
    )


@pytest.fixture(scope="module")
def small_artifacts(tmp_path_factory):
    return write_synthetic_event_dataset(
        tmp_path_factory.mktemp("synthetic-event-v1"), config=SMALL_CONFIG
    )


def test_generator_reproducibility_and_canonical_mapping_precede_detection():
    first = generate_scenario_batch(
        SMALL_CONFIG,
        split="validation",
        scenario="G_PARTIALLY_OVERLAPPING_EVENTS",
        scenario_ordinal=2,
        split_batch_ordinal=2,
    )
    second = generate_scenario_batch(
        SMALL_CONFIG,
        split="validation",
        scenario="G_PARTIALLY_OVERLAPPING_EVENTS",
        scenario_ordinal=2,
        split_batch_ordinal=2,
    )
    assert [item.model_dump(mode="json") for item in first[0]] == [
        item.model_dump(mode="json") for item in second[0]
    ]
    assert [item.model_dump(mode="json") for item in first[1]] == [
        item.model_dump(mode="json") for item in second[1]
    ]
    assert all(item.canonical_event_id for item in first[0])
    assert all(
        not FORBIDDEN_DETECTOR_FIELDS.intersection(item.model_dump())
        for item in first[1]
    )


def test_dataset_mapping_split_leakage_and_pair_ground_truth(small_artifacts):
    report = validate_synthetic_event_dataset(
        small_artifacts.ground_truth_paths,
        small_artifacts.detector_input_paths,
        small_artifacts.pair_path,
        config=SMALL_CONFIG,
    )
    assert report.valid is True
    assert report.report_count == 2_200
    assert report.canonical_event_count == 340
    assert report.leakage_checks["canonical_event_cross_split"] == 0
    assert report.leakage_checks["report_cross_split"] == 0
    assert set(report.pair_label_counts) == {
        "EVENT_MATCH",
        "EVENT_NOT_MATCH",
        "UNCERTAIN",
    }
    assert set(report.scenario_counts) == set(EVENT_SCENARIOS)


def test_detector_input_schema_rejects_hidden_ground_truth():
    batch = _batch("A_SINGLE_EVENT_MULTIPLE_REPORTS")
    payload = batch.detector_inputs[0].model_dump(mode="json")
    payload["canonical_event_id"] = batch.truth[0].canonical_event_id
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SyntheticDetectorInput.model_validate(payload)


def test_chain_bridge_and_legitimate_elongated_event():
    chain = _batch("H_CHAIN_BRIDGE")
    elongated = _batch("K_LEGITIMATE_ELONGATED_EVENT")
    results = predict_batches([chain, elongated], FROZEN_CONFIG, actual_detector=True)
    chain_sizes = sorted(len(item) for item in results[chain.batch_id].clusters)
    assert chain_sizes == [4, 6]
    assert all(len(item) < 10 for item in results[chain.batch_id].clusters)
    assert [len(item) for item in results[elongated.batch_id].clusters] == [10]


def test_duplicate_evidence_and_single_report_lifecycle():
    duplicate = _batch("E_DUPLICATE_REPORTS_WITHIN_EVENT", ordinal=2)
    single = _batch("J_SINGLE_REPORT_EVENT_CANDIDATE")
    evaluation = evaluate_event_configuration([duplicate, single], FROZEN_CONFIG)
    special = evaluation["metrics"]["special_case_results"]
    assert (
        special["duplicate_interaction"]["independent_report_inflation_violations"] == 0
    )
    assert (
        special["duplicate_interaction"]["source_diversity_inflation_violations"] == 0
    )
    assert special["duplicate_interaction"]["event_evidence_inflation_violations"] == 0
    assert special["single_report_event"]["candidate_count"] == 1
    assert special["single_report_event"]["confirmed_count"] == 0


def test_merge_split_metrics_have_explicit_expected_behavior():
    batch = _batch("B_TWO_SPATIALLY_SEPARATE_EVENTS")
    truth_clusters = {}
    for item in batch.truth:
        truth_clusters.setdefault(item.canonical_event_id, set()).add(
            str(item.report_id)
        )
    correct = {
        batch.batch_id: tuple(frozenset(value) for value in truth_clusters.values())
    }
    correct_metrics = calculate_grouping_metrics([batch], correct)
    assert correct_metrics["event_matching_f1"] == 1.0
    merged = {batch.batch_id: (frozenset(str(item.report_id) for item in batch.truth),)}
    merged_metrics = calculate_grouping_metrics([batch], merged)
    assert merged_metrics["false_merge_rate"] > 0.0
    singleton = {
        batch.batch_id: tuple(frozenset({str(item.report_id)}) for item in batch.truth)
    }
    split_metrics = calculate_grouping_metrics([batch], singleton)
    assert split_metrics["false_split_rate"] == 1.0


def test_validation_only_threshold_search_and_ablation():
    validation = tuple(
        _batch(scenario, ordinal)
        for scenario in EVENT_SCENARIOS
        for ordinal in range(3)
    )
    search = select_event_thresholds(validation)
    assert search["selection_split"] == "validation"
    assert search["test_rows_accessed_for_selection"] is False
    assert search["selected"]["spatial_radius_km"] == 5.0
    assert search["selected"]["temporal_window_minutes"] == 180.0
    assert search["selected"]["minimum_type_probability"] == 0.4
    ablation = run_validation_ablation(validation, FROZEN_CONFIG)
    assert {item["ablation"] for item in ablation["ablations"]} == {
        "spatial only",
        "temporal only",
        "type compatibility only",
        "spatial + temporal",
        "spatial + type",
        "temporal + type",
        "full system",
    }
    test_batches = tuple(_batch(item, split="test") for item in EVENT_SCENARIOS)
    with pytest.raises(EventValidationBlocked, match="VALIDATION_SPLIT"):
        select_event_thresholds(test_batches)


def test_deterministic_evaluation_excludes_runtime_measurements():
    batches = tuple(_batch(item) for item in EVENT_SCENARIOS)
    first = evaluate_event_configuration(batches, FROZEN_CONFIG)
    second = evaluate_event_configuration(batches, FROZEN_CONFIG)
    assert first["metrics"] == second["metrics"]
    assert first["error_report"] == second["error_report"]
    assert first["metrics"]["latency_results"]["latency_scope"] == (
        "ORDERED_SYNTHETIC_EVENT_STREAM_NOT_OPERATIONAL_LATENCY"
    )


def test_frozen_configuration_and_artifact_governance():
    artifact, config = load_event_development_artifact()
    assert artifact.artifact_kind == "DETERMINISTIC_CONFIGURATION_NOT_LEARNED_MODEL"
    assert artifact.production_validation == "NOT_VALIDATED"
    assert artifact.selection_split == "validation"
    assert artifact.test_rows_accessed_for_selection is False
    assert config.spatial_radius_km == 5.0
    assert config.temporal_window_minutes == 180.0
    payload = artifact.model_dump(mode="json")
    payload["policy"]["network_access"] = True
    with pytest.raises(ValidationError, match="network_access"):
        EventGroupingDevelopmentArtifact.model_validate(payload)
    development = json.loads(
        DEFAULT_DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    assert development["test_rows_accessed"] is False
    assert development["test_evaluation_invocation_count"] == 0


def test_final_test_receipt_is_one_shot_and_thresholds_are_frozen():
    receipt = json.loads(DEFAULT_FINAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    artifact = json.loads(DEFAULT_EVENT_ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "FINAL_EVALUATION_COMPLETE"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["test_used_for_tuning"] is False
    assert receipt["frozen_configuration"] == artifact["thresholds"]
    assert receipt["production_validation"] == "NOT_VALIDATED"
    with pytest.raises(RuntimeError, match="reevaluation is prohibited"):
        finalize_event_grouping_evaluation()


def test_duplicate_and_nlp_artifacts_are_unchanged():
    snapshot = protected_artifact_snapshot()
    for name, expected in EXPECTED_PROTECTED_HASHES.items():
        assert snapshot[name] == expected
        assert file_sha256(DEFAULT_EVENT_ARTIFACT_PATH.parent / name) == expected


def test_phase20_policy_scan_has_no_network_or_model_dependencies():
    roots = (
        Path(__file__).parents[1] / "data" / "synthetic_event" / "generator.py",
        Path(__file__).parents[1] / "training" / "event_validation.py",
        Path(__file__).parents[4] / "scripts" / "generate_synthetic_event_dataset.py",
        Path(__file__).parents[4] / "scripts" / "validate_event_grouping.py",
    )
    prohibited_imports = re.compile(
        r"^\s*(?:from|import)\s+(?:requests|httpx|urllib|transformers|torch|sentence_transformers|tensorflow)\b",
        re.MULTILINE,
    )
    for path in roots:
        assert prohibited_imports.search(path.read_text(encoding="utf-8")) is None
