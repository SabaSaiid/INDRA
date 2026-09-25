"""Backend compatibility adapter for the frozen, local Phase 19 matcher.

The public service accepts ordered ``(text, lat, lng, created_at)`` tuples and
returns the first matching index. The Phase 19 matcher supplies the text and
combined similarity decision. Backend distance and time gates remain the
stricter legacy eligibility envelope; old similarity settings do not override
the frozen artifact's validation selected thresholds.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from app.core.config import get_settings
from app.ml.contracts import CandidateReport, PredictionStatus, ReportInput

logger = logging.getLogger("indra.services.dedup")

_DEFAULTS = get_settings()

# Kept as public legacy constants for callers and operational diagnostics.
# The cosine and edit values are historical, not Phase 19 decision thresholds.
COSINE_THRESHOLD = _DEFAULTS.DEDUP_COSINE_THRESHOLD
GPS_DELTA_KM = _DEFAULTS.DEDUP_GPS_DELTA_KM
TIME_DELTA_MINUTES = _DEFAULTS.DEDUP_TIME_DELTA_MINUTES
LEVENSHTEIN_THRESHOLD = _DEFAULTS.DEDUP_LEVENSHTEIN_THRESHOLD


def _gates() -> tuple[float, float, int, float]:
    """Read current backend settings; only geo/time are adapter gates."""
    s = get_settings()
    return (
        s.DEDUP_COSINE_THRESHOLD,
        s.DEDUP_GPS_DELTA_KM,
        s.DEDUP_TIME_DELTA_MINUTES,
        s.DEDUP_LEVENSHTEIN_THRESHOLD,
    )


@lru_cache(maxsize=1)
def _get_local_matcher():
    """Authorize the committed Phase 19 artifact and companion state locally."""

    from app.ml.training.duplicate_validation import load_duplicate_development_artifact

    artifact, matcher = load_duplicate_development_artifact()
    logger.info("Loaded frozen local duplicate matcher %s", artifact.artifact_version)
    return matcher


def _get_embedding_model() -> None:
    """Retired compatibility symbol for the quarantined historical classifier.

    It has no package import, checkpoint lookup, cache lookup, network access,
    or production caller.
    """

    return


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two GPS coordinates in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class DedupService:
    """Preserve the backend's ordered-index duplicate relationship contract."""

    def find_duplicate(
        self,
        new_text: str,
        new_lat: float,
        new_lng: float,
        new_time: datetime,
        existing_reports: list[tuple[str, float, float, datetime]],
    ) -> int | None:
        """Return the earliest eligible Phase 19 duplicate, or ``None``.

        Deterministic UUIDs are local adapter identities only. The caller
        retains the real database IDs at the corresponding tuple indexes.
        Missing model inference raises instead of becoming a negative match.
        """
        if not existing_reports:
            return None

        _, gps_gate_km, time_gate_minutes, _ = _gates()
        eligible: list[tuple[int, CandidateReport]] = []
        for index, (text, lat, lng, occurred_at) in enumerate(existing_reports):
            if abs((new_time - occurred_at).total_seconds()) > time_gate_minutes * 60:
                continue
            if _haversine_km(new_lat, new_lng, lat, lng) > gps_gate_km:
                continue
            eligible.append(
                (
                    index,
                    CandidateReport(
                        report_id=UUID(int=index + 1),
                        text=text,
                        occurred_at=occurred_at,
                        latitude=lat,
                        longitude=lng,
                        source_type="BACKEND_CANDIDATE",
                    ),
                )
            )
        if not eligible:
            return None

        matcher = _get_local_matcher()
        for index, candidate in eligible:
            report = ReportInput(
                report_id=UUID(int=0),
                text=new_text,
                occurred_at=new_time,
                latitude=new_lat,
                longitude=new_lng,
                source_type="BACKEND_REPORT",
                candidate_reports=[candidate],
            )
            prediction = matcher.predict(report)
            if prediction.status is not PredictionStatus.AVAILABLE:
                raise RuntimeError(
                    "frozen duplicate inference unavailable: "
                    + ", ".join(prediction.reason_codes or [prediction.status.value])
                )
            if prediction.is_duplicate is True:
                if prediction.matched_report_id != candidate.report_id:
                    raise RuntimeError("frozen duplicate result identity mismatch")
                logger.info(
                    "Duplicate detected by frozen local matcher at candidate index %d",
                    index,
                )
                return index
            if prediction.is_duplicate is not False:
                raise RuntimeError("frozen duplicate inference omitted a decision")

        return None

    def is_duplicate(
        self,
        new_text: str,
        new_lat: float,
        new_lng: float,
        new_time: datetime,
        existing_reports: list[tuple[str, float, float, datetime]],
    ) -> bool:
        """True when the frozen matcher identifies an eligible duplicate."""
        return (
            self.find_duplicate(new_text, new_lat, new_lng, new_time, existing_reports)
            is not None
        )
