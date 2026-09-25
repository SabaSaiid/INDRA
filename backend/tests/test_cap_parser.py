"""
The SACHET CAP parser — layer 1's official-warning feed.

The SACHET fixtures (`tests/fixtures/sachet_*.xml`) are **real payloads
captured from the live NDMA feed on 21 Sep 2026**, not hand-written
approximations. That matters: the two defects this parser is most likely to
have — swapped polygon coordinates and namespace-sensitive tag matching — both
look fine against a fixture written by the same person who wrote the parser,
because the assumption gets baked into both. A captured payload does not share
the assumption.

The Gujarat alert used throughout covers Navsari / The Dangs / Valsad, and its
first real vertex is `21.068749,72.796081` — southern Gujarat. If the parser ever
emits `POLYGON((21.06 72.79))` instead of `POLYGON((72.79 21.06))`, that point
lands in the Arabian Sea off Somalia, inside no bounds check, raising nothing.
`test_polygon_coordinates_are_not_swapped` is the only thing standing between
that bug and a demo.
"""

import pathlib

import pytest

from app.models.enums import Severity
from app.services.cap_parser import (
    CAP_SEVERITY,
    parse_cap_alert,
    parse_datetime,
    parse_polygon_points,
    parse_rss,
    polygon_to_wkt,
    thin,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── RSS index ──────────────────────────────────────────────────────────────

def test_parse_rss_reads_real_feed():
    items = parse_rss(fixture("sachet_rss_sample.xml"))
    assert len(items) == 3
    first = items[0]
    assert first.identifier == "1789957059562006"
    assert first.category == "Met"
    assert "FetchXMLFile?identifier=1789957059562006" in first.cap_url


def test_parse_rss_extracts_sender_from_author():
    """`controlroom@ndma.gov.in (IMD Thiruvananthapuram)` → the office name."""
    items = parse_rss(fixture("sachet_rss_sample.xml"))
    assert items[0].sender_name == "IMD Thiruvananthapuram"


def test_parse_rss_reads_rfc822_pubdate():
    """RSS pubDate is RFC 822, not ISO. Parsing it as ISO yields None."""
    items = parse_rss(fixture("sachet_rss_sample.xml"))
    published = items[0].published_at
    assert published is not None
    assert (published.year, published.month, published.day) == (2026, 9, 21)
    assert published.tzinfo is not None


def test_parse_rss_survives_garbage():
    assert parse_rss(b"not xml at all") == []
    assert parse_rss(b"") == []


def test_parse_rss_skips_items_without_guid():
    """No guid means no way to fetch or deduplicate the alert."""
    xml = b"""<rss><channel>
      <item><title>no guid here</title></item>
      <item><title>has one</title><guid>123</guid></item>
    </channel></rss>"""
    items = parse_rss(xml)
    assert [i.identifier for i in items] == ["123"]


# ── CAP document ───────────────────────────────────────────────────────────

def test_parse_cap_reads_every_field_from_the_real_alert():
    alert = parse_cap_alert(fixture("sachet_cap_sample.xml"))
    assert alert is not None
    assert alert.identifier == "IN-1789954357601020_20"
    assert alert.sender == "Gujarat-SDMA"
    assert alert.status == "Actual"
    assert alert.msg_type == "Update"
    assert alert.category == "Met"
    assert alert.event == "Light Rain"
    assert alert.urgency == "Expected"
    assert alert.certainty == "Likely"
    assert "Navsari" in alert.headline
    assert "Gujarat" in alert.area_desc


def test_parse_cap_maps_severity_and_keeps_the_agency_wording():
    alert = parse_cap_alert(fixture("sachet_cap_sample.xml"))
    assert alert.raw_severity == "Moderate"
    assert alert.severity is Severity.MODERATE


def test_parse_cap_reads_timestamps_with_the_senders_offset():
    """
    `2026-09-21T07:54:00+05:30` must keep +05:30. Assuming UTC would shift every
    Indian alert 5.5 h and make live warnings look expired.
    """
    alert = parse_cap_alert(fixture("sachet_cap_sample.xml"))
    assert alert.sent_at.utcoffset().total_seconds() == 5.5 * 3600
    assert alert.expires_at is not None
    assert alert.expires_at > alert.effective_at


def test_parse_cap_finds_polygon_url_parameter():
    alert = parse_cap_alert(fixture("sachet_cap_sample.xml"))
    assert alert.polygon_url is not None
    assert "FetchPolygonXMLFile?identifier=1789954357601020" in alert.polygon_url


def test_parse_cap_collects_lgd_district_codes():
    alert = parse_cap_alert(fixture("sachet_cap_sample.xml"))
    assert alert.district_codes == ["444", "453", "462"]


def test_parse_cap_handles_a_bare_namespace():
    """
    The real fixture declares `xmlns:cap` and uses `<cap:alert>`. Some senders
    publish `<alert>` with no namespace. Local-name matching must read both;
    fully-qualified matching silently drops one of them.
    """
    alert = parse_cap_alert(
        b"<alert><identifier>X-1</identifier><info>"
        b"<severity>Severe</severity><event>Heavy Rain</event>"
        b"</info></alert>"
    )
    assert alert is not None
    assert alert.identifier == "X-1"
    assert alert.severity is Severity.HIGH
    assert alert.event == "Heavy Rain"


@pytest.mark.parametrize(
    "cap_value,expected",
    [
        ("Extreme", Severity.CRITICAL),
        ("Severe", Severity.HIGH),
        ("Moderate", Severity.MODERATE),
        ("Minor", Severity.ADVISORY),
    ],
)
def test_severity_mapping(cap_value, expected):
    assert CAP_SEVERITY[cap_value] is expected


def test_unknown_severity_maps_to_none_not_advisory():
    """
    CAP's `Unknown` means the agency declined to rate it. Mapping that onto
    ADVISORY would manufacture a judgement nobody made — the same defect class
    as a fabricated telemetry reading.
    """
    alert = parse_cap_alert(
        b"<alert><identifier>X-2</identifier><info>"
        b"<severity>Unknown</severity></info></alert>"
    )
    assert alert.raw_severity == "Unknown"
    assert alert.severity is None
    assert "Unknown" not in CAP_SEVERITY


def test_parse_cap_without_identifier_is_rejected():
    assert parse_cap_alert(b"<alert><info><severity>Severe</severity></info></alert>") is None


def test_parse_cap_survives_garbage():
    assert parse_cap_alert(b"<alert><unclosed>") is None
    assert parse_cap_alert(b"") is None


def test_parse_datetime_returns_none_rather_than_raising():
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None
    assert parse_datetime("") is None


# ── Polygon ────────────────────────────────────────────────────────────────

def test_polygon_points_are_read_in_cap_order():
    points = parse_polygon_points(fixture("sachet_polygon_sample.xml"))
    assert len(points) == 40
    # CAP order is (lat, lng), left exactly as the feed wrote it.
    assert points[0] == (21.068749, 72.796081)


def test_polygon_coordinates_are_not_swapped():
    """
    The bug this whole file exists for.

    CAP writes `lat,lng`; WKT wants `lng lat`. The real alert covers southern
    Gujarat, so longitude ≈ 72.8 and latitude ≈ 21.07. Emitting them in CAP's
    order produces a polygon at 21°E 72°N — northern Siberia — which is a
    perfectly valid WKT string that no bounds check would reject.
    """
    points = parse_polygon_points(fixture("sachet_polygon_sample.xml"))
    wkt = polygon_to_wkt(points)
    assert wkt.startswith("POLYGON((")

    first = wkt[len("POLYGON((") :].split(",")[0].split()
    lng, lat = float(first[0]), float(first[1])

    assert 72.0 < lng < 73.5, f"longitude {lng} is not in Gujarat"
    assert 20.5 < lat < 21.5, f"latitude {lat} is not in Gujarat"
    # And the India bounding box the report API enforces.
    assert 68.0 <= lng <= 97.5 and 6.5 <= lat <= 37.6


def test_polygon_ring_is_closed():
    """PostGIS rejects an unclosed ring; real feeds do not always close theirs."""
    wkt = polygon_to_wkt([(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)])
    coords = wkt[len("POLYGON((") : -2].split(", ")
    assert coords[0] == coords[-1]
    assert len(coords) == 4


def test_polygon_already_closed_is_not_double_closed():
    wkt = polygon_to_wkt([(1.0, 10.0), (2.0, 20.0), (3.0, 30.0), (1.0, 10.0)])
    coords = wkt[len("POLYGON((") : -2].split(", ")
    assert len(coords) == 4


@pytest.mark.parametrize(
    "points",
    [
        [],
        [(1.0, 1.0)],
        [(1.0, 1.0), (2.0, 2.0)],
        # Three entries, but only two distinct vertices — not a ring.
        [(1.0, 1.0), (2.0, 2.0), (1.0, 1.0)],
    ],
)
def test_degenerate_rings_are_none_not_invalid_wkt(points):
    assert polygon_to_wkt(points) is None


def test_malformed_vertex_costs_one_point_not_the_whole_area():
    xml = b"<alert><polygon>21.0,72.0 garbage 21.1,72.1 9,9,9 21.2,72.2</polygon></alert>"
    points = parse_polygon_points(xml)
    assert points == [(21.0, 72.0), (21.1, 72.1), (21.2, 72.2)]


def test_only_the_first_ring_is_used():
    """
    Merging disjoint rings into one would draw a warning area across places
    nobody warned about.
    """
    xml = (
        b"<alert><area>"
        b"<polygon>21.0,72.0 21.1,72.1 21.2,72.2</polygon>"
        b"<polygon>28.0,77.0 28.1,77.1 28.2,77.2</polygon>"
        b"</area></alert>"
    )
    points = parse_polygon_points(xml)
    assert points == [(21.0, 72.0), (21.1, 72.1), (21.2, 72.2)]


def test_polygon_survives_garbage():
    assert parse_polygon_points(b"<alert><polygon></polygon></alert>") == []
    assert parse_polygon_points(b"not xml") == []


# ── Thinning ───────────────────────────────────────────────────────────────

def test_small_ring_is_not_thinned():
    points = [(float(i), float(i)) for i in range(100)]
    thinned, was_thinned = thin(points, limit=2000)
    assert was_thinned is False
    assert thinned == points


def test_large_ring_is_thinned_under_the_limit():
    """One live Gujarat ring was 235 KB. The shape survives; the size does not."""
    points = [(20.0 + i / 10000, 72.0 + i / 10000) for i in range(12000)]
    thinned, was_thinned = thin(points, limit=2000)
    assert was_thinned is True
    assert len(thinned) <= 2000
    assert thinned[0] == points[0]
    assert polygon_to_wkt(thinned) is not None


def test_thinning_at_the_boundary():
    points = [(float(i), float(i)) for i in range(2000)]
    assert thin(points, limit=2000)[1] is False
    points.append((2000.0, 2000.0))
    assert thin(points, limit=2000)[1] is True
