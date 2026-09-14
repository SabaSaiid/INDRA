"""
INDRA Platform — Enum Definitions for Database Models
"""

import enum


class SourceType(str, enum.Enum):
    CITIZEN_APP = "CITIZEN_APP"
    TWITTER_IMD = "TWITTER_IMD"
    AWS_SENSOR = "AWS_SENSOR"
    CWC_GAUGE = "CWC_GAUGE"
    OFFICIAL_DISPATCH = "OFFICIAL_DISPATCH"


class EventType(str, enum.Enum):
    URBAN_FLOOD = "URBAN_FLOOD"
    CLOUDBURST = "CLOUDBURST"
    CYCLONE_INUNDATION = "CYCLONE_INUNDATION"
    RIVER_BREACH = "RIVER_BREACH"


class Severity(str, enum.Enum):
    ADVISORY = "ADVISORY"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewStatus(str, enum.Enum):
    AUTO_PUBLISHED = "AUTO_PUBLISHED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class Quadrant(str, enum.Enum):
    CRITICAL_VERIFIED = "Critical Verified Event"
    UNVERIFIED_THREAT = "Unverified Threat"
    CONFIRMED_MINOR = "Confirmed Minor Event"
    NOISE = "Noise"


class Agency(str, enum.Enum):
    IMD = "IMD"
    CWC = "CWC"
    OPEN_METEO = "OPEN_METEO"


class AuditAction(str, enum.Enum):
    AUTO_VERIFY = "AUTO_VERIFY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    QUARANTINE = "QUARANTINE"
    ESCALATE = "ESCALATE"
