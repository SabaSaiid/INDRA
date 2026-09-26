# NLP human-annotation guide

Guide version: `nlp-annotation-guide-v1`

Scope: local human review of weather reports for the INDRA five-class NLP
taxonomy. This guide is the labeling authority. Model output, rules, keyword
matches, sampling queues, and previous predictions are never ground truth.

## Approved taxonomy

The only class labels are:

- `URBAN_FLOOD`
- `RIVER_BREACH`
- `CLOUDBURST`
- `CYCLONE_INUNDATION`
- `NOT_RELEVANT`

`UNCERTAIN` is an annotation state, not a sixth class. Do not add a label for a
new phenomenon. If the report does not support one approved class reliably,
use `UNCERTAIN`; use `NOT_RELEVANT` only when the report can reliably be judged
outside the four target event classes.

## General decision rules

1. Read the original report exactly as supplied. Do not translate,
   transliterate, rewrite, spell-correct, or expand abbreviations in the stored
   text.
2. Judge the reported event and causal mechanism, not isolated words. A word
   such as “river,” “cyclone,” or “cloudburst” is evidence only in context.
3. Use source metadata only when it is part of the approved review packet.
   Never invent location, time, event, incident, or source-family information.
4. Select one approved class only when the evidence is sufficient. Otherwise
   select `UNCERTAIN` and explain what evidence is missing or conflicting.
5. Record the language as `en`, `hi`, `hinglish`, `other`, or `unknown`.
6. Confidence is the human reviewer’s confidence in their own judgment from
   `0.0` to `1.0`. It is not a model probability.
7. Write a concise reason that cites the report evidence and the relevant
   distinction in this guide.

Illustrative examples below clarify policy; they are not automatically labeled
records and must not be copied into a dataset as ground truth.

## `URBAN_FLOOD`

Positive criteria:

- Water inundates streets, underpasses, homes, shops, transport areas, or other
  built-up places.
- The described mechanism is urban drainage failure, drain or culvert
  overflow, waterlogging, runoff accumulation, or rain overwhelming city
  infrastructure.
- The report can identify the urban-flood condition even when exact depth or
  duration is absent.

Negative criteria:

- The principal source is a breached or overtopped river bank or embankment;
  use `RIVER_BREACH` when that mechanism is sufficiently established.
- Inundation is explicitly caused by a cyclone, storm surge, or cyclone-linked
  coastal water; use `CYCLONE_INUNDATION` when that mechanism is established.
- The report describes intense rain but no urban inundation; do not infer a
  flood from rain alone.

Ambiguous cases:

- A city near a river is flooded but the report does not say whether water came
  from the river or drainage.
- Both a river breach and failed city drains are described, with no dominant
  event mechanism.
- “Water on road” could mean a small puddle rather than disruptive inundation.

Use `UNCERTAIN` when the presence or mechanism of material urban inundation
cannot be established, or when two supported target classes cannot be resolved
to one class.

Distinguishing characteristics are built-up impact and a drainage/runoff
mechanism. Example: “After the drains backed up, water entered shops around the
municipal market” supports `URBAN_FLOOD`. Hinglish example: “Nali block hai aur
gali ke gharon mein paani ghus gaya” supports the same class if the annotator
understands the report reliably.

Common confusions: `RIVER_BREACH`, `CYCLONE_INUNDATION`, ordinary wet roads, and
heavy rain without flooding.

## `RIVER_BREACH`

Positive criteria:

- A river, stream, canal, levee, bank, bund, or embankment breaches, fails,
  overtops, or erodes and releases water.
- Flooding is causally tied to that river-system failure or overflow.
- The report provides enough context to distinguish river water from ordinary
  city drainage.

Negative criteria:

- Built-up waterlogging is attributed only to drains, culverts, or surface
  runoff; use `URBAN_FLOOD`.
- Coastal or inland inundation is explicitly cyclone/storm-surge driven; use
  `CYCLONE_INUNDATION`.
- A report merely mentions a high river level without breach, overtopping,
  erosion, or resulting inundation. Do not invent a breach.

Ambiguous cases:

- “The river is dangerous” without a failure, overflow, or impact.
- Floodwater is seen near a river but its source is not known.
- A damaged embankment is reported, but no current release or inundation is
  described and it is unclear whether the report concerns an event or a repair.

Use `UNCERTAIN` when the river-system mechanism cannot be confirmed or the
report could equally support an urban-drainage event.

Distinguishing characteristics are a named or clearly described watercourse
and a breach/overtopping/erosion mechanism. Example: “The river embankment
failed and fast water entered the downstream fields” supports `RIVER_BREACH`.
Hindi example: “नदी का तटबंध टूटने से गांव में पानी घुस गया” supports the same
class when reviewed by a competent reader.

Common confusions: `URBAN_FLOOD`, high river level without failure, dam-release
notices, and historical discussion of an earlier breach.

### `URBAN_FLOOD` versus `RIVER_BREACH`

Choose `URBAN_FLOOD` when the supported causal pathway is rain/runoff plus
urban drainage or waterlogging. Choose `RIVER_BREACH` when the supported causal
pathway is river, bank, bund, levee, canal, or embankment failure/overtopping.
The impact location alone does not decide the class: river water can enter a
city, and urban flooding can occur near a river. If the report establishes the
impact but not the pathway, use `UNCERTAIN` rather than guessing.

## `CLOUDBURST`

Positive criteria:

- The report explicitly and credibly describes a cloudburst or a very sudden,
  highly localized, extreme downpour with the defining event context.
- The timing and locality support a concentrated extreme-rain event rather
  than routine heavy or prolonged rain.
- The reported event itself is the cloudburst, even if secondary runoff or
  localized flooding is also mentioned.

Negative criteria:

- “Heavy rain,” “very heavy rain,” a thunderstorm, or a monsoon downpour by
  itself is not enough.
- Widespread or prolonged rainfall without sudden localized extreme intensity
  is other heavy rain, not `CLOUDBURST`.
- Urban waterlogging caused by drainage failure should be `URBAN_FLOOD` when
  cloudburst evidence is absent.

Ambiguous cases:

- A source casually calls any strong rain a “cloudburst” without locality,
  suddenness, or corroborating event detail.
- A short message reports flash flooding but does not identify whether it came
  from a cloudburst, river failure, or drainage.
- Translation ambiguity makes the intensity term unreliable.

Use `UNCERTAIN` when cloudburst-specific meaning cannot be distinguished from
ordinary heavy rain or another flood mechanism.

Distinguishing characteristics are sudden onset, exceptional intensity, and
local concentration. Example: “A localized cloudburst over the upper valley
released extreme rain within minutes” supports `CLOUDBURST`. The sentence
“Heavy monsoon rain is forecast across the district today” does not.

Common confusions: other heavy rain, thunderstorms, flash floods of unknown
cause, and urban flooding after intense rain.

### `CLOUDBURST` versus other heavy rain

`OTHER_HEAVY_RAIN` is not an approved label. A report about heavy rain alone,
with no supported cloudburst and no supported urban flood, river breach, or
cyclone inundation, belongs to `NOT_RELEVANT` if that non-target interpretation
is clear. Use `UNCERTAIN` if the text may describe a cloudburst but lacks enough
information to decide. Never convert “heavy,” a rainfall number, or a keyword
match automatically into `CLOUDBURST`.

## `CYCLONE_INUNDATION`

Positive criteria:

- Coastal flooding, storm surge, seawater ingress, or inland inundation is
  explicitly linked to a cyclone.
- The report clearly attributes flooding to cyclone-driven surge, coastal
  water, or cyclone circulation rather than only to routine drainage failure.
- A named cyclone is useful context but is not required when the cyclone causal
  link is otherwise explicit.

Negative criteria:

- A cyclone warning without inundation is not this class.
- Wind damage alone is not inundation.
- Urban drains failing during rainy weather, without a supported cyclone
  causal link, should be `URBAN_FLOOD`.
- Coastal high tide without a cyclone link is not automatically this class.

Ambiguous cases:

- Flooding occurs during a cyclone, but the report attributes it only to
  blocked drains and gives no surge or cyclone-inundation mechanism.
- A coastal report mentions waves and street water but does not establish
  seawater ingress or cyclone causation.
- Both cyclone surge and urban drainage failure materially drive one report.

Use `UNCERTAIN` when cyclone causation or inundation is missing, indirect, or
in conflict with an equally supported urban-flood explanation.

Distinguishing characteristics are explicit cyclone causation plus inundation,
often storm surge or coastal water ingress. Example: “Cyclone-driven storm
surge crossed the sea wall and inundated nearby settlements” supports
`CYCLONE_INUNDATION`.

Common confusions: `URBAN_FLOOD`, cyclone wind damage, high tide, and generic
coastal rain.

### `CYCLONE_INUNDATION` versus `URBAN_FLOOD`

Choose `CYCLONE_INUNDATION` when cyclone-driven surge, seawater, or inundation
is the supported event mechanism. Choose `URBAN_FLOOD` when the supported
mechanism is urban drainage/runoff, even if rain is severe. Mere temporal
coincidence with a cyclone does not settle the label. Use `UNCERTAIN` when the
report supports both mechanisms without enough evidence to choose one.

## `NOT_RELEVANT`

Positive criteria:

- The report is reliably outside all four target event classes.
- It concerns ordinary weather, forecasts or warnings without a target event,
  unrelated civic issues, routine operations, commentary, tests, greetings,
  or other non-event content.
- It describes heavy rain without sufficient evidence of cloudburst, urban
  flood, river breach, or cyclone inundation.

Negative criteria:

- Do not use `NOT_RELEVANT` merely because a report is short, misspelled,
  multilingual, unfamiliar, or low confidence.
- Do not use it as a catch-all for ambiguous target events; use `UNCERTAIN`.
- Do not use a model’s low relevance score as evidence.

Ambiguous cases include vague phrases such as “water everywhere,” incomplete
location-only messages, and unfamiliar dialect. Use `UNCERTAIN` when the
report may concern a target event but cannot be interpreted reliably.

Distinguishing characteristic: the human can affirmatively determine that no
approved target event is being reported. Example: “The weekly weather bulletin
predicts light rain on Friday” supports `NOT_RELEVANT`.

Common confusions: ambiguous short reports, other heavy rain, warnings before
an event, and reports in a language the annotator cannot reliably read.

## Multilingual policy

English, Hindi, and Hinglish are first-class review languages. `other` records
a known different language; `unknown` records that the language itself cannot
be identified reliably. Preserve script, punctuation, whitespace, emoji, and
code-switching exactly. Do not store a translation or transliteration in place
of the source text.

Annotators should review only languages they can interpret reliably. If a
report cannot be classified reliably because of language, dialect, damaged
encoding, or code-switching, select `UNCERTAIN` and state that limitation.

## Assistance and blinding

Blind review is the default. In blind mode no prediction is displayed or
stored. Assisted mode must be explicitly enabled and every displayed result is
headed exactly:

`MODEL SUGGESTION — NOT GROUND TRUTH`

The annotation record then stores `blind_annotation=false`,
`model_assistance=NON_GROUND_TRUTH`, `assistance_shown=true`,
`model_assistance_shown=true`, and suggestion provenance. The annotator must
still enter a human judgment and reason. A
suggestion cannot populate the label field automatically and cannot resolve a
disagreement.

## Disagreement and adjudication

Original annotations are immutable. Agreement is a quality statistic, not an
automatic final label. Every released label requires a separate explicit
adjudication with adjudicator ID, timestamp, final label/state, and reason. If
the evidence or disagreement cannot be resolved, the adjudicator selects
`UNCERTAIN`; the report is excluded from labeled train/validation/test rows and
is recorded in the version manifest as excluded uncertain evidence.
