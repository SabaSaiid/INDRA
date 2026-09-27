"""
INDRA Platform — Weather evidence for every hazard (Phase 4 T1–T3)

Until Phase 4 the Weather Station Corroboration factor read one number, 24 h
rainfall, and was `offline` for every hazard rainfall cannot speak to. This
module reads **each hazard's own variable**, from an airport's observation when
one is near and from Open-Meteo's model otherwise, and says when the weather
**affirmatively contradicts** a claim.

Everything here is pure: values in, an `Evidence` out, no I/O and no clock (the
caller passes the window, which it builds from `services/clock.py`). The same
inputs always give the same evidence, which is what the receipt's determinism
tests rely on.

    Evidence(score, state, variable, value, window, source, contradiction, reason)

* `score` is None and `state` "offline" when there is nothing to read. A 0.0
  with state "computed" is a measurement, and costs the factor its weight.
* `source` is `airport_metar`, `open_meteo_model` or `none`.
* `reason` is the evidence line the receipt prints.
* `detail` keeps the numbers behind it, for the contradiction rules and for a
  reader who wants to check the line.

The window
----------
Evidence is read over **the cluster's observed time span ± 3 h**, never past
now (an hour after now is a forecast): a fog event at 06:00 is checked against
visibility from 03:00 to 09:00. Two exceptions, both written into
`evidence_window()`:

* **the rain and flood family keeps the 24 h accumulation**, as the IMD curve
  has always read it;
* **heat and cold read at least the last 24 h** (a departure from the plan,
  which gives them ± 3 h). IMD grades a heatwave on the day's maximum. A
  heatwave reported at 22:00 checked only from 19:00 would read the evening,
  score it low and, worse, "contradict" a real heatwave with a night-time
  reading. The last 24 h always contains the afternoon.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.hazards import family_of
from app.services.weather import HourlySeries, rainfall_to_score

IST = timezone(timedelta(hours=5, minutes=30))

WINDOW_PAD = timedelta(hours=3)
DAY = timedelta(hours=24)

# Sources, in the receipt's own words.
AIRPORT_METAR = "airport_metar"
OPEN_METEO_MODEL = "open_meteo_model"
NO_SOURCE = "none"


@dataclass(frozen=True)
class Evidence:
    score: Optional[float]
    state: str                      # "computed" | "offline"
    variable: Optional[str] = None  # "maximum temperature_2m", "visibility", …
    value: Optional[float] = None
    window: Optional[str] = None    # "03:00–09:00 UTC (08:30–14:30 IST)"
    source: str = NO_SOURCE
    contradiction: bool = False
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def online(self) -> bool:
        return self.score is not None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "state": self.state,
            "variable": self.variable,
            "value": self.value,
            "window": self.window,
            "source": self.source,
            "contradiction": self.contradiction,
            "reason": self.reason,
            "detail": self.detail,
        }


def offline(reason: str, *, variable: Optional[str] = None, window: Optional[str] = None) -> Evidence:
    return Evidence(None, "offline", variable=variable, window=window, reason=reason)


# ── The window ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    rule: str

    def label(self) -> str:
        """'03:00–09:00 UTC (08:30–14:30 IST)', with dates when it crosses a day."""

        def fmt(a: datetime, b: datetime) -> str:
            same_day = a.date() == b.date()
            left = a.strftime("%H:%M") if same_day else a.strftime("%d %b %H:%M")
            right = b.strftime("%H:%M") if same_day else b.strftime("%d %b %H:%M")
            return f"{left}–{right}"

        return (
            f"{fmt(self.start, self.end)} UTC "
            f"({fmt(self.start.astimezone(IST), self.end.astimezone(IST))} IST)"
        )

    def contains(self, at: Optional[datetime]) -> bool:
        return at is not None and self.start <= _utc(at) <= self.end

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "rule": self.rule,
            "label": self.label(),
        }


def _utc(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


# The types whose evidence is 24 h rainfall on the IMD curve. CLOUDBURST reads
# its peak hour over the ± 3 h window, with this 24 h figure as its floor.
RAIN_24H_TYPES = frozenset({
    "URBAN_FLOOD", "RAINFALL", "RIVER_BREACH", "LANDSLIDE", "CYCLONE_INUNDATION",
})


def evidence_window(
    event_type: Optional[str],
    span_start: datetime,
    span_end: datetime,
    now: datetime,
) -> Window:
    """
    Where to read the evidence for an event observed from span_start to
    span_end. See the module docstring; never ends after `now`.
    """
    span_start, span_end, now = _utc(span_start), _utc(span_end), _utc(now)
    if span_end < span_start:
        span_start, span_end = span_end, span_start
    end = min(now, span_end + WINDOW_PAD)
    etype = event_type or "URBAN_FLOOD"
    if etype in RAIN_24H_TYPES:
        return Window(end - DAY, end, "24 h accumulation ending at the evidence time")
    if family_of(etype) == "thermal":
        start = min(span_start - WINDOW_PAD, end - DAY)
        return Window(start, end, "the last 24 h at least, so the day's extreme is inside it")
    start = span_start - WINDOW_PAD
    if start > end:
        start = end - WINDOW_PAD
    return Window(start, end, "the observed span ± 3 h")


# ── The published scales ───────────────────────────────────────────────────────
# Each is a step table: the first row the value reaches gives the score.

def _step_at_least(value: float, table: Sequence[Tuple[float, float]], default: float) -> float:
    for threshold, score in table:
        if value >= threshold:
            return score
    return default


def _step_at_most(value: float, table: Sequence[Tuple[float, float]], default: float) -> float:
    for threshold, score in table:
        if value <= threshold:
            return score
    return default


def _step_below(value: float, table: Sequence[Tuple[float, float]], default: float) -> float:
    for threshold, score in table:
        if value < threshold:
            return score
    return default


# HEATWAVE, maximum temperature (°C). IMD declares a heatwave on the plains at
# 40 °C with a departure from normal, and outright at 45 °C; 47 °C is a severe
# heatwave day anywhere in India. The table is INDRA's scoring of those cuts.
HEAT_PLAINS = ((47.0, 1.0), (45.0, 0.9), (42.0, 0.6), (40.0, 0.4))
HEAT_DEFAULT = 0.1
# IMD's hill criterion is 30 °C (with a departure of 4.5 °C), 10 °C below the
# plains' 40 °C. Above HILL_ELEVATION_M the plains table is shifted down by
# that 10 °C, so 30 °C in the hills scores as 40 °C does on the plains.
HILL_ELEVATION_M = 1000.0
HILL_SHIFT_C = 10.0

# COLD_WAVE, minimum temperature (°C): IMD's plains cold wave is ≤ 10 °C with
# a departure, and ≤ 4 °C outright; ≤ 2 °C is a severe cold wave.
COLD = ((2.0, 1.0), (4.0, 0.8), (7.0, 0.5), (10.0, 0.3))
COLD_DEFAULT = 0.1

# FOG, minimum visibility (m): IMD's dense fog bands, < 50 m very dense,
# < 200 m dense, < 500 m moderate, < 1,000 m shallow.
FOG = ((50.0, 1.0), (200.0, 0.85), (500.0, 0.6), (1000.0, 0.4))

# STRONG_WIND, maximum gust (km/h): Beaufort 10 (storm, 89), 8 (gale, 62),
# 7 (near gale, 50) and 6 (strong breeze, 39).
GUST = ((89.0, 1.0), (62.0, 0.8), (50.0, 0.6), (39.0, 0.4))

# CLOUDBURST, the peak hour (mm/h). IMD defines a cloudburst as 100 mm or more
# in an hour over a small area.
CLOUDBURST_PEAK = ((100.0, 1.0), (50.0, 0.6), (20.0, 0.3))

# DUST_STORM, dust (µg/m³). These are INDRA's own published thresholds for a
# **model estimate** (CAMS via Open-Meteo): no agency grades dust storms on it.
DUST = ((1000.0, 1.0), (500.0, 0.7), (200.0, 0.4))
DUST_GUST_BONUS_KMH = 40.0
DUST_GUST_BONUS = 0.1

# WMO weather codes Open-Meteo reports: 95 thunderstorm, 96 and 99
# thunderstorm with hail, 80–82 rain showers.
THUNDER_CODES = frozenset({95, 96, 99})
HAIL_CODES = frozenset({96, 99})
SHOWER_CODES = frozenset({80, 81, 82})
THUNDER_CAPE_WITH_SHOWERS = 1000.0
THUNDER_CAPE_ALONE = 500.0

# CYCLONE, CYCLONE_INUNDATION and LANDSLIDE: gusts and rain are partial
# evidence, and the official warning decides (T4). Their weather score is
# capped here so the weather alone never corroborates one.
PARTIAL_EVIDENCE_CAP = 0.5
PARTIAL_TYPES = frozenset({"CYCLONE", "CYCLONE_INUNDATION", "LANDSLIDE"})


def heat_score(max_c: float, hill: bool = False) -> float:
    shift = HILL_SHIFT_C if hill else 0.0
    return _step_at_least(max_c, tuple((t - shift, s) for t, s in HEAT_PLAINS), HEAT_DEFAULT)


def cold_score(min_c: float) -> float:
    return _step_at_most(min_c, COLD, COLD_DEFAULT)


def visibility_score(min_m: float) -> float:
    return _step_below(min_m, FOG, 0.0)


def gust_score(max_kmh: float) -> float:
    return _step_at_least(max_kmh, GUST, 0.0)


def cloudburst_peak_score(peak_mm_h: float) -> float:
    return _step_at_least(peak_mm_h, CLOUDBURST_PEAK, 0.0)


def dust_score(dust_ugm3: float, max_gust_kmh: Optional[float]) -> float:
    score = _step_at_least(dust_ugm3, DUST, 0.0)
    if max_gust_kmh is not None and max_gust_kmh >= DUST_GUST_BONUS_KMH:
        score += DUST_GUST_BONUS
    return round(min(1.0, score), 4)


def thunder_score(codes: Iterable[int], max_cape: Optional[float]) -> float:
    codes = set(codes)
    if codes & THUNDER_CODES:
        return 1.0
    if codes & SHOWER_CODES and max_cape is not None and max_cape >= THUNDER_CAPE_WITH_SHOWERS:
        return 0.6
    if max_cape is not None and max_cape >= THUNDER_CAPE_ALONE:
        return 0.3
    return 0.0


def hail_score(codes: Iterable[int]) -> float:
    codes = set(codes)
    if codes & HAIL_CODES:
        return 1.0
    if 95 in codes:
        return 0.5
    return 0.0


def is_hill(elevation_m: Optional[float]) -> bool:
    return elevation_m is not None and elevation_m > HILL_ELEVATION_M


# ── Model evidence (T1) ────────────────────────────────────────────────────────

WMO_NAMES = {
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}

MODEL_UNAVAILABLE = "Open-Meteo unavailable (timeout or error), so this evidence is offline"


def _hhmm(at: datetime) -> str:
    return _utc(at).strftime("%H:%M UTC")


def _extreme(
    series: Optional[HourlySeries], variable: str, window: Window, lowest: bool = False
) -> Optional[Tuple[datetime, float]]:
    if series is None:
        return None
    points = series.between(variable, window.start, window.end)
    if not points:
        return None
    # Ties go to the earliest hour, so the line is the same on every run.
    if lowest:
        return min(points, key=lambda p: (p[1], p[0].timestamp()))
    return max(points, key=lambda p: (p[1], -p[0].timestamp()))


def model_facts(
    series: Optional[HourlySeries], air: Optional[HourlySeries], window: Window
) -> Dict[str, Any]:
    """Every number the model gives over the window, whatever the hazard."""
    facts: Dict[str, Any] = {"available": series is not None, "air_available": air is not None}
    if series is not None:
        facts["elevation_m"] = series.elevation_m
        facts["hill"] = is_hill(series.elevation_m)
        for key, variable, lowest in (
            ("max_temp_c", "temperature_2m", False),
            ("min_temp_c", "temperature_2m", True),
            ("min_visibility_m", "visibility", True),
            ("max_gust_kmh", "wind_gusts_10m", False),
            ("max_wind_kmh", "wind_speed_10m", False),
            ("max_cape", "cape", False),
            ("peak_hourly_mm", "precipitation", False),
        ):
            hit = _extreme(series, variable, window, lowest)
            facts[key] = round(hit[1], 1) if hit else None
            facts[key + "_at"] = hit[0].isoformat() if hit else None
        codes = sorted({int(v) for _, v in series.between("weather_code", window.start, window.end)})
        facts["codes"] = codes
        facts["max_code"] = max(codes) if codes else None
        facts["code_at"] = {}
        for t, v in series.between("weather_code", window.start, window.end):
            facts["code_at"].setdefault(str(int(v)), t.isoformat())
    if air is not None:
        hit = _extreme(air, "dust", window)
        facts["max_dust"] = round(hit[1], 1) if hit else None
        facts["max_dust_at"] = hit[0].isoformat() if hit else None
    return facts


def _rain_line(rainfall_mm: float, origin: Optional[str]) -> str:
    # The pre-Phase-4 wording, kept word for word: every flood receipt and its
    # tests read it.
    where = (
        "polled station reading" if origin == "station_reading"
        else "Open-Meteo modelled precipitation"
    )
    return f"{rainfall_mm:.1f} mm rainfall in past 24 h ({where})"


def model_evidence(
    event_type: Optional[str],
    window: Window,
    series: Optional[HourlySeries],
    *,
    air: Optional[HourlySeries] = None,
    rainfall_mm: Optional[float] = None,
    rainfall_origin: Optional[str] = None,
) -> Evidence:
    """
    What Open-Meteo says about this hazard over the window. `rainfall_mm` is the
    24 h accumulation the rain family has always read (a stored reading or its
    own request, pipeline._weather_for_cluster), passed in so its path and its
    receipts stay exactly as they were.
    """
    etype = event_type or "URBAN_FLOOD"
    label = window.label()
    facts = model_facts(series, air, window)
    facts["rain_24h_mm"] = rainfall_mm
    common = {"window": label, "source": OPEN_METEO_MODEL, "detail": facts}

    if etype == "UNCLASSIFIED":
        return offline("no hazard type to check the weather against", window=label)

    rain_score = rainfall_to_score(rainfall_mm) if rainfall_mm is not None else None

    if etype in ("URBAN_FLOOD", "RAINFALL", "RIVER_BREACH"):
        if rain_score is None:
            return offline(MODEL_UNAVAILABLE, variable="24 h precipitation", window=label)
        return Evidence(rain_score, "computed", "24 h precipitation", rainfall_mm,
                        reason=_rain_line(rainfall_mm, rainfall_origin), **common)

    if etype == "CLOUDBURST":
        peak = facts.get("peak_hourly_mm")
        peak_score = cloudburst_peak_score(peak) if peak is not None else None
        scores = [s for s in (peak_score, rain_score) if s is not None]
        if not scores:
            return offline(MODEL_UNAVAILABLE, variable="maximum hourly precipitation", window=label)
        parts = []
        if peak is not None:
            parts.append(f"Open-Meteo model: peak {peak:.0f} mm/h in {label}")
        if rainfall_mm is not None:
            parts.append(_rain_line(rainfall_mm, rainfall_origin) + " as the floor")
        return Evidence(max(scores), "computed", "maximum hourly precipitation",
                        peak if peak is not None else rainfall_mm, reason="; ".join(parts), **common)

    if etype in PARTIAL_TYPES:
        gust = facts.get("max_gust_kmh")
        candidates = []
        parts = []
        if etype != "LANDSLIDE" and gust is not None:
            candidates.append(gust_score(gust))
            parts.append(f"Open-Meteo model: gusts to {gust:.0f} km/h in {label}")
        if rain_score is not None:
            candidates.append(rain_score)
            parts.append(_rain_line(rainfall_mm, rainfall_origin))
        if not candidates:
            return offline(MODEL_UNAVAILABLE, variable="gusts and rain", window=label)
        score = min(PARTIAL_EVIDENCE_CAP, max(candidates))
        parts.append(
            f"partial evidence, capped at {PARTIAL_EVIDENCE_CAP}: the official warning decides"
        )
        return Evidence(score, "computed", "gusts and rain (partial)", gust if gust is not None else rainfall_mm,
                        reason="; ".join(parts), **common)

    if series is None and etype != "DUST_STORM":
        return offline(MODEL_UNAVAILABLE, window=label)

    if etype == "HEATWAVE":
        value = facts.get("max_temp_c")
        if value is None:
            return offline("Open-Meteo returned no temperature in the window", window=label)
        hill = facts.get("hill", False)
        threshold = (
            f"hill threshold, grid elevation {facts['elevation_m']:,.0f} m" if hill else "plains threshold"
        )
        return Evidence(heat_score(value, hill), "computed", "maximum temperature_2m", value,
                        reason=(f"Open-Meteo model: maximum {value:.1f} °C at "
                                f"{_hhmm(datetime.fromisoformat(facts['max_temp_c_at']))} in {label} ({threshold})"),
                        **common)

    if etype == "COLD_WAVE":
        value = facts.get("min_temp_c")
        if value is None:
            return offline("Open-Meteo returned no temperature in the window", window=label)
        return Evidence(cold_score(value), "computed", "minimum temperature_2m", value,
                        reason=(f"Open-Meteo model: minimum {value:.1f} °C at "
                                f"{_hhmm(datetime.fromisoformat(facts['min_temp_c_at']))} in {label}"),
                        **common)

    if etype == "FOG":
        value = facts.get("min_visibility_m")
        if value is None:
            return offline("Open-Meteo returned no visibility in the window", window=label)
        return Evidence(visibility_score(value), "computed", "minimum visibility", value,
                        reason=(f"Open-Meteo model: minimum visibility {value:,.0f} m at "
                                f"{_hhmm(datetime.fromisoformat(facts['min_visibility_m_at']))} in {label}"),
                        **common)

    if etype == "STRONG_WIND":
        value = facts.get("max_gust_kmh")
        variable = "maximum wind_gusts_10m"
        if value is None:
            value, variable = facts.get("max_wind_kmh"), "maximum wind_speed_10m"
        if value is None:
            return offline("Open-Meteo returned no wind in the window", window=label)
        return Evidence(gust_score(value), "computed", variable, value,
                        reason=f"Open-Meteo model: gusts to {value:.0f} km/h in {label}", **common)

    if etype in ("THUNDERSTORM", "LIGHTNING", "HAILSTORM"):
        codes = facts.get("codes") or []
        cape = facts.get("max_cape")
        if not codes and cape is None:
            return offline("Open-Meteo returned no weather code or CAPE in the window", window=label)
        score = hail_score(codes) if etype == "HAILSTORM" else thunder_score(codes, cape)
        worst = max(codes) if codes else None
        parts = []
        if worst is not None:
            name = WMO_NAMES.get(worst)
            at = facts["code_at"].get(str(worst))
            parts.append(
                f"Open-Meteo model: weather code {worst}"
                + (f" ({name})" if name else "")
                + (f" at {_hhmm(datetime.fromisoformat(at))}" if at else "")
            )
        if cape is not None:
            parts.append(f"CAPE up to {cape:,.0f} J/kg")
        return Evidence(score, "computed", "weather_code and cape", worst,
                        reason="; ".join(parts) + f" in {label}", **common)

    if etype == "DUST_STORM":
        dust = facts.get("max_dust")
        if dust is None:
            return offline("the Open-Meteo dust estimate is unavailable, so this evidence is offline",
                           window=label)
        gust = facts.get("max_gust_kmh")
        line = f"CAMS model estimate via Open-Meteo: dust up to {dust:,.0f} µg/m³"
        if gust is not None:
            line += f"; gusts to {gust:.0f} km/h"
        return Evidence(dust_score(dust, gust), "computed", "dust (model estimate)", dust,
                        reason=line + f" in {label}", **common)

    return offline(f"no weather evidence is defined for {etype}", window=label)
