"""Day 2 T8 — per-report credibility replaces the hardcoded 0.5."""

import pytest

from app.models.enums import SourceType
from app.services.credibility import compute_credibility

SPECIFIC_60 = "Knee-deep water on Boring Road near the Patna Women's College"


def test_fixture_text_is_about_sixty_characters():
    assert 55 <= len(SPECIFIC_60) <= 65


def test_specific_citizen_report():
    assert 0.5 <= compute_credibility("CITIZEN_APP", SPECIFIC_60) <= 0.7


def test_one_word_citizen_report():
    assert compute_credibility("CITIZEN_APP", "flood") < 0.4


def test_official_dispatch():
    assert compute_credibility("OFFICIAL_DISPATCH", "Team deployed") >= 0.9


def test_visibly_different_quality_gets_visibly_different_scores():
    assert compute_credibility("CITIZEN_APP", SPECIFIC_60) - compute_credibility(
        "CITIZEN_APP", "flood"
    ) >= 0.2


@pytest.mark.parametrize("source", [s.value for s in SourceType] + ["NOT_A_SOURCE"])
@pytest.mark.parametrize("body", ["", "x", "flood", SPECIFIC_60, "y" * 5000, None])
def test_always_within_check_constraint_range(source, body):
    assert 0.0 <= compute_credibility(source, body) <= 1.0


def test_is_deterministic():
    assert compute_credibility("CITIZEN_APP", SPECIFIC_60) == compute_credibility(
        "CITIZEN_APP", SPECIFIC_60
    )
