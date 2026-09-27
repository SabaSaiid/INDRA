# `hazards_real_v1.csv`: 100 real posts and headlines, labelled by hand

Phase 3 T3 part 4. The independent measurement of the hazard tagger on real text, as opposed to
`hazards_v1.csv`, whose rows were written with the rules.

## The sample

Drawn on the team server on **26 Sep 2026, 12:25 IST** by `scripts/sample_real_posts.py` from the
2,198 unduplicated posts and headlines the Phase 2 pollers had collected since 24 Sep 19:41 IST.
Stratified, seed `24092026`: 50 Mastodon posts and 50 Google News headlines, 38 of them in Hindi,
including 5 US National Weather Service flood posts and 5 Vietnam.vn items with "लू" in them.
Committed **unlabelled** (`3a40047`) before any label was written or anything measured.

## Who labelled it, and what that means

**Labelled by Claude, not by a person**, on 27 Sep 2026, at Aditya's request (he found labelling
100 posts too hard). The plan asked for a person, so this is a weaker check than planned:

- The tagger's rules were written with Claude in an earlier session, so the labeller knew the
  lexicon. Judgement calls on ambiguous posts may lean towards the rules.
- The labels were written **before the tagger was run on any of these 100 rows**, and committed
  before measuring. But on 26 Sep a spot check of the backfill showed the tagger's output on about 18
  random rows of the collected corpus (dust storm, cyclone and cloudburst rows), and some may be in
  this sample.

Quote the result as **"measured on 100 real posts collected from 24 Sep, labelled by Claude"**,
never as a human-labelled figure. A person relabelling it, or checking the disagreements, would make
it independent.

## Columns and conventions

`hazards`: every hazard the text describes, `;`-separated, or `none`. `tense`: `forecast` for a
warning or prediction, `past` for an old story, empty for an observation (when a text both reports
the hazard now and warns of more, the observation sets the tense). `notes`: the reason for any
judgement call. The rules are `hazards_v1.md`'s, plus:

- **आंधी with rain** ("आंधी-बारिश", "बारिश और आंधी") is read as a squall: THUNDERSTORM, STRONG_WIND
  and RAINFALL, the way the fixture reads आंधी-तूफान (h135, h139). आंधी alone stays a dust storm.
- **Place doesn't matter**: a US flood warning is labelled a flood. The geocoder decides where it is.
- **A photo post tagged #fog** is fog seen; **a humour post that only carries #ChennaiRains** is not
  a report of rain (`none`).
- **An impossible number** (240 °C, 620 km/h) still names the hazard the post claims; the
  `implausible_value` flag, not the hazard label, is what should catch it.

## `hazards_real_v2.csv`, the independent sample

v1 was read on 27 Sep to find BUG-108 … BUG-112, and the rules were fixed after that, so v1 no
longer measures anything independently. **v2** was drawn the same day, after the fixes, with
`--seed 27092026 --exclude hazards_real_v1.csv`: 100 of 2,801 candidates, 41 in Hindi, no row shared
with v1. One phone number in a rescue request was replaced with `<phone>` (the sampler now does this
itself). v2 was labelled the same way, by Claude, with the conventions above, before the tagger was
run on any of its rows, and committed before measuring. One row (p097, a headline cut off before
its hazard word) is `skip`. **v2's figure is the one to quote**, with the same caveat: labelled by
Claude, not a person.
