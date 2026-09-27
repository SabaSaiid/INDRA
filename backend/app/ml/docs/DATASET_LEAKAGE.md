# Dataset leakage and split policy

Every validation report contains six leakage checks:

- exact duplicate leakage;
- near-duplicate leakage where locally supported;
- group leakage;
- temporal leakage;
- label leakage;
- cross-split identity overlap.

Each check reports `PASS`, `FAIL`, or `INSUFFICIENT_EVIDENCE` and states whether
it is required for that component. Overall status is `FAIL` if any required
check fails, `INSUFFICIENT_EVIDENCE` if no required check fails but one lacks
evidence, and `PASS` only when all required checks pass.

Missing grouping metadata never produces `PASS`. It produces
`INSUFFICIENT_EVIDENCE` and blocks every approval.

## Exact, near, identity, and label checks

For NLP and credibility records, exact leakage uses Unicode NFKC-normalized,
case-folded, whitespace-normalized text. Cross-split identity checks use the
record/report identity. Conflicting labels for one identity fail label leakage.

NLP and credibility near-text checks use a deterministic local character
sequence comparison with a 0.95 threshold. Complete text and split coverage is
required. The exhaustive scan deliberately stops at 5,000 records; larger
corpora receive `INSUFFICIENT_EVIDENCE` and need an independently reviewed,
scalable local near-duplicate report before this implementation can approve
them.

For images, exact leakage uses byte SHA-256. Near leakage uses the explicitly
supplied perceptual hash only when every image has one; it is not a pretrained
embedding. Duplicate image files anywhere in one registered directory are a
validation failure.

For schemas without a supported near-duplicate representation, the near check
is non-required `INSUFFICIENT_EVIDENCE`; it is never presented as measured
success.

## Group rules

The registered grouping field must be present on every row, and one group must
not cross splits. Appropriate groups are:

- NLP: source record family, incident, or other independently justified unit;
- DUPLICATE: event or incident where available;
- EVENT: canonical event or incident;
- CREDIBILITY: report family, event, incident, or justified source unit;
- IMAGE: event, source report, incident, or capture session;
- ANOMALY: station or the explicitly documented station-generalization unit.

A unique group invented per row defeats the purpose of grouped evaluation and
must not be approved by human review merely because the mechanical check
passes.

## Temporal rules

Anomaly data requires populated train, validation, and test timestamps. The
latest training timestamp must be earlier than the earliest validation
timestamp, and the latest validation timestamp must be earlier than the
earliest test timestamp. Equal boundary timestamps count as overlap. This
prevents future observations from entering baseline fitting or threshold
selection.

Temporal ordering is reported as non-required `INSUFFICIENT_EVIDENCE` for
components that do not declare it as a split rule. If another component needs
a temporal policy, register and review that requirement rather than assuming a
random row split is safe.

## Explicit split management

Every readiness row or image annotation must carry `train`, `validation`, or
`test` in the registered split field. Invalid, blank, or missing assignments
fail readiness. A nonstandard field name may be registered explicitly and is
mapped to the canonical split contract during validation.

`split-dataset` only materializes assignments already present in a dataset. It
sorts output deterministically and writes three local JSONL files. It never
chooses random rows, moves groups, repairs temporal ordering, or invents an
empty split.

Run `verify-leakage` after every byte or split change. Revalidation binds a new
report and clears approvals so stale evidence cannot authorize training.
