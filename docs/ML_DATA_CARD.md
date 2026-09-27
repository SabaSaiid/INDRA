# INDRA AI/ML data card

The six frozen artifacts were developed from project-controlled synthetic data. Synthetic train/validation/protected-test procedures establish only development evidence; they do not substitute for representative, human-adjudicated operational data. The hashes below are the dataset content hashes recorded by the Phase 24 freeze manifest, not necessarily the SHA-256 of one CSV file.

| Component | Dataset content SHA-256 | Provenance and limitation |
| --- | --- | --- |
| NLP | `6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76` | Project-generated multilingual synthetic templates; five weather/relevance classes, not the full SIH ontology |
| Duplicate | `ad664bf69755a141f44c82615e7653f28ae5abadc028cb50d6566ee2f13e7231` | Project-generated report pairs and hard negatives; field duplicate prevalence unknown |
| Event | `127a506f8deba172140dd33b71a14b84b629ce325c959ba8b9d4c04635f48f0f` | Project-generated event scenarios; original Phase 20 split lacks template/parameter-family separation evidence, addressed by a separate Phase 20R benchmark |
| Credibility | `1ceab01ae23d7c99eec3f98a0bbad479ae5b66b63f56298a5d713d5218140a87` | Project-generated authentic/misleading cases; cannot establish truth in the field |
| Image | `8cc2da10c57accbeff09a166221eb0b3f1df80e431c1810aad095eda0df972ba` | Project-generated image scenes; deployment-camera and real-disaster shift unmeasured |
| Anomaly | `818b82a3c91a2e263e3e2dd684c434f7072a8415135411f982b027d80f9f0546` | Project-generated station windows; 34/62 features had unusually direct scenario discrimination |

Dataset manifests and quality reports live under `data/labelled/<component>/`; development manifests and immutable protected-test receipts live under `backend/app/ml/artifacts/`. The Phase 24 manifest binds artifact, dataset, manifest, and receipt hashes. Its protected receipts are evidence records and must not be rewritten or rerun merely to refresh metrics.

Phase 20 has incident/report/canonical-event split isolation, but no original per-example template-family or parameter-family IDs. The old evidence remains insufficient; no IDs were assigned retroactively. The separate `data/labelled/events/phase20r_v1/` benchmark preregisters nine distinct geometric and numeric family pairs across three splits and sealed detector-input/ground-truth files. Its 48-batch, 306-report one-shot test passed the preregistered gates, giving `PHASE_20_EVENT_EVIDENCE=REVALIDATED` for synthetic development evidence only. See [validation report](ML_VALIDATION_REPORT.md).
