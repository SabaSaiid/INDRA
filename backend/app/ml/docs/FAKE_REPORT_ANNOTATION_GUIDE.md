# Fake / misleading report annotation guide

THIS SYSTEM DOES NOT ESTABLISH TRUTH BY ITSELF. Human labels must rely only on
evidence available to the annotator and must retain uncertainty when the claim
cannot be established.

## Taxonomy

`AUTHENTIC` means the available evidence supports the material claims and
presentation of the report. It does not mean that a low rule score proved the
report true.

`MISLEADING` means available evidence establishes that a material claim,
context, timestamp, location, media association, or presentation is false or
meaningfully deceptive. The annotation reason must cite that evidence.

`UNCERTAIN` means the evidence cannot establish either label. Use it for
unverifiable claims, incomplete information, ambiguous wording, missing
context, unresolved source conflicts, or any case where the annotator would
otherwise be guessing.

## Important distinctions

- A factually false material claim may be `MISLEADING` when the contradiction
  is supported by available evidence.
- Misleading presentation can include materially wrong context even if some
  individual details are accurate.
- Incomplete information is not automatically misleading. Use `UNCERTAIN`
  unless the omission is demonstrably deceptive and material.
- An unverifiable claim is `UNCERTAIN`, not `MISLEADING` by default.
- A duplicated or copied report is duplication evidence, not proof of falsity.
- An unusual or low-quality report remains ambiguous unless evidence supports
  a stronger label.

## Workflow and blinding

Annotations are append-only and retain annotator ID, timestamp, reason, and
evidence provenance. Multiple annotators may independently review one report;
the same annotator must not submit a second label for that report.

The default annotation view is blinded and hides the rule score. If rule
evidence is displayed, the interface must show:

`MODEL/RULE EVIDENCE — NOT GROUND TRUTH`

Rule evidence may guide inspection but must never be copied directly into the
human label without independent review.

Disagreements create an explicit adjudication case. Until a named adjudicator
records a label, timestamp, and reason, the effective label remains
`UNCERTAIN`. Previous annotations are never overwritten.

## Quality and splitting

Quality checks reject duplicate annotation IDs, repeated report/annotator
records, missing reports, invalid coordinates, invalid timestamps, and
taxonomy violations. Inter-annotator agreement is calculated only for reports
with repeated independent annotations; otherwise it is `DATA_UNAVAILABLE`.

Dataset splits must be grouped by canonical event, incident, or report family.
The same report, group, or exact normalized text may not cross splits. No
pretrained embeddings are used for leakage checks.
