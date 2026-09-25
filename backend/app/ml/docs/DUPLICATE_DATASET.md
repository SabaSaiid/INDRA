# Duplicate dataset specification

The duplicate-pair dataset is a human-adjudicated evaluation dataset. The
matcher can rank local review candidates, but **GROUND TRUTH COMES FROM HUMAN
ADJUDICATION, NOT FROM THE MATCHER**.

## Source and candidate generation

Reports are read from local CSV, JSON, or JSONL files, or from already-loaded
report objects. PostgreSQL, Kafka, remote URLs, and network services are not
used. `generate_candidate_pairs` applies deterministic time and geographic
windows, canonicalizes report order, rejects self-pairs, and emits
`CANDIDATE_FOR_REVIEW`. Its optional token-overlap score is a review heuristic,
not a label.

Reports missing timestamps or coordinates are skipped rather than assigned
fabricated values. Candidate order and pair IDs are deterministic.

## Annotation records

Each independent annotation is stored as one JSONL record containing the pair
ID, both report IDs, one of `DUPLICATE`, `NOT_DUPLICATE`, or `UNCERTAIN`, an
annotator ID, timestamp, reason, and optional event/incident IDs or notes.
`AnnotationStore` is append-only and rejects a second annotation by the same
annotator for the same unordered pair. Different annotators remain separate.

## Adjudication

`AdjudicationCase` preserves every annotation. An unresolved disagreement has
effective label `UNCERTAIN`; no consensus is inferred, even when annotations
happen to agree. An adjudicator must explicitly record the final label,
identity, timestamp, and reason before the case can be exported to an
evaluation dataset.

## Quality control

Quality reports validate pair IDs, self-pairs, reversed pairs, duplicate
annotations, missing report content, timestamps, and coordinates. They report
label counts, annotator counts, disagreements, and agreement only when repeated
annotations exist. Otherwise agreement is `DATA_UNAVAILABLE`.

## Splitting and leakage

Adjudicated records are split by complete `event_id_when_known`, falling back
to `incident_id_when_known`. If grouping is unavailable, the split status is
`GROUPED_SPLIT_UNAVAILABLE`. Pair, reversed-pair, event, incident, and exact
normalized-text overlap across train/validation/test is rejected.

## Versioning and evaluation

Released manifests contain dataset version, creation timestamp, source hash,
content hash, schema/guideline versions, annotator count, label counts, split
definition, and grouping strategy. Manifest and content hashes use canonical
JSON serialization.

Thresholds may be selected from validation only. The test split is held out
for one final evaluation; test-set threshold optimization is rejected. The
default text `0.55` and combined `0.70` thresholds remain
`PROVISIONAL / UNVALIDATED`.

## Phase 19 synthetic development benchmark

The registry contained no approved human-adjudicated duplicate dataset, so
Phase 19 explicitly selected the synthetic fallback. The registered
`indra-duplicate-project-synthetic-v1` release contains 100,000 project-authored
pairs: 70,000 train, 15,000 validation, and 15,000 protected test. It is marked
`PROJECT_AUTHORED / SYNTHETIC / DEVELOPMENT_ONLY`; scenario identity supplies
ground truth and the matcher is never used to label rows.

All required duplicate and hard-negative scenarios are present in English,
Hindi, and Hinglish. Report, unordered/reversed pair, incident, scenario-family,
parameter-combination, and exact-text cross-split leakage checks pass. The new
`duplicate_feature_state_v2.json` was fitted from training report text only;
the original `duplicate_feature_state.json` was not overwritten.

Validation-only selection produced an opt-in text threshold `0.60`, combined
threshold `0.65`, geographic gate `5 km`, and temporal gate `30 minutes`.
After freeze, one protected synthetic test invocation produced precision
`0.9851116625`, recall `0.9998518519`, F1 `0.9924270274`, FPR
`0.0151111111`, and FNR `0.0001481481`. These measurements do not validate
field performance. The default matcher and live backend remain unchanged, and
`PRODUCTION_VALIDATION` remains `NOT_VALIDATED`. See
`DUPLICATE_V1_SYNTHETIC_VALIDATION.md` for hashes, ablation, calibration,
subgroup stability, failures, and performance limitations.
