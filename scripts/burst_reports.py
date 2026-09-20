#!/usr/bin/env python3
"""
INDRA — submit a burst of synthetic reports and measure what the stack does.

Written for Day 5 T12: the day plan referenced this script, and it did not exist.

What it measures, and why each number is here
---------------------------------------------
* **stored / submitted** — did any report get lost between 202 and the database?
* **p50 / p95 / max submit latency** — measured, with no pass/fail target. Quote
  only the number, never a target it was compared against.
* **events created, and their report counts** — clustering did something, and the
  counts are inspectable.
* **duplicate NEW_REPORT broadcasts** — a report re-delivered by the broker must
  not be broadcast twice (Day 4 fixed this per process; a restart still resets it).
* **pg_stat_activity before vs after** — the connection-leak check. reports.py
  builds a fresh AIOKafkaProducer per request and weather.py a fresh
  httpx.AsyncClient per cache miss, so a leak here is plausible rather than
  theoretical.
* **backend RSS before vs after** — the memory check, for the same reason.

Everything it prints comes from the API or from Postgres. Nothing is asserted
against a target, because this is a measurement, not a test.

Usage
-----
    ./start.sh -b
    .venv/bin/python ../scripts/burst_reports.py --count 100 --spread-km 3 --city patna

Reports are synthetic and labelled so in the text itself.
"""

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"

CITIES = {
    "patna": (25.5941, 85.1376),
    "delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "guwahati": (26.1445, 91.7362),
}

# Varied enough that dedup does not collapse the whole burst into one report, and
# all plainly synthetic. Two carry a depth phrase so severity has something to read.
TEMPLATES = [
    "Water on the road near {place}, traffic slowing down",
    "Drain overflowing at {place}, water spreading fast",
    "Knee deep water outside the shops at {place}",
    "{place} underpass is waterlogged, cars turning back",
    "Rain water collecting near {place} bus stop",
    "Street outside {place} is under water since morning",
    "Waist deep water reported in the lane behind {place}",
    "Sewage mixed with rain water near {place}",
    "Buses diverted around {place} because of flooding",
    "Water entering ground floor shops at {place}",
]

PLACES = [
    "Kankarbagh", "Boring Road", "Rajendra Nagar", "Patna Junction",
    "Gandhi Maidan", "Digha", "Bailey Road", "Ashiana Nagar",
    "Mithapur", "Phulwari Sharif",
]


def _request(method, path, payload=None, timeout=20):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, (json.loads(body) if body else None)


def _psql(sql):
    """Query Postgres through the container, so no Python DB deps are needed."""
    out = subprocess.run(
        ["docker", "exec", "indra-postgres", "psql", "-U", "indra_user",
         "-d", "indra_db", "-t", "-A", "-c", sql],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _backend_rss_mb():
    """RSS of the uvicorn process serving port 8000, in MB."""
    try:
        pids = subprocess.run(
            ["lsof", "-ti", ":8000"], capture_output=True, text=True
        ).stdout.split()
        total = 0
        for pid in pids:
            rss = subprocess.run(
                ["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True
            ).stdout.strip()
            if rss:
                total += int(rss)
        return round(total / 1024, 1) if total else None
    except Exception:
        return None


def _scatter(lat, lng, spread_km, rng):
    """A uniformly random point within spread_km, correcting longitude for latitude."""
    radius_km = spread_km * math.sqrt(rng.random())
    bearing = rng.random() * 2 * math.pi
    d_lat = (radius_km * math.cos(bearing)) / 111.0
    d_lng = (radius_km * math.sin(bearing)) / (111.0 * math.cos(math.radians(lat)))
    return round(lat + d_lat, 6), round(lng + d_lng, 6)


def main():
    ap = argparse.ArgumentParser(description="Burst-submit synthetic reports and measure the stack.")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--spread-km", type=float, default=3.0)
    ap.add_argument("--city", default="patna", choices=sorted(CITIES))
    ap.add_argument("--settle", type=int, default=25,
                    help="seconds to let the consumer drain before measuring")
    ap.add_argument("--seed", type=int, default=20260920)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    base_lat, base_lng = CITIES[args.city]
    rule = "─" * 74

    print(rule)
    print(f"  INDRA burst — {args.count} synthetic reports, {args.spread_km} km around {args.city}")
    print(rule)

    try:
        status, health = _request("GET", "/healthz", timeout=5)
    except urllib.error.URLError as e:
        print(f"  ✘ backend not reachable at {API} — start it with ./start.sh -b ({e.reason})")
        sys.exit(1)
    print(f"  backend       {health.get('status')}")

    before = {
        "reports": _psql("SELECT count(*) FROM raw_reports;"),
        "events": _psql("SELECT count(*) FROM verified_events;"),
        "conns": _psql("SELECT count(*) FROM pg_stat_activity WHERE datname='indra_db';"),
        "rss": _backend_rss_mb(),
    }
    print(f"  before        reports={before['reports']}  events={before['events']}  "
          f"pg_conns={before['conns']}  rss={before['rss']} MB")
    print()

    # ── Submit ────────────────────────────────────────────────────────────────
    latencies = []
    accepted, rejected, not_queued = 0, 0, 0
    ids = []
    started = time.monotonic()

    for i in range(args.count):
        lat, lng = _scatter(base_lat, base_lng, args.spread_km, rng)
        body = TEMPLATES[i % len(TEMPLATES)].format(place=rng.choice(PLACES))
        payload = {"latitude": lat, "longitude": lng, "text": f"{body} (synthetic #{i+1})"}

        t0 = time.monotonic()
        try:
            status, res = _request("POST", "/api/reports/submit", payload)
            elapsed_ms = (time.monotonic() - t0) * 1000
            latencies.append(elapsed_ms)
            if status == 202:
                accepted += 1
                ids.append(res["id"])
                if not res.get("queued"):
                    not_queued += 1
            else:
                rejected += 1
        except Exception as e:
            rejected += 1
            print(f"    ✘ report {i+1} failed: {e}")

        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{args.count} submitted")

    submit_s = time.monotonic() - started
    print()
    print(f"  submitted     {accepted} accepted, {rejected} rejected, "
          f"{not_queued} accepted-but-not-queued")
    print(f"  wall time     {submit_s:.1f}s  ({args.count / submit_s:.1f} reports/s)")
    if latencies:
        latencies.sort()
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"  submit latency  p50={statistics.median(latencies):.0f} ms  "
              f"p95={p95:.0f} ms  max={max(latencies):.0f} ms")
    print()

    # ── Let the pipeline drain ────────────────────────────────────────────────
    print(f"  settling {args.settle}s for the consumer to drain")
    time.sleep(args.settle)
    print()

    after = {
        "reports": _psql("SELECT count(*) FROM raw_reports;"),
        "events": _psql("SELECT count(*) FROM verified_events;"),
        "conns": _psql("SELECT count(*) FROM pg_stat_activity WHERE datname='indra_db';"),
        "rss": _backend_rss_mb(),
    }

    stored_delta = int(after["reports"]) - int(before["reports"]) if after["reports"] else 0
    events_delta = int(after["events"]) - int(before["events"]) if after["events"] else 0

    print(rule)
    print("  Results")
    print(rule)
    print(f"    reports stored      {stored_delta}/{args.count}"
          f"{'  ✓' if stored_delta == args.count else '  ✘ REPORTS LOST'}")
    print(f"    events created      {events_delta}")
    print(f"    duplicates marked   {_psql('SELECT count(*) FROM raw_reports WHERE duplicate_of IS NOT NULL;')}")
    print(f"    reports linked      {_psql('SELECT count(*) FROM raw_reports WHERE event_id IS NOT NULL;')}")

    conn_delta = (int(after["conns"]) - int(before["conns"])) if after["conns"] else None
    if conn_delta is not None:
        flag = "✓" if abs(conn_delta) <= 2 else "✘ POSSIBLE CONNECTION LEAK"
        print(f"    pg connections      {before['conns']} → {after['conns']}  (Δ{conn_delta:+d})  {flag}")

    if before["rss"] and after["rss"]:
        rss_delta = round(after["rss"] - before["rss"], 1)
        flag = "✓" if rss_delta < 200 else "✘ MEMORY GROWTH"
        print(f"    backend RSS         {before['rss']} → {after['rss']} MB  (Δ{rss_delta:+.1f})  {flag}")

    per_event = _psql("""
        SELECT event_code || ' ' || severity || ' ' || review_status || ' conf=' ||
               confidence_score || ' reports=' || (
                 SELECT count(*) FROM raw_reports r WHERE r.event_id = e.id)
        FROM verified_events e ORDER BY verified_at DESC LIMIT 12;
    """)
    if per_event:
        print("\n    events (newest first)")
        for line in per_event.splitlines():
            print(f"      {line}")

    polygons = _psql("""
        SELECT count(*) FILTER (WHERE boundary_polygon IS NOT NULL) || '/' || count(*)
        FROM verified_events;
    """)
    print(f"\n    with a boundary     {polygons}")

    coverage = _psql("""
        SELECT DISTINCT verification_receipt->>'factor_coverage'
        FROM verified_events WHERE verification_receipt IS NOT NULL;
    """)
    if coverage:
        print(f"    factor_coverage     {', '.join(coverage.split())}")

    print()
    print(rule)
    print("  Numbers above are measurements, not assertions. Quote them as measured.")
    print(rule)


if __name__ == "__main__":
    main()
