"""
INDRA Platform — METAR parsing (layer 1, Phase 2 T3)

A METAR is the international format for an airport's routine weather
observation, sent every half hour (a SPECI between routine reports when
something changes). At India's civil airports the observers are IMD's
aerodrome meteorological offices. NOAA's Aviation Weather Center (AWC)
republishes every METAR in the world, and its bulk cache file is where
`workers/metar_poller.py` reads them.

This module is pure: text in, numbers out, no I/O and no clock. The raw report
is the source of truth; AWC's CSV columns are only a fallback for a field the
raw text does not carry.

    METAR VABB 101130Z 24012KT 3000 +TSRA FEW015CB SCT020 BKN080 26/24 Q1004 NOSIG
          │    │       │       │    │     │                      │     │     └ trend: stop here
          │    │       │       │    │     └ cloud groups; CB/TCU = convective
          │    │       │       │    └ present weather
          │    │       │       └ visibility, metres (9999 = 10 km or more)
          │    │       └ wind: 240°, 12 kt (G = gusts)
          │    └ day 10, 11:30 UTC
          └ station (ICAO)
                                                       temperature/dewpoint °C (M = minus)

**Only the observation is read.** Everything from the first trend or remark
group (NOSIG, BECMG, TEMPO, RMK) on is a forecast or a note, not what the
observer saw: `… BECMG 5000 HZ` says haze is expected, and must not be stored
as present weather.

Present weather is normalised into a list, one entry per descriptor and per
phenomenon, with intensity carried on the phenomenon it qualifies
(precipitation, DS, SS, FC; never mist, haze, fog or smoke):

    HZ      → ["HZ"]            -RA    → ["RA-"]
    +TSRA   → ["TS", "RA+"]     SHRA   → ["SH", "RA"]
    TSGR    → ["TS", "GR"]      VCTS   → ["VCTS"]   (in the vicinity, not overhead)
    -RABR   → ["RA-", "BR"]     +DS    → ["DS+"]
"""

import csv
import gzip
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

KT_TO_KMH = 1.852
MPS_TO_KMH = 3.6
STATUTE_MILE_M = 1609.34
# "10 km or more": what 9999 and CAVOK both mean.
VISIBILITY_UNLIMITED_M = 10_000

# India's four flight-information regions: Mumbai, Kolkata, Delhi, Chennai.
INDIAN_ICAO_PREFIXES = ("VA", "VE", "VI", "VO")

# Groups after which the rest of the report is forecast or remark.
_STOP_GROUPS = {"NOSIG", "BECMG", "TEMPO", "RMK"}

_WIND_RE = re.compile(r"^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$")
_WIND_VARIATION_RE = re.compile(r"^\d{3}V\d{3}$")
_VIS_METRIC_RE = re.compile(r"^(\d{4})(NDV|N|NE|E|SE|S|SW|W|NW)?$")
_VIS_MILES_RE = re.compile(r"^(P|M)?(?:(\d+)|(\d+)/(\d+))SM$")
_RVR_RE = re.compile(r"^R\d{2}[LCR]?/")
_CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC)(\d{3}|///)(CB|TCU|///)?$")
# Always two digits (M05/M10, 30/24), so a stray "1/2" from a "1 1/2SM"
# visibility is never read as a temperature.
_TEMP_RE = re.compile(r"^(M?\d{2})/(M?\d{2})?$")

_DESCRIPTORS = ("MI", "PR", "BC", "DR", "BL", "SH", "TS", "FZ")
_PHENOMENA = (
    "DZ", "RA", "SN", "SG", "IC", "PL", "GR", "GS", "UP",       # precipitation
    "BR", "FG", "FU", "VA", "DU", "SA", "HZ", "PY",             # obscuration
    "PO", "SQ", "FC", "SS", "DS",                               # other
)
# What an intensity sign (+ or -) can qualify: precipitation, and the three
# phenomena that have a "heavy" form (+DS heavy dust storm, +SS, +FC tornado).
# Obscurations never take one: in "-RABR" the rain is light and the mist is
# just mist.
_TAKES_INTENSITY = {"DZ", "RA", "SN", "SG", "IC", "PL", "GR", "GS", "UP", "DS", "SS", "FC"}
_WEATHER_RE = re.compile(
    r"^(\+|-|VC)?((?:" + "|".join(_DESCRIPTORS) + r"))?((?:" + "|".join(_PHENOMENA) + r")*)$"
)


@dataclass
class Observation:
    """What one METAR says, in SI units. None means the report did not say."""

    station_code: str
    raw: str
    recorded_at: Optional[datetime] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    elevation_m: Optional[float] = None
    temperature_c: Optional[float] = None
    dewpoint_c: Optional[float] = None
    wind_kmh: Optional[float] = None
    gust_kmh: Optional[float] = None
    visibility_m: Optional[int] = None
    weather_codes: List[str] = field(default_factory=list)
    convective_cloud: bool = False


def is_indian(station_code: str) -> bool:
    return (station_code or "").upper().startswith(INDIAN_ICAO_PREFIXES)


def _to_kmh(value: str, unit: str) -> float:
    factor = {"KT": KT_TO_KMH, "MPS": MPS_TO_KMH, "KMH": 1.0}[unit]
    return round(int(value) * factor, 1)


def _temperature(token: str) -> float:
    return float(-int(token[1:]) if token.startswith("M") else int(token))


def normalise_weather(token: str) -> Optional[List[str]]:
    """
    One present-weather group as a list of codes, or None if it is not one.

    Intensity (+ or -) belongs to the phenomenon, never to the descriptor:
    "+TSRA" is heavy rain in a thunderstorm, so TS stays TS and RA becomes RA+.
    """
    if not token or token in {"NSW"}:
        return None
    m = _WEATHER_RE.match(token)
    if not m:
        return None
    prefix, descriptor, phenomena = m.group(1), m.group(2), m.group(3)
    if not descriptor and not phenomena:
        return None

    codes: List[str] = []
    parts = [phenomena[i:i + 2] for i in range(0, len(phenomena or ""), 2)]
    if prefix == "VC":
        # In the vicinity (8–16 km), not at the aerodrome: kept distinct so a
        # thunderstorm nearby is never read as one overhead.
        return ["VC" + (descriptor or "") + "".join(parts)]
    if descriptor:
        codes.append(descriptor)
    suffix = prefix if prefix in {"+", "-"} else ""
    if parts:
        codes.extend(p + suffix if p in _TAKES_INTENSITY else p for p in parts)
    elif suffix:
        # A lone descriptor with intensity, e.g. "+TS": heavy thunderstorm.
        codes[-1] = codes[-1] + suffix
    return codes


def parse_report(raw: str) -> Dict[str, object]:
    """
    Wind, visibility, present weather, cloud and temperature from the raw text.

    Returns only what the report states; a field it omits is absent from the
    dict, so a caller can tell "not reported" from a value.
    """
    tokens = (raw or "").replace("=", " ").split()
    # Header: METAR/SPECI, then the station, then DDHHMMZ, then optional flags.
    while tokens and tokens[0] in {"METAR", "SPECI"}:
        tokens = tokens[1:]
    body = tokens[2:] if len(tokens) >= 2 else []

    out: Dict[str, object] = {}
    weather: List[str] = []
    convective = False

    for token in body:
        if token in _STOP_GROUPS:
            break
        if token in {"AUTO", "COR", "NIL"}:
            continue

        m = _WIND_RE.match(token)
        if m and "wind_kmh" not in out:
            out["wind_kmh"] = _to_kmh(m.group(2), m.group(4))
            if m.group(3):
                out["gust_kmh"] = _to_kmh(m.group(3), m.group(4))
            continue
        if _WIND_VARIATION_RE.match(token):
            continue

        if token == "CAVOK":
            # Ceiling and visibility OK: 10 km or more, no weather, no
            # significant cloud.
            out["visibility_m"] = VISIBILITY_UNLIMITED_M
            continue

        m = _VIS_METRIC_RE.match(token)
        if m and "visibility_m" not in out:
            metres = int(m.group(1))
            out["visibility_m"] = VISIBILITY_UNLIMITED_M if metres == 9999 else metres
            continue
        if m:
            # A later 4-digit group is a directional minimum, not the
            # prevailing visibility.
            continue

        m = _VIS_MILES_RE.match(token)
        if m and "visibility_m" not in out:
            miles = float(m.group(2)) if m.group(2) else int(m.group(3)) / int(m.group(4))
            out["visibility_m"] = int(round(miles * STATUTE_MILE_M))
            continue

        if _RVR_RE.match(token) or token.startswith("VV"):
            continue

        m = _CLOUD_RE.match(token)
        if m:
            if m.group(3) in {"CB", "TCU"}:
                convective = True
            continue
        if token in {"NSC", "NCD", "SKC", "CLR"}:
            continue

        m = _TEMP_RE.match(token)
        if m and "temperature_c" not in out:
            out["temperature_c"] = _temperature(m.group(1))
            if m.group(2):
                out["dewpoint_c"] = _temperature(m.group(2))
            continue

        if token.startswith(("Q", "A")) and token[1:].isdigit():
            continue  # pressure
        if token.startswith("RE") or token.startswith("WS"):
            continue  # recent weather, wind shear: not present weather

        codes = normalise_weather(token)
        if codes:
            for code in codes:
                if code not in weather:
                    weather.append(code)

    out["weather_codes"] = weather
    out["convective_cloud"] = convective
    return out


# ── AWC's bulk cache file ──────────────────────────────────────────────────────

def _float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    value = value.strip().rstrip("+")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def read_cache_rows(content: bytes) -> List[Dict[str, str]]:
    """
    The cache file's rows as dicts keyed by column name.

    Accepts the gzip bytes as served or already-decompressed CSV. The header
    repeats `sky_cover` and `cloud_base_ft_agl` four times, one per cloud
    layer, so rows are read positionally and only the first of each repeated
    name is kept; this module reads cloud from the raw text anyway.

    Raises ValueError for a body that is neither.
    """
    if content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except (OSError, EOFError) as e:
            raise ValueError(f"corrupt gzip: {e}") from e
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"not UTF-8 text: {e}") from e

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("empty file")
    if "raw_text" not in header or "station_id" not in header:
        raise ValueError(f"unexpected columns: {header[:6]}")

    first_index: Dict[str, int] = {}
    for i, name in enumerate(header):
        first_index.setdefault(name, i)

    rows: List[Dict[str, str]] = []
    for values in reader:
        if not values:
            continue
        rows.append({
            name: (values[i] if i < len(values) else "")
            for name, i in first_index.items()
        })
    return rows


def observation_from_row(row: Dict[str, str]) -> Optional[Observation]:
    """One cache row as an Observation, or None if it has no station or time."""
    station = (row.get("station_id") or "").strip().upper()
    raw = " ".join((row.get("raw_text") or "").split())
    recorded_at = _time(row.get("observation_time"))
    if not station or not raw or recorded_at is None:
        return None

    parsed = parse_report(raw)
    obs = Observation(
        station_code=station,
        raw=raw,
        recorded_at=recorded_at,
        lat=_float(row.get("latitude")),
        lng=_float(row.get("longitude")),
        elevation_m=_float(row.get("elevation_m")),
        temperature_c=parsed.get("temperature_c"),
        dewpoint_c=parsed.get("dewpoint_c"),
        wind_kmh=parsed.get("wind_kmh"),
        gust_kmh=parsed.get("gust_kmh"),
        visibility_m=parsed.get("visibility_m"),
        weather_codes=list(parsed.get("weather_codes") or []),
        convective_cloud=bool(parsed.get("convective_cloud")),
    )

    # The CSV's columns fill only what the raw text did not say. Its
    # temperatures carry tenths where the report has them.
    if obs.temperature_c is None:
        obs.temperature_c = _float(row.get("temp_c"))
    if obs.dewpoint_c is None:
        obs.dewpoint_c = _float(row.get("dewpoint_c"))
    if obs.wind_kmh is None:
        kt = _float(row.get("wind_speed_kt"))
        obs.wind_kmh = round(kt * KT_TO_KMH, 1) if kt is not None else None
    if obs.gust_kmh is None:
        kt = _float(row.get("wind_gust_kt"))
        obs.gust_kmh = round(kt * KT_TO_KMH, 1) if kt is not None else None
    if obs.visibility_m is None:
        # Indian METARs report metres and the CSV converts them to miles, so
        # this is the last resort, not the source.
        miles = _float(row.get("visibility_statute_mi"))
        obs.visibility_m = int(round(miles * STATUTE_MILE_M)) if miles is not None else None
    return obs


def indian_observations(rows: Iterable[Dict[str, str]]) -> List[Observation]:
    """The rows from Indian stations, parsed; unparseable rows are dropped."""
    out: List[Observation] = []
    for row in rows:
        if not is_indian(row.get("station_id") or ""):
            continue
        obs = observation_from_row(row)
        if obs is not None:
            out.append(obs)
    return out
