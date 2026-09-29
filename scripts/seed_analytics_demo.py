#!/usr/bin/env python3
"""
INDRA Platform — Analytics Demo Seed
Inserts realistic demo data for the three new analytics panels:
  1. Water Inundation Depth  (raw_reports.analysis->>'depth_cm')
  2. Top Impacted Districts  (verified_events.district / .severity)
  3. Verification Breakdown  (already has some data — this tops it up)

Safe to run multiple times: uses ON CONFLICT DO NOTHING on dockets and
event_codes. Does NOT touch existing rows.

Usage:
  python3 scripts/seed_analytics_demo.py
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg

# ── Connection ─────────────────────────────────────────────────────────────
DB_DSN = "postgresql://indra_user:indra_password@localhost:5433/indra_db"

# ── Realistic Indian flood-affected districts (2024 season) ────────────────
DISTRICTS = [
    ("Patna",         "Bihar"),
    ("Muzaffarpur",   "Bihar"),
    ("Darbhanga",     "Bihar"),
    ("Saharsa",       "Bihar"),
    ("Gaya",          "Bihar"),
    ("Varanasi",      "Uttar Pradesh"),
    ("Gorakhpur",     "Uttar Pradesh"),
    ("Allahabad",     "Uttar Pradesh"),
    ("Barpeta",       "Assam"),
    ("Dhubri",        "Assam"),
    ("Morigaon",      "Assam"),
    ("Dibrugarh",     "Assam"),
    ("Khurda",        "Odisha"),
    ("Cuttack",       "Odisha"),
    ("Puri",          "Odisha"),
    ("Surat",         "Gujarat"),
    ("Vadodara",      "Gujarat"),
    ("Kolkata",       "West Bengal"),
    ("Howrah",        "West Bengal"),
    ("Chennai",       "Tamil Nadu"),
]

SEVERITIES    = ["CRITICAL", "HIGH", "MODERATE", "ADVISORY"]
SEV_WEIGHTS   = [0.20, 0.30, 0.35, 0.15]   # realistic: more moderate than critical
REVIEW_STATUS = ["AUTO_PUBLISHED", "HUMAN_APPROVED"]
RS_WEIGHTS    = [0.65, 0.35]               # most go auto

EVENT_TYPES = [
    "URBAN_FLOOD", "URBAN_FLOOD", "URBAN_FLOOD",   # weight floods heavily
    "RIVER_BREACH", "RIVER_BREACH",
    "LANDSLIDE", "CLOUDBURST", "RAINFALL",
]

QUADRANTS = [
    "Critical Verified Event",
    "Unverified Threat",
    "Confirmed Minor Event",
    "Noise",
]

VERDICTS = ["CORROBORATED", "UNCONFIRMED"]

SOURCE_TYPES = [
    "CITIZEN_APP", "CITIZEN_APP", "CITIZEN_APP",   # majority citizen
    "OFFICIAL_DISPATCH", "SOCIAL_MEDIA", "NEWS_MEDIA",
]

# Depth distribution we want to see in the chart
#   < 15 cm  : ~25 reports
#   15-30 cm : ~40 reports
#   30-60 cm : ~35 reports
#   60-120 cm: ~20 reports
#   > 120 cm : ~10 reports
DEPTH_DISTRIBUTION = (
    [(random.uniform(1,  14.9)) for _ in range(25)] +
    [(random.uniform(15, 29.9)) for _ in range(40)] +
    [(random.uniform(30, 59.9)) for _ in range(35)] +
    [(random.uniform(60,119.9)) for _ in range(20)] +
    [(random.uniform(120,300))  for _ in range(10)]
)
random.shuffle(DEPTH_DISTRIBUTION)


def weighted_choice(items, weights):
    r = random.random()
    cumulative = 0.0
    for item, w in zip(items, weights):
        cumulative += w
        if r < cumulative:
            return item
    return items[-1]


def now_ish(offset_hours=0):
    return datetime.now(timezone.utc) - timedelta(hours=offset_hours)


async def main():
    print("Connecting to", DB_DSN.split("@")[1])
    conn = await asyncpg.connect(DB_DSN)

    try:
        # ── 1. Insert verified_events with realistic districts ──────────────
        print("\n── Step 1: verified_events with districts ──")
        events_inserted = 0
        # Build a district→count distribution (top districts get more events)
        district_weights = [
            20, 17, 15, 12, 10,   # top 5 (Bihar, Assam) heavy
             8,  7,  6,  5,  4,
             3,  3,  2,  2,  2,
             2,  1,  1,  1,  1,
        ]
        for (district, state), count in zip(DISTRICTS, district_weights):
            for i in range(count):
                sev  = weighted_choice(SEVERITIES, SEV_WEIGHTS)
                rs   = weighted_choice(REVIEW_STATUS, RS_WEIGHTS)
                etype  = random.choice(EVENT_TYPES)
                quad   = random.choice(QUADRANTS)
                verdict = "CORROBORATED" if sev in ("CRITICAL", "HIGH") else "UNCONFIRMED"

                # High-severity events tend to have higher confidence
                if sev == "CRITICAL":
                    conf = round(random.uniform(0.70, 0.99), 4)
                elif sev == "HIGH":
                    conf = round(random.uniform(0.55, 0.90), 4)
                else:
                    conf = round(random.uniform(0.35, 0.75), 4)

                # AUTO_PUBLISHED needs higher confidence
                if rs == "AUTO_PUBLISHED" and conf < 0.60:
                    conf = round(random.uniform(0.60, 0.95), 4)

                event_code = f"DEMO-{uuid.uuid4().hex[:8].upper()}"
                eid = uuid.uuid4()
                verified_at = now_ish(random.uniform(0, 72))
                updated_at  = verified_at

                receipt = {
                    "pipeline_version": "3.2",
                    "confidence_score": conf,
                    "factors": {
                        "weather_score": round(random.uniform(0.5, 1.0), 3),
                        "report_density": round(random.uniform(0.3, 1.0), 3),
                        "credibility_avg": round(random.uniform(0.5, 1.0), 3),
                    },
                    "decision": rs,
                }

                await conn.execute("""
                    INSERT INTO verified_events (
                        id, event_code, event_type, severity, confidence_score,
                        review_status, quadrant, district, state,
                        place_precision, hazard_family, verdict,
                        verification_receipt, verified_at, updated_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15
                    )
                    ON CONFLICT (event_code) DO NOTHING
                """,
                    eid, event_code, etype, sev, conf,
                    rs, quad, district, state,
                    "district", "FLOOD", verdict,
                    json.dumps(receipt), verified_at, updated_at,
                )
                events_inserted += 1


        print(f"  → {events_inserted} verified_events rows inserted (ON CONFLICT DO NOTHING)")

        # ── 2. Insert raw_reports with depth_cm in analysis JSON ────────────
        print("\n── Step 2: raw_reports with depth_cm ──")
        reports_inserted = 0

        # Sample report texts with realistic depth mentions
        TEMPLATES = [
            "Water level reached {d} cm near {place}, roads submerged.",
            "Flood depth approx {d} cm outside our building in {place}.",
            "Standing water {d} cm deep on highway near {place}, vehicles stranded.",
            "River breach — {d} cm inundation in {place} ward.",
            "पानी का स्तर {d} सेमी, {place} में नावें चल रही हैं।",
            "Flood depth {d} cm, requesting relief team to {place}.",
            "Ground floor submerged, water depth {d} cm, {place}.",
        ]
        PLACES = [d[0] for d in DISTRICTS] + [
            "Rajendra Nagar", "Gandhi Ghat", "Kankarbagh",
            "Boring Road", "Bailey Road", "Ashok Rajpath",
        ]

        for depth_cm in DEPTH_DISTRIBUTION:
            place = random.choice(PLACES)
            text  = random.choice(TEMPLATES).format(d=int(depth_cm), place=place)
            src   = random.choice(SOURCE_TYPES)
            cred  = round(random.uniform(0.4, 0.9), 4)
            created_at = now_ish(random.uniform(0, 168))   # up to 1 week ago
            docket = f"R-DEMO{uuid.uuid4().hex[:7].upper()}"
            rid = uuid.uuid4()

            # NLP extraction result
            analysis = {
                "cleaned_text":  text,
                "language":      "en" if not "पानी" in text else "hi",
                "depth_cm":      round(depth_cm, 1),
                "depth_basis":   "explicit_mention",
                "keywords":      ["flood", "water", "inundation"],
                "places":        [place],
                "url_count":     0,
                "phone_count":   0,
                "extracted_at":  created_at.isoformat(),
            }

            district, state = random.choice(DISTRICTS)

            await conn.execute("""
                INSERT INTO raw_reports (
                    id, created_at, source_type, raw_text,
                    district, state, credibility_score,
                    analysis, docket, place_precision,
                    hazard_primary, hazard_family
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12
                )
                ON CONFLICT (docket) DO NOTHING
            """,
                rid, created_at, src, text,
                district, state, cred,
                json.dumps(analysis), docket, "district",
                "FLOOD", "FLOOD",
            )
            reports_inserted += 1

        print(f"  → {reports_inserted} raw_reports rows inserted (with depth_cm)")

        # ── 3. Quick verification ───────────────────────────────────────────
        print("\n── Step 3: Verifying data ──")

        depth_rows = await conn.fetch("""
            SELECT
                CASE
                    WHEN (analysis->>'depth_cm')::numeric < 15  THEN '< 15 cm'
                    WHEN (analysis->>'depth_cm')::numeric < 30  THEN '15-30 cm'
                    WHEN (analysis->>'depth_cm')::numeric < 60  THEN '30-60 cm'
                    WHEN (analysis->>'depth_cm')::numeric < 120 THEN '60-120 cm'
                    ELSE '> 120 cm'
                END AS bucket,
                COUNT(*) AS n
            FROM raw_reports
            WHERE analysis IS NOT NULL AND analysis->>'depth_cm' IS NOT NULL
              AND duplicate_of IS NULL
            GROUP BY 1
            ORDER BY MIN((analysis->>'depth_cm')::numeric)
        """)
        print("  Inundation depth buckets:")
        for r in depth_rows:
            print(f"    {r['bucket']:>12}  {r['n']:>5} reports")

        top_dist = await conn.fetch("""
            SELECT district, COUNT(*) AS n
            FROM verified_events
            WHERE review_status IN ('AUTO_PUBLISHED','HUMAN_APPROVED')
              AND district IS NOT NULL
            GROUP BY district
            ORDER BY n DESC
            LIMIT 5
        """)
        print("  Top 5 districts:")
        for r in top_dist:
            print(f"    {r['district']:<20}  {r['n']:>3} events")

        vb = await conn.fetch("""
            SELECT
                CASE
                    WHEN confidence_score < 0.2 THEN '0.0-0.2'
                    WHEN confidence_score < 0.4 THEN '0.2-0.4'
                    WHEN confidence_score < 0.6 THEN '0.4-0.6'
                    WHEN confidence_score < 0.8 THEN '0.6-0.8'
                    ELSE '0.8-1.0'
                END AS bucket,
                COUNT(*) AS n
            FROM verified_events
            WHERE review_status != 'REJECTED'
            GROUP BY 1
            ORDER BY MIN(confidence_score)
        """)
        print("  Confidence score buckets:")
        for r in vb:
            print(f"    {r['bucket']:>10}  {r['n']:>4} events")

        print("\n✅ Demo seed complete. Reload the Analytics page to see the charts.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
