from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID

from app.ml.components.duplicate_matching import DuplicateMatcher, normalize_text
from app.ml.config import DuplicateMatchingConfig
from app.ml.contracts import CandidateReport, PredictionStatus, ReportInput
from app.ml.evaluation.evaluate import evaluate_duplicate_scores


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
LATITUDE = 25.5941
LONGITUDE = 85.1376


def candidate(
    number: int,
    text: str,
    *,
    minutes: float = 0,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
) -> CandidateReport:
    return CandidateReport(
        report_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        text=text,
        occurred_at=NOW + timedelta(minutes=minutes),
        latitude=latitude,
        longitude=longitude,
        source_type="CITIZEN_APP",
    )


def report(text: str, *candidates: CandidateReport) -> ReportInput:
    return ReportInput(
        report_id=UUID("10000000-0000-0000-0000-000000000001"),
        text=text,
        occurred_at=NOW,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        source_type="CITIZEN_APP",
        candidate_reports=list(candidates),
    )


def test_empty_text_is_explicit_and_not_a_negative_prediction():
    result = DuplicateMatcher().predict(report("", candidate(1, "water rising")))
    assert result.status is PredictionStatus.INSUFFICIENT_DATA
    assert result.is_duplicate is None
    assert result.reason_codes == ["EMPTY_TEXT"]


def test_no_candidates_is_not_applicable():
    result = DuplicateMatcher().predict(report("water rising"))
    assert result.status is PredictionStatus.NOT_APPLICABLE
    assert result.is_duplicate is None
    assert result.reason_codes == ["NO_CANDIDATES"]


def test_identical_english_text_is_duplicate_with_complete_evidence():
    text = "Water is rising near Rajendra Nagar road"
    result = DuplicateMatcher().predict(report(text, candidate(1, text)))
    assert result.status is PredictionStatus.AVAILABLE
    assert result.is_duplicate is True
    assert result.candidate_id == candidate(1, text).report_id
    assert result.character_similarity == 1.0
    assert result.word_similarity == 1.0
    assert result.edit_similarity == 1.0
    assert result.geographic_similarity == 1.0
    assert result.temporal_similarity == 1.0
    assert result.similarity == 1.0
    assert result.text_threshold is not None
    assert result.threshold is not None
    assert result.threshold_status == "PROVISIONAL / UNVALIDATED"
    assert len(result.evidence) >= 10


def test_minor_wording_variation_is_scored_as_a_likely_duplicate():
    result = DuplicateMatcher().predict(
        report(
            "Water is rising near Rajendra Nagar road",
            candidate(1, "Water rising near Rajendra Nagar road"),
        )
    )
    assert result.is_duplicate is True
    assert result.text_similarity is not None
    assert result.text_similarity >= result.text_threshold


def test_hindi_unicode_is_preserved_and_matches():
    text = "सड़क पर पानी भर गया है"
    result = DuplicateMatcher().predict(report(text, candidate(1, text)))
    assert "पानी" in normalize_text(text)
    assert result.is_duplicate is True


def test_hinglish_is_preserved_and_minor_variation_matches():
    result = DuplicateMatcher().predict(
        report(
            "sadak par paani bhar gaya hai",
            candidate(1, "sadak par paani bhar gaya"),
        )
    )
    assert result.is_duplicate is True


def test_unrelated_text_is_not_duplicate_even_when_nearby():
    result = DuplicateMatcher().predict(
        report(
            "Water is rising near Rajendra Nagar road",
            candidate(1, "Power outage reported near the railway station"),
        )
    )
    assert result.status is PredictionStatus.AVAILABLE
    assert result.is_duplicate is False
    assert "BELOW_PROVISIONAL_THRESHOLD" in result.reason_codes


def test_same_text_beyond_geographic_gate_is_not_compared():
    text = "Water is rising near Rajendra Nagar road"
    result = DuplicateMatcher().predict(
        report(text, candidate(1, text, latitude=28.6139, longitude=77.2090))
    )
    assert result.is_duplicate is False
    assert result.comparisons_performed == 0
    assert result.reason_codes == ["NO_CANDIDATE_WITHIN_GATES"]


def test_same_text_beyond_temporal_gate_is_not_compared():
    text = "Water is rising near Rajendra Nagar road"
    result = DuplicateMatcher().predict(
        report(text, candidate(1, text, minutes=16))
    )
    assert result.is_duplicate is False
    assert result.comparisons_performed == 0
    assert result.reason_codes == ["NO_CANDIDATE_WITHIN_GATES"]


def test_multiple_candidates_return_the_best_candidate():
    text = "Water is rising near Rajendra Nagar road"
    best = candidate(2, text)
    result = DuplicateMatcher().predict(
        report(text, candidate(1, "Power outage near station"), best)
    )
    assert result.is_duplicate is True
    assert result.candidate_id == best.report_id
    assert result.comparisons_performed == 2


def test_threshold_is_configurable_and_provisional():
    config = DuplicateMatchingConfig(
        text_similarity_threshold=1.0,
        combined_threshold=1.0,
    )
    result = DuplicateMatcher(config).predict(
        report(
            "Water is rising near Rajendra Nagar road",
            candidate(1, "Water rising near Rajendra Nagar road"),
        )
    )
    assert result.is_duplicate is False
    assert "TEXT_SIMILARITY_BELOW_THRESHOLD" in result.reason_codes


def test_repeated_calls_are_deterministic():
    matcher = DuplicateMatcher()
    input_report = report(
        "Water is rising near Rajendra Nagar road",
        candidate(1, "Water rising near Rajendra Nagar road"),
    )
    assert matcher.predict(input_report) == matcher.predict(input_report)


def test_benchmark_reports_only_local_fixture_measurements(capsys):
    candidates = [
        candidate(index, f"Water report number {index} near Rajendra Nagar")
        for index in range(1, 51)
    ]
    input_report = report("Water report number 1 near Rajendra Nagar", *candidates)
    started = perf_counter()
    result = DuplicateMatcher().predict(input_report)
    elapsed = perf_counter() - started
    print(
        "DUPLICATE_MATCH_BENCHMARK "
        f"candidate_count={result.candidate_count} "
        f"comparisons_performed={result.comparisons_performed} "
        f"runtime_seconds={elapsed:.6f}"
    )
    assert result.candidate_count == 50
    assert result.comparisons_performed == 50
    assert elapsed >= 0.0
    assert "DUPLICATE_MATCH_BENCHMARK" in capsys.readouterr().out


def test_evaluation_reports_data_unavailable_without_labels():
    result = evaluate_duplicate_scores([], [], [0.5, 0.7])
    assert result.evaluation_status == "DATA_UNAVAILABLE"
    assert result.threshold_sweep == []
