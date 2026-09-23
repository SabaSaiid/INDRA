"""
Phase 1 T1 — the hazard taxonomy: one table, 16 event types.

Unit level: services/hazards.py is pure data plus lookups.
"""

import pytest

from app.models.enums import EventType
from app.services import hazards


def test_every_event_type_has_exactly_one_row():
    missing = {t.value for t in EventType} - set(hazards.HAZARDS)
    extra = set(hazards.HAZARDS) - {t.value for t in EventType}
    assert not missing, f"EventType members with no taxonomy row: {sorted(missing)}"
    assert not extra, f"taxonomy rows with no EventType member: {sorted(extra)}"
    assert len(EventType) == 16


def test_every_family_in_use_has_a_radius_and_a_window():
    used = {h.family for h in hazards.HAZARDS.values() if h.family is not None}
    assert used == set(hazards.FAMILIES)
    for family in hazards.FAMILIES.values():
        assert family.eps_km > 0
        assert family.window_hours > 0


@pytest.mark.parametrize(
    "family, eps_km, window_hours",
    [("water", 5.0, 6), ("convective", 10.0, 3), ("thermal", 25.0, 24), ("visibility", 15.0, 12)],
)
def test_family_radius_and_window_are_the_planned_values(family, eps_km, window_hours):
    assert hazards.FAMILIES[family].eps_km == eps_km
    assert hazards.FAMILIES[family].window_hours == window_hours


@pytest.mark.parametrize(
    "event_type, family",
    [
        ("HEATWAVE", "thermal"),
        ("URBAN_FLOOD", "water"),
        (EventType.FOG, "visibility"),
        ("DUST_STORM", "convective"),
        ("UNCLASSIFIED", None),
        ("TORNADO", None),
        (None, None),
    ],
)
def test_family_of(event_type, family):
    assert hazards.family_of(event_type) == family


def test_the_impact_outranks_its_cause():
    assert hazards.by_precedence(["RAINFALL", "URBAN_FLOOD"]) == ["URBAN_FLOOD", "RAINFALL"]
    assert hazards.by_precedence([EventType.RAINFALL, EventType.LANDSLIDE]) == ["LANDSLIDE", "RAINFALL"]


def test_an_unknown_type_sorts_last_rather_than_raising():
    assert hazards.by_precedence(["TORNADO", "FOG"]) == ["FOG", "TORNADO"]


def test_types_in_a_family_come_in_precedence_order():
    water = hazards.types_in_family("water")
    assert water[-1] == "RAINFALL"
    assert set(water) == {
        "URBAN_FLOOD", "CLOUDBURST", "CYCLONE_INUNDATION", "RIVER_BREACH", "LANDSLIDE", "RAINFALL",
    }
    assert hazards.types_in_family("nonsense") == []


def test_labels_are_present_and_unique():
    labels = [h.label for h in hazards.HAZARDS.values()]
    assert all(label.strip() for label in labels)
    assert len(labels) == len(set(labels))


@pytest.mark.parametrize(
    "event_type, label",
    [
        # The strings the dashboard's icon table and chart colours key on
        # (GlobeEventMap.tsx eventTypeEmojis). Renaming one silently swaps its
        # map icon for the fallback, so they are pinned.
        ("URBAN_FLOOD", "Flood"),
        ("THUNDERSTORM", "Thunderstorm"),
        ("STRONG_WIND", "Strong Winds"),
        ("FOG", "Fog"),
        ("RAINFALL", "Heavy Rainfall"),
    ],
)
def test_labels_the_dashboard_keys_on_are_kept(event_type, label):
    assert hazards.label_of(event_type) == label


def test_an_unknown_type_is_labelled_as_itself():
    assert hazards.label_of("TORNADO") == "TORNADO"


def test_the_four_original_types_keep_their_thumbnails():
    assert hazards.IMAGE_GRADIENTS["URBAN_FLOOD"] == "linear-gradient(135deg, #2563EB, #1E3A8A)"
    assert hazards.IMAGE_GRADIENTS["CLOUDBURST"] == "linear-gradient(135deg, #3B82F6, #6366F1)"
    assert hazards.IMAGE_GRADIENTS["CYCLONE_INUNDATION"] == "linear-gradient(135deg, #EF4444, #C2410C)"
    assert hazards.IMAGE_GRADIENTS["RIVER_BREACH"] == "linear-gradient(135deg, #F59E0B, #92400E)"


def test_unclassified_clusters_with_nothing_and_looks_unknown():
    h = hazards.HAZARDS["UNCLASSIFIED"]
    assert h.family is None
    assert h.gradient == hazards.DEFAULT_GRADIENT
    assert hazards.gradient_of("TORNADO") == hazards.DEFAULT_GRADIENT
