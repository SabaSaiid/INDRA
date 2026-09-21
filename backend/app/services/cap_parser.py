"""
INDRA Platform — CAP 1.2 parser for the SACHET (NDMA) national alert feed

Layer 1's second scheduled feed, and the first one that carries another agency's
judgement rather than a raw measurement.

`https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml` lists the live
alerts for all of India. Each item links to a CAP 1.2 document, and most carry a
`Polygon URL` parameter pointing at the warning's actual footprint. Verified
against the live feed on 21 Sep 2026: 99 alerts, senders including IMD Ahmedabad,
IMD Mumbai, IMD Kolkata, CWC and several state SDMAs.

**Why this file is only parsing.** Everything here is a pure function over bytes.
The poller does the network and the database; this module can therefore be tested
against a captured payload with no stack running, which is how the boundary cases
below are pinned.

Three details that are easy to get wrong:

1. **CAP polygons are `lat,lng`; PostGIS wants `lng lat`.** Silently swapping them
   puts every Indian warning area in Kazakhstan or the Indian Ocean — inside the
   lat/lng bounds of nothing, so nothing would raise. `polygon_to_wkt` swaps, and
   `test_cap_parser.py` pins a known Gujarat ring to real Gujarat coordinates.

2. **Namespaces vary between senders.** The same feed serves `<cap:alert>` with a
   declared namespace and, from some senders, a bare `<alert>`. Matching on the
   *local* name handles both; matching on a fully-qualified tag drops half the
   feed without an error.

3. **`Unknown` severity is not a severity.** CAP allows it, and mapping it onto
   ADVISORY would invent a judgement the issuing agency explicitly declined to
   make. It maps to None, and an alert with no severity is stored with NULL —
   the same rule `station_readings.anomaly_score` follows.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

from app.models.enums import Severity

logger = logging.getLogger("indra.services.cap_parser")

# CAP 1.2 severity → INDRA severity. "Unknown" is deliberately absent: see the
# module docstring. CAP's own vocabulary is closed, so an unrecognised value is
# a malformed document, not a new category.
CAP_SEVERITY: Dict[str, Severity] = {
    "Extreme": Severity.CRITICAL,
    "Severe": Severity.HIGH,
    "Moderate": Severity.MODERATE,
    "Minor": Severity.ADVISORY,
}

# A CAP ring can be very large — one Gujarat district alert measured 235 KB of
# coordinates. Past this many points the ring is thinned by taking every Nth
# vertex, which keeps the shape while bounding what goes into Postgres and over
# the wire to the dashboard. Thinning is recorded on the row so the footprint is
# never passed off as the agency's exact geometry.
MAX_POLYGON_POINTS = 2000


def _local(tag: str) -> str:
    """`{urn:oasis:...}alert` → `alert`. Namespace-agnostic matching, detail 2."""
    return tag.rsplit("}", 1)[-1]


def _find(elem, name: str):
    """First descendant whose local name matches, or None."""
    for child in elem.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(elem, name: str) -> Optional[str]:
    node = _find(elem, name) if elem is not None else None
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


@dataclass
class RssItem:
    """One row of the SACHET RSS index."""

    identifier: str
    title: str
    category: Optional[str]
    cap_url: Optional[str]
    sender_name: Optional[str]
    published_at: Optional[datetime]


@dataclass
class CapAlert:
    """A parsed CAP 1.2 document. Absent fields stay None rather than guessed."""

    identifier: str
    sender: Optional[str] = None
    sent_at: Optional[datetime] = None
    status: Optional[str] = None
    msg_type: Optional[str] = None
    category: Optional[str] = None
    event: Optional[str] = None
    urgency: Optional[str] = None
    severity: Optional[Severity] = None
    raw_severity: Optional[str] = None
    certainty: Optional[str] = None
    effective_at: Optional[datetime] = None
    onset_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    area_desc: Optional[str] = None
    polygon_url: Optional[str] = None
    district_codes: List[str] = field(default_factory=list)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """
    CAP timestamps are ISO 8601 with an offset (`2026-09-21T07:54:00+05:30`).

    Returned tz-aware and left in the offset the sender used; the database column
    is `timestamptz`, so Postgres normalises. A naive value is returned as-is
    rather than assumed to be UTC — guessing an offset on an Indian alert would
    shift it by five and a half hours, quietly making live alerts look expired.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        logger.warning(f"CAP timestamp unparseable: {value!r}")
        return None


def parse_rss(payload: bytes) -> List[RssItem]:
    """
    The feed index. Never raises: a malformed feed yields [], logged once.

    `<guid>` is the stable per-alert identifier and the value the polygon and CAP
    endpoints take as `?identifier=`. An item without one cannot be fetched or
    deduplicated, so it is skipped.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as e:
        logger.warning(f"SACHET RSS unparseable: {e}")
        return []

    items: List[RssItem] = []
    for node in root.iter():
        if _local(node.tag) != "item":
            continue
        identifier = _text(node, "guid")
        if not identifier:
            continue
        author = _text(node, "author")
        # "controlroom@ndma.gov.in (IMD Ahmedabad)" → "IMD Ahmedabad"
        sender_name = None
        if author:
            match = re.search(r"\(([^)]+)\)", author)
            sender_name = match.group(1).strip() if match else author
        items.append(
            RssItem(
                identifier=identifier,
                title=_text(node, "title") or "",
                category=_text(node, "category"),
                cap_url=_text(node, "link"),
                sender_name=sender_name,
                published_at=parse_rfc822(_text(node, "pubDate")),
            )
        )
    return items


def parse_rfc822(value: Optional[str]) -> Optional[datetime]:
    """RSS `pubDate` is RFC 822 (`Mon, 21 Sep 2026 02:28:50 GMT`), not ISO."""
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value.strip())
    except (TypeError, ValueError) as e:
        logger.warning(f"RSS pubDate unparseable: {value!r} ({e})")
        return None


def parse_cap_alert(payload: bytes) -> Optional[CapAlert]:
    """
    One CAP document → a CapAlert, or None if it has no identifier or will not
    parse. Never raises.

    Only the first `<info>` block is read. Indian alerts repeat `<info>` per
    language (en-IN, then the regional language) with the same event, severity
    and area, so the first is the English one and the rest are translations.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as e:
        logger.warning(f"CAP document unparseable: {e}")
        return None

    identifier = _text(root, "identifier")
    if not identifier:
        logger.warning("CAP document has no <identifier>; skipped")
        return None

    info = None
    for node in root.iter():
        if _local(node.tag) == "info":
            info = node
            break

    alert = CapAlert(
        identifier=identifier,
        sender=_text(root, "sender"),
        sent_at=parse_datetime(_text(root, "sent")),
        status=_text(root, "status"),
        msg_type=_text(root, "msgType"),
    )

    if info is None:
        logger.warning(f"CAP {identifier} has no <info> block")
        return alert

    raw_severity = _text(info, "severity")
    alert.category = _text(info, "category")
    alert.event = _text(info, "event")
    alert.urgency = _text(info, "urgency")
    alert.raw_severity = raw_severity
    alert.severity = CAP_SEVERITY.get(raw_severity) if raw_severity else None
    alert.certainty = _text(info, "certainty")
    alert.effective_at = parse_datetime(_text(info, "effective"))
    alert.onset_at = parse_datetime(_text(info, "onset"))
    alert.expires_at = parse_datetime(_text(info, "expires"))
    alert.headline = _text(info, "headline")
    alert.description = _text(info, "description")
    alert.area_desc = _text(info, "areaDesc")

    if raw_severity and alert.severity is None and raw_severity != "Unknown":
        logger.warning(f"CAP {identifier} has unrecognised severity {raw_severity!r}")

    # <parameter><valueName>Polygon URL</valueName><value>https://…</value>
    for node in info.iter():
        if _local(node.tag) != "parameter":
            continue
        if (_text(node, "valueName") or "").strip().lower() == "polygon url":
            alert.polygon_url = _text(node, "value")
            break

    # <geocode><valueName>LGD District Code</valueName><value>444</value>
    for node in info.iter():
        if _local(node.tag) != "geocode":
            continue
        if "district" in (_text(node, "valueName") or "").lower():
            code = _text(node, "value")
            if code:
                alert.district_codes.append(code)

    return alert


def parse_polygon_points(payload: bytes) -> List[Tuple[float, float]]:
    """
    The polygon document → `[(lat, lng), …]` in CAP's own order, unswapped.

    Points that are not two finite numbers are dropped individually; a single
    malformed vertex should cost one point, not the whole warning area. Returns
    [] on anything unusable.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as e:
        logger.warning(f"CAP polygon unparseable: {e}")
        return []

    points: List[Tuple[float, float]] = []
    for node in root.iter():
        if _local(node.tag) != "polygon" or not (node.text or "").strip():
            continue
        for pair in node.text.split():
            parts = pair.split(",")
            if len(parts) != 2:
                continue
            try:
                lat, lng = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            points.append((lat, lng))
        if points:
            # First ring only. A CAP <area> may repeat <polygon>, but the schema
            # has one geometry column and merging disjoint rings into a single
            # ring would draw a warning area across places nobody warned about.
            break
    return points


def thin(points: List[Tuple[float, float]], limit: int = MAX_POLYGON_POINTS) -> Tuple[List[Tuple[float, float]], bool]:
    """
    (points, was_thinned). Keeps every Nth vertex when over the limit, always
    retaining the first point so the ring can still be closed.
    """
    if len(points) <= limit:
        return points, False
    step = (len(points) // limit) + 1
    return points[::step], True


def polygon_to_wkt(points: List[Tuple[float, float]]) -> Optional[str]:
    """
    `[(lat, lng), …]` → a closed `POLYGON((lng lat, …))` in EPSG:4326, or None
    if there is no usable ring.

    **The coordinate order flips here** (detail 1 in the module docstring): CAP
    writes `lat,lng`, WKT wants `lng lat`.

    A ring needs at least three distinct vertices, and PostGIS requires the first
    and last to be identical. CAP says the same, but real feeds do not always
    comply, so the ring is closed here rather than trusted.
    """
    if len(points) < 3:
        return None

    ring = list(points)
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    if len({(round(lat, 7), round(lng, 7)) for lat, lng in ring}) < 3:
        return None

    coords = ", ".join(f"{lng} {lat}" for lat, lng in ring)
    return f"POLYGON(({coords}))"
