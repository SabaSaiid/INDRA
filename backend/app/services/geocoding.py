"""
INDRA Platform — Indian Geospatial Resolver & Geocoding Normalizer

Validates, sanitizes, and normalizes geographical coordinates for raw reports
and verified events within Indian territorial boundaries.
Prevents coordinate inversion (lat/lng swapped) and auto-resolves coordinates
for incoming reports with missing GPS.

Two directions live here and they are not the same thing:

- **Forward** — `sanitize_coordinates`, backed by `INDIAN_GAZETTEER`, turns a
  name mentioned in a report into coordinates when the report carried no GPS.
- **Reverse** — `reverse_geocode`, backed by `data/geo/india_districts.csv`,
  turns coordinates into a district name. This is the direction the platform
  spent its whole life without, which is why every real event was served to
  the console as `"city": "Unknown"`.

The reverse resolver never invents a name. When it cannot place a point it
returns `None`, and the column stays NULL, so "we do not know where this is"
stays distinguishable from "somewhere in India" — the same rule the rest of
the receipt follows for factors that did not run.
"""

import csv
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger("indra.services.geocoding")

# Indian sovereign territory geographic bounding box
INDIA_MIN_LAT = 6.5
INDIA_MAX_LAT = 37.6
INDIA_MIN_LNG = 68.0
INDIA_MAX_LNG = 97.5

# High-precision gazetteer of Indian state capitals and disaster nodes
INDIAN_GAZETTEER: Dict[str, Dict[str, Any]] = {
    "patna": {"city": "Patna", "state": "Bihar", "lat": 25.6093, "lng": 85.1376},
    "gaya": {"city": "Gaya", "state": "Bihar", "lat": 24.7914, "lng": 85.0002},
    "kolkata": {"city": "Kolkata", "state": "West Bengal", "lat": 22.5726, "lng": 88.3639},
    "siliguri": {"city": "Siliguri", "state": "West Bengal", "lat": 26.7271, "lng": 88.3953},
    "darjeeling": {"city": "Darjeeling", "state": "West Bengal", "lat": 27.0410, "lng": 88.2663},
    "bhubaneswar": {"city": "Bhubaneswar", "state": "Odisha", "lat": 20.2961, "lng": 85.8245},
    "puri": {"city": "Puri", "state": "Odisha", "lat": 19.8135, "lng": 85.8312},
    "cuttack": {"city": "Cuttack", "state": "Odisha", "lat": 20.4625, "lng": 85.8828},
    "ranchi": {"city": "Ranchi", "state": "Jharkhand", "lat": 23.3441, "lng": 85.3096},
    "mumbai": {"city": "Mumbai", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    "pune": {"city": "Pune", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567},
    "nagpur": {"city": "Nagpur", "state": "Maharashtra", "lat": 21.1458, "lng": 79.0882},
    "nashik": {"city": "Nashik", "state": "Maharashtra", "lat": 19.9975, "lng": 73.7898},
    "ahmedabad": {"city": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lng": 72.5714},
    "surat": {"city": "Surat", "state": "Gujarat", "lat": 21.1702, "lng": 72.8311},
    "vadodara": {"city": "Vadodara", "state": "Gujarat", "lat": 22.3072, "lng": 73.1812},
    "panaji": {"city": "Panaji", "state": "Goa", "lat": 15.4909, "lng": 73.8278},
    "new delhi": {"city": "New Delhi", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "delhi": {"city": "New Delhi", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "lucknow": {"city": "Lucknow", "state": "Uttar Pradesh", "lat": 26.8467, "lng": 80.9462},
    "varanasi": {"city": "Varanasi", "state": "Uttar Pradesh", "lat": 25.3176, "lng": 82.9739},
    "kanpur": {"city": "Kanpur", "state": "Uttar Pradesh", "lat": 26.4499, "lng": 80.3319},
    "dehradun": {"city": "Dehradun", "state": "Uttarakhand", "lat": 30.3165, "lng": 78.0322},
    "shimla": {"city": "Shimla", "state": "Himachal Pradesh", "lat": 31.1048, "lng": 77.1734},
    "manali": {"city": "Manali", "state": "Himachal Pradesh", "lat": 32.2432, "lng": 77.1892},
    "srinagar": {"city": "Srinagar", "state": "Jammu and Kashmir", "lat": 34.0837, "lng": 74.7973},
    "jammu": {"city": "Jammu", "state": "Jammu and Kashmir", "lat": 32.7266, "lng": 74.8570},
    "chandigarh": {"city": "Chandigarh", "state": "Punjab", "lat": 30.7333, "lng": 76.7794},
    "amritsar": {"city": "Amritsar", "state": "Punjab", "lat": 31.6340, "lng": 74.8723},
    "jaipur": {"city": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lng": 75.7873},
    "jodhpur": {"city": "Jodhpur", "state": "Rajasthan", "lat": 26.2389, "lng": 73.0243},
    "barmer": {"city": "Barmer", "state": "Rajasthan", "lat": 25.7521, "lng": 71.3967},
    "chennai": {"city": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    "coimbatore": {"city": "Coimbatore", "state": "Tamil Nadu", "lat": 11.0168, "lng": 76.9558},
    "bengaluru": {"city": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "bangalore": {"city": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "mangalore": {"city": "Mangalore", "state": "Karnataka", "lat": 12.9141, "lng": 74.8560},
    "hyderabad": {"city": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    "visakhapatnam": {"city": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lng": 83.2185},
    "vizag": {"city": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lng": 83.2185},
    "vijayawada": {"city": "Vijayawada", "state": "Andhra Pradesh", "lat": 16.5062, "lng": 80.6480},
    "kochi": {"city": "Kochi", "state": "Kerala", "lat": 9.9312, "lng": 76.2673},
    "thiruvananthapuram": {"city": "Thiruvananthapuram", "state": "Kerala", "lat": 8.5241, "lng": 76.9366},
    "wayanad": {"city": "Wayanad", "state": "Kerala", "lat": 11.6854, "lng": 76.1320},
    "idukki": {"city": "Idukki", "state": "Kerala", "lat": 9.8494, "lng": 76.9804},
    "guwahati": {"city": "Guwahati", "state": "Assam", "lat": 26.1445, "lng": 91.7362},
    "silchar": {"city": "Silchar", "state": "Assam", "lat": 24.8333, "lng": 92.7789},
    "shillong": {"city": "Shillong", "state": "Meghalaya", "lat": 25.5788, "lng": 91.8933},
    "imphal": {"city": "Imphal", "state": "Manipur", "lat": 24.8170, "lng": 93.9368},
    "agartala": {"city": "Agartala", "state": "Tripura", "lat": 23.8315, "lng": 91.2868},
    "bhopal": {"city": "Bhopal", "state": "Madhya Pradesh", "lat": 23.2599, "lng": 77.4126},
    "indore": {"city": "Indore", "state": "Madhya Pradesh", "lat": 22.7196, "lng": 75.8577},
    "raipur": {"city": "Raipur", "state": "Chhattisgarh", "lat": 21.2514, "lng": 81.6296},
    "port blair": {"city": "Port Blair", "state": "Andaman and Nicobar", "lat": 11.6234, "lng": 92.7265},
}


# ---------------------------------------------------------------------------
# Reverse geocoding — coordinates to a district name
# ---------------------------------------------------------------------------

# Built by scripts/build_gazetteer.py; see that file for provenance.
DISTRICTS_CSV = (
    Path(__file__).resolve().parents[3] / "data" / "geo" / "india_districts.csv"
)

# How far a point may sit from the representative point of the nearest district
# before we stop claiming to know where it is. These two numbers are the whole
# honesty policy of the resolver, so they are named rather than inlined.
#
# 25 km is about the radius of a typical Indian district, so a point that close
# to the representative point is almost certainly inside it. Past 60 km we are
# guessing, and past 60 km we decline instead. Both bands are only consulted
# when no district's bounding box contains the point at all — a containment hit
# is exact enough to skip distance entirely.
DISTRICT_CONFIDENT_KM = 25.0
DISTRICT_NEARBY_KM = 60.0

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Place:
    """
    A resolved location, carrying how it was resolved rather than only what.

    `precision` is the part that matters downstream. A caller that wants to
    print a label needs to know whether "Patna" means "in Patna district" or
    "the nearest district we could name is Patna, 40 km away", and the API
    publishes it for the same reason the confidence receipt publishes factor
    coverage: a number without its basis invites being read as more than it is.
    """

    district: Optional[str]
    state: str
    # "district" — the point is in it, or the text named it outright
    # "near"     — close to it, but we cannot say it is inside
    # "state"    — no district could be identified, only the state
    precision: str
    distance_km: float

    @property
    def label(self) -> str:
        """The human-facing name, which hedges whenever the resolver hedged."""
        if self.precision == "state" or not self.district:
            return self.state
        if self.precision == "near":
            return f"near {self.district}"
        return self.district


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def load_districts() -> List[Dict[str, Any]]:
    """
    Read the district gazetteer once per process.

    A missing or unreadable file is logged and yields an empty table rather
    than raising: a stack that cannot name places is degraded, but a stack
    that will not boot is down. Every caller already handles `None`.
    """
    try:
        with DISTRICTS_CSV.open(newline="") as handle:
            rows = [
                {
                    "district": row["district"],
                    "state": row["state"],
                    "lat": float(row["lat"]),
                    "lng": float(row["lng"]),
                    "min_lat": float(row["min_lat"]),
                    "min_lng": float(row["min_lng"]),
                    "max_lat": float(row["max_lat"]),
                    "max_lng": float(row["max_lng"]),
                }
                for row in csv.DictReader(handle)
            ]
    except (OSError, KeyError, ValueError) as exc:
        logger.error(
            f"District gazetteer unreadable at {DISTRICTS_CSV} ({exc}) — "
            "locations will resolve to None until it is rebuilt with "
            "scripts/build_gazetteer.py"
        )
        return []

    if not rows:
        logger.error(f"District gazetteer at {DISTRICTS_CSV} is empty")
    return rows


def reverse_geocode(lat: Optional[float], lng: Optional[float]) -> Optional[Place]:
    """
    Resolve coordinates to an Indian district, or `None` when we cannot.

    Two passes, in order:

    1. **Bounding-box containment.** Districts whose box contains the point;
       the nearest representative point among them wins. Boxes overlap freely
       — a box is a rectangle and a district is not — so containment narrows
       the field rather than deciding it outright. This is what lets a point
       in western Kutch resolve to Kutch despite being 100 km from the one
       point that represents it.
    2. **Nearest representative point**, banded by the two constants above.

    Returns `None` for a point outside India, and for a point that no box
    contains and that is more than `DISTRICT_NEARBY_KM` from every district.
    """
    if lat is None or lng is None:
        return None
    if not is_within_india(lat, lng):
        return None

    districts = load_districts()
    if not districts:
        return None

    containing = [
        d for d in districts
        if d["min_lat"] <= lat <= d["max_lat"] and d["min_lng"] <= lng <= d["max_lng"]
    ]

    if containing:
        best = min(containing, key=lambda d: _haversine_km(lat, lng, d["lat"], d["lng"]))
        return Place(
            district=best["district"],
            state=best["state"],
            precision="district",
            distance_km=round(_haversine_km(lat, lng, best["lat"], best["lng"]), 2),
        )

    best = min(districts, key=lambda d: _haversine_km(lat, lng, d["lat"], d["lng"]))
    distance = _haversine_km(lat, lng, best["lat"], best["lng"])

    if distance > DISTRICT_NEARBY_KM:
        return None

    return Place(
        district=best["district"],
        state=best["state"],
        precision="district" if distance <= DISTRICT_CONFIDENT_KM else "near",
        distance_km=round(distance, 2),
    )


@lru_cache(maxsize=1)
def _districts_by_name() -> Dict[str, Dict[str, Any]]:
    """Lowercased district name to its row, for resolving alerts by name."""
    return {d["district"].lower(): d for d in load_districts()}


def district_by_name(name: str, state_hint: Optional[str] = None) -> Optional[Place]:
    """
    Resolve a district by name, for feeds that publish places and not points.

    SACHET CAP alerts are the caller: NDMA answers 403 on the polygon endpoint,
    so not one of the alerts in the database carries a geometry, but their
    `area_desc` names districts in plain text ("Chamarajanagara, Kodagu, Mysuru
    districts of Karnataka"). Their `district_codes` are LGD codes, a
    vocabulary this gazetteer does not carry, so the name is what we have.

    `state_hint` disambiguates the names that repeat across states — Bilaspur
    is in both Chhattisgarh and Himachal Pradesh, Aurangabad in both
    Maharashtra and Bihar. Without a hint an ambiguous name is refused rather
    than guessed.
    """
    if not name:
        return None

    key = name.strip().lower()
    if not key:
        return None

    matches = [d for d in load_districts() if d["district"].lower() == key]
    if not matches:
        return None

    # A state hint constrains every lookup, not only the ambiguous ones. An
    # earlier version applied it only when a name matched more than one
    # district, so "Purulia district of Kerala" resolved happily to Purulia in
    # West Bengal: the hint was dropped precisely because the name looked
    # unambiguous. A hint that contradicts the only match is a contradiction,
    # not a detail to discard.
    if state_hint:
        hint = state_hint.strip().lower()
        matches = [d for d in matches if d["state"].lower() == hint]
        if len(matches) != 1:
            return None
    elif len(matches) > 1:
        return None

    best = matches[0]
    return Place(
        district=best["district"],
        state=best["state"],
        precision="district",
        distance_km=0.0,
    )


# Words a CAP area description wraps around the place names it carries.
# "Chamarajanagara,Kodagu,Mysuru districts of Karnataka" has to reduce to
# three district names, and "mkp-ardhaveedu, mkp-dornala mandals" to nothing
# at all — sub-district units are below this gazetteer's resolution, and
# inventing a district for them would be the failure mode this whole module
# is built to avoid.
_AREA_NOISE_WORDS = {
    "district", "districts", "dist", "of", "and", "the",
    "mandal", "mandals", "taluk", "taluka", "talukas", "tehsil", "tehsils",
    "block", "blocks", "city", "town", "area", "areas", "region", "parts",
    "river", "basin", "sub-division", "subdivision",
}

_AREA_SPLIT_RE = re.compile(r"[,/;()\[\]]+|\s+-\s+|\bและ\b")


@lru_cache(maxsize=1)
def _state_names() -> List[str]:
    """State names longest-first, so 'Andhra Pradesh' wins over any substring."""
    names = {d["state"] for d in load_districts()}
    return sorted(names, key=len, reverse=True)


# Close enough to be a spelling of the same district, far enough that two
# genuinely different districts do not collide. Purulia/Puruliya and
# Paschim/Pashchim Medinipur are the real cases from the live SACHET feed:
# CAP senders transliterate as they please and the gazetteer has one spelling.
_NAME_MATCH_CUTOFF = 0.88


def _fuzzy_district(name: str, state_hint: Optional[str]) -> Optional[Place]:
    """
    A district whose name is a near-spelling of `name`.

    Only ever consulted after an exact match has failed, and only within a
    known state when one was named — matching a transliteration across all
    737 districts would turn a typo into a confident answer somewhere else
    in the country.
    """
    import difflib

    candidates = [
        d for d in load_districts()
        if state_hint is None or d["state"].lower() == state_hint.lower()
    ]
    if not candidates:
        return None

    by_name = {d["district"].lower(): d for d in candidates}
    close = difflib.get_close_matches(
        name.lower(), by_name.keys(), n=1, cutoff=_NAME_MATCH_CUTOFF
    )
    if not close:
        return None

    best = by_name[close[0]]
    return Place(
        district=best["district"], state=best["state"],
        precision="district", distance_km=0.0,
    )


@lru_cache(maxsize=1)
def _state_points() -> Dict[str, tuple]:
    """
    A representative point per state: the mean of its districts' points.

    Used only when an alert names a state and no district we recognise —
    "6 districts of Kerala" is a real SACHET area description. The resulting
    Place is marked `precision="state"` and carries no district, so nothing
    downstream can mistake a state-wide warning for a located one.
    """
    sums: Dict[str, List[float]] = {}
    for d in load_districts():
        acc = sums.setdefault(d["state"], [0.0, 0.0, 0.0])
        acc[0] += d["lat"]
        acc[1] += d["lng"]
        acc[2] += 1
    return {s: (a[0] / a[2], a[1] / a[2]) for s, a in sums.items() if a[2]}


def place_point(place: Optional[Place]) -> Optional[Tuple[float, float]]:
    """
    The (lat, lng) a resolved Place should be drawn at.

    A district Place gets its district's representative point; a state Place
    gets the mean of that state's districts. `None` when the Place is None or
    names something the gazetteer cannot point at, so a caller can leave the
    marker off rather than place it at (0, 0).
    """
    if place is None:
        return None

    if place.precision == "state" or not place.district:
        return _state_points().get(place.state)

    for d in load_districts():
        if d["district"] == place.district and d["state"] == place.state:
            return (d["lat"], d["lng"])
    return None


def state_place(state: str) -> Optional[Place]:
    """The whole-state fallback, named as such."""
    for known in _state_names():
        if known.lower() == state.strip().lower():
            if known in _state_points():
                return Place(
                    district=None, state=known,
                    precision="state", distance_km=0.0,
                )
    return None


def locate_area_description(area_desc: Optional[str]) -> List[Place]:
    """
    Every district named in a CAP alert's free-text area description.

    SACHET alerts are the reason this exists. NDMA answers 403 on the polygon
    endpoint, so not one stored alert carries a geometry, and their
    `district_codes` are LGD codes that this gazetteer does not speak. What
    they do carry is prose: "Chamarajanagara, Kodagu, Mysuru districts of
    Karnataka", or "Ganga, Bhagalpur, Bhagalpur, Bihar".

    Returns the matches in the order they appear, deduplicated. When no
    district resolves but the text names a state, returns a single
    `precision="state"` Place instead, because "6 districts of Kerala" is a
    real area description and Kerala is genuinely what it tells us.

    Returns an empty list when neither resolves. That is a real answer — an
    alert scoped to two mandals has no district-level location here, and is
    better left off a map than pinned somewhere plausible.
    """
    if not area_desc:
        return []

    text = area_desc.strip()
    if not text:
        return []

    # A state named anywhere in the description disambiguates the district
    # names that repeat across states, which is most of the hard cases.
    lowered = text.lower()
    state_hint = next((s for s in _state_names() if s.lower() in lowered), None)

    found: List[Place] = []
    seen: set = set()

    for chunk in _AREA_SPLIT_RE.split(text):
        words = [w for w in chunk.split() if w.lower() not in _AREA_NOISE_WORDS]
        if not words:
            continue

        # Try the whole chunk first ("North and Middle Andaman"), then shrink
        # from the end, so "Bhagalpur district" still resolves to Bhagalpur.
        for size in range(len(words), 0, -1):
            candidate = " ".join(words[:size])
            place = district_by_name(candidate, state_hint)
            if place is None:
                # A CAP sender's transliteration against our one spelling.
                place = _fuzzy_district(candidate, state_hint)
            if place is not None:
                key = (place.district, place.state)
                if key not in seen:
                    seen.add(key)
                    found.append(place)
                break

    if found:
        return found

    # Nothing district-level, but the state is still real information.
    if state_hint:
        whole_state = state_place(state_hint)
        if whole_state is not None:
            return [whole_state]

    return []


class OutOfIndiaBoundsError(ValueError):
    """Coordinates were supplied but fall outside India's bounding box."""

    def __init__(self, lat: float, lng: float):
        self.lat = lat
        self.lng = lng
        super().__init__(
            f"Coordinates ({lat}, {lng}) are outside India's bounds "
            f"(lat {INDIA_MIN_LAT}–{INDIA_MAX_LAT}, lng {INDIA_MIN_LNG}–{INDIA_MAX_LNG})"
        )


class LocationUnresolvedError(ValueError):
    """No usable coordinates, and no place in the hints the gazetteer knows."""

    def __init__(self, hint: str = ""):
        self.hint = hint
        super().__init__(
            "No coordinates were supplied and no known place was named"
            + (f" in {hint[:80]!r}" if hint else "")
        )


def is_within_india(lat: float, lng: float) -> bool:
    """Check if lat/lng is within Indian boundaries."""
    return (
        INDIA_MIN_LAT <= lat <= INDIA_MAX_LAT and
        INDIA_MIN_LNG <= lng <= INDIA_MAX_LNG
    )


def is_inverted(lat: float, lng: float) -> bool:
    """Detect inverted coordinates (lat/lng swapped)."""
    return (
        INDIA_MIN_LNG <= lat <= INDIA_MAX_LNG and
        INDIA_MIN_LAT <= lng <= INDIA_MAX_LAT
    )


def sanitize_coordinates(
    lat: Optional[float],
    lng: Optional[float],
    text_hint: Optional[str] = None,
    city_hint: Optional[str] = None,
) -> Tuple[float, float, str, str]:
    """
    Sanitizes coordinates, auto-corrects inverted pairs, or falls back to
    Gazetteer lookup from text/city hints.

    Coordinates that are present but outside India raise OutOfIndiaBoundsError.
    Snapping them to a gazetteer match or a fixed point in central India used
    to be possible, and with DBSCAN_MIN_SAMPLES=2 any two junk or GPS-glitched
    reports then clustered at that one point and manufactured a verified event
    in the middle of India.

    Missing coordinates resolve from the hints — there is nothing to reject,
    only a location to look up. When the hints name no known place either,
    LocationUnresolvedError: this function never answers with a placeholder.

    Returns: (lat, lng, city, state)
    """
    if lat is not None and lng is not None:
        try:
            f_lat = float(lat)
            f_lng = float(lng)
        except (ValueError, TypeError):
            f_lat = f_lng = None

        if f_lat is not None and f_lng is not None:
            # A swapped pair is a recoverable client bug, not junk: the swap
            # lands inside India, so it is corrected rather than rejected.
            if is_inverted(f_lat, f_lng):
                f_lat, f_lng = f_lng, f_lat

            if is_within_india(f_lat, f_lng):
                # Was `city_hint or "India Node"` — a placeholder that made
                # every GPS-bearing report nameless, which is most of them.
                # A report with coordinates is the one case where we can say
                # exactly where it is, so resolve it instead of labelling it.
                place = reverse_geocode(f_lat, f_lng)
                if place is not None:
                    return f_lat, f_lng, city_hint or place.district, place.state
                return f_lat, f_lng, city_hint or "", ""

            raise OutOfIndiaBoundsError(f_lat, f_lng)

    # Resolve from text or city hint
    search_str = f"{city_hint or ''} {text_hint or ''}".lower()
    for key, loc in INDIAN_GAZETTEER.items():
        if re.search(rf"\b{re.escape(key)}\b", search_str) or key in search_str:
            return loc["lat"], loc["lng"], loc["city"], loc["state"]

    raise LocationUnresolvedError(" ".join(h for h in (city_hint, text_hint) if h))


# ---------------------------------------------------------------------------
# Place from text — where a post or headline says it is (Phase 2 T6)
# ---------------------------------------------------------------------------
#
# Mastodon posts and news headlines almost never carry GPS, but they name
# places: "heavy rain in Ernakulam", "#MumbaiRains", "Waterlogging in Kochi".
# place_from_text() turns those names into a district, a state, or an honest
# "none", with a precision that says which:
#
#   district   exactly one district or city named, or several within 50 km of
#              each other (their centroid). Clusterable, like a GPS report.
#   state      only a state named, or districts too far apart to be one place.
#              Stored and filterable, but never clustered: a state is not a
#              location for a 5 km radius.
#   none       nothing recognised, or only names that could be several places.
#
# **It never guesses.** A name that belongs to more than one district
# (Aurangabad in Bihar and in Maharashtra; Bilaspur, Hamirpur, Pratapgarh,
# Balrampur, Bijapur) resolves only when the text also names the state, the
# same rule district_by_name() applies to SACHET's area descriptions (BUG-042).
# A post placed in the wrong district would corroborate a flood that is not
# there, which is worse than a post with no place at all.

CITY_ALIASES_CSV = DISTRICTS_CSV.parent / "india_city_aliases.csv"

# How far apart the districts one post names may be and still be one place.
TEXT_PLACE_SPREAD_KM = 50.0

# District names that are also ordinary words, names or rivers, and so appear
# in weather posts without meaning the district: "Punch" (Poonch), "Samba",
# "Anand", "Sagar", "Tapi" and "Gomati" (rivers), "Krishna", "Narmada",
# "Banda" and "Panna" (Hinglish words), "NTR" and "YSR" (people). Their aliases
# still work ("Poonch" resolves to Punch).
_GENERIC_DISTRICT_NAMES = {
    "punch", "samba", "gomati", "tapi", "pali", "mon", "una", "mau", "guna",
    "dang", "anand", "sagar", "dhar", "nuh", "ntr", "ysr", "banda", "mansa",
    "panna", "sidhi", "jalna", "senapati", "krishna", "narmada",
}

# State names as posts write them, beyond the gazetteer's own spelling.
_STATE_ALIASES: Dict[str, str] = {
    "orissa": "Odisha",
    "uttaranchal": "Uttarakhand",
    "chattisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh",
    "telengana": "Telangana",
    "west bengal": "West Bengal",
    "bengal": "West Bengal",
    "jammu & kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "kashmir": "Jammu and Kashmir",
    "andaman": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "tamilnadu": "Tamil Nadu",
    # Hindi
    "बिहार": "Bihar", "केरल": "Kerala", "उत्तर प्रदेश": "Uttar Pradesh",
    "महाराष्ट्र": "Maharashtra", "राजस्थान": "Rajasthan", "गुजरात": "Gujarat",
    "मध्य प्रदेश": "Madhya Pradesh", "तमिलनाडु": "Tamil Nadu",
    "पश्चिम बंगाल": "West Bengal", "बंगाल": "West Bengal", "ओडिशा": "Odisha",
    "असम": "Assam", "पंजाब": "Punjab", "हरियाणा": "Haryana",
    "उत्तराखंड": "Uttarakhand", "हिमाचल प्रदेश": "Himachal Pradesh",
    "हिमाचल": "Himachal Pradesh", "झारखंड": "Jharkhand",
    "छत्तीसगढ़": "Chhattisgarh", "तेलंगाना": "Telangana",
    "आंध्र प्रदेश": "Andhra Pradesh", "कर्नाटक": "Karnataka",
    "जम्मू-कश्मीर": "Jammu and Kashmir", "जम्मू कश्मीर": "Jammu and Kashmir",
    "गोवा": "Goa", "सिक्किम": "Sikkim", "मेघालय": "Meghalaya",
    "मणिपुर": "Manipur", "मिजोरम": "Mizoram", "नागालैंड": "Nagaland",
    "त्रिपुरा": "Tripura", "अरुणाचल प्रदेश": "Arunachal Pradesh",
    "लद्दाख": "Ladakh",
    # How Hindi headlines abbreviate: "यूपी में मानसून की री-एंट्री".
    "यूपी": "Uttar Pradesh", "एमपी": "Madhya Pradesh",
}

# Written in capitals as standalone tokens, and matched only so: "up" and "ap"
# are English words, "UP" and "AP" in a headline are states.
_STATE_ABBREVIATIONS: Dict[str, str] = {
    "UP": "Uttar Pradesh",
    "MP": "Madhya Pradesh",
    "HP": "Himachal Pradesh",
    "AP": "Andhra Pradesh",
    "TN": "Tamil Nadu",
    "WB": "West Bengal",
    "J&K": "Jammu and Kashmir",
    "JK": "Jammu and Kashmir",
}
_ABBREVIATION_RE = re.compile(
    r"(?<![\w&])(" + "|".join(re.escape(k) for k in sorted(_STATE_ABBREVIATIONS, key=len, reverse=True)) + r")(?![\w&])"
)

# Seas and bays named after land. "Low pressure over the Bay of Bengal" is not
# a post about West Bengal; these are removed before any name is matched.
_WATER_BODIES_RE = re.compile(
    r"\b(bay of bengal|arabian sea|indian ocean|andaman sea|gulf of mannar|"
    r"gulf of kutch|gulf of khambhat)\b",
    re.IGNORECASE,
)

# What a weather hashtag wraps around its place: #MumbaiRains, #KeralaWeather,
# #keralarain, #DelhiFloods. Stripped from the end, longest first.
_HASHTAG_SUFFIXES = sorted(
    {
        "rains", "rain", "rainfall", "weather", "floods", "flood", "flooding",
        "fog", "heatwave", "heat", "storm", "storms", "cyclone", "alert",
        "alerts", "monsoon", "update", "updates", "news", "waterlogging",
        "landslide", "landslides", "cloudburst", "thunderstorm", "lightning",
        "hailstorm", "duststorm", "coldwave", "winter", "traffic",
        # Not "now" or "live": #Lucknow would become "Luck".
    },
    key=len,
    reverse=True,
)
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_HASHTAG_IN_TEXT_RE = re.compile(r"#(\w+)")


def hashtag_words(tag: str) -> str:
    """
    A hashtag as the words it hides: "#MumbaiRains" → "Mumbai",
    "#keralarain" → "kerala", "#NewDelhiWeather" → "New Delhi".

    Camel case is split first; then weather words are stripped from the end,
    repeatedly, so "#DelhiRainAlert" loses both.
    """
    tag = (tag or "").lstrip("#").strip()
    if not tag:
        return ""
    words = _CAMEL_RE.sub(" ", tag).replace("_", " ").split()
    # Strip whole trailing words first ("Mumbai Rains")…
    while len(words) > 1 and words[-1].lower() in _HASHTAG_SUFFIXES:
        words.pop()
    # …then suffixes glued onto a lowercase tag ("keralarain").
    if len(words) == 1:
        word = words[0]
        changed = True
        while changed:
            changed = False
            for suffix in _HASHTAG_SUFFIXES:
                if word.lower().endswith(suffix) and len(word) > len(suffix) + 2:
                    word = word[: -len(suffix)]
                    changed = True
                    break
        words = [word]
    return " ".join(words)


@lru_cache(maxsize=1)
def _load_city_aliases() -> List[Dict[str, str]]:
    try:
        with CITY_ALIASES_CSV.open(newline="", encoding="utf-8") as handle:
            return [
                {"alias": r["alias"].strip(), "district": r["district"].strip(), "state": r["state"].strip()}
                for r in csv.DictReader(handle)
                if r.get("alias") and r.get("district")
            ]
    except (OSError, KeyError) as exc:
        logger.error(f"City alias table unreadable at {CITY_ALIASES_CSV} ({exc}); aliases off")
        return []


@lru_cache(maxsize=1)
def _place_names() -> Tuple[Dict[str, Dict[str, Any]], Any]:
    """
    Every name place_from_text recognises, lowercased, with what it means, and
    one regex that finds them all (longest name first, so "Navi Mumbai" wins
    over "Mumbai" and "West Bengal" over "Bengal").

    Each entry: {"districts": [(district, state), …], "state": state or None}.
    A name with more than one district candidate is ambiguous.
    """
    names: Dict[str, Dict[str, Any]] = {}

    def entry(key: str) -> Dict[str, Any]:
        return names.setdefault(key, {"districts": [], "state": None})

    for d in load_districts():
        key = d["district"].lower()
        if key in _GENERIC_DISTRICT_NAMES:
            continue
        pair = (d["district"], d["state"])
        if pair not in entry(key)["districts"]:
            entry(key)["districts"].append(pair)

    for a in _load_city_aliases():
        pair = (a["district"], a["state"])
        e = entry(a["alias"].lower())
        if pair not in e["districts"]:
            e["districts"].append(pair)

    for state in {d["state"] for d in load_districts()}:
        entry(state.lower())["state"] = state
    for alias, state in _STATE_ALIASES.items():
        entry(alias.lower())["state"] = state

    alternation = "|".join(re.escape(k) for k in sorted(names, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w&])({alternation})(?![\w&])", re.IGNORECASE)
    return names, pattern


def _district_point(district: str, state: str) -> Optional[Tuple[float, float]]:
    for d in load_districts():
        if d["district"] == district and d["state"] == state:
            return (d["lat"], d["lng"])
    return None


def place_from_text(text: Optional[str], hashtags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    {district, state, lat, lng, precision, matched} for a post or headline.

    `precision` is `district`, `state` or `none` (see the block above);
    `matched` lists the names that decided it, for the record. Pure and
    deterministic: the same text always gives the same place.
    """
    none = {"district": None, "state": None, "lat": None, "lng": None,
            "precision": "none", "matched": []}
    if not load_districts():
        return none

    names, pattern = _place_names()
    body = text or ""
    tags = list(hashtags or []) + _HASHTAG_IN_TEXT_RE.findall(body)
    segments = [_WATER_BODIES_RE.sub(" ", body)]
    segments += [hashtag_words(t) for t in tags]
    haystack = " | ".join(s for s in segments if s)

    district_mentions: List[Tuple[str, List[Tuple[str, str]]]] = []
    states: List[str] = []
    matched: List[str] = []

    for m in pattern.finditer(haystack):
        key = m.group(1).lower()
        info = names.get(key)
        if not info:
            continue
        matched.append(m.group(1))
        if info["districts"]:
            district_mentions.append((key, info["districts"]))
        if info["state"] and info["state"] not in states:
            states.append(info["state"])

    for m in _ABBREVIATION_RE.finditer(_WATER_BODIES_RE.sub(" ", body)):
        state = _STATE_ABBREVIATIONS[m.group(1)]
        matched.append(m.group(1))
        if state not in states:
            states.append(state)

    # Resolve each district mention; an ambiguous one needs a named state.
    resolved: List[Tuple[str, str]] = []
    for _key, candidates in district_mentions:
        pick: Optional[Tuple[str, str]] = None
        if len(candidates) == 1:
            pick = candidates[0]
        else:
            narrowed = [c for c in candidates if c[1] in states]
            if len(narrowed) == 1:
                pick = narrowed[0]
        if pick and pick not in resolved:
            resolved.append(pick)

    points = [(pair, _district_point(*pair)) for pair in resolved]
    points = [(pair, p) for pair, p in points if p is not None]

    if points:
        spread = max(
            (_haversine_km(a[1][0], a[1][1], b[1][0], b[1][1]) for a in points for b in points),
            default=0.0,
        )
        if spread <= TEXT_PLACE_SPREAD_KM:
            lat = sum(p[0] for _, p in points) / len(points)
            lng = sum(p[1] for _, p in points) / len(points)
            district, state = points[0][0]
            return {"district": district, "state": state, "lat": round(lat, 6),
                    "lng": round(lng, 6), "precision": "district", "matched": matched}
        # Too far apart to be one place: the state, if they share one.
        shared = {pair[1] for pair, _ in points}
        if len(shared) == 1:
            states = [shared.pop()]
        else:
            return {**none, "matched": matched}

    if len(states) == 1:
        point = _state_points().get(states[0])
        if point is not None:
            return {"district": None, "state": states[0], "lat": round(point[0], 6),
                    "lng": round(point[1], 6), "precision": "state", "matched": matched}

    return {**none, "matched": matched}
