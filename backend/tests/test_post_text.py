"""
Phase 2 T4 and T7 — the pure text helpers behind collected posts.

* `html_to_text` (T4): a Mastodon post's HTML as plain text, each link's URL
  once, hashtags kept as written.
* `canonical_url` (T7): one article's many shared URLs as one, so a story
  linked twenty times counts once.
* `core_text` (T7): a post without its links and hashtag tail, so an outlet's
  post and its own RSS item compare as the same text.
"""

import pytest

from app.services.text_processing import canonical_url, core_text, html_to_text


# ── canonical_url ──────────────────────────────────────────────────────────────

def test_t7_table_row_one_tracking_and_trailing_slash_are_the_same_link():
    assert canonical_url("https://x.com/a?utm_source=m") == canonical_url("https://x.com/a/")


@pytest.mark.parametrize(
    "url, canonical",
    [
        ("https://www.x.com/a/?utm_source=m#top", "https://x.com/a"),
        ("https://m.x.com/a/amp", "https://x.com/a"),
        ("https://x.com/amp/a", "https://x.com/a"),
        ("http://X.com/a?id=7&utm_medium=social", "https://x.com/a?id=7"),
        ("https://x.com/a?fbclid=IwAR0abc", "https://x.com/a"),
        ("https://x.com/a?b=2&a=1", "https://x.com/a?a=1&b=2"),
        ("www.thehindu.com/news/x.ece", "https://thehindu.com/news/x.ece"),
        ("https://x.com/a).", "https://x.com/a"),
        ("https://x.com", "https://x.com"),
        # Not a www./m. prefix: the host is kept whole.
        ("https://mastodon.social/@imd/123", "https://mastodon.social/@imd/123"),
    ],
)
def test_canonical_url(url, canonical):
    assert canonical_url(url) == canonical


@pytest.mark.parametrize("url", [None, "", "not a url", "ftp://x.com/a", "mailto:a@b.c"])
def test_not_a_web_url_is_none(url):
    assert canonical_url(url) is None


def test_a_page_choosing_parameter_keeps_two_articles_apart():
    assert canonical_url("https://x.com/story?id=7") != canonical_url("https://x.com/story?id=8")


# ── core_text ──────────────────────────────────────────────────────────────────

def test_core_text_drops_the_link_and_hashtag_tail():
    post = "IMD warns of heavy rain in Telangana https://t.co/abc #IMD #Rain"
    assert core_text(post) == "IMD warns of heavy rain in Telangana"


def test_an_outlets_post_and_its_rss_headline_share_a_core():
    post = "IMD warns of extremely heavy rain in Telangana districts https://example.com/x #IMD"
    headline = "IMD warns of extremely heavy rain in Telangana districts"
    assert core_text(post) == core_text(headline)


def test_a_leading_hashtag_is_part_of_the_text():
    assert core_text("#IMD alert for Kerala") == "#IMD alert for Kerala"


def test_core_text_of_nothing():
    assert core_text(None) == ""
    assert core_text("https://t.co/abc #IMD") == ""


# ── html_to_text ───────────────────────────────────────────────────────────────

# How Mastodon renders a post: a hashtag link, and a page link split into
# three spans with the scheme and the tail hidden.
MASTODON_HTML = (
    '<p>Heavy rain <a href="https://mastodon.social/tags/imd" class="mention hashtag" rel="tag">'
    "#<span>imd</span></a></p>"
    '<p>See <a href="https://example.com/news/2026/09/24/heavy-rain" rel="nofollow noopener">'
    '<span class="invisible">https://</span><span class="ellipsis">example.com/news/2026/</span>'
    '<span class="invisible">09/24/heavy-rain</span></a><br>more &amp; more</p>'
)


def test_t4_table_row_tags_gone_url_once():
    text = html_to_text(MASTODON_HTML)
    assert "<" not in text and ">" not in text
    assert text.count("https://example.com/news/2026/09/24/heavy-rain") == 1
    assert "example.com/news/2026/ " not in text  # the truncated visible form


def test_hashtags_keep_their_text():
    assert html_to_text(MASTODON_HTML).startswith("Heavy rain #imd")


def test_entities_are_decoded_and_breaks_become_lines():
    assert html_to_text(MASTODON_HTML).splitlines() == [
        "Heavy rain #imd",
        "See https://example.com/news/2026/09/24/heavy-rain",
        "more & more",
    ]


def test_mentions_keep_their_text_not_the_profile_url():
    html = '<p><span class="h-card"><a href="https://mastodon.social/@imd" class="u-url mention">@<span>imd</span></a></span> thanks</p>'
    assert html_to_text(html) == "@imd thanks"


def test_empty_html():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""
