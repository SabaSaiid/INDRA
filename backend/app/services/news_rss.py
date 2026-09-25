"""
INDRA Platform — Google News RSS parsing (layer 1, Phase 2 T5)

Pure: bytes in, items out. `workers/news_poller.py` does the fetching.

An item from `https://news.google.com/rss/search?q=…` looks like:

    <item>
      <title>IMD issues red alert for heavy rainfall in Telangana - News On AIR</title>
      <link>https://news.google.com/rss/articles/CBMi…</link>
      <guid isPermaLink="false">CBMi…</guid>
      <pubDate>Wed, 23 Sep 2026 08:45:00 GMT</pubDate>
      <description>&lt;a href="…"&gt;IMD issues red alert…&lt;/a&gt;&amp;nbsp;&amp;nbsp;
                   &lt;font color="#6f6f6f"&gt;News On AIR&lt;/font&gt;</description>
      <source url="https://newsonair.gov.in">News On AIR</source>
    </item>

* **The title carries the publisher** after " - ". It is removed when it is
  the `<source>` name, and only then: a headline may contain " - " itself.
* **The description is almost always Google's own link block**, the headline
  again and the publisher, or a list of related headlines. It is kept only
  when it says something the headline does not, which in practice is rarely.
* **Only the headline, link and publisher are stored**, never the article:
  each publisher's text is theirs.
"""

import email.utils
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

logger = logging.getLogger("indra.services.news_rss")

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_KEY_STRIP_RE = re.compile(r"[^\w\s]", re.UNICODE)


class FeedUnreadable(ValueError):
    """The body is not an RSS document this parser can read."""


@dataclass
class NewsItem:
    guid: str
    headline: str
    link: Optional[str]
    published_at: Optional[datetime]
    publisher: Optional[str]
    publisher_domain: Optional[str]
    description: Optional[str]

    @property
    def headline_key(self) -> str:
        return headline_key(self.headline)


def headline_key(headline: str) -> str:
    """
    A headline reduced to what makes two copies of it the same: lowercase,
    punctuation and extra spaces gone. "IMD issues RED alert!" and "IMD
    issues red alert" share a key; different wording does not.
    """
    s = _KEY_STRIP_RE.sub(" ", (headline or "").lower())
    return _SPACE_RE.sub(" ", s).strip()


def _text(node, name: str) -> Optional[str]:
    child = node.find(name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _plain(fragment: Optional[str]) -> str:
    """HTML (already XML-unescaped) to one line of text."""
    if not fragment:
        return ""
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host or None


def _time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if ts is None:
        return None
    return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def strip_publisher(title: str, publisher: Optional[str]) -> str:
    """"Headline - Publisher" → "Headline", only when the tail is the publisher."""
    title = _SPACE_RE.sub(" ", title or "").strip()
    if publisher:
        tail = f" - {publisher.strip()}"
        if title.endswith(tail) and len(title) > len(tail):
            return title[: -len(tail)].strip()
    return title


def useful_description(description: Optional[str], headline: str, publisher: Optional[str]) -> Optional[str]:
    """
    The description as text, or None when it is only Google's link block: the
    headline and publisher again, or a list of related headlines.
    """
    if not description:
        return None
    if "<ol" in description or "<li" in description:
        return None  # a cluster of related stories, each already its own item
    text = _plain(description)
    for known in (headline, publisher or ""):
        if known:
            text = text.replace(known, " ")
    text = _SPACE_RE.sub(" ", text).strip(" -|· ")
    return text if len(text) >= 30 else None


def parse_feed(payload: bytes) -> List[NewsItem]:
    """
    Every usable item in the feed. Raises FeedUnreadable for a body that is
    not RSS; an item with no guid or no title is skipped.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as e:
        raise FeedUnreadable(f"malformed XML: {e}") from e
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedUnreadable(f"not an RSS document (root <{root.tag}>)")

    items: List[NewsItem] = []
    for node in channel.findall("item"):
        guid = _text(node, "guid")
        title = _text(node, "title")
        if not guid or not title:
            continue
        source = node.find("source")
        publisher = (source.text or "").strip() if source is not None and source.text else None
        publisher_url = source.get("url") if source is not None else None
        headline = strip_publisher(title, publisher)
        items.append(NewsItem(
            guid=guid,
            headline=headline,
            link=_text(node, "link"),
            published_at=_time(_text(node, "pubDate")),
            publisher=publisher,
            publisher_domain=_domain(publisher_url),
            description=useful_description(_text(node, "description"), headline, publisher),
        ))
    return items
