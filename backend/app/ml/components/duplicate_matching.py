"""Policy-compliant deterministic duplicate matching.

This component is deliberately independent of the live backend. It receives
already-loaded reports and transforms them with a committed, development-only
frozen feature state. It never fits or mutates feature state during inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from app.ml.config import DEFAULT_DUPLICATE_MATCHING_CONFIG, DuplicateMatchingConfig
from app.ml.components.duplicate_features import (
    DuplicateFeatureState,
    load_feature_state,
    normalize_text,
)
from app.ml.contracts import (
    CandidateReport,
    DuplicatePrediction,
    PredictionStatus,
    ReportInput,
)


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return geodesic distance in kilometres, not raw degree distance."""

    earth_radius_km = 6371.0088
    lat_a = np.radians(latitude_a)
    lat_b = np.radians(latitude_b)
    delta_lat = np.radians(latitude_b - latitude_a)
    delta_lon = np.radians(longitude_b - longitude_a)
    value = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(lat_a) * np.cos(lat_b) * np.sin(delta_lon / 2.0) ** 2
    )
    value = np.clip(value, 0.0, 1.0)
    return float(earth_radius_km * 2.0 * np.arctan2(np.sqrt(value), np.sqrt(1.0 - value)))


def temporal_distance_minutes(report: ReportInput, candidate: CandidateReport) -> float:
    return abs((report.occurred_at - candidate.occurred_at).total_seconds()) / 60.0


def _linear_proximity(distance: float, gate: float) -> float:
    return max(0.0, min(1.0, 1.0 - (distance / gate)))


def edit_similarity(text_a: str, text_b: str) -> float:
    """Use the installed fast implementation when available, with stdlib fallback."""

    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0
    try:
        import Levenshtein

        return float(Levenshtein.ratio(text_a, text_b))
    except ImportError:
        return float(SequenceMatcher(None, text_a, text_b, autojunk=False).ratio())


def _sparse_cosine(vector_a: dict[int, float], vector_b: dict[int, float]) -> float:
    if not vector_a or not vector_b:
        return 0.0
    if len(vector_a) > len(vector_b):
        vector_a, vector_b = vector_b, vector_a
    dot = sum(value * vector_b.get(index, 0.0) for index, value in vector_a.items())
    return max(0.0, min(1.0, float(dot)))


@dataclass(frozen=True)
class _CandidateScore:
    candidate: CandidateReport
    character_similarity: float
    word_similarity: float
    edit_similarity: float
    geographic_similarity: float
    temporal_similarity: float
    geographic_distance_km: float
    temporal_distance_minutes: float
    text_similarity: float
    combined_score: float


class DuplicateMatcher:
    """Deterministic multi-signal matcher over caller-provided candidates."""

    component_name = "duplicate_matcher"
    method = "char_word_tfidf+edit_similarity+haversine+temporal_proximity"

    def __init__(
        self,
        config: DuplicateMatchingConfig | None = None,
        feature_state: DuplicateFeatureState | None = None,
    ) -> None:
        self.config = config or DEFAULT_DUPLICATE_MATCHING_CONFIG
        self._feature_state_error: str | None = None
        if feature_state is not None:
            self.feature_state = feature_state
        else:
            try:
                self.feature_state = load_feature_state(self.config.feature_state_path)
            except Exception as error:
                self.feature_state = None
                self._feature_state_error = f"{type(error).__name__}: {error}"
        if self.feature_state is not None:
            if self.feature_state.feature_version != self.config.feature_version:
                raise ValueError("feature state and matcher feature versions differ")
            if self.feature_state.preprocessing_version != self.config.preprocessing_version:
                raise ValueError("feature state and matcher preprocessing versions differ")
            if tuple(self.feature_state.char_space.ngram_range) != tuple(self.config.char_ngram_range):
                raise ValueError("feature state and matcher character n-gram ranges differ")
            if tuple(self.feature_state.word_space.ngram_range) != tuple(self.config.word_ngram_range):
                raise ValueError("feature state and matcher word n-gram ranges differ")

    def _eligible_candidates(
        self, report: ReportInput
    ) -> tuple[list[CandidateReport], int, list[str]]:
        eligible: list[CandidateReport] = []
        evidence: list[str] = []
        for candidate in report.candidate_reports:
            distance = haversine_km(
                report.latitude,
                report.longitude,
                candidate.latitude,
                candidate.longitude,
            )
            elapsed = temporal_distance_minutes(report, candidate)
            if distance <= self.config.geographic_gate_km and elapsed <= self.config.temporal_gate_minutes:
                eligible.append(candidate)
            else:
                evidence.append(
                    f"gated candidate {candidate.report_id}: "
                    f"distance_km={distance:.4f}, time_minutes={elapsed:.4f}"
                )
        return eligible, len(eligible), evidence

    def _score_candidates(
        self, report: ReportInput, candidates: list[CandidateReport]
    ) -> list[_CandidateScore]:
        if self.feature_state is None:
            return []
        normalized_new = normalize_text(report.text)
        normalized_candidates = [normalize_text(candidate.text) for candidate in candidates]
        new_char = self.feature_state.char_space.transform(normalized_new)
        new_word = self.feature_state.word_space.transform(normalized_new)
        text_weight = self.config.char_weight + self.config.word_weight + self.config.edit_weight
        results: list[_CandidateScore] = []

        for index, candidate in enumerate(candidates):
            normalized_candidate = normalized_candidates[index]
            char_score = _sparse_cosine(
                new_char,
                self.feature_state.char_space.transform(normalized_candidate),
            )
            word_score = _sparse_cosine(
                new_word,
                self.feature_state.word_space.transform(normalized_candidate),
            )
            edit_score = edit_similarity(normalized_new, normalized_candidate)
            distance = haversine_km(
                report.latitude,
                report.longitude,
                candidate.latitude,
                candidate.longitude,
            )
            elapsed = temporal_distance_minutes(report, candidate)
            geographic_score = _linear_proximity(distance, self.config.geographic_gate_km)
            temporal_score = _linear_proximity(elapsed, self.config.temporal_gate_minutes)
            text_score = (
                self.config.char_weight * char_score
                + self.config.word_weight * word_score
                + self.config.edit_weight * edit_score
            ) / text_weight
            combined_score = (
                self.config.char_weight * char_score
                + self.config.word_weight * word_score
                + self.config.edit_weight * edit_score
                + self.config.geographic_weight * geographic_score
                + self.config.temporal_weight * temporal_score
            )
            results.append(
                _CandidateScore(
                    candidate=candidate,
                    character_similarity=char_score,
                    word_similarity=word_score,
                    edit_similarity=edit_score,
                    geographic_similarity=geographic_score,
                    temporal_similarity=temporal_score,
                    geographic_distance_km=distance,
                    temporal_distance_minutes=elapsed,
                    text_similarity=round(max(0.0, min(1.0, float(text_score))), 12),
                    combined_score=round(max(0.0, min(1.0, float(combined_score))), 12),
                )
            )
        return results

    def predict(self, report: ReportInput) -> DuplicatePrediction:
        candidate_count = len(report.candidate_reports)
        base = {
            "status": PredictionStatus.AVAILABLE,
            "model_version": None,
            "feature_version": self.config.feature_version,
            "preprocessing_version": self.config.preprocessing_version,
            "text_threshold": self.config.text_similarity_threshold,
            "threshold": self.config.combined_threshold,
            "threshold_status": self.config.threshold_status,
            "candidate_count": candidate_count,
            "comparisons_performed": 0,
            "method": self.method,
        }

        if self.feature_state is None:
            return DuplicatePrediction(
                **base,
                status=PredictionStatus.ERROR,
                reason_codes=["FEATURE_STATE_UNAVAILABLE"],
                warnings=[self._feature_state_error or "Feature state is unavailable."],
            )

        if candidate_count == 0:
            base["status"] = PredictionStatus.NOT_APPLICABLE
            return DuplicatePrediction(
                **base,
                reason_codes=["NO_CANDIDATES"],
                warnings=["No candidate reports were supplied for comparison."],
            )

        if not normalize_text(report.text):
            base["status"] = PredictionStatus.INSUFFICIENT_DATA
            return DuplicatePrediction(
                **base,
                reason_codes=["EMPTY_TEXT"],
                warnings=["Empty report text cannot produce a text similarity."],
            )

        eligible, comparisons, gate_evidence = self._eligible_candidates(report)
        base["comparisons_performed"] = comparisons
        if not eligible:
            return DuplicatePrediction(
                **base,
                is_duplicate=False,
                reason_codes=["NO_CANDIDATE_WITHIN_GATES"],
                evidence=[
                    f"candidate_count={candidate_count}",
                    "comparisons_performed=0",
                    *gate_evidence,
                ],
            )

        scored = self._score_candidates(report, eligible)
        best = max(scored, key=lambda item: (item.combined_score, str(item.candidate.report_id)))
        is_duplicate = (
            best.text_similarity >= self.config.text_similarity_threshold
            and best.combined_score >= self.config.combined_threshold
        )
        reasons = [
            "MATCH_ABOVE_PROVISIONAL_THRESHOLD"
            if is_duplicate
            else "BELOW_PROVISIONAL_THRESHOLD"
        ]
        if best.text_similarity < self.config.text_similarity_threshold:
            reasons.append("TEXT_SIMILARITY_BELOW_THRESHOLD")
        if best.combined_score < self.config.combined_threshold:
            reasons.append("COMBINED_SCORE_BELOW_THRESHOLD")
        evidence = [
            f"candidate_count={candidate_count}",
            f"comparisons_performed={comparisons}",
            f"candidate_id={best.candidate.report_id}",
            f"character_similarity={best.character_similarity:.6f}",
            f"word_similarity={best.word_similarity:.6f}",
            f"edit_similarity={best.edit_similarity:.6f}",
            f"geographic_similarity={best.geographic_similarity:.6f}",
            f"temporal_similarity={best.temporal_similarity:.6f}",
            f"text_similarity={best.text_similarity:.6f}",
            f"combined_similarity={best.combined_score:.6f}",
        ]
        return DuplicatePrediction(
            **base,
            is_duplicate=is_duplicate,
            candidate_id=best.candidate.report_id,
            matched_report_id=best.candidate.report_id if is_duplicate else None,
            similarity=best.combined_score,
            text_similarity=best.text_similarity,
            character_similarity=best.character_similarity,
            word_similarity=best.word_similarity,
            edit_similarity=best.edit_similarity,
            geographic_similarity=best.geographic_similarity,
            temporal_similarity=best.temporal_similarity,
            geographic_distance_km=best.geographic_distance_km,
            temporal_distance_minutes=best.temporal_distance_minutes,
            reason_codes=reasons,
            evidence=evidence,
        )
