"""
INDRA Platform — Hazard-specific severity: the content axis (Phase 3 T7)

An event's severity is `max(content_axis, corroboration_axis)`
(`pipeline._derive_severity`). The corroboration (count) axis is unchanged.
The **content axis now depends on the hazard's family**, so a 46 °C heatwave
and a knee-deep flood are each graded by their own measure:

| Family, measure                       | ADVISORY        | MODERATE         | HIGH                 | CRITICAL                 |
|---------------------------------------|-----------------|------------------|----------------------|--------------------------|
| water, `depth_cm`                     | < 20            | 20–59            | 60–119               | ≥ 120                    |
| water, `rain_mm` in 24 h              | < 64.5          | 64.5–115.5 heavy | 115.6–204.4 very heavy | ≥ 204.5 extremely heavy |
| thermal (heat), `temp_c`              | < 40            | 40–44.9          | 45–46.9 heatwave     | ≥ 47 severe heatwave     |
| thermal (cold), `temp_c`              | cold words only | ≤ 10             | ≤ 4 cold wave        | ≤ 2 severe cold wave     |
| visibility, `visibility_m`            | 500–999 shallow | 200–499 moderate | 50–199 dense         | < 50 very dense          |
| convective, `wind_kmh`                | < 39            | 39–61            | 62–88 gale           | ≥ 89 storm               |

Sources for the cuts:

* **Depth**: INDRA's operational cuts (20 cm stops a two-wheeler, 60 cm
  floats a small car, 120 cm is above an adult's waist), unchanged.
* **Rain**: IMD's 24-hour rainfall categories — heavy 64.5–115.5 mm, very heavy
  115.6–204.4 mm, extremely heavy ≥ 204.5 mm.
* **Heat**: IMD's heatwave criteria for the plains — a maximum of 40 °C or
  more is where a heatwave can be declared; 45 °C or more is a heatwave on the
  actual temperature, 47 °C or more a severe one.
* **Cold**: IMD's cold-wave criteria for the plains — a minimum of 10 °C or
  less is where a cold wave can be declared; 4 °C or less is a cold wave, 2 °C
  or less a severe one.
* **Fog**: IMD's fog classes by visibility — shallow 500–999 m, moderate
  200–499 m, dense 50–199 m, very dense under 50 m.
* **Wind**: the Beaufort scale in km/h — 39 is a strong breeze (force 6), 62
  a gale (force 8), 89 a strong gale into storm (force 10).

The measure is the worst any report in the cluster quotes: the deepest water,
the most rain, the hottest (or coldest) reading, the lowest visibility, the
strongest wind. The phrase it came from goes into the receipt.

**Impact words set a floor, whatever the measure says** — what happened to
people is a better grade than any number:

* HIGH: stranded, rescue, boats, heatstroke, hospitalised, trees uprooted,
  poles down; in fog, an accident or a pile-up.
* CRITICAL: drowned, died, death, dead, killed, house collapsed, roof blown
  off, "bijli girne se maut" / "बिजली गिरने से मौत".

A denied impact ("no deaths reported", "koi maut nahi") sets no floor.
"""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.models.enums import Severity
from app.services.hazard_tagger import fold
from app.services.hazards import family_of

ORDER = (Severity.ADVISORY, Severity.MODERATE, Severity.HIGH, Severity.CRITICAL)

DEPTH_CUTS_CM = (20, 60, 120)
RAIN_CUTS_MM = (64.5, 115.6, 204.5)
HEAT_CUTS_C = (40.0, 45.0, 47.0)
COLD_CUTS_C = (10.0, 4.0, 2.0)           # at or below
FOG_CUTS_M = (1000.0, 500.0, 200.0, 50.0)  # below 1000 is fog at all; see visibility_severity
WIND_CUTS_KMH = (39.0, 62.0, 89.0)

_HIGH_RE = re.compile(
    r"\bstranded\b|\brescu\w*|\bboats?\b|\bheat[\s-]?strokes?\b|\bsun[\s-]?strokes?\b|\bhospitali[sz]ed\b"
    r"|\btrees?\s+(?:were\s+|have\s+been\s+|got\s+)?uprooted\b|\buprooted\s+trees?\b"
    r"|\b(?:electric(?:ity)?\s+)?poles?\s+(?:are\s+|were\s+)?(?:down|uprooted)\b"
    r"|फंसे|बचाव|\bnaav\b|नाव|लू\s+लगने|अस्पताल\s+में\s+भर्ती|पेड\s+उखड"
)
_FOG_HIGH_RE = re.compile(r"\baccidents?\b|\bpile[\s-]?ups?\b|\bcollisions?\b|\bcrash(?:ed)?\b|हादसा|हादसे|दुर्घटना")
_CRITICAL_RE = re.compile(
    r"\bdrown(?:ed|ing|s)?\b|\bdied\b|\bdeaths?\b|\bdead\b|\bkilled\b|\bbodies\b"
    r"|\bhouses?\s+(?:has\s+|have\s+)?collapsed\b|\bcollapsed\s+houses?\b|\bbuilding\s+collapsed\b"
    r"|\broofs?\s+(?:was\s+|were\s+|got\s+)?blown\s+off\b|\bblew\s+(?:the\s+)?roofs?\s+off\b"
    r"|\bmaut\b|मौत|मृत्यु|मकान\s+ढह|घर\s+ढह|डूबने\s+से|डूबकर"
)
# "no deaths", "zero casualties", "koi maut nahi": a denied impact.
_DENIED_BEFORE_RE = re.compile(r"(?:\b(?:no|not|zero|without|koi)\s+(?:\S+\s+)?|कोई\s+)$")
_DENIED_AFTER_RE = re.compile(r"^\s*(?:\S+\s+)?(?:nahi|nahin|नहीं)\b")


def _grade(value: float, cuts: Tuple[float, float, float]) -> Severity:
    """At or above each cut raises the grade one step."""
    level = sum(1 for cut in cuts if value >= cut)
    return ORDER[level]


def depth_severity(depth_cm: Optional[float]) -> Severity:
    return Severity.ADVISORY if depth_cm is None else _grade(depth_cm, DEPTH_CUTS_CM)


def rain_severity(rain_mm: Optional[float]) -> Severity:
    return Severity.ADVISORY if rain_mm is None else _grade(rain_mm, RAIN_CUTS_MM)


def heat_severity(temp_c: Optional[float]) -> Severity:
    return Severity.ADVISORY if temp_c is None else _grade(temp_c, HEAT_CUTS_C)


def cold_severity(temp_c: Optional[float]) -> Severity:
    if temp_c is None:
        return Severity.ADVISORY
    return ORDER[sum(1 for cut in COLD_CUTS_C if temp_c <= cut)]


def visibility_severity(visibility_m: Optional[float]) -> Severity:
    """500–999 shallow, 200–499 moderate, 50–199 dense, < 50 very dense; ≥ 1000 is not fog."""
    if visibility_m is None or visibility_m >= FOG_CUTS_M[0]:
        return Severity.ADVISORY
    if visibility_m < FOG_CUTS_M[3]:
        return Severity.CRITICAL
    if visibility_m < FOG_CUTS_M[2]:
        return Severity.HIGH
    if visibility_m < FOG_CUTS_M[1]:
        return Severity.MODERATE
    return Severity.ADVISORY


def wind_severity(wind_kmh: Optional[float]) -> Severity:
    return Severity.ADVISORY if wind_kmh is None else _grade(wind_kmh, WIND_CUTS_KMH)


def _worst(metas: Sequence[Mapping[str, Any]], key: str, lowest: bool = False):
    """(value, phrase) of the most extreme reading any report quotes, or (None, None)."""
    found = [
        (m[key], (m.get("number_phrases") or {}).get(key))
        for m in metas if m.get(key) is not None and key not in (m.get("implausible") or [])
    ]
    if not found:
        return None, None
    return (min if lowest else max)(found, key=lambda f: f[0])


def content_axis(event_type: Optional[str], metas: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    The content axis for one event: {"severity", "axis", "value", "phrase"}.
    `metas` are extract_metadata outputs, one per non-duplicate report.

    UNCLASSIFIED has no measure of its own ("none"): only impact words and the
    count can grade it. An event with no type (the legacy callers) is graded as
    a flood, which is what every event was before Phase 3.
    """
    family = family_of(event_type) if event_type else "water"

    if family == "water":
        depth, depth_phrase = _worst(metas, "depth_cm")
        depth_basis = next(
            (m.get("depth_basis") for m in metas if m.get("depth_cm") is not None and m["depth_cm"] == depth),
            None,
        )
        rain, rain_phrase = _worst(metas, "rain_mm")
        by_depth = {"severity": depth_severity(depth), "axis": "water_depth", "value": depth,
                    "phrase": depth_basis}
        by_rain = {"severity": rain_severity(rain), "axis": "water_rain", "value": rain, "phrase": rain_phrase}
        # The worse of the two; with no depth quoted at all, the rain reading is
        # the measure the receipt shows, even when it grades ADVISORY.
        if rain is not None and (
            depth is None or ORDER.index(by_rain["severity"]) > ORDER.index(by_depth["severity"])
        ):
            return by_rain
        return by_depth

    if family == "thermal":
        if event_type == "COLD_WAVE":
            temp, phrase = _worst(metas, "temp_c", lowest=True)
            return {"severity": cold_severity(temp), "axis": "thermal_cold", "value": temp, "phrase": phrase}
        temp, phrase = _worst(metas, "temp_c")
        return {"severity": heat_severity(temp), "axis": "thermal_heat", "value": temp, "phrase": phrase}

    if family == "visibility":
        vis, phrase = _worst(metas, "visibility_m", lowest=True)
        return {"severity": visibility_severity(vis), "axis": "visibility", "value": vis, "phrase": phrase}

    if family == "convective":
        wind, phrase = _worst(metas, "wind_kmh")
        return {"severity": wind_severity(wind), "axis": "convective_wind", "value": wind, "phrase": phrase}

    return {"severity": Severity.ADVISORY, "axis": "none", "value": None, "phrase": None}


def _undenied(regex: "re.Pattern[str]", text: str) -> Optional[str]:
    for m in regex.finditer(text):
        before = text[max(0, m.start() - 24):m.start()]
        after = text[m.end():m.end() + 16]
        if _DENIED_BEFORE_RE.search(before) or _DENIED_AFTER_RE.match(after):
            continue
        return m.group(0)
    return None


def impact_floor(texts: Sequence[str], event_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """The highest floor any report's impact words set: {"severity", "phrase"}, or None."""
    fog = (family_of(event_type) if event_type else None) == "visibility"
    high: Optional[str] = None
    for raw in texts:
        text = fold(raw)
        critical = _undenied(_CRITICAL_RE, text)
        if critical:
            return {"severity": Severity.CRITICAL, "phrase": critical}
        if high is None:
            high = _undenied(_HIGH_RE, text) or (_undenied(_FOG_HIGH_RE, text) if fog else None)
    return {"severity": Severity.HIGH, "phrase": high} if high else None


def highest(*levels: Severity) -> Severity:
    return max(levels, key=ORDER.index)


def list_metas(texts: Sequence[str]) -> List[Dict[str, Any]]:
    """extract_metadata over each text: the input content_axis reads."""
    from app.services.text_processing import extract_metadata

    return [extract_metadata(t or "") for t in texts]
