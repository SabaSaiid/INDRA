# Phase 12 golden benchmark

> Historical Phase 12 benchmark snapshot. Later Phase 18–23 frozen artifacts exist; the current
> validation status and remaining evidence gaps are in `docs/ML_VALIDATION_REPORT.md`.

## Scope and interpretation

This benchmark is deterministic, local, synthetic engineering-regression
coverage for the six-component INDRA AI/ML subsystem. It exercises the path:

```text
ReportInput
  -> NLP
  -> DUPLICATE
  -> EVENT
  -> CREDIBILITY
  -> IMAGE
  -> ANOMALY
  -> UnifiedMLResult
```

All scenario data is marked `TEST_FIXTURE_ONLY`, `SYNTHETIC`, and
`NOT_PRODUCTION_DATA`. The suite-level validation scope is
`ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION`.

The benchmark proves stable software behavior for the committed fixtures. It
does **not** prove production validity, field accuracy, real-world event truth,
calibration, operational capacity, or production throughput.

`PRODUCTION_VALIDATION` remains `NOT_VALIDATED`.

## Versioned scenario contract

The source is
`backend/app/ml/golden/fixtures/golden_scenarios_v1.json`. Every scenario has:

- `scenario_id`, description, input, and deterministic expected properties;
- `scenario_version = golden-scenario-v1` and `schema_version = 1.0`;
- a timezone-aware `creation_timestamp`;
- a SHA-256 `fixture_hash` over the canonical scenario payload, excluding only
  the hash field itself;
- explicit fixture/data/validation markers;
- expected component statuses for every report;
- expected reason codes, event structure, duplicate relationship, or anomaly
  outcome where those values are stable by design.

The schema rejects unknown fields, missing report expectations, duplicate
scenario/report IDs, references to unknown reports, naive timestamps, and hash
mismatches. Exact floating-point predictions are not fixture requirements
unless the underlying operation is deliberately deterministic and stable.

## Scenarios

| ID | Synthetic case | Stable engineering assertion |
|---|---|---|
| 01 | Single ordinary report | NLP executes; duplicate/image are not applicable; anomaly history is insufficient; event output is a one-report provisional candidate. |
| 02 | Multiple related flood reports | One bounded group, deterministic duplicate link, and two independent reports from three inputs. |
| 03 | Distinct events | Geography/time separation produces three candidates rather than an invalid merge. |
| 04 | A-B-C union-find bridge | A-B and B-C proximity cannot bridge A-C beyond the complete-link diameter bound; two groups remain. |
| 05 | Duplicate flood reports | Near-identical colocated report matches the original and does not add independent event evidence. |
| 06 | Contradictory report | Credibility evidence emits inspectable inconsistency/review reasons without declaring factual falsity. |
| 07 | Image absent | Image status is `NOT_APPLICABLE`, with no labels, probabilities, confidence, or model load. |
| 08 | Insufficient anomaly history | Status is `INSUFFICIENT_DATA` and no anomaly score is fabricated. |
| 09 | Constructed anomalous rainfall | The local statistical baseline deterministically returns the expected synthetic weather-behavior anomaly outcome. |
| 10 | Missing/invalid weather data | Missing timestamp, non-finite measurement, and impossible negative rainfall are explicit validation errors. |

Scenario 09 is a unit/regression construction. Its result is not field
validation or an accuracy observation.

## Single-report event semantics

`EventDetector.predict()` returns `HEURISTIC_ONLY` with a typed
`SingleReportEventCandidate`. It contains exactly one report ID, NLP-derived
type evidence when available, candidate coordinates and timestamp, an
`EVENT_EVIDENCE_SCORE`, feature/algorithm versions, and lifecycle state
`CANDIDATE`.

Generic event confidence remains null. The reason codes include
`SINGLE_REPORT_EVENT_CANDIDATE` and `NOT_CONFIRMED_EVENT`. The one-report schema
cannot represent `CONFIRMED`; batch lifecycle transition to `CONFIRMED`
requires an explicit `human_confirmed=True` action.

One report is therefore an event hypothesis, never proof of a real event.

## Unified-result and semantic gates

Every scenario verifies:

- exact `UnifiedMLResult` field order and schema version;
- stable component order: NLP, duplicate, event, credibility, image, anomaly;
- expected statuses and exact model/feature version maps;
- non-empty version identifiers where supplied;
- unified warning/error aggregation semantics;
- null results rather than invented zero scores for unavailable inference;
- exact JSON object-to-serialize-to-deserialize equality;
- stable reason-code and evidence ordering.

The following invariants are named and asserted for every execution:

- `DUPLICATE_NE_FAKE`;
- `ANOMALY_NE_FALSE_REPORT`;
- `EVENT_NE_NLP_CLASSIFICATION`;
- `RISK_SCORE_NE_PROBABILITY`;
- `HEURISTIC_CONFIDENCE_NE_CALIBRATED_PROBABILITY`;
- `MISSING_INFERENCE_NE_ZERO_SCORE`;
- `IMAGE_EVIDENCE_NE_AUTHENTICITY_PROOF`;
- `SINGLE_REPORT_NE_CONFIRMED_EVENT`.

## Artifact, determinism, resource, and policy checks

The NLP JSON artifact and duplicate JSON feature state must pass shared
manifest authorization, exact file SHA-256, structural validation, and embedded
provenance checks. Duplicate character/word transformation is checked for exact
repeatability. The image and anomaly manifest entries and learned artifacts do
not exist, and absent/insufficient scenarios verify that no placeholder loader
is called.

Every scenario is run twice. Semantic payloads, component results, statuses,
reason codes, evidence ordering, and serialized values must be exactly equal.
Only nondeterministic batch-event timing observations are excluded from semantic
comparison; no broad floating-point tolerance hides output drift.

The resource regression verifies one NLP artifact load per classifier, one
duplicate-state load per matcher, one NLP vectorization per analyzed report,
stable component instances, stable artifact identities, immutable duplicate
state, and no retained `UnifiedMLResult` objects after callers release them.

Policy scans cover the new ML source tree and governed artifact directory.
Runtime downloads and external inference remain disabled. Golden execution is
also run with socket construction blocked. No pretrained/open-weight model,
external embedding, external AI API, cloud inference, or network access is used
by this subsystem. The quarantined legacy classifier and legacy artifact are
not imported or authorized by the unified engine.

## Recorded local performance observation

The raw record is
`backend/app/ml/golden/fixtures/golden_benchmark_results.json`. It was captured
on 2026-09-22 with Python 3.14.3 on Windows 11 using `perf_counter` wall time.
Artifact loading is measured separately and excluded from the warmed engine
measurements.

Artifact observations:

| Artifact | Manifest/hash/structure | Load seconds |
|---|---:|---:|
| `nlp_classifier_v1.json` | passed | 0.033980 |
| `duplicate_feature_state.json` | passed | 0.001406 |

Complete local-engine observations:

| Reports | Total s | NLP s | Duplicate s | Event s | Credibility s | Image s | Anomaly s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.003429 | 0.001925 | 0.000024 | 0.000181 | 0.001201 | 0.000020 | 0.000015 |
| 10 | 0.016053 | 0.013800 | 0.000095 | 0.000823 | 0.000766 | 0.000089 | 0.000058 |
| 100 | 0.154151 | 0.138237 | 0.000920 | 0.007593 | 0.003713 | 0.000612 | 0.000437 |

These are one-machine engineering observations, not production throughput or
latency targets. A portable test catches only gross regressions by using a
documented floor plus generous multipliers over the recorded values. The guard
is explicitly `GROSS_LOCAL_REGRESSION_ONLY` and `production_slo = false`.

## Known limitations

- Inputs are constructed fixtures and do not represent citizen, station, image,
  language, geographic, seasonal, adversarial, or operational distributions.
- The NLP artifact is development-only and its release gate remains closed.
- Duplicate thresholds are provisional and lack an authoritative labelled
  pair dataset.
- Event grouping has no authoritative event-level ground truth.
- Credibility is an uncalibrated rule baseline and does not determine truth.
- No trained image model or learned anomaly artifact exists.
- The rainfall anomaly scenario tests deterministic mechanics, not field
  detection quality.
- Timings exclude database, queue, network, persistence, API, and frontend
  work, and vary by host load and hardware.
- Passing this suite cannot promote any component to production validated.
