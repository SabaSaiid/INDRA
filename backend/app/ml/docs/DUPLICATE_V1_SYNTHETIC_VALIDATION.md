# Phase 19 duplicate matcher synthetic validation

## Scope and dataset decision

The dataset registry contained no duplicate dataset that was both
human-adjudicated and explicitly approved for training, validation, and test.
The recorded decision is therefore:

- `USE_IT = FALSE`
- `GENERATE_SYNTHETIC_DUPLICATE_DATASET = TRUE`

Phase 19 binds only `indra-duplicate-project-synthetic-v1`, version
`synthetic-duplicate-100k-v1`, SHA-256
`ad664bf69755a141f44c82615e7653f28ae5abadc028cb50d6566ee2f13e7231`.
The source is `PROJECT_AUTHORED / SYNTHETIC / DEVELOPMENT_ONLY`. Labels come
directly from generator scenario identity, never from the matcher, a model,
or a threshold. The normal production training gate remains closed because
the dataset is synthetic, non-human-adjudicated, and has no split approvals.

## Dataset construction and integrity

The deterministic generator uses seed `190019` and produces 100,000 pairs:

| Split | Pairs | Duplicate | Not duplicate | Uncertain |
|---|---:|---:|---:|---:|
| Train | 70,000 | 31,500 | 31,500 | 7,000 |
| Validation | 15,000 | 6,750 | 6,750 | 1,500 |
| Test | 15,000 | 6,750 | 6,750 | 1,500 |
| Total | 100,000 | 45,000 | 45,000 | 10,000 |

Duplicate scenarios are `EASY_DUPLICATE`, `NEAR_DUPLICATE`,
`PARAPHRASED_DUPLICATE`, `MINOR_TYPO_DUPLICATE`,
`TIME_VARIATION_DUPLICATE`, and
`LOCATION_VARIATION_DUPLICATE_WHEN_VALID`. Hard negatives are
`SAME_WEATHER_DIFFERENT_EVENT`, `SAME_LOCATION_DIFFERENT_TIME`,
`SAME_EVENT_TYPE_DIFFERENT_EVENT`, `SAME_TEXT_DIFFERENT_EVENT`,
`SAME_SOURCE_DIFFERENT_EVENT`, `SPATIALLY_NEAR_TEMPORALLY_FAR`, and
`TEMPORALLY_NEAR_SPATIALLY_FAR`. Two boundary scenarios supply uncertain
examples.

English, Hindi, and Hinglish are balanced. Event type and source type are
balanced within every scenario so neither acts as a class-label proxy. Split
locations, scenario families, report IDs, incident IDs, and parameter
combinations are generator-separated. Custom and registry validation report
zero cross-split report, incident, scenario-family, parameter-combination,
exact-text, unordered-pair, or reversed-pair leakage. The test split contains
15,000 held-out parameter combinations.

## Feature-state protection

The existing `duplicate_feature_state.json` remains byte-for-byte unchanged at
SHA-256
`6d8aad9701700686f42deefa72ed8074ede836a4e9f0d2457db2c054636c2cdc`.
Phase 19 creates `duplicate_feature_state_v2.json`, version
`duplicate-feature-state-v2`, from exactly 140,000 train report texts. Its
training-corpus SHA-256 is
`fcabdcf1c0bddc7fb9c1189a4897e1cc49f7ff5423b61a36b4510ab92e5e7b61`;
its artifact SHA-256 is
`d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731`.
Validation and test call `transform()` only. No validation or test text is
used to fit IDF or vocabulary state.

The feature configuration remains character TF-IDF 3–5 grams, word TF-IDF
1–2 grams, and deterministic Unicode-preserving normalization. Matcher weights
are character `0.35`, word `0.30`, edit `0.15`, geographic `0.10`, and temporal
`0.10`.

## Validation-only boundary selection

The current default `0.55` text threshold, `0.70` combined threshold, 1 km
gate, and 15 minute gate achieved validation precision `1.0`, recall
`0.6608888889`, F1 `0.7958255285`, FPR `0.0`, and FNR `0.3391111111`.
They remain the unchanged default and retain `PROVISIONAL / UNVALIDATED`
status.

Phase 19 searched bounded text, combined, geographic, and temporal grids using
validation only. It selected the opt-in development configuration:

- text threshold: `0.60`
- combined threshold: `0.65`
- geographic candidate gate: `5.0 km`
- temporal candidate gate: `30.0 minutes`
- threshold version: `duplicate-thresholds-v1-synthetic-validation`
- status: `VALIDATION_SELECTED_SYNTHETIC_DEVELOPMENT`

On 13,500 binary validation pairs, with 1,500 uncertain rows excluded, this
configuration produced precision `0.9882869693`, recall `1.0`, F1
`0.9941089838`, FPR `0.0118518519`, FNR `0.0`, and average precision PR-AUC
`0.9999926685`. There were 80 false duplicates and no missed duplicates.

The score remains `SIMILARITY_EVIDENCE_NOT_PROBABILITY`. Raising the combined
threshold to `0.70` reduced validation FPR to `0.0001481481` but reduced recall
to `0.9004444444`; at `0.75`, precision reached `1.0` while recall fell to
`0.6309629630`. This tradeoff is preserved rather than hidden.

## Validation-only ablation

| Signal configuration | Selected threshold | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Text only | 0.67 | 0.6753 | 0.9920 | 0.8036 |
| Geo only | 0.81 | 0.6363 | 1.0000 | 0.7777 |
| Time only | 0.53 | 0.7777 | 1.0000 | 0.8750 |
| Text + geo | 0.68 | 0.6986 | 0.9994 | 0.8223 |
| Text + time | 0.68 | 0.8010 | 0.9847 | 0.8834 |
| Text + geo + time | 0.71 | 0.8049 | 0.9680 | 0.8789 |
| Edit + text | 0.64 | 0.6629 | 0.9944 | 0.7955 |
| Full model | text 0.60 / combined 0.65 | 0.9883 | 1.0000 | 0.9941 |

The full two-threshold candidate-gated decision materially outperforms each
single-score ablation on this generator. This is synthetic scientific evidence,
not proof of deployment behavior.

## Calibration, multilingual results, and stability

Validation binary pairs were deterministically divided by pair-ID SHA-256
parity into 6,807 calibration-fit and 6,693 calibration-check rows. Versioned
Platt scaling (`duplicate-score-platt-v1`) reduced check log loss from
`0.1806312422` to `0.0614251388` and Brier score from `0.0495415753` to
`0.0137291895`. It is retained as
`SELECTED_VALIDATION_ONLY_SYNTHETIC_DEVELOPMENT`, does not affect the duplicate
decision, and is not production calibration.

Validation F1 by language is English `1.0`, Hindi `0.9825327511`, and
Hinglish `1.0`. All 80 validation false duplicates are Hindi
`SAME_WEATHER_DIFFERENT_EVENT` hard negatives. Event-type and source-type
prevalence are approximately balanced, and the global threshold has no large
diagnostic divergence flags across language, event type, source type,
distance bucket, or time bucket. No subgroup-specific thresholds were created.

## One-shot final synthetic test

The feature state, preprocessing, weights, gates, thresholds, decision logic,
and selected calibration were frozen before test access. The protected test
descriptor SHA-256 is
`29a391c08c15d149c8e1a76fd31f8b4a6bb7f2ba92ec1feedbe21700d44c49ef`.
Exactly one invocation is recorded by `duplicate_v1_final_test_receipt.json`;
the evaluator refuses any rerun before loading test rows.

On 13,500 binary test pairs, with 1,500 uncertain rows excluded:

| Metric | Final synthetic test |
|---|---:|
| Duplicate prevalence | 0.5000000000 |
| Precision | 0.9851116625 |
| Recall | 0.9998518519 |
| F1 | 0.9924270274 |
| False-positive rate | 0.0151111111 |
| False-negative rate | 0.0001481481 |
| PR-AUC / average precision | 0.9999032951 |
| True duplicate / false duplicate | 6,749 / 102 |
| True non-duplicate / missed duplicate | 6,648 / 1 |

Final English, Hindi, and Hinglish F1 are `0.9993334814`, `0.9782608696`, and
`1.0`. The 102 false duplicates comprise 100 Hindi and two English
`SAME_WEATHER_DIFFERENT_EVENT` hard negatives. The one missed duplicate is an
English `LOCATION_VARIATION_DUPLICATE_WHEN_VALID` example. No retraining or
retuning followed the test.

## Local performance observation

The train-only directed-comparison benchmark measured 100, 1,000, 10,000, and
100,000 candidates. At 100,000, feature transformation took `36.7599 s`,
similarity computation `41.6665 s`, and decision logic `1.7968 s` on this host.
These are local engineering observations only; they exclude retrieval,
persistence, network, and live-service overhead and are not production
throughput or latency claims.

## Governance and limitations

`duplicate_matcher_v1.json` is opt-in and hash-authorized; it does not replace
the default matcher configuration or modify the live backend. Its SHA-256 is
`85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b`.
NLP v3 hashes are unchanged. `backend/app/services/dedup.py`, MiniLM, Kafka,
PostgreSQL, frontend, and API code were not modified.

No pretrained model, open-weight model, embedding, Sentence Transformer,
external AI API, remote data, model download, or network access is used.
Synthetic scenario coverage cannot establish citizen-report representativeness,
field precision, field calibration, geographic robustness, temporal drift, or
production safety. Therefore `PRODUCTION_VALIDATION = NOT_VALIDATED` and the
production status remains `NOT_PRODUCTION_READY`.
