/**
 * INDRA Platform - Frontend event-state derivation
 *
 * The backend fallback generator sets review_status and quadrant independently
 * of each other and of the confidence rule. This file implements the documented
 * 2x2 matrix (Feature 3.3 in understand.md) so every rendering path shows an
 * internally consistent state, regardless of what the API actually sent.
 *
 * NOTE TO BACKEND TEAM: The correct fix is to move this same logic into the
 * backend event-generation and review-status derivation paths, so that
 * review_status and quadrant are always derived from (severity, confidence_score)
 * rather than set independently. Until that happens, the frontend corrects the
 * inconsistency here and logs a warning so the mismatch stays visible in dev-tools.
 *
 * Rule (understand.md section 3.3 - 2x2 Severity x Confidence Matrix):
 *   High/Critical  + >= 90%   -> Critical Verified Event / AUTO_PUBLISHED
 *   High/Critical  + <  90%   -> Unverified Threat       / PENDING_HUMAN_REVIEW
 *   Low/Mod/Adv    + >= 70%   -> Confirmed Minor Event   / AUTO_PUBLISHED
 *   Low/Mod/Adv    + <  70%   -> Noise                   / QUARANTINED
 *   Missing/unparseable        -> Unverified Threat       / PENDING_HUMAN_REVIEW (fail safe)
 */

export type DerivedEventState = {
  quadrant: string;
  reviewStatus: string;
  reviewLabel: string;
};

const HIGH_SEVERITY = new Set(["high", "critical", "HIGH", "CRITICAL"]);
const LOW_SEVERITY  = new Set(["low", "moderate", "advisory", "LOW", "MODERATE", "ADVISORY"]);

/** Fail-safe default when severity or confidence cannot be interpreted. */
const UNVERIFIED_THREAT: DerivedEventState = {
  quadrant:     "Unverified Threat",
  reviewStatus: "PENDING_HUMAN_REVIEW",
  reviewLabel:  "Pending Human Review",
};

/**
 * Derive the canonical quadrant and review-status for a weather event from its
 * severity and confidence score, implementing the documented 2x2 matrix.
 *
 * @param severity        Severity string from the API (case-insensitive).
 * @param confidenceScore Confidence value as fraction [0,1] or percent [0,100].
 *                        Values above 1 are treated as percentages.
 */
export function deriveEventState(
  severity: string | null | undefined,
  confidenceScore: number | null | undefined,
): DerivedEventState {
  if (!severity || typeof severity !== "string") return UNVERIFIED_THREAT;
  if (confidenceScore == null || typeof confidenceScore !== "number" || isNaN(confidenceScore)) {
    return UNVERIFIED_THREAT;
  }

  // Normalise to percentage (0-100). Backend sends fractions (0.83 = 83%).
  const pct = confidenceScore > 1 ? confidenceScore : confidenceScore * 100;

  if (HIGH_SEVERITY.has(severity)) {
    if (pct >= 90) {
      return {
        quadrant:     "Critical Verified Event",
        reviewStatus: "AUTO_PUBLISHED",
        reviewLabel:  "Auto-Published",
      };
    }
    return UNVERIFIED_THREAT; // High/Critical + <90% -> human review, NEVER auto-publish
  }

  if (LOW_SEVERITY.has(severity)) {
    if (pct >= 70) {
      return {
        quadrant:     "Confirmed Minor Event",
        reviewStatus: "AUTO_PUBLISHED",
        reviewLabel:  "Auto-Published",
      };
    }
    return {
      quadrant:     "Noise",
      reviewStatus: "QUARANTINED",
      reviewLabel:  "Quarantined",
    };
  }

  return UNVERIFIED_THREAT; // Unknown severity -> fail safe
}

/**
 * Warn when the derived state disagrees with what the API sent. Keeps the
 * mismatch visible in dev-tools without hiding it from the UI.
 */
export function warnIfMismatch(
  eventId: string,
  apiReviewStatus: string | null | undefined,
  derived: DerivedEventState,
): void {
  if (!apiReviewStatus) return;
  if (apiReviewStatus !== derived.reviewStatus) {
    console.warn(
      '[INDRA] Event ' + eventId + ': review_status mismatch - ' +
      'API said ' + apiReviewStatus + ', derived ' + derived.reviewStatus + ' ' +
      'from (severity, confidence). ' +
      'Root cause: backend fallback sets review_status independently of the 2x2 rule.'
    );
  }
}

/**
 * Derive state, warn on mismatch, return derived state.
 * Use this wherever you previously read event.review_status directly.
 */
export function safeEventState(
  eventId: string,
  severity: string | null | undefined,
  confidenceScore: number | null | undefined,
  apiReviewStatus?: string | null,
): DerivedEventState {
  const derived = deriveEventState(severity, confidenceScore);
  warnIfMismatch(eventId, apiReviewStatus, derived);
  return derived;
}
