# Datasheet — `reports_v1.csv`

**SHA-256:** `ce142c3a109365bee6f0e407288b74096e675fe71abcaa1cf3dd90ff732f2745`
(`shasum -a 256 data/labelled/reports_v1.csv`; checked by `backend/tests/test_labelled_dataset.py`)

## What it is

300 short, citizen-style flood reports labelled for three tasks: event type, severity and
water depth, plus a spam flag. Used to train and measure the event-type classifier
(`backend/app/ml/event_classifier.py`) and, later, the severity rules and the spam filter.

| Column | Values |
|---|---|
| `id` | `r001` … `r300`, in authoring order |
| `text` | the report |
| `lang` | `en` · `hinglish` (Hindi in Latin script) · `hi` (Devanagari) |
| `event_type` | `URBAN_FLOOD`, `RIVER_BREACH`, `CLOUDBURST`, `CYCLONE_INUNDATION` (the `EventType` enum) or `NOT_RELEVANT` |
| `severity` | `ADVISORY`, `MODERATE`, `HIGH`, `CRITICAL`; **empty if and only if** `NOT_RELEVANT` |
| `depth_cm` | water depth the text states or clearly implies (ankle ≈ 5–10, knee ≈ 40–50, waist ≈ 90, chest ≈ 120, neck ≈ 150–160, roof ≈ 300); empty if none |
| `spam` | `1` for promotional or deliberately misleading text (a subset of `NOT_RELEVANT`) |
| `split` | `train` (210) / `test` (90) |

**Counts.** 60 rows per `event_type`. 17–21 Hindi or Hinglish rows per class. Over the 240
relevant rows, 60 per severity. 62 rows carry a `depth_cm`. 16 rows are spam.

## Where it came from — read this before quoting any number measured on it

- **Synthetic.** Every row was written by Aditya for this project on 17 Sep 2026, in the same
  session that built the classifier. No row is a real citizen report, tweet or news item. Place names are real; the incidents are invented, modelled
  on the kinds of reports seen in Indian urban, riverine, hill and coastal floods.
- **Written by the same people building the model.** Test-set accuracy therefore measures how
  separable *our own phrasing* of the five classes is, not accuracy on reports from real
  citizens. Expect field accuracy to be lower. A holdout written by a teammate who has not seen
  the training rows (`reports_holdout_teammate.csv`, 30 rows) is the planned check; it does not
  exist yet.
- **Label rules are the author's.** Severity follows the pattern ADVISORY = warning or minor
  pooling; MODERATE = ankle-to-knee water, disruption, property damage; HIGH = waist-deep water,
  people stranded, evacuation; CRITICAL = deaths, missing people, collapse, people on roofs.
  Borderline rows exist (e.g. a Sundarbans embankment overtopped by a cyclone surge is labelled
  `CYCLONE_INUNDATION`, not `RIVER_BREACH`).
- **Non-India floods are `NOT_RELEVANT`** (Dhaka, Kathmandu, Manila, Dubai), because the
  platform covers India only.

## The split

Frozen once by `scripts/split_dataset.py` (stratified by `event_type`, `test_size=0.30`,
`random_state=42`) **before any model was trained**, giving 18 test rows per class. The script
refuses to run on a file whose `split` column is already set. Model selection uses
cross-validation on `train` only; `test` is evaluated once.

Leakage checks in `test_labelled_dataset.py`: no exact duplicate text (casefolded,
whitespace-collapsed) across train and test, and no train/test pair with MiniLM cosine ≥ 0.95.

## Known limits

- **Hindi in Devanagari is poorly represented by the features.** `all-MiniLM-L6-v2` is an
  English model: it tokenises Devanagari into single characters and drops the vowel signs.
  Two unrelated Hindi sentences score ~0.70 cosine (two unrelated English ones ~0.36). The
  classifier's metrics file reports Hindi/Hinglish-only accuracy separately for this reason.
- 300 rows is small. Per-class test metrics rest on 18 rows each, so one error moves a class's
  recall by 5.6 points.
- Short, clean sentences. Real reports have typos, emoji, mixed scripts inside one sentence,
  forwarded-message boilerplate and far more off-topic noise than 20%.
