/**
 * INDRA Platform - Frontend event-state derivation
 *
 * The backend fallback generator sets review_status and quadrant independently
 * of each other and of the confidence rule. This file implements the documented
 * 2x2 matrix (Feature 3.3 in understand.md) so every rendering path shows an
 * internally consistent state, regardless of what the API actually sent.
 *
 * Since 24 Sep (BUG-070) this is a fallback only: safeEventState shows the
 * API's review_status and quadrant whenever the response carries them, and
 * derives a state only for a response that does not.
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

const REVIEW_LABELS: Record<string, string> = {
  AUTO_PUBLISHED: "Auto-Published",
  PENDING_HUMAN_REVIEW: "Pending Human Review",
  QUARANTINED: "Quarantined",
  HUMAN_APPROVED: "Approved",
  REJECTED: "Rejected",
};

/**
 * The event's review state as the API sent it (BUG-070).
 *
 * This used to return the derivation above whatever the API said, and use the
 * API's value only for a console warning. So an approved event kept its
 * machine pill and its Approve button (a second approve then 409s), a
 * Moderate event at 0.60-0.69 waiting for a human was shown as "Quarantined /
 * Noise", and one at 0.70-0.89 as "Auto-Published", a publication that never
 * happened. The backend routes at 0.60 and applies the severity rule itself
 * (BUG-067), so its status is the truth to show. The derivation is kept only
 * as the fallback for a response that carries no status at all.
 */
export function safeEventState(
  eventId: string,
  severity: string | null | undefined,
  confidenceScore: number | null | undefined,
  apiReviewStatus?: string | null,
  apiQuadrant?: string | null,
): DerivedEventState {
  if (apiReviewStatus && REVIEW_LABELS[apiReviewStatus]) {
    return {
      reviewStatus: apiReviewStatus,
      reviewLabel: REVIEW_LABELS[apiReviewStatus],
      quadrant: apiQuadrant || deriveEventState(severity, confidenceScore).quadrant,
    };
  }
  return deriveEventState(severity, confidenceScore);
}
