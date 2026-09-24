"""
Phase 2 T6 — where a post or headline says it is.

The first eight cases are T6's test table, row for row. The rest pin down what
the code added on the way: hashtag splitting, the water-body filter, the
stoplist of district names that are ordinary words, state abbreviations and
Hindi names. The rule under all of them: **never guess**. A post placed in the
wrong district corroborates a flood that is not there.
"""

import pytest

from app.services.geocoding import TEXT_PLACE_SPREAD_KM, hashtag_words, place_from_text


def _place(text, hashtags=None):
    p = place_from_text(text, hashtags)
    return p["district"], p["state"], p["precision"]


# ── T6's table ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, expected",
    [
        ("#IMD orange alert: heavy rain in Ernakulam", ("Ernakulam", "Kerala", "district")),
        ("Waterlogging in Kochi after two hours of rain", ("Ernakulam", "Kerala", "district")),
        ("#MumbaiRains trains stopped", ("Mumbai", "Maharashtra", "district")),
        ("Heavy rain in Kerala today", (None, "Kerala", "state")),
        ("Aurangabad flooded", (None, None, "none")),
        ("Aurangabad, Bihar flooded", ("Aurangabad", "Bihar", "district")),
        ("Rain in Patna and Gaya", (None, "Bihar", "state")),
        ("Weather is nice", (None, None, "none")),
    ],
)
def test_t6_table(text, expected):
    assert _place(text) == expected


def test_district_precision_carries_the_district_centroid():
    p = place_from_text("heavy rain in Ernakulam")
    assert p["lat"] == pytest.approx(10.0, abs=0.5)
    assert p["lng"] == pytest.approx(76.4, abs=0.5)


def test_state_precision_keeps_coordinates_for_filtering():
    p = place_from_text("Heavy rain in Kerala today")
    assert p["lat"] is not None and p["lng"] is not None


def test_none_precision_has_no_coordinates():
    p = place_from_text("Weather is nice")
    assert (p["lat"], p["lng"]) == (None, None)


def test_patna_and_gaya_are_further_apart_than_the_spread_limit():
    # The table's "about 95 km": if the limit ever grows past it, this row's
    # expectation has to be revisited, not silently flipped.
    assert TEXT_PLACE_SPREAD_KM < 90


# ── Ambiguous names ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["Bilaspur flooded", "Hamirpur roads cut off", "Pratapgarh rain"])
def test_an_ambiguous_district_alone_is_not_placed(text):
    assert _place(text)[2] == "none"


def test_an_ambiguous_district_with_its_state_is_placed():
    assert _place("Bilaspur, Chhattisgarh: heavy rain") == ("Bilaspur", "Chhattisgarh", "district")


def test_places_in_two_states_are_not_placed():
    assert _place("Rain in Patna and Mumbai") == (None, None, "none")


# ── Hashtags ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "tag, words",
    [
        ("#MumbaiRains", "Mumbai"),
        ("#keralarain", "kerala"),
        ("#NewDelhiWeather", "New Delhi"),
        ("#DelhiRainAlert", "Delhi"),
        ("#KeralaWeather", "Kerala"),
        ("#Lucknow", "Lucknow"),
        ("#rain", "rain"),
        ("", ""),
    ],
)
def test_hashtag_words(tag, words):
    assert hashtag_words(tag) == words


def test_hashtags_passed_separately_are_read():
    assert _place("trains stopped", ["MumbaiRains"]) == ("Mumbai", "Maharashtra", "district")


def test_a_glued_lowercase_state_hashtag_is_read():
    assert _place("#keralarain again today") == (None, "Kerala", "state")


# ── Things that look like places and are not ───────────────────────────────────

def test_the_bay_of_bengal_is_not_west_bengal():
    assert _place("Low pressure area over the Bay of Bengal") == (None, None, "none")


@pytest.mark.parametrize(
    "text",
    [
        "What a punch this storm packs",   # Punch (Poonch)
        "Anand ji says the rain is heavy",  # Anand
        "Sagar of rain everywhere",         # Sagar
    ],
)
def test_district_names_that_are_ordinary_words_are_ignored(text):
    assert _place(text)[2] == "none"


def test_a_stoplisted_district_still_resolves_through_its_alias():
    assert _place("Landslide in Poonch")[2] == "district"


# ── State abbreviations ────────────────────────────────────────────────────────

def test_capital_up_is_uttar_pradesh():
    assert _place("Heavy rain in UP today") == (None, "Uttar Pradesh", "state")


def test_lowercase_up_is_an_english_word():
    assert _place("keep your umbrellas up") == (None, None, "none")


def test_j_and_k_is_read():
    assert _place("Snowfall in J&K") == (None, "Jammu and Kashmir", "state")


# ── Hindi ──────────────────────────────────────────────────────────────────────

def test_hindi_state_name():
    assert _place("बिहार में भारी बारिश") == (None, "Bihar", "state")


def test_hindi_city_alias():
    assert _place("मुंबई में भारी बारिश")[:2] == ("Mumbai", "Maharashtra")


def test_hindi_abbreviation_for_up():
    assert _place("यूपी में मानसून की री-एंट्री") == (None, "Uttar Pradesh", "state")


# ── Contract ───────────────────────────────────────────────────────────────────

def test_empty_and_none_text():
    assert _place("") == (None, None, "none")
    assert _place(None) == (None, None, "none")


def test_same_text_same_place():
    text = "Waterlogging in Kochi after two hours of rain"
    assert place_from_text(text) == place_from_text(text)


def test_matched_names_are_recorded():
    assert "Kochi" in place_from_text("Waterlogging in Kochi")["matched"]
