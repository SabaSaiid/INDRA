"""
INDRA Platform — The hazard taxonomy

One table describes every event type INDRA can store: what to call it, which
family it belongs to, which of two overlapping reports wins, and what a later
phase will measure to corroborate it. Everything that needs one of those facts
reads it from here, so adding a hazard means adding one row, not finding every
dictionary that happened to list the old ones.

**Families decide what may cluster together** (Phase 3). A flood report and a
rain report describe the same wet afternoon and belong in one event; a flood
report and a fog report do not, however close they are. Each family carries the
clustering radius and time window that suit its physics: water pools locally
and drains in hours, a heatwave covers a district for a day.

**Precedence breaks ties, and the impact outranks its cause** (lower wins). When
reports in one cluster disagree, the event is named for the thing that hurts
people: a flood beats the rain that caused it, a landslide beats the rain too.
Two hazards with the same precedence are ordered by their place in the table
below, where the more specific comes first (Phase 3): lightning and hail before
the thunderstorm that brings them, a cloudburst or a storm surge before the
flood it causes. So "bijli giri, thunder and heavy rain" is a lightning report,
and the answer never depends on the order a caller listed the types in.

**`measured_by` says, in words, what corroborates each hazard** (IMD airport
METAR, Open-Meteo, SACHET warnings). Since Phase 4 the measurements themselves
are read in `services/evidence.py` (the weather, per hazard) and
`services/official_warnings.py` (the warnings); this column stays the one-line
summary a reviewer can scan, and nothing computes from it.

**Labels keep the strings the dashboard already keys on.** The map's icon table
(`frontend/src/components/client-only/GlobeEventMap.tsx`) and the distribution
chart's colours match on the display label — "Flood", "Thunderstorm", "Strong
Winds", "Fog", "Heavy Rainfall" — so those are the labels here, and the list
endpoint also sends the raw `event_type` for the frontend to key on instead.
`URBAN_FLOOD` therefore stays "Flood", as it has been since Day 1.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Union

from app.models.enums import EventType


@dataclass(frozen=True)
class Family:
    """Which reports may cluster together, and over what distance and time."""

    name: str
    eps_km: float       # clustering radius
    window_hours: int   # how far apart in time two reports can be and still cluster


@dataclass(frozen=True)
class Hazard:
    type: EventType
    label: str
    family: Optional[str]   # None only for UNCLASSIFIED, which clusters with nothing
    precedence: int         # lower wins a tie; see the module docstring
    measured_by: str        # what Phase 4 corroborates it with
    gradient: str           # the event card's thumbnail
    color: str              # the distribution chart's slice


FAMILIES: Dict[str, Family] = {
    "water": Family("water", eps_km=5.0, window_hours=6),
    "convective": Family("convective", eps_km=10.0, window_hours=3),
    "thermal": Family("thermal", eps_km=25.0, window_hours=24),
    "visibility": Family("visibility", eps_km=15.0, window_hours=12),
}

# Used when a type is not in the table: the same grey the list endpoint has
# always drawn for an unknown type.
DEFAULT_GRADIENT = "linear-gradient(135deg, #64748B, #334155)"
DEFAULT_COLOR = "#94A3B8"

_HAZARDS = (
    # ── water ──────────────────────────────────────────────────────────────
    # The four flood types INDRA started with keep their thumbnails, and the
    # chart colours match the ones the dashboard already shows.
    # Within precedence 1 the specific cause comes first: a report naming a
    # cloudburst and the flood it caused is a cloudburst report.
    Hazard(EventType.CLOUDBURST, "Cloudburst", "water", 1,
           "hourly rainfall of 100 mm/h or more",
           "linear-gradient(135deg, #3B82F6, #6366F1)", "#0EA5E9"),
    Hazard(EventType.CYCLONE_INUNDATION, "Storm surge", "water", 1,
           "official warning",
           "linear-gradient(135deg, #EF4444, #C2410C)", "#0891B2"),
    Hazard(EventType.URBAN_FLOOD, "Flood", "water", 1,
           "24 h rainfall; METAR rain codes",
           "linear-gradient(135deg, #2563EB, #1E3A8A)", "#F59E0B"),
    Hazard(EventType.RIVER_BREACH, "River flood", "water", 2,
           "24 h rainfall",
           "linear-gradient(135deg, #F59E0B, #92400E)", "#D97706"),
    Hazard(EventType.LANDSLIDE, "Landslide", "water", 3,
           "24 h rainfall; official warning",
           "linear-gradient(135deg, #A16207, #451A03)", "#E11D48"),
    Hazard(EventType.RAINFALL, "Heavy Rainfall", "water", 9,
           "24 h rainfall",
           "linear-gradient(135deg, #60A5FA, #1D4ED8)", "#3B82F6"),
    # ── convective ─────────────────────────────────────────────────────────
    Hazard(EventType.CYCLONE, "Cyclone", "convective", 3,
           "official warning; gusts",
           "linear-gradient(135deg, #7C3AED, #1E1B4B)", "#2563EB"),
    Hazard(EventType.DUST_STORM, "Dust storm", "convective", 4,
           "METAR DS/DU; dust µg/m³; visibility",
           "linear-gradient(135deg, #D97706, #78350F)", "#CA8A04"),
    # Within precedence 5, lightning and hail (what injures people and crops)
    # come before the thunderstorm that brings them.
    Hazard(EventType.LIGHTNING, "Lightning", "convective", 5,
           "as thunderstorm",
           "linear-gradient(135deg, #FACC15, #6D28D9)", "#EAB308"),
    Hazard(EventType.HAILSTORM, "Hailstorm", "convective", 5,
           "METAR GR/GS; weather codes 96 and 99",
           "linear-gradient(135deg, #7DD3FC, #0369A1)", "#06B6D4"),
    Hazard(EventType.THUNDERSTORM, "Thunderstorm", "convective", 5,
           "METAR TS and CB clouds; weather codes 95–99; CAPE",
           "linear-gradient(135deg, #6D28D9, #312E81)", "#8B5CF6"),
    Hazard(EventType.STRONG_WIND, "Strong Winds", "convective", 6,
           "METAR gusts or SQ; model gusts",
           "linear-gradient(135deg, #0EA5E9, #1E40AF)", "#2563EB"),
    # ── thermal ────────────────────────────────────────────────────────────
    Hazard(EventType.HEATWAVE, "Heatwave", "thermal", 7,
           "METAR temperature; model maximum temperature",
           "linear-gradient(135deg, #F97316, #B91C1C)", "#EF4444"),
    Hazard(EventType.COLD_WAVE, "Cold wave", "thermal", 7,
           "model minimum temperature",
           "linear-gradient(135deg, #A5F3FC, #1E3A8A)", "#38BDF8"),
    # ── visibility ─────────────────────────────────────────────────────────
    Hazard(EventType.FOG, "Fog", "visibility", 8,
           "METAR FG and visibility; model visibility",
           "linear-gradient(135deg, #94A3B8, #475569)", "#64748B"),
    # ── none ───────────────────────────────────────────────────────────────
    # Nothing identified the hazard. It clusters with nothing, so an unknown
    # report is never quietly counted as corroboration for a flood.
    Hazard(EventType.UNCLASSIFIED, "Unclassified", None, 99,
           "—",
           DEFAULT_GRADIENT, DEFAULT_COLOR),
)

HAZARDS: Dict[str, Hazard] = {h.type.value: h for h in _HAZARDS}

# A type's place in the table: the tie-break between equal precedences.
_TABLE_ORDER: Dict[str, int] = {t: i for i, t in enumerate(HAZARDS)}

# The two maps the events API has always used, now derived rather than copied.
EVENT_TYPE_LABELS: Dict[str, str] = {t: h.label for t, h in HAZARDS.items()}
IMAGE_GRADIENTS: Dict[str, str] = {t: h.gradient for t, h in HAZARDS.items()}


TypeLike = Union[EventType, str, None]


def _key(event_type: TypeLike) -> Optional[str]:
    if event_type is None:
        return None
    return event_type.value if isinstance(event_type, EventType) else str(event_type)


def hazard_of(event_type: TypeLike) -> Optional[Hazard]:
    return HAZARDS.get(_key(event_type))


def family_of(event_type: TypeLike) -> Optional[str]:
    """The type's family name, or None for UNCLASSIFIED and unknown types."""
    hazard = hazard_of(event_type)
    return hazard.family if hazard else None


def label_of(event_type: TypeLike) -> str:
    """The display label; an unknown type is shown as itself, never as blank."""
    hazard = hazard_of(event_type)
    return hazard.label if hazard else (_key(event_type) or "")


def gradient_of(event_type: TypeLike) -> str:
    hazard = hazard_of(event_type)
    return hazard.gradient if hazard else DEFAULT_GRADIENT


def color_of(event_type: TypeLike) -> str:
    hazard = hazard_of(event_type)
    return hazard.color if hazard else DEFAULT_COLOR


def precedence_key(event_type: TypeLike) -> tuple:
    """
    Sort key: precedence, then the type's place in the table. Unknown types
    sort after every known one, among themselves by name.
    """
    key = _key(event_type) or ""
    if key in HAZARDS:
        return (HAZARDS[key].precedence, _TABLE_ORDER[key], "")
    return (1000, 1000, key)


def by_precedence(event_types: Iterable[TypeLike]) -> List[str]:
    """Type values ordered so the one an event should be named for comes first."""
    keys = [_key(t) for t in event_types if _key(t)]
    return sorted(keys, key=precedence_key)


def types_in_family(family: str) -> List[str]:
    """Every type value in a family, in precedence order. Empty for an unknown family."""
    return by_precedence(t for t, h in HAZARDS.items() if h.family == family)
