# Backend TODO — `INDRA/backend`

Aditya's actionable backlog, backend-only. Not yet run past the team — a starting proposal.

## P0 — Wire the real pipeline

- [ ] In `app/workers/report_consumer.py`, replace the raw relay with the real flow:
  1. Receive raw report from Kafka.
  2. `DedupService.is_duplicate()` against recent reports in the same area/time window — drop or flag if duplicate.
  3. Persist the raw report (`raw_reports` table) if not a duplicate.
  4. `GeoClusteringService.cluster_unassigned_reports()` + `assign_h3_cells()` to group it with related reports.
  5. `FusionEngine.compute_receipt()` → `assign_quadrant()` → `determine_review_status()` on the resulting cluster.
  6. Persist a `verified_events` row with the receipt.
  7. Broadcast the real verified event over `/ws/events`, not the raw message.
- [ ] Write an integration test: push a synthetic report onto `indra.raw.reports`, assert a `verified_events` row appears with a non-random confidence score.
- [ ] Confirm Alembic migrations are applied to the live DB (`alembic current`, `alembic upgrade head` if not).

## P1 — Replace random scoring with real signals

- [ ] `weather_station` factor: read from `station_readings` table or live Open-Meteo call instead of `random.uniform`.
- [ ] `report_density` factor: count actual independent (deduplicated) reports in the cluster.
- [ ] `spatial_coherence` factor: derive from DBSCAN cluster tightness (e.g. max pairwise distance vs. eps), not random.
- [ ] `vision_analysis` factor: either wire a real image classifier or mark the factor explicitly as "offline" in the receipt (don't fake a score).
- [ ] `source_reliability`, `anomaly_detection`: same — real signal or explicit "offline" marker.

## P2 — Fill in unknowns from `backend-status.md`

- [ ] Read `app/api/auth.py` and `app/core/security.py` fully; determine if RBAC (`OperatorRole`: COMMANDER/ANALYST/ADMIN/CITIZEN/FIELD_RESPONDER) is actually enforced anywhere or just defined as an enum.
- [ ] Check whether any code path calls Open-Meteo/OpenWeather; if not, decide whether that's P1 work or explicitly out of scope for now.
- [ ] Check `models/audit_logs.py` — does anything write real audit/provenance records (hash chains), or is it schema-only?

## P3 — Hygiene

- [ ] Once the pipeline is wired, update `backend-status.md` to move items from "broken/disconnected" to "working."
- [ ] Keep `api-requirements.md` in sync with any new/changed endpoint added while doing the above.

## Explicitly not doing (flag to team instead of touching)

- Frontend changes to consume new response shapes — describe the needed shape, let the frontend owner implement it.
- Adding MinIO/S3 to `docker-compose.yml` — infra decision, raise it rather than deciding unilaterally.
