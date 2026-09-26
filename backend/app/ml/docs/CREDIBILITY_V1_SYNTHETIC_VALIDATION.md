# Phase 21 credibility-risk synthetic validation

## Status and interpretation boundary

`credibility-v1-synthetic-development` is an opt-in local development model
evaluated only on a project-authored synthetic benchmark. Its semantic target
is `MISLEADING_RISK_EVIDENCE`. It is not a truth detector, does not estimate
`TRUTH_PROBABILITY`, and does not establish that a report is factually true or
false. `PRODUCTION_VALIDATION` remains `NOT_VALIDATED`.

The live `credibility.py`/rule path, pipeline, database, Kafka, API, frontend,
NLP v3, duplicate matcher v1, and event grouping v1 were not modified. The
learned artifact is isolated from the live backend.

## Dataset and ground truth

The registered dataset is `indra-credibility-project-synthetic-v1`, version
`synthetic-credibility-100800-v1`:

- provenance: `PROJECT_AUTHORED`;
- kind: `SYNTHETIC`;
- classification: `DEVELOPMENT_ONLY`;
- generator: `synthetic-credibility-generator-v1`;
- seed: `210021`;
- reports: `100,800`;
- labels: 36,000 `AUTHENTIC`, 57,600 `MISLEADING`, and 7,200 `UNCERTAIN`;
- train/validation/test: 70,560 / 15,120 / 15,120;
- composite dataset SHA-256:
  `1ceab01ae23d7c99eec3f98a0bbad479ae5b66b63f56298a5d713d5218140a87`;
- canonical split SHA-256:
  `7142901293a1ac0c0cf5fbc6972168025def9cbdcde8fb27d5ffb46cf352b742`.

Ground truth comes directly from generator scenario identity. No rule score,
detector output, model prediction, keyword decision, external AI, or human
review result creates a label. The 14 scenario families each contribute 7,200
reports:

- `AUTHENTIC_CONSISTENT`;
- `AUTHENTIC_EXTREME_BUT_PLAUSIBLE`;
- `AUTHENTIC_WITH_INCOMPLETE_METADATA`;
- `LEGITIMATE_DUPLICATE`;
- `LEGITIMATE_EVENT_CONFLICT`;
- `CONTRADICTORY_TIME`;
- `CONTRADICTORY_LOCATION`;
- `CONTRADICTORY_EVENT_CONTEXT`;
- `MISLEADING_OMISSION`;
- `MISLEADING_CONTEXT`;
- `REPEATED_COPYING`;
- `IMPOSSIBLE_METADATA`;
- `SOURCE_BEHAVIOR_ANOMALY`;
- `UNCERTAIN_AMBIGUOUS`.

The three additional authentic scenarios are deliberate hard negatives. They
prevent a duplicate relationship, missing metadata, or event conflict from
being synonymous with `MISLEADING`.

## Input isolation and leakage controls

Hidden truth and detector input are separate JSONL files for every split. The
detector schema rejects ground-truth label, scenario, hidden authenticity,
canonical event, report family, template, parameter combination, generated
adjudication, language subgroup, and split. It receives only report text,
time, valid report coordinates, source type/metadata, and project-authored
duplicate observation context available at assessment time.

Families contain four reports and are assigned as units. Canonical event,
report family, split-specific template, and parameter-combination overlap are
all zero across splits. Exact Unicode-NFKC/casefold/whitespace-normalized text
overlap is also zero. Splitting is deterministic and never random by row.

The ordinary production training gate remains closed because the data are
development-only, non-human, and unapproved. A narrower Phase 21 synthetic
development gate verifies exact registered bytes, project authorship, scenario
identity, input isolation, and the hash-bound scalable leakage report. It does
not override or weaken the production gate.

## Features, model selection, and calibration

Only the existing `CredibilityFeatureSnapshot` is used. The five documented
families are text, metadata, duplicate, event, and source evidence. Optional
missingness indicators and deterministic numeric transforms are preprocessing,
not new semantic features. Preprocessing medians and scales are fitted on train
only. No future review or adjudication field is available to the model.

`UNCERTAIN` is not a fitted class. Six bounded binary logistic-regression
configurations fit resolved `AUTHENTIC`/`MISLEADING` training rows. The
validation families are deterministically divided into disjoint model-
selection, calibration, and threshold-selection partitions. The selected
configuration is unweighted logistic regression with `C=10.0`.

Validation-only scalar temperature scaling selected `0.5`. It reduced
synthetic calibration log loss from `0.0000645024` to `0.0000000214`, Brier
score from `0.0000000213` to `0.0`, and 10-bin ECE from `0.0000644917` to
`0.0000000214`. These values are not field calibration.

Validation selected `AUTHENTIC` at probability at or below `0.0000001`,
`MISLEADING` at probability at or above `0.7`, and `UNCERTAIN` between them.
The extremely low authentic cutoff is a synthetic-distribution warning, not a
recommended operational threshold. Any representative real-data calibration
could differ materially.

## Baseline, ablation, and validation

The existing `RULE_BASED_CREDIBILITY_BASELINE` was evaluated separately and
its score remains an uncalibrated risk score. On validation it produced macro
F1 `0.3988699180`, misleading recall `0.1666666667`, misleading precision
`1.0`, false-positive rate `0.0`, and false-negative rate `0.8333333333`.

Validation-only ablation macro F1 values, using fixed comparison thresholds,
were:

| Evidence | Macro F1 |
|---|---:|
| TEXT | 0.3592793858 |
| METADATA | 0.3370920768 |
| DUPLICATE | 0.3608278345 |
| EVENT | 0.2348596750 |
| SOURCE | 0.3870482841 |
| TEXT + METADATA | 0.5588246540 |
| TEXT + DUPLICATE + EVENT | 0.4422637033 |
| FULL | 0.6917678643 |

The ablation comparison does not reuse the final calibrated threshold search,
so its `FULL` value is not the final validation score. After validation-only
calibration and threshold selection, full validation macro F1, misleading
precision, and misleading recall were all `1.0`; FPR and FNR were `0.0`.

## One-shot synthetic holdout

After artifact, preprocessing, calibration, thresholds, and configuration were
frozen, the 15,120-row test was evaluated exactly once. No fitting, calibration,
or selection occurred afterward.

| Metric | Final synthetic test |
|---|---:|
| Accuracy | 1.0 |
| Macro F1 | 1.0 |
| MISLEADING precision | 1.0 |
| MISLEADING recall | 1.0 |
| False-positive rate | 0.0 |
| False-negative rate | 0.0 |
| Log loss | 0.0000000106 |
| Brier score | 0.0 |
| 10-bin ECE | 0.0000000106 |

English, Hindi, and Hinglish each have test macro F1 `1.0`. Every required hard
negative scenario has correct rate `1.0`; authentic extreme, incomplete-
metadata, legitimate-duplicate, and legitimate-event-conflict false-misleading
rates are `0.0`. The test has zero `FALSE_MISLEADING` and zero
`MISSED_MISLEADING` cases, so the corresponding deterministic failure-example
lists are empty rather than fabricated. Validation failure lists are also
retained separately.

Perfect generator-defined results demonstrate that the implementation recovers
the encoded synthetic evidence regimes. They do not measure unrepresented
field ambiguity, coordinated manipulation, source drift, geographic behavior,
annotation disagreement, adversarial adaptation, or factual truth.

## Artifacts and one-shot receipt

`credibility_v1.json` stores the portable linear coefficients, intercept,
feature order/families, train-only preprocessing, validation-only temperature,
abstention thresholds, policy, and exact dataset provenance. Its internal
artifact hash is
`1063a75a1460ab0dc42365a3319790dd594c70a26c98138e9e250fe20a0ab681`;
its file SHA-256 is
`8bbd16727be2ba639e031db37a84f0ca92a2a14220fd1819e45dbf689bab7052`.

The search, calibration, ablation, baseline, validation metrics/errors,
performance, golden, final metrics/errors, and development manifest are
separate hash-bound JSON evidence. The final receipt is
`credibility_v1_final_test_receipt.json`, SHA-256
`d9f3dc044bf57722180ee70fd459f7208233c3e3cd12bac5b35abe557e4c39dc`.
It records invocation count one, prohibits rerun, and confirms that test data
were not used for model selection, preprocessing, calibration, or thresholds.

No pretrained model, open-weight model, embedding service, external API, or
network access is used. Promotion requires representative human-adjudicated
field data, independent grouped splits, a newly governed untouched test,
field calibration, monitoring, and explicit deployment approval. Until then:
`NOT_VALIDATED`.
