# Inference contract

> Historical phase-scoped contract notes. For the current typed contract and exact status values,
> see `docs/ML_INFERENCE_CONTRACT.md`; earlier "no trained image model" text is superseded.

## Input

`ReportInput` contains an identifier, text, occurrence time, coordinates,
source type and metadata, already-loaded duplicate candidates, already-loaded
station observations, and optional image bytes.

The ML layer must never fetch a URL, query a database, consume Kafka, access
authentication, access frontend state, or download a model.

`InferenceEngine.analyze()` executes components in the stable order NLP,
duplicate, event, credibility, image, anomaly. Credibility receives the typed
NLP, duplicate, and event results produced earlier in that run. The
single-report event interface emits a provisional candidate for upstream
composition; batch observations remain required for multi-report grouping.

## Component outputs

Every prediction has:

- explicit `PredictionStatus`;
- optional model, feature, and preprocessing versions;
- evidence and reason codes;
- warnings;
- result fields that remain `null` when no result exists.

`0.0` must not be used to represent missing inference.

## NLP text prediction

The Phase 5 `NLPClassifier` accepts either a string or an already-loaded
`ReportInput`. With non-empty text and a valid, manifest-authorized local JSON artifact it returns
`AVAILABLE`, one of the five trained labels, a probability for every class,
confidence, evidence, and the model/feature/preprocessing versions. Its
reason code is `DEVELOPMENT_MODEL_INFERENCE`, and a warning explicitly states
that the synthetic-data model is not production validated.

Empty or punctuation-only text returns `NOT_APPLICABLE` with `EMPTY_TEXT` and
no fabricated probability distribution. A missing, invalid, remote, or
version-incompatible artifact returns `OFFLINE` with
`MODEL_ARTIFACT_UNAVAILABLE`; inference never silently falls back to a
different model.

The NLP artifact is JSON-only and uses the frozen training-time character and
word TF-IDF spaces. No feature fitting occurs during inference.

## Unified result

`UnifiedMLResult` contains the six component results plus schema version,
version maps, warnings, and errors.  The backend may persist or fuse this
result, but persistence is outside this package.

## Duplicate prediction evidence

`DuplicatePrediction` exposes the best candidate, decision, combined score,
text score, character score, word score, edit score, geographic score,
temporal score, physical distance, elapsed time, both thresholds, candidate
count, and comparisons performed.

When no candidates are supplied, the status is `NOT_APPLICABLE`.  When
candidates exist but all fail the geographic or temporal gates, the result is
an explicit available negative decision with `NO_CANDIDATE_WITHIN_GATES`.
When candidates exist but report text is empty after normalization, status is
`INSUFFICIENT_DATA` with `EMPTY_TEXT`; no negative duplicate decision or zero
similarity is fabricated.

Duplicate inference uses a frozen, local JSON TF-IDF feature state and never
refits from the candidate batch. The state is development-only and carries
explicit corpus provenance. Duplicate thresholds are marked
`PROVISIONAL / UNVALIDATED` until an authoritative human-labeled duplicate-pair
dataset exists; no live pipeline integration is permitted in this phase.

## Event detection

Event detection consumes a batch of already-loaded `EventObservation` values,
not a database query or a report-level NLP classification. Each observation
contains its `TextPrediction`, coordinates, occurrence time, source type,
caller-supplied `DuplicatePrediction`, and optional weather, image,
credibility, and anomaly evidence.

`EventDetectionResult` returns typed `EventCandidate` values with event type,
member reports, centroid, time range, source diversity, feature snapshots,
evidence, lifecycle status, and algorithm/feature versions. The grouping
result is deterministic and uses configurable spatial, temporal, and type
compatibility rules. `event-grouping-v2` also requires complete-link cluster
bounds, so transitive bridge links cannot make a cluster exceed the configured
maximum member-to-member distance or temporal span.
`EventDetector.predict(ReportInput)` returns `HEURISTIC_ONLY` and a
`SingleReportEventCandidate` containing exactly one report ID, event-type
evidence from the supplied NLP result when available, candidate coordinates,
candidate timestamp, provisional `EVENT_EVIDENCE_SCORE`, lifecycle state
`CANDIDATE`, and feature/algorithm versions. Generic `confidence` remains null.
Reason codes include `SINGLE_REPORT_EVENT_CANDIDATE` and
`NOT_CONFIRMED_EVENT`. This object is an event hypothesis only; its schema
cannot carry `CONFIRMED`.

The candidate score is `PROVISIONAL_EVENT_CONFIDENCE`, not a calibrated
probability. Event lifecycle confirmation requires explicit human confirmation;
heuristic scoring alone cannot produce `CONFIRMED`.

## Golden regression contract

The Phase 12 golden runner uses only versioned, hash-verified synthetic fixture
inputs. It verifies the exact `UnifiedMLResult` field order, six component
statuses, model/feature maps, supplied preprocessing versions, warning/error
aggregation, null semantics, and JSON round-trip equality. Every scenario is
executed twice; component output, status, reason-code order, and evidence order
must match exactly. Batch-event wall-time observations are excluded from
semantic comparison, but substantive numeric output is not hidden behind broad
tolerances.

The golden contract enforces the following separations: duplicate is not fake;
anomaly is not false report; event grouping is not NLP classification; risk
score is not probability; heuristic evidence is not calibrated probability;
missing inference is not zero; image evidence is not authenticity proof; and a
single report is not a confirmed event.

The golden performance record measures a warmed local engine at 1, 10, and 100
synthetic reports and records artifact load time separately. Those values are
engineering-regression observations, not a production SLO or throughput claim.

## Credibility-risk prediction

`CredibilityRiskInput` contains an already-loaded `ReportInput` plus optional
`DuplicatePrediction`, `EventPrediction`, `TextPrediction`, `ImagePrediction`,
submission time, geographic checks, source-history counts, and duplicate
cluster metadata. The detector never obtains these values itself.

`CredibilityPrediction` returns status, `risk_score`, `risk_level`, structured
evidence, reason codes, model/feature/preprocessing versions, and explicit
calibration status. `risk_score` is a deterministic review score, not a
probability. `INSUFFICIENT_DATA` returns no score rather than encoding missing
inference as zero.

The legacy generic `score` compatibility field is not populated by the
credibility baseline; callers must use the explicitly named `risk_score`.

The baseline is named `RULE_BASED_CREDIBILITY_BASELINE`. Duplicate evidence,
event inconsistency, or unusual metadata may raise review signals, but none is
phrased as proof that a report is fake. Media fields are reserved and are not
used to claim manipulation in Phase 7.

`LEGACY_CREDIBILITY_PRIOR` remains separate from this framework. THIS SYSTEM
DOES NOT ESTABLISH TRUTH BY ITSELF.

## Image prediction

`ImageAnalyzer` receives either a typed `ImageInput` or legacy `ReportInput`
containing already-loaded bytes and caller-supplied media metadata. It never
resolves a URL or accesses storage, a database, a queue, or the network.

`ImagePrediction` contains status, image ID, multi-label outputs,
probabilities, confidence, model/feature/preprocessing versions, evidence,
reason codes, warnings, and calibration status. Phase 8 has no trained model:

- no supplied image returns `NOT_APPLICABLE` with `IMAGE_NOT_SUPPLIED`;
- invalid content returns `ERROR` and structured validation reason codes;
- valid content returns `OFFLINE` with `TRAINING_UNAVAILABLE`, byte/hash and
  decoded-format evidence, empty labels/probabilities, no confidence, and
  `CALIBRATION_UNAVAILABLE`.

No fallback rule maps pixels to labels. An image prediction is visual evidence
only and must not be interpreted as authenticity verification. Image presence
does not mean authentic or fake, and a future visual class must not be treated
as proof that the associated report is true.

NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED. Any future `.pt` state dict
must first pass shared-manifest and image-specific provenance checks for model,
architecture, dataset, preprocessing, training configuration, seed, framework,
hash, project-controlled source, and policy status.

## Anomaly prediction

`AnomalyDetector` accepts an `AnomalyInputWindow` of ordered, already-loaded
`WeatherObservation` records for one station. A compatibility adapter can use
already-loaded `ReportInput.station_observations`; the component never queries
storage, discovers neighboring stations, calls Open-Meteo/HTTP, consumes a
queue, or fills missing values.

`AnomalyPrediction` reports status, station and observation IDs, anomaly type
and point/window scope, separate data-quality/weather-behavior domain, score,
score type, threshold, model/feature/baseline versions, evidence, reason codes,
calibration status, and optional missing-data state. No observations yields
`NOT_APPLICABLE`; invalid structure yields an explicit error or insufficient
state; inadequate past coverage yields `INSUFFICIENT_DATA`; statistical output
yields `HEURISTIC_ONLY`.

The only Phase 9 numeric score is `STATISTICAL_OUTLIER_SCORE`. It has no
`[0, 1]` probability semantics and carries `NOT_CALIBRATED`. A normal decision
may have score zero; unavailable inference has a null score. A single missing
measurement is `MISSING_INPUT`, while a configured repeated gap may produce a
`MISSINGNESS_PATTERN` data-quality window. Plausible extreme rainfall can be a
weather-behavior outlier but is never automatically called bad data.

An explicit fitted baseline must match the feature version and station scope,
and its end timestamp must precede the scored target. Baselines record dataset
hash and fitting provenance. No learned anomaly model is available, no artifact
is loaded, and no result is written into a production database field.
