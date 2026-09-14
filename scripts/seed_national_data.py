#!/usr/bin/env python3
"""
INDRA Platform — National Seed Data Generator
Generates realistic multi-city sample data across 10 Indian cities.

Target numbers:
  - 37 verified_events (Rainfall×14, Flood×8, Thunderstorm×6, Strong Winds×5, Fog×3, Others×1)
  - ~1,200+ raw_reports from mixed sources
  - ~8,000+ citizen_reports (CITIZEN_APP)
  - verified_at timestamps spread across past 7 days (upward curve)

Usage:
  cd backend && .venv/bin/python ../scripts/seed_national_data.py
"""

import asyncio
import uuid
import random
import math
import json
import hashlib
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
    """Generate a realistic verification receipt JSONB."""
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
    print("=" * 60)

    conn = await asyncpg.connect(DSN)

    # Check if data already exists
    existing = await conn.fetchval("SELECT COUNT(*) FROM verified_events")
    if existing > 0:
        print(f"⚠ Database already contains {existing} events. Clearing existing data...")
        await conn.execute("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_immutable")
        await conn.execute("DELETE FROM audit_logs")
        await conn.execute("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_immutable")
        try:
            await conn.execute("DELETE FROM user_profiles")
            await conn.execute("DELETE FROM teams")
        except Exception:
            pass
        await conn.execute("DELETE FROM raw_reports")
        await conn.execute("DELETE FROM station_readings")
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

    # ── 4. Generate station readings ───────────────────────────────────────
    print("\n🌡️ Generating station readings...")
    station_count = 0
    agencies = ["IMD", "CWC", "OPEN_METEO"]

    for city in CITIES:
        for agency in agencies:
            for day in range(7):
                station_code = f"{agency}-{city['name'][:3].upper()}-{random.randint(100, 999)}"
                recorded_at = datetime.now(timezone.utc) - timedelta(days=day, hours=random.randint(0, 23))

                await conn.execute("""
                    INSERT INTO station_readings
                        (id, station_code, station_name, agency, station_location,
                         rainfall_mm, river_level_m, anomaly_score, recorded_at)
                    VALUES ($1, $2, $3, $4::agency_enum,
                            ST_SetSRID(ST_MakePoint($5, $6), 4326),
                            $7, $8, $9, $10)
                """,
                    uuid.uuid4(), station_code,
                    f"{city['name']} {agency} Station",
                    agency,
                    jitter(city["lng"], 0.02), jitter(city["lat"], 0.02),
                    round(random.uniform(0, 250), 1),
                    round(random.uniform(0, 15), 2) if agency == "CWC" else None,
                    round(random.uniform(0, 1), 3),
                    recorded_at,
                )
                station_count += 1

    print(f"  ✓ Inserted {station_count} station readings")

    # ── 5. Generate audit logs ─────────────────────────────────────────────
    print("\n📋 Generating audit logs...")
    audit_count = 0
    actions = ["AUTO_VERIFY", "MANUAL_OVERRIDE", "QUARANTINE", "ESCALATE"]

    for ev in events[:20]:  # First 20 events
        action = random.choice(actions)
        reason = f"{'Automated' if action == 'AUTO_VERIFY' else 'Manual'} verification - confidence: {ev['confidence_score']}"
        sha = hashlib.sha256(f"{ev['id']}{action}{reason}".encode()).hexdigest()

        await conn.execute("""
            INSERT INTO audit_logs
                (id, event_id, operator_id, action_taken, reason, sha256_hash, logged_at)
            VALUES ($1, $2, $3, $4::audit_action_enum, $5, $6, $7)
        """,
            uuid.uuid4(), ev["id"],
            f"OP-{'AUTO' if action == 'AUTO_VERIFY' else 'CMD'}-{random.randint(1,5):03d}",
            action, reason, sha, ev["verified_at"],
        )
        audit_count += 1

    print(f"  ✓ Inserted {audit_count} audit logs")

    # ── 6. Generate teams and user profiles ────────────────────────────────
    print("\n🛡️ Generating disaster response teams and operator profiles...")
    teams_data = [
        ("TEAM-NDRF-09", "NDRF 9th Battalion - Flood Rescue Unit", "NDRF", "Patna", "Bihar", "Commandant R. K. Verma", "+91 94311 02847", "HAWK-ONE", "Urban Flood & Deep Water Evacuation", "DEPLOYED", 18, events[0]["id"] if len(events) > 0 else None),
        ("TEAM-SDRF-MH01", "SDRF Coastal Quick Response Team", "SDRF", "Mumbai", "Maharashtra", "Inspector Sanjay Deshmukh", "+91 98220 54198", "SEA-HAWK-4", "Coastal Inundation & High Tide Evacuation", "DEPLOYED", 14, events[1]["id"] if len(events) > 1 else None),
        ("TEAM-IMD-NOW01", "IMD Severe Weather Nowcasting Cell", "IMD", "New Delhi", "Delhi", "Dr. Sunita Raman", "+91 98110 77312", "DOPPLER-BASE", "Doppler Radar Analysis & Microburst Tracking", "AVAILABLE", 8, None),
        ("TEAM-CWC-HYDRO04", "CWC Brahmaputra Basin Hydrology Unit", "CWC", "Guwahati", "Assam", "Chief Hydrologist B. K. Sarma", "+91 94350 18273", "RIVER-GUARD-2", "River Embankment & Inundation Modeling", "DEPLOYED", 12, events[2]["id"] if len(events) > 2 else None),
        ("TEAM-NDRF-04", "NDRF 4th Battalion - Cyclone Action Team", "NDRF", "Chennai", "Tamil Nadu", "Deputy Commandant S. Karthik", "+91 94440 99821", "COROMANDEL-ONE", "Severe Cyclonic Storm Response & Heavy Debris Clearing", "STANDBY", 22, None),
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
        ("commander", "Commandant Rajesh K. Verma", "rajesh.verma@sih-indra.gov.in", "+91 94311 02847", "COMMANDER", "SDMA_BIHAR", "OP-CMD-001", "NDRF-PAT-091", "EAGLE-LEADER", team_id_map.get("TEAM-NDRF-09"), "Incident Commander", "ON_DUTY", "National Disaster Response Force commander leading urban inundation and river flood operations."),
        ("admin", "Dr. Ananya Sen", "ananya.sen@ndma.gov.in", "+91 98100 11982", "ADMIN", "NDMA", "OP-ADMIN-001", "NDMA-DIR-004", "CENTRAL-ONE", team_id_map.get("TEAM-NDMA-NAT01"), "Platform Administrator", "ON_DUTY", "National Disaster Management Authority chief data officer administering the INDRA big data platform."),
        ("analyst", "Dr. Vikram Sethi", "vikram.sethi@imd.gov.in", "+91 98710 44210", "ANALYST", "IMD", "OP-ANL-001", "IMD-MET-552", "RADAR-HAWK", team_id_map.get("TEAM-IMD-NOW01"), "Lead Meteorological Analyst", "ON_DUTY", "IMD Nowcasting specialist focusing on Doppler weather radar echoes and cloudburst probability synthesis."),
        ("citizen", "Aarav Sharma", "aarav.sharma@gmail.com", "+91 97112 88401", "CITIZEN", "PUBLIC", "OP-CIT-001", "CITIZEN-REP-88", "OBSERVER-IND", None, "Volunteer Observer", "ON_DUTY", "Registered citizen weather observer contributing geotagged ground reports and flooding photos in Patna."),
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
                SET full_name = EXCLUDED.full_name, duty_status = EXCLUDED.duty_status, team_id = EXCLUDED.team_id
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
    print(f"  Station Readings:  {station_count}")
    print(f"  Audit Logs:        {audit_count}")
    print(f"  Response Teams:    {len(teams_data)}")
    print(f"  Operator Profiles: {len(profiles_data)}")
    print(f"  Cities:            {', '.join(c['name'] for c in CITIES)}")
    print("=" * 60)



if __name__ == "__main__":
    asyncio.run(seed())
