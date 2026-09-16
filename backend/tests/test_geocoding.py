"""
Day 2 T1 — coordinates outside India are rejected, not snapped.

Snapping used to send every out-of-bounds report to (22, 82), where two of them
were enough (DBSCAN_MIN_SAMPLES=2) to manufacture a verified event in the middle
of the country. These pin the India bounding box down city by city.
"""

import pytest

from app.services.geocoding import (
    OutOfIndiaBoundsError,
    sanitize_coordinates,
)


@pytest.mark.parametrize(
    "name, lat, lng",
    [
        ("Patna", 25.5941, 85.1376),
        ("Kanyakumari", 8.09, 77.55),
        ("Ladakh", 35.5, 77.0),
        ("Delhi", 28.6139, 77.2090),
    ],
)
def test_in_bounds_coordinates_pass_through_unchanged(name, lat, lng):
    out_lat, out_lng, _, _ = sanitize_coordinates(lat, lng)
    assert (out_lat, out_lng) == (lat, lng)


@pytest.mark.parametrize(
    "name, lat, lng",
    [
        ("Paris", 48.85, 2.35),
        ("Sydney", -33.87, 151.21),
        ("Null Island", 0.0, 0.0),
        ("just south of the box", 6.49, 80.0),
        ("just east of the box", 25.0, 97.51),
    ],
)
def test_out_of_bounds_coordinates_are_rejected(name, lat, lng):
    with pytest.raises(OutOfIndiaBoundsError):
        sanitize_coordinates(lat, lng)


def test_rejection_is_not_bypassed_by_a_city_name_in_the_text():
    """Paris coordinates with "Patna" in the text used to snap to Patna."""
    with pytest.raises(OutOfIndiaBoundsError):
        sanitize_coordinates(48.85, 2.35, text_hint="Flooding in Patna")


@pytest.mark.parametrize("lat, lng", [(6.5, 68.0), (37.6, 97.5)])
def test_box_corners_are_inclusive(lat, lng):
    assert sanitize_coordinates(lat, lng)[:2] == (lat, lng)


def test_swapped_pair_is_corrected_not_rejected():
    out_lat, out_lng, _, _ = sanitize_coordinates(85.1376, 25.5941)
    assert (out_lat, out_lng) == (25.5941, 85.1376)


def test_snapping_is_still_available_behind_the_explicit_flag():
    assert sanitize_coordinates(48.85, 2.35, snap_out_of_bounds=True)[:2] == (22.0, 82.0)


def test_missing_coordinates_still_resolve_from_text():
    lat, lng, city, _ = sanitize_coordinates(None, None, text_hint="water in Patna")
    assert city == "Patna"
