#!/usr/bin/env python3
"""
Build the offline district gazetteer used by the reverse geocoder.

INDRA had no reverse geocoder at all: every event carried coordinates and the
API answered `"city": "Unknown"` because nothing in the stack could turn a
point into a place name. This script produces the lookup table that fixes
that — one row per Indian district, with a point that is guaranteed to lie
inside the district's own boundary.

Source: district boundary polygons (Census 2011 districts) published at
https://github.com/udit-001/india-maps-data, one GeoJSON per state.

Only the derived CSV is committed, not the ~70 MB of boundary polygons. This
script is committed next to it so the CSV is reproducible rather than magic:

    ./backend/.venv/bin/python scripts/build_gazetteer.py

Re-run it with --source-dir to build from an already-downloaded copy instead
of fetching, which is what the offline test run does.

A note on the district codes carried here. They are **Census 2011** codes,
which are *not* the codes SACHET CAP alerts publish in `district_codes` —
those are LGD codes, a different vocabulary (Mysuru is 577 in Census 2011 and
541 in LGD). No public LGD mapping was reachable when this was written, so the
agency-alert resolver matches on district *name* out of `area_desc` and the
census code is carried only so a row can be traced back to its source polygon.
Do not use it to resolve a CAP alert.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    from shapely.geometry import shape
except ImportError:  # pragma: no cover - a setup error, not a runtime path
    sys.exit("shapely is required: ./backend/.venv/bin/pip install shapely")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "geo" / "india_districts.csv"

BASE_URL = "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/states"

STATES = [
    "andaman-and-nicobar-islands", "andhra-pradesh", "arunachal-pradesh", "assam",
    "bihar", "chandigarh", "chhattisgarh", "delhi", "dnh-and-dd", "goa", "gujarat",
    "haryana", "himachal-pradesh", "jammu-and-kashmir", "jharkhand", "karnataka",
    "kerala", "ladakh", "lakshadweep", "madhya-pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "puducherry", "punjab", "rajasthan",
    "sikkim", "tamil-nadu", "telangana", "tripura", "uttar-pradesh", "uttarakhand",
    "west-bengal",
]

FIELDNAMES = [
    "district", "state", "lat", "lng",
    "min_lat", "min_lng", "max_lat", "max_lng",
    "census_code",
]


def fetch_state(slug: str, cache_dir: Path) -> dict:
    """Return one state's GeoJSON, downloading it only if it is not cached."""
    cached = cache_dir / f"{slug}.geojson"
    if cached.exists():
        return json.loads(cached.read_text())

    import httpx

    response = httpx.get(f"{BASE_URL}/{slug}.geojson", timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    cached.write_text(response.text)
    return response.json()


def districts_from(collection: dict) -> list[dict]:
    """
    One row per district feature.

    `representative_point()` rather than `centroid`: a district shaped like a
    crescent — or one that is a scatter of islands, which Andaman and
    Lakshadweep genuinely are — has a centroid in the sea. A representative
    point is guaranteed to lie inside the polygon, so every row in this file
    is a place that is actually in the district it names.

    The bounding box is carried alongside because distance-to-a-single-point
    is a poor test for a large district: a village in western Kutch is over
    100 km from any one point that can represent Kutch, and nearest-point
    alone would either name the wrong district or give up. The box lets the
    resolver ask "is this point inside the district at all" first and fall
    back to distance only when no box contains it.
    """
    rows = []
    for feature in collection.get("features", []):
        props = feature.get("properties", {})
        district = (props.get("district") or "").strip()
        state = (props.get("st_nm") or "").strip()
        if not district or not state:
            continue

        geometry = shape(feature["geometry"])
        point = geometry.representative_point()
        min_lng, min_lat, max_lng, max_lat = geometry.bounds
        rows.append({
            "district": district,
            "state": state,
            "lat": round(point.y, 6),
            "lng": round(point.x, 6),
            "min_lat": round(min_lat, 6),
            "min_lng": round(min_lng, 6),
            "max_lat": round(max_lat, 6),
            "max_lng": round(max_lng, 6),
            "census_code": (props.get("dt_code") or "").strip(),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="directory holding the per-state GeoJSON files; downloads into it when absent",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    cache_dir = args.source_dir or (REPO_ROOT / ".gazetteer-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for slug in STATES:
        try:
            collection = fetch_state(slug, cache_dir)
        except Exception as exc:
            print(f"  {slug:32} FAILED: {exc}", file=sys.stderr)
            return 1
        found = districts_from(collection)
        rows.extend(found)
        print(f"  {slug:32} {len(found):3} districts")

    if not rows:
        print("No districts parsed — refusing to write an empty gazetteer.", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: (r["state"], r["district"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    states = len({r["state"] for r in rows})
    print(f"\nWrote {len(rows)} districts across {states} states to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
