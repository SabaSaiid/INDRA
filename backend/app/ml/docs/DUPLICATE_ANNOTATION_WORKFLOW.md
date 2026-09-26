# Duplicate annotation workflow

1. Prepare a local report file containing report IDs, text, timestamps, and
   coordinates where available.
2. Run deterministic candidate generation with the approved time and
   geographic windows.
3. Review candidates locally with the CLI. The default mode randomizes review
   order with a fixed seed and hides the candidate score. If a score is shown,
   it is explicitly labeled `MODEL SCORE — NOT GROUND TRUTH`.
4. Save each annotator's decision as an independent append-only JSONL record.
   The three choices are `DUPLICATE`, `NOT_DUPLICATE`, and `UNCERTAIN`.
5. Run quality control and inspect missing content, invalid pair IDs,
   duplicate annotations, disagreements, and agreement availability.
6. Create an adjudication case for repeated annotations. An unresolved case
   remains `UNCERTAIN`; only an explicit adjudicator decision is exportable as
   dataset ground truth.
7. Group adjudicated records into train, validation, and test. Never place the
   same event or incident in more than one split.
8. Run leakage checks, create a deterministic dataset manifest, and retain its
   source/content hashes.
9. Select thresholds on validation only. Evaluate the test split once after
   the threshold is frozen. Do not claim statistical significance for tiny
   datasets.

The workflow is local-only and contains no pretrained model, external
embedding, external API, network call, runtime download, or production
pipeline integration.
