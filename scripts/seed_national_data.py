#!/usr/bin/env python3
"""
INDRA Platform — National Seed Data Generator
Generates realistic multi-city sample data across 10 Indian cities.

Target numbers:
  - 37 verified_events (Rainfall×14, Flood×8, Thunderstorm×6, Strong Winds×5, Fog×3, Others×1)
  - ~1,200+ raw_reports from mixed sources
  - ~8,000+ citizen_reports (CITIZEN_APP)
  - verified_at timestamps spread across past 7 days (upward curve)

Everything this script writes is SYNTHETIC: random severities, random
confidence scores and invented receipts. Every receipt it writes carries
`"synthetic": true` and `provenance: {"all": "synthetic"}` so a seeded event can
never pass for a computed one. It refuses to run without --synthetic.

It deliberately does NOT write:
  * station_readings — invented rainfall and anomaly scores would poison anything
    that reads the table as real telemetry.
  * audit_logs — rows without a prev_hash break the hash chain, and
    verify_chain() would then fail in every provenance response.
It also never disables trg_audit_immutable. If the audit ledger already has
rows it refuses to clear the database; start from `docker compose down -v`.

Never run it before a demo: its ~5,600 unassigned reports would be clustered by
the live pipeline into events.

Usage:
  cd backend && .venv/bin/python ../scripts/seed_national_data.py --synthetic
"""

import argparse
import asyncio
import sys
import uuid
import random
import math
import json
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv
import os

# Load environment from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://indra_user:indra_password@localhost:5433/indra_db",
)
# Convert to raw asyncpg URL
DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


# ── City data ──────────────────────────────────────────────────────────────────
CITIES = [
    {"name": "Patna", "state": "Bihar", "lat": 25.6093, "lng": 85.1376},
    {"name": "Guwahati", "state": "Assam", "lat": 26.1445, "lng": 91.7362},
    {"name": "Mumbai", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    {"name": "New Delhi", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    {"name": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    {"name": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    {"name": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    {"name": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lng": 72.5714},
    {"name": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lng": 75.7873},
    {"name": "Lucknow", "state": "Uttar Pradesh", "lat": 26.8467, "lng": 80.9462},
]

# ── Event distribution ─────────────────────────────────────────────────────────
# Display type → (count, db_event_type)
EVENT_DISTRIBUTION = [
    ("Rainfall", 14, "CLOUDBURST"),
    ("Flood", 8, "URBAN_FLOOD"),
    ("Thunderstorm", 6, "RIVER_BREACH"),
    ("Strong Winds", 5, "CYCLONE_INUNDATION"),
    ("Fog", 3, "CLOUDBURST"),
    ("Others", 1, "RIVER_BREACH"),
]

SEVERITIES = ["ADVISORY", "MODERATE", "HIGH", "CRITICAL"]
SEVERITY_WEIGHTS = [0.15, 0.35, 0.30, 0.20]

REVIEW_STATUSES = ["AUTO_PUBLISHED", "PENDING_HUMAN_REVIEW", "QUARANTINED"]
REVIEW_WEIGHTS = [0.50, 0.35, 0.15]

SOURCE_TYPES = ["CITIZEN_APP", "TWITTER_IMD", "AWS_SENSOR", "CWC_GAUGE", "OFFICIAL_DISPATCH"]

REPORT_TEMPLATES = [
    "Heavy waterlogging reported near {area} in {city}. Roads submerged.",
    "Intense rainfall continuing for the past 3 hours in {city}. Visibility low.",
    "River water level rising dangerously near {area}, {city}. Evacuation underway.",
    "Thunderstorm with lightning in {city}. Power outage in several sectors.",
    "Strong winds reported in {city} coastal area. Trees uprooted near {area}.",
    "Dense fog advisory for {city} — visibility below 50m near {area}.",
    "Flash flood situation developing in {city}. Multiple areas waterlogged.",
    "IMD issues red alert for {city} — extremely heavy rainfall expected.",
    "CWC gauge at {area} shows water above danger mark. Alert level raised.",
    "Multiple citizen reports of flooding near {area} in {city}. Help needed.",
    "Urban drain overflow at {area}, {city}. Residents stranded.",
    "Cloudburst in {city} hill area near {area}. Landslide risk high.",
    "Water pumping operations started in {city} by NDRF team at {area}.",
    "IMD nowcast: Moderate to heavy rainfall likely in {city} next 6 hours.",
    "Social media reports of knee-deep water at {area}, {city}.",
]

AREA_NAMES = [
    "Gandhi Maidan", "MG Road", "Civil Lines", "Station Road", "Lake Area",
    "Industrial Estate", "Old City", "Ring Road Junction", "University Campus",
    "Market Square", "Railway Colony", "IT Park", "Airport Road", "Cantonment",
    "River Bank Colony", "Bypass Junction", "Mall Road", "Bus Stand Area",
]


def jitter(base: float, radius_deg: float = 0.05) -> float:
    """Add GPS jitter to coordinates."""
    return base + random.uniform(-radius_deg, radius_deg)


def generate_event_code() -> str:
    """Generate a unique event code like WX-EV-XXXXXXXX-A."""
    hex_part = uuid.uuid4().hex[:8].upper()
    suffix = random.choice("ABCDEFGH")
    return f"WX-EV-{hex_part}-{suffix}"


def compute_quadrant(severity: str, confidence: float) -> str:
    """Assign quadrant based on severity and confidence."""
    high_sev = {"HIGH", "CRITICAL"}
    if severity in high_sev and confidence >= 0.90:
        return "Critical Verified Event"
    elif severity in high_sev:
        return "Unverified Threat"
    elif confidence >= 0.70:
        return "Confirmed Minor Event"
    else:
        return "Noise"


def generate_verification_receipt(city_data: dict, display_type: str) -> dict:
    """Generate an invented verification receipt, marked synthetic."""
    factors = [
        {"factor": "Weather Station Corroboration", "weight_pct": 25,
         "score": round(random.uniform(0.70, 0.98), 4),
         "evidence": "IMD station data corroborated"},
        {"factor": "Report Density Analysis", "weight_pct": 20,
         "score": round(random.uniform(0.60, 0.95), 4),
         "evidence": "Multiple reports from area"},
        {"factor": "Spatial Coherence Score", "weight_pct": 20,
         "score": round(random.uniform(0.65, 0.95), 4),
         "evidence": "Geo-cluster confirmed"},
        {"factor": "Computer Vision Analysis", "weight_pct": 15,
         "score": round(random.uniform(0.70, 0.95), 4),
         "evidence": "Flood depth estimation from media"},
        {"factor": "Source Reliability Index", "weight_pct": 15,
         "score": round(random.uniform(0.60, 0.90), 4),
         "evidence": "Source credibility verified"},
        {"factor": "Anomaly Detection Signal", "weight_pct": 5,
         "score": round(random.uniform(0.50, 0.85), 4),
         "evidence": "Anomaly detected in readings"},
    ]

    for f in factors:
        f["weighted_points"] = round(f["score"] * f["weight_pct"] / 100, 4)

    total = sum(f["weighted_points"] for f in factors)

    return {
        "synthetic": True,
        "provenance": {"all": "synthetic"},
        "city": city_data["name"],
        "state": city_data["state"],
        "event_type_display": display_type,
        "confidence_score": round(total, 4),
        "factors": factors,
        "total_weighted": round(total, 4),
    }


def upward_curve_timestamp(day_index: int, total_days: int = 7) -> datetime:
    """
    Generate timestamps with an upward curve — more recent days have
    higher probability of being selected.
    """
    now = datetime.now(timezone.utc)
    # Weight more towards recent days
    weight = (day_index + 1) / total_days
    hours_ago = random.uniform(0, 24) + (total_days - day_index - 1) * 24
    return now - timedelta(hours=hours_ago)


async def seed():
    """Main seed function."""
    print("🌱 INDRA National Seed Data Generator")
    print("writes SYNTHETIC events with invented receipts — never run before a demo")
    print("=" * 60)

    ssl_mode = "require" if ("localhost" not in DSN and "127.0.0.1" not in DSN) else None
    conn = await asyncpg.connect(DSN, ssl=ssl_mode)


    # Check if data already exists
    existing = await conn.fetchval("SELECT COUNT(*) FROM verified_events")
    if existing > 0:
        ledger_rows = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
        if ledger_rows > 0:
            await conn.close()
            print(
                f"✘ The audit ledger holds {ledger_rows} row(s). This script will not "
                "delete audit history. Start from an empty database "
                "(docker compose down -v && alembic upgrade head)."
            )
            sys.exit(1)
        print(f"⚠ Database already contains {existing} events. Clearing existing data...")
        try:
            await conn.execute("DELETE FROM user_profiles")
            await conn.execute("DELETE FROM teams")
        except Exception:
            pass
        await conn.execute("DELETE FROM raw_reports")
        await conn.execute("DELETE FROM verified_events")
        print("✓ Existing data cleared.")


    # ── 1. Generate verified events ────────────────────────────────────────
    print("\n📊 Generating 37 verified events across 10 cities...")
    events = []
    event_idx = 0

    for display_type, count, db_type in EVENT_DISTRIBUTION:
        for i in range(count):
            city = CITIES[event_idx % len(CITIES)]
            severity = random.choices(SEVERITIES, SEVERITY_WEIGHTS)[0]
            confidence = round(random.uniform(0.55, 0.98), 4)
            quadrant = compute_quadrant(severity, confidence)
            review_status = random.choices(REVIEW_STATUSES, REVIEW_WEIGHTS)[0]

            # If critical + high confidence, force AUTO_PUBLISHED
            if severity == "CRITICAL" and confidence >= 0.90:
                review_status = "AUTO_PUBLISHED"

            receipt = generate_verification_receipt(city, display_type)
            receipt["confidence_score"] = confidence

            lat = jitter(city["lat"])
            lng = jitter(city["lng"])

            # Spread across 7 days with upward curve
            day_index = random.choices(
                range(7),
                weights=[1, 2, 3, 5, 8, 12, 18],  # upward curve
            )[0]
            verified_at = upward_curve_timestamp(day_index)

            event_id = uuid.uuid4()
            events.append({
                "id": event_id,
                "event_code": generate_event_code(),
                "event_type": db_type,
                "severity": severity,
                "confidence_score": confidence,
                "review_status": review_status,
                "quadrant": quadrant,
                "impact_radius_km": round(random.uniform(2.0, 25.0), 1),
                "lat": lat,
                "lng": lng,
                "receipt": json.dumps(receipt),
                "verified_at": verified_at,
                "city": city,
                "display_type": display_type,
            })
            event_idx += 1

    # Insert events
    for ev in events:
        await conn.execute("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km, center_point,
                 verification_receipt, verified_at)
            VALUES ($1, $2, $3::event_type_enum, $4::severity_enum, $5,
                    $6::review_status_enum, $7::quadrant_enum, $8,
                    ST_SetSRID(ST_MakePoint($9, $10), 4326),
                    $11::jsonb, $12)
        """,
            ev["id"], ev["event_code"], ev["event_type"], ev["severity"],
            ev["confidence_score"], ev["review_status"], ev["quadrant"],
            ev["impact_radius_km"], ev["lng"], ev["lat"],
            ev["receipt"], ev["verified_at"],
        )

    print(f"  ✓ Inserted {len(events)} verified events")

    # Count severities
    sev_counts = {}
    for ev in events:
        sev_counts[ev["severity"]] = sev_counts.get(ev["severity"], 0) + 1
    print(f"  Severity breakdown: {sev_counts}")

    # ── 2. Generate raw reports ────────────────────────────────────────────
    print("\n📝 Generating ~1,200 mixed-source raw reports...")
    report_count = 0

    # Non-citizen reports: ~1,200
    for _ in range(1200):
        city = random.choice(CITIES)
        source = random.choice(["TWITTER_IMD", "AWS_SENSOR", "CWC_GAUGE", "OFFICIAL_DISPATCH"])
        area = random.choice(AREA_NAMES)
        text = random.choice(REPORT_TEMPLATES).format(city=city["name"], area=area)
        lat = jitter(city["lat"], 0.03)
        lng = jitter(city["lng"], 0.03)

        # Assign to a random event (or none)
        event_id = random.choice(events)["id"] if random.random() < 0.4 else None

        day_index = random.choices(range(7), weights=[1, 2, 3, 5, 8, 12, 18])[0]
        created_at = upward_curve_timestamp(day_index)

        try:
            import h3
            h3_cell = h3.latlng_to_cell(lat, lng, 8)
        except Exception:
            h3_cell = None

        await conn.execute("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 h3_res8, credibility_score, event_id, created_at)
            VALUES ($1, $2::source_type_enum, $3, $4, $5,
                    ST_SetSRID(ST_MakePoint($5, $4), 4326),
                    $6, $7, $8, $9)
        """,
            uuid.uuid4(), source, text, lat, lng,
            h3_cell, round(random.uniform(0.3, 0.9), 2),
            event_id, created_at,
        )
        report_count += 1

    print(f"  ✓ Inserted {report_count} mixed-source reports")

    # ── 3. Generate citizen reports (~8,000+) ──────────────────────────────
    print("\n👥 Generating ~8,200 citizen reports...")
    citizen_count = 0

    for _ in range(8200):
        city = random.choice(CITIES)
        area = random.choice(AREA_NAMES)
        text = random.choice(REPORT_TEMPLATES).format(city=city["name"], area=area)
        lat = jitter(city["lat"], 0.04)
        lng = jitter(city["lng"], 0.04)

        event_id = random.choice(events)["id"] if random.random() < 0.3 else None

        day_index = random.choices(range(7), weights=[1, 2, 3, 5, 8, 12, 18])[0]
        created_at = upward_curve_timestamp(day_index)

        try:
            import h3
            h3_cell = h3.latlng_to_cell(lat, lng, 8)
        except Exception:
            h3_cell = None

        await conn.execute("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 h3_res8, credibility_score, event_id, created_at)
            VALUES ($1, 'CITIZEN_APP'::source_type_enum, $2, $3, $4,
                    ST_SetSRID(ST_MakePoint($4, $3), 4326),
                    $5, $6, $7, $8)
        """,
            uuid.uuid4(), text, lat, lng,
            h3_cell, round(random.uniform(0.3, 0.7), 2),
            event_id, created_at,
        )
        citizen_count += 1

    print(f"  ✓ Inserted {citizen_count} citizen reports")

    # ── 6. Generate teams and user profiles ────────────────────────────────
    print("\n🛡️ Generating disaster response teams and operator profiles...")
    teams_data = [
        ("TEAM-NDMA-BIH01", "State Emergency Operations Centre — Bihar / NDMA", "NDMA", "Patna", "Bihar", "Rajesh K. Verma", "+91 94311 02847", "SEOC-DIR-01", "Urban Flood & Emergency Operations Leadership", "DEPLOYED", 18, events[0]["id"] if len(events) > 0 else None),
        ("TEAM-SDRF-MH01", "SDRF Coastal Quick Response Team", "SDRF", "Mumbai", "Maharashtra", "Inspector Sanjay Deshmukh", "+91 98220 54198", "SEA-HAWK-4", "Coastal Inundation & High Tide Evacuation", "DEPLOYED", 14, events[1]["id"] if len(events) > 1 else None),
        ("TEAM-IMD-NOW01", "IMD Severe Weather Nowcasting Cell", "IMD", "New Delhi", "Delhi", "Dr. Sunita Raman", "+91 98110 77312", "DOPPLER-BASE", "Doppler Radar Analysis & Microburst Tracking", "AVAILABLE", 8, None),
        ("TEAM-CWC-HYDRO04", "CWC Brahmaputra Basin Hydrology Unit", "CWC", "Guwahati", "Assam", "Chief Hydrologist B. K. Sarma", "+91 94350 18273", "RIVER-GUARD-2", "River Embankment & Inundation Modeling", "DEPLOYED", 12, events[2]["id"] if len(events) > 2 else None),
        ("TEAM-NDRF-04", "NDRF 4th Battalion - Cyclone Action Team", "NDRF", "Chennai", "Tamil Nadu", "Assistant Director S. Karthik", "+91 94440 99821", "COROMANDEL-ONE", "Severe Cyclonic Storm Response & Heavy Debris Clearing", "STANDBY", 22, None),
        ("TEAM-BBMP-URB02", "BBMP Disaster Rapid Drainage Taskforce", "MUNICIPAL", "Bengaluru", "Karnataka", "Executive Engineer K. Shivakumar", "+91 98450 33124", "RAPID-PUMP-8", "Stormwater Drain Cleansing & High-Volume Dewatering", "AVAILABLE", 16, None),
        ("TEAM-GHMC-HYD01", "GHMC Monsoon Emergency Action Team", "MUNICIPAL", "Hyderabad", "Telangana", "Superintendent P. Anji Reddy", "+91 98490 12099", "DECCAN-SHIELD-3", "Urban Flash Flood Control & Road Clearing", "STANDBY", 15, None),
        ("TEAM-NDMA-NAT01", "NDMA National Aerial Reconnaissance Wing", "NDMA", "New Delhi", "Delhi", "Group Captain V. Nair", "+91 99100 44552", "GARUDA-CENTRAL", "UAV Disaster Surveillance & Thermal Flood Mapping", "AVAILABLE", 10, None),
    ]

    team_id_map = {}
    try:
        for t in teams_data:
            tid = uuid.uuid4()
            team_id_map[t[0]] = tid
            await conn.execute("""
                INSERT INTO teams
                    (id, team_code, name, agency, city, state, lead_name, lead_phone,
                     radio_callsign, specialization, status, members_count, assigned_event_id, created_at)
                VALUES ($1, $2, $3, $4::team_agency_enum, $5, $6, $7, $8, $9, $10, $11::team_status_enum, $12, $13, NOW())
                ON CONFLICT (team_code) DO UPDATE
                SET status = EXCLUDED.status, assigned_event_id = EXCLUDED.assigned_event_id
            """, tid, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11])
        print(f"  ✓ Inserted {len(teams_data)} operational response teams")
    except Exception as e:
        print(f"  ⚠ Could not seed teams table (may not exist yet): {e}")

    # Seed User Profiles
    profiles_data = [
        ("commander", "Rajesh K. Verma", "rajesh.verma@sih-indra.gov.in", "+91 94311 02847", "COMMANDER", "SDMA_BIHAR", "OP-EOC-001", "SEOC-PAT-091", "SEOC-DIR-01", team_id_map.get("TEAM-NDMA-BIH01"), "Operations Director", "ON_DUTY", "State Emergency Operations Director coordinating multi-agency disaster response, flood mitigation, and resource dispatch across Eastern India."),
        ("admin", "Saba Saeed", "sabasaid826@gmail.com", "+91 84347 08060", "ADMIN", "NDMA", "OP-ADMIN-001", "NDMA-DIR-001", "CENTRAL-LEADER", team_id_map.get("TEAM-NDMA-NAT01"), "Platform Administrator & Team Lead", "ON_DUTY", "Lead System Architect and NDMA Platform Administrator managing the INDRA national big data weather platform."),
        ("analyst", "Dr. Vikram Sethi", "vikram.sethi@imd.gov.in", "+91 98710 44210", "ANALYST", "IMD", "OP-ANL-001", "IMD-MET-552", "RADAR-HAWK", team_id_map.get("TEAM-IMD-NOW01"), "Lead Meteorological Analyst", "ON_DUTY", "IMD Nowcasting specialist focusing on Doppler weather radar echoes and cloudburst probability synthesis."),
        ("citizen", "Meenal Sinha", "meenal.sinha09@gmail.com", "+91 93541 18582", "CITIZEN", "PUBLIC", "OP-CIT-001", "CITIZEN-REP-06", "OBSERVER-MEENAL", None, "Volunteer Reporter", "ON_DUTY", "Registered citizen weather observer and ground-truth volunteer contributing geotagged ground reports and flooding photos."),
    ]

    try:
        for p in profiles_data:
            pid = uuid.uuid4()
            await conn.execute("""
                INSERT INTO user_profiles
                    (id, username, full_name, email, phone, role, agency, operator_id, badge_number,
                     callsign, team_id, team_role, duty_status, bio, last_active_at, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::operator_role_enum, $7, $8, $9, $10, $11, $12, $13::duty_status_enum, $14, NOW(), NOW())
                ON CONFLICT (username) DO UPDATE
                SET full_name = EXCLUDED.full_name, email = EXCLUDED.email, phone = EXCLUDED.phone,
                    badge_number = EXCLUDED.badge_number, callsign = EXCLUDED.callsign, team_role = EXCLUDED.team_role,
                    duty_status = EXCLUDED.duty_status, team_id = EXCLUDED.team_id, bio = EXCLUDED.bio
            """, pid, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10], p[11], p[12])
        print(f"  ✓ Inserted {len(profiles_data)} operator profiles")
    except Exception as e:
        print(f"  ⚠ Could not seed user_profiles table (may not exist yet): {e}")

    await conn.close()

    # ── Summary ────────────────────────────────────────────────────────────
    total_reports = report_count + citizen_count
    print("\n" + "=" * 60)
    print("🎉 INDRA National Seed Data — Complete!")
    print(f"  Verified Events:   {len(events)}")
    print(f"  Total Reports:     {total_reports:,}")
    print(f"  Citizen Reports:   {citizen_count:,}")
    print("  Station Readings:  0 (never seeded)")
    print("  Audit Logs:        0 (never seeded)")
    print(f"  Response Teams:    {len(teams_data)}")
    print(f"  Operator Profiles: {len(profiles_data)}")
    print(f"  Cities:            {', '.join(c['name'] for c in CITIES)}")
    print("=" * 60)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="acknowledge that every row written is invented demo data",
    )
    args = parser.parse_args()
    if not args.synthetic:
        print(
            "Refusing to run: this script writes SYNTHETIC events with invented "
            "receipts. Pass --synthetic to confirm. Never run it before a demo.",
            file=sys.stderr,
        )
        sys.exit(2)
    asyncio.run(seed())
