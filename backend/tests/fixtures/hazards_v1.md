# `hazards_v1.csv`: the hazard tagger's labelled fixture

Phase 3 T3. 360 hand-written reports, labelled with the hazards each one describes, used to measure
the rule-based tagger in `app/services/hazard_tagger.py`. `data/labelled/reports_v1.csv` stays frozen
and holds floods only, so this is a new file.

## What is in it

| Group | Rows | What |
|---|---|---|
| each of the 15 hazards | 20 × 15 = 300 | reports of that hazard, often naming a second one too ("waterlogged after two hours of rain") |
| `NEG_NEGATED` | 20 | a hazard word, denied: "No rain in Lucknow today", "कोहरा नहीं है" |
| `NEG_OTHER` | 20 | a hazard word in another sense: "a flood of emails", "heat of the moment", "Rain the singer", "Cyclone the rollercoaster", "लूट", a Vietnamese name "लू" |
| `NEG_TENSE` | 20 | 15 forecasts or warnings, 5 stories about the past |

**Languages:** 221 rows in English, 69 in Hinglish (romanised Hindi), 70 in Hindi (Devanagari):
139 of 360, **38.6%**, are Hindi or Hinglish (the plan asked for at least 30%).

## Columns

| Column | Meaning |
|---|---|
| `id` | `h001` … `h360` |
| `text` | the report, as a citizen, a post or a headline would put it |
| `lang` | `en`, `hinglish` or `hi` |
| `group` | the hazard it was written for, or `NEG_NEGATED` / `NEG_OTHER` / `NEG_TENSE` |
| `hazards` | every hazard the text describes, `;`-separated; empty when it describes none |
| `tense` | `forecast` or `past` for the `NEG_TENSE` rows; empty for an observation |
| `split` | `dev` (60%) or `test` (40%), frozen by `scripts/split_hazard_fixture.py` |

## How the rows were labelled

- **A hazard is labelled when the text says it is happening**, or, in a `NEG_TENSE` row, that it will
  happen or did happen. The tagger is scored on the hazard; the tense is scored separately.
- **Several hazards per row are normal.** Rain that floods a road is `URBAN_FLOOD;RAINFALL`; a dust
  storm that uproots trees is `DUST_STORM;STRONG_WIND`. Wind damage (trees uprooted or down, roofs or
  tin sheets blown off, hoardings down) is labelled `STRONG_WIND` whatever caused the wind.
- **Water in streets, homes or a village is `URBAN_FLOOD`**, including water from a river, the sea or
  a cloudburst; the river, sea or cloudburst gets its own label too.
- **Not labelled:** a power cut ("bijli gul"), a hot or cold day that is not extreme ("ice cold
  coffee in this heat"), visibility lost to dust (a dust storm is not fog), a disaster the text does
  not name.
- The **primary hazard** is not stored: it is derived from the labels by the taxonomy's precedence
  (`services/hazards.py`), the same rule the tagger uses.

## Read this before quoting a number from it

**The rows were written by the same person, in the same session, as the rules they measure**, just
before the rules were written. The split was frozen and committed first, so no rule could be tuned
on the test rows, but the writer knew what kind of rule was coming. The fixture is therefore a
check that the rules do what they say across three languages and the traps the plan names. It is
not an independent estimate of accuracy on real posts. **The independent figure is the 100-real-post
sample** (T3 part 4), drawn from what the Phase 2 pollers collected from 24 Sep, and that is the
number to quote.

The gate was set before measuring: on the held-out `test` rows, precision ≥ 0.85 and recall ≥ 0.80
for each of the PS's seven categories (rainfall, thunderstorm, flooding, heatwave, fog, dust storm,
strong wind), macro-F1 ≥ 0.80 across all 15, and no more than 10% of the negatives tagged as an
observation. If a category misses, the rules are tuned on the `dev` rows only and re-measured; the
gate is never lowered.
