"""
INDRA Platform — StationReading ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, Float, Enum, DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import Agency


class StationReading(Base):
    __tablename__ = "station_readings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_code = Column(String(30), nullable=False)
    station_name = Column(String(120), nullable=False)
    agency = Column(Enum(Agency, name="agency_enum"), nullable=False)
    station_location = Column(Geometry("POINT", srid=4326), nullable=True)
    rainfall_mm = Column(Float, nullable=True)
    river_level_m = Column(Float, nullable=True)
    # No default: the frozen anomaly model writes separate advisory evidence,
    # not this legacy numeric column. NULL means no anomaly factor was computed
    # here; 0.0 would incorrectly claim a measured normal result. (0006)
    anomaly_score = Column(Float, nullable=True)
    recorded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Migration 0016 (Phase 2 T3): airport observations. See its docstring.
    # Which poller wrote the row: open_meteo or metar.
    feed = Column(String(20), nullable=True)
    temperature_c = Column(Float, nullable=True)
    dewpoint_c = Column(Float, nullable=True)
    wind_kmh = Column(Float, nullable=True)
    gust_kmh = Column(Float, nullable=True)
    # 10,000 means "10 km or more" (9999 or CAVOK in the report).
    visibility_m = Column(Integer, nullable=True)
    # Present weather, normalised: +TSRA -> ["TS", "RA+"].
    weather_codes = Column(ARRAY(Text), nullable=True)
    # A CB or TCU cloud group was reported.
    convective_cloud = Column(Boolean, nullable=True)
    # The report exactly as transmitted.
    raw_observation = Column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_stations_location_gist",
            "station_location",
            postgresql_using="gist",
        ),
    )

    def __repr__(self) -> str:
        return f"<StationReading {self.station_code} [{self.agency.value}]>"
