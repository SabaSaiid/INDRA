#!/usr/bin/env python3
"""
INDRA — one live demo per hazard (Phase 3 T10).

Posts five synthetic citizen reports about one hazard in one city, each from a
distinct reporter (`X-Reporter-Id`), follows them through the pipeline by their
dockets, then reads the event they joined back from the API and prints its
type, severity and receipt. Nothing printed is computed here: every number is
the API's.

Usage
-----
    ./start.sh -b                       # the backend must be running
    backend/.venv/bin/python scripts/run_hazard_demo.py --hazard heatwave --city delhi
    backend/.venv/bin/python scripts/run_hazard_demo.py --hazard fog --city lucknow
    backend/.venv/bin/python scripts/run_hazard_demo.py --hazard flood --city patna --official

Hazards: flood, heatwave, fog, thunderstorm, dust_storm, strong_wind, cold_wave
(the PS's seven categories). Cities: see CITIES.

**Exit code 1 if the event's type is not the hazard asked for**, or no event
formed, so the script is a smoke test for each category as well as a demo.

The report texts are synthetic, written for this script and labelled so on
every run. `flood` in `patna` sends the Patna demo's own five reports, at their
own coordinates, so `run_patna_demo.py` is this script with those arguments.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "http://localhost:8000"
RULE = "─" * 72
COMMANDER = ("commander", "commander123")

# Hardcoded events DEMO_MODE serves for an empty database; never a result.
DEMO_EVENT_CODE_PREFIX = "WX-EV-"

CITIES = {
    "patna": (25.5941, 85.1376),
    "delhi": (28.6139, 77.2090),
    "lucknow": (26.8467, 80.9462),
    "kolkata": (22.5726, 88.3639),
    "jaipur": (26.9124, 75.7873),
    "bikaner": (28.0229, 73.3119),
    "mumbai": (19.0760, 72.8777),
    "chennai": (13.0827, 80.2707),
    "amritsar": (31.6340, 74.8723),
    "bhubaneswar": (20.2961, 85.8245),
    "ahmedabad": (23.0225, 72.5714),
    "hyderabad": (17.3850, 78.4867),
}

# hazard → (the event type it must produce, scale of the spread in degrees
# relative to a flood: each family clusters over its own radius), five texts,
# an extra corroborating text (--corroborate) and an official dispatch (--official).
HAZARDS = {
    "flood": {
        "event_type": "URBAN_FLOOD",
        "spread": 1.0,
        "texts": [
            "Road waterlogged after heavy rain, autos stuck",
            "Water entered houses in our colony, knee deep",
            "Ghutno tak paani bhar gaya hai gali mein",
            "भारी बारिश के बाद मोहल्ले में जलभराव",
            "Underpass flooded, traffic diverted",
        ],
        "extra": "More water collecting near the market, still rising",
        "official": "District control room confirms waterlogging, SDRF team en route",
    },
    "heatwave": {
        "event_type": "HEATWAVE",
        "spread": 8.0,
        "texts": [
            "Extreme heat here, 46 degrees this afternoon",
            "Heatwave in the city, two labourers hospitalised with heatstroke",
            "46 degree hai, loo chal rahi hai, bahar mat niklo",
            "भीषण गर्मी, पारा 45 डिग्री के पार",
            "Scorching heat, roads empty by noon",
        ],
        "extra": "Unbearable heat in the old city, 45°C at 3 pm",
        "official": "District control room: heatwave conditions, cooling centres opened",
    },
    "fog": {
        "event_type": "FOG",
        "spread": 5.0,
        "texts": [
            "Dense fog on the highway, visibility under 50 m",
            "Thick fog this morning, trains running late",
            "Ghana kohra hai, kuch dikh nahi raha",
            "घना कोहरा छाया है, गाड़ियाँ रेंग रही हैं",
            "Visibility dropped to 100 m near the airport, dense fog",
        ],
        "extra": "Foggy morning, drivers crawling with hazard lights on",
        "official": "Traffic control room: dense fog, speed limits reduced on the expressway",
    },
    "thunderstorm": {
        "event_type": "THUNDERSTORM",
        "spread": 3.0,
        "texts": [
            "Severe thunderstorm with heavy rain here",
            "Loud thunder for the last half hour, heavy rain",
            "Garaj ke saath tez baarish ho rahi hai",
            "गरज के साथ बारिश शुरू",
            "Thunderstorm passing over the city right now",
        ],
        "extra": "Thunder and heavy showers across the city",
        "official": "District control room: thunderstorm over the city, power cut in parts",
    },
    "dust_storm": {
        "event_type": "DUST_STORM",
        "spread": 3.0,
        "texts": [
            "Dust storm hit the city, sky turned brown",
            "Tez aandhi aayi, dhool hi dhool",
            "धूल भरी आंधी चल रही है",
            "Massive duststorm, everything covered in sand",
            "Sandstorm across the outskirts, dust everywhere",
        ],
        "extra": "Thick wall of dust rolling in from the west",
        "official": "District control room: dust storm, flights on hold",
    },
    "strong_wind": {
        "event_type": "STRONG_WIND",
        "spread": 3.0,
        "texts": [
            "Strong winds uprooted trees on the main road",
            "Gusty winds, tin sheets flying off roofs",
            "Tez hawa chal rahi hai, hoarding gir gaya",
            "तेज़ हवा से कई पेड़ गिर गए",
            "Winds of 70 km/h here, poles down",
        ],
        "extra": "Very strong wind, trees fell on parked cars",
        "official": "District control room: strong winds, trees down on three roads",
    },
    "cold_wave": {
        "event_type": "COLD_WAVE",
        "spread": 8.0,
        "texts": [
            "Cold wave here, 3 degrees this morning",
            "Biting cold, people sitting around fires",
            "Kadaake ki thand hai, 4 degree subah",
            "शीतलहर से ठिठुरा शहर",
            "Ground frost in the fields, severe cold",
        ],
        "extra": "Freezing cold night, homeless people in shelters",
        "official": "District control room: cold wave, night shelters opened",
    },
}

# The Patna demo's reports, at their own coordinates (Kankarbagh, within ~2 km).
# The third carries the only depth phrase, which makes the event MODERATE on the
# depth axis. Kept verbatim so the Patna figures stay comparable.
PATNA_FLOOD = {
    "reports": [
        (25.5941, 85.1376, "Water entering ground floor shops near Kankarbagh main road"),
        (25.5955, 85.1390, "Kankarbagh underpass completely submerged, cars stuck"),
        (25.5930, 85.1360, "Knee deep water outside my house, drain overflowing"),
        (25.5968, 85.1402, "Flooding on the road to Patna junction, buses diverted"),
        (25.5920, 85.1345, "Sewage water mixed with rain water on the street here"),
    ],
    "extra": (25.5948, 85.1381, "More water collecting near the Kankarbagh community hall, still rising"),
    "official": (25.5949, 85.1381, "District control room confirms waterlogging at Kankarbagh, SDRF team en route"),
}

# Offsets from the city centre, in units of 0.001°, times the hazard's spread:
# about 0.5 km apart for a flood, a few km for a heatwave.
OFFSETS = [(0, 0), (4, 3), (-3, 4), (5, -4), (-4, -3), (2, -5), (-5, 1)]


def _request(api, method, path, payload=None, timeout=10, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"Content-Type": "application/json"} if data else {}
    all_headers.update(headers or {})
    req = urllib.request.Request(f"{api}{path}", data=data, method=method, headers=all_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, (json.loads(body) if body else None)


def _die(message):
    print(f"\n  ✘ {message}")
    sys.exit(1)


def plan_reports(hazard, city, corroborate):
    """[(lat, lng, text)] to send, and the official dispatch."""
    spec = HAZARDS[hazard]
    if hazard == "flood" and city == "patna":
        reports = list(PATNA_FLOOD["reports"]) + ([PATNA_FLOOD["extra"]] if corroborate else [])
        return reports, PATNA_FLOOD["official"]
    lat0, lng0 = CITIES[city]
    texts = list(spec["texts"]) + ([spec["extra"]] if corroborate else [])
    reports = [
        (round(lat0 + dy * 0.001 * spec["spread"], 5), round(lng0 + dx * 0.001 * spec["spread"], 5), t)
        for (dy, dx), t in zip(OFFSETS, texts)
    ]
    return reports, (lat0, lng0, spec["official"])


def preflight(api, title):
    print(RULE)
    print(f"  INDRA — {title} (live pipeline; the report texts are synthetic)")
    print(RULE)
    try:
        status, health = _request(api, "GET", "/healthz", timeout=5)
    except urllib.error.URLError as e:
        _die(f"backend not reachable at {api} — start it with ./start.sh -b ({e.reason})")
    print(f"  backend      {api}  →  {health.get('status')}")
    for name, check in sorted(health.get("checks", {}).items()):
        mark = "✓" if check.get("status") == "up" else "✘"
        print(f"    {mark} {name:14} {check.get('status')}")
    if status != 200:
        _die(f"/healthz returned {status} — a critical dependency is down")
    print()


def submit(api, reports, run_id):
    """Each report from its own reporter id, so each is an independent witness."""
    print(f"  Submitting {len(reports)} synthetic reports, each from its own reporter")
    dockets = []
    for i, (lat, lng, body) in enumerate(reports, start=1):
        try:
            status, res = _request(
                api, "POST", "/api/reports/submit",
                {"latitude": lat, "longitude": lng, "text": body},
                headers={"X-Reporter-Id": f"demo-{run_id}-{i}"},
            )
        except urllib.error.HTTPError as e:
            _die(f"submit returned {e.code} for {body[:40]!r}")
        if status != 202:
            _die(f"submit returned {status} for {body[:40]!r}")
        dockets.append(res["docket"])
        queued = "queued" if res.get("queued") else "stored; waiting for Kafka"
        print(f"    ✓ {res['docket']}  {queued:25} {body[:46]}")
    print()
    return dockets


def login(api, username, password):
    form = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{api}/api/auth/token", data=form, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        _die(f"login as {username!r} failed with HTTP {e.code}")


def submit_official(api, report):
    lat, lng, body = report
    token = login(api, *COMMANDER)
    print(f"  Filing one official dispatch as {COMMANDER[0]!r}")
    try:
        _, res = _request(
            api, "POST", "/api/reports/official",
            {"latitude": lat, "longitude": lng, "text": body},
            headers={"Authorization": f"Bearer {token}"},
        )
    except urllib.error.HTTPError as e:
        _die(f"official submit returned {e.code}")
    print(f"    ✓ {res.get('docket') or res['id'][:8]}  {res['source_type']}  {body[:46]}\n")
    return res.get("docket")


def follow(api, dockets, deadline_s):
    """
    Wait until every report has been processed, via its docket. Returns the
    event codes they joined (a report may legitimately stay alone or be
    suppressed as a duplicate; the script says so).
    """
    print(f"  Following the reports through the pipeline (up to {deadline_s}s)")
    started = time.monotonic()
    last = {}
    while time.monotonic() - started < deadline_s:
        for docket in dockets:
            try:
                _, track = _request(api, "GET", f"/api/reports/track/{docket}")
            except urllib.error.URLError:
                continue
            last[docket] = track
        codes = [t.get("event_code") for t in last.values() if t.get("event_code")]
        pending = [d for d in dockets if (last.get(d) or {}).get("status") in (None, "received", "queued")]
        if len(codes) == len(dockets) or (codes and not pending):
            break
        time.sleep(1.0)
    elapsed = time.monotonic() - started
    for docket in dockets:
        t = last.get(docket) or {}
        print(f"    {docket}  {t.get('status', '?'):12} {t.get('event_code') or ''}")
    print(f"    after {elapsed:.1f}s\n")
    return [t.get("event_code") for t in last.values() if t.get("event_code")]


def fetch_event(api, code):
    _, events = _request(api, "GET", f"/api/events?q={urllib.parse.quote(code)}")
    for event in events or []:
        if event.get("event_code") == code and not str(code).startswith(DEMO_EVENT_CODE_PREFIX):
            _, detail = _request(api, "GET", f"/api/events/{event['id']}")
            return detail
    return None


def show(detail):
    receipt = detail.get("verification_receipt") or {}
    print(RULE)
    print("  The event, as the API returns it")
    print(RULE)
    for label, key in [
        ("event code", "event_code"), ("event type", "event_type"), ("severity", "severity"),
        ("review status", "review_status"), ("quadrant", "quadrant"), ("confidence", "confidence_score"),
    ]:
        if detail.get(key) is not None:
            print(f"    {label:16} {detail[key]}")

    type_basis = receipt.get("event_type_basis") or {}
    if type_basis:
        print(f"\n    type rule        {type_basis.get('rule')}")
        print(f"      votes          {type_basis.get('votes')}")
        print(f"      untagged       {type_basis.get('reports_untagged')}")

    basis = receipt.get("severity_basis") or {}
    if basis:
        print(f"\n    severity rule    {basis.get('rule')}")
        print(f"      axis           {basis.get('axis')} = {basis.get('value')} "
              f"(from {basis.get('phrase')!r}) → {basis.get('content_axis')}")
        print(f"      count axis     {basis.get('count_axis')} ({basis.get('report_count')} reports)")
        floor = basis.get("impact_floor")
        if floor:
            print(f"      impact floor   {floor.get('severity')} (from {floor.get('phrase')!r})")

    density = receipt.get("density_basis") or {}
    if density:
        print(f"\n    witnesses        {density.get('reports')} reports, {density.get('n_eff')} independent "
              f"from {density.get('distinct_reporters')} reporters "
              f"({density.get('unverified_reporters')} unverified, {density.get('excluded')} excluded)")

    factors = receipt.get("factors") or []
    if factors:
        print(f"\n    {'factor':34} {'weight':>7} {'score':>7} {'points':>7}  state")
        for f in factors:
            print(f"    {f['factor'][:34]:34} {f['weight_pct']:6.1f}% {f['score']:7.4f} "
                  f"{f['weighted_points']:7.4f}  {f.get('state', '?')}")
    weather = receipt.get("weather") or {}
    if weather.get("note"):
        print(f"\n    weather          {weather['note']}")
    routing = receipt.get("routing") or {}
    if routing.get("caps"):
        print(f"    caps             {', '.join(routing['caps'])} (never auto-published)")
    print()


def show_heatmap(api):
    try:
        _, body = _request(api, "GET", "/api/geo/heatmap?resolution=8")
    except urllib.error.HTTPError as e:
        print(f"  heatmap        unavailable ({e.code})\n")
        return
    cells = body.get("cells", [])
    total = sum(c["report_count"] for c in cells)
    print(RULE)
    print(f"  Heat map — {len(cells)} H3 cell(s) at res {body['resolution']}, {total} report(s)")
    print(RULE)
    for c in cells[:6]:
        print(f"    {c['h3']}  reports={c['report_count']}  linked={c['linked_report_count']}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run one hazard's demo against a live backend.")
    ap.add_argument("--hazard", required=True, choices=sorted(HAZARDS))
    ap.add_argument("--city", required=True, choices=sorted(CITIES))
    ap.add_argument("--corroborate", action="store_true", help="send one extra corroborating report")
    ap.add_argument("--official", action="store_true",
                    help="also file one official dispatch as the demo commander (POST /api/reports/official)")
    ap.add_argument("--heatmap", action="store_true", help="print the H3 heat map afterwards")
    ap.add_argument("--wait", type=int, default=60, help="seconds to wait for the pipeline")
    ap.add_argument("--api", default=API)
    args = ap.parse_args(argv)

    expected = HAZARDS[args.hazard]["event_type"]
    preflight(args.api, f"{args.hazard.replace('_', ' ')} demo, {args.city.title()}")
    reports, official = plan_reports(args.hazard, args.city, args.corroborate)
    dockets = submit(args.api, reports, uuid.uuid4().hex[:12])
    if args.official:
        docket = submit_official(args.api, official)
        if docket:
            dockets.append(docket)

    codes = follow(args.api, dockets, args.wait)
    if not codes:
        _die("no event formed. Is the report consumer running, and is DEMO_MODE=false?")
    code = max(set(codes), key=codes.count)
    if len(set(codes)) > 1:
        print(f"  note: the reports joined {len(set(codes))} events {sorted(set(codes))}; showing {code}\n")

    detail = fetch_event(args.api, code)
    if detail is None:
        _die(f"event {code} not found through GET /api/events")
    show(detail)
    if args.heatmap:
        show_heatmap(args.api)

    got = detail.get("event_type")
    print(RULE)
    if got != expected:
        print(f"  ✘ expected a {expected} event, the pipeline made {got}")
        print(RULE)
        return 1
    print(f"  ✓ {expected}, as expected. Every number above was read back from the API;")
    print("    the report texts are synthetic.")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
