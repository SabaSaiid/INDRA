#!/usr/bin/env python3
"""
The verification demo: a genuine case and a fabricated one, on today's weather
(Phase 4 T8).

    backend/.venv/bin/python scripts/run_verification_demo.py
    backend/.venv/bin/python scripts/run_verification_demo.py --record data/demo/verification_cases.json
    backend/.venv/bin/python scripts/run_verification_demo.py --frozen data/demo/verification_cases.json

* **Case A, genuine.** A place with supporting evidence right now: the centre
  of a SACHET heavy-rain warning in force, or else an airport reporting rain or
  a thunderstorm, or else one reporting fog or 40 °C. Five reports of that
  hazard there. Expected: **CORROBORATED**.
* **Case B, fabricated.** A plains airport whose maximum over the last 24 h is
  under 35 °C. Five "heatwave, 47 degree" reports 5 km from it. Expected:
  **CONTRADICTED**, with the station and its temperature in the reason.

Both receipts are printed side by side, then every evidence line. The exit
code is 1 if either verdict is not the expected one, or if no place with
supporting evidence exists today: the script says so and never pretends.

**It writes nothing.** On 25 Sep the demo injectors that posted scripted
reports into the live database were removed, and this does not bring that
back. The places and every reading are live (SACHET, the stored METAR
observations, Open-Meteo); the ten reports exist only in this process, each
text labelled "[synthetic demo]", and are scored by the pipeline's own pure
`score_cluster()` over the pipeline's own evidence functions. No event, report,
snapshot or ledger row is created.

`--record PATH` saves every input the live run read (the places, the hourly
series, the airport observations, the warnings, SACHET's freshness), and
`--frozen PATH` replays such a file without a network or a database, for
rehearsing offline. There is no frozen file until a live run records one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

LABEL = "[synthetic demo]"
DEFAULT_FILE = REPO_ROOT / "data" / "demo" / "verification_cases.json"
REPORTS_PER_CASE = 5

# What five people would write, per hazard. The tagger decides the type from
# these, exactly as it does for a real report.
TEXTS = {
    "URBAN_FLOOD": [
        "Heavy rain since morning, the road outside is flooded knee deep",
        "Waterlogging near the market after heavy rain, water knee deep",
        "Flooded street, heavy rain still falling, cars stuck in water",
        "Heavy rain here and the lane is flooded, water entering shops",
        "Road flooded after continuous heavy rain, knee deep water",
    ],
    "THUNDERSTORM": [
        "Thunderstorm right now, loud thunder and heavy rain here",
        "Strong thunderstorm with thunder and lightning over the area",
        "Thunder and lightning, thunderstorm with gusty wind here",
        "Thunderstorm hitting the city now, heavy thunder",
        "Severe thunderstorm with lightning and rain here",
    ],
    "FOG": [
        "Dense fog here, visibility under 50 metres on the highway",
        "Very dense fog, cannot see the next vehicle, visibility near zero",
        "Thick fog this morning, visibility below 100 metres",
        "Dense fog on the road, visibility very low",
        "Fog so dense that visibility is under 50 metres",
    ],
    "HEATWAVE": [
        "Heatwave here, 47 degree today, unbearable heat",
        "Severe heatwave, temperature 47 degree, loo chal rahi hai",
        "Extreme heat, 47 degree in the afternoon, heatwave",
        "Heatwave conditions, mercury touched 47 degree",
        "Scorching heatwave, 47 degree celsius today",
    ],
}


# ── Geometry of five reports around a point ────────────────────────────────────

def _offset(lat: float, lng: float, north_km: float, east_km: float) -> Tuple[float, float]:
    return (
        lat + north_km / 111.32,
        lng + east_km / (111.32 * math.cos(math.radians(lat))),
    )


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def make_reports(hazard: str, lat: float, lng: float, now: datetime) -> List[Dict[str, Any]]:
    """Five labelled reports within ~1 km of the point, 5 to 45 minutes old."""
    spots = [(0.0, 0.0), (0.4, 0.3), (-0.3, 0.5), (0.6, -0.4), (-0.5, -0.2)]
    out = []
    for i, ((dn, de), body) in enumerate(zip(spots, TEXTS[hazard])):
        rlat, rlng = _offset(lat, lng, dn, de)
        out.append({
            "text": f"{LABEL} {body}",
            "lat": round(rlat, 5),
            "lng": round(rlng, 5),
            "at": (now - timedelta(minutes=45 - 10 * i)).isoformat(),
        })
    return out


# ── Scoring a case, from recorded inputs only ─────────────────────────────────

def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def score_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """The receipt for one case, from its recorded inputs. No I/O."""
    from app.models.enums import SourceType
    from app.services import evidence as ev
    from app.services.corroboration import effective_reporters, news_corroboration
    from app.services.credibility import compute_credibility
    from app.services.event_typing import decide_event_type
    from app.services.geo_clustering import family_params
    from app.services.hazard_tagger import tag_hazards
    from app.services.hazards import family_of
    from app.services.official_warnings import Warning, evidence_from_warnings
    from app.services.pipeline import score_cluster
    from app.services.weather import HourlySeries

    now = _dt(case["now"])
    reports = []
    for i, r in enumerate(case["reports"]):
        tagged = tag_hazards(r["text"], reference_year=now.year)
        reports.append({
            "id": uuid.UUID(int=i + 1),
            "raw_text": r["text"],
            "source_type": SourceType.CITIZEN_APP.value,
            "hazard_primary": tagged["hazard_primary"],
            "citizen_hazard": None,
            "reporter_hash": f"demo-reporter-{case['case']}-{i}",
            "credibility": compute_credibility(SourceType.CITIZEN_APP, r["text"]),
            "flags": [],
            "at": _dt(r["at"]),
            "lat": r["lat"],
            "lng": r["lng"],
        })

    typed = decide_event_type(reports)
    event_type = typed["event_type"]
    points = [(r["lat"], r["lng"]) for r in reports]
    c_lat = sum(p[0] for p in points) / len(points)
    c_lng = sum(p[1] for p in points) / len(points)
    stats = {
        "count": len(points),
        "centroid_lat": c_lat,
        "centroid_lng": c_lng,
        "max_pairwise_km": round(max(_haversine_km(a, b) for a in points for b in points), 4),
        "radius_km": round(max(_haversine_km((c_lat, c_lng), p) for p in points), 4),
    }

    span = [r["at"] for r in reports]
    window = ev.evidence_window(event_type, min(span), max(span), now)
    hourly = HourlySeries.from_json(case["hourly"]) if case.get("hourly") else None
    air = HourlySeries.from_json(case["air"]) if case.get("air") else None
    rain = case.get("rainfall") or {}
    model = ev.model_evidence(
        event_type, window, hourly, air=air,
        rainfall_mm=rain.get("mm"), rainfall_origin=rain.get("source"), rain_score=rain.get("score"),
    )
    observations = [{**o, "recorded_at": _dt(o["recorded_at"])} for o in case.get("metar") or []]
    stations = ev.group_stations(observations, window)
    station = ev.station_evidence(
        event_type, stations, window,
        hill_hint=model.detail.get("hill") if hourly is not None else None,
    )
    weather = ev.combine_weather(event_type, model, station)
    warnings = [
        Warning(
            identifier=w["identifier"], sender=w["sender"], event=w["event"],
            headline=w["headline"], raw_severity=w["raw_severity"],
            expires_at=_dt(w["expires_at"]), matched_by=w["matched_by"],
        )
        for w in case.get("warnings") or []
    ]
    sachet = case.get("sachet") or {}
    official = evidence_from_warnings(
        event_type, warnings, sachet_fresh=bool(sachet.get("fresh")),
        sachet_age_minutes=sachet.get("age_minutes"),
    )
    contradiction = ev.find_contradiction(
        event_type, weather, model, stations, window,
        cyclone_warning_nearby=case.get("cyclone_nearby"),
    )
    bundle = {
        "now": now, "window": window, "weather": weather, "model": model, "station": station,
        "stations_seen": len(stations), "official": official, "contradiction": contradiction,
        "news": news_corroboration([]), "rainfall_mm": rain.get("mm"),
        "weather_source": rain.get("source") or "not_applicable",
    }
    scored = score_cluster(
        stats,
        [r["source_type"] for r in reports],
        report_texts=[r["raw_text"] for r in reports],
        event_type=event_type,
        event_type_basis=typed["basis"],
        density=effective_reporters(reports),
        eps_km=family_params(family_of(event_type)).eps_km,
        evidence=bundle,
    )
    return {"case": case, "event_type": event_type, "scored": scored}


# ── Choosing the places, live ──────────────────────────────────────────────────

WATER_WARNING_SQL = """
    SELECT identifier, sender, event, headline, raw_severity,
           ST_Y(ST_PointOnSurface(area_polygon)), ST_X(ST_PointOnSurface(area_polygon))
    FROM agency_alerts
    WHERE area_polygon IS NOT NULL
      AND lower(COALESCE(status, '')) = 'actual'
      AND lower(COALESCE(msg_type, '')) IN ('alert', 'update')
      AND COALESCE(effective_at, onset_at, sent_at) <= CAST(:now AS timestamptz)
      AND expires_at >= CAST(:now AS timestamptz)
    ORDER BY CASE raw_severity WHEN 'Extreme' THEN 0 WHEN 'Severe' THEN 1
                               WHEN 'Moderate' THEN 2 ELSE 3 END, expires_at DESC, identifier
"""

METAR_RECENT_SQL = """
    SELECT station_code, recorded_at, COALESCE(weather_codes, '{}'::text[]), temperature_c, visibility_m
    FROM station_readings
    WHERE feed = 'metar' AND recorded_at >= CAST(:since AS timestamptz)
    ORDER BY recorded_at DESC
"""

METAR_MAX_TEMP_SQL = """
    SELECT station_code, max(temperature_c), count(*)
    FROM station_readings
    WHERE feed = 'metar' AND temperature_c IS NOT NULL
      AND recorded_at >= CAST(:since AS timestamptz)
    GROUP BY station_code
    HAVING count(*) >= 6
    ORDER BY max(temperature_c), station_code
"""


async def _choose_case_a(db, now: datetime) -> Optional[Dict[str, Any]]:
    """
    A place where the evidence supports the claim right now. A warning is a
    forecast, so a warned place counts only if some rain has also fallen there
    in the last 24 h: a flood claim under a warning on a dry day is exactly
    what the contradiction rule catches, and would not be a genuine case.
    """
    from sqlalchemy import text

    from app.services.official_warnings import Warning, warning_families
    from app.services.pipeline import _weather_for_cluster
    from app.workers.metar_poller import station_table

    for row in (await db.execute(text(WATER_WARNING_SQL), {"now": now})).fetchall():
        if (row[4] or "").strip().title() not in ("Extreme", "Severe", "Moderate") or row[5] is None:
            continue
        w = Warning(identifier=row[0], sender=row[1], event=row[2], headline=row[3],
                    raw_severity=row[4], expires_at=None, matched_by="polygon")
        if "water" not in warning_families(w):
            continue
        _score, mm, _source = await _weather_for_cluster(db, row[5], row[6])
        if mm is None or mm <= 0.0:
            continue
        return {"hazard": "URBAN_FLOOD", "lat": row[5], "lng": row[6],
                "because": f"a SACHET {row[4]} warning in force ({row[1]}: {row[2]}), at a point "
                           f"inside its polygon where {mm:.1f} mm fell in the last 24 h"}

    table = station_table()
    recent = (await db.execute(text(METAR_RECENT_SQL), {"since": now - timedelta(hours=3)})).fetchall()
    for want, hazard, why in (
        (lambda b, c, t, v: "TS" in b, "THUNDERSTORM", "reporting a thunderstorm (TS)"),
        (lambda b, c, t, v: "RA+" in c or ("RA" in b and "SH" in b), "URBAN_FLOOD", "reporting heavy rain"),
        (lambda b, c, t, v: "RA" in b, "URBAN_FLOOD", "reporting rain (RA)"),
        (lambda b, c, t, v: v is not None and (v < 200 or ("FG" in b and v < 500)), "FOG",
         "reporting fog under 500 m"),
        (lambda b, c, t, v: t is not None and t >= 42, "HEATWAVE", "reading 42 °C or more"),
    ):
        for station, at, codes, temp, vis in recent:
            bases = {str(c).rstrip("+-") for c in codes}
            known = table.get(station)
            if known and want(bases, list(codes), temp, vis):
                lat, lng = _offset(known["lat"], known["lon"], 0.0, 5.0)
                return {"hazard": hazard, "lat": lat, "lng": lng,
                        "because": f"airport {station} ({known['name']}) {why} at "
                                   f"{at.isoformat()}; the reports are placed 5 km east of it"}
    return None


async def _choose_case_b(db, now: datetime) -> Optional[Dict[str, Any]]:
    from sqlalchemy import text

    from app.services.evidence import HEAT_CONTRADICTION_PLAINS_C, HILL_ELEVATION_M
    from app.workers.metar_poller import station_table

    table = station_table()
    rows = (await db.execute(text(METAR_MAX_TEMP_SQL), {"since": now - timedelta(hours=24)})).fetchall()
    for station, max_c, n in rows:
        known = table.get(station)
        if not known or max_c is None or max_c >= HEAT_CONTRADICTION_PLAINS_C:
            continue
        if known.get("elevation_m") is None or known["elevation_m"] > HILL_ELEVATION_M:
            continue
        if not known.get("civil"):
            continue
        lat, lng = _offset(known["lat"], known["lon"], 0.0, 5.0)
        return {"hazard": "HEATWAVE", "lat": lat, "lng": lng,
                "because": f"airport {station} ({known['name']}, {known['elevation_m']:.0f} m) read a "
                           f"maximum of {max_c:.1f} °C over the last 24 h ({n} observations); the "
                           f"reports are placed 5 km east of it"}
    return None


async def _record_inputs(db, case_id: str, choice: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Every input score_case() needs for one place, read live."""
    from app.services import evidence as ev
    from app.services.geocoding import reverse_geocode
    from app.services.official_warnings import covering_warnings, sachet_freshness
    from app.services.pipeline import (
        EVIDENCE_HOURLY_TYPES, EVIDENCE_RAIN_TYPES, _metar_observations, _weather_for_cluster,
    )
    from app.services.weather import fetch_hourly

    hazard, lat, lng = choice["hazard"], choice["lat"], choice["lng"]
    reports = make_reports(hazard, lat, lng, now)
    span = [datetime.fromisoformat(r["at"]) for r in reports]
    window = ev.evidence_window(hazard, min(span), max(span), now)
    place = reverse_geocode(lat, lng)

    rainfall = None
    if hazard in EVIDENCE_RAIN_TYPES:
        score, mm, source = await _weather_for_cluster(db, lat, lng)
        rainfall = {"score": score, "mm": mm, "source": source}
    hourly = await fetch_hourly(lat, lng) if hazard in EVIDENCE_HOURLY_TYPES else None
    observations = await _metar_observations(db, lat, lng, window.start, window.end)
    fresh, age = await sachet_freshness(db, now)
    warnings = await covering_warnings(db, now=now, lat=lat, lng=lng,
                                       district=place.district if place else None) if fresh else []
    return {
        "case": case_id,
        "now": now.isoformat(),
        "hazard_claimed": hazard,
        "chosen_because": choice["because"],
        "place": {"district": place.district if place else None, "state": place.state if place else None},
        "reports": reports,
        "rainfall": rainfall,
        "hourly": hourly.to_json() if hourly else None,
        "air": None,
        "metar": [{**o, "recorded_at": o["recorded_at"].isoformat()} for o in observations],
        "sachet": {"fresh": fresh, "age_minutes": age},
        "warnings": [
            {"identifier": w.identifier, "sender": w.sender, "event": w.event, "headline": w.headline,
             "raw_severity": w.raw_severity,
             "expires_at": w.expires_at.isoformat() if w.expires_at else None,
             "matched_by": w.matched_by}
            for w in warnings
        ],
        "cyclone_nearby": None,
    }


async def live_inputs() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    from app.core.database import async_session
    from app.services import clock

    now = clock.now()
    problems = []
    async with async_session() as db:
        a = await _choose_case_a(db, now)
        b = await _choose_case_b(db, now)
        if a is None:
            problems.append(
                "Case A: no SACHET heavy-rain warning is in force, and no airport reported rain, "
                "a thunderstorm, fog or 42 °C in the last 3 hours. There is no genuine case to show "
                "today, and the script will not invent one."
            )
        if b is None:
            problems.append(
                "Case B: no civil plains airport read a maximum under 35 °C over the last 24 hours, "
                "so a fabricated heatwave cannot be shown contradicted by a thermometer today."
            )
        case_a = await _record_inputs(db, "A", a, now) if a else None
        case_b = await _record_inputs(db, "B", b, now) if b else None
    return case_a, case_b, problems


# ── Printing ───────────────────────────────────────────────────────────────────

def _cell(text_: Any, width: int) -> str:
    s = "" if text_ is None else str(text_)
    return (s[: width - 1] + "…") if len(s) > width else s.ljust(width)


def print_side_by_side(a: Dict[str, Any], b: Dict[str, Any]) -> None:
    ra, rb = a["scored"]["receipt"], b["scored"]["receipt"]
    w0, w = 34, 44
    rows = [
        ("", "CASE A — genuine", "CASE B — fabricated"),
        ("Place", _place(a), _place(b)),
        ("Claim (5 labelled reports)", a["event_type"], b["event_type"]),
    ]
    fa = {f["key"]: f for f in ra["factors"]}
    fb = {f["key"]: f for f in rb["factors"]}
    for key in fa:
        label = f"{fa[key]['factor'][:26]} ({fa[key]['weight_pct']:.0f}%)"
        rows.append((label, _factor(fa[key]), _factor(fb[key])))
    rows += [
        ("Factor coverage", ra["factor_coverage"], rb["factor_coverage"]),
        ("Confidence", ra["confidence_score"], rb["confidence_score"]),
        ("VERDICT", ra["verdict"]["value"], rb["verdict"]["value"]),
        ("Review status", a["scored"]["review_status"].value, b["scored"]["review_status"].value),
    ]
    print()
    for label, left, right in rows:
        print(f"{_cell(label, w0)} {_cell(left, w)} {_cell(right, w)}")
    print()
    for case in (a, b):
        r = case["scored"]["receipt"]
        print(f"— Case {case['case']['case']}: chosen because {case['case']['chosen_because']}")
        for key in ("weather_station", "official_warning"):
            e = r["evidence"][key]
            print(f"    {key}: [{e['source']}] {e['reason']}")
        for c in r["contradictions"]:
            print(f"    CONTRADICTION ({c['rule']}): {c['reason']}")
        print(f"    verdict: {r['verdict']['reason']}")
        print()


def _place(case: Dict[str, Any]) -> str:
    p = case["case"].get("place") or {}
    return ", ".join(x for x in (p.get("district"), p.get("state")) if x) or "unnamed place"


def _factor(f: Dict[str, Any]) -> str:
    if f["state"] == "offline":
        return "offline"
    flag = " CONTRADICTED" if f.get("contradiction") else ""
    return f"{f['score']:.2f}{flag}"


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4's verification demo; writes nothing.")
    parser.add_argument("--frozen", nargs="?", const=str(DEFAULT_FILE), default=None,
                        help="replay recorded inputs (default %(const)s)")
    parser.add_argument("--record", default=None, help="save the live run's inputs to this file")
    args = parser.parse_args()

    if args.frozen:
        path = Path(args.frozen)
        if not path.exists():
            print(f"No recorded inputs at {path}. Run once live with --record {path} first.")
            return 1
        data = json.loads(path.read_text())
        case_a, case_b, problems = data.get("A"), data.get("B"), data.get("problems", [])
        print(f"Replaying inputs recorded at {data.get('recorded_at')} ({path})")
    else:
        case_a, case_b, problems = asyncio.run(live_inputs())
        if args.record:
            path = Path(args.record)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(
                {"recorded_at": datetime.now(timezone.utc).isoformat(), "A": case_a, "B": case_b,
                 "problems": problems},
                indent=2, ensure_ascii=False, default=str,
            ))
            print(f"Inputs recorded to {path}")

    for p in problems:
        print(p)
    if case_a is None or case_b is None:
        return 1

    a, b = score_case(case_a), score_case(case_b)
    print_side_by_side(a, b)

    ok = True
    for case, expected in ((a, "CORROBORATED"), (b, "CONTRADICTED")):
        got = case["scored"]["verdict"].value
        if got != expected:
            ok = False
            print(f"Case {case['case']['case']}: expected {expected}, got {got}")
    print("Every report above is synthetic and labelled; the places and readings are real.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
