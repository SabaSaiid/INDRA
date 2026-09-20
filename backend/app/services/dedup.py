"""
INDRA Platform — Deduplication Service
Detects duplicate incoming reports using:
  1. Cosine similarity via sentence-transformers (primary)
  2. Levenshtein distance (fallback)
  + GPS delta ≤ 1.0 km
  + Time delta ≤ 15 minutes
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

logger = logging.getLogger("indra.services.dedup")

# ── Thresholds ─────────────────────────────────────────────────────────────────
COSINE_THRESHOLD = 0.88
GPS_DELTA_KM = 1.0
TIME_DELTA_MINUTES = 15
LEVENSHTEIN_THRESHOLD = 0.75  # normalized similarity

# ── Lazy-loaded embedding model ────────────────────────────────────────────────
_model = None
_model_failed = False


def _get_embedding_model():
    """Load sentence-transformers model lazily. Returns None if unavailable."""
    global _model, _model_failed
    if _model_failed:
        return None
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        # CPU, not MPS: MPS kernels are not bit-reproducible, and the event
        # classifier reuses this instance and must give identical outputs.
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
        logger.info("✓ Loaded sentence-transformers/all-MiniLM-L6-v2 for dedup")
        return _model
    except Exception as e:
        _model_failed = True
        logger.warning(f"⚠ Could not load sentence-transformers: {e}. Using Levenshtein fallback.")
        return None


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


def _cosine_similarity(vec_a, vec_b) -> float:
    """Compute cosine similarity between two numpy vectors."""
    import numpy as np
    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein similarity (1.0 = identical)."""
    try:
        import Levenshtein
        dist = Levenshtein.distance(s1, s2)
        max_len = max(len(s1), len(s2), 1)
        return 1.0 - (dist / max_len)
    except ImportError:
        # Ultra-fallback: simple keyword overlap
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / max(len(words1), len(words2))


class DedupService:
    """
    Check if an incoming report is a duplicate of existing recent reports.
    A report is duplicate if ALL three conditions hold:
      - text_similarity ≥ 0.88 (cosine) or ≥ 0.75 (Levenshtein fallback)
      - gps_delta ≤ 1.0 km
      - time_delta ≤ 15 min
    """

    def find_duplicate(
        self,
        new_text: str,
        new_lat: float,
        new_lng: float,
        new_time: datetime,
        existing_reports: List[Tuple[str, float, float, datetime]],
    ) -> Optional[int]:
        """
        Check against a list of existing (text, lat, lng, created_at) tuples.

        Returns the index in `existing_reports` of the first report this one
        duplicates, or None. Candidates are checked in the order given, so a
        caller that passes them oldest first gets the earliest match.
        """
        if not existing_reports:
            return None

        model = _get_embedding_model()
        use_embeddings = model is not None

        if use_embeddings:
            try:
                new_embedding = model.encode(new_text, convert_to_numpy=True)
            except Exception:
                use_embeddings = False

        for index, (ex_text, ex_lat, ex_lng, ex_time) in enumerate(existing_reports):
            # Time delta check (fastest, do first)
            if abs((new_time - ex_time).total_seconds()) > TIME_DELTA_MINUTES * 60:
                continue

            # GPS delta check
            dist_km = _haversine_km(new_lat, new_lng, ex_lat, ex_lng)
            if dist_km > GPS_DELTA_KM:
                continue

            # Text similarity check
            if use_embeddings:
                try:
                    ex_embedding = model.encode(ex_text, convert_to_numpy=True)
                    sim = _cosine_similarity(new_embedding, ex_embedding)
                    if sim >= COSINE_THRESHOLD:
                        logger.info(
                            f"Duplicate detected (cosine={sim:.3f}, dist={dist_km:.2f}km)"
                        )
                        return index
                except Exception:
                    # Fall through to Levenshtein
                    sim = _levenshtein_similarity(new_text, ex_text)
                    if sim >= LEVENSHTEIN_THRESHOLD:
                        return index
            else:
                sim = _levenshtein_similarity(new_text, ex_text)
                if sim >= LEVENSHTEIN_THRESHOLD:
                    logger.info(
                        f"Duplicate detected (levenshtein={sim:.3f}, dist={dist_km:.2f}km)"
                    )
                    return index

        return None

    def is_duplicate(
        self,
        new_text: str,
        new_lat: float,
        new_lng: float,
        new_time: datetime,
        existing_reports: List[Tuple[str, float, float, datetime]],
    ) -> bool:
        """True if any existing report is considered a duplicate."""
        return (
            self.find_duplicate(new_text, new_lat, new_lng, new_time, existing_reports)
            is not None
        )
