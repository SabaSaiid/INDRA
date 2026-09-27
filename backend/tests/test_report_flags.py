"""
Phase 3 T8 — the misleading-text flags, and effective independent reporters.

Part A: each published flag, its rule and its credibility multiplier
(`app/services/report_flags.py`), through ingest's own `derive_text_fields`,
so the credibility is exactly what a stored report gets.

Part B: `n_eff`, the density factor's new input
(`app/services/corroboration.py`), with T8's and T9's tables row for row.
The `coordinated` flag needs other reports, so the pipeline sets it; it is
tested with the pipeline in `test_hazard_clustering.py`.
"""

import uuid

import pytest

from app.services.corroboration import CITIZEN_BASELINE, effective_reporters
from app.services.ingest import derive_text_fields
from app.services.report_flags import FLAGS, adjust_credibility, credibility_multiplier


def _derive(text, source_type="CITIZEN_APP"):
    return derive_text_fields(source_type, text, uuid.uuid4())


# ── Part A: the flags ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, flags",
    [
        ("SELLING UMBRELLAS!!! CALL 9812345678", ["promotional", "shouting"]),
        ("Buy raincoats at a discount, whatsapp me", ["promotional"]),
        ("see https://a.com and https://b.com flood", ["promotional"]),
        ("IMD: heavy rain likely in Patna tomorrow", ["not_an_observation"]),
        ("Throwback to the 2019 Patna floods", ["past_event"]),
        ("temperature 75 degree in Delhi", ["implausible_value"]),
        ("Never seen before, whole city underwater!", ["exaggeration"]),
        ("Forwarded as received: flood in Patna, please share", ["forward_marker"]),
        ("Heavy rain in Patna, roads flooded", []),
    ],
)
def test_each_flag(text, flags):
    assert _derive(text)["flags"] == flags


def test_a_rescue_call_with_a_phone_number_is_not_promotional():
    """A person in trouble gives their number; that is not an advert."""
    assert _derive("Trapped on the roof with kids, call 9812345678, water rising")["flags"] == []


def test_sales_words_still_flag_a_report_with_a_rescue_word():
    assert "promotional" in _derive("Rescue boats on rent, call now, best price")["flags"]


def test_shouting_needs_twenty_letters():
    assert _derive("FLOOD HERE")["flags"] == []  # 9 letters
    assert "shouting" in _derive("WATER EVERYWHERE IN THE COLONY NOW")["flags"]


def test_the_plans_worked_example():
    """0.60 × 0.80 × 0.3 × 0.9: a 36-character report's starting 0.48, promotional, shouting."""
    derived = _derive("SELLING UMBRELLAS!!! CALL 9812345678")
    assert derived["credibility"] == pytest.approx(0.48 * 0.3 * 0.9, abs=1e-4)  # 0.1296
    assert derived["credibility"] / CITIZEN_BASELINE == pytest.approx(0.216, abs=1e-3)


def test_multipliers_compound_with_a_floor():
    assert credibility_multiplier(["promotional", "past_event"]) == pytest.approx(0.12)
    assert adjust_credibility(0.6, ["promotional", "past_event", "implausible_value"]) == 0.05
    assert adjust_credibility(0.5911111, []) == 0.5911


def test_a_forecast_keeps_its_credibility():
    """not_an_observation excludes a report from density; it does not mark it down."""
    assert FLAGS["not_an_observation"] is None
    assert credibility_multiplier(["not_an_observation"]) == 1.0


def test_flags_come_in_the_published_order():
    flags = _derive("NEVER SEEN BEFORE!!! BUY NOW, forward to all")["flags"]
    assert flags == [f for f in FLAGS if f in flags]


# ── Part B: n_eff ──────────────────────────────────────────────────────────────

def _r(credibility, reporter=None, flags=(), source_type="CITIZEN_APP", publisher=None):
    return {
        "id": uuid.uuid4(),
        "credibility": credibility,
        "reporter_hash": reporter,
        "flags": list(flags),
        "source_type": source_type,
        "publisher": publisher,
    }


CLEAN = [0.595, 0.565, 0.555, 0.57, 0.565]  # the Patna texts' credibility


def test_five_clean_reports_from_five_devices():
    result = effective_reporters([_r(c, f"dev{i}") for i, c in enumerate(CLEAN)])
    assert result["n_eff"] == pytest.approx(4.75, abs=1e-4)  # T8's table: ≈ 4.8
    assert result["basis"]["distinct_reporters"] == 5


def test_five_reports_from_one_device_count_once():
    result = effective_reporters([_r(c, "same-phone") for c in CLEAN])
    assert result["n_eff"] <= 1.0
    assert result["basis"]["distinct_reporters"] == 1
    assert result["basis"]["reports"] == 5


def test_four_clean_and_one_promotional():
    reports = [_r(c, f"dev{i}") for i, c in enumerate(CLEAN[:4])] + [_r(0.1296, "spam")]
    result = effective_reporters(reports)
    # T8's table said ≈ 4.1; with these credibilities it is exactly
    # 0.9917 + 0.9417 + 0.925 + 0.95 + 0.216 = 4.0243.
    assert result["n_eff"] == pytest.approx(4.0243, abs=1e-4)


def test_forecasts_are_excluded():
    reports = [_r(c, f"dev{i}") for i, c in enumerate(CLEAN[:3])]
    reports += [_r(0.5, f"fc{i}", flags=["not_an_observation"]) for i in range(2)]
    result = effective_reporters(reports)
    assert result["n_eff"] == pytest.approx(2.8583, abs=1e-4)  # T8's table: ≈ 3
    assert result["basis"]["excluded"] == 2
    assert result["basis"]["reports"] == 3


def test_reports_with_no_reporter_id_each_count_as_their_own():
    result = effective_reporters([_r(c) for c in CLEAN])
    assert result["n_eff"] == pytest.approx(4.75, abs=1e-4)
    assert result["basis"]["unverified_reporters"] == 5


def test_a_reporter_counts_by_their_best_report():
    result = effective_reporters([_r(0.1296, "p"), _r(0.57, "p")])
    assert result["n_eff"] == pytest.approx(0.95, abs=1e-4)


def test_one_reporter_counts_at_most_once():
    assert effective_reporters([_r(0.9, "official")])["n_eff"] == 1.0


# T9: news counts by publisher.
def test_six_outlets_carrying_one_story_count_by_publisher():
    outlets = ["jagran.com", "amarujala.com", "livehindustan.com", "bhaskar.com", "navbharattimes.com",
               "aajtak.in"]
    reports = [_r(0.5, source_type="NEWS_MEDIA", publisher=p) for p in outlets]
    reports += [_r(0.5, source_type="NEWS_MEDIA", publisher="jagran.com")]  # the same outlet twice
    reports += [_r(0.57, "citizen")]
    result = effective_reporters(reports)
    assert result["basis"]["publishers"] == 6
    assert result["basis"]["distinct_reporters"] == 7
    # 6 publishers × 0.5/0.6 + the citizen's 0.95; each publisher at most 1.
    assert result["n_eff"] == pytest.approx(6 * 0.5 / 0.6 + 0.95, abs=1e-3)
    assert result["n_eff"] <= 7


def test_the_basis_shows_the_arithmetic():
    basis = effective_reporters([_r(0.57, "a"), _r(0.57)])["basis"]
    assert set(basis) == {
        "reports", "distinct_reporters", "n_eff", "excluded", "unverified_reporters", "publishers",
        "baseline", "rule",
    }
    assert basis["baseline"] == 0.6
