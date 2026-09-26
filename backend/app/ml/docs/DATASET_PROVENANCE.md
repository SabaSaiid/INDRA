# Dataset provenance

Provenance is a required declaration, not an inference made from a filename,
directory, label, or user account.

## Allowed declarations

`PROJECT_AUTHORED` means the project created the data and can identify the
creation process. It does not imply field realism or production suitability.

`USER_SUPPLIED` means a user deliberately placed the data in local scope and
provided its source and usage statement.

`PUBLIC_DATASET_MANUALLY_ACQUIRED` means a person acquired a public dataset
outside this subsystem and supplied it locally. The registry must still record
the dataset name/source description and its license or usage terms. INDRA does
not download it.

`OPERATIONAL_EXPORT` means the data came from an authorized operational export.
The source description must identify the export process and permitted use
without embedding secrets or personal data in registry metadata.

`PROVENANCE_UNKNOWN` is the only honest value when origin cannot be established.
It is retained so unknown data can be inventoried and inspected, but every
approval path rejects it.

## Required provenance evidence

Before registration, a reviewer must establish and enter:

- stable dataset ID and version;
- timezone-aware creation timestamp;
- plain-language source description;
- one explicit provenance value;
- license, consent, retention, or internal usage note as applicable;
- dataset and label schema versions;
- `CANDIDATE_DATA`, `DEVELOPMENT_ONLY`, `TEST_FIXTURE_ONLY`, or
  `PRODUCTION_TEST` classification;
- label source and whether labels were independently human-adjudicated;
- grouping and time fields required by the component;
- anomaly baseline/evaluation role for anomaly data.

Whitespace placeholders do not satisfy descriptive registry fields. The tool
does not fabricate missing provenance, license terms, adjudication, grouping,
or acquisition dates.

## Label provenance rules

Human-adjudication declarations are required for duplicate, event,
credibility, image, and supervised anomaly approval. A label source containing
model, matcher, heuristic, rule, detector, or generated provenance is blocked
for those components.

The current NLP `reports_v1.csv` provenance is `PROJECT_AUTHORED`, but its
classification is `DEVELOPMENT_ONLY` because it is synthetic. Project authorship
does not upgrade it to real operational evidence.

Current duplicate matcher output, event heuristic output, credibility rule
scores, image test fixtures, anomaly detector output, and Phase 12 golden
scenarios are not ground-truth datasets. They cannot be relabeled by registry
metadata to bypass that fact.

## Manual public or archived data

If a reviewer manually obtains data under valid terms, acquisition remains
outside this software. Only the resulting local file or archive enters the
Phase 13 workflow. Use `extract-local-archive` for a ZIP, review the extracted
tree, then register that tree or a structured local file. Do not add a URL and
expect the registry to retrieve it; URL and network paths are rejected.

Any uncertainty about source or usage rights must be recorded as
`PROVENANCE_UNKNOWN` or in the usage note and resolved before approval.
