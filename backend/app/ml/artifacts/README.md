# INDRA ML artifact governance

All artifacts in this directory are local development artifacts. They are not
production approvals. Phase 3 adds a development-only frozen feature-state
JSON for deterministic duplicate-matcher inference. Phase 5 adds a
development-only NLP classifier artifact trained from the committed synthetic
reports dataset.

An artifact may be added only when its manifest entry includes:

- artifact name and version;
- SHA-256 hash of the artifact;
- training dataset hash;
- feature and preprocessing versions;
- training timestamp;
- random seed;
- framework/library versions;
- intended component;
- `COMPLIANT` policy status.

Runtime downloads are prohibited.  Artifacts must be produced by this project
and loaded only after manifest validation.  Arbitrary `joblib`, pickle,
checkpoint, or model files must not be loaded without a compliant manifest
entry.

The existing `event_classifier_v1.joblib` and metrics file are legacy evidence
only. They depend on the prohibited legacy feature extractor and are not
registered as loadable artifacts. Phase 5 uses no pretrained or open-weight
model, and the runtime NLP loader accepts JSON only.

`duplicate_feature_state.json` records the feature/preprocessing versions,
development corpus identifier and SHA-256, creation timestamp, and library
version. Its shared-manifest entry records the exact artifact hash, corpus
hash, versions, creation time, deterministic no-RNG marker (`random_seed=0`),
intended component, and `COMPLIANT` policy status. The loader verifies that
entry before parsing JSON. The file contains no pickle, joblib, checkpoint,
pretrained model, or runtime-download dependency.

`nlp_classifier_v1.json` contains the frozen character and word TF-IDF states
and logistic-regression coefficients as JSON. Its manifest entry records the
artifact hash, dataset hash, feature/preprocessing versions, seed, library
versions, intended component, and `COMPLIANT` policy status. Its metrics file
is evidence for development only and records `PRODUCTION_VALIDATION` as
`NOT_VALIDATED`. The embedded `artifact_version` identifies the JSON format;
the manifest `artifact_version` identifies the fitted model version. Runtime
loading requires both to match their configured meanings.

`nlp_classifier_v2.json` is the Phase 14 opt-in development candidate. It is
not the default model and is not connected to the live backend. In addition to
the fitted TF-IDF and logistic-regression state, it freezes explicit
character/word feature weights, class-weight mode, the deterministic
train/validation split, and validation-only temperature scaling. Its
development manifest, split definition, controlled-search results,
calibration report, validation error report, one-shot final metrics, and final
evaluation receipt are separate hash-bound JSON files with the same `v2`
prefix.

The final receipt is intentionally non-repeatable. It records exactly one
`FINAL_UNTOUCHED_TEST_EVALUATION`, no configuration change after freeze, and no
retraining after evaluation. The artifact status remains `DEVELOPMENT_ONLY`
even though it passed the synthetic development criteria. Its calibration
status is `CALIBRATED_ON_VALIDATION`; production calibration and validation
remain absent.

Phase 15 does not create or modify an artifact. It may display the already
frozen v2 prediction only in an explicitly enabled local annotation view marked
`MODEL SUGGESTION — NOT GROUND TRUTH`. The v2 bytes, configuration, thresholds,
calibration, and one-shot final-test receipt remain unchanged. Human-annotated
candidate datasets are reserved for separately governed future human-data
model work; the Phase 18 synthetic v3 candidate does not consume them.

`nlp_classifier_v3.json` is the Phase 18 opt-in synthetic development
candidate. It is trained only from the exact hash-bound Phase 17
`indra-nlp-project-synthetic-v1` dataset and has the immutable status
`DEVELOPMENT_ONLY_SYNTHETIC`. Its JSON freezes the fitted TF-IDF states,
33,917-feature logistic-regression parameters, class order, explicit feature
weights, seed, validation-derived temperature, split hashes, and complete
synthetic provenance. It is not the default classifier and is not connected to
the live backend.

The companion `nlp_classifier_v3.development_manifest.json`, `.search.json`,
`.calibration.json`, `.golden.json`, `.metrics.json`, `.error_report.json`, and
`.final_test_receipt.json` files record the bounded search, validation-only
selection/calibration, golden contract regression, one-shot protected test,
and categorized errors. The shared manifest authorizes only the exact artifact
SHA-256. The receipt records one completed evaluation and the evaluator refuses
a rerun before loading test data. These artifacts authorize reproducible local
development inference only; they do not authorize production use or alter the
Phase 13 production training gate.

Phase 8 creates no image model artifact. Any future `.pt` file must be trained
from scratch on approved project-controlled data and must pass both the shared
manifest and image-specific provenance gate before tensor loading. Unknown,
hash-mismatched, externally sourced, pretrained, or provenance-incomplete image
weights are rejected. NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED.

Phase 9 creates no learned anomaly artifact. Statistical baselines are explicit
in-memory data contracts, not model files. Any future project-trained Isolation
Forest or custom artifact must record and match its model version, dataset
hash, feature version, baseline version, library version, random seed, artifact
hash, training window, station scope, project-controlled source, and compliant
policy status. The anomaly authorization gate validates provenance only; Phase
9 intentionally exposes no artifact deserializer. External, pretrained,
open-weight, remote, unknown, or hash-mismatched anomaly artifacts are rejected.

Phase 19 adds two separate, opt-in duplicate development artifacts without
replacing `duplicate_feature_state.json` or the default matcher configuration.
`duplicate_feature_state_v2.json` is fitted only from the 140,000 report texts
in the registered synthetic training split. `duplicate_matcher_v1.json` freezes
the state binding, fixed signal weights, validation-selected text/combined
thresholds and candidate gates, decision logic, and the optional versioned
validation-only Platt calibration layer. Both entries are authorized under the
`duplicate_matcher` component by exact filename and SHA-256.

The companion `duplicate_v1.development_manifest.json`, threshold-search,
ablation, calibration, stability, performance, golden, validation-metric,
validation-error, final-metric, and final-error JSON files preserve the Phase
19 evidence chain. `duplicate_v1_final_test_receipt.json` records exactly one
protected synthetic holdout invocation and prohibits rerun. The artifact is
`DEVELOPMENT_ONLY_SYNTHETIC`, remains disconnected from the live backend, and
does not authorize production use. Its score remains evidence rather than a
probability; selected calibration is explicitly `NOT_VALIDATED` for production.

Phase 20 adds `event_grouping_v1.json`, a deterministic configuration artifact,
not a learned model. It binds `event-grouping-v2` to the exact project-authored
synthetic event dataset and freezes validation-selected 5 km, 180 minute, and
0.40 type-evidence thresholds, minimum two independent reports, identical-type
compatibility, complete-link all-member constraints, and conjunctive merge
logic. Its internal artifact hash covers canonical JSON excluding only the
`artifact_hash` field; the shared manifest separately authorizes the complete
file SHA-256 under `event_detector`.

The companion development manifest, threshold search, ablation, validation
metrics/errors, performance record, golden assertions, final metrics/errors,
and `event_grouping_v1_final_test_receipt.json` preserve the evidence chain.
The receipt records exactly one held-out synthetic test invocation and refuses
rerun. No learned event weights exist, and the artifact remains
`DEVELOPMENT_ONLY_SYNTHETIC / NOT_VALIDATED` and disconnected from the live
backend.

Phase 21 adds `credibility_v1.json`, an opt-in interpretable logistic-regression
development artifact trained only from the registered project-authored
synthetic credibility benchmark. It stores the existing credibility feature
order, train-only imputation/scaling, two resolved fitted classes,
validation-only temperature, and validation-selected AUTHENTIC/UNCERTAIN/
MISLEADING thresholds as JSON. `UNCERTAIN` is an abstention state, not a fitted
class. Its probability represents `MISLEADING_RISK_EVIDENCE`, never truth.

The companion search, calibration, ablation, baseline, validation metrics and
errors, performance, golden, final metrics and errors, development manifest,
and `credibility_v1_final_test_receipt.json` preserve the Phase 21 evidence
chain. The receipt records exactly one protected synthetic test invocation and
prohibits rerun. The artifact remains `DEVELOPMENT_ONLY_SYNTHETIC /
NOT_VALIDATED`, is disconnected from the live backend, and does not alter the
existing rule baseline or its uncalibrated score.
