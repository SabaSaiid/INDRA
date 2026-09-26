"""
Phase 3 T7 — hazard-specific severity.

`severity = max(content_axis, count_axis, impact_floor)`: the content axis is
the hazard's own measure on IMD's or Beaufort's published cuts
(`app/services/severity_rules.py`), and impact words set a floor. T7's table
is first, row for row; then every cut and the value just past it, so a cut
that drifts by 0.1 fails a named case. All single-report clusters, so the
count axis (5 reports → MODERATE) never decides.

The existing `test_severity_rules.py` keeps the flood-only depth and count
rules from before Phase 3; they are unchanged.
"""

import pytest

from app.models.enums import Severity
from app.services.pipeline import _derive_severity


def _grade(event_type, text):
    return _derive_severity([text], 1, event_type=event_type)


# ── T7's table ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "event_type, text, severity",
    [
        ("HEATWAVE", "Temperature 44.9 degree in Delhi", "MODERATE"),
        ("HEATWAVE", "Temperature 45 degree in Delhi", "HIGH"),
        ("HEATWAVE", "Temperature 47 degree in Delhi", "CRITICAL"),
        ("FOG", "dense fog, visibility 500 m", "ADVISORY"),
        ("FOG", "dense fog, visibility 199 m", "HIGH"),
        ("FOG", "dense fog, visibility 49 m", "CRITICAL"),
        ("THUNDERSTORM", "thunderstorm, winds of 61 km/h", "MODERATE"),
        ("THUNDERSTORM", "thunderstorm, winds of 62 km/h", "HIGH"),
        ("THUNDERSTORM", "thunderstorm, winds of 89 km/h", "CRITICAL"),
        ("URBAN_FLOOD", "Knee deep water outside my house", "MODERATE"),
        ("RAINFALL", "120 mm rain in Chennai", "HIGH"),
        ("LIGHTNING", "2 died after lightning strike", "CRITICAL"),
    ],
)
def test_t7_table(event_type, text, severity):
    assert _grade(event_type, text)["severity"].value == severity


def test_a_fog_pile_up_is_at_least_high():
    graded = _grade("FOG", "dense fog, 3-car pile-up on the expressway")
    assert graded["severity"] in (Severity.HIGH, Severity.CRITICAL)
    assert graded["basis"]["impact_floor"] == {"severity": "HIGH", "phrase": "pile-up"}


def test_a_pile_up_is_a_floor_only_in_fog():
    assert _grade("URBAN_FLOOD", "3-car pile-up on the expressway")["basis"]["impact_floor"] is None


# ── Every cut, and just past it ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "event_type, text, severity",
    [
        # water, rain in 24 h (IMD): heavy 64.5, very heavy 115.6, extremely heavy 204.5
        ("RAINFALL", "64.4 mm rain", "ADVISORY"),
        ("RAINFALL", "64.5 mm rain", "MODERATE"),
        ("RAINFALL", "115.6 mm rain", "HIGH"),
        ("RAINFALL", "204.4 mm rain", "HIGH"),
        ("RAINFALL", "204.5 mm rain", "CRITICAL"),
        # heat (IMD, plains): 40, 45, 47
        ("HEATWAVE", "Temperature 39.9 degree", "ADVISORY"),
        ("HEATWAVE", "Temperature 40 degree", "MODERATE"),
        ("HEATWAVE", "Temperature 46.9 degree", "HIGH"),
        # cold (IMD, plains), at or below: 10, 4, 2
        ("COLD_WAVE", "cold wave, 10.1 degree", "ADVISORY"),
        ("COLD_WAVE", "cold wave, 10 degree", "MODERATE"),
        ("COLD_WAVE", "cold wave, 4 degree", "HIGH"),
        ("COLD_WAVE", "cold wave, 2 degree", "CRITICAL"),
        ("COLD_WAVE", "biting cold today", "ADVISORY"),
        # fog classes (IMD): 1000 is not fog, 999 shallow, 200 moderate, 50 dense
        ("FOG", "dense fog, visibility 1000 m", "ADVISORY"),
        ("FOG", "dense fog, visibility 999 m", "ADVISORY"),
        ("FOG", "dense fog, visibility 499 m", "MODERATE"),
        ("FOG", "dense fog, visibility 200 m", "MODERATE"),
        ("FOG", "dense fog, visibility 50 m", "HIGH"),
        # wind (Beaufort): 39 force 6, 62 gale, 89 storm
        ("STRONG_WIND", "winds of 38 km/h", "ADVISORY"),
        ("STRONG_WIND", "winds of 39 km/h", "MODERATE"),
        ("STRONG_WIND", "winds of 88 km/h", "HIGH"),
        # depth, unchanged: 20, 60, 120 cm
        ("URBAN_FLOOD", "Waist deep water in the lane", "HIGH"),
    ],
)
def test_every_cut(event_type, text, severity):
    assert _grade(event_type, text)["severity"].value == severity


# ── The receipt names what decided it ──────────────────────────────────────────

@pytest.mark.parametrize(
    "event_type, text, axis, value, phrase",
    [
        ("HEATWAVE", "46 degree hai, loo chal rahi hai", "thermal_heat", 46.0, "46 degree"),
        ("COLD_WAVE", "Kadaake ki thand, 3 degree in Amritsar", "thermal_cold", 3.0, "3 degree"),
        ("FOG", "घना कोहरा, visibility 50 m on NH-44", "visibility", 50.0, "visibility 50 m"),
        ("THUNDERSTORM", "thunderstorm, winds of 62 km/h", "convective_wind", 62.0, "62 km/h"),
        ("URBAN_FLOOD", "Knee deep water outside my house", "water_depth", 50, "body:knee"),
        ("RAINFALL", "120 mm rain in Chennai", "water_rain", 120.0, "120 mm"),
        # A rain reading with no depth is what the receipt shows, even at ADVISORY.
        ("RAINFALL", "64.4 mm rain", "water_rain", 64.4, "64.4 mm"),
        ("UNCLASSIFIED", "something happened here", "none", None, None),
    ],
)
def test_the_basis_names_the_axis_and_the_phrase(event_type, text, axis, value, phrase):
    basis = _grade(event_type, text)["basis"]
    assert (basis["axis"], basis["value"], basis["phrase"]) == (axis, value, phrase)
    assert basis["event_type"] == event_type


def test_the_worst_reading_in_the_cluster_decides():
    graded = _derive_severity(
        ["44 degree in Churu", "47.5 degree in Phalodi", "41 degree"], 3, event_type="HEATWAVE"
    )
    assert graded["severity"] is Severity.CRITICAL
    assert graded["basis"]["value"] == 47.5


def test_the_coldest_reading_decides_a_cold_wave():
    graded = _derive_severity(["cold wave, 9 degree", "cold wave, 1.5 degree"], 2, event_type="COLD_WAVE")
    assert graded["severity"] is Severity.CRITICAL
    assert graded["basis"]["value"] == 1.5


def test_an_implausible_reading_decides_nothing():
    graded = _grade("HEATWAVE", "temperature 75 degree, heatwave")
    assert graded["basis"]["value"] is None


# ── Impact words ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "event_type, text, floor, phrase",
    [
        ("HEATWAVE", "heatstroke cases, 3 hospitalised", "HIGH", "heatstroke"),
        ("URBAN_FLOOD", "families stranded, boats sent", "HIGH", "stranded"),
        ("STRONG_WIND", "roof blown off, trees uprooted", "CRITICAL", "roof blown off"),
        ("LIGHTNING", "बिजली गिरने से मौत", "CRITICAL", "मौत"),
    ],
)
def test_impact_words_set_a_floor(event_type, text, floor, phrase):
    graded = _grade(event_type, text)
    assert graded["severity"].value == floor
    assert graded["basis"]["impact_floor"] == {"severity": floor, "phrase": phrase}
    assert graded["provenance"] == "rule_based_impact_words"


@pytest.mark.parametrize(
    "text",
    [
        "no deaths reported, water receding",
        "heavy rain, no one stranded",
        "koi maut nahi hui, paani utar raha",
    ],
)
def test_a_denied_impact_sets_no_floor(text):
    graded = _grade("URBAN_FLOOD", text)
    assert graded["basis"]["impact_floor"] is None
    assert graded["severity"] is Severity.ADVISORY


def test_the_patna_cluster_is_still_moderate():
    patna = [
        "Water entering ground floor shops near Kankarbagh main road",
        "Kankarbagh underpass completely submerged, cars stuck",
        "Knee deep water outside my house, drain overflowing",
        "Flooding on the road to Patna junction, buses diverted",
        "Sewage water mixed with rain water on the street here",
    ]
    graded = _derive_severity(patna, 5, event_type="URBAN_FLOOD")
    assert graded["severity"] is Severity.MODERATE
    assert graded["basis"]["axis"] == "water_depth"
