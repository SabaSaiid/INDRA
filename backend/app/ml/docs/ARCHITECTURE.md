# INDRA AI/ML architecture

> Historical phase-scoped architecture snapshot. For the current frozen six-component implementation,
> backend wiring, and release status, use `docs/ML_ARCHITECTURE.md` and `docs/ML_VALIDATION_REPORT.md`.

```text
existing backend
    │ already-loaded ReportInput
    ▼
local ML boundary
    │
    ├── 1. NLP classifier
    ├── 2. duplicate matcher
    ├── 3. event detector (single report -> provisional candidate only)
    ├── 4. credibility-risk detector (consumes 1–3 evidence)
    ├── 5. image analyzer
    └── 6. anomaly detector
    │ typed component predictions
    ▼
UnifiedMLResult
    │
    ▼
existing backend persistence, fusion, review, and API layers
```

The ML subsystem does not own PostgreSQL, PostGIS, Kafka, authentication,
frontend state, external ingestion, deployment, or event persistence.

The new engine has one locally trained development classifier available:
`NLPClassifier`. Other components expose local statistical/rule-based
baselines or explicit unavailable states according to their phase; they do not
fabricate learned inference when no approved artifact exists. No component
downloads a model or calls an external inference API.

The former MiniLM-based implementation remains legacy and is excluded from the
new engine.  It is not a compatibility dependency.

## Phase 14 NLP development boundary

`app.ml.training.nlp_development` is an offline-only experiment boundary. It
creates a deterministic 168/42 train/validation split from the existing 210
development rows, runs a fixed 12-configuration search using validation only,
fits validation-only temperature scaling, and serializes an opt-in v2 JSON
artifact. The configuration-selection function has no final-test input. A
separate finalization path requires the frozen manifest and creates an
exclusive receipt before one protected test access.

The default `NLPClassifierConfig`, `InferenceEngine`, live services, API,
Kafka, database, and frontend are unchanged and continue to use the existing
v1 development path. The v2 artifact can be loaded only through an explicit
configuration and remains `DEVELOPMENT_ONLY / NOT_VALIDATED` for production.
See `NLP_DEVELOPMENT_VALIDATION.md`.

## Phase 12 golden regression boundary

`app.ml.golden` is an isolated, local test/benchmark boundary around the same
`InferenceEngine`; it is not a parallel inference implementation. A strict
versioned schema loads ten synthetic scenarios, runs the six components, and
checks exact typed structure, component order, status/version propagation,
warning/error aggregation, serialization, deterministic evidence order, and
cross-component semantic invariants. Batch event grouping and explicit anomaly
windows are exercised after each report has traversed the unified engine.

Each fixture is hash-bound and marked `TEST_FIXTURE_ONLY`, `SYNTHETIC`, and
`NOT_PRODUCTION_DATA`. Local 1/10/100-report timings are engineering-regression
observations only; artifact loading is recorded separately. The harness does
not connect to PostgreSQL/PostGIS, Kafka, Redis, the live report pipeline, API
routes, authentication, frontend state, or external ingestion. See
`GOLDEN_BENCHMARK.md`.

## Duplicate matching

Phase 3 stabilizes the independent `DuplicateMatcher` component introduced in
Phase 2.

It evaluates caller-provided candidates in this order:

1. Cheap Haversine geographic and elapsed-time gates.
2. Character TF-IDF cosine similarity using the frozen configurable 3–5
   character n-gram state.
3. Word TF-IDF cosine similarity using the frozen configurable 1–2 word
   n-gram state.
4. Edit-derived similarity using `python-Levenshtein`, with a standard-library
   fallback.
5. Transparent weighted combination of text, geographic, and temporal signals.

Inference transforms text with the committed JSON feature state at
`backend/app/ml/artifacts/duplicate_feature_state.json`; it never fits on the
incoming comparison batch. The state is explicitly `development_only` and
records its corpus identifier/hash, feature/preprocessing versions, creation
timestamp, and library version. Before parsing, the loader requires the local
file to match its `COMPLIANT` shared-manifest entry and SHA-256. It is not a
production model artifact and is not a claim that the current corpus
represents deployment traffic.

The component does not retrieve candidates, access a database, use Kafka, call
HTTP, or load the legacy MiniLM implementation.

The default weights and gates are provisional configuration, not learned or
production-validated thresholds.

## Event detection framework

Event detection is distinct from report-level NLP classification. NLP answers
which phenomenon an individual report mentions; the event framework asks
whether multiple already-loaded observations are consistent with one
underlying event.

`EventDetector.detect()` accepts typed `EventObservation` values. The
`event-grouping-v2` algorithm performs a deterministic temporal sweep,
geographic Haversine gating, explicit event-type compatibility checks, and
caller-supplied duplicate-link handling. It uses complete-link cluster bounds:
every member pair must remain inside the configured spatial and temporal
limits and satisfy type compatibility. This prevents an A–B–C bridge from
merging A and C when they exceed a configured bound. It
does not query PostgreSQL/PostGIS, Kafka, Redis, HTTP, or any external API.
The temporal sweep stops once the configured time window is exceeded, keeping
comparisons bounded by the local time window rather than blindly comparing all
reports.

Each `EventCandidate` records its report IDs, centroid, time range, duration,
source diversity, independent-report count, versioned feature snapshot, and
inspectable evidence. The score is named `EVENT_EVIDENCE_SCORE` /
`PROVISIONAL_EVENT_CONFIDENCE`; it is not a calibrated probability. Candidate
states are `CANDIDATE`, `UNCERTAIN`, `MERGED`, `CONFIRMED`, and `CLOSED`.
`CONFIRMED` requires explicit human confirmation and is never assigned by the
heuristic grouping run.

`EventDetector.predict()` adapts one already-loaded `ReportInput` into a typed
`SingleReportEventCandidate`. The result is `HEURISTIC_ONLY`, contains exactly
one report ID, uses an explicitly named `EVENT_EVIDENCE_SCORE`, and has the
fixed lifecycle `CANDIDATE`. It cannot represent a confirmed event. This
single-report path supplies typed upstream event evidence to credibility
assessment without reinterpreting one report as proof that an event occurred.

No event-level ground truth exists in the current repository, so there is no
learned event detector, event model artifact, or production accuracy claim.

## Credibility-risk framework

Phase 7 separates the existing backend `LEGACY_CREDIBILITY_PRIOR` from the new
`RULE_BASED_CREDIBILITY_BASELINE`. The new component consumes already-loaded
report, duplicate, event, image-interface, source, temporal, and geographic
metadata. It performs no database, Kafka, Redis, HTTP, authentication, or
frontend access.

The baseline extracts transparent text, metadata, temporal, geographic,
duplication, source-history, and event-consistency features. Each fired rule
returns structured evidence with a code, value, interpretation, severity, and
provenance. Duplicate or event inconsistency signals request review; neither
is treated as proof that a report is false.

The output is an uncalibrated risk score and risk level. It is not a truth
probability. The live `FakeDetector.fit()` remains blocked because the
repository has no approved human-adjudicated fake/misleading-report dataset.

Phase 21 adds a separate offline synthetic-development path. It consumes the
same `CredibilityFeatureSnapshot`, fits a portable local logistic regression,
and uses validation-only temperature scaling plus an `UNCERTAIN` abstention
band. The path is not imported by the live engine, and its probability means
modeled `MISLEADING_RISK_EVIDENCE`, not truth. Hidden generator identity is
physically and structurally excluded from detector input. The artifact remains
`NOT_VALIDATED` for production.

## NLP event classification

Phase 5 trains a multiclass text classifier from the project-controlled
`data/labelled/reports_v1.csv` development dataset. The training path fits a
character TF-IDF space over 3–5 character n-grams and a word TF-IDF space over
1–2 word n-grams on the explicit training split only. A logistic-regression
classifier is selected by cross-validation on training rows only; the test
split remains untouched until final evaluation.

The resulting JSON artifact stores both frozen feature spaces and the
classifier coefficients. Runtime inference uses that JSON state directly and
supports raw text or an already-loaded `ReportInput`. It returns typed class
probabilities, confidence, evidence, model/feature/preprocessing versions,
and an explicit offline or empty-text state when inference cannot be produced.
The runtime first authorizes the exact local filename, intended component,
policy status, and SHA-256 through the shared manifest, then validates fitted
dimensions and embedded dataset/version/seed provenance.

The current corpus is synthetic and development-only. The trained artifact is
registered as policy-compliant for local loading, but its metrics do not
constitute production validation. The acceptance gate currently remains
closed because the NOT_RELEVANT recall threshold is not met.

## Image analysis framework

Phase 8 accepts a typed `ImageInput` containing already-loaded bytes and local
identity metadata. It does not fetch media URLs or access HTTP, PostgreSQL,
Kafka, or Redis. Content validation decodes the actual header and pixels with
Pillow, enforces JPEG/PNG MIME, byte, dimension, pixel, and color-mode limits,
and returns structured errors. Exact identity is SHA-256 over encoded bytes;
the optional average hash is explicitly a `PERCEPTUAL_SIMILARITY_HASH`, not a
learned embedding.

`image-preprocessing-v1` converts supported `L`, `RGB`, or `RGBA` input to RGB,
letterboxes to 224×224 with deterministic bilinear interpolation, emits CHW
float32 values in `[0, 1]`, and uses no pretrained normalization statistics.
Its benchmark metadata records encoded byte size, original/target dimensions,
and preprocessing time only.

The task is `MULTI_LABEL`. Five visible-content labels are future model targets;
`UNCERTAIN` is an annotation/adjudication state excluded from targets. Dataset
splits require event, incident, source-report, or capture-session metadata and
also bind exact/perceptual duplicate components. Without grouping metadata the
status is `GROUPED_SPLIT_UNAVAILABLE`.

The modest `scratch-cnn-v1` definition uses only Conv2d, BatchNorm, ReLU,
pooling, dropout, and a linear head with deterministic random initialization.
It is an architecture interface only. No validated image dataset or image
artifact exists, so `fit()` returns
`TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA` and valid inference returns
`OFFLINE` without labels or probabilities.

NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED. Any eventual image model
must be initialized locally and trained from scratch on approved,
project-controlled data.

## Anomaly detection framework

Phase 9 adds a local, isolated `AnomalyDetector` boundary for already-loaded
station observations. The typed contract intentionally includes only the
measurements found in this repository: 24-hour `rainfall_mm` and optional
`river_level_m`. It performs no PostgreSQL/PostGIS, Kafka, Redis, Open-Meteo,
HTTP, station-discovery, or neighbor lookup.

Validation reports chronological, duplicate/missing timestamp, numeric,
coordinate, missing-measurement, station, window-span, and irregular-sampling
issues without silently sorting or imputing input. `anomaly-features-v1`
produces level, prior-only change/rate, bounded rolling, time-context,
observation-density, and missingness features. Future values never contribute
to an earlier feature row.

`STATISTICAL_ANOMALY_BASELINE` uses a median-centered robust scale defined as
`max(1.4826*MAD, normal-equivalent configured quantile span,
measurement_floor)`; the default quartiles reduce to `IQR/1.349`. Its
`STATISTICAL_OUTLIER_SCORE` is an inspectable deviation statistic, not a
probability. Explicit baselines record their dataset hash, past time span,
feature/baseline versions, fitting parameters, station scope, and optional
hour-of-day strata. `DATA_QUALITY_ANOMALY` and
`WEATHER_BEHAVIOR_ANOMALY` remain separate output domains.

The learned-model interface reserves local, project-fitted methods such as
Isolation Forest, but no validated anomaly labels exist. Training therefore
returns `TRAINING_BLOCKED_NO_VALIDATED_ANOMALY_DATA`, writes no artifact, and
reports no production metric. Temporal split, station-overlap reporting,
annotation, validation-only threshold selection, frozen-test evaluation, and
artifact authorization are present for future approved data. The live
pipeline, station poller, database models, and production anomaly fields are
unchanged.
