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
    # Added 23 Sep (migration 0011) for Phase 2's feeds: Mastodon posts and news
    # items. Never stored as TWITTER_IMD — a row naming a platform it did not
    # come from is a fabricated source.
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    NEWS_MEDIA = "NEWS_MEDIA"


class EventType(str, enum.Enum):
    URBAN_FLOOD = "URBAN_FLOOD"
    CLOUDBURST = "CLOUDBURST"
    CYCLONE_INUNDATION = "CYCLONE_INUNDATION"
    RIVER_BREACH = "RIVER_BREACH"
    # Added 23 Sep (migration 0011) so every hazard the PS names can be stored.
    # Labels, families and what corroborates each one: services/hazards.py.
    RAINFALL = "RAINFALL"
    THUNDERSTORM = "THUNDERSTORM"
    LIGHTNING = "LIGHTNING"
    HAILSTORM = "HAILSTORM"
    DUST_STORM = "DUST_STORM"
    STRONG_WIND = "STRONG_WIND"
    CYCLONE = "CYCLONE"
    HEATWAVE = "HEATWAVE"
    COLD_WAVE = "COLD_WAVE"
    FOG = "FOG"
    LANDSLIDE = "LANDSLIDE"
    # Nothing identified the hazard. Distinct from every real type, so an
    # unknown report is never stored as a flood.
    UNCLASSIFIED = "UNCLASSIFIED"


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
    # A commander or admin approved the event. Distinct from AUTO_PUBLISHED so
    # the record never claims the machine published what a human decided.
    HUMAN_APPROVED = "HUMAN_APPROVED"


class Verdict(str, enum.Enum):
    """
    What the evidence says about an event (Phase 4 T4, migration 0020).

    CONTRADICTED   the weather (or, for a cyclone, the absence of any warning)
                   affirmatively says the opposite of the claim; a human decides
    CORROBORATED   no contradiction, and an official warning or the weather
                   evidence scores at least 0.6
    UNCONFIRMED    neither: nothing independent either way
    """

    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    UNCONFIRMED = "UNCONFIRMED"


class Quadrant(str, enum.Enum):
    CRITICAL_VERIFIED = "Critical Verified Event"
    UNVERIFIED_THREAT = "Unverified Threat"
    CONFIRMED_MINOR = "Confirmed Minor Event"
    NOISE = "Noise"


class Agency(str, enum.Enum):
    IMD = "IMD"
    CWC = "CWC"
    OPEN_METEO = "OPEN_METEO"
    # Added 24 Sep (migration 0016): an Indian aerodrome's METAR, received
    # through the international exchange NOAA's Aviation Weather Center
    # republishes. Not IMD: some of these stations are military airfields.
    AERODROME_METAR = "AERODROME_METAR"


class AuditAction(str, enum.Enum):
    AUTO_VERIFY = "AUTO_VERIFY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    QUARANTINE = "QUARANTINE"
    ESCALATE = "ESCALATE"
    HUMAN_APPROVE = "HUMAN_APPROVE"
    HUMAN_REJECT = "HUMAN_REJECT"
    # Added 24 Sep (migration 0015): an analyst exported reports or events.
    # Not a decision about an event, so its ledger row has no event_id.
    DATA_EXPORT = "DATA_EXPORT"
    # Added 27 Sep (migration 0020, Phase 4 T5): evidence that arrived after
    # the event (an IMD warning, an airport observation) changed its score,
    # verdict or status. Details: {trigger, before, after}.
    LATE_CORROBORATION = "LATE_CORROBORATION"
    # Added 28 Sep (migration 0021, Phase 5 T5): an analyst was given a link to
    # a report's original photo or video, EXIF and GPS included. Details:
    # {media_ids, report_ids}. No event_id: it is about media, not a decision.
    MEDIA_ORIGINAL_ACCESS = "MEDIA_ORIGINAL_ACCESS"
    # Added 28 Sep (migration 0023, Phase 5 T5): a citizen withdrew their
    # report by its docket. Details: {report_id, docket, event_code,
    # media_deleted}.
    REPORT_WITHDRAWN = "REPORT_WITHDRAWN"


class TeamStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"
    STANDBY = "STANDBY"
    OFF_DUTY = "OFF_DUTY"


class TeamAgency(str, enum.Enum):
    NDRF = "NDRF"
    SDRF = "SDRF"
    IMD = "IMD"
    CWC = "CWC"
    NDMA = "NDMA"
    MUNICIPAL = "MUNICIPAL"


class DutyStatus(str, enum.Enum):
    ON_DUTY = "ON_DUTY"
    STANDBY = "STANDBY"
    DEPLOYED = "DEPLOYED"
    OFF_DUTY = "OFF_DUTY"


class OperatorRole(str, enum.Enum):
    COMMANDER = "COMMANDER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"
    CITIZEN = "CITIZEN"
    FIELD_RESPONDER = "FIELD_RESPONDER"

