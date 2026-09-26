# Local dataset registry

Phase 13 adds one machine-readable source of truth for data presented to the
INDRA AI/ML subsystem:

`backend/app/ml/data/registry/datasets.json`

The registry covers `NLP`, `DUPLICATE`, `EVENT`, `CREDIBILITY`, `IMAGE`, and
`ANOMALY`. It records local data identity and validation state; it does not
grant approval merely because a file was discovered or validated.

## Local-only boundary

Registry, hashing, validation, reporting, splitting, and approval operations
accept filesystem paths only. URL and UNC/network paths are rejected. These
operations contain no downloader, API collector, cloud client, remote model
loader, or external inference path.

Supported inputs are CSV, JSON, JSONL, locally supported Parquet, JPEG, PNG,
local directories, and manually supplied ZIP archives. A ZIP is never
validated in place. It must first be extracted with the local extraction
command, which preflights member count, total expanded size, path traversal,
symbolic links, duplicate destinations, and overwrites.

For non-image directory datasets, CSV/JSON/JSONL/Parquet shards are loaded in
canonical relative-path order. Other members remain included in the directory
hash and are disclosed as unparsed warnings. Image directories use one root
annotation manifest plus recursively discovered JPEG/PNG files.

## Registry record

Each `(dataset_id, dataset_version)` identity is unique. A record contains:

- component and local path;
- declared format;
- SHA-256 content identity;
- dataset and label schema versions;
- timezone-aware creation timestamp;
- source description, explicit provenance, and license/usage note;
- split, grouping, and time field names;
- label and row/image counts;
- status and data classification;
- human-adjudication and label-source declarations;
- anomaly data role when applicable;
- a hash-bound validation-report path;
- separate, split-scoped approval records.

For one file, `content_sha256` is the SHA-256 of its exact bytes. For a
directory, it is the SHA-256 of a canonical manifest sorted by relative POSIX
path. Every manifest item includes relative path, byte count, and file SHA-256;
filesystem enumeration order and modification times do not affect identity.
Symbolic links are rejected.

## Status and classification

Status describes workflow state:

- `DISCOVERED`
- `VALIDATING`
- `VALID`
- `INVALID`
- `APPROVED_TRAINING`
- `APPROVED_VALIDATION`
- `APPROVED_TEST`
- `QUARANTINED`

The scalar status reflects the latest state transition. The `approvals` list
is authoritative when more than one use has been approved; each use can occur
at most once and is bound to its exact split, bytes, and validation report.

Classification describes permitted evidence use:

- `CANDIDATE_DATA`
- `DEVELOPMENT_ONLY`
- `TEST_FIXTURE_ONLY`
- `PRODUCTION_TEST`

`VALID` means that the bytes and supported schema passed structural checks. It
does not mean that leakage evidence is sufficient or that any use is approved.
Development-only and test-fixture data cannot be approved. Production-test
data can never be approved for training.

## Local commands

Run commands from `backend`:

```text
python -m app.ml.data.cli hash-dataset D:\local\dataset.jsonl

python -m app.ml.data.cli discover-dataset --dataset-id citizen-reports --dataset-version 2026-09-reviewed --component NLP --path D:\local\citizen-reports.jsonl --schema-version nlp-report-dataset-v1 --label-schema-version event-type-labels-v1 --source-description "Manually supplied reviewed export" --provenance USER_SUPPLIED --license-or-usage-note "Internal approved research use" --grouping-field incident_id

python -m app.ml.data.cli validate-dataset --dataset-id citizen-reports --dataset-version 2026-09-reviewed

python -m app.ml.data.cli report-dataset --dataset-id citizen-reports --dataset-version 2026-09-reviewed

python -m app.ml.data.cli verify-leakage --dataset-id citizen-reports --dataset-version 2026-09-reviewed
```

The other commands are `approve-dataset`, `split-dataset`, and
`extract-local-archive`. Use `--registry` to operate on a separately managed
local registry. Discovery never infers provenance, labels, grouping, or
approval.

## Committed registry state

The original entry is `indra-nlp-reports-v1-synthetic` version
`reports-v1-development-synthetic`. Its file hash matches and its schema is
structurally valid. It remains `DEVELOPMENT_ONLY`, has no validation partition
or grouping field, has leakage status `INSUFFICIENT_EVIDENCE`, and has no
approvals.

Phase 17 adds `indra-nlp-project-synthetic-v1` version
`synthetic-nlp-100k-v1`. Its 100,000 rows, structured scenarios, quality report,
and manifest are hash-bound and valid. Its explicit partitions use
generator-level template, lexical, location, time-range, and parameter
separation. This entry is also `DEVELOPMENT_ONLY`, carries
`PROJECT_GENERATED_SYNTHETIC` labels, has no approvals, and is prohibited as
real-world or production-validation evidence. See `SYNTHETIC_NLP_DATASET.md`.
