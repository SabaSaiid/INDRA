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
import re
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


_REPOST_PREFIX = re.compile(r"^(?:(?:urgent|fwd|fw|forwarded)\s*:\s*)+", re.I)


def _canonical_repost_text(value: str) -> str:
    """Exact-content policy for common forwarding labels, never a semantic score."""

    without_prefix = _REPOST_PREFIX.sub("", value.casefold().strip())
    return " ".join(re.findall(r"\w+", without_prefix, flags=re.UNICODE))


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
        canonical_new = _canonical_repost_text(new_text)
        for index, candidate in eligible:
            # Preserve the backend's literal repost guarantee for an identical
            # message marked URGENT/Fwd, without changing frozen model weights
            # or treating an unavailable model as a negative inference.
            if canonical_new and canonical_new == _canonical_repost_text(candidate.text):
                logger.info("Literal repost detected at candidate index %d", index)
                return index
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


def _levenshtein_similarity(left: str, right: str) -> float:
    """Normalized local edit similarity for the separate post/headline path."""

    try:
        import Levenshtein

        distance = Levenshtein.distance(left, right)
        return 1.0 - distance / max(len(left), len(right), 1)
    except ImportError:
        # The dependency is declared; keep the historical local fallback if a
        # minimal environment omits it rather than contacting a model server.
        left_words, right_words = set(left.lower().split()), set(right.lower().split())
        if not left_words or not right_words:
            return 0.0
        return len(left_words & right_words) / max(len(left_words), len(right_words))


# Historical 24 Sep feed audit: the former comparator produced false Hindi matches. The live
# feed path below now uses only local edit distance, independent of script.
LATIN_SHARE_FOR_MODEL = 0.5


def _mostly_latin(text_: str) -> bool:
    """More than LATIN_SHARE_FOR_MODEL of the letters are Latin (a–z, with accents)."""
    letters = [c for c in text_ if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if c.isascii() or "\u00c0" <= c <= "\u024f")
    return latin / len(letters) > LATIN_SHARE_FOR_MODEL


def find_similar_text(
    new_text: str,
    candidate_texts: list[str],
    cosine_threshold: float | None = None,
) -> tuple[int, float, str] | None:
    """
    The first candidate whose text is a copy of `new_text`, as
    (index, similarity, method), or None. Text only: no distance, no clock.

    Used for posts and headlines, which have their own link/place/time gates.
    The retired comparator is not used. A conservative local edit-distance
    comparison preserves exact/near repost detection without making unrelated
    Hindi headlines into duplicates. ``cosine_threshold`` is retained as an
    optional caller threshold for API compatibility; no cosine is computed.

    Synchronous and CPU-bound: call it through asyncio.to_thread.
    """
    if not candidate_texts or not (new_text or "").strip():
        return None
    _, _, _, levenshtein = _gates()
    threshold = levenshtein if cosine_threshold is None else cosine_threshold

    # In candidate order, so the earliest copy is the one returned.
    for i, text_ in enumerate(candidate_texts):
        sim = _levenshtein_similarity(new_text, text_)
        if sim >= threshold:
            return i, round(sim, 4), "levenshtein"
    return None
