# Legacy deduplication migration specification

> Historical pre-Phase-25 specification. The live MiniLM path was subsequently removed and
> replaced by the frozen Phase 19 local matcher. See `docs/ML_ARCHITECTURE.md` for current state.

Status: `SPECIFICATION_ONLY / MIGRATION_NOT_IMPLEMENTED`

## Current state

The live path is a `LEGACY_BACKEND_VIOLATION`:

```text
pipeline._dedup_candidates()
  -> backend-owned SQL time/spatial candidate retrieval
  -> asyncio.to_thread(DedupService.find_duplicate)
  -> sentence-transformers/all-MiniLM-L6-v2 when available
  -> Levenshtein fallback when unavailable
  -> raw_reports.duplicate_of update
```

`backend/app/main.py` also warms the embedding model during startup, and
`backend/requirements.txt` declares `sentence-transformers`. These live files
are intentionally unchanged in Phase 11.

## Target state

The target scoring engine is the compliant, local
`app.ml.components.duplicate_matching.DuplicateMatcher`, using the authorized
`duplicate_feature_state.json` feature state and `DuplicatePrediction` result
contract. Its current combined threshold `0.70` and text threshold `0.55` are
`PROVISIONAL / UNVALIDATED`; migration must not describe them as calibrated or
production validated.

## Required migration design

### Candidate retrieval remains backend-owned

Keep the database query, transaction, original-report resolution, spatial/time
prefilter, ordering, and candidate-count limits in the backend. Convert each
retrieved row into a `CandidateReport` and supply the list in `ReportInput`.
The ML package must not import SQLAlchemy, query `raw_reports`, or resolve
`duplicate_of` chains.

### DuplicateMatcher becomes the scoring engine

Replace only the synchronous `DedupService.find_duplicate` scoring call after a
shadow comparison and an approved cutover. The matcher evaluates all supplied
candidates and returns the deterministic best match. Candidate tie-breaking is
by score and report ID, which differs from the legacy first-match/oldest-first
behavior and therefore requires explicit regression acceptance.

### Result-contract mapping

Map results as follows:

| `DuplicatePrediction` state | Backend behavior |
|---|---|
| `AVAILABLE` and `is_duplicate=true` | Resolve `matched_report_id` to the backend-owned original ID, then use the existing persistence transaction. |
| `AVAILABLE` and `is_duplicate=false` | Continue the existing pipeline without suppressing the report. |
| `NOT_APPLICABLE` | No candidates were supplied; continue without a duplicate decision. |
| `INSUFFICIENT_DATA` | Do not suppress; record the reason for observability and route according to approved fallback policy. |
| `ERROR` or `OFFLINE` | Do not silently treat as a validated non-duplicate; invoke the approved fallback or fail-safe path. |

Persisted audit evidence should include component/version identifiers,
threshold status, selected candidate ID, similarities, geographic and temporal
distances, reason codes, and whether a fallback was used. The ML package must
not perform the database write itself.

### Fallback behavior

Choose and approve one explicit policy before cutover:

1. temporarily call the legacy scorer only for `ERROR`/`OFFLINE` during a
   measured transition window; or
2. fail open to normal event processing while recording a dedup-unavailable
   audit event; or
3. hold the report for human review if operational policy requires it.

The fallback must never download a model, must be observable, and must not turn
missing/error states into `is_duplicate=false` without an audit record. The
legacy fallback cannot be removed until the selected behavior has regression
coverage and operational approval.

### Threshold configuration

Backend settings and `DuplicateMatchingConfig` currently express different
scoring methods and thresholds; they are not numerically interchangeable. Do
not copy the legacy cosine `0.88` or Levenshtein `0.75` into the new combined
score. Freeze new thresholds only from human-adjudicated, grouped validation
data, evaluate the untouched test split once, version the selected values, and
retain rollback settings.

### Feature-state loading

Load `duplicate_feature_state.json` through its existing local-only loader at
startup or first use. Startup readiness must verify the exact manifest entry,
SHA-256, component identity, corpus hash, feature/preprocessing versions,
analyzer definitions, vocabulary/IDF dimensions, and policy status. A failed
authorization must produce an explicit unavailable state; no refitting or
runtime download is allowed.

### Startup warm-up removal

After the new path has passed shadow and cutover tests, remove only the legacy
MiniLM warm-up task and its shutdown handling from `backend/app/main.py`.
Confirm that application startup, health checks, and shutdown no longer depend
on embedding initialization or cache availability.

### Dependency and legacy-code removal

Remove `sentence-transformers`, the legacy model loader, and legacy-only model
artifacts only after repository-wide import/use searches are clean and the
complete backend suite passes. `backend/app/ml/event_classifier.py` also uses
the legacy embedding service and must be retired or replaced before dependency
removal. This cleanup is a separately reviewed change, not part of Phase 11.

## Required regression evidence

- Golden cases for no candidates, exact duplicates, paraphrases, nearby but
  distinct incidents, same text outside geographic/time gates, empty text,
  multilingual text, ties, and malformed feature state.
- Shadow-mode comparison on representative traffic with disagreement review;
  no live decisions should be changed during shadowing.
- Human-adjudicated false-merge and false-split measurements, stratified by
  language/source/event type and grouped by incident or event.
- Verification that `duplicate_of` still points to an original report and that
  duplicates never become corroborating event members.
- Concurrent pipeline, transaction, idempotency, startup, health-check,
  latency, and bounded-candidate tests.
- Explicit artifact-hash, version-mismatch, local-only path, no-network, and
  missing-artifact failures.
- Complete ML and backend test suites in the approved environment.

## Rollback strategy

Use an explicit backend feature flag with three observable modes:
`legacy`, `shadow`, and `local_matcher`. Preserve the legacy implementation and
its dependency during shadow and initial cutover. Record scorer identity and
version with every decision so affected reports can be audited. Roll back by
switching to `legacy` without changing persisted report/event schemas; do not
delete the new feature state or rewrite past decisions. Remove the flag and
legacy code only after the rollback window closes and production evidence is
approved.

Phase 11 performs none of these live changes.
