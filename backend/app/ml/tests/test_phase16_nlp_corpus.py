from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ml.annotation.nlp_corpus_cli import main as nlp_corpus_cli_main
from app.ml.data.dataset_validation import validate_registered_dataset
from app.ml.data.loaders import load_csv
from app.ml.data.nlp_annotations import (
    PROTECTED_REPORTS_PATH,
    NLPAnnotationState,
    NLPEventLabel,
    NLPLanguage,
    adjudicate_nlp_case,
    assert_protected_nlp_assets_immutable,
    build_nlp_adjudication_case,
    create_nlp_human_annotation,
    load_nlp_source_reports,
)
from app.ml.data.nlp_corpus import (
    CorpusGroupingStatus,
    NLPAnnotationQueueStatus,
    NLPAnnotationQueueStatusStore,
    NLPQueueSamplingStrategy,
    create_queue_status_event,
    enroll_local_nlp_corpus,
    load_enrolled_nlp_corpus,
    queue_statuses,
    raw_nlp_reports_to_annotation_sources,
    write_nlp_annotation_queue,
)
from app.ml.data.nlp_dataset import (
    group_nlp_records,
    release_nlp_annotation_dataset,
    resolve_nlp_adjudications,
)
from app.ml.data.registry import (
    DatasetApprovalError,
    DatasetClassification,
    DatasetProvenance,
    DatasetRegistry,
    DatasetStatus,
    DatasetUse,
    approve_dataset,
    find_dataset,
    load_dataset_registry,
    save_dataset_registry,
)
from app.ml.data.schemas import DatasetSplit

FIXED_TIME = datetime(2026, 9, 23, 14, 30, tzinfo=timezone.utc)


def _write_json(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _valid_rows(count: int = 5) -> list[dict[str, object]]:
    languages: list[str | None] = ["English", "Hindi", "Hinglish", "Other", None]
    texts = [
        "  Phase sixteen preserves these leading spaces — exactly.  ",
        "नया स्थानीय विवरण क्रमांक दो, केवल परीक्षण हेतु।",
        "Naya local report teen, paani alag jagah par hai.",
        "Relatório local quatro para revisão humana.",
        "Fifth locally authored record with no supplied language or grouping.",
    ]
    rows: list[dict[str, object]] = []
    for index in range(count):
        row: dict[str, object] = {
            "report_id": f"phase16-{index + 1:02d}",
            "text": texts[index],
            "observed_at": f"2026-09-{index + 1:02d}T10:00:00+05:30",
            "submitted_at": f"2026-09-{index + 1:02d}T10:05:00+05:30",
            "latitude": 20.0 + index,
            "longitude": 70.0 + index,
            "source_type": "LOCAL_FIXTURE" if index < 3 else "LOCAL_EXPORT",
            "source_id": f"source-{index % 2}",
        }
        if languages[index] is not None:
            row["language"] = languages[index]
        if index < count - 1:
            row["event_id"] = f"event-{index + 1}"
            row["incident_id"] = f"incident-{index + 1}"
            row["source_report_family"] = f"family-{index + 1}"
        rows.append(row)
    return rows


def _enroll(
    tmp_path: Path,
    rows: list[dict[str, object]],
    *,
    dataset_id: str = "phase16-local-corpus",
    provenance: DatasetProvenance = DatasetProvenance.USER_SUPPLIED,
    source_name: str = "source.json",
    output_name: str = "enrolled",
):
    source = _write_json(tmp_path / source_name, rows)
    return enroll_local_nlp_corpus(
        source,
        dataset_id=dataset_id,
        dataset_version="v1",
        source_description="Deterministic local Phase 16 fixture corpus.",
        provenance_classification=provenance,
        output_directory=tmp_path / output_name,
        creation_timestamp=FIXED_TIME,
    )


def _issue_codes(result) -> set[str]:
    return {item.code for item in result.validation_report.issues}


def test_valid_corpus_enrollment_is_deterministic_and_preserves_original_text(
    tmp_path,
):
    rows = _valid_rows()
    source = _write_json(tmp_path / "source.json", rows)
    first = enroll_local_nlp_corpus(
        source,
        dataset_id="phase16-deterministic",
        dataset_version="v1",
        source_description="Explicitly supplied local records.",
        provenance_classification=DatasetProvenance.USER_SUPPLIED,
        output_directory=tmp_path / "first",
        creation_timestamp=FIXED_TIME,
    )
    second = enroll_local_nlp_corpus(
        source,
        dataset_id="phase16-deterministic",
        dataset_version="v1",
        source_description="Explicitly supplied local records.",
        provenance_classification=DatasetProvenance.USER_SUPPLIED,
        output_directory=tmp_path / "second",
        creation_timestamp=FIXED_TIME,
    )

    assert first.validation_report.valid is True
    assert first.enrollment_manifest.annotation_readiness == "READY"
    assert first.normalized_corpus_path is not None
    assert second.normalized_corpus_path is not None
    assert (
        first.source_manifest_path.read_bytes()
        == second.source_manifest_path.read_bytes()
    )
    assert (
        first.validation_report_path.read_bytes()
        == second.validation_report_path.read_bytes()
    )
    assert (
        first.normalized_corpus_path.read_bytes()
        == second.normalized_corpus_path.read_bytes()
    )
    loaded = load_enrolled_nlp_corpus(first.enrollment_directory)
    preserved = next(item for item in loaded.reports if item.report_id == "phase16-01")
    assert preserved.original_text == rows[0]["text"]
    assert preserved.text == rows[0]["text"]
    assert preserved.normalized_text != preserved.original_text
    assert (
        preserved.original_text_sha256
        == hashlib.sha256(str(rows[0]["text"]).encode("utf-8")).hexdigest()
    )
    assert preserved.raw_record_hash
    assert (
        preserved.provenance.source_content_hash == first.source_manifest.content_hash
    )
    annotation_sources = load_nlp_source_reports(first.normalized_corpus_path)
    adapted = raw_nlp_reports_to_annotation_sources(loaded.reports)
    assert annotation_sources == list(adapted)


@pytest.mark.parametrize("extension", ["csv", "jsonl"])
def test_csv_and_jsonl_are_supported_local_formats(tmp_path, extension):
    rows = _valid_rows(2)
    source = tmp_path / f"source.{extension}"
    if extension == "csv":
        import csv

        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        source.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows),
            encoding="utf-8",
            newline="\n",
        )
    result = enroll_local_nlp_corpus(
        source,
        dataset_id=f"phase16-{extension}",
        dataset_version="v1",
        source_description=f"Local {extension} fixture.",
        provenance_classification=DatasetProvenance.PROJECT_AUTHORED,
        output_directory=tmp_path / "out",
        creation_timestamp=FIXED_TIME,
    )
    assert result.validation_report.valid is True
    assert result.source_manifest.input_format == extension.upper()


def test_parquet_is_supported_when_local_dependency_exists(tmp_path):
    parquet = pytest.importorskip("pyarrow.parquet")
    pyarrow = pytest.importorskip("pyarrow")
    source = tmp_path / "source.parquet"
    parquet.write_table(pyarrow.Table.from_pylist(_valid_rows(2)), source)
    result = enroll_local_nlp_corpus(
        source,
        dataset_id="phase16-parquet",
        dataset_version="v1",
        source_description="Local Parquet fixture.",
        provenance_classification=DatasetProvenance.PROJECT_AUTHORED,
        output_directory=tmp_path / "out",
        creation_timestamp=FIXED_TIME,
    )
    assert result.validation_report.valid is True
    assert result.source_manifest.input_format == "PARQUET"


def test_phase16_cli_enrolls_and_builds_a_blind_queue(tmp_path):
    source = _write_json(tmp_path / "cli-source.json", _valid_rows(2))
    enrollment_root = tmp_path / "cli-enrollments"
    assert (
        nlp_corpus_cli_main(
            [
                "enroll",
                "--source",
                str(source),
                "--dataset-id",
                "phase16-cli",
                "--dataset-version",
                "v1",
                "--source-description",
                "Explicit local CLI fixture.",
                "--provenance",
                "PROJECT_AUTHORED",
                "--output-directory",
                str(enrollment_root),
                "--creation-timestamp",
                FIXED_TIME.isoformat(),
            ]
        )
        == 0
    )
    enrollment_directory = enrollment_root / "phase16-cli" / "v1"
    queue_directory = tmp_path / "cli-queue"
    assert (
        nlp_corpus_cli_main(
            [
                "queue",
                "--enrollment-directory",
                str(enrollment_directory),
                "--output-directory",
                str(queue_directory),
                "--strategy",
                "RANDOM",
                "--seed",
                "101",
                "--creation-timestamp",
                FIXED_TIME.isoformat(),
            ]
        )
        == 0
    )
    queue_payload = json.loads(
        (queue_directory / "annotation_queue.json").read_text(encoding="utf-8")
    )
    assert queue_payload["blind_annotation"] is True
    assert queue_payload["model_assistance_shown"] is False
    assert queue_payload["automatic_labels"] == "NONE"


@pytest.mark.parametrize(
    ("rows", "expected_code"),
    [
        ([{"report_id": "empty", "text": "   "}], "EMPTY_TEXT"),
        ([{"report_id": "missing-text"}], "MISSING_TEXT"),
        (
            [
                {"report_id": "duplicate", "text": "Unique one."},
                {"report_id": "duplicate", "text": "Unique two."},
            ],
            "DUPLICATE_REPORT_ID",
        ),
        (
            [
                {"report_id": "exact-1", "text": "Exact duplicate."},
                {"report_id": "exact-2", "text": "Exact duplicate."},
            ],
            "EXACT_DUPLICATE_TEXT",
        ),
        (
            [
                {"report_id": "normalized-1", "text": "Water   RISES"},
                {"report_id": "normalized-2", "text": "water rises"},
            ],
            "NORMALIZED_DUPLICATE_TEXT",
        ),
        (
            [
                {
                    "report_id": "bad-time",
                    "text": "Malformed timestamp fixture.",
                    "observed_at": "not-a-time",
                }
            ],
            "INVALID_TIMESTAMP",
        ),
        (
            [
                {
                    "report_id": "bad-coordinate",
                    "text": "Malformed coordinate fixture.",
                    "latitude": 91,
                    "longitude": 72,
                }
            ],
            "INVALID_COORDINATE",
        ),
        (
            [
                {
                    "report_id": "bad-language",
                    "text": "Unsupported explicit language fixture.",
                    "language": "French",
                }
            ],
            "INVALID_LANGUAGE",
        ),
    ],
)
def test_quality_errors_fail_closed_and_publish_no_annotation_corpus(
    tmp_path,
    rows,
    expected_code,
):
    result = _enroll(tmp_path, rows)
    assert result.validation_report.valid is False
    assert result.enrollment_manifest.annotation_readiness == "BLOCKED"
    assert result.normalized_corpus_path is None
    assert expected_code in _issue_codes(result)
    assert result.validation_report_path.name == "corpus_validation_report.json"
    with pytest.raises(ValueError, match="annotation queue is blocked"):
        load_enrolled_nlp_corpus(result.enrollment_directory)


def test_invalid_utf8_is_reported_and_fails_closed(tmp_path):
    source = tmp_path / "invalid.jsonl"
    source.write_bytes(b'{"report_id":"bad","text":"\xff"}\n')
    result = enroll_local_nlp_corpus(
        source,
        dataset_id="phase16-invalid-encoding",
        dataset_version="v1",
        source_description="Invalid UTF-8 fixture.",
        provenance_classification=DatasetProvenance.PROJECT_AUTHORED,
        output_directory=tmp_path / "out",
        creation_timestamp=FIXED_TIME,
    )
    assert result.validation_report.valid is False
    assert result.validation_report.encoding_problem_count == 1
    assert "ENCODING_ERROR" in _issue_codes(result)


def test_unknown_language_and_missing_grouping_are_explicit_not_inferred(tmp_path):
    rows = [
        {"report_id": "unknown-1", "text": "No language metadata was supplied."},
        {"report_id": "unknown-2", "text": "A second ungrouped local record."},
    ]
    result = _enroll(tmp_path, rows)
    assert result.validation_report.valid is True
    assert result.validation_report.grouping_status is (
        CorpusGroupingStatus.GROUPING_NOT_AVAILABLE
    )
    assert result.validation_report.grouped_count == 0
    assert result.validation_report.ungrouped_count == 2
    assert result.validation_report.language_counts[NLPLanguage.UNKNOWN.value] == 2
    assert "GROUPING_NOT_AVAILABLE" in _issue_codes(result)
    loaded = load_enrolled_nlp_corpus(result.enrollment_directory)
    assert {item.language for item in loaded.reports} == {NLPLanguage.UNKNOWN}
    assert all(item.event_id is None for item in loaded.reports)


def test_inconsistent_group_identifiers_fail_closed(tmp_path):
    rows = [
        {
            "report_id": "group-conflict-1",
            "text": "First group conflict fixture.",
            "event_id": "same-event",
            "incident_id": "incident-one",
        },
        {
            "report_id": "group-conflict-2",
            "text": "Second group conflict fixture.",
            "event_id": "same-event",
            "incident_id": "incident-two",
        },
    ]
    result = _enroll(tmp_path, rows)
    assert result.validation_report.valid is False
    assert "INCONSISTENT_GROUP_IDENTIFIERS" in _issue_codes(result)


def test_sealed_final_test_overlap_reports_ids_and_hashes_and_never_queues(
    tmp_path,
):
    protected = assert_protected_nlp_assets_immutable()
    final_record = next(
        item
        for item in load_csv(PROTECTED_REPORTS_PATH)
        if item.split is DatasetSplit.TEST
    )
    result = _enroll(
        tmp_path,
        [{"report_id": "forbidden-overlap", "text": final_record.text}],
    )
    assert result.validation_report.valid is False
    assert "FINAL_TEST_OVERLAP_DETECTED" in _issue_codes(result)
    assert len(result.validation_report.final_test_overlap) == 1
    overlap = result.validation_report.final_test_overlap[0]
    assert overlap.record_identifier == "forbidden-overlap"
    assert overlap.original_text_sha256 in protected.exact_text_hashes
    assert overlap.normalized_text_sha256 in protected.normalized_text_hashes
    assert result.normalized_corpus_path is None


def test_queue_order_and_all_sampling_modes_are_deterministic_priority_only(
    tmp_path,
):
    enrollment = _enroll(tmp_path, _valid_rows())
    corpus = load_enrolled_nlp_corpus(enrollment.enrollment_directory)
    all_ids = {item.report_id for item in corpus.reports}
    for strategy in NLPQueueSamplingStrategy:
        review_ids = (
            ["phase16-02", "phase16-04"]
            if strategy
            in {
                NLPQueueSamplingStrategy.UNCERTAINTY_REVIEW,
                NLPQueueSamplingStrategy.MODEL_ERROR_REVIEW,
            }
            else []
        )
        first = write_nlp_annotation_queue(
            corpus,
            output_directory=tmp_path / f"queue-{strategy.value}-one",
            sampling_strategy=strategy,
            seed=73,
            priority_count=2,
            review_report_ids=review_ids,
            created_at=FIXED_TIME,
        )
        second = write_nlp_annotation_queue(
            corpus,
            output_directory=tmp_path / f"queue-{strategy.value}-two",
            sampling_strategy=strategy,
            seed=73,
            priority_count=2,
            review_report_ids=review_ids,
            created_at=FIXED_TIME,
        )
        assert first.queue_path.read_bytes() == second.queue_path.read_bytes()
        assert len(first.queue.items) == len(corpus.reports)
        assert {item.report_id for item in first.queue.items} == all_ids
        assert sum(item.priority_selected for item in first.queue.items) == 2
        assert first.queue.underlying_distribution_unchanged is True
        assert first.queue.automatic_labels == "NONE"
        assert first.queue.blind_annotation is True
        assert first.queue.model_assistance_shown is False
        serialized = first.queue.model_dump(mode="json")
        assert all("label" not in item for item in serialized["items"])
        if review_ids:
            assert {item.report_id for item in first.queue.items[:2]} == set(review_ids)


def test_annotation_queue_report_uses_observed_counts_without_fabrication(tmp_path):
    enrollment = _enroll(tmp_path, _valid_rows())
    corpus = load_enrolled_nlp_corpus(enrollment.enrollment_directory)
    result = write_nlp_annotation_queue(
        corpus,
        output_directory=tmp_path / "queue",
        sampling_strategy=NLPQueueSamplingStrategy.LANGUAGE_BALANCED,
        seed=19,
        created_at=FIXED_TIME,
    )
    report = result.report
    assert report.total_reports == 5
    assert report.english_count == 1
    assert report.hindi_count == 1
    assert report.hinglish_count == 1
    assert report.other_count == 1
    assert report.unknown_count == 1
    assert report.grouped_count == 4
    assert report.ungrouped_count == 1
    assert sum(report.source_counts.values()) == 5
    assert report.date_range.earliest is not None
    assert report.date_range.latest is not None
    assert report.duplicate_report_id_count == 0
    assert report.exact_duplicate_text_count == 0
    assert report.normalized_duplicate_text_count == 0
    assert report.empty_text_count == 0
    assert (
        report.queue_hash == hashlib.sha256(result.queue_path.read_bytes()).hexdigest()
    )


def test_queue_statuses_are_append_only_label_free_and_require_adjudication(
    tmp_path,
):
    enrollment = _enroll(tmp_path, _valid_rows(2))
    corpus = load_enrolled_nlp_corpus(enrollment.enrollment_directory)
    queued = write_nlp_annotation_queue(
        corpus,
        output_directory=tmp_path / "queue",
        sampling_strategy=NLPQueueSamplingStrategy.RANDOM,
        seed=11,
        created_at=FIXED_TIME,
    )
    report_id = queued.queue.items[0].report_id
    store = NLPAnnotationQueueStatusStore(tmp_path / "queue-status.jsonl")
    events = []
    for status, kwargs in (
        (NLPAnnotationQueueStatus.IN_REVIEW, {}),
        (
            NLPAnnotationQueueStatus.LABELED,
            {"annotation_reference": "annotation-human-a"},
        ),
        (
            NLPAnnotationQueueStatus.ADJUDICATION_REQUIRED,
            {"annotation_reference": "annotation-human-a"},
        ),
        (
            NLPAnnotationQueueStatus.RELEASED,
            {
                "adjudication_id": "adjudication-human-a",
                "released_dataset_version": "candidate-v1",
            },
        ),
    ):
        event = create_queue_status_event(
            queued.queue,
            events,
            report_id=report_id,
            annotation_status=status,
            actor_id="phase16-human-operator",
            reason=f"Explicit transition to {status.value}.",
            timestamp=FIXED_TIME,
            **kwargs,
        )
        store.append(queued.queue, event)
        events.append(event)
    assert queue_statuses(queued.queue, store.load())[report_id] is (
        NLPAnnotationQueueStatus.RELEASED
    )
    assert all("label" not in item.model_dump() for item in store.load())
    other_report = queued.queue.items[1].report_id
    with pytest.raises(ValueError, match="invalid queue status transition"):
        create_queue_status_event(
            queued.queue,
            events,
            report_id=other_report,
            annotation_status=NLPAnnotationQueueStatus.RELEASED,
            actor_id="phase16-human-operator",
            reason="Cannot skip annotation and adjudication.",
            timestamp=FIXED_TIME,
            adjudication_id="invalid-direct-release",
            released_dataset_version="candidate-v1",
        )


def test_unknown_provenance_remains_unknown_and_blocks_release(tmp_path):
    enrollment = _enroll(
        tmp_path,
        _valid_rows(2),
        provenance=DatasetProvenance.PROVENANCE_UNKNOWN,
    )
    assert enrollment.source_manifest.provenance_classification is (
        DatasetProvenance.PROVENANCE_UNKNOWN
    )
    assert "PROVENANCE_UNKNOWN" in _issue_codes(enrollment)
    corpus = load_enrolled_nlp_corpus(enrollment.enrollment_directory)
    with pytest.raises(ValueError, match="known provenance"):
        release_nlp_annotation_dataset(
            raw_nlp_reports_to_annotation_sources(corpus.reports),
            [],
            [],
            dataset_id="unknown-provenance-release",
            dataset_version="v1",
            output_directory=tmp_path / "release",
            registry_path=tmp_path / "registry.json",
            split_assignments_by_group={},
            provenance=DatasetProvenance.PROVENANCE_UNKNOWN,
            source_description="Unknown provenance remains explicit.",
            license_or_usage_note="Not approved.",
            creation_timestamp=FIXED_TIME,
            source_manifest_path=corpus.source_manifest_path,
            source_manifest_hash=corpus.enrollment_manifest.source_manifest_hash,
        )


def test_source_manifest_tampering_blocks_queue_loading(tmp_path):
    enrollment = _enroll(tmp_path, _valid_rows(2))
    enrollment.source_manifest_path.write_text(
        enrollment.source_manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="source manifest hash mismatch"):
        load_enrolled_nlp_corpus(enrollment.enrollment_directory)


def test_human_adjudicated_release_binds_phase16_manifest_and_stays_candidate(
    tmp_path,
):
    rows = _valid_rows(4)
    rows[-1].update(
        {
            "event_id": "event-4",
            "incident_id": "incident-4",
            "source_report_family": "family-4",
        }
    )
    enrollment = _enroll(tmp_path, rows)
    corpus = load_enrolled_nlp_corpus(enrollment.enrollment_directory)
    reports = list(raw_nlp_reports_to_annotation_sources(corpus.reports))
    protected = assert_protected_nlp_assets_immutable()
    labels = [
        NLPEventLabel.URBAN_FLOOD,
        NLPEventLabel.RIVER_BREACH,
        NLPEventLabel.URBAN_FLOOD,
        NLPEventLabel.RIVER_BREACH,
    ]
    annotations = []
    decisions = []
    for report, label in zip(reports, labels, strict=True):
        annotation = create_nlp_human_annotation(
            report,
            state=NLPAnnotationState.LABELED,
            label=label,
            annotator_id=f"annotator-{report.report_id}",
            reason="Independent human label for the Phase 16 release fixture.",
            confidence=0.8,
            language=report.language_hint or NLPLanguage.UNKNOWN,
            timestamp=FIXED_TIME,
            annotation_id=f"annotation-{report.report_id}",
            protected_index=protected,
        )
        case = build_nlp_adjudication_case([annotation])
        adjudicated = adjudicate_nlp_case(
            case,
            final_state=NLPAnnotationState.LABELED,
            final_label=label,
            adjudicator_id="phase16-adjudicator",
            reason="Explicit human adjudication for candidate release.",
            timestamp=FIXED_TIME,
            adjudication_id=f"adjudication-{report.report_id}",
        )
        assert adjudicated.decision is not None
        annotations.append(annotation)
        decisions.append(adjudicated.decision)
    grouping = group_nlp_records(
        resolve_nlp_adjudications(
            reports,
            annotations,
            decisions,
            protected_index=protected,
        ).records
    )
    assignments = {
        record.split_assignment_key: ("train" if index < 2 else "validation")
        for index, record in enumerate(grouping.records)
    }
    registry_path = tmp_path / "registry" / "datasets.json"
    save_dataset_registry(
        DatasetRegistry(last_modified_at=FIXED_TIME),
        registry_path,
        modified_at=FIXED_TIME,
    )
    release = release_nlp_annotation_dataset(
        reports,
        annotations,
        decisions,
        dataset_id="phase16-human-candidate",
        dataset_version="v1",
        output_directory=tmp_path / "released",
        registry_path=registry_path,
        split_assignments_by_group=assignments,
        provenance=DatasetProvenance.USER_SUPPLIED,
        source_description=enrollment.source_manifest.source_description,
        license_or_usage_note="Authorized only for local candidate review.",
        creation_timestamp=FIXED_TIME,
        source_manifest_path=enrollment.source_manifest_path,
        source_manifest_hash=enrollment.enrollment_manifest.source_manifest_hash,
    )

    assert release.manifest.dataset_hash == release.manifest.content_hash
    assert release.manifest.annotation_schema_version == "nlp-human-annotation-v1"
    assert release.manifest.guide_version == "nlp-annotation-guide-v1"
    assert release.manifest.annotator_count == 4
    assert release.manifest.adjudicator_count == 1
    assert release.manifest.grouping_coverage == 1.0
    assert release.manifest.uncertainty_count == 0
    assert release.manifest.source_manifest_hash == (
        enrollment.enrollment_manifest.source_manifest_hash
    )
    assert release.manifest.leakage_report_hash
    registered = find_dataset(
        load_dataset_registry(registry_path),
        "phase16-human-candidate",
        "v1",
    )
    assert registered.status is DatasetStatus.DISCOVERED
    assert registered.data_classification is DatasetClassification.CANDIDATE_DATA
    assert registered.metadata["source_manifest_path"] == str(
        enrollment.source_manifest_path
    )
    validation = validate_registered_dataset(
        "phase16-human-candidate",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    assert validation.valid is True
    assert validation.component_readiness["source_manifest_hash"] == (
        enrollment.enrollment_manifest.source_manifest_hash
    )
    with pytest.raises(DatasetApprovalError):
        approve_dataset(
            "phase16-human-candidate",
            DatasetUse.TRAINING,
            approver_id="phase16-reviewer",
            approval_note="Fixture intentionally lacks an independent test split.",
            registry_path=registry_path,
            dataset_version="v1",
            approved_at=FIXED_TIME,
        )
    enrolled_source_path = Path(enrollment.source_manifest.local_path)
    enrolled_source_path.write_text(
        enrolled_source_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(DatasetApprovalError, match="ENROLLED_SOURCE_HASH_MISMATCH"):
        approve_dataset(
            "phase16-human-candidate",
            DatasetUse.TRAINING,
            approver_id="phase16-reviewer",
            approval_note="Changed source evidence must fail before approval.",
            registry_path=registry_path,
            dataset_version="v1",
            approved_at=FIXED_TIME,
        )
