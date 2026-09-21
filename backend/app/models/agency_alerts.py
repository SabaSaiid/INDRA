"""
INDRA Platform — AgencyAlert ORM Model

An official warning issued by a government agency and published on NDMA's SACHET
feed. This is the first table in the platform holding a judgement INDRA did not
make: IMD, CWC or a state SDMA decided the severity, and the row records it.

**Why `sender` is a string and not the `Agency` enum.** The live feed carries
`IMD Ahmedabad`, `IMD Mumbai`, `Gujarat-SDMA`, `Andhra Pradesh SDMA`, `CWC` and
more. Forcing those into the three-value `Agency` enum would either lose the
issuing office or invent a taxonomy nobody publishes. The sender is stored
verbatim, exactly as the CAP document gives it — the same rule that keeps
`station_readings.agency` set to `OPEN_METEO` instead of the IMD it is not.

`severity` is NULL when the agency said `Unknown`. `area_polygon` is NULL when the
alert carried no polygon; a district-code-only alert is real, and a fabricated
bounding box would be a footprint no agency drew.
"""

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Column, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from app.core.database import Base
from app.models.enums import Severity


class AgencyAlert(Base):
    __tablename__ = "agency_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The SACHET <guid>. Unique: re-polling the feed must update the row, not
    # append a duplicate. A CAP "Update" msgType reuses the identifier.
    identifier = Column(String(128), nullable=False, unique=True, index=True)
    source_feed = Column(String(32), nullable=False, default="SACHET")

    sender = Column(String(160), nullable=True)
    status = Column(String(32), nullable=True)
    msg_type = Column(String(32), nullable=True)
    category = Column(String(64), nullable=True)
    event = Column(String(160), nullable=True)

    urgency = Column(String(32), nullable=True)
    severity = Column(Enum(Severity, name="severity_enum"), nullable=True)
    # What the agency actually wrote, including "Unknown". Kept alongside the
    # mapped enum so the receipt can quote the source rather than our reading.
    raw_severity = Column(String(32), nullable=True)
    certainty = Column(String(32), nullable=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)
    # The RSS <pubDate>, kept separate from the CAP <sent>. They are different
    # fields and they disagree: on one real alert the CAP said 02:24 UTC and the
    # feed said 02:28. Comparing the feed's timestamp against the stored CAP
    # timestamp makes every alert look republished on every tick, which refetches
    # 99 CAP documents and up to 99 polygons forever. Freshness is judged
    # feed-against-feed.
    feed_published_at = Column(DateTime(timezone=True), nullable=True)
    effective_at = Column(DateTime(timezone=True), nullable=True)
    onset_at = Column(DateTime(timezone=True), nullable=True)
    # The alert's own lifetime. Corroboration must respect it: an expired warning
    # is not evidence about now.
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)

    headline = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    area_desc = Column(Text, nullable=True)
    district_codes = Column(ARRAY(String(16)), nullable=True)

    area_polygon = Column(Geometry("POLYGON", srid=4326), nullable=True)
    # True when the ring was decimated to fit MAX_POLYGON_POINTS, so the stored
    # footprint is an approximation of the agency's geometry and says so.
    polygon_thinned = Column(Boolean, nullable=False, default=False)
    polygon_points = Column(Integer, nullable=True)

    fetched_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_agency_alerts_area_gist", "area_polygon", postgresql_using="gist"),
        Index("ix_agency_alerts_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<AgencyAlert {self.identifier} [{self.sender}] {self.event!r}>"
