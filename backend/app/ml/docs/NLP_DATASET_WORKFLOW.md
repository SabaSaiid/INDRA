# NLP human-dataset workflow

Workflow versions: `nlp-corpus-enrollment-v1`, `nlp-annotation-queue-v1`, and
`nlp-human-annotation-v1`

This is local dataset infrastructure for a future NLP v3 candidate. It does
not train, tune, evaluate, activate, or modify NLP v2. It does not touch the
API, pipeline, Kafka, database, frontend, or legacy MiniLM path. No network,
external model, embedding service, hosted AI API, translation service, or
download is used.

The current NLP v2 artifact remains `DEVELOPMENT_ONLY_FROZEN`. Its historical
90-row final test remains sealed and must never become an annotation source,
training row, validation row, or future test row.

## Files and contracts

- `app/ml/data/nlp_annotations.py`: typed source, annotation, assistance,
  adjudication, quality, sampling, and sealed-test contracts.
- `app/ml/data/nlp_corpus.py`: local corpus discovery, `RawNLPReport`
  normalization, provenance manifests, fail-closed quality/leakage validation,
  and full-population annotation queues.
- `app/ml/data/nlp_dataset.py`: explicit adjudication resolution, connected
  grouping, split materialization, leakage checks, immutable manifests, and
  Phase 13 registry integration.
- `app/ml/annotation/nlp_cli.py`: local operator commands.
- `app/ml/annotation/nlp_corpus_cli.py`: Phase 16 enrollment, queue, and
  source-manifest-bound release commands. This module has no model import.
- `NLP_ANNOTATION_GUIDE.md`: the human labeling authority.
- `data/labelled/nlp/annotation_quality_report.json`: an honest committed
  zero-data report. It remains `DATA_UNAVAILABLE` until actual local review
  evidence exists.

No real citizen or field dataset is bundled by Phase 15 or Phase 16.

## Lifecycle states are not interchangeable

- **CORPUS ENROLLED** means an explicitly supplied local file has a hash-bound
  source manifest and has passed schema, quality, encoding, duplicate, and
  sealed-final-test checks. It has no event labels.
- **ANNOTATED** means one or more append-only human judgments exist. A human
  judgment may remain `UNCERTAIN`; matching votes do not become a final label.
- **ADJUDICATED** means a separate human decision explicitly resolved a report.
  Original annotations remain immutable. Only an explicitly adjudicated class
  can enter a labeled release.
- **CANDIDATE_DATA** means an immutable labeled version was released and
  registered. This is still neither valid nor approved merely because it was
  released.
- **APPROVED TRAINING DATA** means the Phase 13 validator passed and an
  independent reviewer explicitly approved the exact hash for `TRAINING`.
  Known provenance, complete human evidence, compatible schemas, complete
  grouping, leakage `PASS`, zero historical-final-test overlap, sufficient
  train/validation/test evidence, and all other registry gates are mandatory.

No transition invokes NLP v1, NLP v2, a pretrained/open-weight model,
embedding, external API, network service, or automatic labeler.

## Phase 16 local corpus enrollment

Only a path supplied by the operator is read. URL and UNC/network paths are
rejected; URLs found inside a record are inert strings and are never fetched.
Supported formats are strict UTF-8 CSV, JSON, and JSONL. Parquet is accepted
only when the local optional `pyarrow` dependency already exists; no dependency
is downloaded.

Enroll a file from `backend/`:

```text
python -m app.ml.annotation.nlp_corpus_cli enroll \
  --source D:\local-data\incoming-reports.jsonl \
  --dataset-id local-report-corpus \
  --dataset-version 2026-09-23-v1 \
  --source-description "Explicit local operations export" \
  --provenance OPERATIONAL_EXPORT \
  --output-directory D:\local-data\nlp-enrollments
```

The immutable enrollment directory contains:

- `source_manifest.json`: dataset ID/version, source description, resolved
  local path, exact source-content hash, existing-registry provenance class,
  creation timestamp, and input format;
- `corpus_validation_report.json`: machine-readable checks, counts, grouping
  availability, language/source distribution, date range, and issue codes;
- `records.jsonl`: canonical `RawNLPReport` rows, but only when validation
  passes;
- `enrollment_manifest.json`: exact hashes binding all evidence and either
  `annotation_readiness=READY` or `BLOCKED`.

`PROVENANCE_UNKNOWN` is preserved verbatim. It is a warning at enrollment and
is never converted to a known class; labeled release/approval remains blocked
until provenance is established through a new reviewed version.

### RawNLPReport and text preservation

Each valid row carries `report_id`, exact `text`/`original_text`, separately
derived `normalized_text`, optional observed/submitted timestamps, optional
coordinate pair, optional source type/ID, supplied event/incident/family IDs,
validated language, raw-record hash, exact and normalized text SHA-256 values,
and row-level provenance. Missing optional values remain null. Text is never
trimmed, translated, transliterated, corrected, or overwritten. Normalized
text is NFKC/case/whitespace-normalized and may be used only for search and
contamination checks.

Supplied language accepts `English`/`en`, `Hindi`/`hi`, `Hinglish`, `Other`,
or `Unknown`. Missing language becomes `UNKNOWN`; there is no detector.

### Fail-closed corpus validation

Validation checks missing/empty IDs and text, duplicate IDs, exact and
normalized duplicate text, timezone-aware timestamp syntax, finite/bounded
paired coordinates, UTF-8 decoding, supplied language values, and conflicting
event/incident/family mappings. Any error produces `FAIL` and `BLOCKED`; the
validation and provenance evidence are retained, but `records.jsonl` is not
published and queue loading is refused. Records are never silently dropped to
make a corpus pass.

The frozen v1/v2 files and source corpus are hash-checked before enrollment.
Every incoming exact and normalized text hash is checked against the sealed
90-row final test. Any match emits `FINAL_TEST_OVERLAP_DETECTED` with record
identifier and hashes, blocks the entire enrollment, and is never silently
removed.

Grouping uses only supplied `event_id`, `incident_id`, and
`source_report_family`. Connected identifiers receive a deterministic
component key for queue priority; no text-derived event is inferred. If no row
has a grouping identifier, the report states `GROUPING_NOT_AVAILABLE`. Partial
grouping remains visible and later prevents approval.

## Phase 16 annotation queue

Create a queue only from a `READY` enrollment:

```text
python -m app.ml.annotation.nlp_corpus_cli queue \
  --enrollment-directory D:\local-data\nlp-enrollments\local-report-corpus\2026-09-23-v1 \
  --strategy LANGUAGE_BALANCED \
  --seed 42 \
  --priority-count 100 \
  --output-directory D:\local-data\queues\local-report-corpus-v1
```

The queue contains every enrolled report exactly once. Sampling changes only
`priority_rank` and `priority_selected`; it does not filter, duplicate,
oversample, reweight, or alter the underlying corpus distribution. Every item
contains deterministic `queue_id`, report/dataset identity, exact text hash,
language, supplied-only grouping metadata, and initial status `UNANNOTATED`.
There is no event-label field. Later workflow states are `IN_REVIEW`,
`LABELED`, `UNCERTAIN`, `ADJUDICATION_REQUIRED`, and `RELEASED`; labels remain
in the separate human annotation/adjudication records. State changes are an
append-only JSONL event stream created by `nlp_corpus_cli queue-status`; the
original queue is never rewritten. Invalid transitions fail, and `RELEASED`
requires an adjudication ID plus the released dataset version.

Strategies are `RANDOM`, `LANGUAGE_BALANCED`, `GROUP_BALANCED`,
`SOURCE_BALANCED`, `UNCERTAINTY_REVIEW`, and `MODEL_ERROR_REVIEW`. The two
review strategies require an explicit local list of report IDs. The queue code
does not run a model or derive uncertainty/errors; those IDs are non-ground-
truth priority evidence only. Strategy, seed, priority count, population count,
and review IDs are recorded.

`annotation_queue_report.json` records actual total/language/group/source
counts, date range, and duplicate/empty counts. It never asserts synthetic
balance. The default is `blind_annotation=true` and
`model_assistance_shown=false`. Phase 15 assisted review remains a separate,
explicit opt-in; it must display `MODEL SUGGESTION — NOT GROUND TRUTH` and the
human annotation records both `assistance_shown=true` and
`model_assistance_shown=true`.

Run the existing Phase 15 human interface against the enrolled records and
the Phase 16 queue. It consumes every queue item in priority order; a
`priority_count` marks the intended first review batch but does not remove the
remaining population:

```text
python -m app.ml.annotation.nlp_cli annotate \
  --reports D:\local-data\nlp-enrollments\local-report-corpus\2026-09-23-v1\records.jsonl \
  --queue D:\local-data\queues\local-report-corpus-v1\annotation_queue.json \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --annotator-id annotator-a
```

## Legacy/direct Phase 15 source report format

Input is local UTF-8 JSON, JSONL, or CSV. Every row requires:

- `report_id`: stable unique identifier;
- `text`: original non-empty report text.

Supported optional fields are:

- `source_metadata_if_available` (JSON object; `source_metadata` is accepted
  as an input alias);
- `language_hint` (`en`, `hi`, `hinglish`, `other`, or `unknown`);
- `event_id_if_known`;
- `incident_id_if_known`;
- `source_report_family`;
- `source_dataset_id`.

Input aliases `id`, `language`, `lang`, `event_id`, `incident_id`, and
`report_family_id` are accepted where documented in the loader. The loader
does not alter `text`; there is no translation, transliteration, normalization,
spell correction, or trimming of report content. Duplicate report IDs and any
exact or Unicode/whitespace-normalized overlap with the sealed final test are
rejected.

## Annotation record

Each append-only record contains the required Phase 15 fields:

- `annotation_id`, `report_id`, `text_hash`, and exact `text`;
- `state` (`LABELED` or `UNCERTAIN`) and approved `label` when labeled;
- `annotator_id`, timezone-aware `annotation_timestamp`, `reason`, and human
  `confidence`;
- `source_metadata_if_available` and `language`;
- `event_id_if_known`, `incident_id_if_known`, and
  `source_report_family` when supplied.

It also records `source_dataset_id`, schema version, blind/assisted mode,
whether assistance was shown, and suggestion provenance. `LABELED` requires
one approved taxonomy label. `UNCERTAIN` prohibits a class label. The exact
UTF-8 SHA-256 must match the stored text.

The store supports append only. It rejects duplicate annotation IDs and a
second judgment by the same annotator on the same report. Different annotators
may independently review the same report. There is no update or delete API.

## Blind annotation

From `backend/`, run:

```text
python -m app.ml.annotation.nlp_cli annotate \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --annotator-id annotator-a
```

Blind mode is the default: `BLIND_ANNOTATION = TRUE`. The operator must enter a
human class or `UNCERTAIN`, language, reason, and confidence. Nothing in the
source loader or CLI can populate a ground-truth label automatically.

Assisted mode is optional and explicit:

```text
python -m app.ml.annotation.nlp_cli annotate \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --annotator-id annotator-b \
  --model-assistance
```

This loads only the already frozen local v2 artifact after verifying its
sealed SHA-256. Every prediction is headed `MODEL SUGGESTION — NOT GROUND
TRUTH`; the annotator still enters an independent human judgment. Assistance
is recorded in the annotation. It cannot fill the label, adjudicate, alter the
model, call a service, or trigger training.

## Phase 15 post-annotation review queues

The sampling command prioritizes review and never generates labels or changes
the underlying population distribution:

```text
python -m app.ml.annotation.nlp_cli sample \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --strategy LANGUAGE_BALANCED \
  --count 100 \
  --seed 42 \
  --output D:\local-data\queues\language-review.json
```

Strategies are `RANDOM`, `CLASS_BALANCED`, `LANGUAGE_BALANCED`,
`DISAGREEMENT_REVIEW`, `UNCERTAINTY_REVIEW`, `NOT_RELEVANT_REVIEW`,
`HINDI_REVIEW`, `HINGLISH_REVIEW`, and `CONFUSION_PAIR_REVIEW`. Class and error
queues use only existing human labels; a confusion queue compares an existing
human label with an explicitly stored non-ground-truth suggestion. The same
inputs and seed produce the same queue. Queue manifests state
`population_distribution_unchanged=true` and `label_generation=NONE`.

Use a queue during annotation with `--queue <path>`. Sampling does not
oversample, duplicate, reweight, or rewrite the source corpus.

## Multi-annotator quality control

Generate the machine-readable report with:

```text
python -m app.ml.annotation.nlp_cli quality \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --adjudications D:\local-data\nlp-adjudications.jsonl \
  --output D:\local-data\annotation_quality_report.json
```

Validation covers duplicate annotation IDs, repeated judgments by the same
annotator, duplicate source report IDs, missing reports, exact text/hash
mismatch, invalid taxonomy/language values, conflicting text hashes,
disagreement, and adjudication references. It reports source-report,
annotation, and annotator counts; per-annotator, class, and language counts;
uncertainty; repeated reports; agreement; disagreement; adjudication; and
unresolved disagreement.

Agreement uses only reports with at least two independent annotations. If the
configured minimum number of repeated reports is not met, status is
`DATA_UNAVAILABLE` and no agreement rate is invented. Counts include real
zeros; absent evidence is never presented as balance.

## Explicit adjudication

Run:

```text
python -m app.ml.annotation.nlp_cli adjudicate \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --adjudications D:\local-data\nlp-adjudications.jsonl \
  --adjudicator-id adjudicator-a
```

The CLI displays every original human judgment and requires a separate final
human state/label and reason. The decision records `adjudicator_id`, timestamp,
all source annotation IDs, final state/label, and reason. Original annotations
remain unchanged. Matching annotators do not create inferred consensus; every
released class still requires an explicit decision. An unresolved decision is
recorded as `UNCERTAIN` and excluded from labeled rows.

## Grouping and split planning

Grouping creates connected components over every supplied `event_id_if_known`,
`incident_id_if_known`, and `source_report_family`. This is transitive: if A
shares an event with B and B shares an incident with C, A/B/C receive one
group. A report with no available grouping identifier remains visibly
ungrouped; it is not silently treated as proven independent.

Create a plan:

```text
python -m app.ml.annotation.nlp_cli plan-splits \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --adjudications D:\local-data\nlp-adjudications.jsonl \
  --output D:\local-data\nlp-grouping-plan.json
```

The plan lists assignment keys, member reports, known identifiers, and source
dataset IDs. Every `split` is deliberately `null` and
`automatic_split_assignment=NONE`. A reviewer creates a separate JSON object
mapping every assignment key to exactly one of `train`, `validation`, or
`test`, for example:

```json
{
  "nlp-group-0123456789abcdefabcd": "train",
  "nlp-group-fedcba9876543210abcd": "validation"
}
```

The release command requires exact coverage: missing and extra keys fail.
There is no record-level random fallback. A connected group can receive only
one split.

## Future test-set rule

The current 90 rows are historical sealed evidence and cannot be copied,
repurposed, or registered by this workflow. A future `test` row must contain a
`source_dataset_id` explicitly named with
`--independent-test-dataset-id`. That source ID cannot provide any train or
validation row in the version. Supplying a test-source ID without test rows,
or assigning its rows to development splits, fails.

Independence is a data-governance assertion backed by provenance review, not
something the code invents. The registry still requires separate test
approval.

## Leakage checks

Before release, the dedicated validator checks cross-split overlap for:

- record IDs;
- connected group IDs;
- event IDs, incident IDs, and source-report families;
- exact UTF-8 text hashes;
- Unicode/case/whitespace-normalized text hashes;
- near-duplicate normalized text using a transparent local string comparison;
- exact or normalized overlap with the sealed historical final test.

Actual overlap is `FAIL` and stops release. Missing grouping evidence or an
unavailable bounded near-duplicate scan is `INSUFFICIENT_EVIDENCE`: a candidate
version may be preserved for review, but the Phase 13 approval gate rejects it.
No embedding or pretrained feature extractor is used.

## Immutable dataset release

After reviewing the grouping plan and writing the explicit assignments:

```text
python -m app.ml.annotation.nlp_cli release \
  --reports D:\local-data\reports.jsonl \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --adjudications D:\local-data\nlp-adjudications.jsonl \
  --split-assignments D:\local-data\split-assignments.json \
  --dataset-id indra-nlp-human-reports \
  --dataset-version v1 \
  --output-directory D:\local-data\released \
  --registry D:\INDRA\backend\app\ml\data\registry\datasets.json \
  --provenance USER_SUPPLIED \
  --source-description "Locally supplied reports independently human reviewed" \
  --license-or-usage-note "Authorized for approved local development only" \
  --independent-test-dataset-id independently-collected-test-v1
```

Omit `--independent-test-dataset-id` when the candidate intentionally contains
no test rows. Such a version cannot receive training approval until an
independently defined test split exists.

The release directory is new and immutable. Reusing the same dataset ID and
version fails instead of overwriting. It contains canonical `records.jsonl`,
`leakage_report.json`, and `manifest.json`. The manifest includes:

- `dataset_id` and `dataset_version`;
- exact `content_hash`/`dataset_hash`, source-evidence hash, and
  `source_manifest_hash`;
- annotation schema, guide, dataset-schema, and label-schema versions;
- annotator and adjudicator counts;
- label and language counts;
- grouping strategy/status and exact grouping coverage;
- creation timestamp, row count, split definition, and split counts;
- independent test source IDs, explicitly excluded uncertain reports, and
  `uncertainty_count`;
- assistance count, sealed-final-test hash, and leakage result;
- `human_ground_truth=true` and `automatic_label_generation=NONE`.

The registry entry is created as `CANDIDATE_DATA`, `DISCOVERED`,
`human_adjudicated=true`, and `label_source=EXPLICIT_HUMAN_ADJUDICATION`. The
release command never validates, approves, trains, or promotes it.

For a Phase 16 enrollment, use the source-manifest-bound release command:

```text
python -m app.ml.annotation.nlp_corpus_cli release \
  --enrollment-directory D:\local-data\nlp-enrollments\local-report-corpus\2026-09-23-v1 \
  --annotations D:\local-data\nlp-annotations.jsonl \
  --adjudications D:\local-data\nlp-adjudications.jsonl \
  --split-assignments D:\local-data\split-assignments.json \
  --dataset-id indra-nlp-human-reports \
  --dataset-version v1 \
  --output-directory D:\local-data\released \
  --registry D:\INDRA\backend\app\ml\data\registry\datasets.json \
  --license-or-usage-note "Authorized for reviewed local development only"
```

This command rechecks the enrollment source, source-manifest,
validation-report, and normalized-corpus hashes; reuses the Phase 15 explicit
adjudication/leakage path; writes all required release fields; and registers
the exact result as `CANDIDATE_DATA` with initial registry status `DISCOVERED`.
The Phase 13 validator and approval remain separate explicit operations.

## Phase 13 validation and approval

Run validation separately:

```text
python -m app.ml.data.cli validate-dataset \
  --registry D:\INDRA\backend\app\ml\data\registry\datasets.json \
  --dataset-id indra-nlp-human-reports \
  --dataset-version v1
```

Only an independent reviewer may then issue a split-scoped approval:

```text
python -m app.ml.data.cli approve-dataset \
  --registry D:\INDRA\backend\app\ml\data\registry\datasets.json \
  --dataset-id indra-nlp-human-reports \
  --dataset-version v1 \
  --use TRAINING \
  --approver-id dataset-reviewer \
  --approval-note "Reviewed provenance, human adjudication, grouping, and leakage evidence"
```

The NLP branch fails closed for unknown provenance, invalid labels,
development/test-fixture classifications, uncertainty entering a labeled row,
missing or incomplete groups, leakage, missing splits, insufficient class or
multilingual coverage, absent human adjudication, or a label source containing
model/rule/heuristic/detector/generated/random/keyword/LLM provenance. Training
also requires validation and test splits. Approval is explicit and bound to the
validated content hash and validation-report hash.

## Sealed evidence

Every source load, annotation append, resolution, and release invokes protected
checks as appropriate. The committed seals are:

- source corpus SHA-256:
  `3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d`;
- historical final-90 canonical SHA-256:
  `6082b1a16b0326e7932f5610ce99c873112c216b4c422f9a98dda360b0166813`;
- historical final-90 source-order SHA-256:
  `9404db546620ec734efb38464aa1a7d5b7ddfab8f217facc5785d461a3c6c88a`;
- v1 artifact SHA-256:
  `a12387cdfc753e92656f840ae7f22c35fac6d4d2179994b2b9c3ddc594789ba4`;
- frozen v2 artifact SHA-256:
  `ec827431e59116b534c01aba5359410c1a241e8b5c98534339c0ef0d126c560b`.

Protection reads hashes and text fingerprints only for integrity/contamination
checks. It does not expose historical test content to the labeling UI, use it
for sampling, or evaluate it again.
