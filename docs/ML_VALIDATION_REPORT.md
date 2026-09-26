# INDRA AI/ML validation and release gates

Status: 25 September 2026. These are regression and integrity checks, **not** field-performance claims. Protected Phase 18–23 benchmark evaluations were not rerun, and their receipts were not modified.

| Gate | Observed result |
| --- | --- |
| Isolated environment | Python 3.14.3; pytest 9.1.1; pytest-asyncio 1.4.0; asyncpg 0.31.0; details in `phase25_runtime_environment.json` |
| Backend collection | 698 collected: original 686 plus 12 Phase 26 integration checks |
| Disposable native test stack | PostgreSQL 16.15 / PostGIS 3.4 on `127.0.0.1:5433` (`indra_test`, Alembic `0009_event_location`); Memurai Developer 4.1.2 Redis API 7.2.5 on `127.0.0.1:6379`; neither is a production service |
| Full backend suite | 690 passed, 8 pre-existing repository-declared skips, 0 failed, 0 deselected; includes real PostgreSQL/PostGIS and five Redis tests |
| AI/ML regression | 343 passed, including three Phase 20R governance checks; protected benchmark evaluators were not rerun by pytest |
| MiniLM migration guard | 2 passed; no live MiniLM runtime reference found |
| Socket-denial probes | 2 passed; frozen local inference needs no network |
| ML policy and boundary scans | 93 production ML source files; 0 prohibited-policy imports/calls; 0 infrastructure-boundary violations |
| Frozen artifacts and protected receipts | 19 component artifacts, companions, development manifests, and receipts matched the Phase 24 freeze hashes; Phase 24 manifest SHA-256 matched |
| Phase 25R verification | `PASS`; receipt at `backend/app/ml/artifacts/phase25_backend_verification_receipt.json` |
| Phase 20R synthetic event revalidation | `REVALIDATED` on the new family-disjoint benchmark: 48 test batches / 306 reports, event-match F1 1.0, event-level F1 1.0, false-merge rate 0.0; one protected evaluation |
| Phase 26 six-component backend integration | 12 passed: ten requested scenarios plus database-backed `UnifiedMLResult` and event-receipt persistence |
| Phase 27 release audit | `PASS`: dependency consistency, policy/boundary isolation, frozen/protected hashes, Phase 20R receipts, documentation, source-secret scan, and `git diff --check` |
| Repository release state | `PRE_COMMIT_READY`; no agent commit, push, or merge; **not** production approval |

The earlier blocker inventory at `backend/app/ml/artifacts/phase25_backend_test_infrastructure_blockers.json` is historical evidence of 191 PostgreSQL/PostGIS and five Redis tests that lacked infrastructure. A dedicated native local stack resolved that blocker; those tests were run in the complete backend suite, not mocked or silently skipped. The external Open-Meteo resilience test does not establish live external connectivity.

The previously requested `D:\INDRA\offline\_wheelhouse` and its two named wheel files were absent when rechecked, so their specified SHA-256 values could not be verified. The superseding master task explicitly permitted a one-time PyPI bootstrap of ordinary dependencies; the isolated `.venv` used that route. No model or checkpoint download was authorized or performed.

The old Phase 20 receipt remains historical and immutable. Its original generator and manifests cannot prove template- or parameter-family separation, so that benchmark is still insufficient on its own. Phase 20R is a **new** versioned synthetic benchmark under `data/labelled/events/phase20r_v1/`, with distinct geometric templates and numeric parameter families for train, validation, and test. The preregistration manifest `backend/app/ml/artifacts/event_grouping_phase20r_v1.manifest.json` binds the unchanged frozen Phase 20 configuration, source and dataset hashes, disjoint family/identity audit, deterministic regeneration, and acceptance gates before test evaluation. Generator metadata and canonical labels are absent from detector records. Train and validation each have 48 batches; the sealed test was evaluated exactly once and its receipt is `backend/app/ml/artifacts/event_grouping_phase20r_v1.final_test_receipt.json` (SHA-256 `3b725b0f99e17852e16e3ad41f52dd933b53145364499d27c8ed880d04e0cfbb`). All five predeclared gates passed, so `PHASE_20_EVENT_EVIDENCE=REVALIDATED` **for synthetic development evidence only**. The controlled NLP predictions are fixtures, not field NLP inference; perfect synthetic scores do not establish production validity.

The legacy 300-row `data/labelled/reports_v1.csv` is byte-hashed in the sealed NLP registry as the Windows CRLF checkout (`3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d`), while its older datasheet and classifier-v1 metrics record the Git LF blob (`ce142c3a109365bee6f0e407288b74096e675fe71abcaa1cf3dd90ff732f2745`). Two non-protected backend tests now assert **both** hashes explicitly. No dataset or frozen evidence was edited.

The anomaly synthetic-generator dependence remains `HIGH` (34/62 direct scenario features). Its existing dataset quality report verifies grouped split-family separation, hidden-label isolation, and deterministic replay; feature extraction uses only the detector-visible historical window, while rolling baseline features are prior-only. That prevents an identified metadata/future-window leak, but does not erase generator dependence. `PRODUCTION_VALIDATION=NOT_VALIDATED` for all six components. Phase 26 wires the frozen components as advisory results but does not make their synthetic metrics operational accuracy or allow them to change human-review decisions. The Phase 27 release audit and final manifest record the repository gate separately from production approval.

The frozen image dataset currently includes 100,000 PNG files (about 1.21 GB). It is intentional, not temporary pytest output. The 106,821-byte frozen `image_model_v1.pt` now has a narrow `.gitignore` exception so a manual commit can include the exact hashed checkpoint. Review the large data-file scope before committing; no files were staged or committed by this audit.
