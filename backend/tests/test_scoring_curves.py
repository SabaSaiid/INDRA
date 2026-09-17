"""
Day 2 T4 — the Report Density and Spatial Coherence curves.

The exact numbers are in the pipeline docstrings with their reasoning; these
tests make sure the curves and the documentation cannot drift apart.
"""

import pytest

from app.core.config import get_settings
from app.services.pipeline import _coherence_score, _density_score


# ── report_density ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "size, lo, hi",
    [
        (1, 0.0, 0.2),
        (3, 0.25, 0.45),
        (10, 0.75, 0.85),
        (25, 1.0, 1.0),
        (100, 1.0, 1.0),
    ],
)
def test_density_table(size, lo, hi):
    assert lo <= _density_score(size) <= hi


def test_density_of_empty_cluster_is_zero():
    assert _density_score(0) == 0.0


def test_density_is_strictly_increasing_up_to_saturation():
    scores = [_density_score(n) for n in range(0, 26)]
    assert all(a < b for a, b in zip(scores, scores[1:]))


def test_ten_reports_score_strictly_higher_than_three():
    assert _density_score(10) > _density_score(3)


# ── spatial_coherence (DBSCAN_EPS_KM = 5.0) ────────────────────────────────────

@pytest.fixture(autouse=True)
def _eps_is_five_km(monkeypatch):
    monkeypatch.setattr(get_settings(), "DBSCAN_EPS_KM", 5.0)


@pytest.mark.parametrize(
    "km, lo, hi",
    [
        (0.0, 1.0, 1.0),
        (1.0, 0.85, 1.0),
        (5.0, 0.4, 0.6),
        (10.0, 0.0, 0.0),
        (25.0, 0.0, 0.0),
    ],
)
def test_coherence_table(km, lo, hi):
    assert lo <= _coherence_score(km) <= hi


def test_one_km_cluster_scores_strictly_higher_than_four_km():
    assert _coherence_score(1.0) > _coherence_score(4.0)


def test_coherence_is_strictly_decreasing_inside_the_search_diameter():
    scores = [_coherence_score(k / 2) for k in range(0, 21)]  # 0 .. 10 km
    assert all(a > b for a, b in zip(scores, scores[1:]))
