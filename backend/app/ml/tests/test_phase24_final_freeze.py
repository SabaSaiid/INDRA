"""Phase 24 forensic freeze, policy, and fail-closed audit tests."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from app.ml.final_freeze import (
    COMPONENT_SPECS,
    DEFAULT_FINAL_FREEZE_PATH,
    DIRECT_SCENARIO_AUC_THRESHOLD,
    PRODUCTION_VALIDATION,
    VALIDATION_STATUS,
    _best_cross_split_discriminator,
    _rank_auc_by_category,
    _semantic_freeze,
    _synthetic_dependence_risks,
    audit_anomaly_feature_separability,
    audit_artifact_reproducibility,
    audit_frozen_hashes,
    audit_global_data_leakage,
    audit_legacy_embedding_references,
    audit_network_isolation,
    audit_protected_receipts,
    build_production_readiness_matrix,
    write_final_freeze_manifest,
)

EXPECTED_MATRIX_COLUMNS = [
    "component",
    "implementation_status",
    "model_type",
    "training_source",
    "dataset_type",
    "dataset_hash",
    "validation_status",
    "protected_test_status",
    "production_validation_status",
    "pretrained_model_used",
    "open_weight_model_used",
    "network_required",
    "backend_integration_status",
    "artifact_hash",
    "known_limitations",
]


def test_frozen_artifact_dataset_and_receipt_hashes_are_exact():
    hashes = audit_frozen_hashes()
    receipts = audit_protected_receipts()
    assert hashes["status"] == "PASS"
    assert hashes["shared_artifact_manifest_unchanged"] is True
    assert receipts["status"] == "PASS"
    assert receipts["protected_test_evaluations_invoked_by_phase_24"] == 0
    assert set(hashes["components"]) == set(COMPONENT_SPECS)
    for component, spec in COMPONENT_SPECS.items():
        row = hashes["components"][component]
        receipt = receipts["components"][component]
        assert row["artifact_sha256"] == spec["artifact_sha256"]
        assert row["dataset_sha256"] == spec["dataset_sha256"]
        assert receipt["receipt_sha256"] == spec["receipt_sha256"]
        assert receipt["evaluation_invocation_count"] == 1
        assert receipt["rerun_permitted"] is False


def test_readiness_matrix_has_exact_columns_and_fail_closed_statuses():
    rows = build_production_readiness_matrix()
    assert len(rows) == 6
    assert {row["component"] for row in rows} == set(COMPONENT_SPECS)
    assert all(list(row) == EXPECTED_MATRIX_COLUMNS for row in rows)
    for row in rows:
        assert row["validation_status"] == VALIDATION_STATUS
        assert row["production_validation_status"] == PRODUCTION_VALIDATION
        assert row["pretrained_model_used"] is False
        assert row["open_weight_model_used"] is False
        assert row["network_required"] is False
        assert row["backend_integration_status"] == ("NOT_INTEGRATED_DEVELOPMENT_ONLY")


def test_global_leakage_audit_fails_closed_only_for_phase20_evidence_gaps():
    audit = audit_global_data_leakage()
    assert audit["status"] == "FAIL"
    assert audit["failed_checks"] == {
        "EVENT": ["template_scenario_leakage", "parameter_leakage"]
    }
    assert audit["protected_test_evaluations_invoked_by_phase_24"] == 0
    for component in set(COMPONENT_SPECS) - {"EVENT"}:
        assert audit["components"][component]["overall_status"] == "PASS"


def test_all_artifacts_reproduce_inference_with_network_blocked():
    audit = audit_artifact_reproducibility()
    assert audit["status"] == "PASS"
    assert audit["protected_test_data_used"] is False
    assert audit["active_socket_guard"] is True
    for row in audit["components"].values():
        assert row["load_status"] == "PASS"
        assert row["required_metadata_status"] == "PASS"
        assert row["stable_sha256_status"] == "PASS"
        assert row["deterministic_inference_status"] == "PASS"
        assert row["network_guard_active"] is True
        assert row["network_required"] is False
        assert row["runtime_downloads"] is False
        assert row["external_model_files"] == []
        assert row["configuration_sufficient_for_inference"] is True


def test_phase24_historical_minilm_finding_is_immutable_and_current_path_is_removed():
    frozen = json.loads(DEFAULT_FINAL_FREEZE_PATH.read_text(encoding="utf-8"))
    assert frozen["legacy_minilm_audit"]["status"] == "LEGACY_BACKEND_VIOLATION"
    assert frozen["legacy_minilm_audit"]["live_backend_depends_on_embedding_model"]
    audit = audit_legacy_embedding_references()
    allowed = {
        "LIVE_PRODUCTION_PATH",
        "DEAD_CODE",
        "TEST_ONLY",
        "DOCUMENTATION_ONLY",
        "MIGRATION_TARGET",
    }
    assert audit["status"] == "REMOVED_FROM_LIVE_RUNTIME"
    assert audit["live_backend_depends_on_embedding_model"] is False
    assert audit["new_six_component_subsystem_depends_on_embedding_model"] is False
    assert audit["dead_legacy_classifier_importers"] == []
    assert set(audit["classification_counts"]).issubset(allowed)
    assert all(item["classification"] in allowed for item in audit["references"])
    assert audit["live_reference_files"] == []


def test_network_audit_distinguishes_frozen_subsystem_from_legacy_backend():
    frozen = json.loads(DEFAULT_FINAL_FREEZE_PATH.read_text(encoding="utf-8"))
    assert frozen["network_isolation_audit"]["status"] == "FAIL"
    audit = audit_network_isolation()
    assert audit["status"] == "PASS"
    assert audit["six_component_frozen_subsystem_status"] == "PASS"
    assert audit["repository_live_runtime_status"] == "PASS"
    assert audit["frozen_subsystem_network_access"] == "NONE"
    assert audit["static_policy_scan"]["compliant"] is True
    assert audit["boundary_independence"]["status"] == "PASS"
    assert audit["component_artifact_policy"]["status"] == "PASS"


def test_semantic_freeze_preserves_component_contracts():
    semantics = _semantic_freeze()
    event = semantics["EVENT"]
    assert event["single_report_lifecycle"] == "CANDIDATE"
    assert event["single_report_is_confirmed_event"] is False
    assert event["cluster_safeguard"] == "COMPLETE_LINK_ALL_MEMBER_PAIRS"
    assert event["automatic_single_report_confirmation"] is False
    credibility = semantics["CREDIBILITY"]
    assert credibility["output_labels"] == [
        "AUTHENTIC",
        "MISLEADING",
        "UNCERTAIN",
    ]
    assert credibility["model_output_is_ground_truth"] is False
    assert semantics["IMAGE"]["task_semantics"] == "MULTI_LABEL"
    assert semantics["IMAGE"]["model"] == "SCRATCH_CNN_V2"
    assert semantics["ANOMALY"]["separate_heads"] == [
        "DATA_QUALITY_ANOMALY",
        "WEATHER_BEHAVIOR_ANOMALY",
    ]
    assert semantics["ANOMALY"]["statistical_baseline_preserved"] is True


def test_directionless_auc_requires_cross_split_direct_discrimination():
    categories = np.asarray(["A", "A", "B", "B"], dtype=object)
    train = _rank_auc_by_category(np.asarray([0.0, 0.1, 0.9, 1.0]), categories)
    validation = _rank_auc_by_category(np.asarray([0.05, 0.15, 0.85, 0.95]), categories)
    result = _best_cross_split_discriminator(train, validation)
    assert result["cross_split_min_auc"] == 1.0
    assert result["direction_consistent"] is True
    assert result["cross_split_min_auc"] >= DIRECT_SCENARIO_AUC_THRESHOLD


def test_anomaly_audit_source_rejects_test_scope_before_file_access():
    source = inspect.getsource(audit_anomaly_feature_separability)
    assert "protected_test_labels_read" in source
    assert "protected_test_rows_read" in source
    from app.ml.final_freeze import _load_anomaly_audit_split

    with pytest.raises(ValueError, match="train/validation only"):
        _load_anomaly_audit_split("test")


def test_anomaly_high_risk_is_propagated_without_model_mutation():
    synthetic_audit = {
        "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "HIGH",
        "direct_scenario_features": ["feature-a"],
        "feature_count": 62,
    }
    risks = _synthetic_dependence_risks(synthetic_audit)
    assert risks["ANOMALY"]["SYNTHETIC_GENERATOR_DEPENDENCE_RISK"] == "HIGH"
    assert risks["EVENT"]["SYNTHETIC_GENERATOR_DEPENDENCE_RISK"] == "HIGH"


def test_final_manifest_writer_is_create_only():
    parent = Path(__file__).resolve().parents[3] / ".phase24-test-tmp"
    root = parent / f"case-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        output = root / "phase24.json"
        payload = {"freeze_version": "test", "sentinel": True}
        assert write_final_freeze_manifest(output, manifest=payload) == payload
        assert output.is_file()
        with pytest.raises(FileExistsError, match="already exists"):
            write_final_freeze_manifest(output, manifest=payload)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
