"""
Phase 5 T7 — account signals for social sources
(`app/services/account_signals.py`), through the Mastodon poller's mapping
and ingest's credibility.

T7's table row for row: a two-day-old account with one follower counts
× 0.48 of an established one; a bot is at most half a witness; a three-year-old
account with 800 followers is unchanged. Then the boundaries, and "the same
post always gets the same flags" (age is measured when it posted).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.account_signals import FEW_FOLLOWERS, NEW_ACCOUNT_AGE, account_flags
from app.services.corroboration import effective_reporters
from app.services.ingest import derive_text_fields
from app.services.report_flags import adjust_credibility
from app.workers.mastodon_poller import status_to_report

POSTED = datetime(2026, 9, 24, 2, 45, tzinfo=timezone.utc)


def flags_for(created, followers, bot=False, posted=POSTED):
    return account_flags(account_created_at=created, followers_count=followers, bot=bot, posted_at=posted)


# ── T7's table ─────────────────────────────────────────────────────────────────

def test_a_two_day_old_account_with_one_follower():
    flags, basis = flags_for(POSTED - timedelta(days=2), 1)
    assert flags == ["new_account", "few_followers"]
    assert basis == {"new_account": "account 2 days old when it posted", "few_followers": "1 follower"}
    # × 0.6 × 0.8 = × 0.48 of what the same post from an established account counts.
    assert adjust_credibility(0.5, flags) == 0.24
    assert adjust_credibility(0.5, flags) / adjust_credibility(0.5, []) == pytest.approx(0.48)


def test_a_bot_is_at_most_half_a_witness():
    flags, basis = flags_for("2020-01-01T00:00:00Z", 5000, bot=True)
    assert flags == ["bot_account"]
    assert basis["bot_account"] == "the platform marks this account as a bot"
    report = {"id": uuid.uuid4(), "reporter_hash": "news-bot", "source_type": "SOCIAL_MEDIA",
              "credibility": 0.9, "flags": flags}
    assert effective_reporters([report])["n_eff"] == 0.5


def test_an_established_account_is_unchanged():
    flags, basis = flags_for(POSTED - timedelta(days=3 * 365), 800)
    assert flags == [] and basis == {}


# ── Boundaries and unknowns ────────────────────────────────────────────────────

def test_new_account_is_less_than_7_days():
    assert NEW_ACCOUNT_AGE == timedelta(days=7)
    assert flags_for(POSTED - timedelta(days=7), 100)[0] == []
    assert flags_for(POSTED - timedelta(days=6, hours=23), 100)[0] == ["new_account"]


def test_few_followers_is_fewer_than_5():
    assert FEW_FOLLOWERS == 5
    assert flags_for("2020-01-01", 5)[0] == []
    assert flags_for("2020-01-01", 4)[0] == ["few_followers"]
    assert flags_for("2020-01-01", 0)[1]["few_followers"] == "0 followers"


def test_unknown_values_set_nothing():
    assert flags_for(None, None, bot=None) == ([], {})
    assert flags_for("not a date", "many", bot="true") == ([], {})


def test_age_is_measured_when_it_posted_not_now():
    """A post collected a year later still reads "2 days old": the same post, the same flags."""
    created = "2026-09-22T02:45:00Z"
    assert flags_for(created, 50, posted="2026-09-24T02:45:00Z")[0] == ["new_account"]
    assert flags_for(created, 50, posted=datetime(2026, 9, 24, 2, 45))[0] == ["new_account"]


# ── Through the poller and ingest ──────────────────────────────────────────────

def _status(created_at, followers, bot=False):
    return {
        "id": "9", "uri": "https://mastodon.social/users/a/statuses/9",
        "created_at": "2026-09-24T02:45:00.000Z",
        "content": "<p>Heavy rain and waterlogging in Patna since morning</p>",
        "account": {"acct": "a", "created_at": created_at, "followers_count": followers, "bot": bot},
        "tags": [{"name": "imd"}],
    }


def test_the_poller_carries_the_account_flags_to_ingest():
    mapped = status_to_report(_status("2026-09-22T00:00:00.000Z", 1), "mastodon.social", "IMD")
    assert mapped["extra_flags"] == ["new_account", "few_followers"]
    assert mapped["extra_basis"]["new_account"] == "account 2 days old when it posted"
    established = status_to_report(_status("2023-01-01T00:00:00.000Z", 800), "mastodon.social", "IMD")
    assert established["extra_flags"] == [] and established["extra_basis"] == {}


def test_a_boost_is_judged_by_the_original_author():
    status = _status("2023-01-01T00:00:00.000Z", 800)
    status["reblog"] = {**_status("2026-09-23T00:00:00.000Z", 2), "id": "8"}
    mapped = status_to_report(status, "mastodon.social", "IMD")
    assert mapped is not None
    assert "new_account" in mapped["extra_flags"]


def test_ingest_charges_the_account_flags_and_keeps_their_reasons():
    text = "Heavy rain and waterlogging in Patna since morning"
    plain = derive_text_fields("SOCIAL_MEDIA", text, uuid.uuid4())
    flags, basis = flags_for(POSTED - timedelta(days=2), 1)
    flagged = derive_text_fields("SOCIAL_MEDIA", text, uuid.uuid4(), extra_flags=flags, extra_basis=basis)
    assert flagged["flags"] == ["new_account", "few_followers"]
    assert flagged["credibility"] == round(plain["credibility"] * 0.48, 4)
    assert flagged["analysis"]["flag_basis"]["few_followers"] == "1 follower"
