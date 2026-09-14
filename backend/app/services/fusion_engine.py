"""
INDRA Platform — FusionEngine
Computes the Verification Receipt as a weighted 6-factor confidence score,
assigns quadrant and review_status to verified events.
"""

import logging
import random
from typing import Dict, Any, List, Optional

from app.models.enums import Severity, ReviewStatus, Quadrant

logger = logging.getLogger("indra.services.fusion_engine")


# ── Factor weights ─────────────────────────────────────────────────────────────
FACTORS = {
    "weather_station": {"weight": 0.25, "label": "Weather Station Corroboration"},
    "report_density": {"weight": 0.20, "label": "Report Density Analysis"},
    "spatial_coherence": {"weight": 0.20, "label": "Spatial Coherence Score"},
    "vision_analysis": {"weight": 0.15, "label": "Computer Vision Analysis"},
    "source_reliability": {"weight": 0.15, "label": "Source Reliability Index"},
    "anomaly_detection": {"weight": 0.05, "label": "Anomaly Detection Signal"},
}


class FusionEngine:
    """
    Computes the multi-factor verification receipt and assigns quadrant + status.
    """

    def compute_receipt(
        self,
        weather_score: Optional[float] = None,
        report_density_score: Optional[float] = None,
        spatial_score: Optional[float] = None,
        vision_score: Optional[float] = None,
        reliability_score: Optional[float] = None,
        anomaly_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compute the verification receipt.

        Each factor that is None is scored 0.0 with evidence "Telemetry factor offline".
        Returns { "confidence_score": float, "factors": [...], "total_weighted": float }
        """
        scores = {
            "weather_station": weather_score,
            "report_density": report_density_score,
            "spatial_coherence": spatial_score,
            "vision_analysis": vision_score,
            "source_reliability": reliability_score,
            "anomaly_detection": anomaly_score,
        }

        factors: List[Dict[str, Any]] = []
        total_weighted = 0.0

        for key, meta in FACTORS.items():
            raw_score = scores.get(key)
            if raw_score is None:
                raw_score = 0.0
                evidence = "Telemetry factor offline"
            else:
                raw_score = max(0.0, min(1.0, raw_score))
                evidence = f"{meta['label']} data integrated"

            weight_pct = meta["weight"] * 100
            weighted_points = raw_score * meta["weight"]
            total_weighted += weighted_points

            factors.append({
                "factor": meta["label"],
                "weight_pct": weight_pct,
                "score": round(raw_score, 4),
                "weighted_points": round(weighted_points, 4),
                "evidence": evidence,
            })

        confidence = round(max(0.0, min(1.0, total_weighted)), 4)

        return {
            "confidence_score": confidence,
            "factors": factors,
            "total_weighted": round(total_weighted, 4),
        }

    def assign_quadrant(
        self, severity: Severity, confidence: float
    ) -> Quadrant:
        """
        Quadrant assignment based on severity and confidence.

        - severity ∈ {HIGH, CRITICAL} & C ≥ 0.90 → "Critical Verified Event"
        - severity ∈ {HIGH, CRITICAL} & C < 0.90 → "Unverified Threat"
        - severity ∈ {ADVISORY, MODERATE} & C ≥ 0.70 → "Confirmed Minor Event"
        - else → "Noise"
        - Default (can't determine) → "Unverified Threat" (fail-safe)
        """
        try:
            high_severities = {Severity.HIGH, Severity.CRITICAL}
            low_severities = {Severity.ADVISORY, Severity.MODERATE}

            if severity in high_severities:
                if confidence >= 0.90:
                    return Quadrant.CRITICAL_VERIFIED
                else:
                    return Quadrant.UNVERIFIED_THREAT

            if severity in low_severities:
                if confidence >= 0.70:
                    return Quadrant.CONFIRMED_MINOR
                else:
                    return Quadrant.NOISE

            # Fail-safe: default to Unverified Threat
            return Quadrant.UNVERIFIED_THREAT

        except Exception:
            return Quadrant.UNVERIFIED_THREAT

    def determine_review_status(
        self, confidence: float, auto_threshold: float = 0.90, review_threshold: float = 0.70
    ) -> ReviewStatus:
        """
        Route event to the appropriate review status based on confidence.

        - C ≥ auto_threshold → AUTO_PUBLISHED
        - C ≥ review_threshold → PENDING_HUMAN_REVIEW
        - else → QUARANTINED
        """
        if confidence >= auto_threshold:
            return ReviewStatus.AUTO_PUBLISHED
        elif confidence >= review_threshold:
            return ReviewStatus.PENDING_HUMAN_REVIEW
        else:
            return ReviewStatus.QUARANTINED

    def generate_heuristic_scores(self) -> Dict[str, float]:
        """
        Stub for perception layers (NLP + CV).
        Returns plausible random scores for factors that don't have real data yet.
        """
        return {
            "weather_score": round(random.uniform(0.70, 0.95), 3),
            "report_density_score": round(random.uniform(0.60, 0.95), 3),
            "spatial_score": round(random.uniform(0.65, 0.95), 3),
            "vision_score": round(random.uniform(0.70, 0.95), 3),
            "reliability_score": round(random.uniform(0.60, 0.90), 3),
            "anomaly_score": round(random.uniform(0.50, 0.85), 3),
        }
