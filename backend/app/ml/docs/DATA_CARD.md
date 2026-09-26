# Dataset card

The current committed labeled dataset is
`data/labelled/reports_v1.csv`.

- 300 synthetic short reports.
- Five event labels with 60 rows each.
- 210 training rows and 90 test rows.
- No independent validation set.
- 16 synthetic spam rows, all within `NOT_RELEVANT`.
- No image, video, duplicate-pair, event-cluster, or anomaly labels.
- No real citizen-report holdout is committed.

It is suitable only for scaffold validation and historical classifier
reproduction.  It is not sufficient evidence for deployment.

## Phase 13 registry and approval status

The corpus is registered as `indra-nlp-reports-v1-synthetic`, version
`reports-v1-development-synthetic`, in
`backend/app/ml/data/registry/datasets.json`. Its exact file SHA-256 is
`3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d`.
A hash-bound machine validation report is stored under
`backend/app/ml/data/registry/reports/`.

Structural validation is `VALID`: all 300 rows parse, the registered content
hash matches, the five labels each contain 60 rows, and no exact/near text or
record-identity overlap was found across the supplied train/test assignments.
This structural status is not an approval.

The leakage result is `INSUFFICIENT_EVIDENCE` because no grouping field exists.
There is also no independent validation split. The registry classification
remains `DEVELOPMENT_ONLY`, and the approval list is empty. Consequently the
dataset is ineligible for training, validation, or final-test approval through
the Phase 13 gate. It has not been reclassified as production data.

A future real NLP dataset must be locally registered with explicit provenance,
usage terms, label source, grouping, and train/validation/test assignments. It
must pass schema, multilingual, label sufficiency, exact/near text, group, and
cross-split leakage checks and then receive separate split-scoped approvals.
The complete workflow is documented in `DATASET_REGISTRY.md`,
`DATASET_APPROVAL.md`, `DATASET_PROVENANCE.md`, and `DATASET_LEAKAGE.md`.

Phase 1 validation uses exact normalized text checks only.  No embedding model
is used for contamination detection.

## NLP classifier use

Phase 5 uses the same dataset for a development-only five-class NLP classifier:
`URBAN_FLOOD`, `RIVER_BREACH`, `CLOUDBURST`, `CYCLONE_INUNDATION`, and
`NOT_RELEVANT`. The committed split is used as provided: 210 training rows and
90 test rows. Character and word TF-IDF vocabularies and IDF values are fitted
on training rows only. Cross-validation and regularization selection also use
training rows only; the test rows are evaluated once after the model is frozen.

The dataset hash, split hash, preprocessing version, and feature version are
recorded in the JSON artifact, metrics report, and artifact manifest. The
dataset has English, Hindi, and Hinglish examples, but the Hindi and Hinglish
test subgroups are small and are reported as development evidence rather than
deployment assurance. No real citizen-report holdout is included.

### Phase 14 derived development split

Phase 14 does not change `reports_v1.csv`. It deterministically partitions the
existing 210 source-development rows into 168 development-train and 42
development-validation rows using event-label stratification and seed 42. The
existing 90 test rows remain untouched and in their original order. Exact
record IDs, class/language distributions, and SHA-256 hashes are frozen in
`backend/app/ml/artifacts/nlp_classifier_v2.split.json`.

This derived validation split is legitimate for the controlled synthetic
development experiment, but it does not make the dataset release eligible. No
incident/grouping field exists, no independent field collection exists, and
the corpus remains `DEVELOPMENT_ONLY`. Validation has only four Hindi rows and
11 Hinglish rows; the final test has eight Hindi and 15 Hinglish rows. Phase 14
therefore reports Hindi as `INSUFFICIENT_DATA` under its ten-row subgroup
minimum and does not infer field performance.

The final test was accessed once only after configuration and calibration were
frozen. The receipt records one invocation and forbids rerun. Passing the
synthetic development criteria does not alter registry classification,
approvals, production validation, or the Phase 13 general training gate.

### Phase 15 human-annotation readiness

Phase 15 adds a local, append-only human workflow for the unchanged five-class
taxonomy. Annotation schema `nlp-human-annotation-v1` preserves exact English,
Hindi, and Hinglish text; records human state/label, language, reason,
confidence, annotator, source metadata, and event/incident/family identifiers;
and makes blind review the default. Optional frozen-v2 output is stored only as
`MODEL SUGGESTION — NOT GROUND TRUTH` provenance and cannot populate a label.

Every released labeled row requires a separate explicit human adjudication.
Agreement is reported but is not inferred as consensus. Unresolved reports
remain `UNCERTAIN` and are excluded with an auditable manifest entry. Connected
grouping uses event, incident, and source-family identifiers; explicit split
assignment is required, and a future test row must come from a separately
named independent source dataset. Exact, normalized, near-text, identity, and
group leakage checks run before registry validation. The historical final 90
is hash-sealed and barred from all new sources and releases.

No real reports or human labels are committed in Phase 15. The committed
`data/labelled/nlp/annotation_quality_report.json` truthfully records zero
reports/annotations and `agreement_status=DATA_UNAVAILABLE`; it is not evidence
of class or language balance. Future immutable versions are registered as
`CANDIDATE_DATA` through the Phase 13 registry and require separate validation
and split-scoped approval. They are candidates for separately governed future
human-data model work, not inputs to the Phase 18 synthetic v3 experiment. See
`NLP_ANNOTATION_GUIDE.md` and `NLP_DATASET_WORKFLOW.md`.

### Phase 16 local-corpus readiness

Phase 16 adds no data and makes no performance claim. It adds a local-only,
hash-bound enrollment gate for explicitly supplied CSV, JSON, JSONL, and—when
the dependency is already installed—Parquet report corpora. Valid records use
`RawNLPReport`; exact original text and its SHA-256 remain separate from a
normalized validation/search representation. Missing language remains
`UNKNOWN`, and grouping uses only supplied event, incident, or source-family
identifiers.

Enrollment is fail-closed for missing/empty fields, duplicate identity or
text, invalid timestamps/coordinates/UTF-8/language, inconsistent grouping,
and exact or normalized overlap with the sealed historical final 90. Failed
enrollments retain source and validation evidence but publish no annotation
corpus. Successful queues contain the complete observed population and no
event labels; deterministic sampling changes priority only.

An enrolled corpus is not annotated data. Human annotations are not an
adjudicated dataset. An adjudicated immutable release is initially only
`CANDIDATE_DATA`. The Phase 13 registry still requires known provenance,
human-label/adjudication evidence, compatible schemas, complete grouping,
leakage `PASS`, zero final-test overlap, recorded dataset/source-manifest
hashes, adequate split evidence, and explicit approval before it can become
`APPROVED_TRAINING`. No real corpus is committed by Phase 16.

### Phase 17 project-generated synthetic expansion

Phase 17 adds a separate 100,000-row English/Hindi/Hinglish corpus generated
from versioned structured scenarios. It is registered as
`indra-nlp-project-synthetic-v1` / `synthetic-nlp-100k-v1`, with provenance
`PROJECT_AUTHORED`, label source `PROJECT_GENERATED_SYNTHETIC`, and
classification `DEVELOPMENT_ONLY`. It has generator-level train, validation,
and synthetic test partitions plus hash-bound scenario and leakage evidence.

This expansion does not change the status of `reports_v1.csv`, does not modify
NLP v2, and does not provide real-world or production-validation evidence. See
`SYNTHETIC_NLP_DATASET.md` for exact counts, hashes, and reproduction commands.

### Phase 18 synthetic v3 use

Phase 18 consumes only the exact registered Phase 17 dataset bytes with
SHA-256
`6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76`,
generator version `synthetic-nlp-generator-v1`, and seed `170017`. Training is
blocked if any registry, dataset, manifest, scenario-metadata, split,
validation, leakage, generator-version, or seed binding differs. The source
classification remains `DEVELOPMENT_ONLY`, and the normal production training
gate remains closed.

The generator-defined partitions are used without reassignment: 80,000 train,
10,000 validation, and 10,000 protected synthetic-test rows. The frozen split
hashes are:

- train: `9ebe62d97a1a14d2ad114cd5a8ccb814442cddac739d55c8633d4303f231073e`;
- validation: `4405d3083c15b13fff47ebb773e0321f0bebdca6d22f18127af6427d0f4150a6`;
- test: `cea06fa366c4de7387c1ed89e92f795071cdc8aff8c98a74a7ce492c9ab6033b`.

Base-template family, parameter-combination, and scenario-family leakage are
all zero across splits. Training contains 26,667 `NONE`, 26,667 `LOW`, and
26,666 `MEDIUM` noise rows; validation contains 3,333, 3,334, and 3,333; the
test deliberately contains 10,000 `HIGH` noise rows and no rows in the other
noise strata. Hard negatives number 16,000/2,000/2,000 across train,
validation, and test. English, Hindi, and Hinglish metrics are reported
separately, as are 45 held-out test base-template families and six realized
structure families.

The test descriptor—not its text, labels, or features—was available during
selection to bind its row IDs, count, order, and hash. Its rows were loaded
only after the selected configuration, validation calibration, artifact, and
golden checks were frozen. A receipt records one evaluation invocation and
prohibits rerun. This procedural isolation does not make synthetic data
independent field evidence. No Phase 18 row is human-authored or
human-adjudicated, and no production, geographic, demographic, temporal-drift,
or operational representativeness claim is supported.

## Duplicate-pair dataset specification

Future duplicate labels use `DuplicatePairRecord` in
`backend/app/ml/data/duplicate_pairs.py`. Each record will carry:

- pair identifier;
- report A and report B identifiers;
- one of `DUPLICATE`, `NOT_DUPLICATE`, or `UNCERTAIN`;
- annotator ID, annotation timestamp, annotation reason, and label provenance;
- optional `event_id_when_known` or `incident_id_when_known` grouping keys;
- optional text, temporal, geographic, and source relationships;
- optional time delta, physical distance, and coordinates.

No duplicate-pair production dataset is populated. Future production labels
must be produced by independent human review with documented adjudication,
preserving hard negatives such as same-topic reports from different incidents
and identical text submitted at incompatible times or locations.

Phase 19 adds the registered
`indra-duplicate-project-synthetic-v1 / synthetic-duplicate-100k-v1`
development corpus. Its exact SHA-256 is
`ad664bf69755a141f44c82615e7653f28ae5abadc028cb50d6566ee2f13e7231`.
It contains 100,000 pairs split by generator construction into 70,000 train,
15,000 validation, and 15,000 protected test: 45,000 `DUPLICATE`, 45,000
`NOT_DUPLICATE`, and 10,000 `UNCERTAIN`. Scenario identity supplies labels;
no matcher, rule threshold, model, embedding, or LLM labels the rows.

English, Hindi, and Hinglish; four event types; four source types; six
duplicate scenarios; seven hard-negative scenarios; and two uncertain boundary
scenarios are represented. Event and source factors are balanced inside every
scenario. Split-specific reports, incidents, scenario families, exact text,
and parameter combinations prevent correlated leakage. Both the custom quality
report and registry validation pass. The registry still blocks all production
uses because the source is `PROJECT_AUTHORED / SYNTHETIC / DEVELOPMENT_ONLY`,
is not human-adjudicated, and has no explicit approvals.

The older `UNIT_TEST_ONLY` fixture and original unlabeled development feature
corpus remain non-ground-truth. The Phase 19 synthetic final metrics are useful
only for controlled development and regression. They are not field-performance
metrics, and `PRODUCTION_VALIDATION` remains `NOT_VALIDATED`. Detailed
construction, hashes, leakage evidence, and limitations are in
`DUPLICATE_V1_SYNTHETIC_VALIDATION.md`.

## Event-level data status

The current `reports_v1.csv` contains report-level labels only. It contains no
authoritative event IDs, event clusters, canonical event assignments, or
human-reviewed event-match labels. The Phase 6 event fixtures are deterministic
unit fixtures only and are not evaluation data.

Future event annotations must keep the same underlying event, duplicate
reports, and near-identical event definitions within one grouped split. The
event annotation schema reports cross-split canonical-event, event-ID,
report-ID, and definition-hash leakage before evaluation.

Phase 20 adds the separately registered
`indra-event-project-synthetic-v1:synthetic-event-110k-v1` benchmark. It is
project-authored, synthetic, and development-only: 110,000 reports, 17,000
generator-defined canonical events, and 55,000 direct-identity pair labels.
Canonical-event splitting yields 77,000/16,500/16,500 reports and
11,900/2,550/2,550 events across train/validation/test, with zero canonical,
incident, or report leakage. Hidden truth and detector-visible evidence are
stored separately. Its composite hash is
`127a506f8deba172140dd33b71a14b84b629ce325c959ba8b9d4c04635f48f0f`.

This benchmark supports deterministic event-grouping development and
regression only. Generator identity is not human adjudication, controlled text
predictions are not frozen NLP inference, and project-authored duplicate links
are not duplicate-matcher output. Phase 20 therefore does not alter the human
event-data status: representative field event labels remain unavailable and
production validation remains `NOT_VALIDATED`. See
`EVENT_GROUPING_V1_SYNTHETIC_VALIDATION.md`.

## Fake / misleading report data status

No representative human-adjudicated authenticity or misleading-report dataset
exists. The 16 existing `spam` rows all belong to `NOT_RELEVANT`, so that field
is confounded and must not be used as fake-report ground truth. No labels are
inferred from the legacy credibility prior or from Phase 7 rule scores.

Phase 21 adds a 100,800-report project-authored synthetic benchmark with the
taxonomy `AUTHENTIC`, `MISLEADING`, and `UNCERTAIN`. Scenario identity supplies
ground truth before inference. The grouped 70,560/15,120/15,120 splits have
zero report-family, canonical-event, template, parameter-combination, and
exact normalized text leakage. Hidden truth and detector-visible input are
physically separate. The composite hash is
`1ceab01ae23d7c99eec3f98a0bbad479ae5b66b63f56298a5d713d5218140a87`.

This dataset is `PROJECT_AUTHORED / SYNTHETIC / DEVELOPMENT_ONLY`. It supports
credibility-risk regression and local model development only. It is not human
adjudication, factual-truth evidence, field authenticity performance, or
production validation. See `CREDIBILITY_V1_SYNTHETIC_VALIDATION.md`.

## Image data status

No validated or project-approved labeled image dataset is present. Frontend
assets, documentation images, and unit-test-generated PNG/JPEG bytes are not
training data and must never be treated as ground truth. Consequently image
training, model evaluation, subgroup claims, and production metrics are
unavailable.

NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED. Any eventual image model
will be trained from scratch only on approved project-controlled data.

The annotation schema is `image-annotations-v1` and the initial task is
`MULTI_LABEL`. The visible-content taxonomy is `FLOODED_SCENE`,
`HEAVY_RAIN_VISUAL`, `STANDING_WATER`, `STORM_DAMAGE`, `NORMAL_SCENE`, and the
exclusive unresolved state `UNCERTAIN`. The definitions and limitations are in
`IMAGE_ANNOTATION_GUIDE.md`.

Future data must contain decoded format/dimensions, exact byte hash, optional
clearly identified perceptual hash, annotator provenance, and event/incident/
report/session grouping metadata. Original annotations remain append-only;
disagreement remains `UNCERTAIN` until explicit adjudication. Exact-set
agreement is reported only for genuinely repeated annotations.

Splitting is unavailable when grouping metadata is absent. Exact byte matches,
coarse average-hash near-duplicates, source reports, capture sessions,
incidents, and events are checked for cross-split leakage. Average hash does not
detect semantic reuse reliably and is not a pretrained feature extractor.

## Anomaly data status

No validated anomaly ground-truth dataset is committed. The station schema
currently provides 24-hour rainfall accumulation and an optional river-level
field; repository evidence does not support temperature, humidity, pressure,
wind, or other invented measurements. Existing station rows, synthetic series
in unit tests, statistical outlier scores, legacy production anomaly fields,
and event labels are not anomaly ground truth.

The future annotation schema is `anomaly-annotations-v1` with `ANOMALY`,
`NORMAL`, and `UNCERTAIN`. Resolved anomalies require a supported point/window
type and one of the distinct `DATA_QUALITY_ANOMALY` or
`WEATHER_BEHAVIOR_ANOMALY` domains. Original judgments are append-only;
agreement is calculated only on independently repeated targets, and unresolved
disagreement remains uncertain.

Evaluation data must retain chronological train/validation/test order, keep
equal timestamps together, report station composition and overlap, and support
station-disjoint splits when evaluating generalization to unseen stations.
Baseline fitting uses only the earlier period, threshold selection uses
validation only, and the frozen threshold is applied to the final test period.
Until reviewed labels exist, anomaly metrics and calibration are
`DATA_UNAVAILABLE` / `NOT_AVAILABLE`.

## Phase 12 golden engineering-regression data

`backend/app/ml/golden/fixtures/golden_scenarios_v1.json` contains ten wholly
synthetic scenarios created for deterministic software regression. The suite
and every scenario are explicitly marked `TEST_FIXTURE_ONLY` and `SYNTHETIC`;
each scenario is also marked `NOT_PRODUCTION_DATA`. Every scenario carries a
scenario/schema version, timezone-aware creation timestamp, and a SHA-256 over
its canonical payload.

The cases cover one ordinary report, related reports, distinct events, an
A-B-C bridge, duplicates, contradictory metadata, absent image input,
insufficient anomaly history, a deliberately constructed rainfall outlier, and
invalid weather observations. These inputs were authored to exercise known
branches. They were not sampled from citizen reports, field sensors, production
traffic, or a representative population.

The golden fixtures must not be used for training, threshold selection,
accuracy estimation, calibration, field validation, or deployment claims.
Expected statuses, reason codes, grouping structure, duplicate links, and
anomaly outcomes are engineering assertions derived from the documented
contracts. The performance record is likewise synthetic host-local timing and
not a dataset or production-throughput measurement.
