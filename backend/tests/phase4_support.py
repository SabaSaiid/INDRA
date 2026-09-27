"""
Helpers for Phase 4's database tests: an official warning, SACHET's heartbeat,
an airport observation, and a clean-up of all three.

Every row these write is marked (identifier `p4-…`, station `VT…`/named
codes with sender `P4-TEST`), so the clean-up removes exactly what the tests
wrote and nothing a poller stored.
"""

import math
import uuid
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import text

TEST_SENDER = "P4-TEST"
TEST_PREFIX = "p4-"


def square_wkt(lat: float, lng: float, half_km: float) -> str:
    """A closed square ring around a point, `half_km` from its centre to each side."""
    dlat = half_km / 111.32
    dlng = half_km / (111.32 * math.cos(math.radians(lat)))
    ring = [
        (lng - dlng, lat - dlat), (lng + dlng, lat - dlat), (lng + dlng, lat + dlat),
        (lng - dlng, lat + dlat), (lng - dlng, lat - dlat),
    ]
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"


async def insert_warning(
    db,
    *,
    lat: float,
    lng: float,
    now: datetime,
    event: str = "Heavy Rainfall",
    raw_severity: str = "Severe",
    status: str = "Actual",
    msg_type: str = "Alert",
    effective_hours_ago: float = 1.0,
    expires_in_hours: float = 12.0,
    half_km: float = 20.0,
    polygon: bool = True,
    area_desc: Optional[str] = None,
    identifier: Optional[str] = None,
    sender: str = TEST_SENDER,
    sent_at: Optional[datetime] = None,
) -> str:
    identifier = identifier or f"{TEST_PREFIX}{uuid.uuid4().hex[:12]}"
    await db.execute(
        text("""
            INSERT INTO agency_alerts
                (id, identifier, source_feed, sender, status, msg_type, category, event,
                 urgency, raw_severity, certainty, sent_at, feed_published_at, effective_at,
                 expires_at, headline, area_desc, area_polygon, polygon_thinned, fetched_at)
            VALUES
                (CAST(:id AS uuid), :identifier, 'SACHET', :sender, :status, :msg_type, 'Met', :event,
                 'Expected', :raw_severity, 'Likely', :sent, :sent, :effective,
                 :expires, :headline, :area_desc,
                 CASE WHEN CAST(:wkt AS text) IS NULL THEN NULL
                      ELSE ST_GeomFromText(CAST(:wkt AS text), 4326) END,
                 false, :sent)
        """),
        {
            "id": str(uuid.uuid4()),
            "identifier": identifier,
            "sender": sender,
            "status": status,
            "msg_type": msg_type,
            "event": event,
            "raw_severity": raw_severity,
            "sent": sent_at or now - timedelta(hours=effective_hours_ago),
            "effective": now - timedelta(hours=effective_hours_ago),
            "expires": now + timedelta(hours=expires_in_hours),
            "headline": f"{event} warning",
            "area_desc": area_desc,
            "wkt": square_wkt(lat, lng, half_km) if polygon else None,
        },
    )
    await db.commit()
    return identifier


async def sachet_heartbeat(db, last_success_at: datetime) -> None:
    """SACHET's feed_status row, as if its last successful tick was then."""
    await db.execute(
        text("""
            INSERT INTO feed_status (feed, kind, enabled, last_attempt_at, last_success_at,
                                     consecutive_failures, rows_total, updated_at)
            VALUES ('sachet', 'warnings', true, :at, :at, 0, 0, :at)
            ON CONFLICT (feed) DO UPDATE SET last_success_at = EXCLUDED.last_success_at,
                                             last_attempt_at = EXCLUDED.last_attempt_at,
                                             consecutive_failures = 0
        """),
        {"at": last_success_at},
    )
    await db.commit()


async def insert_metar(
    db,
    *,
    station: str,
    lat: float,
    lng: float,
    recorded_at: datetime,
    temperature_c: Optional[float] = None,
    visibility_m: Optional[int] = None,
    wind_kmh: Optional[float] = None,
    gust_kmh: Optional[float] = None,
    weather_codes: Iterable[str] = (),
    convective_cloud: bool = False,
) -> None:
    await db.execute(
        text("""
            INSERT INTO station_readings
                (id, station_code, station_name, agency, station_location, recorded_at, feed,
                 temperature_c, visibility_m, wind_kmh, gust_kmh, weather_codes, convective_cloud,
                 raw_observation)
            VALUES
                (CAST(:id AS uuid), :station, :name, 'AERODROME_METAR',
                 ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :at, 'metar',
                 :temp, :vis, :wind, :gust, CAST(:codes AS text[]), :cb, :raw)
        """),
        {
            "id": str(uuid.uuid4()), "station": station, "name": f"{TEST_SENDER} {station}",
            "lat": lat, "lng": lng, "at": recorded_at, "temp": temperature_c, "vis": visibility_m,
            "wind": wind_kmh, "gust": gust_kmh, "codes": list(weather_codes), "cb": convective_cloud,
            "raw": f"METAR {station} {TEST_SENDER}",
        },
    )
    await db.commit()


async def wipe_phase4_rows(db) -> None:
    """Remove every warning, heartbeat and observation these helpers wrote."""
    await db.execute(text("DELETE FROM agency_alerts WHERE sender = :s OR identifier LIKE 'p4-%'"),
                     {"s": TEST_SENDER})
    await db.execute(text("DELETE FROM station_readings WHERE raw_observation LIKE :s"),
                     {"s": f"%{TEST_SENDER}%"})
    await db.execute(text("DELETE FROM feed_status WHERE feed = 'sachet'"))
    await db.commit()
