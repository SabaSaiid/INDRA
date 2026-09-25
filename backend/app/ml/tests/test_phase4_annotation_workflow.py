from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ml.annotation.cli import format_pair_for_review, run_annotation_cli
from app.ml.data.adjudication import (
    adjudicate_case,
    build_adjudication_case,
    export_adjudicated_records,
)
from app.ml.data.annotations import AnnotationRecord, AnnotationStore, validate_annotation_quality
from app.ml.data.candidate_pairs import (
    CandidatePairRecord,
    LocalReportRecord,
    canonical_pair_key,
    deterministic_pair_id,
    generate_candidate_pairs,
)
from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord
from app.ml.data.leakage import validate_split_leakage
from app.ml.data.splits import grouped_duplicate_split
from app.ml.data.versioning import (
    build_dataset_version_manifest,
    dataset_content_sha256,
    dataset_manifest_sha256,
)
from app.ml.evaluation.evaluate import (
    calibrate_duplicate_threshold,
    evaluate_duplicate_pairs,
    evaluate_duplicate_test,
)


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase4-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _report(report_id: str, text: str, *, minutes: float = 0.0, latitude: float = 25.5941, event: str | None = None) -> LocalReportRecord:
    return LocalReportRecord(
        report_id=report_id,
        text=text,
        occurred_at=NOW + timedelta(minutes=minutes),
        latitude=latitude,
        longitude=85.1376,
        source_type="CITIZEN_APP",
        source_metadata={"fixture": "UNIT_TEST_ONLY"},
        event_id_when_known=event,
    )


def _candidate() -> CandidatePairRecord:
    return CandidatePairRecord(
        pair_id=deterministic_pair_id("r1", "r2"),
        report_a_id="r1",
        report_b_id="r2",
        time_delta_seconds=60.0,
        distance_km=0.1,
        text_summary={"token_jaccard": 0.5},
        candidate_score=0.5,
        candidate_score_label="LOCAL HEURISTIC SCORE — NOT GROUND TRUTH",
    )


def _annotation(candidate: CandidatePairRecord, annotator: str, label: DuplicatePairLabel, annotation_id: str) -> AnnotationRecord:
    return AnnotationRecord(
        annotation_id=annotation_id,
        pair_id=candidate.pair_id,
        report_a_id=candidate.report_a_id,
        report_b_id=candidate.report_b_id,
        label=label,
        annotator_id=annotator,
        annotation_timestamp=NOW,
        annotation_reason="UNIT_TEST_ONLY review reason",
    )


def _dataset_record(pair_id: str, a: str, b: str, label: DuplicatePairLabel, event: str, split: str) -> DuplicatePairRecord:
    return DuplicatePairRecord(
        pair_id=pair_id,
        report_a_id=a,
        report_b_id=b,
        label=label,
        annotator_id="adjudicator-1",
        annotation_timestamp=NOW,
        annotation_reason="UNIT_TEST_ONLY adjudication",
        label_provenance="UNIT_TEST_ONLY",
        event_id_when_known=event,
        split=split,
    )


def test_pair_canonicalization_and_deterministic_candidate_generation():
    assert canonical_pair_key("r2", "r1") == ("r1", "r2")
    assert deterministic_pair_id("r1", "r2") == deterministic_pair_id("r2", "r1")
    with pytest.raises(ValueError, match="self-pairs"):
        canonical_pair_key("r1", "r1")

    reports = [
        _report("r2", "Water is rising near the road", minutes=1),
        _report("r1", "Water rising near the road"),
        _report("r3", "Power outage at station", minutes=1, latitude=28.0),
    ]
    first = generate_candidate_pairs(reports)
    second = generate_candidate_pairs(list(reversed(reports)))
    assert [item.pair_id for item in first.candidates] == [item.pair_id for item in second.candidates]
    assert len(first.candidates) == 1
    assert first.candidates[0].status == "CANDIDATE_FOR_REVIEW"
    assert first.candidates[0].candidate_score_label == "LOCAL HEURISTIC SCORE — NOT GROUND TRUTH"


def test_annotation_serialization_append_only_and_multiple_annotators(local_tmp_path):
    candidate = _candidate()
    store = AnnotationStore(local_tmp_path / "annotations.jsonl")
    first = _annotation(candidate, "annotator-1", DuplicatePairLabel.DUPLICATE, "annotation-1")
    second = _annotation(candidate, "annotator-2", DuplicatePairLabel.UNCERTAIN, "annotation-2")
    store.append(first)
    store.append(second)
    assert [item.annotation_id for item in store.load()] == ["annotation-1", "annotation-2"]
    with pytest.raises(ValueError, match="same annotator"):
        store.append(_annotation(candidate, "annotator-1", DuplicatePairLabel.NOT_DUPLICATE, "annotation-3"))


def test_local_annotation_interface_is_blinded_by_default_and_requires_reason(capsys, local_tmp_path):
    candidate = _candidate()
    reports = {
        "r1": _report("r1", "Water is rising"),
        "r2": _report("r2", "Water rising near road"),
    }
    rendered = format_pair_for_review(candidate, reports)
    assert "MODEL SCORE" not in rendered
    assert "REPORT A" in rendered and "REPORT B" in rendered
    responses = iter(["U", "insufficient context"])
    created = run_annotation_cli(
        [candidate],
        reports,
        AnnotationStore(local_tmp_path / "annotations.jsonl"),
        annotator_id="annotator-1",
        input_fn=lambda _: next(responses),
    )
    assert created[0].label is DuplicatePairLabel.UNCERTAIN
    assert "MODEL SCORE" not in capsys.readouterr().out


def test_adjudication_keeps_disagreement_uncertain_until_explicit_decision():
    candidate = _candidate()
    first = _annotation(candidate, "annotator-1", DuplicatePairLabel.DUPLICATE, "annotation-1")
    second = _annotation(candidate, "annotator-2", DuplicatePairLabel.NOT_DUPLICATE, "annotation-2")
    case = build_adjudication_case([first, second])
    assert case.disagreement is True
    assert case.effective_label is DuplicatePairLabel.UNCERTAIN
    assert export_adjudicated_records([case]) == []
    resolved = adjudicate_case(
        case,
        adjudicated_label=DuplicatePairLabel.NOT_DUPLICATE,
        adjudicator_id="adjudicator-1",
        reason="separate observations after human review",
        timestamp=NOW,
    )
    exported = export_adjudicated_records([resolved])
    assert exported[0].label is DuplicatePairLabel.NOT_DUPLICATE


def test_quality_control_reports_counts_annotators_and_agreement():
    candidate = _candidate()
    reports = {"r1": _report("r1", "Water"), "r2": _report("r2", "Water rising")}
    annotations = [
        _annotation(candidate, "annotator-1", DuplicatePairLabel.DUPLICATE, "annotation-1"),
        _annotation(candidate, "annotator-2", DuplicatePairLabel.NOT_DUPLICATE, "annotation-2"),
    ]
    quality = validate_annotation_quality(annotations, [candidate], reports)
    assert quality.valid
    assert quality.total_pairs == 1
    assert quality.duplicate_labels == 1
    assert quality.non_duplicate_labels == 1
    assert quality.annotator_counts == {"annotator-1": 1, "annotator-2": 1}
    assert quality.agreement_status == "DATA_AVAILABLE"
    assert quality.agreement_rate == 0.0
    assert quality.disagreement_pairs == 1


def test_grouped_split_and_explicit_leakage_checks_cover_pair_event_incident_and_text():
    records = [
        _dataset_record("p1", "r1", "r2", DuplicatePairLabel.DUPLICATE, "event-1", "train"),
        _dataset_record("p2", "r2", "r1", DuplicatePairLabel.NOT_DUPLICATE, "event-1", "test"),
    ]
    leak = validate_split_leakage(
        {"train": [records[0]], "test": [records[1]]},
        report_text_by_id={"r1": "same text", "r2": "different"},
    )
    assert not leak.valid
    assert leak.pair_keys_across_splits
    assert leak.reversed_pair_keys_across_splits
    assert leak.event_ids_across_splits == ["event-1"]
    assert set(leak.exact_texts_across_splits) == {"same text", "different"}

    grouped = grouped_duplicate_split(
        [
            _dataset_record("p3", "r3", "r4", DuplicatePairLabel.DUPLICATE, "event-2", "train"),
            _dataset_record("p4", "r5", "r6", DuplicatePairLabel.NOT_DUPLICATE, "event-3", "train"),
            _dataset_record("p5", "r7", "r8", DuplicatePairLabel.UNCERTAIN, "event-4", "train"),
        ],
        seed=42,
    )
    assert grouped.status == "GROUPED_SPLIT_AVAILABLE"


def test_dataset_hash_and_manifest_are_deterministic():
    records = [_dataset_record("p1", "r1", "r2", DuplicatePairLabel.DUPLICATE, "event-1", "train")]
    first = dataset_content_sha256(records)
    second = dataset_content_sha256(list(reversed(records)))
    assert first == second
    manifest = build_dataset_version_manifest(
        records,
        dataset_version="duplicates-v1",
        source_hash="0" * 64,
        creation_timestamp=NOW,
    )
    assert dataset_manifest_sha256(manifest) == dataset_manifest_sha256(manifest)
    assert manifest.label_counts[DuplicatePairLabel.DUPLICATE.value] == 1
    assert manifest.split_counts["train"] == 1


def test_evaluation_rejects_insufficient_data_and_test_threshold_tuning():
    record = _dataset_record("p1", "r1", "r2", DuplicatePairLabel.DUPLICATE, "event-1", "validation")
    report = evaluate_duplicate_pairs([record], {"p1": 0.9}, [0.5])
    assert report.evaluation_status == "INSUFFICIENT_DATA"
    with pytest.raises(ValueError, match="test tuning"):
        calibrate_duplicate_threshold([True, False], [0.9, 0.1], [0.5], split_name="test")


def test_final_test_evaluation_uses_frozen_threshold_without_optimization():
    records = [
        _dataset_record("p1", "r1", "r2", DuplicatePairLabel.DUPLICATE, "event-1", "test"),
        _dataset_record("p2", "r3", "r4", DuplicatePairLabel.NOT_DUPLICATE, "event-2", "test"),
    ]
    result = evaluate_duplicate_test(
        records,
        {"p1": 0.9, "p2": 0.1},
        frozen_threshold=0.70,
    )
    assert result.evaluation_status == "DATA_AVAILABLE"
    assert result.threshold_sweep[0].threshold == 0.70
    assert result.duplicate_prevalence == 0.5


def test_invalid_label_and_invalid_report_context_are_rejected():
    with pytest.raises(ValidationError):
        AnnotationRecord(
            pair_id="p1",
            report_a_id="r1",
            report_b_id="r2",
            label="MAYBE",
            annotator_id="a1",
            annotation_timestamp=NOW,
            annotation_reason="reason",
        )
    with pytest.raises(ValidationError):
        LocalReportRecord(
            report_id="r1",
            text="text",
            occurred_at=NOW,
            latitude=95.0,
            longitude=85.0,
        )
