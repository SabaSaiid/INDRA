# Phase 14 NLP development validation

Status: `DEVELOPMENT_ACCEPTED / DEVELOPMENT_ONLY / NOT_PRODUCTION_READY`

This record describes the Phase 14 experiment over the existing synthetic
`reports_v1.csv` corpus. It is development evidence only. The default NLP
configuration and live backend remain on the pre-existing v1 path; the v2
artifact is not activated by this phase.

## Protected protocol

The registered source file SHA-256 is
`3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d`.
Its existing 210 `train` rows were sorted by record ID and divided with
event-label stratification, `random_seed=42`, and a validation fraction of
`0.20`. The split version is `nlp-development-split-v1`.

| Partition | Rows | SHA-256 |
|---|---:|---|
| Development train | 168 | `61b648cbca7a9d87bde7421ac14a00d1d7750b35e4a18d11f71340454b30a268` |
| Development validation | 42 | `3c29e91f4243e0b5f543270e3df3b3b8d06e546de8395f83d8026d02d0a70101` |
| Existing final test | 90 | `6082b1a16b0326e7932f5610ce99c873112c216b4c422f9a98dda360b0166813` |

The 90 final rows retained their source order. Configuration selection accepts
only a `SelectionDataset` containing development train and validation records;
it has no final-test parameter and performs no dataset load. An automated test
replaces the dataset loader with a failing sentinel and proves that selection
still completes. Final access is in a separate function that creates an
exclusive receipt before loading protected examples.

The completed receipt records one invocation, no post-freeze configuration
change, no post-evaluation retraining, and no permitted rerun. Its final-test
label is `FINAL_UNTOUCHED_TEST_EVALUATION`.

## Controlled search and selection

Twelve configurations were enumerated explicitly. This was not a generated or
open-ended grid.

| ID | Character n-grams | Character / word weight | Class weight | C | Validation macro F1 | Validation NOT_RELEVANT recall |
|---|---|---:|---|---:|---:|---:|
| A_EQUAL_NONE_C1 | 3–5 | 1.00 / 1.00 | None | 1.0 | 0.6851 | 0.6250 |
| A_EQUAL_BALANCED_C1 | 3–5 | 1.00 / 1.00 | balanced | 1.0 | 0.6851 | 0.6250 |
| B_EQUAL_NONE_C1 | 2–5 | 1.00 / 1.00 | None | 1.0 | 0.6851 | 0.6250 |
| B_EQUAL_BALANCED_C1 | 2–5 | 1.00 / 1.00 | balanced | 1.0 | 0.6851 | 0.6250 |
| C_EQUAL_NONE_C1 | 3–6 | 1.00 / 1.00 | None | 1.0 | 0.6851 | 0.6250 |
| C_EQUAL_BALANCED_C1 | 3–6 | 1.00 / 1.00 | balanced | 1.0 | 0.6851 | 0.6250 |
| D_CHAR125_NONE_C1 | 3–5 | 1.25 / 0.75 | None | 1.0 | 0.7106 | 0.7500 |
| D_CHAR125_BALANCED_C1 | 3–5 | 1.25 / 0.75 | balanced | 1.0 | 0.7106 | 0.7500 |
| E_WORD125_NONE_C1 | 3–5 | 0.75 / 1.25 | None | 1.0 | 0.7106 | 0.6250 |
| E_WORD125_BALANCED_C1 | 3–5 | 0.75 / 1.25 | balanced | 1.0 | 0.6861 | 0.6250 |
| F_EQUAL_NONE_C0_5 | 3–5 | 1.00 / 1.00 | None | 0.5 | 0.6851 | 0.6250 |
| G_EQUAL_NONE_C2 | 3–5 | 1.00 / 1.00 | None | 2.0 | 0.6851 | 0.6250 |

The frozen rule first requires validation NOT_RELEVANT recall of at least
`0.80` and macro F1 of at least `0.75`, then maximizes macro F1. If no model
meets the recall constraint, it maximizes recall among macro-F1-preserving
models. If no model preserves the macro-F1 floor, it maximizes macro F1, then
NOT_RELEVANT recall, accuracy, and finally configuration ID.

No candidate met either validation floor. The recorded selection path is
`NO_CONFIGURATION_MET_MACRO_F1_PRESERVATION_FLOOR`. The fallback selected
`D_CHAR125_BALANCED_C1`: character TF-IDF 3–5, word TF-IDF 1–2, weights
`1.25 / 0.75`, balanced logistic regression, and `C=1.0`. The unweighted and
balanced versions produced exactly the same validation labels and metrics, so
there is no evidence that balanced weighting is superior; balanced won only
the final deterministic tie-break.

The valid same-protocol recreation of the previous 3–5/equal/unweighted
configuration scored macro F1 `0.6851` and NOT_RELEVANT recall `0.6250`. The
selected configuration improved those validation values to `0.7106` and
`0.7500`. The committed v1 artifact itself cannot be evaluated validly on the
new validation rows because it was trained on all 210 source-development rows.

## Multilingual validation and errors

The selected model fit the development training rows perfectly. That result is
training fit, not generalization evidence.

| Validation subgroup | Status | Rows | Accuracy | Macro precision | Macro recall | Macro F1 |
|---|---|---:|---:|---:|---:|---:|
| English | DATA_AVAILABLE | 27 | 0.8519 | 0.8850 | 0.8467 | 0.8457 |
| Hindi | INSUFFICIENT_DATA | 4 | — | — | — | — |
| Hinglish | DATA_AVAILABLE | 11 | 0.4545 | 0.4500 | 0.5333 | 0.4276 |

There were 12 validation misclassifications, represented in both the
false-positive and false-negative views. Five involved NOT_RELEVANT, two were
Hindi examples, and six were Hinglish examples. The most frequent directed
confusions were `RIVER_BREACH -> CYCLONE_INUNDATION` (2) and
`URBAN_FLOOD -> RIVER_BREACH` (2). The deterministic error artifact contains
every example grouped by actual and predicted class; no external interpreter
was used.

## Validation-only calibration

Scalar temperature scaling was fitted on validation logits only. It did not
change predicted labels.

| Measure | Before | After candidate |
|---|---:|---:|
| Multiclass log loss | 1.2184 | 0.7834 |
| Multiclass Brier score | 0.6111 | 0.3974 |
| Five-bin expected calibration error | 0.3845 | 0.1117 |

The frozen temperature is `0.2500000093`, at the lower edge of the evaluated
range. This and reuse of the small selection split make the calibration result
fragile. Its only valid status is `CALIBRATED_ON_VALIDATION`; it is not
production calibration.

## Frozen artifact

The model is `nlp-classifier-v2-development` using feature version
`nlp-features-v2` and preprocessing version `nlp-text-normalization-v1`.
The JSON artifact SHA-256 is
`ec827431e59116b534c01aba5359410c1a241e8b5c98534339c0ef0d126c560b`.
The frozen-configuration SHA-256 is
`450bb35b4a8c82b90a13df0ee978bd7abd63345b084c3b1a4d76ec933b7567ab`.
The artifact records all dataset/split hashes, feature and classifier settings,
calibration state, seed, timestamp, and Python, NumPy, SciPy, and scikit-learn
versions.

## One-shot final result

The final result was produced once after freezing and is marked
`FINAL_UNTOUCHED_TEST_EVALUATION`.

| Metric | Result |
|---|---:|
| Accuracy | 0.8000 |
| Macro precision | 0.8181 |
| Macro recall | 0.8000 |
| Macro F1 | 0.8024 |
| NOT_RELEVANT recall | 0.8333 |
| Flood classes predicted NOT_RELEVANT | 4 |

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| CLOUDBURST | 0.9286 | 0.7222 | 0.8125 | 18 |
| CYCLONE_INUNDATION | 1.0000 | 0.8889 | 0.9412 | 18 |
| NOT_RELEVANT | 0.7895 | 0.8333 | 0.8108 | 18 |
| RIVER_BREACH | 0.7059 | 0.6667 | 0.6857 | 18 |
| URBAN_FLOOD | 0.6667 | 0.8889 | 0.7619 | 18 |

The confusion-matrix label order is CLOUDBURST, CYCLONE_INUNDATION,
NOT_RELEVANT, RIVER_BREACH, URBAN_FLOOD:

```text
13  0  1  2  2
 0 16  1  1  0
 0  0 15  1  2
 1  0  1 12  4
 0  0  1  1 16
```

| Final subgroup | Status | Rows | Accuracy | Macro precision | Macro recall | Macro F1 |
|---|---|---:|---:|---:|---:|---:|
| English | DATA_AVAILABLE | 67 | 0.8507 | 0.8778 | 0.8457 | 0.8515 |
| Hindi | INSUFFICIENT_DATA | 8 | — | — | — | — |
| Hinglish | DATA_AVAILABLE | 15 | 0.6667 | 0.7167 | 0.7133 | 0.6800 |

All unchanged development gates passed: macro F1 `>=0.75`, NOT_RELEVANT
recall `>=0.80`, and flood-to-NOT_RELEVANT errors `<=4`. The resulting status
is `DEVELOPMENT_ACCEPTED`.

The historical v1 final-test metrics are retained only as a non-comparable
reference: macro F1 `0.8105` and NOT_RELEVANT recall `0.7778`. They were not
used for selection.

## Limitations and production status

- The corpus is synthetic and only 300 rows.
- No incident/group key exists, so event-family independence is unproven.
- Validation Hindi support is four rows; final Hindi support is eight rows.
- Hinglish validation performance is weak.
- Validation selection and calibration share the same small holdout.
- The calibration optimum touched its configured search boundary.
- No real-world, field, temporal, or independent multilingual validation is
  present.

The production status remains `NOT_PRODUCTION_READY` and production validation
remains `NOT_VALIDATED`. No pretrained model, open-weight model, external API,
network access, runtime download, or live-backend change was used.
