"""
BUG-012 — DBSCAN's radius is a ground distance at every latitude.

The clustering eps used to be DBSCAN_EPS_KM converted at a flat 0.009 deg/km.
That is right north-south and about 10% short east-west at Patna, because a
degree of longitude shrinks with cos(latitude): the 5 km neighbourhood was an
ellipse 5.0 km tall and 4.5 km wide. These tests pin the replacement to a
circle, on both sides of the boundary, at the latitudes India spans.

No database: `dbscan_labels` is the pure function the service calls.
"""

import math

import pytest

from app.services.geo_clustering import EARTH_RADIUS_KM, dbscan_labels

PATNA = (25.5941, 85.1376)
EPS_KM = 5.0


def east_of(lat: float, lng: float, km: float) -> tuple:
    """The point `km` due east along the parallel, by the haversine metric."""
    dlng = 2 * math.asin(math.sin(km / (2 * EARTH_RADIUS_KM)) / math.cos(math.radians(lat)))
    return (lat, lng + math.degrees(dlng))


def north_of(lat: float, lng: float, km: float) -> tuple:
    """The point `km` due north along the meridian."""
    return (lat + math.degrees(km / EARTH_RADIUS_KM), lng)


def labels_for_pair(a: tuple, b: tuple) -> list:
    return dbscan_labels([a, b], EPS_KM, min_samples=2)


@pytest.mark.parametrize("km, clustered", [(4.8, True), (4.99, True), (5.01, False), (5.2, False)])
def test_east_west_radius_is_the_full_eps_at_patna(km, clustered):
    labels = labels_for_pair(PATNA, east_of(*PATNA, km))
    assert (labels == [0, 0]) is clustered
    if not clustered:
        assert labels == [-1, -1]


@pytest.mark.parametrize("km, clustered", [(4.8, True), (4.99, True), (5.01, False), (5.2, False)])
def test_north_south_radius_is_the_full_eps_at_patna(km, clustered):
    labels = labels_for_pair(PATNA, north_of(*PATNA, km))
    assert (labels == [0, 0]) is clustered


def test_the_old_degree_eps_would_have_split_this_pair():
    """
    The defect, stated as arithmetic: 4.8 km east of Kankarbagh is more than
    0.045 degrees of longitude away, so eps_km * 0.009 excluded it.
    """
    _, lng = east_of(*PATNA, 4.8)
    assert lng - PATNA[1] > EPS_KM * 0.009
    assert labels_for_pair(PATNA, east_of(*PATNA, 4.8)) == [0, 0]


@pytest.mark.parametrize(
    "place, lat, lng",
    [
        ("Thiruvananthapuram", 8.5241, 76.9366),
        ("Patna", 25.5941, 85.1376),
        ("Srinagar", 34.0837, 74.7973),
    ],
)
def test_the_neighbourhood_is_the_same_size_at_every_latitude(place, lat, lng):
    assert labels_for_pair((lat, lng), east_of(lat, lng, 4.9)) == [0, 0], place
    assert labels_for_pair((lat, lng), east_of(lat, lng, 5.1)) == [-1, -1], place
    assert labels_for_pair((lat, lng), north_of(lat, lng, 4.9)) == [0, 0], place
    assert labels_for_pair((lat, lng), north_of(lat, lng, 5.1)) == [-1, -1], place


def test_border_points_join_a_cluster_at_higher_min_samples():
    """
    Same core/border rule as ST_ClusterDBSCAN. Three points 4 km apart in a
    line: the middle one has three points within 5 km (itself included), so it
    is a core point, and the two ends — 8 km from each other — are its border
    points. All three form one cluster.
    """
    a = PATNA
    b = east_of(*a, 4.0)
    c = east_of(*b, 4.0)
    assert dbscan_labels([a, b, c], EPS_KM, min_samples=3) == [0, 0, 0]
    # Two points alone cannot reach min_samples=3.
    assert dbscan_labels([a, b], EPS_KM, min_samples=3) == [-1, -1]


def test_labels_follow_input_order_and_are_deterministic():
    points = [PATNA, east_of(*PATNA, 1.0), (24.79, 85.00), north_of(*PATNA, 1.0)]
    first = dbscan_labels(points, EPS_KM, min_samples=2)
    assert first == [0, 0, -1, 0]
    assert dbscan_labels(points, EPS_KM, min_samples=2) == first


def test_no_points_is_no_clusters():
    assert dbscan_labels([], EPS_KM, min_samples=2) == []
