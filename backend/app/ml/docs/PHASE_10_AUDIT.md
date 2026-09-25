# Phase 10 AI/ML subsystem audit

> Historical snapshot: this document records the Phase 10 state. Phase 12
> supersedes its single-report event limitation with a provisional
> `SingleReportEventCandidate`; production validation remains unchanged.

Audit date: 2026-09-22

Scope: all files under `backend/app/ml`, the committed ML artifacts and
datasets they reference, and the directly relevant entries in
`backend/requirements.txt`. This is a development audit, not a production
approval or field-performance claim.

## Dependency graph

```text
contracts
  └── config / artifact policy
        ├── data schemas, loaders, splits, leakage, annotation, adjudication
        ├── components
        │     ├── NLP ────────> frozen TF-IDF + classifier JSON
        │     ├── duplicate ──> frozen TF-IDF feature-state JSON
        │     ├── event ──────> deterministic grouping only
        │     ├── credibility -> deterministic rules only
        │     ├── image ──────> validation/preprocessing; no model artifact
        │     └── anomaly ────> statistical baseline; no learned artifact
        ├── training commands
        └── evaluation contracts

components -> inference engine -> orchestration entry point
all layers  -> isolated ML tests
```

An AST import-graph audit found no circular dependency in the new subsystem.
`data/candidate_pairs.py` intentionally reuses duplicate text normalization and
Haversine distance from component code; this is a low-risk layer inversion,
not a runtime backend dependency. Haversine implementations exist separately
in duplicate and event code. They have component-local numeric dependencies
and are left separate to avoid an audit-phase rewrite. Credibility and leakage
normalizers are intentionally distinct because their punctuation and exact-
match semantics differ.

The generic training placeholder and component-specific blocked training
commands are retained as explicit unavailable interfaces. The generic
`CredibilityPrediction.score` field is compatibility-only; the credibility
baseline populates only the semantically explicit `risk_score`.

## Inference flow and executability

The stable engine order is:

```text
ReportInput
  -> NLP
  -> duplicate
  -> event
  -> credibility
  -> image
  -> anomaly
  -> UnifiedMLResult
```

Credibility receives the NLP, duplicate, and event values produced earlier in
the same run. Current execution states are:

- NLP: locally executable development classifier when its authorized artifact
  is present; otherwise `OFFLINE`.
- Duplicate: locally executable against caller-supplied candidates; missing
  candidates are `NOT_APPLICABLE` and empty report text is
  `INSUFFICIENT_DATA`.
- Event at the Phase 10 checkpoint: the batch `detect()` heuristic was
  executable while single-report `predict()` was `NOT_IMPLEMENTED`. Phase 12
  now returns a one-report lifecycle `CANDIDATE`, never a confirmed event.
- Credibility: locally executable deterministic, uncalibrated risk baseline.
- Image: validation is executable. With valid bytes, learned inference is
  `OFFLINE`; with no bytes it is `NOT_APPLICABLE`.
- Anomaly: local statistical scoring is executable when adequate already-
  loaded history exists; otherwise it returns an explicit unavailable,
  insufficient, or error state.

Repeated inference over the same input and state is deterministic. Runtime
timing fields in standalone benchmark/batch result contracts are measurements,
not model outputs and are excluded from semantic equality claims.

## Artifact audit

Loadable artifacts:

| Artifact | SHA-256 | State | Self-contained |
|---|---|---|---|
| `nlp_classifier_v1.json` | `a12387cdfc753e92656f840ae7f22c35fac6d4d2179994b2b9c3ddc594789ba4` | `COMPLIANT`, development only | Yes: character/word vocabularies, IDF, classes, coefficients, intercepts, dimensions, and provenance |
| `duplicate_feature_state.json` | `6d8aad9701700686f42deefa72ed8074ede836a4e9f0d2457db2c054636c2cdc` | `COMPLIANT`, development only | Yes: character/word vocabularies and IDF plus corpus provenance |

The duplicate corpus hash is
`fdb433ee9d36b08b08ffc82cf7a4191f6fbdf647ad0087bedc756c876687b960`.
The NLP training dataset hash is
`3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d`.

Both runtime loaders reject URLs and UNC paths, require one matching intended-
component entry in the shared manifest, verify the exact file SHA-256, and
cross-check embedded versions and provenance. Fitted TF-IDF dimensions,
contiguous vocabulary indexes, finite positive IDF values, and classifier
matrix dimensions are validated before inference. No artifact was rebuilt in
Phase 10.

`nlp_classifier_v1.metrics.json` is evaluation evidence, not an inference
artifact. `event_classifier_v1.joblib` and
`event_classifier_v1.metrics.json` are legacy evidence and are deliberately
listed only under `legacy_artifacts`; they are not authorized by the new
loader. No image or learned-anomaly artifact exists.

The embedded NLP `artifact_version` is the JSON format version
(`nlp-classifier-artifact-v1`). The manifest `artifact_version` is the fitted
model version (`nlp-classifier-v1`). Runtime checks enforce both meanings. The
duplicate manifest uses `random_seed=0` as an explicit no-RNG marker for its
deterministically fitted feature state.

## Policy, network, and backend boundaries

New production ML source has no import of Sentence Transformers,
Transformers, Hugging Face, pretrained checkpoints, cloud AI SDKs, HTTP
clients, sockets, SQLAlchemy, PostgreSQL/PostGIS clients, Kafka, Redis,
FastAPI request state, authentication, frontend state, or live backend
services. AST policy tests and a socket-blocked end-to-end inference test guard
these boundaries. File-based entry points reject URL and UNC/network paths.

`backend/requirements.txt` still declares `sentence-transformers`, and the
legacy `backend/app/services/dedup.py` path loads
`sentence-transformers/all-MiniLM-L6-v2`. The live application warms and uses
that dedup path. `backend/app/ml/event_classifier.py` also references the same
legacy embedding path but is excluded from the new engine. This is a
`LEGACY_BACKEND_VIOLATION`, not a `NEW_ML_SUBSYSTEM_VIOLATION`.

Legacy removal is not safe in this phase. The live dedup caller and startup
warm-up must first be migrated or explicitly retired, configuration and
fallback behavior must be verified, relevant tests must pass without the
dependency, and only then may the dependency, legacy module, and artifacts be
removed in a separately authorized change.

## Event chain hardening

The original union-find accepted pairwise links transitively, so A–B and B–C
could merge A–B–C even when A–C exceeded a configured spatial or temporal
bound. `event-grouping-v2` retains the temporal sweep and union-find but adds a
complete-link check before every cluster union. Every cross-cluster member pair
must satisfy spatial radius, temporal window, and event-type compatibility.
Candidate-to-candidate merging uses conservative spatial-diameter and total-
span bounds because raw member coordinates are not present in that contract.

Regression fixtures cover both spatial and temporal A–B–C bridges and verify
that no three-report over-bound cluster is formed. This remains heuristic event
grouping, not a learned detector and not validated event truth.

## Missing data and terminology

Unavailable inference remains null/empty with an explicit status and reason;
it is not replaced by zero or false. A zero credibility risk or statistical
outlier score is emitted only when a real deterministic calculation yields
zero. Multiclass probability mappings are finite, bounded, normalized, and
validated separately from similarities, risk scores, event evidence scores,
and statistical outlier scores. Image multi-label probabilities are bounded
but are not required to sum to one.

The implementation and documentation distinguish classification probability,
duplicate similarity, credibility risk score, event heuristic confidence,
statistical outlier score, human annotation, and adjudication. None of the
heuristic components establishes ground truth, authenticity, falsity, or a
calibrated event/anomaly probability.

## Reproducibility and leakage

The NLP training path records an explicit seed, split hash, full dataset hash,
configuration, library versions, class distribution, and timestamp.
Cross-validation and logistic regression use the configured seed. The scratch
image architecture preserves caller RNG state and uses an explicit
initialization seed. Duplicate, event, credibility, preprocessing, and
statistical anomaly paths are deterministic.

Leakage controls cover:

- NLP exact normalized train/test text overlap and training-only feature fit /
  model selection;
- duplicate unordered and reversed pairs, event/incident groups, and exact
  text overlap;
- event canonical IDs, event IDs, report IDs, and definition hashes;
- credibility report families, canonical events, and exact/near-identical
  text;
- image event/incident/report/session groups plus exact and perceptual hashes;
- anomaly chronological periods, future-baseline exclusion, and optional
  station-disjoint evaluation.

No authoritative duplicate, event, credibility, image, or anomaly training
dataset is currently populated. Those controls are framework validation, not
proof that an absent dataset is leakage-free. The synthetic NLP dataset lacks
authoritative incident/event grouping metadata, so incident-level leakage
cannot be independently ruled out beyond its exact-text and fixed-split audit.

## Performance and remaining limitations

NLP loads and caches one authorized artifact per classifier instance.
Duplicate feature state loads once per matcher and the incoming report vector
is transformed once per prediction; candidate vectors are necessarily local
per candidate. Image validation performs a header verification followed by a
bounded full decode intentionally. Anomaly rolling windows are bounded.

Duplicate candidate comparison and candidate-pair generation are O(N) and
O(N²) respectively in their caller-supplied candidate/report counts. Event
pair discovery is O(N²) in a dense temporal window. Complete-link validation
can perform O(N³) cached Boolean member checks in an adversarial dense split,
although distance/type calculations are limited to one per member pair. This
correctness-first bound is retained pending representative batch data. No
production throughput claim is made, and no speculative optimization was
introduced.

Remaining limitations are the synthetic NLP corpus and failed development
acceptance gate, provisional duplicate thresholds, absent authoritative labels
for five components, unavailable learned image inference, heuristic anomaly
and event behavior, uncalibrated credibility risk, and the live legacy MiniLM
dependency outside the new subsystem.
