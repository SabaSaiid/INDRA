# Phase 20 event-grouping synthetic validation

## Status and permitted interpretation

`event-grouping-v2` has been evaluated on a project-authored synthetic event
benchmark. The benchmark, configuration, and metrics are
`DEVELOPMENT_ONLY_SYNTHETIC`. `PRODUCTION_VALIDATION` remains `NOT_VALIDATED`.
The results measure recovery of generator-defined structures; they are not
field performance, operational accuracy, or evidence that an event is real.

No learned event model was created. `event_grouping_v1.json` is a deterministic
configuration/manifest, and `EVENT_EVIDENCE_SCORE` remains an uncalibrated
heuristic evidence score rather than a probability.

## Dataset and ground truth

The registered dataset is `indra-event-project-synthetic-v1`, version
`synthetic-event-110k-v1`:

- provenance: `PROJECT_AUTHORED`
- kind: `SYNTHETIC`
- classification: `DEVELOPMENT_ONLY`
- generator: `synthetic-event-generator-v1`
- seed: `200020`
- reports: `110,000`
- canonical events: `17,000`
- event-pair annotations: `55,000`
- composite dataset SHA-256:
  `127a506f8deba172140dd33b71a14b84b629ce325c959ba8b9d4c04635f48f0f`
- canonical split SHA-256:
  `5ba383c9565739486a67e79ad6ae9a651261a11c00c4ac9dd7ec7c6c67d555e6`

Canonical event identity, incident identity, type, report identity, time,
coordinates, source family, and duplicate family are generated before detector
execution. Pair labels are direct generator identity: 42,000 `EVENT_MATCH`,
11,000 `EVENT_NOT_MATCH`, and 2,000 deliberately boundary-marked `UNCERTAIN`
annotations. The detector is never used to create labels.

The generator covers single events, spatially separate events, temporally
separate events, same-weather hard negatives, duplicate reports, noisy and
partially missing evidence, partially overlapping events, A-B-C bridges,
event-type conflict, single-report events, and legitimate elongated events.
Each family has 10,000 reports, with varied templates, coordinates, times,
report-count allocation, sources, language, and noise profiles.

## Split and isolation controls

Splits are assigned at canonical-event level, never by report row:

| Split | Reports | Canonical events | Pair annotations |
|---|---:|---:|---:|
| Train | 77,000 | 11,900 | 38,500 |
| Validation | 16,500 | 2,550 | 8,250 |
| Test | 16,500 | 2,550 | 8,250 |

Canonical-event, incident, and report cross-split leak counts are all zero.
Ground truth and detector input are physically separate JSONL files. Detector
input schemas reject `canonical_event_id`, generator identity, scenario family,
batch identity, incident identity, duplicate-family identity, and split. The
detector receives only report text/metadata, time, coordinates, controlled
`TextPrediction`, project-generated `DuplicatePrediction`, source metadata, and
optional weather observations.

Controlled text predictions are fixtures, not frozen NLP v3 inference. The
duplicate matcher is not invoked; duplicate relationships are authored by the
event generator. Neither frozen component was modified.

## Validation selection and ablation

Only validation data selected thresholds. The bounded search considered 3/5/8
km, 90/180/300 minutes, and 0.35/0.40/0.60 minimum type evidence. Minimum
independent evidence, complete-link span enforcement, and merge logic were
fixed rather than tuned.

The frozen configuration is:

- spatial radius: `5.0 km`
- temporal window: `180 minutes`
- minimum type probability: `0.40`
- minimum independent reports: `2`
- type compatibility: identical approved taxonomy labels only; missing type
  evidence remains compatible
- cluster constraint: complete-link over every member pair
- merge logic: spatial AND temporal AND type compatibility

Validation-only ablation pairwise F1 was: spatial `0.9521322889`, temporal
`0.8731045491`, type-only `0.8273628820`, spatial+temporal `0.9833707865`,
spatial+type `0.9259343148`, temporal+type `0.8525547445`, and full
`0.9576013118`. Spatial+temporal scores higher than the full system because the
controlled type-conflict family intentionally creates type-driven splits. The
full configuration yields higher precision and lower false merges, illustrating
the explicit merge/split tradeoff rather than establishing a universally
superior field policy.

## Metric definitions and one-shot test result

Event-match metrics operate on report pairs. Precision is correctly grouped
same-event pairs divided by all grouped pairs; recall is correctly grouped
same-event pairs divided by all generator same-event pairs. False-merge rate is
different-event pairs among grouped pairs. False-split rate is separated pairs
among generator same-event pairs. Purity is report-weighted majority canonical
identity per predicted cluster. Completeness is report-weighted largest
recovered predicted fragment per canonical event. Event-level precision and
recall require exact cluster equality.

The frozen test was invoked exactly once:

- event-match precision: `0.9822200865`
- event-match recall: `0.9341864717`
- event-match F1: `0.9576013118`
- false-merge rate: `0.0177799135`
- false-split rate: `0.0658135283`
- average cluster purity: `0.9900000000`
- average cluster completeness: `0.9636363636`
- exact event-level precision: `0.8730277986`
- exact event-level recall: `0.9113725490`
- exact event-level F1: `0.8917881811`
- predicted events: `2,662` versus `2,550` canonical events
- event-count error: `+112` (`+0.0439215686` normalized)

The exact one-shot receipt is
`event_grouping_v1_final_test_receipt.json`. It records invocation count one,
prohibits rerun, binds both test-file hashes, and confirms that test data was not
used for tuning.

## Event type, stream latency, and special cases

Grouping and type are reported separately. Controlled event-type agreement is
`0.9411764706` over 2,550 canonical test events. Per-type exact grouping recall
is `0.9436201780` for urban flood, `0.9366666667` for river breach,
`0.8328402367` for cloudburst, and `0.9383333333` for cyclone inundation. The
full confusion table is in `event_grouping_v1.metrics.json`.

Synthetic ordered-stream timing is not operational latency. Mean time to the
first one-report candidate is `0.0` minutes by contract. Mean time to stable
cluster is `42.3529411765` minutes (p95 `160.0`). Mean delay to two independent
reports is `7.1597222229` minutes (p95 `17.7777777833`); 150 legitimate
single-report events never reach that evidence minimum.

All 150 chain batches remained not-all-one-event, and all recovered the expected
partition. All 150 legitimate elongated events were recovered exactly. All 150
single-report events remained `CANDIDATE`, with zero automatic confirmations.
Across 150 duplicate-family events there were zero independent-count,
source-diversity, or event-evidence inflation violations.

## Artifacts and limits

`event_grouping_v1.json` has artifact hash
`e70a61efdbcb5be22b75236b4822c2721df94bb4eaf5d1e93ceb5e4e314d5d3d`;
its file SHA-256 is
`10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973`.
The threshold search, ablation, validation metrics/errors, performance record,
golden assertions, final metrics/errors, development manifest, and final receipt
are separate JSON evidence files.

The benchmark cannot measure unrepresented geography, report behavior,
language variation, NLP error distributions, coordinated abuse, sensor faults,
field annotation ambiguity, or operational drift. Promotion requires a
representative human-adjudicated field event dataset, grouped independent
splits, field-specific threshold review, untouched governed testing, monitoring,
and explicit deployment approval. Until then: `NOT_VALIDATED`.
