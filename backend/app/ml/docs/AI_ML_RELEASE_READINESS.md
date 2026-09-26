# AI/ML release readiness

> Historical 24 Sep readiness snapshot. Phase 25 removed the live MiniLM path; Phase 25R
> verification remains blocked by test infrastructure. Use `docs/ML_VALIDATION_REPORT.md`
> for current status. Do not reuse historical release-gate conclusions as current results.

Assessment date: 2026-09-24

Overall status: `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY`

The fail-closed machine check is
`app.ml.release_gate.validate_ml_release()`. It reads committed evidence,
authorizes current local artifacts, blocks network sockets during repeated
inference, and emits typed component gates. It does not train, retune,
download, integrate, or promote anything.

## Component status matrix

| Component | Implementation status | Data status | Model status | Evaluation status | Calibration status | Production status |
|---|---|---|---|---|---|---|
| NLP | `AVAILABLE_DEVELOPMENT / HUMAN_ANNOTATION_WORKFLOW_READY` | `DEVELOPMENT_ONLY / SYNTHETIC; REAL_HUMAN_DATA_UNAVAILABLE` | `ACTIVE_V1 / V2_FROZEN_NOT_ACTIVE / V3_SYNTHETIC_FROZEN_NOT_ACTIVE` | `ACTIVE_V1_GATE_FAILED / V2_DEVELOPMENT_ACCEPTED_SYNTHETIC_ONLY / V3_DEVELOPMENT_GATE_PASSED_SYNTHETIC_ONLY` | `ACTIVE_V1_NOT_CALIBRATED / V2_AND_V3_CALIBRATED_ON_VALIDATION` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |
| Duplicate | `AVAILABLE_DEVELOPMENT` | `SYNTHETIC_DEVELOPMENT_ONLY / HUMAN_FIELD_DATA_UNAVAILABLE` | `DETERMINISTIC_DEFAULT + OPT_IN_V1_SYNTHETIC_CONFIG` | `SYNTHETIC_HOLDOUT_COMPLETE / FIELD_NOT_VALIDATED` | `VALIDATION_ONLY_SYNTHETIC / NOT_PRODUCTION_CALIBRATED` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |
| Event | `HEURISTIC_ONLY` | `SYNTHETIC_DEVELOPMENT_ONLY / HUMAN_FIELD_DATA_UNAVAILABLE` | `HEURISTIC_DEFAULT + OPT_IN_V1_SYNTHETIC_CONFIG` | `SYNTHETIC_HOLDOUT_COMPLETE / FIELD_NOT_VALIDATED` | `NOT_APPLICABLE` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |
| Credibility | `RULE_BASED_DEFAULT + ISOLATED_SYNTHETIC_MODEL` | `SYNTHETIC_DEVELOPMENT_ONLY / HUMAN_FIELD_DATA_UNAVAILABLE` | `RULE_BASED_DEFAULT + OPT_IN_V1_LOGISTIC_REGRESSION` | `SYNTHETIC_HOLDOUT_COMPLETE / FIELD_NOT_VALIDATED` | `VALIDATION_ONLY_SYNTHETIC / NOT_PRODUCTION_CALIBRATED` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |
| Image | `FRAMEWORK_ONLY` | `DATA_UNAVAILABLE` | `TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA` | `NOT_VALIDATED` | `CALIBRATION_UNAVAILABLE` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |
| Anomaly | `STATISTICAL_BASELINE` | `DATA_UNAVAILABLE` | `STATISTICAL_BASELINE` | `NOT_VALIDATED` | `NOT_CALIBRATED` | `DEVELOPMENT_ONLY / NOT_PRODUCTION_READY` |

`AVAILABLE` means the stated development or heuristic path can run for suitable
input; it is not a production claim. Event batch grouping is available, and a
single report creates only a provisional lifecycle `CANDIDATE`, never a
confirmed event. Image learned inference is `OFFLINE`. Anomaly scoring returns
`INSUFFICIENT_DATA` without adequate local history. All six components are
`NOT_VALIDATED`.

## Formal production gate

Every component must provide explicit passing evidence for all of the following
before the code permits `PRODUCTION_VALIDATED`:

| ID | Mandatory evidence |
|---|---|
| A | Valid dataset exists |
| B | Dataset provenance is documented |
| C | Independent validation split exists |
| D | Test split was untouched during tuning |
| E | Leakage checks pass |
| F | Training/inference is reproducible |
| G | Configured metric thresholds pass |
| H | Calibration passes wherever probability is claimed |
| I | Artifact provenance passes |
| J | New-subsystem policy scan passes |
| K | Deterministic inference passes |
| L | Limitations are documented |

Missing evidence is converted to a failed `MISSING` check. Component-specific
requirements are added to A–L; omitting one cannot promote a component.

## Dataset readiness

The machine-readable source is `dataset_readiness.json`. Its scope is
release-eligible labelled datasets. It records real values or explicit nulls:

- NLP: the 300-row synthetic development dataset is present. Phase 14 derives a
  deterministic 168/42 development train/validation split from the existing
  210 source-development rows and preserves the existing 90-row test. This is
  not an independent real-world release dataset, so the release-readiness JSON
  continues to report independence as unestablished. Formal annotator and
  incident-group counts are unknown and remain null. Exact normalized text
  leakage passed, but incident-level independence is not established.
  Phase 15 supplies a local human-annotation/adjudication and immutable
  registry-release workflow, but supplies no real reports or labels. Its honest
  quality report has zero annotations and `DATA_UNAVAILABLE` agreement; this
  changes infrastructure readiness only, not dataset or production readiness.
  Phase 17 additionally supplies a 100,000-row project-generated synthetic
  corpus with generator-level development splits and hash-bound scenario and
  leakage evidence. It remains `DEVELOPMENT_ONLY`, is not human-adjudicated,
  does not replace the historical final 90, and adds no field-validation or
  production-readiness evidence. Phase 18 trains and evaluates v3 against
  those exact bytes under the narrower `DEVELOPMENT_ONLY_SYNTHETIC` path; this
  records synthetic model evidence but does not satisfy or bypass the formal
  production data and approval gate.
- Duplicate: no authoritative human-adjudicated duplicate-pair dataset. Phase
  19 adds 100,000 registered project-generated synthetic pairs with grouped
  70,000/15,000/15,000 development splits and passed leakage evidence. The
  corpus is `DEVELOPMENT_ONLY`, has no human approvals, and cannot open the
  production gate. The three-record JSON remains `UNIT_TEST_ONLY`; the original
  frozen TF-IDF corpus remains unlabeled and unchanged.
- Event: no human-adjudicated field event ground truth. Phase 20 supplies a
  110,000-report project-authored synthetic structural benchmark and a
  one-shot protected test, but cannot open the production gate.
- Credibility: no representative human-adjudicated authenticity/misleading
  dataset. Phase 21 supplies a 100,800-report project-authored synthetic
  benchmark with grouped 70,560/15,120/15,120 splits, hidden-input isolation,
  and one-shot protected testing. Its production gate remains closed.
- Image: no validated labelled image dataset.
- Anomaly: no validated historical anomaly-label dataset.

No absent dataset is reported with invented zero counts, versions, or hashes.

## Current NLP development evaluation

The opt-in `nlp-classifier-v2-development` candidate was selected on the new
42-row validation split only. No candidate met the validation NOT_RELEVANT
recall or macro-F1 floors; the documented fallback selected the highest
macro-F1 configuration. Validation macro F1 was `0.7106209150326797` and
NOT_RELEVANT recall was `0.75`. Validation-only temperature scaling reduced
log loss from `1.218443297569186` to `0.7833805885861674`; its status is
`CALIBRATED_ON_VALIDATION`, not production calibrated.

After configuration freeze, one `FINAL_UNTOUCHED_TEST_EVALUATION` was run on
the existing 90 rows.

| Metric | Phase 14 final result |
|---|---:|
| Accuracy | 0.8 |
| Macro precision | 0.8181188264779596 |
| Macro recall | 0.8 |
| Macro F1 | 0.8024212658036187 |
| NOT_RELEVANT recall | 0.8333333333333334 |
| Flood-to-NOT_RELEVANT errors | 4 |

All unchanged development criteria pass, so the synthetic development result
is `DEVELOPMENT_ACCEPTED`. English final accuracy/macro F1 are
`0.8507462686567164 / 0.8514976091446679`; Hinglish values are
`0.6666666666666666 / 0.68`; the eight-row Hindi subset is
`INSUFFICIENT_DATA` under the Phase 14 ten-row minimum.

The existing `nlp_classifier_v1.metrics.json` remains read-only historical
reference. Its macro F1 `0.8104532163742689` and NOT_RELEVANT recall
`0.7777777777777778` were not used for model selection and are not directly
comparable because v1 trained on all 210 source-development rows. The default
NLP configuration remains v1; v2 was not activated in the engine or backend.

Production remains closed because development acceptance cannot bypass the
synthetic dataset classification, absent incident grouping and independent
field data, insufficient Hindi evidence, absent multilingual field validation,
or absent production calibration. Full methodology and hashes are recorded in
`NLP_DEVELOPMENT_VALIDATION.md`.

### Phase 18 NLP v3 synthetic development evaluation

The opt-in `nlp-classifier-v3-synthetic-development` candidate is bound to the
exact 100,000-row Phase 17 dataset hash. Eleven declared TF-IDF/logistic-
regression configurations used 80,000 training rows and validation-only
selection on 10,000 rows. `B_EQUAL_NONE_C1` was selected with validation macro
F1 `0.8925588427176322` and NOT_RELEVANT recall `0.915`. Validation-only
temperature calibration reduced log loss from `0.47745326394211063` to
`0.28349350710196364` and ECE from `0.2023368719637998` to
`0.025787741167492922`.

After freeze, one protected 10,000-row synthetic test evaluation produced:

| Metric | Phase 18 final result |
|---|---:|
| Accuracy | 0.9359 |
| Macro precision | 0.9368249631190861 |
| Macro recall | 0.9359 |
| Macro F1 | 0.9359267894270392 |
| NOT_RELEVANT recall | 0.936 |

English/Hindi/Hinglish macro F1 values are
`0.9288706618 / 0.9330825674 / 0.9467145850`. The entire test uses the
held-out `HIGH` noise regime. Its 2,000 hard negatives have macro F1
`0.8303691026` and NOT_RELEVANT recall `0.9975`; 45 held-out base-template
families and six realized structure families are reported. The development
gate passed, but the immutable status remains `DEVELOPMENT_ONLY_SYNTHETIC` and
production validation remains `NOT_VALIDATED`. v2 and v3 are
`NOT_DIRECTLY_COMPARABLE` because their datasets and evaluation designs differ.

The Phase 18 golden run preserves all ten original v1 snapshots and passes the
v3 schema, status, serialization, determinism, no-network, no-confirmed-event,
and cross-component contract assertions. Four v3 outputs intentionally differ
from model-dependent v1 snapshot fields and are recorded, not suppressed. The
v3 classifier remains opt-in and is not connected to the live backend. Full
evidence and hashes are in `NLP_V3_SYNTHETIC_DEVELOPMENT.md`.

### Phase 15 NLP data gate

The default annotation view is blind. Human judgments are append-only, exact
English/Hindi/Hinglish text is preserved, repeated reports can be reviewed by
multiple annotators, and every released class requires explicit adjudication.
Unresolved evidence remains `UNCERTAIN`; no agreement-derived consensus or
automatic/model/rule/keyword/random/LLM label can enter a released row.

Connected components over known event, incident, and source-family IDs are the
split units. Split assignments are explicit, incomplete grouping remains
`INSUFFICIENT_EVIDENCE`, and actual cross-split identity/group/exact/normalized/
near-text leakage fails release. Any future test rows must identify a separate
independent source dataset. The historical final 90 and v1/v2 artifact hashes
remain sealed and are checked before annotation/release operations.

Released versions begin as `CANDIDATE_DATA / DISCOVERED`. The Phase 13 NLP gate
now additionally requires `human_adjudicated=true` and rejects label-source
provenance containing model, matcher, heuristic, rule, detector, generated,
random, keyword, or LLM mechanisms. It still requires known provenance, valid
labels, complete groups, passed leakage, multilingual/label sufficiency,
explicit validation, and split-scoped human approval. A future approved corpus
would be input to separately governed human-data model development; it does
not authorize changes to frozen v2 or synthetic v3.

### Phase 16 NLP corpus enrollment gate

Phase 16 adds no corpus and does not open the NLP production gate. It provides
an explicit-local-file intake path with source/content manifests,
`RawNLPReport` text preservation, strict quality checks, supplied-only
grouping, and exact/normalized overlap checks against the sealed final 90. A
failed corpus remains `BLOCKED` and cannot publish `records.jsonl` or an
annotation queue.

A successful queue is blind and label-free by default, contains the entire
enrolled population exactly once, and records deterministic priority strategy,
seed, and parameters. Queue workflow states are append-only; `RELEASED`
requires adjudication evidence and a dataset version. Release manifests now
bind `dataset_hash`, grouping coverage, uncertainty count, leakage-report hash,
and source-manifest hash. The registry result remains
`CANDIDATE_DATA / DISCOVERED` until the existing Phase 13 validation and
explicit approval gates pass. No model, pretrained/open-weight asset,
embedding, API, network service, or training operation is involved.

## Component-specific blockers

### Duplicate

The unchanged default matcher still uses text `0.55` and combined `0.70` with
`PROVISIONAL / UNVALIDATED` status. Phase 19 adds a separate opt-in synthetic
development configuration selected on validation only: text `0.60`, combined
`0.65`, `5 km`, and `30 minutes`. Its one-shot synthetic test precision is
`0.9851116625`, recall `0.9998518519`, F1 `0.9924270274`, FPR
`0.0151111111`, and FNR `0.0001481481`.

These results do not remove the blocker: the dataset is generator-authored,
not independently human-adjudicated field evidence. Hindi same-weather/
different-event hard negatives dominate false duplicates. Promotion still
requires an approved representative human dataset, grouped independent splits,
field calibration, and a newly governed untouched test. Production validation
is `NOT_VALIDATED`.

### Event

`MODELING_STATUS = HEURISTIC_ONLY`. Phase 20 adds generator-authored synthetic
event truth and freezes a non-learned 5 km / 180 minute / 0.40 type-evidence
development configuration. The one-shot synthetic test pairwise F1 is
`0.9576013118`; false-merge and false-split rates are `0.0177799135` and
`0.0658135283`. Chain, elongated-event, duplicate-evidence, and single-report
lifecycle assertions pass. This is controlled structural evidence only:
human-adjudicated field event ground truth remains absent,
`EVENT_EVIDENCE_SCORE` is not a probability, and production validation remains
`NOT_VALIDATED`.

### Credibility

The live/default implementation remains `RULE_BASED_CREDIBILITY_BASELINE` and
its score remains `NOT_CALIBRATED`. Phase 21 adds a separate opt-in local
logistic-regression artifact trained from project-authored synthetic scenario
identity. The one-shot 15,120-row synthetic test has macro F1, misleading
precision, and misleading recall `1.0`, with FPR/FNR `0.0`; English, Hindi,
and Hinglish macro F1 are each `1.0`.

These perfect values recover deliberately separable generator regimes and are
not authenticity or truth performance. The selected authentic threshold is
`0.0000001`, emphasizing the absence of representative field calibration.
The modeled value is `MISLEADING_RISK_EVIDENCE`, not `TRUTH_PROBABILITY`.
Promotion still requires representative human adjudication, independent
grouped field splits, a newly governed untouched test, operational monitoring,
and production calibration. Production validation remains `NOT_VALIDATED`.

### Image

Status remains `FRAMEWORK_ONLY` and
`TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA`. There is no `.pt` artifact. Required
evidence is a validated grouped dataset, reproducible scratch-only training,
leakage results, frozen evaluation rules, multi-label metrics, calibration, and
authorized artifact provenance.

### Anomaly

Status remains `STATISTICAL_BASELINE`. The contract keeps
`DATA_QUALITY_ANOMALY` distinct from `WEATHER_BEHAVIOR_ANOMALY`. Promotion
requires labelled historical series, chronological validation, station-grouped
evaluation, a threshold frozen before test, and separate domain labels.

## Artifact and policy readiness

The v1 NLP JSON, opt-in v2 and v3 NLP JSON files, original duplicate feature
state, Phase 19 `duplicate_feature_state_v2.json`, and opt-in
`duplicate_matcher_v1.json` exist and pass exact manifest, SHA-256, component
identity, structure, and provenance checks. Phase 20 additionally registers
the exact `event_grouping_v1.json` deterministic configuration and binds it to
the 110,000-report synthetic event corpus, validation selection evidence, and
one-shot final receipt. Phase 21 registers `credibility_v1.json`, binds its
existing-feature logistic regression, train-only preprocessing,
validation-only calibration/thresholds, and one-shot final receipt to the exact
100,800-report synthetic credibility corpus. The NLP, duplicate, event, and
credibility development manifests
bind train, validation, final-test, frozen-configuration, artifact, and
evaluation evidence. Each final receipt records exactly one protected
evaluation. All remain development artifacts; NLP v3, duplicate v1, event
grouping v1, and credibility v1 are explicitly synthetic-only. No validated image or learned
anomaly artifact exists, so subsystem-wide artifact readiness is partial.

The new subsystem policy scan passes: no Sentence Transformer import,
pretrained/open-weight checkpoint loader, hosted AI API, runtime model
download, network client, or live backend dependency is present. Runtime
download and external inference configuration are disabled. The legacy live
MiniLM path is excluded from the compliant subsystem and remains visibly
classified `LEGACY_BACKEND_VIOLATION` pending the separately specified
migration.

## Integration readiness

The type boundary is ready for backend review; production integration is not.
`BACKEND_INTEGRATION_CONTRACT.md` fixes `ReportInput` as input and
`UnifiedMLResult` as output and records backend/ML ownership. The live backend
must not be changed until production gates, the complete backend suite, and the
legacy migration criteria pass.

## Test-environment status

- `ML_TESTS_PASSING`: 310 tests passed, 0 failed, and 0 skipped in the isolated
  ML suite on 2026-09-24. Three warnings report unrecognized asyncio pytest
  options because the corresponding plugin is absent.
- `FULL_BACKEND_TESTS_NOT_EXECUTED`: collection is blocked in the active
  environment because `pytest_asyncio` is missing.

The dependency manifest is unchanged. Passing ML tests must not be represented
as `FULL_BACKEND_SUITE_VERIFIED`.

## Known blockers and required promotion evidence

1. Independent, representative, provenance-complete labelled datasets for all
   applicable components.
2. Dedicated validation splits and untouched test splits with grouping and
   temporal controls appropriate to each component.
3. Passed leakage and independence audits over the actual release datasets.
4. Configured validation metrics and acceptance thresholds passing without test
   retuning.
5. Calibration evidence for every field represented as probability.
6. Authorized, reproducible artifacts or baselines with exact provenance.
7. Passed deterministic/no-network/policy checks at the release commit.
8. Complete ML and backend test suites in the approved environment.
9. Backend integration tests for every unavailable and missing-data state.
10. A separately approved, regression-tested, rollback-capable legacy MiniLM
    migration.

Until all required evidence passes, the only valid overall status is
`DEVELOPMENT_ONLY / NOT_PRODUCTION_READY`.
