# Duplicate-pair annotation guide

This guide defines the future human-review protocol for duplicate matching.
The repository currently contains no production duplicate labels. The sample
fixture under `data/labelled/duplicates/` is marked `UNIT_TEST_ONLY` and must
not be used as an operational quality claim.

## Review unit

Review two already-loaded reports as one unordered pair. Reviewers must use
the report text, occurrence time, coordinates, source metadata, and any
available incident/event context supplied by the annotation tool. Do not
search external sources or infer a match solely from a shared generic word.

## Labels

- `DUPLICATE`: both reports refer to the same underlying occurrence or to
  substantially the same submitted observation, according to the project's
  operational definition, with enough corroborating context to merge them.
- `NOT_DUPLICATE`: the reports are distinct incidents, even if they share a
  location, event type, or generic wording.
- `UNCERTAIN`: evidence is insufficient, contradictory, or outside the review
  policy. Do not force a binary decision.

Examples that are normally `NOT_DUPLICATE` include the same weather type at
different times or locations, two localized incidents during the same broad
storm, copied text describing separate observations, and reports that merely
share a generic phrase. A shared location is not enough when the event or time
differs.

## Required annotation fields

Every annotation records `pair_id`, both report IDs, `label`, `annotator_id`,
`annotation_timestamp`, `annotation_reason`, and `label_provenance`. Record
`event_id_when_known` or `incident_id_when_known` when known so grouped
train/validation/test splits can prevent event leakage. A second annotation by
the same annotator for the same unordered pair is a duplicate annotation and
must be rejected.

## Disagreement and adjudication

Different labels for the same unordered pair are retained as an explicit
contradiction for adjudication; they are not silently averaged. Until an
authorized adjudicator resolves the conflict, the pair is treated as
`UNCERTAIN` for metric calculation. Metrics exclude `UNCERTAIN` pairs and
report the excluded count.

The matcher is an evidence-producing comparison tool; it does not define the
ground-truth label and must never be used to auto-annotate the dataset.

## Split and threshold policy

Splits are grouped by complete `event_id_when_known`, or by complete
`incident_id_when_known` when event IDs are unavailable. If neither key is complete, grouped splitting is
reported as `GROUPED_SPLIT_UNAVAILABLE`; a row-level fallback is prohibited.
Threshold selection is validation-only. The test split is held out for one
final evaluation and may not be used to tune thresholds, weights, or feature
state.
