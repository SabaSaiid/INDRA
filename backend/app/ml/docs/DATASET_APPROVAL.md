# Dataset approval and model-training gate

Dataset approval is explicit, split-scoped, and fail-closed. Validation never
creates an approval.

## How real data becomes eligible

1. Place the manually supplied dataset on a local filesystem. Safely extract a
   manually supplied ZIP before discovery.
2. Establish the source, usage rights, schema version, label provenance,
   grouping strategy, and split strategy outside the tool. Do not guess any
   missing fact.
3. Register the exact bytes with `discover-dataset`. A deterministic content
   hash is recorded immediately and status remains `DISCOVERED`.
4. Run `validate-dataset`. This writes a machine-readable report, binds its
   file SHA-256 into the registry, updates counts, clears stale approvals, and
   sets status to `VALID` or `INVALID`.
5. Inspect `report-dataset` and `verify-leakage`. All required leakage checks
   must be `PASS`; `INSUFFICIENT_EVIDENCE` is not approval evidence.
6. Independently review provenance, license/usage, label quality, split
   independence, component-specific readiness, and validation output.
7. Run `approve-dataset` separately for `TRAINING`, `VALIDATION`, and `TEST`,
   naming an approver and a meaningful approval note. Each approval is bound to
   the expected split (`train`, `validation`, or `test`), current content hash,
   and current validation-report hash.
8. Invoke a training entry point with dataset ID, dataset version, and registry
   path. The entry point rechecks the registry, local path, current bytes,
   report binding, leakage result, classification, component, and approvals
   before any fitting code can run.

Revalidation clears all prior approvals. Changing dataset bytes causes a hash
mismatch. Changing the report causes a report-hash mismatch. Changing registry
identity, component, path, format, or registered hash makes the bound report
invalid. None of these conditions falls back to training.

## Approval API

`approve_dataset(...)` accepts exactly one `DatasetUse` at a time. It rejects:

- records not in a validated or already-approved state;
- `INVALID`, `QUARANTINED`, `DISCOVERED`, or `VALIDATING` data;
- unknown provenance;
- development-only or test-fixture data;
- production-test data requested for training;
- changed or missing local bytes;
- missing, changed, malformed, stale, or identity-mismatched reports;
- validation failure;
- leakage `FAIL` or `INSUFFICIENT_EVIDENCE`;
- absent target splits, incomplete grouping, insufficient labels, or any
  component-specific blocker.

## Component gates

NLP requires independent train/validation/test assignments, complete grouping,
at least two represented labels with sufficient training examples, and
multilingual coverage in each approved split. Exact and near text leakage must
pass. The committed synthetic corpus cannot be promoted.

DUPLICATE requires human-adjudicated `DUPLICATE`, `NOT_DUPLICATE`, or
`UNCERTAIN` labels and event/incident grouping where registered. Matcher,
model, detector, rule, or generated labels are prohibited.

EVENT requires human event-pair or report-to-event ground truth and canonical
event/incident grouping. Current heuristic event output is not ground truth.

CREDIBILITY requires human-adjudicated `AUTHENTIC`, `MISLEADING`, or
`UNCERTAIN` judgments with grouping by report family, event, incident, or an
explicit source strategy. Current rule scores cannot become labels.

IMAGE requires decodable local JPEG/PNG files, exact annotation-to-file hash
and dimension agreement, real labels, complete registered grouping, and no
duplicate image bytes. Synthetic images remain `TEST_FIXTURE_ONLY`.

ANOMALY requires historical observations, chronological train/validation/test
ordering, station grouping, and an explicit role. `UNSUPERVISED_BASELINE` can
be approved only as training baseline data; it is not validation or test
ground truth. `SUPERVISED_EVALUATION` requires human-adjudicated anomaly labels.
Detector output cannot manufacture those labels.

## Training denial reasons

The model-training gate returns an explicit decision with stable reason codes,
including:

- `DATASET_UNREGISTERED`
- `DATASET_VERSION_AMBIGUOUS`
- `COMPONENT_MISMATCH`
- `DATASET_PATH_MISMATCH`
- `DATASET_HASH_MISMATCH`
- `INVALID_SCHEMA`
- `PROVENANCE_UNKNOWN`
- `LEAKAGE_FAILURE`
- `LEAKAGE_INSUFFICIENT_EVIDENCE`
- `WRONG_SPLIT`
- `INSUFFICIENT_LABELS`
- `TEST_CONTAMINATION`
- `APPROVAL_MISSING:<USE>`
- `APPROVAL_STALE:<USE>`
- `VALIDATION_REPORT_INVALID`
- `DATASET_STATUS_BLOCKED`
- `DATASET_CLASSIFICATION_BLOCKED`

The gate raises `DatasetTrainingGateError` when authorization fails. It never
logs a warning and proceeds.

Phase 13 adds no model and performs no retraining. The image and anomaly
training commands still return their prior explicit unavailable state, and the
duplicate, event, and credibility commands remain non-training placeholders.
