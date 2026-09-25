/**
 * INDRA Platform - an event's review state, as the API sent it
 *
 * The backend decides review_status and quadrant: it routes at 0.60 and
 * applies the severity rule itself (BUG-067), so its values are the truth to
 * show on every card, list and receipt (BUG-070). A status the API did not
 * send, or one this file does not know, is shown as 'Status not reported'. It
 * is never worked out from severity and confidence.
 *
 * Removed 25 Sep: the 90 %/70 % severity-by-confidence derivation that stood in
 * for a missing status, whose thresholds no longer matched the backend.
 */

export type EventReviewState = {
  /** The API's quadrant, or '' when it sent none. */
  quadrant: string;
  /** The API's review_status, or 'UNKNOWN'. */
  reviewStatus: string;
  reviewLabel: string;
};

const REVIEW_LABELS: Record<string, string> = {
  AUTO_PUBLISHED: "Auto-Published",
  PENDING_HUMAN_REVIEW: "Pending Human Review",
  QUARANTINED: "Quarantined",
  HUMAN_APPROVED: "Approved",
  REJECTED: "Rejected",
};

export function eventReviewState(
  apiReviewStatus?: string | null,
  apiQuadrant?: string | null,
): EventReviewState {
  if (apiReviewStatus && REVIEW_LABELS[apiReviewStatus]) {
    return {
      reviewStatus: apiReviewStatus,
      reviewLabel: REVIEW_LABELS[apiReviewStatus],
      quadrant: apiQuadrant || '',
    };
  }
  return {
    reviewStatus: 'UNKNOWN',
    reviewLabel: 'Status not reported',
    quadrant: apiQuadrant || '',
  };
}
