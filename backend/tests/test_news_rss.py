"""
Phase 2 T5 — the Google News RSS parser, as pure unit tests.

Fixtures are two real searches saved on 24 Sep, 100 items each: "IMD heavy
rain" in English and "भारी बारिश" in Hindi. The poller's cases (one row per
guid across queries, stale items, the failed tick) need a database and live in
the integration tests.
"""

from datetime import timezone
from pathlib import Path

import pytest

from app.services.news_rss import (
    FeedUnreadable,
    headline_key,
    parse_feed,
    strip_publisher,
    useful_description,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def english():
    return parse_feed((FIXTURES / "google_news_imd_heavy_rain.xml").read_bytes())


@pytest.fixture(scope="module")
def hindi():
    return parse_feed((FIXTURES / "google_news_hi_heavy_rain.xml").read_bytes())


# ── T5's table ─────────────────────────────────────────────────────────────────

def test_all_hundred_items_parse(english):
    assert len(english) == 100
    assert len({i.guid for i in english}) == 100


def test_publishers_are_extracted(english):
    by_headline = {i.headline: i for i in english}
    item = by_headline["IMD warns of extremely heavy rain in Telangana districts"]
    assert item.publisher == "Telangana Today"
    assert all(i.publisher for i in english)
    assert "The Hindu" in {i.publisher for i in english}


def test_publisher_domain_drops_www(english):
    assert all(i.publisher_domain and not i.publisher_domain.startswith("www.") for i in english)


def test_pubdate_is_utc(english):
    for item in english:
        assert item.published_at is not None
        assert item.published_at.tzinfo == timezone.utc


def test_hindi_headlines_are_intact(hindi):
    assert len(hindi) == 100
    assert any("भारी बारिश" in i.headline for i in hindi)
    assert all("&#" not in i.headline for i in hindi)


@pytest.mark.parametrize(
    "payload",
    [b"<rss><channel><item>", b"not xml at all", b""],
)
def test_malformed_xml_raises_feed_unreadable(payload):
    with pytest.raises(FeedUnreadable):
        parse_feed(payload)


def test_a_document_that_is_not_rss_is_unreadable():
    with pytest.raises(FeedUnreadable, match="not an RSS"):
        parse_feed(b"<feed><entry/></feed>")


# ── The headline ───────────────────────────────────────────────────────────────

def test_the_trailing_publisher_is_stripped():
    assert strip_publisher("IMD warns of rain - The Hindu", "The Hindu") == "IMD warns of rain"


def test_a_dash_in_the_headline_itself_stays():
    assert strip_publisher("Rain - and more rain - The Hindu", "The Hindu") == "Rain - and more rain"
    assert strip_publisher("Rain - and more rain", "The Hindu") == "Rain - and more rain"


def test_a_title_that_is_only_the_publisher_is_kept():
    assert strip_publisher(" - The Hindu", "The Hindu") == "- The Hindu"


def test_no_headline_keeps_its_publisher_suffix(english):
    assert not [i for i in english if i.headline.endswith(f" - {i.publisher}")]


def test_headline_key_ignores_case_and_punctuation():
    assert headline_key("IMD issues RED alert!") == headline_key("IMD issues red alert")
    assert headline_key("IMD issues red alert") != headline_key("IMD issues orange alert")


# ── The description ────────────────────────────────────────────────────────────

def test_googles_link_block_is_dropped(english):
    assert all(i.description is None for i in english)


def test_a_related_stories_list_is_dropped():
    assert useful_description("<ol><li>a</li></ol>", "Headline", "Pub") is None


def test_a_real_summary_is_kept():
    desc = "<p>Headline</p> Schools in six districts stay shut on Thursday as rivers rise."
    assert useful_description(desc, "Headline", "Pub") == (
        "Schools in six districts stay shut on Thursday as rivers rise."
    )


def test_an_item_with_no_guid_or_title_is_skipped():
    feed = (
        b"<rss><channel>"
        b"<item><title>Only a title</title></item>"
        b"<item><guid>g1</guid></item>"
        b"<item><guid>g2</guid><title>Kept - Pub</title><source url='https://www.pub.in'>Pub</source></item>"
        b"</channel></rss>"
    )
    items = parse_feed(feed)
    assert [(i.guid, i.headline, i.publisher_domain) for i in items] == [("g2", "Kept", "pub.in")]
