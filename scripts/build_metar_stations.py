#!/usr/bin/env python3
"""
Build data/geo/india_metar_stations.csv: every Indian aerodrome that reports
METARs, with its name, position and elevation.

The METAR poller (backend/app/workers/metar_poller.py) reads AWC's bulk cache
file, which carries a position for each report but no station name. This table
supplies the names ("Ahmadabad/Patel Intl"), once, from AWC's station catalogue:

    https://aviationweather.gov/api/data/stationinfo?bbox=6,68,37.6,98&format=json

No key is needed. Kept: country IN, and an ICAO id in one of India's four
flight-information regions (VA Mumbai, VE Kolkata, VI Delhi, VO Chennai). The
bounding box also catches Nepal (VN), Sri Lanka (VC), Bangladesh (VG),
Pakistan (OP) and others; those are dropped.

    python scripts/build_metar_stations.py            # fetch and write
    python scripts/build_metar_stations.py --dry-run  # fetch and count only

Re-run when AWC adds stations; the poller also stores a station it does not
find here, named by its ICAO id, so a stale table costs a name, not a reading.
"""

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "geo" / "india_metar_stations.csv"
URL = "https://aviationweather.gov/api/data/stationinfo?bbox=6,68,37.6,98&format=json"
INDIAN_PREFIXES = ("VA", "VE", "VI", "VO")
USER_AGENT = "INDRA-SIH2026/1.0 (Team Sixth Sense; disaster situational awareness)"
COLUMNS = ["icao", "name", "state_code", "lat", "lon", "elevation_m", "iata", "wmo"]


def fetch() -> list:
    request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def indian_rows(stations: list) -> list:
    rows = []
    for s in stations:
        icao = (s.get("icaoId") or "").strip().upper()
        if s.get("country") != "IN" or not icao.startswith(INDIAN_PREFIXES):
            continue
        if s.get("lat") is None or s.get("lon") is None:
            continue
        rows.append({
            "icao": icao,
            # Collapse runs of spaces: AWC has "Amravati  Arpt".
            "name": " ".join((s.get("site") or icao).split()),
            "state_code": (s.get("state") or "").strip(),
            "lat": round(float(s["lat"]), 4),
            "lon": round(float(s["lon"]), 4),
            "elevation_m": s.get("elev") if s.get("elev") is not None else "",
            "iata": (s.get("iataId") or "").strip(),
            "wmo": (s.get("wmoId") or "").strip(),
        })
    return sorted(rows, key=lambda r: r["icao"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and count; write nothing")
    args = parser.parse_args()

    rows = indian_rows(fetch())
    if not rows:
        print("AWC returned no Indian stations; nothing written.", file=sys.stderr)
        return 1
    print(f"{len(rows)} Indian METAR stations")
    if args.dry_run:
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
