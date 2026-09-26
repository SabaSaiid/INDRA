# NLP v3 synthetic development record

## Decision

Phase 18 produced and froze `nlp-classifier-v3-synthetic-development` for
opt-in local development inference. The exact status is
`DEVELOPMENT_ONLY_SYNTHETIC`; production validation is `NOT_VALIDATED`, and
the model is neither the configured default nor connected to the live backend.

No pretrained model, open-weight model, external embedding, hosted API,
network access, or runtime download was used. The model consists only of
project-fitted TF-IDF state and multinomial logistic-regression parameters
serialized as JSON.

## Dataset binding and isolation

- Dataset ID: `indra-nlp-project-synthetic-v1`
- Dataset version: `synthetic-nlp-100k-v1`
- Dataset SHA-256:
  `6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76`
- Generator version: `synthetic-nlp-generator-v1`
- Generator seed: `170017`
- Training rows: 80,000
- Validation rows: 10,000
- Protected synthetic-test rows: 10,000
- Training split SHA-256:
  `9ebe62d97a1a14d2ad114cd5a8ccb814442cddac739d55c8633d4303f231073e`
- Validation split SHA-256:
  `4405d3083c15b13fff47ebb773e0321f0bebdca6d22f18127af6427d0f4150a6`
- Test split SHA-256:
  `cea06fa366c4de7387c1ed89e92f795071cdc8aff8c98a74a7ce492c9ab6033b`

Registry, source bytes, Phase 17 manifest/report/scenario hashes, generator
metadata, row counts, split hashes, validation result, and leakage result are
checked before training. Any dataset-byte mismatch raises the stable reason
`TRAINING_BLOCKED_DATASET_HASH_MISMATCH`. The general production training gate
is also run and remains closed because this dataset is synthetic and lacks
split-scoped human approvals. The Phase 18 exception is scoped only to
synthetic development and cannot emit a production status.

Split membership comes from the generator and is not reassigned. Cross-split
base-template-family, parameter-combination, and scenario-family overlap is
zero. The selection path receives only a test descriptor containing count,
ordered IDs, and hash. It cannot receive test text, labels, vectors, or
metrics. The test is loaded only after configuration, calibration, model,
manifest, and golden evidence are frozen.

## Controlled search and selection

Eleven named candidates cover character n-grams 3–5, 2–5, and 3–6; word
n-grams 1–2; character/word weights 1.0/1.0, 1.25/0.75, and 1.5/0.5;
`C` values 0.25, 0.5, 1.0, and 2.0; and unweighted versus balanced class
weighting. Every TF-IDF vocabulary and IDF vector is fitted on training rows
only. Validation and test perform sparse transform only.

Selection maximizes validation macro F1 subject to NOT_RELEVANT recall at
least 0.80, then uses NOT_RELEVANT recall, hard-negative macro F1, minimum
language macro F1, declared deterministic rank, and candidate ID as stable
tie-breakers.

The selected candidate is `B_EQUAL_NONE_C1`:

- character TF-IDF n-grams 2–5, cap 60,000;
- word TF-IDF n-grams 1–2, cap 20,000;
- equal character/word weights;
- logistic regression with `lbfgs`, `C=1.0`, no class weighting;
- seed `170017`;
- 25,886 character plus 8,031 word features (33,917 total).

The balanced counterpart tied exactly. The supported conclusion is
`NO_MEASURED_VALIDATION_BENEFIT_FROM_BALANCED`, not that class weighting is
generally ineffective.

## Validation results

Overall validation accuracy is `0.8930`, macro precision
`0.9015925832`, macro recall `0.8930`, macro F1 `0.8925588427`, and
NOT_RELEVANT recall `0.9150`.

| Language | Rows | Accuracy | Macro F1 | NOT_RELEVANT recall |
|---|---:|---:|---:|---:|
| English | 3,333 | 0.9252925293 | 0.9254648388 | 0.9640179910 |
| Hindi | 3,334 | 0.8389322136 | 0.8353235362 | 0.8455772114 |
| Hinglish | 3,333 | 0.9147914791 | 0.9148434708 | 0.9354354354 |

| Noise | Rows | Accuracy | Macro F1 | NOT_RELEVANT recall |
|---|---:|---:|---:|---:|
| NONE | 3,333 | 0.8547854785 | 0.8521203851 | 0.9354354354 |
| LOW | 3,334 | 0.9286142771 | 0.9287782684 | 0.9640179910 |
| MEDIUM | 3,333 | 0.8955895590 | 0.8949690526 | 0.8455772114 |
| HIGH | 0 | `NO_SAMPLES` | `NO_SAMPLES` | `NO_SAMPLES` |

The 2,000 validation hard negatives have accuracy `0.5815`, macro F1
`0.5477122049`, and NOT_RELEVANT recall `0.6475`. Required distinction
accuracies are urban-flood versus river-breach `0.1475`, cloudburst versus
urban-flood `1.0`, cyclone versus urban-flood `0.965`, and weather mention
versus actual event `0.6475`. Full class and generator-type reports remain in
the machine-readable development manifest.

Validation reports all 45 held-out base-template families and six realized
structure families separately. Base-template macro F1 spans `0.0` to `1.0`;
the worst family, `validation-urban-flood-hi-hard-01` (134 rows), has accuracy
and macro F1 `0.0`. Realized-structure macro F1 spans `0.8676324960` to
`0.9144635880`. These poor localized results are retained even though the
overall validation result passes the development criterion.

Validation-only scalar temperature fitting selected
`0.39154547863530537` within the declared search bounds, with status
`INTERIOR_OPTIMUM`. Log loss changed `0.4774532639 -> 0.2834935071`, Brier
score `0.2186512686 -> 0.1553599640`, and ECE
`0.2023368720 -> 0.0257877412`. No bound was expanded and no test probability
was used to fit calibration.

## One-shot protected synthetic test

The final receipt was claimed before loading test rows. It records one
`FINAL_UNTOUCHED_TEST_EVALUATION`, transform-only feature use, no test fitting,
no calibration on test, no retraining, and no post-test configuration change.
Subsequent evaluation requests fail before test loading.

| Metric | Final result |
|---|---:|
| Accuracy | 0.9359 |
| Macro precision | 0.9368249631190861 |
| Macro recall | 0.9359 |
| Macro F1 | 0.9359267894270392 |
| NOT_RELEVANT recall | 0.936 |
| Log loss | 0.2009070683 |
| Brier score | 0.1013458939 |
| ECE | 0.0626650461 |

Per-class F1 is `0.9626955475` CLOUDBURST, `0.9759344598`
CYCLONE_INUNDATION, `0.9514612452` NOT_RELEVANT, `0.8822645291`
RIVER_BREACH, and `0.9072781655` URBAN_FLOOD.

| Language | Rows | Accuracy | Macro F1 | NOT_RELEVANT recall |
|---|---:|---:|---:|---:|
| English | 3,334 | 0.9289142172 | 0.9288706618 | 0.8785607196 |
| Hindi | 3,333 | 0.9321932193 | 0.9330825674 | 0.9834834835 |
| Hinglish | 3,333 | 0.9465946595 | 0.9467145850 | 0.9460269865 |

All 10,000 rows are in the deliberately held-out `HIGH` noise stratum; its
accuracy and macro F1 equal the overall values. `NONE`, `LOW`, and `MEDIUM`
have explicit `NO_SAMPLES` results, never invented zero metrics.

The 2,000 final hard negatives have accuracy `0.8310`, macro precision
`0.8410781388`, macro recall `0.8310`, macro F1 `0.8303691026`, and
NOT_RELEVANT recall `0.9975`. Required distinction accuracies are urban-flood
versus river-breach `0.69125`, cloudburst versus urban-flood `1.0`, cyclone
versus urban-flood `0.775`, and weather mention versus actual event `0.9975`.

All 45 held-out base-template families and all six realized structure families
are reported. Base-template macro F1 ranges from `0.5543478261` to `1.0`; the
worst family is `test-urban-flood-hi-hard-01` (133 rows, accuracy
`0.3834586466`). Realized-family macro F1 ranges from `0.9222274164` to
`0.9435178029`. There were 641 errors. The largest directed confusions were
URBAN_FLOOD to RIVER_BREACH (171), RIVER_BREACH to URBAN_FLOOD (151),
RIVER_BREACH to CLOUDBURST (74), and NOT_RELEVANT to CLOUDBURST (72).

## Golden regression and comparison

The unchanged ten-scenario v1 golden suite still passes its exact historical
snapshots. Running v3 on those same existing fixtures passes typed schema,
component status, version-map, JSON round-trip, repeat determinism,
no-network, event-lifecycle, duplicate/anomaly semantics, and all documented
cross-component invariants. Four v3 outputs differ from v1 in model-dependent
labels/confidences and resulting event grouping; those differences are
recorded explicitly rather than misrepresented as exact v1 equivalence.

NLP v2 is historical context only. The v3 report marks the comparison
`NOT_DIRECTLY_COMPARABLE` because model selection, dataset size and source,
split construction, noise regimes, template families, and protected test are
different.

## Frozen evidence

- Artifact SHA-256:
  `7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca`
- Development-manifest SHA-256:
  `4d8f580b2c6cc4a446ce7c8b3e2bb7018806480171d7ef30b2c551d5e12b7392`
- Frozen-configuration SHA-256:
  `57af7a08092fad8a5c6efee3e41b8ce315b56ca0a25408d675c223ddb51ebe9b`
- Golden-report SHA-256:
  `511c3ccf155bd46c57059b8efd5dbf11c360295c2dc2061948dd488f059ac333`
- Final-metrics SHA-256:
  `033db50927e45a583f7bcdd9fc6e5ec6577093fc955a2d79d6c65dd7923c3394`
- Error-report SHA-256:
  `a3d8d7c76deffcf7d273414edb2898fb35c855f6514bd3f248e9996f54896121`
- Final-receipt file SHA-256:
  `ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b`

## Limitations and prohibited claims

The generator is project-authored and finite. Its labels follow generator
rules, not independent human judgment. Even held-out templates, combinations,
scenario families, and high-noise transformations remain inside that designed
synthetic world. The test therefore cannot establish behavior on citizen
language, rare events, code-switching outside templates, novel geography,
operational drift, adversarial inputs, accessibility variants, or real class
prevalence. Temperature scaling may be over-optimistic outside the generator.

The artifact must not be described as production ready, field validated,
human validated, representative, safety validated, or production calibrated.
Promotion requires a separate provenance-complete human-adjudicated corpus,
grouped leakage-safe splits, an independent field test, explicit approvals,
production calibration, backend integration review, and all release-gate
evidence.
