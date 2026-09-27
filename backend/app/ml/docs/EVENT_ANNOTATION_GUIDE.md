# Event annotation guide

Phase 6 defines the human-review workflow for future event-level labels. No
event labels are fabricated from the current report dataset, and the current
unit fixtures are not ground truth.

## What is the same underlying event?

Use `EVENT_MATCH` when two candidates are evidence of the same physical
weather-driven occurrence, considering time, geography, impact progression,
and corroboration. A storm may produce multiple reports at nearby locations
within a coherent time window and still be one event when the evidence
supports a common occurrence.

Use `EVENT_NOT_MATCH` when the candidates represent separate physical events,
even if they share a weather phenomenon or label. Examples include:

- the same storm system causing distinct, spatially separated local incidents;
- the same location reporting separate flood episodes separated by a material
  time gap;
- two cloudbursts or floods with the same type but different occurrence times;
- reports that are duplicates of one another versus independent corroborating
  observations of one event.

Duplicate reports should not be counted as independent corroboration. A pair
of near-identical submissions may belong to the same event, but the annotation
reason should distinguish duplicate evidence from independent reports.

## Use `UNCERTAIN`

Use `UNCERTAIN` when the available evidence cannot distinguish a shared event
from separate events. This includes missing or unreliable timestamps or
coordinates, ambiguous event boundaries, conflicting reports, insufficient
context, and cases where the same broad weather system could plausibly explain
either one or multiple local incidents. Do not force a binary label to improve
coverage.

## Annotation fields and quality

`EventPairAnnotation` records the two candidate IDs, label, annotator, reason,
timestamp, optional canonical event ID, split, report IDs, and deterministic
event-definition hashes. Event pairs should be reviewed independently by more
than one annotator where feasible. Contradictory labels for one unordered pair
must be adjudicated and the reason retained.

Train/validation/test assignment must be grouped by canonical event. The same
canonical event, event ID, report ID, or near-identical event definition must
not cross splits. Run `validate_event_annotation_leakage()` before any metric
calculation.

## Interpretation

The event detector's `EVENT_EVIDENCE_SCORE` is heuristic evidence, not a
calibrated probability. Event-level evaluation may be reported only after
authoritative human labels exist. Until then, event metrics are
`DATA_UNAVAILABLE` or `NOT_AVAILABLE`, and candidate lifecycle state remains
`CANDIDATE` or `UNCERTAIN` unless a human explicitly confirms it.
