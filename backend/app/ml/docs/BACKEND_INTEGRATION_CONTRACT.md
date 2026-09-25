# Backend integration contract

Status: `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY`

This document defines the boundary for a future, separately authorized backend
integration. It does not authorize live pipeline changes. The backend must call
the ML layer with already-loaded values; the ML layer must not query platform
state, persist decisions, consume Kafka, or control event lifecycle state.

## Stable interface

### Input: `ReportInput`

`app.ml.contracts.ReportInput` is the only unified single-report input. Required
fields are:

| Field | Type | Owner |
|---|---|---|
| `report_id` | UUID | Backend |
| `text` | string | Backend |
| `occurred_at` | datetime | Backend |
| `latitude` | float in `[-90, 90]` | Backend |
| `longitude` | float in `[-180, 180]` | Backend |
| `source_type` | non-empty string | Backend |

Optional already-loaded context is supplied through `source_metadata`,
`candidate_reports`, `station_observations`, and `image_bytes`. The backend may
omit unavailable context. The ML layer must preserve that absence through
explicit result states rather than substituting invented values.

Candidate retrieval remains backend-owned. Candidate records must include the
candidate report ID, text, timestamp, latitude, and longitude. Event grouping
is a batch operation and requires the backend to construct already-loaded
`EventObservation` values. A lone `ReportInput` creates only a provisional
single-report event `CANDIDATE`; it never creates a confirmed event or owns an
event lifecycle transition.

### Output: `UnifiedMLResult`

`app.ml.contracts.UnifiedMLResult` is the only unified output. It contains:

- `report_id` and `schema_version`;
- `text_prediction`;
- `duplicate_prediction`;
- `event_prediction`;
- `credibility_prediction`;
- `image_prediction`;
- `anomaly_prediction`;
- component `model_versions` and `feature_versions`;
- aggregated `warnings` and `errors`.

Every component result has an explicit `PredictionStatus`. A caller must handle
`AVAILABLE`, `NOT_APPLICABLE`, `OFFLINE`, `ERROR`, `NOT_IMPLEMENTED`,
`INSUFFICIENT_DATA`, and `HEURISTIC_ONLY`; a non-available result must not be
coerced to a zero score, `false`, or an empty prediction with implied success.

The supported local entry point is:

```python
from app.ml.orchestration.service import analyze_report

result = analyze_report(report_input)
```

Before any future integration release, `app.ml.release_gate.validate_ml_release()`
must return `release_ready=true` and every component production gate must be
`PRODUCTION_VALIDATED`. The current result is deliberately false.

## Ownership boundary

| Backend remains responsible for | ML layer remains responsible for |
|---|---|
| Database access and transactions | Local feature extraction |
| Kafka production and consumption | Local inference over supplied values |
| Authentication and authorization | Typed predictions and explicit statuses |
| HTTP/API validation and response mapping | Evidence and reason codes |
| Persistence and audit records | Model, feature, and preprocessing metadata |
| Candidate retrieval | Evaluation metadata and release-gate evidence |
| Event lifecycle and state transitions | Deterministic event grouping proposals |
| Human-review queues and adjudication actions | Never replacing human adjudication |

The backend decides whether and how to persist a result. The ML layer does not
publish, suppress, merge, authenticate, authorize, or mutate a report or event.
Duplicate similarity, event evidence, credibility risk, and anomaly outlier
scores are distinct quantities and must not be remapped to probabilities.

## Integration prerequisites

1. All six component production gates pass against independent evidence.
2. The complete backend suite is verified in an environment containing its
   declared test dependencies.
3. The legacy dedup migration is separately approved and its regression and
   rollback criteria pass.
4. Input/output schema compatibility is verified at the exact integration
   commit.
5. Artifact authorization and version checks run before serving traffic.
6. Missing-data and component-unavailability branches are covered by backend
   integration tests.
7. Persistence, event lifecycle, and human-review behavior are approved by the
   backend owners; the ML package must not take those responsibilities.

No live backend integration is authorized by Phase 11.
