# INDRA local AI/ML model card

> Historical phase-scoped model card. Its earlier "no trained image/anomaly model" statements
> are superseded. The current frozen model inventory and hashes are in `docs/ML_MODEL_CARD.md`.

## Intended use

The Phase 5 NLP classifier is a local development artifact for classifying
short reports into five event/relevance labels. It is available through the
new `InferenceEngine` only as a development result and is not connected to
the live pipeline.

## Method

- character TF-IDF features with 3–5 character n-grams;
- word TF-IDF features with 1–2 word n-grams;
- `sublinear_tf=True`, L2 normalization, and project-owned text
  normalization;
- multiclass logistic regression with regularization selected by stratified
  cross-validation on training rows only.

The complete fitted state is JSON: frozen feature vocabularies/weights,
classifier coefficients, intercepts, classes, versions, and provenance. No
pickle, joblib, checkpoint, pretrained model, open-weight model, runtime
download, or external inference API is used.

## Governance

All models must:

- use only parameters fitted by this project;
- avoid pretrained or open-weight checkpoints;
- avoid runtime downloads and external inference APIs;
- record dataset hash, feature version, preprocessing version, seed, library
  versions, metrics, and policy status;
- pass a manifest validation step before loading;
- provide representative multilingual and field-like evaluation data;
- document intended use, limitations, failure modes, and subgroup performance.

The Phase 5 artifact is registered as `COMPLIANT` for local development
loading. Its current development evaluation has macro F1 above the configured
minimum but NOT_RELEVANT recall below the configured acceptance threshold, so
the artifact status is `EVALUATED`, not `DEVELOPMENT_ACCEPTED`.

## Phase 5 historical development evaluation

On the untouched 90-row test split, the measured accuracy is `0.8111`, macro
precision is `0.8168`, macro recall is `0.8111`, and macro F1 is `0.8105`.
NOT_RELEVANT recall is `0.7778`, below the configured `0.80` gate. Subgroup
accuracy/macro F1 are English `0.8806 / 0.8831`, Hindi `0.6250 / 0.5143`, and
Hinglish `0.6000 / 0.5119`. These are development measurements on synthetic
data, not field-performance estimates.

`PRODUCTION_VALIDATION` is `NOT_VALIDATED`. The synthetic dataset, small Hindi
and Hinglish subgroups, short-text domain, and absence of a real-world holdout
limit any interpretation of the metrics. The legacy classifier remains
excluded from the new engine and must not be promoted.

## Phase 14 development candidate

Phase 14 creates a separate, opt-in `nlp-classifier-v2-development` artifact.
It does not replace the default v1 configuration or change the live backend.
The existing 210 development rows were split deterministically into 168 train
and 42 validation rows; the original 90 test rows remained in source order and
were protected from model selection.

Twelve explicitly enumerated character/word TF-IDF logistic-regression
configurations compared character ranges 3–5, 2–5, and 3–6; equal and explicit
feature weights; no class weighting versus balanced weighting; and a small C
comparison. Selection required validation NOT_RELEVANT recall `>=0.80` and
macro F1 `>=0.75` if possible. No candidate met those validation floors, so the
documented fallback selected the highest macro-F1 candidate:
`D_CHAR125_BALANCED_C1`, with 3–5 character n-grams, 1–2 word n-grams,
character/word weights `1.25/0.75`, balanced class weighting, and `C=1.0`.
Its validation macro F1 was `0.7106` and NOT_RELEVANT recall was `0.7500`.
The equivalent unweighted candidate tied exactly, so the experiment provides
no evidence that balanced class weighting is superior.

Validation-only scalar temperature scaling reduced log loss from `1.2184` to
`0.7834` and five-bin expected calibration error from `0.3845` to `0.1117`.
Its status is `CALIBRATED_ON_VALIDATION`, never `PRODUCTION_CALIBRATED`.

The frozen artifact then received exactly one
`FINAL_UNTOUCHED_TEST_EVALUATION`. Accuracy was `0.8000`, macro precision
`0.8181`, macro recall `0.8000`, macro F1 `0.8024`, and NOT_RELEVANT recall
`0.8333`. All unchanged development criteria passed, producing
`DEVELOPMENT_ACCEPTED`. English final accuracy/macro F1 were
`0.8507 / 0.8515`; Hinglish were `0.6667 / 0.6800`; the eight-row Hindi subset
is `INSUFFICIENT_DATA` under the Phase 14 minimum of ten rows.

This acceptance applies only to synthetic development evidence. Dataset
independence, field representativeness, incident grouping, real multilingual
validation, and production calibration remain absent. The authoritative
methodology, hashes, error analysis, per-class metrics, and limitations are in
`NLP_DEVELOPMENT_VALIDATION.md`. Production remains
`NOT_PRODUCTION_READY / NOT_VALIDATED`.

## Phase 15 annotation infrastructure

NLP v2 remains byte-for-byte `DEVELOPMENT_ONLY_FROZEN`; Phase 15 does not
retrain it, change thresholds, rerun its final evaluation, activate it, or
replace default v1. The source corpus, historical 90-row final test, source
order, and v1/v2 artifacts are guarded by fixed SHA-256 checks.

Phase 15 creates no model. It adds a local human-data path for future
human-data model candidates: blind annotation by default, exact multilingual text
preservation, multiple append-only judgments, explicit adjudication,
uncertainty exclusion, connected event/incident/source-family grouping,
explicit train/validation/test assignment, independent future-test sourcing,
leakage checks, immutable manifests, and Phase 13 registry integration.

Frozen v2 prediction and confidence may be shown only after explicit operator
opt-in. The interface marks them `MODEL SUGGESTION — NOT GROUND TRUTH`, records
that assistance was shown, and still requires a separately entered human
label/state and reason. Model output, rules, keywords, random choices, and LLMs
cannot create ground truth or resolve adjudication.

No real annotated dataset, human-data training run, field metric, or new
production claim exists yet. The current annotation quality evidence is
`DATA_UNAVAILABLE`. Any future human-data model work must begin with a
provenance-known, human-adjudicated, grouping-complete, leakage-safe dataset
that passes explicit registry approval; it must define validation and a new
independent test set without copying or repurposing the historical final 90.

## Phase 16 local corpus enrollment

Phase 16 creates no model and does not invoke NLP v1 or frozen NLP v2. It adds
only deterministic local data governance: explicit-file discovery,
`RawNLPReport` normalization with immutable original text, provenance and
content hashes, fail-closed quality/final-test checks, supplied-only grouping,
and label-free full-population annotation priority queues. No pretrained or
open-weight model, embedding, external API, network service, download,
training, tuning, calibration, or evaluation is used.

Queue modes (`RANDOM`, language/group/source balanced, uncertainty review, and
model-error review) alter priority only. Review modes consume explicit local
report-ID evidence and never calculate a prediction or ground-truth label.
Blind review remains the default. Optional Phase 15 assistance remains a
separate explicit action, visibly non-ground-truth, and cannot populate the
human label.

No local real-world corpus was supplied or enrolled into the repository in
Phase 16. A released human-adjudicated version would enter the registry only
as `CANDIDATE_DATA` and require separate validation and explicit approval.

Phase 17 adds a 100,000-row project-generated synthetic corpus for continued
development. Its scenario-derived labels, generator-level synthetic holdout,
and quality report are reproducible and hash-bound, but the registry keeps it
`DEVELOPMENT_ONLY`. It is not human-adjudicated or field evidence. No NLP v3
model, metric, calibration result, production-validation evidence, or
production-readiness claim is created in Phase 17; NLP v2 remains unchanged.

## Phase 18 synthetic v3 development candidate

Phase 18 creates a separate, opt-in
`nlp-classifier-v3-synthetic-development` artifact from the exact Phase 17
dataset bytes with SHA-256
`6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76`.
The fixed generator partitions contain 80,000 training, 10,000 validation,
and 10,000 protected synthetic-test rows. Base-template, parameter-combination,
and scenario-family overlap across those partitions is zero. The general
production training gate remains closed because the source is synthetic and
has no human split approvals; Phase 18 uses a narrowly scoped development-only
path that cannot change that classification.

Eleven explicitly enumerated character/word TF-IDF logistic-regression
configurations were fitted on training rows and selected only on validation
evidence. The selected configuration is `B_EQUAL_NONE_C1`: character n-grams
2–5, word n-grams 1–2, equal feature weights, `C=1.0`, no class weighting,
`lbfgs`, and seed `170017`. Its 33,917 fitted features stay below the declared
caps. Validation accuracy is `0.8930`, macro F1 is `0.8926`, and
NOT_RELEVANT recall is `0.9150`. The balanced counterpart tied the selected
candidate exactly, so there is no measured validation benefit from balanced
class weighting.

Validation-only scalar temperature fitting selected
`0.39154547863530537` at an interior optimum. It reduced validation log loss
from `0.4775` to `0.2835`, Brier score from `0.2187` to `0.1554`, and ECE from
`0.2023` to `0.0258`. This is `CALIBRATED_ON_VALIDATION`, not production
calibration.

After artifact/configuration freeze and golden contract checks, the protected
test was transformed and evaluated exactly once. Accuracy is `0.9359`, macro
precision `0.9368`, macro recall `0.9359`, macro F1 `0.9359`, and
NOT_RELEVANT recall `0.9360`. English, Hindi, and Hinglish final macro F1 are
`0.9289`, `0.9331`, and `0.9467`. The entire protected partition uses the
held-out `HIGH` noise regime; its macro F1 is `0.9359`. The 2,000-row hard-
negative subset has macro F1 `0.8304` and NOT_RELEVANT recall `0.9975`.
The weak validation urban-flood/river-breach distinction accuracy (`0.1475`)
and a 134-row validation base-template family with macro F1 `0.0` remain
explicit. All 45 held-out base-template families and all six realized
structure families are reported separately.

These results measure project-generated synthetic generalization only. The
status is exactly `DEVELOPMENT_ONLY_SYNTHETIC`; production validation remains
`NOT_VALIDATED`, the model is not the default and is not connected to the live
backend. There is no real citizen-report evidence, human-adjudicated training
set, field calibration, robustness claim outside the generator, or evidence
of demographic/geographic representativeness. NLP v2 results are historical
context only and are `NOT_DIRECTLY_COMPARABLE` because the dataset, split,
sample size, generator regimes, and test construction differ. Full methodology
and immutable evidence are documented in `NLP_V3_SYNTHETIC_DEVELOPMENT.md`.

## Phase 19 duplicate matcher development configuration

No approved human-adjudicated duplicate dataset was present, so Phase 19 used
the explicitly governed synthetic fallback. The 100,000 project-authored pairs
are grouped 70,000/15,000/15,000 for train/validation/test, cover all required
duplicate and hard-negative scenarios, balance English/Hindi/Hinglish, and
pass report, pair, incident, scenario-family, parameter-combination, and exact-
text leakage checks. Labels come from scenario identity, not matcher output.

A new opt-in `duplicate-feature-state-v2` was fitted from 140,000 training
report texts only. The original feature state and default matcher remain
unchanged. Validation-only selection chose text threshold `0.60`, combined
threshold `0.65`, a `5 km` candidate gate, and a `30 minute` time gate. The
full model achieved validation precision `0.9883`, recall `1.0`, and F1
`0.9941`; individual text, geo, time, and declared combination ablations were
weaker. Validation-only Platt scaling is versioned
`duplicate-score-platt-v1`; it does not alter the duplicate decision and is
not production calibration.

Exactly one protected synthetic test evaluation produced precision
`0.9851116625`, recall `0.9998518519`, F1 `0.9924270274`, FPR
`0.0151111111`, FNR `0.0001481481`, and average precision `0.9999032951`.
Hindi `SAME_WEATHER_DIFFERENT_EVENT` pairs dominate false duplicates. This
finding is retained as a limitation. The artifact status is
`DEVELOPMENT_ONLY_SYNTHETIC`; it is not active in the engine or live backend.
Synthetic performance is not field evidence, so production validation remains
`NOT_VALIDATED`. Full evidence is in
`DUPLICATE_V1_SYNTHETIC_VALIDATION.md`.

## Event detection status

Phase 6 adds a heuristic event-grouping framework, not a learned event model.
The hardened `event-grouping-v2` groups typed local observations using spatial
proximity, temporal proximity, report-level type compatibility, complete-link
cluster bounds, and caller-supplied duplicate relationships. The complete-link
rule prevents transitive bridge chains from exceeding spatial or temporal
cluster limits. `EVENT_EVIDENCE_SCORE` is provisional evidence and must not be
interpreted as the probability that an event is real. No event-level ground
truth is available, so event production metrics are `NOT_AVAILABLE`.

## Credibility-risk status

`RULE_BASED_CREDIBILITY_BASELINE` remains a deterministic evidence framework,
not a learned fake detector. Its score is `NOT_CALIBRATED` and must not be
described as a probability of truth or falsity. The current `spam` field is
confounded with `NOT_RELEVANT` and is explicitly excluded from training.

Phase 21 adds the separate opt-in
`credibility-v1-synthetic-development` artifact. It is an interpretable local
logistic regression fitted only to generator-defined `AUTHENTIC` and
`MISLEADING` scenarios using the existing feature snapshot. `UNCERTAIN` is a
validation-selected abstention band, not a fitted target. Its calibrated value
is a synthetic-development probability of `MISLEADING_RISK_EVIDENCE`, never a
truth probability.

The one-shot synthetic test has macro F1, misleading precision, and misleading
recall `1.0`, with FPR/FNR `0.0`. Those perfect values reflect separable
generator-defined regimes and are not field-performance evidence. The selected
authentic cutoff is `0.0000001`, itself a strong distribution-shift warning.
The artifact remains disconnected from live inference and production
validation remains `NOT_VALIDATED`. The existing backend credibility prior and
rule baseline were not modified.

### Credibility feature semantics and availability

Text features describe length, lexical diversity, deterministic repetition,
punctuation, claim-token density, and URL counts. Phone-reference counts are
used only when supplied by the backend. Temporal and geographic features use
the report and submission metadata available at assessment time. Duplication,
source-history, and event-consistency features are consumed only when already
supplied by the caller. Media consistency is reserved and is not scored in
Phase 7.

No feature may use a final annotation, adjudicated label, future moderation
outcome, or information created after the assessment point. Missing optional
evidence remains missing; it is not converted into a favorable score.

Phase 21 preprocessing adds only deterministic transforms and explicit
missingness indicators over those same observable fields. Medians/scales are
fitted on train only; model selection, temperature scaling, and abstention
threshold selection use disjoint grouped validation partitions. Full details
are in `CREDIBILITY_V1_SYNTHETIC_VALIDATION.md`.

## Image analyzer status

Task type: `MULTI_LABEL`. The future output labels are `FLOODED_SCENE`,
`HEAVY_RAIN_VISUAL`, `STANDING_WATER`, `STORM_DAMAGE`, and `NORMAL_SCENE`.
`UNCERTAIN` is reserved for unresolved human annotation and is excluded from
training/evaluation targets.

No image classifier has been trained. No image model artifact, accuracy,
precision, recall, F1, calibration result, or throughput claim exists.
`ImageAnalyzer.fit()` returns `TRAINING_BLOCKED_NO_VALIDATED_IMAGE_DATA` and
`predict()` returns `OFFLINE` after successful validation, with empty labels,
empty probabilities, and no confidence. Invalid bytes return structured error
codes instead of inference.

The repository contains a deliberately small `scratch-cnn-v1` architecture
definition for future approved work. It has three generic convolution blocks,
global pooling, dropout, and a linear multi-label head. It is initialized from
random project-local parameters under an explicit seed and is not currently
trained or loaded.

NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED. There is no transfer
learning, fine-tuning, checkpoint download, external embedding, external vision
API, or network access. A future model may proceed only with approved
project-controlled labeled images, grouped leakage-safe splits, documented
provenance, and a policy-compliant `.pt` artifact.

Known limitations include no validated dataset, no field evaluation, no model
predictions, a deliberately narrow taxonomy, Pillow-only deterministic content
checks, and average-hash near-duplicate detection that captures coarse
luminance similarity rather than semantic similarity.

## Anomaly detector status

The Phase 9 anomaly component is a transparent statistical review baseline,
not a trained anomaly classifier. It accepts only already-loaded rainfall and
river-level observations, computes causal rolling/reference statistics, and
returns `HEURISTIC_ONLY` or an explicit unavailable/error state. Its score is
`STATISTICAL_OUTLIER_SCORE`; it is not a calibrated anomaly probability and is
not evidence that an observation is false.

The baseline distinguishes point from persistent-window behavior and supports
`VALUE_OUTLIER`, `RATE_OF_CHANGE`, `PERSISTENT_DEVIATION`, and
`MISSINGNESS_PATTERN`. Impossible or non-finite values can produce a separate
`DATA_QUALITY_ANOMALY`; plausible extremes are treated as potential
`WEATHER_BEHAVIOR_ANOMALY`, never automatically as sensor error. Missing input
is not automatically anomalous.

No validated anomaly ground truth is present. Learned training returns
`TRAINING_BLOCKED_NO_VALIDATED_ANOMALY_DATA`; no Isolation Forest or other
learned artifact is created or loaded. Accuracy, precision, recall, F1,
false-alarm rate, detection delay, calibration, field performance, and
production throughput are `NOT_AVAILABLE`. Deterministic fixtures and local
timings are software tests only.

No pretrained model, open-weight model, external embedding, external AI API,
runtime download, network access, or cloud inference is used.

## Phase 12 engineering-regression evidence

The Phase 12 golden suite is software-regression evidence, not model-quality
evaluation. Ten versioned, hash-bound synthetic scenarios exercise the unified
NLP, duplicate, event, credibility, image, and anomaly path. Each scenario is
run twice and must preserve exact statuses, typed outputs, reason/evidence
ordering, version maps, and JSON round-trip equality.

The suite also verifies that a single report produces only a provisional
`EVENT_CANDIDATE`; duplicate evidence is not a fake-report label; anomaly
evidence is not a false-report label; event evidence is not NLP classification;
credibility risk and heuristic event scores are not calibrated probabilities;
missing inference is not encoded as zero; and image evidence does not establish
authenticity.

The recorded 1/10/100-report timings in `GOLDEN_BENCHMARK.md` exist only to
detect gross local engineering regressions. They are not production latency,
capacity, throughput, field-performance, accuracy, calibration, or release
metrics. Passing the golden suite does not alter any component's
`DEVELOPMENT_ONLY` / `NOT_VALIDATED` status.

## Phase 20 event-grouping development configuration

`event_grouping_v1.json` is a non-learned, opt-in deterministic configuration
for `event-grouping-v2`. Validation-only selection froze 5 km, 180 minutes,
minimum type evidence 0.40, minimum two independent reports, identical-label
type compatibility, complete-link all-member bounds, and conjunctive
spatial/temporal/type merge logic. Its evidence score is explicitly not a
probability.

On the single protected synthetic test invocation, report-pair precision,
recall, and F1 were `0.9822200865`, `0.9341864717`, and `0.9576013118`;
false-merge and false-split rates were `0.0177799135` and `0.0658135283`.
Exact event-level precision/recall/F1 were `0.8730277986`/`0.9113725490`/
`0.8917881811`. Event-type agreement from controlled fixtures was
`0.9411764706` and is reported separately from grouping quality.

The benchmark is generator-authored, not human field evidence. No learned event
model was created, no NLP model was retrained or invoked, no duplicate matcher
was modified or invoked, and no live backend integration occurred. The valid
status remains `DEVELOPMENT_ONLY_SYNTHETIC / NOT_VALIDATED`. Detailed scope,
metrics, latency definitions, failure analysis, and limitations are in
`EVENT_GROUPING_V1_SYNTHETIC_VALIDATION.md`.
