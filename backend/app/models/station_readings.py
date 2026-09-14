"""
INDRA Platform — StationReading ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Enum, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
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
    anomaly_score = Column(Float, nullable=True, default=0.0)
    recorded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_stations_location_gist",
            "station_location",
            postgresql_using="gist",
        ),
    )

    def __repr__(self) -> str:
        return f"<StationReading {self.station_code} [{self.agency.value}]>"
