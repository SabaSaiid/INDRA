import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.ml.release_gate import (
    ALL_COMPONENTS,
    COMPONENT_REQUIREMENTS,
    DATASET_READINESS_PATH,
    FORMAL_REQUIREMENTS,
    NLP_METRICS_PATH,
    ComponentName,
    GateCheck,
    NLPReleaseThresholds,
    ProductionStatus,
    ReleaseAvailability,
    ReleaseGateConfig,
    current_component_statuses,
    evaluate_component_gate,
    load_current_nlp_evaluation,
    load_dataset_readiness,
    scan_new_ml_policy,
    validate_ml_release,
)


def _passing_check(requirement_id: str) -> GateCheck:
    return GateCheck(
        requirement_id=requirement_id,
        passed=True,
        evidence_status="PASS",
        evidence="independently verified test evidence",
    )


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase11-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def test_component_status_matrix_is_explicit_and_not_production_ready():
    statuses = current_component_statuses()
    assert set(statuses) == set(ALL_COMPONENTS)
    assert all(
        status.production_status is ProductionStatus.DEVELOPMENT_ONLY
        for status in statuses.values()
    )
    assert statuses[ComponentName.NLP].implementation_status.value == (
        "AVAILABLE_DEVELOPMENT"
    )
    assert statuses[ComponentName.DUPLICATE].calibration_status.value == (
        "PROVISIONAL / UNVALIDATED"
    )
    assert statuses[ComponentName.EVENT].model_status.value == "HEURISTIC_ONLY"
    assert statuses[ComponentName.CREDIBILITY].model_status.value == (
        "RULE_BASED_CREDIBILITY_BASELINE"
    )
    assert statuses[ComponentName.IMAGE].implementation_status.value == (
        "FRAMEWORK_ONLY"
    )
    assert statuses[ComponentName.ANOMALY].implementation_status.value == (
        "STATISTICAL_BASELINE"
    )


def test_dataset_readiness_report_has_six_components_and_explicit_nulls():
    report = load_dataset_readiness()
    assert set(report.components) == set(ALL_COMPONENTS)

    nlp = report.components[ComponentName.NLP]
    assert nlp.dataset_present is True
    assert nlp.label_count == 300
    assert nlp.train_count == 210
    assert nlp.validation_count is None
    assert nlp.test_count == 90
    assert nlp.independence_status == "NOT_ESTABLISHED"

    for component in set(ALL_COMPONENTS) - {ComponentName.NLP}:
        value = report.components[component]
        assert value.dataset_present is False
        assert value.dataset_version is None
        assert value.dataset_hash is None
        assert value.label_count is None
        assert value.train_count is None
        assert value.validation_count is None
        assert value.test_count is None


def test_historical_nlp_metrics_are_preserved_exactly():
    before = hashlib.sha256(NLP_METRICS_PATH.read_bytes()).hexdigest()
    metrics = load_current_nlp_evaluation()
    after = hashlib.sha256(NLP_METRICS_PATH.read_bytes()).hexdigest()

    assert before == after
    assert metrics.macro_precision == 0.8168253968253968
    assert metrics.macro_recall == 0.8111111111111111
    assert metrics.macro_f1 == 0.8104532163742689
    assert metrics.not_relevant_recall == 0.7777777777777778
    assert metrics.english.model_dump() == {
        "sample_count": 67,
        "accuracy": 0.8805970149253731,
        "macro_f1": 0.8831397560541052,
    }
    assert metrics.hindi.model_dump() == {
        "sample_count": 8,
        "accuracy": 0.625,
        "macro_f1": 0.5142857142857142,
    }
    assert metrics.hinglish.model_dump() == {
        "sample_count": 15,
        "accuracy": 0.6,
        "macro_f1": 0.5119047619047619,
    }
    assert metrics.historical_acceptance_passed is False
    assert metrics.production_validated is False


def test_component_gate_fails_closed_when_any_required_evidence_is_missing():
    result = evaluate_component_gate(ComponentName.NLP, {})
    expected = set(FORMAL_REQUIREMENTS) | set(
        COMPONENT_REQUIREMENTS[ComponentName.NLP]
    )
    assert set(result.checks) == expected
    assert result.passed is False
    assert result.production_status is ProductionStatus.DEVELOPMENT_ONLY
    assert all(check.evidence_status == "MISSING" for check in result.checks.values())


def test_component_gate_can_promote_only_with_every_required_check_passing():
    required = set(FORMAL_REQUIREMENTS) | set(
        COMPONENT_REQUIREMENTS[ComponentName.EVENT]
    )
    evidence = {key: _passing_check(key) for key in required}
    result = evaluate_component_gate(ComponentName.EVENT, evidence)
    assert result.passed is True
    assert result.production_status is ProductionStatus.PRODUCTION_VALIDATED
    assert result.blockers == []

    failed_key = "EVENT_GROUND_TRUTH"
    evidence[failed_key] = GateCheck(
        requirement_id=failed_key,
        passed=False,
        evidence_status="FAIL",
        evidence="ground truth unavailable",
    )
    failed = evaluate_component_gate(ComponentName.EVENT, evidence)
    assert failed.passed is False
    assert failed.production_status is ProductionStatus.DEVELOPMENT_ONLY


def test_nlp_release_thresholds_and_subgroup_requirements_are_configurable():
    metrics_hash = hashlib.sha256(NLP_METRICS_PATH.read_bytes()).hexdigest()
    default_result = validate_ml_release()
    assert (
        default_result.production_gates[ComponentName.NLP]
        .checks["NLP_NOT_RELEVANT_RECALL"]
        .passed
        is False
    )

    relaxed = ReleaseGateConfig(
        nlp=NLPReleaseThresholds(
            min_macro_f1=0.75,
            min_not_relevant_recall=0.70,
            required_language_subgroups=("en", "hi", "hinglish"),
            minimum_subgroup_rows={"en": 60, "hi": 8, "hinglish": 15},
        )
    )
    relaxed_result = validate_ml_release(relaxed)
    assert (
        relaxed_result.production_gates[ComponentName.NLP]
        .checks["NLP_NOT_RELEVANT_RECALL"]
        .passed
        is True
    )
    assert (
        relaxed_result.production_gates[ComponentName.NLP]
        .checks["NLP_MULTILINGUAL_SUBGROUPS"]
        .passed
        is True
    )
    assert relaxed_result.release_ready is False
    assert relaxed_result.overall_status is ProductionStatus.DEVELOPMENT_ONLY
    assert hashlib.sha256(NLP_METRICS_PATH.read_bytes()).hexdigest() == metrics_hash


def test_policy_scan_passes_current_subsystem_and_rejects_network_import(
    local_tmp_path,
):
    current = scan_new_ml_policy()
    assert current.compliant is True
    assert current.violations == []
    assert current.legacy_status == "LEGACY_BACKEND_VIOLATION"

    (local_tmp_path / "unsafe.py").write_text("import socket\n", encoding="utf-8")
    unsafe = scan_new_ml_policy(local_tmp_path)
    assert unsafe.compliant is False
    assert any("prohibited import socket" in item for item in unsafe.violations)


def test_unified_release_check_is_local_deterministic_and_fail_closed():
    first = validate_ml_release()
    second = validate_ml_release()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.release_ready is False
    assert first.overall_status is ProductionStatus.DEVELOPMENT_ONLY
    assert first.checks["contract_compatibility"].passed is True
    assert first.checks["artifact_authorization"].passed is True
    assert first.checks["artifact_availability"].passed is False
    assert first.checks["policy_compliance"].passed is True
    assert first.checks["version_consistency"].passed is True
    assert first.checks["missing_data_semantics"].passed is True
    assert first.checks["deterministic_inference"].passed is True
    assert first.checks["no_network_access"].passed is True
    assert first.checks["component_status"].passed is False
    assert first.checks["ml_tests_passing"].passed is True
    assert first.checks["full_backend_suite_verified"].passed is False
    assert first.checks["legacy_integration_migration"].passed is False
    assert first.test_environment.ml_tests == "ML_TESTS_PASSING"
    assert (
        first.test_environment.full_backend_suite
        == "FULL_BACKEND_TESTS_NOT_EXECUTED"
    )
    assert first.test_environment.blocker == "pytest_asyncio missing"


def test_release_result_identifies_required_component_states():
    result = validate_ml_release()
    dispositions = result.component_dispositions
    assert ReleaseAvailability.AVAILABLE in dispositions[ComponentName.NLP].states
    assert ReleaseAvailability.AVAILABLE in dispositions[ComponentName.DUPLICATE].states
    assert ReleaseAvailability.AVAILABLE in dispositions[ComponentName.EVENT].states
    assert (
        ReleaseAvailability.NOT_IMPLEMENTED
        not in dispositions[ComponentName.EVENT].states
    )
    assert ReleaseAvailability.AVAILABLE in dispositions[ComponentName.CREDIBILITY].states
    assert ReleaseAvailability.OFFLINE in dispositions[ComponentName.IMAGE].states
    assert (
        ReleaseAvailability.INSUFFICIENT_DATA
        in dispositions[ComponentName.ANOMALY].states
    )
    assert all(
        ReleaseAvailability.NOT_VALIDATED in disposition.states
        for disposition in dispositions.values()
    )
    assert DATASET_READINESS_PATH.is_file()
