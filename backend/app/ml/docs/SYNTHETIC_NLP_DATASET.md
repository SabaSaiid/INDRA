# Phase 17 project-generated synthetic NLP dataset

Dataset identity: `indra-nlp-project-synthetic-v1` / `synthetic-nlp-100k-v1`

This corpus is **PROJECT_AUTHORED**, **SYNTHETIC**, and
**DEVELOPMENT_ONLY**. It is not real incident data, is not production
validation, and does not estimate field performance. NLP v2 was not used to
generate labels and was not modified. Phase 17 trains no model.

## Reproduction

From the repository root:

```text
python scripts/generate_synthetic_nlp_dataset.py
```

The frozen defaults are:

- generator: `synthetic-nlp-generator-v1`;
- scenarios: `synthetic-nlp-scenarios-v1`;
- templates: `synthetic-nlp-templates-v1`;
- split plan: `synthetic-nlp-generator-splits-v1`;
- seed: `170017`;
- rows: `100000`;
- creation timestamp: `2026-09-23T00:00:00Z`.

Use `--no-register` for artifact generation without registry mutation. Existing
artifacts are never overwritten unless `--overwrite` is explicit, and an
existing registry identity is never replaced unless
`--replace-registry-entry` is explicit.

The generator uses only local Python standard-library behavior plus existing
repository contracts. It performs no network access, downloads, API calls,
model inference, embeddings, or automated relabeling.

## Released files

The release is under `data/labelled/nlp/synthetic_v1/`:

- `synthetic_nlp_dataset.jsonl` is the compact classifier-development corpus;
- `synthetic_nlp_scenarios.jsonl` stores the corresponding structured scenario
  metadata without generated text;
- `synthetic_nlp_dataset_report.json` is the specialized quality and leakage
  receipt;
- `synthetic_nlp_dataset_manifest.json` binds versions, policy declarations,
  and artifact hashes.

The dataset SHA-256 is
`6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76`.
The scenario-metadata SHA-256 is
`9d87d4d59a3d576a76e603edc1cf509ac4cf6d0ceaf99003448b31f6641cb79f`.

## Composition

The five primary labels each contain 20,000 rows:

- `URBAN_FLOOD`;
- `RIVER_BREACH`;
- `CLOUDBURST`;
- `CYCLONE_INUNDATION`;
- `NOT_RELEVANT`.

Language counts are 33,334 English, 33,333 Hindi, and 33,333 Hinglish. Hindi
uses natural Unicode Devanagari. Hinglish is authored independently with
code-switching patterns rather than mechanical translation.

There are 20,000 independently generated hard-negative rows, 4,000 for each
of these distinctions:

- urban drainage flooding versus river failure;
- river failure versus urban drainage;
- localized cloudburst versus generic waterlogging;
- cyclone surge versus routine urban flooding;
- weather wording without an observed target event.

The source contains 135 split/language/class-specific base templates. Source
style and sentence framing produce 4,831 realized structural template variants
in the frozen release; the most-used realized structure occurs 85 times.
Scenario parameters additionally vary locations, timestamps, depths, durations,
rain terms, river/storm/cyclone conditions, severity, source style, and
punctuation/noise.

Noise distribution is 30,000 `NONE`, 30,001 `LOW`, 29,999 `MEDIUM`, and
10,000 `HIGH`. `HIGH` is held out from train and is used only by the synthetic
test partition.

## Generator-level holdout

Rows are never randomly split. Scenario allocation produces 80,000 train,
10,000 validation, and 10,000 test rows. Each partition has separate template
IDs, location pools, lexical pools, and non-overlapping time ranges. Test also
uses the held-out `HIGH` noise profile. Parameter-combination, template, and
scenario identifiers are checked for cross-split reuse.

This is a synthetic holdout only. It must not be described as independent
real-world validation.

## Validation and governance

The specialized streaming validator checks:

- duplicate record and scenario IDs;
- exact and Unicode-normalized duplicate text;
- conflicting labels and scenario-to-row label bindings;
- class, language, split, noise, and hard-negative coverage;
- language-specific script/code-switch constraints;
- exact and normalized cross-split text overlap;
- template, scenario, and parameter-combination leakage;
- cross-split near duplicates using location/number-masked token-bigram
  SimHash with deterministic LSH candidate lookup.

All duplicate, contradiction, binding, and leakage counts are zero in the
frozen release. The registry independently hashes the dataset and verifies the
specialized report, manifest, and scenario metadata before marking the entry
`VALID`.

`VALID` means structurally intact, not production approved. The registry entry
remains `DEVELOPMENT_ONLY`, has no approvals, is not human-adjudicated, and has
label source `PROJECT_GENERATED_SYNTHETIC`. Training, validation, and test
approval paths remain blocked for production governance.
