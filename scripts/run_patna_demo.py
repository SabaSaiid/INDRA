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
    ./start.sh -b                       # backend must be running (-b = background)
    .venv/bin/python ../scripts/run_patna_demo.py
    .venv/bin/python ../scripts/run_patna_demo.py --corroborate  # one extra report
    .venv/bin/python ../scripts/run_patna_demo.py --official     # + one official dispatch

Exit code is non-zero if the demo did not produce an event, so it can be used as
a smoke test rather than only read by a human.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
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

# One more corroborating report, sent with --corroborate.
#
# This used to be called OFFICIAL and was described as raising source reliability
# from 0.60 to 1.00. That was wrong, and running it is what showed it:
# POST /api/reports/submit stamps every report CITIZEN_APP (reports.py:159), so
# the "district control room" text arrived with citizen reliability like any other
# and the receipt's cluster block read ["CITIZEN_APP"].
#
# The hardcoding is deliberate and correct -- if a client could declare its own
# source_type, anyone could claim OFFICIAL_DISPATCH and award itself the model's
# highest trust weight, and the factor would measure what a reporter says about
# itself. So this flag adds corroboration, which on a dry day is the lever that
# moves the score. Raising source reliability is --official, below.
EXTRA_REPORT = (
    25.5948,
    85.1381,
    "More water collecting near the Kankarbagh community hall, still rising",
)

# One field dispatch, sent with --official through the authenticated route
# (POST /api/reports/official, BUG-025). The script logs in as the demo
# commander, so the report is stored OFFICIAL_DISPATCH with submitted_by
# "commander" and lifts source reliability to 1.00. It is still one report in
# the cluster: it does not bypass corroboration, weather or review.
OFFICIAL_REPORT = (
    25.5949,
    85.1381,
    "District control room confirms waterlogging at Kankarbagh, SDRF team en route",
)
COMMANDER = ("commander", "commander123")

RULE = "─" * 72

# Hardcoded demo events in app/api/events.py, served when DEMO_MODE is true and a
# read finds no rows. Their confidences (0.94, 0.91, ...) are values the real
# pipeline cannot reach, so seeing one means the script is being shown demo data,
# not a result. Recognised by event_code so it can be named in the error.
DEMO_EVENT_CODE_PREFIX = "WX-EV-"


def _request(method, path, payload=None, timeout=10, headers=None):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"Content-Type": "application/json"} if data else {}
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
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
        _die(f"backend not reachable at {API} — start it with ./start.sh -b ({e.reason})")
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


def login(username, password):
    """A bearer token from POST /api/auth/token (form-encoded, OAuth2 password flow)."""
    form = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{API}/api/auth/token", data=form, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        _die(f"login as {username!r} failed with HTTP {e.code}")


def submit_official(report):
    lat, lng, body = report
    token = login(*COMMANDER)
    print(f"  Filing one official dispatch as {COMMANDER[0]!r}")
    try:
        status, res = _request(
            "POST", "/api/reports/official",
            {"latitude": lat, "longitude": lng, "text": body},
            headers={"Authorization": f"Bearer {token}"},
        )
    except urllib.error.HTTPError as e:
        _die(f"official submit returned {e.code}")
    print(f"    ✓ {res['id'][:8]}  {res['source_type']}  {body[:46]}")
    print()
    return res["id"]


def _is_computed(event):
    """
    True only for an event this pipeline actually produced.

    With DEMO_MODE=true, GET /api/events answers an *empty* database with
    hardcoded demo events -- and during the first seconds of a run the database is
    empty, so the endpoint legitimately returns invented data. Those events carry
    no `factors` block, so the presence of a real receipt is what separates a
    computed event from a narrated one.

    Without this check the script reported WX-EV-28231827-A at confidence 0.94,
    AUTO_PUBLISHED, 0.0s after submitting -- a value the real pipeline cannot
    reach. Narrating that to a nodal officer as a live result is the exact
    dishonesty this script was rewritten to remove, so it verifies rather than
    trusts.
    """
    if str(event.get("event_code", "")).startswith(DEMO_EVENT_CODE_PREFIX):
        return False
    try:
        _, detail = _request("GET", f"/api/events/{event['id']}")
    except urllib.error.HTTPError:
        return False
    receipt = detail.get("verification_receipt") or {}
    return "factor_coverage" in receipt and bool(receipt.get("factors"))


def wait_for_event(deadline_s=45):
    """Poll /api/events until the pipeline has fused something real."""
    print(f"  Waiting for the pipeline (up to {deadline_s}s)")
    started = time.monotonic()
    saw_demo = False

    while time.monotonic() - started < deadline_s:
        try:
            _, events = _request("GET", "/api/events")
        except urllib.error.URLError:
            events = None

        for event in events or []:
            if _is_computed(event):
                elapsed = time.monotonic() - started
                print(f"    ✓ event after {elapsed:.1f}s\n")
                return event, elapsed
            saw_demo = True

        if saw_demo:
            print("    … ignoring demo-mode placeholder events "
                  "(set DEMO_MODE=false — see bug.md BUG-024)")
            saw_demo = False
        time.sleep(1.0)

    _die(
        f"no computed event after {deadline_s}s.\n"
        "    Checks: is the report consumer running? is exactly one backend attached\n"
        "    to the broker (lsof -i :8000)? is DEMO_MODE=false so that an empty\n"
        "    database is not answered with invented events?"
    )


def settle(event, quiet_for=4.0, limit_s=30.0):
    """
    Wait until the event stops growing before printing it.

    Reports are consumed one at a time, so a cluster is still absorbing members
    for a few seconds after the first event appears. Printed too early the demo
    shows "3 reports, confidence 0.4585" and a refresh a moment later shows
    "5 reports, 0.4984" — which looks like the number is unstable when it is
    simply still arriving. Measured on a local stack: all five land within ~8s.

    Polls the receipt's cluster size until it has held steady for `quiet_for`
    seconds. It reads verification_receipt.cluster.size rather than a top-level
    report_count, because GET /api/events/{id} does not return one — a first
    version of this function polled `detail["report_count"]`, got None every time,
    and reported "steady at None report(s)" while measuring nothing at all.
    """
    print(f"  Letting the cluster settle (quiet for {quiet_for:.0f}s)")
    last, stable_since = None, time.monotonic()
    started = time.monotonic()

    while time.monotonic() - started < limit_s:
        try:
            _, detail = _request("GET", f"/api/events/{event['id']}")
        except urllib.error.URLError:
            break

        receipt = detail.get("verification_receipt") or {}
        count = (receipt.get("cluster") or {}).get("size")
        if count is None:
            print("    … no cluster size in the receipt yet")
            time.sleep(1.0)
            continue

        if count != last:
            if last is not None:
                print(f"    cluster size {last} → {count}")
            last, stable_since = count, time.monotonic()
        elif time.monotonic() - stable_since >= quiet_for:
            print(f"    ✓ steady at {count} report(s)\n")
            return
        time.sleep(1.0)

    print(f"    … still changing after {limit_s:.0f}s; printing anyway\n")


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
    ap.add_argument("--corroborate", action="store_true",
                    help="submit one extra corroborating citizen report, raising the "
                         "report-density factor")
    ap.add_argument("--official", action="store_true",
                    help="also file one official dispatch as the demo commander through "
                         "POST /api/reports/official, lifting source reliability to 1.00")
    ap.add_argument("--wait", type=int, default=45, help="seconds to wait for an event")
    args = ap.parse_args()

    preflight()
    reports = list(REPORTS) + ([EXTRA_REPORT] if args.corroborate else [])
    submit(reports)
    if args.official:
        submit_official(OFFICIAL_REPORT)
    event, _ = wait_for_event(args.wait)
    settle(event)
    detail = show_event(event)
    show_heatmap()

    print(RULE)
    status = detail.get("review_status")
    if status == "QUARANTINED":
        print("  Read: a handful of unverified citizen reports is not a verified disaster.")
        print("  Quarantined is the correct verdict, not a failure — and the receipt above")
        print("  shows exactly which evidence produced it.")
        print()
        print("  What would raise it: more independent reports (the density factor), real")
        print("  rainfall (the weather factor, live from Open-Meteo), or a report from a")
        print("  trusted source. Citizens cannot claim that last one — the public route is")
        print("  always CITIZEN_APP — so it comes through POST /api/reports/official, which")
        print("  needs a commander's token and records who filed it (--official).")
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
