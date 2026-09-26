from __future__ import annotations

import argparse
import json
import shutil
import socket
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app.ml.data.cli import build_parser
from app.ml.data.dataset_validation import (
    CheckStatus,
    materialize_explicit_splits,
    validate_dataset_record,
    validate_registered_dataset,
)
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    AnomalyDataRole,
    DatasetApprovalError,
    DatasetClassification,
    DatasetComponent,
    DatasetFormat,
    DatasetProvenance,
    DatasetRegistry,
    DatasetRegistryRecord,
    DatasetStatus,
    DatasetUse,
    approve_dataset,
    find_dataset,
    hash_dataset_path,
    load_dataset_registry,
    register_dataset,
    safe_extract_local_zip,
    save_dataset_registry,
)
from app.ml.training.dataset_gate import (
    TrainingGateReason,
    evaluate_training_dataset,
)

FIXED_TIME = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_dataset_workspace():
    root = Path(__file__).resolve().parents[3] / ".phase13-test-tmp"
    case = (root / f"case-{uuid4().hex}").resolve()
    case.mkdir(parents=True, exist_ok=False)
    try:
        yield case
    finally:
        if case.is_relative_to(root.resolve()):
            shutil.rmtree(case)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _valid_nlp_rows() -> list[dict[str, str]]:
    examples = (
        (
            "train",
            "URBAN_FLOOD",
            "en",
            "City drain overflow at eastern market after overnight rain",
        ),
        (
            "train",
            "URBAN_FLOOD",
            "hi",
            "बस अड्डे के पास घरों में पानी घुस गया",
        ),
        (
            "train",
            "RIVER_BREACH",
            "en",
            "River embankment failed near Kaveri village at dawn",
        ),
        (
            "train",
            "RIVER_BREACH",
            "hi",
            "उत्तरी खेत सड़क के पास नदी का तटबंध टूटा",
        ),
        (
            "validation",
            "URBAN_FLOOD",
            "en",
            "Underpass flooded near the civic centre after an evening storm",
        ),
        (
            "validation",
            "RIVER_BREACH",
            "hi",
            "दक्षिणी गांव से नदी किनारे कटाव की सूचना मिली",
        ),
        (
            "test",
            "URBAN_FLOOD",
            "en",
            "Street water surrounded the railway colony during heavy showers",
        ),
        (
            "test",
            "RIVER_BREACH",
            "hi",
            "नदी का पानी पश्चिमी खेतों में बांध पार कर गया",
        ),
    )
    return [
        {
            "record_id": f"record-{index:02d}",
            "text": text,
            "event_type": label,
            "language": language,
            "split": split,
            "group_id": f"incident-{index:02d}",
        }
        for index, (split, label, language, text) in enumerate(examples, start=1)
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _empty_registry(workspace: Path) -> Path:
    path = workspace / "registry" / "datasets.json"
    save_dataset_registry(
        DatasetRegistry(last_modified_at=FIXED_TIME),
        path,
        modified_at=FIXED_TIME,
    )
    return path


def _register_nlp_dataset(
    workspace: Path,
    rows: list[dict] | None = None,
    *,
    dataset_id: str = "phase13-nlp",
    provenance: DatasetProvenance = DatasetProvenance.USER_SUPPLIED,
    classification: DatasetClassification = DatasetClassification.CANDIDATE_DATA,
) -> tuple[Path, Path, DatasetRegistryRecord]:
    registry_path = _empty_registry(workspace)
    dataset_path = workspace / "datasets" / f"{dataset_id}.jsonl"
    selected_rows = rows if rows is not None else _valid_nlp_rows()
    _write_jsonl(dataset_path, selected_rows)
    record = DatasetRegistryRecord(
        dataset_id=dataset_id,
        dataset_version="v1",
        component=DatasetComponent.NLP,
        local_path=str(dataset_path.resolve()),
        format=DatasetFormat.JSONL,
        content_sha256=hash_dataset_path(dataset_path).content_sha256,
        schema_version="nlp-report-dataset-v1",
        label_schema_version="event-type-labels-v1",
        creation_timestamp=FIXED_TIME,
        source_description="Locally supplied human-reviewed Phase 13 test corpus.",
        provenance=provenance,
        license_or_usage_note="Authorized only for local test execution.",
        grouping_field="group_id",
        split_field="split",
        label_count=len(selected_rows),
        row_or_image_count=len(selected_rows),
        data_classification=classification,
        human_adjudicated=True,
        label_source="INDEPENDENT_HUMAN_REVIEW",
    )
    register_dataset(
        record,
        registry_path=registry_path,
        modified_at=FIXED_TIME,
    )
    return registry_path, dataset_path, record


def _component_record(
    path: Path,
    component: DatasetComponent,
    *,
    dataset_format: DatasetFormat = DatasetFormat.JSONL,
    grouping_field: str,
    human_adjudicated: bool = True,
    label_source: str = "INDEPENDENT_HUMAN_REVIEW",
    classification: DatasetClassification = DatasetClassification.CANDIDATE_DATA,
    time_field: str | None = None,
    anomaly_data_role: AnomalyDataRole | None = None,
) -> DatasetRegistryRecord:
    return DatasetRegistryRecord(
        dataset_id=f"phase13-{component.value.casefold()}",
        dataset_version="v1",
        component=component,
        local_path=str(path.resolve()),
        format=dataset_format,
        content_sha256=hash_dataset_path(path).content_sha256,
        schema_version=f"{component.value.casefold()}-dataset-v1",
        label_schema_version=f"{component.value.casefold()}-labels-v1",
        creation_timestamp=FIXED_TIME,
        source_description="Local Phase 13 component validation fixture.",
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note="Local automated test use only.",
        grouping_field=grouping_field,
        time_field=time_field,
        label_count=0,
        row_or_image_count=0,
        data_classification=classification,
        human_adjudicated=human_adjudicated,
        label_source=label_source,
        anomaly_data_role=anomaly_data_role,
    )


def _approve_all_uses(registry_path: Path, dataset_id: str = "phase13-nlp") -> None:
    for use in (DatasetUse.TRAINING, DatasetUse.VALIDATION, DatasetUse.TEST):
        approve_dataset(
            dataset_id,
            use,
            approver_id="phase13-reviewer",
            approval_note=f"Independent approval for the explicit {use.value} split.",
            registry_path=registry_path,
            dataset_version="v1",
            approved_at=FIXED_TIME,
        )


def test_valid_dataset_generates_complete_component_and_leakage_report(
    local_dataset_workspace,
):
    registry_path, _, record = _register_nlp_dataset(local_dataset_workspace)

    report = validate_dataset_record(
        record,
        registry_path=registry_path,
        generated_at=FIXED_TIME,
    )

    assert report.valid is True
    assert report.validation_status == "VALID"
    assert report.hash_matches_registry is True
    assert report.row_or_image_count == 8
    assert report.label_count == 8
    assert report.split_counts == {"train": 4, "validation": 2, "test": 2}
    assert report.grouping_coverage == 1.0
    assert report.leakage.overall_status is CheckStatus.PASS
    assert report.component_readiness["class_counts"] == {
        "RIVER_BREACH": 4,
        "URBAN_FLOOD": 4,
    }
    assert report.approval_blockers == {
        "TRAINING": [],
        "VALIDATION": [],
        "TEST": [],
    }


def test_malformed_dataset_fails_schema_and_required_field_checks(
    local_dataset_workspace,
):
    rows = _valid_nlp_rows()
    rows[0].pop("text")
    registry_path, _, record = _register_nlp_dataset(
        local_dataset_workspace,
        rows,
    )

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is False
    assert any(error.startswith("row 1:") for error in report.errors)
    assert (
        next(
            check
            for check in report.checks
            if check.code == "SCHEMA_AND_REQUIRED_FIELDS"
        ).status
        is CheckStatus.FAIL
    )


def test_unknown_provenance_blocks_explicit_approval(local_dataset_workspace):
    registry_path, _, _ = _register_nlp_dataset(
        local_dataset_workspace,
        provenance=DatasetProvenance.PROVENANCE_UNKNOWN,
    )
    report = validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    assert report.valid is True
    assert "PROVENANCE_UNKNOWN" in report.approval_blockers["TRAINING"]

    with pytest.raises(DatasetApprovalError, match="PROVENANCE_UNKNOWN"):
        approve_dataset(
            "phase13-nlp",
            DatasetUse.TRAINING,
            approver_id="reviewer",
            approval_note="Approval must fail because provenance is unknown.",
            registry_path=registry_path,
            dataset_version="v1",
        )


def test_hash_mismatch_invalidates_validation_and_training(
    local_dataset_workspace,
):
    registry_path, dataset_path, record = _register_nlp_dataset(local_dataset_workspace)
    dataset_path.write_text(
        dataset_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )

    report = validate_dataset_record(record, registry_path=registry_path)
    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.NLP,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert report.valid is False
    assert report.hash_matches_registry is False
    assert "DATASET_HASH_MISMATCH" in report.errors
    assert TrainingGateReason.DATASET_HASH_MISMATCH.value in decision.reason_codes


def test_duplicate_rows_are_rejected(local_dataset_workspace):
    rows = _valid_nlp_rows()
    rows.append(dict(rows[0]))
    registry_path, _, record = _register_nlp_dataset(local_dataset_workspace, rows)

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is False
    assert "exact duplicate rows found" in report.errors
    duplicate_check = next(
        check for check in report.checks if check.code == "DUPLICATE_RECORDS"
    )
    assert duplicate_check.status is CheckStatus.FAIL


def test_cross_split_text_leakage_and_test_contamination_fail_closed(
    local_dataset_workspace,
):
    rows = _valid_nlp_rows()
    rows[-2]["text"] = rows[0]["text"]
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace, rows)

    report = validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.NLP,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert report.leakage.exact_duplicate_leakage.status is CheckStatus.FAIL
    assert report.leakage.overall_status is CheckStatus.FAIL
    assert TrainingGateReason.LEAKAGE_FAILURE.value in decision.reason_codes
    assert TrainingGateReason.TEST_CONTAMINATION.value in decision.reason_codes


def test_wrong_component_is_an_explicit_training_gate_reason(
    local_dataset_workspace,
):
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace)
    validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )

    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.DUPLICATE,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert decision.allowed is False
    assert TrainingGateReason.COMPONENT_MISMATCH.value in decision.reason_codes


@pytest.mark.parametrize(
    ("field", "value"),
    (("event_type", "INVENTED_LABEL"), ("split", "random_holdout")),
)
def test_wrong_labels_and_invalid_splits_fail_schema_validation(
    local_dataset_workspace,
    field,
    value,
):
    rows = _valid_nlp_rows()
    rows[0][field] = value
    registry_path, _, record = _register_nlp_dataset(local_dataset_workspace, rows)

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is False
    assert any(error.startswith("row 1:") for error in report.errors)
    assert report.approval_blockers["TRAINING"]


def test_insufficient_labels_are_reported_as_approval_and_training_blockers(
    local_dataset_workspace,
):
    rows = _valid_nlp_rows()
    for row in rows:
        row["event_type"] = "URBAN_FLOOD"
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace, rows)

    report = validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.NLP,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert report.valid is True
    assert "INSUFFICIENT_LABELS" in report.approval_blockers["TRAINING"]
    assert TrainingGateReason.INSUFFICIENT_LABELS.value in decision.reason_codes


def test_approval_fails_before_validation_can_bind_a_report(local_dataset_workspace):
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace)

    with pytest.raises(DatasetApprovalError, match="DATASET_STATUS_DISCOVERED"):
        approve_dataset(
            "phase13-nlp",
            DatasetUse.TRAINING,
            approver_id="reviewer",
            approval_note="This must not bypass independent validation.",
            registry_path=registry_path,
            dataset_version="v1",
        )


def test_successful_split_scoped_approval_authorizes_training(
    local_dataset_workspace,
):
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace)
    report = validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    assert report.valid and report.leakage.overall_status is CheckStatus.PASS

    _approve_all_uses(registry_path)
    registered = find_dataset(
        load_dataset_registry(registry_path),
        "phase13-nlp",
        "v1",
    )
    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.NLP,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert {approval.use for approval in registered.approvals} == set(DatasetUse)
    assert registered.status is DatasetStatus.APPROVED_TEST
    assert decision.allowed is True
    assert decision.reason_codes == []


def test_training_is_blocked_when_valid_dataset_has_no_approvals(
    local_dataset_workspace,
):
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace)
    validate_registered_dataset(
        "phase13-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )

    decision = evaluate_training_dataset(
        "phase13-nlp",
        DatasetComponent.NLP,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert decision.allowed is False
    assert {
        "APPROVAL_MISSING:TRAINING",
        "APPROVAL_MISSING:VALIDATION",
        "APPROVAL_MISSING:TEST",
    }.issubset(decision.reason_codes)


def test_unified_validator_reports_duplicate_event_and_credibility_readiness(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    splits = ["train"] * 4 + ["validation"] * 2 + ["test"] * 2
    labels = [0, 1, 0, 1, 0, 1, 0, 1]

    duplicate_rows = [
        {
            "pair_id": f"pair-{index}",
            "report_a_id": f"report-a-{index}",
            "report_b_id": f"report-b-{index}",
            "label": "DUPLICATE" if labels[index] == 0 else "NOT_DUPLICATE",
            "annotator_id": "human-reviewer",
            "annotation_timestamp": "2026-09-22T10:00:00Z",
            "annotation_reason": "Independent comparison of the report pair.",
            "label_provenance": "human-adjudication-v1",
            "event_id_when_known": f"duplicate-event-{index}",
            "split": splits[index],
        }
        for index in range(8)
    ]
    duplicate_path = local_dataset_workspace / "duplicate.jsonl"
    _write_jsonl(duplicate_path, duplicate_rows)
    duplicate_record = _component_record(
        duplicate_path,
        DatasetComponent.DUPLICATE,
        grouping_field="event_id_when_known",
    )

    event_rows = [
        {
            "report_id": f"event-report-{index}",
            "event_id": f"candidate-event-{index}",
            "label": "ASSIGNED" if labels[index] == 0 else "NOT_ASSIGNED",
            "annotator_id": "human-reviewer",
            "reason": "Independent report-to-event assessment.",
            "timestamp": "2026-09-22T10:00:00Z",
            "canonical_event_id": f"canonical-event-{index}",
            "event_type": "URBAN_FLOOD" if labels[index] == 0 else "RIVER_BREACH",
            "split": splits[index],
        }
        for index in range(8)
    ]
    event_path = local_dataset_workspace / "event.jsonl"
    _write_jsonl(event_path, event_rows)
    event_record = _component_record(
        event_path,
        DatasetComponent.EVENT,
        grouping_field="canonical_event_id",
    )

    source_texts = [row["text"] for row in _valid_nlp_rows()]
    credibility_rows = [
        {
            "annotation_id": f"credibility-annotation-{index}",
            "report_id": f"credibility-report-{index}",
            "label": "AUTHENTIC" if labels[index] == 0 else "MISLEADING",
            "annotator_id": "human-reviewer",
            "annotation_timestamp": "2026-09-22T10:00:00Z",
            "reason": "Independent source and evidence review.",
            "report_family_id": f"report-family-{index}",
            "report_text": source_texts[index],
            "split": splits[index],
            "blinded": True,
        }
        for index in range(8)
    ]
    credibility_path = local_dataset_workspace / "credibility.jsonl"
    _write_jsonl(credibility_path, credibility_rows)
    credibility_record = _component_record(
        credibility_path,
        DatasetComponent.CREDIBILITY,
        grouping_field="report_family_id",
    )

    reports = {
        component: validate_dataset_record(record, registry_path=registry_path)
        for component, record in {
            DatasetComponent.DUPLICATE: duplicate_record,
            DatasetComponent.EVENT: event_record,
            DatasetComponent.CREDIBILITY: credibility_record,
        }.items()
    }

    assert all(report.valid for report in reports.values())
    assert all(
        report.leakage.overall_status is CheckStatus.PASS for report in reports.values()
    )
    assert reports[DatasetComponent.DUPLICATE].component_readiness["pair_count"] == 8
    assert reports[DatasetComponent.EVENT].component_readiness["event_count"] == 8
    assert (
        reports[DatasetComponent.CREDIBILITY].component_readiness["authentic_count"]
        == 4
    )


def test_image_dataset_checks_real_files_hashes_groups_and_resolution(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    dataset_path = local_dataset_workspace / "images"
    dataset_path.mkdir()
    splits = ["train"] * 4 + ["validation"] * 2 + ["test"] * 2
    annotations = []
    for index, split in enumerate(splits):
        image_path = dataset_path / f"image-{index}.png"
        Image.new(
            "RGB",
            (2, 2),
            color=(index * 20, 255 - index * 20, index * 10),
        ).save(image_path, format="PNG")
        annotations.append(
            {
                "annotation_id": f"image-annotation-{index}",
                "image_id": f"image-{index}",
                "image_path": image_path.name,
                "labels": ["FLOODED_SCENE" if index % 2 == 0 else "NORMAL_SCENE"],
                "annotator_id": "human-reviewer",
                "annotation_timestamp": "2026-09-22T10:00:00Z",
                "reason": "Visible-scene review for local validator coverage.",
                "byte_sha256": hash_dataset_path(image_path).content_sha256,
                "width": 2,
                "height": 2,
                "detected_format": "PNG",
                "capture_session_id": f"capture-{index}",
                "split": split,
            }
        )
    _write_jsonl(dataset_path / "annotations.jsonl", annotations)
    record = _component_record(
        dataset_path,
        DatasetComponent.IMAGE,
        dataset_format=DatasetFormat.DIRECTORY,
        grouping_field="capture_session_id",
        classification=DatasetClassification.TEST_FIXTURE_ONLY,
    )

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is True
    assert report.component_readiness["image_count"] == 8
    assert report.component_readiness["corrupt_images"] == []
    assert report.component_readiness["duplicate_hashes"] == {}
    assert report.component_readiness["resolution_distribution"] == {"2x2": 8}
    assert "TEST_FIXTURE_ONLY_DATASET" in report.approval_blockers["TRAINING"]


def test_unsupervised_anomaly_baseline_has_separate_training_approval_path(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    dataset_path = local_dataset_workspace / "anomaly-baseline.jsonl"
    splits = ["train"] * 4 + ["validation"] * 2 + ["test"] * 2
    rows = [
        {
            "observation_id": f"observation-{index}",
            "station_id": f"station-{index}",
            "observed_at": f"2026-09-22T{index:02d}:00:00Z",
            "rainfall_mm": float(index),
            "river_level_m": float(index) / 10.0,
            "split": splits[index],
        }
        for index in range(8)
    ]
    _write_jsonl(dataset_path, rows)
    record = _component_record(
        dataset_path,
        DatasetComponent.ANOMALY,
        grouping_field="station_id",
        human_adjudicated=False,
        label_source="HISTORICAL_OBSERVATIONS",
        time_field="observed_at",
        anomaly_data_role=AnomalyDataRole.UNSUPERVISED_BASELINE,
    )
    register_dataset(
        record,
        registry_path=registry_path,
        modified_at=FIXED_TIME,
    )

    report = validate_registered_dataset(
        record.dataset_id,
        registry_path=registry_path,
        dataset_version=record.dataset_version,
        generated_at=FIXED_TIME,
    )
    assert report.valid is True
    assert report.leakage.temporal_leakage.status is CheckStatus.PASS
    assert report.approval_blockers["TRAINING"] == []
    assert (
        "UNSUPERVISED_BASELINE_NOT_EVALUATION_GROUND_TRUTH"
        in (report.approval_blockers["TEST"])
    )

    approve_dataset(
        record.dataset_id,
        DatasetUse.TRAINING,
        approver_id="baseline-reviewer",
        approval_note="Approved only as an unsupervised historical baseline.",
        registry_path=registry_path,
        dataset_version=record.dataset_version,
        approved_at=FIXED_TIME,
    )
    decision = evaluate_training_dataset(
        record.dataset_id,
        DatasetComponent.ANOMALY,
        registry_path=registry_path,
        dataset_version=record.dataset_version,
    )
    assert decision.allowed is True


def test_registered_custom_split_field_is_used_without_random_assignment(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    rows = _valid_nlp_rows()
    for row in rows:
        row["partition"] = row.pop("split")
    dataset_path = local_dataset_workspace / "custom-split.jsonl"
    _write_jsonl(dataset_path, rows)
    record = _component_record(
        dataset_path,
        DatasetComponent.NLP,
        grouping_field="group_id",
        human_adjudicated=False,
        label_source="INDEPENDENT_HUMAN_REVIEW",
    ).model_copy(update={"split_field": "partition"})

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is True
    assert report.split_counts == {"train": 4, "validation": 2, "test": 2}
    assert report.leakage.overall_status is CheckStatus.PASS


def test_structured_multifile_directory_is_loaded_in_canonical_shard_order(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    dataset_path = local_dataset_workspace / "nlp-shards"
    rows = _valid_nlp_rows()
    _write_jsonl(dataset_path / "z-test.jsonl", rows[4:])
    _write_jsonl(dataset_path / "a-train.jsonl", rows[:4])
    record = _component_record(
        dataset_path,
        DatasetComponent.NLP,
        dataset_format=DatasetFormat.DIRECTORY,
        grouping_field="group_id",
        human_adjudicated=False,
        label_source="INDEPENDENT_HUMAN_REVIEW",
    )

    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is True
    assert report.row_or_image_count == 8
    assert report.split_counts == {"train": 4, "validation": 2, "test": 2}
    assert report.leakage.overall_status is CheckStatus.PASS


def test_illegal_coordinates_and_naive_registered_timestamps_are_rejected(
    local_dataset_workspace,
):
    registry_path = _empty_registry(local_dataset_workspace)
    rows = _valid_nlp_rows()
    for row in rows:
        row["observed_at"] = "2026-09-22T10:00:00"
    rows[0]["latitude"] = 91.0
    rows[0]["longitude"] = 72.0
    dataset_path = local_dataset_workspace / "invalid-values.jsonl"
    _write_jsonl(dataset_path, rows)
    record = _component_record(
        dataset_path,
        DatasetComponent.NLP,
        grouping_field="group_id",
        human_adjudicated=False,
        label_source="INDEPENDENT_HUMAN_REVIEW",
        time_field="observed_at",
    )

    report = validate_dataset_record(record, registry_path=registry_path)
    checks = {check.code: check.status for check in report.checks}

    assert report.valid is False
    assert checks["COORDINATE_VALIDITY"] is CheckStatus.FAIL
    assert checks["TIMESTAMP_VALIDITY"] is CheckStatus.FAIL


def test_file_and_multifile_dataset_hashing_is_deterministic(
    local_dataset_workspace,
):
    first_file = local_dataset_workspace / "first.bin"
    second_file = local_dataset_workspace / "second.bin"
    first_file.write_bytes(b"identical-local-bytes")
    second_file.write_bytes(b"identical-local-bytes")

    left = local_dataset_workspace / "left"
    right = local_dataset_workspace / "right"
    (left / "nested").mkdir(parents=True)
    (right / "nested").mkdir(parents=True)
    (left / "a.txt").write_text("alpha", encoding="utf-8")
    (left / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    (right / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    (right / "a.txt").write_text("alpha", encoding="utf-8")

    assert (
        hash_dataset_path(first_file).content_sha256
        == hash_dataset_path(second_file).content_sha256
    )
    assert (
        hash_dataset_path(left).content_sha256
        == hash_dataset_path(right).content_sha256
    )
    assert [entry.relative_path for entry in hash_dataset_path(left).entries] == [
        "a.txt",
        "nested/b.txt",
    ]


def test_dataset_operations_make_no_network_calls(local_dataset_workspace, monkeypatch):
    attempted: list[str] = []

    def deny_network(*args, **kwargs):
        attempted.append("network")
        raise AssertionError("dataset operations attempted network access")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", deny_network)
    registry_path, dataset_path, record = _register_nlp_dataset(local_dataset_workspace)

    hash_dataset_path(dataset_path)
    report = validate_dataset_record(record, registry_path=registry_path)

    assert report.valid is True
    assert attempted == []


def test_explicit_splits_are_materialized_without_random_assignment(
    local_dataset_workspace,
):
    registry_path, _, _ = _register_nlp_dataset(local_dataset_workspace)
    output_directory = local_dataset_workspace / "splits"

    outputs = materialize_explicit_splits(
        "phase13-nlp",
        output_directory,
        registry_path=registry_path,
        dataset_version="v1",
    )

    assert set(outputs) == {"train", "validation", "test"}
    assert {
        split: len(path.read_text(encoding="utf-8").splitlines())
        for split, path in outputs.items()
    } == {"train": 4, "validation": 2, "test": 2}


def test_archive_extraction_rejects_path_traversal(local_dataset_workspace):
    archive = local_dataset_workspace / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("safe/first.jsonl", "{}\n")
        handle.writestr("../escape.jsonl", "{}\n")

    destination = local_dataset_workspace / "extracted"
    with pytest.raises(ValueError, match="unsafe archive member path"):
        safe_extract_local_zip(archive, destination)
    assert not (destination / "safe" / "first.jsonl").exists()


def test_registry_covers_all_components_and_cli_exposes_local_commands():
    assert {item.value for item in DatasetComponent} == {
        "NLP",
        "DUPLICATE",
        "EVENT",
        "CREDIBILITY",
        "IMAGE",
        "ANOMALY",
    }
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert {
        "discover-dataset",
        "validate-dataset",
        "hash-dataset",
        "report-dataset",
        "approve-dataset",
        "split-dataset",
        "verify-leakage",
    }.issubset(subparsers.choices)


def test_committed_synthetic_nlp_dataset_remains_development_only():
    registry = load_dataset_registry(DEFAULT_DATASET_REGISTRY_PATH)
    record = find_dataset(
        registry,
        "indra-nlp-reports-v1-synthetic",
        "reports-v1-development-synthetic",
    )
    report = validate_dataset_record(
        record,
        registry_path=DEFAULT_DATASET_REGISTRY_PATH,
        generated_at=FIXED_TIME,
    )

    assert record.data_classification is DatasetClassification.DEVELOPMENT_ONLY
    assert record.approvals == []
    assert report.valid is True
    assert report.leakage.overall_status is CheckStatus.INSUFFICIENT_EVIDENCE
    assert "DEVELOPMENT_ONLY_DATASET" in report.approval_blockers["TRAINING"]
