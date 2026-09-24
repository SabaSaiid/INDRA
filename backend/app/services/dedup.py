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

from app.core.config import get_settings

logger = logging.getLogger("indra.services.dedup")

# ── Thresholds ─────────────────────────────────────────────────────────────────
# These live in settings since 20 Sep, with exactly the values they were
# hard-coded at, so they can be tuned from .env rather than by editing this file.
# Nothing about dedup behaviour changed in that move.
#
# They are resolved **per call**, not at import time: a threshold read once at
# import cannot be overridden by an environment variable in a running process,
# which would have made the setting decorative. See _gates().
#
# The bare module names remain as the documented defaults; several docstrings and
# notes cite COSINE_THRESHOLD = 0.88 by name.
_DEFAULTS = get_settings()

COSINE_THRESHOLD = _DEFAULTS.DEDUP_COSINE_THRESHOLD
GPS_DELTA_KM = _DEFAULTS.DEDUP_GPS_DELTA_KM
TIME_DELTA_MINUTES = _DEFAULTS.DEDUP_TIME_DELTA_MINUTES
LEVENSHTEIN_THRESHOLD = _DEFAULTS.DEDUP_LEVENSHTEIN_THRESHOLD  # normalized similarity


def _gates():
    """The four dedup gates as configured right now."""
    s = get_settings()
    return (
        s.DEDUP_COSINE_THRESHOLD,
        s.DEDUP_GPS_DELTA_KM,
        s.DEDUP_TIME_DELTA_MINUTES,
        s.DEDUP_LEVENSHTEIN_THRESHOLD,
    )

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

        cosine_threshold, gps_delta_km, time_delta_minutes, levenshtein_threshold = _gates()

        model = _get_embedding_model()
        use_embeddings = model is not None

        if use_embeddings:
            try:
                new_embedding = model.encode(new_text, convert_to_numpy=True)
            except Exception:
                use_embeddings = False

        for index, (ex_text, ex_lat, ex_lng, ex_time) in enumerate(existing_reports):
            # Time delta check (fastest, do first)
            if abs((new_time - ex_time).total_seconds()) > time_delta_minutes * 60:
                continue

            # GPS delta check
            dist_km = _haversine_km(new_lat, new_lng, ex_lat, ex_lng)
            if dist_km > gps_delta_km:
                continue

            # Text similarity check
            if use_embeddings:
                try:
                    ex_embedding = model.encode(ex_text, convert_to_numpy=True)
                    sim = _cosine_similarity(new_embedding, ex_embedding)
                    if sim >= cosine_threshold:
                        logger.info(
                            f"Duplicate detected (cosine={sim:.3f}, dist={dist_km:.2f}km)"
                        )
                        return index
                except Exception:
                    # Fall through to Levenshtein
                    sim = _levenshtein_similarity(new_text, ex_text)
                    if sim >= levenshtein_threshold:
                        return index
            else:
                sim = _levenshtein_similarity(new_text, ex_text)
                if sim >= levenshtein_threshold:
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


# The embedding model (all-MiniLM-L6-v2) was trained on English. It has almost
# no vocabulary for Devanagari, so two unrelated Hindi headlines come out as
# near-identical vectors: on the first live news tick (24 Sep) 75 Hindi
# headlines were suppressed as "copies" at cosine 0.88–0.96 — crop damage in
# Sitapur as a copy of crop damage in Husainganj, a fog alert as a copy of a
# hospital's heat advisory. Text the model cannot read is compared by
# Levenshtein instead, which kept 3 of those 75: the two verbatim reposts and
# one at the threshold.
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
    candidate_texts: List[str],
    cosine_threshold: Optional[float] = None,
) -> Optional[Tuple[int, float, str]]:
    """
    The first candidate whose text is a copy of `new_text`, as
    (index, similarity, method), or None. Text only: no distance, no clock.

    Used for posts and headlines (Phase 2 T7), which have their own gates for
    place and time; citizen reports keep DedupService above, unchanged. The
    threshold is the same measured 0.88 by default (BUG-013). A pair is
    compared by the model only when both texts are mostly Latin script (see
    LATIN_SHARE_FOR_MODEL); otherwise, and whenever the model is unavailable,
    by Levenshtein and its own threshold.

    Synchronous and CPU-bound: call it through asyncio.to_thread.
    """
    if not candidate_texts or not (new_text or "").strip():
        return None
    cosine, _gps, _minutes, levenshtein = _gates()
    threshold = cosine if cosine_threshold is None else cosine_threshold

    readable = _mostly_latin(new_text)
    by_model = [readable and _mostly_latin(t) for t in candidate_texts]

    similarities: dict = {}
    model = _get_embedding_model() if any(by_model) else None
    if model is not None:
        try:
            chosen = [i for i, use in enumerate(by_model) if use]
            vectors = model.encode(
                [new_text] + [candidate_texts[i] for i in chosen], convert_to_numpy=True
            )
            for i, vec in zip(chosen, vectors[1:]):
                similarities[i] = _cosine_similarity(vectors[0], vec)
        except Exception as e:
            logger.warning(f"Embedding failed for a post, using Levenshtein: {e}")
            similarities = {}

    # In candidate order, so the earliest copy is the one returned.
    for i, text_ in enumerate(candidate_texts):
        if i in similarities:
            if similarities[i] >= threshold:
                return i, round(similarities[i], 4), "cosine"
            continue
        sim = _levenshtein_similarity(new_text, text_)
        if sim >= levenshtein:
            return i, round(sim, 4), "levenshtein"
    return None

