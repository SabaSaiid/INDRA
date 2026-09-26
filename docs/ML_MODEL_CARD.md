# INDRA frozen AI/ML model card

All six entries are **synthetic-development validated**, not field or production validated. The Phase 24 freeze manifest is `backend/app/ml/artifacts/ai_ml_final_freeze_manifest.json`, SHA-256 `f800014d825d5a20b3eaae8856efa03eb14abf0bc3872ac6fc6471c2b074219d`. Hashes below are file SHA-256 values recorded there and rechecked during Phase 25R.

| Component / version | Method and output | Frozen artifact | SHA-256 |
| --- | --- | --- | --- |
| NLP / v3 | Locally fit character/word TF-IDF linear classifier; `URBAN_FLOOD`, `RIVER_BREACH`, `CLOUDBURST`, `CYCLONE_INUNDATION`, `NOT_RELEVANT` | `nlp_classifier_v3.json` | `7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca` |
| Duplicate / v1 | Locally fit frozen text-feature matcher, not MiniLM | `duplicate_matcher_v1.json` | `85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b` |
| Event / v1 | Deterministic heuristic grouping, **not** a learned classifier; complete-link, spatial, temporal, and type constraints; independent-report requirement | `event_grouping_v1.json` | `10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973` |
| Credibility / v1 | Local logistic regression trained on `AUTHENTIC` and `MISLEADING`; `UNCERTAIN` also emitted as an output state; risk evidence, **not truth probability** | `credibility_v1.json` | `8bbd16727be2ba639e031db37a84f0ca92a2a14220fd1819e45dbf689bab7052` |
| Image / v1 | Locally trained `scratch-cnn-v2-dual-pool`; `FLOODED_SCENE`, `HEAVY_RAIN_VISUAL`, `STANDING_WATER`, `STORM_DAMAGE`, `NORMAL_SCENE` | `image_model_v1.pt` | `6daf6e9dc41783c7d30b19b5c0cc2a0fb20871733f9ab714a7b99552424f9248` |
| Anomaly / v1 | `STATISTICAL_ANOMALY_BASELINE` plus `LOCAL_SCRATCH_DUAL_LOGISTIC`; separates `DATA_QUALITY_ANOMALY` from `WEATHER_BEHAVIOR_ANOMALY` | `anomaly_model_v1.json` | `3fdc354af80224bfe11dc23b6c5fccd629f44daf45efb9220a4cd9406004eceb` |

The duplicate matcher also binds `duplicate_feature_state_v2.json`, SHA-256 `d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731`. Artifact authorization uses the local manifest and hashes; no runtime model download or pretrained/open-weight checkpoint is permitted. PyTorch is a local library for the scratch CNN, not a source of pretrained weights.

The existing `event_classifier_v1.joblib` and its metrics are quarantined legacy artifacts, not the frozen Phase 18 NLP model or the Phase 20 event grouping algorithm. The broader 14-class design and Isolation Forest/classical-image proposals are historical plans. No component has field calibration or production-accuracy evidence. Dataset provenance and hashes are in [data card](ML_DATA_CARD.md); current gate results are in [validation report](ML_VALIDATION_REPORT.md).
