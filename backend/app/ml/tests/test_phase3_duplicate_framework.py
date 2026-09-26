import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import pytest

from app.ml.components.duplicate_features import feature_state_sha256, load_feature_state
from app.ml.components.duplicate_matching import DuplicateMatcher, _sparse_cosine, normalize_text
from app.ml.config import DEFAULT_DUPLICATE_MATCHING_CONFIG, load_artifact_manifest
from app.ml.contracts import CandidateReport, ReportInput
from app.ml.data.duplicate_pairs import (
    DuplicatePairLabel,
    DuplicatePairRecord,
    validate_duplicate_pairs,
)
from app.ml.data.splits import grouped_duplicate_split
from app.ml.evaluation.evaluate import (
    calibrate_duplicate_threshold,
    evaluate_duplicate_pairs,
)


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase10-test-tmp"
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


def _candidate(number: int, text: str, *, minutes: float = 0.0) -> CandidateReport:
    return CandidateReport(
        report_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        text=text,
        occurred_at=NOW + timedelta(minutes=minutes),
        latitude=25.5941,
        longitude=85.1376,
        source_type="CITIZEN_APP",
    )


def _report(text: str, candidates: list[CandidateReport]) -> ReportInput:
    return ReportInput(
        report_id=UUID("10000000-0000-0000-0000-000000000001"),
        text=text,
        occurred_at=NOW,
        latitude=25.5941,
        longitude=85.1376,
        source_type="CITIZEN_APP",
        candidate_reports=candidates,
    )


def _pair(pair_id: str, a: int, b: int, label: DuplicatePairLabel, event: str, annotator: str = "reviewer-1") -> DuplicatePairRecord:
    return DuplicatePairRecord(
        pair_id=pair_id,
        report_a_id=UUID(f"00000000-0000-0000-0000-{a:012d}"),
        report_b_id=UUID(f"00000000-0000-0000-0000-{b:012d}"),
        label=label,
        annotator_id=annotator,
        annotation_timestamp="2026-09-21T12:00:00Z",
        annotation_reason="unit fixture only",
        label_provenance="UNIT_TEST_ONLY",
        event_id=event,
    )


def test_frozen_state_and_pair_score_are_independent_of_unrelated_candidates():
    matcher = DuplicateMatcher()
    text = "Water is rising near Rajendra Nagar road"
    base = matcher.predict(_report(text, [_candidate(1, "Water rising near Rajendra Nagar road")]))
    expanded = matcher.predict(
        _report(
            text,
            [
                _candidate(1, "Water rising near Rajendra Nagar road"),
                _candidate(2, "Power outage near station"),
                _candidate(3, "Traffic signal is not working near the market"),
            ],
        )
    )
    assert base.candidate_id == expanded.candidate_id
    assert base.similarity == expanded.similarity
    assert base.text_similarity == expanded.text_similarity
    assert feature_state_sha256(matcher.feature_state) == feature_state_sha256(matcher.feature_state)


def test_feature_state_metadata_is_frozen_development_only():
    matcher = DuplicateMatcher()
    assert matcher.feature_state is not None
    assert matcher.feature_state.development_only is True
    assert matcher.feature_state.corpus_identifier.endswith("development_feature_corpus.txt")
    assert len(matcher.feature_state.corpus_sha256) == 64
    before = feature_state_sha256(matcher.feature_state)
    matcher.predict(_report("Water is rising near Rajendra Nagar road", [_candidate(1, "Water rising near Rajendra Nagar road")]))
    assert feature_state_sha256(matcher.feature_state) == before


def test_feature_state_is_manifest_authorized_and_rejects_tampering(local_tmp_path):
    source = DEFAULT_DUPLICATE_MATCHING_CONFIG.feature_state_path
    manifest = load_artifact_manifest()
    entry = next(
        item
        for item in manifest.artifacts
        if item.intended_component == "duplicate_matcher"
    )
    assert entry.artifact_name == source.name
    assert entry.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    state = load_feature_state(source)
    assert state.state_version == entry.artifact_version
    assert state.corpus_sha256 == entry.training_dataset_hash

    artifact_path = local_tmp_path / source.name
    manifest_path = local_tmp_path / "manifest.json"
    artifact_path.write_bytes(source.read_bytes())
    manifest_path.write_text(
        manifest.model_copy(update={"artifacts": [entry]}).model_dump_json(indent=2),
        encoding="utf-8",
    )
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash does not match manifest"):
        load_feature_state(artifact_path, manifest_path=manifest_path)

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["feature_version"] = "unexpected-features-v2"
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    mismatched_entry = entry.model_copy(
        update={"sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest()}
    )
    manifest_path.write_text(
        manifest.model_copy(update={"artifacts": [mismatched_entry]}).model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="feature-state provenance mismatch"):
        load_feature_state(artifact_path, manifest_path=manifest_path)


def test_duplicate_schema_and_grouped_validation_flags_reversed_contradictory_and_leakage():
    first = _pair("pair-1", 1, 2, DuplicatePairLabel.DUPLICATE, "event-1")
    reversed_pair = _pair("pair-2", 2, 1, DuplicatePairLabel.NOT_DUPLICATE, "event-1", annotator="reviewer-2")
    reversed_pair = reversed_pair.model_copy(update={"split": "test"})
    first = first.model_copy(update={"split": "train"})
    report = validate_duplicate_pairs([first, reversed_pair])
    assert not report.valid
    assert report.reversed_pair_ids == ["pair-2"]
    assert report.contradictory_pair_keys
    assert report.leakage_groups == ["event_id:event-1"]


def test_grouped_split_is_deterministic_and_unavailable_without_group_key():
    records = [
        _pair(f"pair-{index}", index * 2 + 1, index * 2 + 2, DuplicatePairLabel.DUPLICATE, f"event-{index}")
        for index in range(6)
    ]
    first = grouped_duplicate_split(records, seed=17)
    second = grouped_duplicate_split(records, seed=17)
    assert first.status == "GROUPED_SPLIT_AVAILABLE"
    assert [record.pair_id for record in first.train] == [record.pair_id for record in second.train]
    assert {record.event_id for record in first.train}.isdisjoint(
        {record.event_id for record in first.validation + first.test}
    )
    unavailable = grouped_duplicate_split([record.model_copy(update={"event_id": None, "incident_id": None}) for record in records])
    assert unavailable.status == "GROUPED_SPLIT_UNAVAILABLE"


def test_evaluation_excludes_uncertain_and_rejects_test_threshold_tuning():
    records = [
        _pair("pair-1", 1, 2, DuplicatePairLabel.DUPLICATE, "event-1"),
        _pair("pair-2", 3, 4, DuplicatePairLabel.NOT_DUPLICATE, "event-2"),
        _pair("pair-3", 5, 6, DuplicatePairLabel.UNCERTAIN, "event-3"),
    ]
    result = evaluate_duplicate_pairs(
        records,
        {"pair-1": 0.9, "pair-2": 0.1},
        [0.5, 0.7],
    )
    assert result.evaluation_status == "DATA_AVAILABLE"
    assert result.number_labeled_pairs == 2
    assert result.excluded_uncertain_pairs == 1
    with pytest.raises(ValueError, match="test tuning"):
        calibrate_duplicate_threshold([True, False], [0.9, 0.1], [0.5], split_name="test")


def test_local_performance_benchmark_reports_feature_and_similarity_costs(capsys):
    matcher = DuplicateMatcher()
    state = matcher.feature_state
    assert state is not None
    report_text = normalize_text("Water is rising near Rajendra Nagar road")
    measurements = []
    for count in (1, 10, 100, 1000):
        texts = [normalize_text(f"Water report number {index} near Rajendra Nagar") for index in range(count)]
        started = perf_counter()
        new_char = state.char_space.transform(report_text)
        new_word = state.word_space.transform(report_text)
        candidate_vectors = [
            (state.char_space.transform(text), state.word_space.transform(text)) for text in texts
        ]
        feature_seconds = perf_counter() - started
        started = perf_counter()
        for char_vector, word_vector in candidate_vectors:
            _sparse_cosine(new_char, char_vector)
            _sparse_cosine(new_word, word_vector)
        similarity_seconds = perf_counter() - started
        measurements.append((count, feature_seconds, similarity_seconds))
    print("DUPLICATE_FEATURE_BENCHMARK " + " ".join(f"n={n}:feature={feature:.6f}:similarity={similarity:.6f}" for n, feature, similarity in measurements))
    assert all(feature >= 0.0 and similarity >= 0.0 for _, feature, similarity in measurements)
    assert "DUPLICATE_FEATURE_BENCHMARK" in capsys.readouterr().out
