# INDRA image annotation guide

Schema version: `image-annotations-v1`
Task type: `MULTI_LABEL`

## Scope and governing rule

Annotate what is visibly present in the image, not what a caption, filename,
report, or uploader claims the image represents. Text saying “flood” is not
visual evidence of flooding. Location, capture time, authenticity, causation,
and image manipulation are outside this taxonomy unless independently supplied
and reviewed through another process.

An image may receive more than one positive visual label. For example,
`FLOODED_SCENE` and `STANDING_WATER` may both apply. `NORMAL_SCENE` and
`UNCERTAIN` are exclusive and cannot be combined with another label.

## FLOODED_SCENE

- Positive criteria: water visibly inundates land, roads, buildings, or other
  areas that are ordinarily dry, with enough context to distinguish inundation
  from a normal water body.
- Negative criteria: ordinary rivers, lakes, drains, puddles, wet pavement, or
  rain without visible inundation.
- Ambiguous cases: tightly cropped water with no dry-land context; reflections;
  an unknown road or river boundary.
- UNCERTAIN criteria: the annotator cannot determine whether the covered area is
  ordinarily dry or whether the visible region is water.
- Example: vehicles moving through water spanning the full width of an urban
  road is positive; a full river channel within its banks is negative.
- Limitation: depth, current, geographic location, and flood cause generally
  cannot be established from one image.

## HEAVY_RAIN_VISUAL

- Positive criteria: dense visible rain streaks or sheets, strong rain haze, or
  clearly intense rainfall in the scene itself.
- Negative criteria: wet surfaces, dark clouds, umbrellas, or windshield drops
  without visible heavy rainfall.
- Ambiguous cases: motion blur, compression artifacts, mist, spray, or distant
  low-contrast precipitation.
- UNCERTAIN criteria: rain may be present but visual intensity cannot be
  distinguished reliably.
- Example: dense streaking that materially obscures the background is positive;
  a wet road after rain is negative.
- Limitation: no rainfall rate is inferred and a single frame cannot establish
  duration.

## STANDING_WATER

- Positive criteria: visibly pooled or stagnant water on a surface or area not
  intended as a permanent water body.
- Negative criteria: normal rivers, lakes, reservoirs, fountains, drainage
  channels, uniformly wet pavement, or an isolated reflection with no visible
  pool boundary.
- Ambiguous cases: shallow reflective regions, mud, shadow, or an unknown water
  feature.
- UNCERTAIN criteria: the visual evidence does not reliably separate pooled
  water from wet material or a normal water body.
- Example: a bounded pool covering part of a road is positive; rain-darkened
  asphalt with no pooled edge is negative.
- Limitation: water depth, contamination, movement, and hazard severity are not
  inferred.

## STORM_DAMAGE

- Positive criteria: visible physical damage plausibly consistent with severe
  weather, such as uprooted trees, torn roofs, collapsed weather-exposed
  structures, or widespread wind/debris damage.
- Negative criteria: intact scenes, routine construction, demolition, litter,
  or isolated wear with no observable storm-damage pattern.
- Ambiguous cases: damage with unknown cause, old damage, planned demolition,
  or a crop too tight to establish context.
- UNCERTAIN criteria: damage is visible but its form cannot be distinguished
  from construction, neglect, collision, or another cause.
- Example: multiple uprooted trees and damaged roofs in one scene is positive;
  a building under planned renovation is negative.
- Limitation: this label describes visible damage pattern only and does not
  prove cause, recency, or relation to a reported event.

## NORMAL_SCENE

- Positive criteria: the visible scene is interpretable and none of the four
  positive weather-visual labels is present.
- Negative criteria: any positive weather-visual criterion is met.
- Ambiguous cases: obstructed, extremely dark, blurred, or context-free images.
- UNCERTAIN criteria: image quality or missing context prevents a reliable
  negative judgment.
- Example: a clear, dry, undamaged street is positive; a clear road containing
  a bounded pool is not.
- Limitation: “normal” means only no defined visual condition is observed. It is
  not evidence that the report or wider event is normal or authentic.

## UNCERTAIN

- Positive criteria: corruption that escaped ingestion checks, severe blur,
  obstruction, inadequate lighting, missing scene context, or genuine
  ambiguity prevents a defensible visual label.
- Negative criteria: one or more positive labels can be assigned under their
  definitions, or the scene clearly satisfies `NORMAL_SCENE`.
- Ambiguous cases: when uncertainty is material, use this label rather than
  guessing or lowering standards to fill a class.
- UNCERTAIN criteria: this label is itself the unresolved state and must be used
  alone.
- Example: a tiny dark crop that may show water is uncertain; a clear scene with
  both inundation and pooled water receives both positive labels instead.
- Limitation: `UNCERTAIN` is excluded from model targets and measured metrics;
  it is not a learnable visual condition.

## Annotation workflow

Each judgment records image ID, exact `BYTE_HASH`, optional
`PERCEPTUAL_SIMILARITY_HASH`, decoded dimensions and format, annotator ID,
timestamp, one or more labels, optional confidence, and a reason. Original
judgments are append-only. A second annotator adds another record; no record is
overwritten.

Inter-annotator exact-set agreement is calculated only for images actually
reviewed by at least two distinct annotators. It is `DATA_UNAVAILABLE` when no
such repeats exist. Disagreement is routed to an adjudication record. Until an
adjudicator records labels, identity, timestamp, and rationale, its effective
label remains `UNCERTAIN`.

Annotation confidence expresses confidence in applying this guide, not the
probability that an event occurred or that a report is authentic.

## Quality and split controls

Before any future training, validate content decoding, dimensions, labels,
repeated judgments, duplicate byte hashes, and split leakage. Group by event,
incident, source report, or capture session. Exact byte duplicates and images
within the configured average-hash Hamming threshold stay in one component.
If grouping metadata is unavailable, return `GROUPED_SPLIT_UNAVAILABLE`; never
fall back to image-level random splitting.

The optional perceptual hash is a deterministic average hash. It can flag
coarse luminance similarity and simple near-duplicates, but it is not a learned
model and cannot establish semantic equivalence, provenance, or authenticity.

NO PRETRAINED OR OPEN-WEIGHT VISION MODEL IS USED for annotation, duplicate
detection, grouping, or leakage checks.
