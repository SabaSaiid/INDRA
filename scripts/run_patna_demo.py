#!/usr/bin/env python3
"""
INDRA — the Patna demo, run against the live backend.

Posts five citizen reports to POST /api/reports/submit, waits for the pipeline to
fuse them, then reads the event back and prints only what the API returned.

What this replaces, and why
---------------------------
Until 20 Sep this script printed a hand-written narrative from
`data/samples/patna_flood_scenario.json`: 127 signals, confidence 0.94,
AUTO_PUBLISHED, "IMD AWS recorded 92mm rainfall", two "CWC river level sensors",
ten "verified multimedia evidence". It made no HTTP call, no Kafka produce and no
database write — it exercised nothing, and several of its claims contradicted the
code it was standing in front of (there is no IMD or CWC feed, vision analysis is
permanently offline, and the real pipeline cannot reach 0.94).

So every number printed below is read back from the API. If the pipeline is
broken, this script shows it instead of hiding it. Nothing here is hard-coded
except the five report texts, which are labelled synthetic.

Usage
-----
    ./start.sh bg                       # backend must be running
    .venv/bin/python ../scripts/run_patna_demo.py
    .venv/bin/python ../scripts/run_patna_demo.py --official   # add the dispatch

Exit code is non-zero if the demo did not produce an event, so it can be used as
a smoke test rather than only read by a human.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"

# Synthetic reports, written for this demo. Kankarbagh, Patna, within ~2 km.
# The third one carries the only depth phrase, which is what makes the event
# MODERATE on the depth axis rather than ADVISORY.
REPORTS = [
    (25.5941, 85.1376, "Water entering ground floor shops near Kankarbagh main road"),
    (25.5955, 85.1390, "Kankarbagh underpass completely submerged, cars stuck"),
    (25.5930, 85.1360, "Knee deep water outside my house, drain overflowing"),
    (25.5968, 85.1402, "Flooding on the road to Patna junction, buses diverted"),
    (25.5920, 85.1345, "Sewage water mixed with rain water on the street here"),
]

# An official dispatch raises source reliability from 0.60 to 1.00, which is the
# escalation step of the demo. Only sent with --official.
OFFICIAL = (
    25.5948,
    85.1381,
    "District control room confirms waterlogging in Kankarbagh, pumps deployed",
)

RULE = "─" * 72


def _request(method, path, payload=None, timeout=10):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, (json.loads(body) if body else None)


def _die(message):
    print(f"\n  ✘ {message}")
    sys.exit(1)


def preflight():
    print(RULE)
    print("  INDRA — Patna urban flood demo (live pipeline)")
    print(RULE)
    try:
        status, health = _request("GET", "/healthz", timeout=5)
    except urllib.error.URLError as e:
        _die(f"backend not reachable at {API} — start it with ./start.sh bg ({e.reason})")
        return

    state = health.get("status")
    print(f"  backend      {API}  →  {state}")
    for name, check in sorted(health.get("checks", {}).items()):
        mark = "✓" if check.get("status") == "up" else "✘"
        print(f"    {mark} {name:14} {check.get('status')}")
    if status != 200:
        _die(f"/healthz returned {status} — a critical dependency is down")
    print()


def submit(reports):
    print("  Submitting reports")
    ids = []
    for lat, lng, body in reports:
        status, res = _request(
            "POST", "/api/reports/submit",
            {"latitude": lat, "longitude": lng, "text": body},
        )
        if status != 202:
            _die(f"submit returned {status} for {body[:40]!r}")
        ids.append(res["id"])
        queued = "queued" if res.get("queued") else "NOT queued (broker down)"
        print(f"    ✓ {res['id'][:8]}  {queued}  {body[:46]}")
    print()
    return ids


def wait_for_event(deadline_s=45):
    """Poll /api/events until the pipeline has fused something."""
    print(f"  Waiting for the pipeline (up to {deadline_s}s)")
    started = time.monotonic()
    while time.monotonic() - started < deadline_s:
        try:
            _, events = _request("GET", "/api/events")
        except urllib.error.URLError:
            events = None
        if events:
            elapsed = time.monotonic() - started
            print(f"    ✓ event after {elapsed:.1f}s\n")
            return events[0], elapsed
        time.sleep(1.0)
    _die(
        f"no event after {deadline_s}s — check the consumer is running and that "
        "exactly one backend process is attached to the broker"
    )


def show_event(event):
    """Print the event and its receipt, entirely from the API response."""
    _, detail = _request("GET", f"/api/events/{event['id']}")
    receipt = detail.get("verification_receipt") or {}

    print(RULE)
    print("  Verified event")
    print(RULE)
    for label, key in [
        ("event code", "event_code"),
        ("severity", "severity"),
        ("review status", "review_status"),
        ("quadrant", "quadrant"),
        ("report count", "report_count"),
    ]:
        if detail.get(key) is not None:
            print(f"    {label:16} {detail[key]}")

    confidence = detail.get("confidence_score")
    coverage = receipt.get("factor_coverage")
    total = receipt.get("total_weighted")
    print(f"    {'confidence':16} {confidence}")
    if coverage is not None:
        print(f"    {'factor coverage':16} {coverage}")
        if total is not None:
            print(f"    {'':16} = {total} points measured out of {coverage} available")

    factors = receipt.get("factors") or []
    if factors:
        print(f"\n    {'factor':34} {'weight':>7} {'score':>7} {'points':>7}  state")
        for f in factors:
            print(
                f"    {f['factor'][:34]:34} {f['weight_pct']:6.1f}% "
                f"{f['score']:7.4f} {f['weighted_points']:7.4f}  {f.get('state','?')}"
            )

    basis = receipt.get("severity_basis")
    if basis:
        print(f"\n    severity rule    {basis.get('rule')}")
        print(f"      depth axis     {basis.get('depth_axis')} "
              f"(max {basis.get('max_depth_cm')} cm from {basis.get('depth_basis')})")
        print(f"      count axis     {basis.get('count_axis')} "
              f"({basis.get('report_count')} reports)")

    provenance = receipt.get("provenance") or {}
    if provenance:
        offline = [k for k, v in provenance.items() if v == "offline"]
        print(f"\n    offline factors  {', '.join(offline) if offline else 'none'}")
        print("      (vision_analysis and anomaly_detection are permanently offline —")
        print("       layer 4 is out of scope, and the receipt says so rather than faking a score)")

    if detail.get("boundary_geojson"):
        geo = detail["boundary_geojson"]
        geo = json.loads(geo) if isinstance(geo, str) else geo
        ring = geo.get("coordinates", [[]])[0]
        print(f"\n    boundary         {geo.get('type')}, {len(ring)} vertices")
    else:
        print("\n    boundary         none")
    print()
    return detail


def show_heatmap():
    try:
        _, body = _request("GET", "/api/geo/heatmap?resolution=8")
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


def main():
    ap = argparse.ArgumentParser(description="Run the Patna demo against a live backend.")
    ap.add_argument("--official", action="store_true",
                    help="also submit an official dispatch report, which raises source "
                         "reliability to 1.00 and should push the event over the review gate")
    ap.add_argument("--wait", type=int, default=45, help="seconds to wait for an event")
    args = ap.parse_args()

    preflight()
    reports = list(REPORTS) + ([OFFICIAL] if args.official else [])
    submit(reports)
    event, _ = wait_for_event(args.wait)
    detail = show_event(event)
    show_heatmap()

    print(RULE)
    status = detail.get("review_status")
    if status == "QUARANTINED":
        print("  Read: five unverified citizen reports and light rain is not a verified")
        print("  disaster. Re-run with --official to add a district control room dispatch")
        print("  and watch the score cross the review gate.")
    elif status == "PENDING_HUMAN_REVIEW":
        print("  Read: corroborated enough to reach an operator, not enough to publish")
        print("  itself. An operator now approves or rejects it via")
        print("  PATCH /api/events/{id}/review, and that decision is hash-chained.")
    elif status == "AUTO_PUBLISHED":
        print("  Read: above the 0.90 auto-publish gate.")
    print(RULE)
    print("  Every number above was read back from the API. Report texts are synthetic;")
    print("  the rainfall factor is live Open-Meteo data.")
    print(RULE)


if __name__ == "__main__":
    main()
