# INDRA — Questions You Will Be Asked, and the Honest Answer

The answer to every hard question a nodal officer, reviewer or teammate is likely to ask about the
platform. Each answer has a number, a file or a test behind it.

**The rule this whole project runs on:** *stating that a signal is absent is strictly better than
faking it.* Every answer below follows from that, including the uncomfortable ones. If you are
ever unsure what to say, say what is true and say where it is written down.

| | |
|---|---|
| **Applies to** | `main` after Phase 4 (PR #47) |
| **Last reviewed** | 28 Sep 2026. The Phase 4 numbers were measured on 27 Sep |
| **Out of scope here** | Layer 4 (AI/ML), whose evidence is advisory and synthetic-development only: [ML architecture](ML_ARCHITECTURE.md), [validation](ML_VALIDATION_REPORT.md) |

---

## About the score

### How is confidence computed?

> **Receipt v2 (Phase 4, tested 27 Sep):** seven factors. The official warning (IMD and SDMA, via
> SACHET) joins at 10%; the weather falls to 20% and spatial coherence to 15%. With vision and
> anomaly offline the coverage is still 0.80. A v2 worked example, measured on real weather on 27
> Sep: five labelled reports under an Extreme Uttarakhand SDMA rain warning, 54.6 mm fallen,
> `0.5696 / 0.80 = 0.712` (CORROBORATED); five labelled "47 °C" reports beside Dehradun airport,
> which measured 20.0 °C, `0.3495 / 0.80 = 0.4369` (CONTRADICTED). Five citizen flood reports in
> Patna with 15.6 mm of rain score **0.5171 with no warning in force** (quarantined: "no warning
> covers this" is now measured evidence) and **0.6234 under a Severe IMD warning** (review). The
> v1 example below is kept as history.

Six weighted factors (v1). The score is the weighted mean **over the factors that actually reported**:

```
confidence = Σ_online(weight × score) / Σ_online(weight)
```

A worked example, from a 20 Sep test cluster of five scripted reports: `0.3987 / 0.80 = 0.4984`.
On 22 Sep, with more rain in Patna, the same five gave `0.4117 / 0.80 = 0.5146`. The weather factor
is live, so the same reports score differently on a different day. The script, the reports and the
event were deleted on 25 Sep; only the arithmetic is quoted. The receipt prints every factor, its
weight, its score, its points and whether it was `computed` or `offline`, so the arithmetic can be
checked on the spot. The dashboard's receipt now shows the coverage under the score and the
division beneath the factors.

### What does `factor_coverage` mean?

**The share of the designed model that actually reported.** `0.80` means factors worth 20% of the
scale produced nothing, so the score is a mean over the 80% that did.

It exists because the alternative is worse. If an offline factor scores zero and keeps its weight,
a system missing two factors can never exceed 0.80 — and then a cluster with every available
signal at maximum still could not be auto-published. That is not honesty, it is a broken scale.
Re-normalising makes the score usable; publishing the coverage keeps it honest.

**Never quote the score without the coverage.**

### Why do new events score only about 0.5? Isn't that a failure?

No — it is the system working.

A fresh event is typically a few unverified citizen reports, from one source type, often on a dry
day. Nobody has confirmed it, no official channel has reported it, and there is no photograph.
A platform that called that a verified disaster would be the broken one.

Watch what it does instead: it quarantines the event (or, if the reports describe a High or
Critical situation, sends it straight to review) and puts it in front of a human, and the receipt
shows exactly which evidence produced the number. **Add more independent reports and the density
factor rises. Add real rainfall and the weather factor rises. Add a report from a trusted source
and source reliability rises.** Measured 22 Sep on a test cluster of five reports: 0.5146,
`QUARANTINED`; the same five plus one official dispatch through the commander's route scored
**0.6065, `PENDING_HUMAN_REVIEW`**, with source reliability 0.60 → 1.00. Those were test reports,
since deleted. On stage, point at the receipt of whatever real event is on screen.

### Could you not just raise the numbers?

Yes, trivially, and every one of them would be a lie. The curves are deliberately not tunable to
taste: rainfall is scored against **IMD's own published daily rainfall categories** (2.5 mm light,
15.6 moderate, 64.5 heavy, 115.6 very heavy, 204.5 extremely heavy). The severity depth cuts are
operational facts — 20 cm stops a two-wheeler, 60 cm floats a small car, 120 cm turns wading into
a rescue. They are numbers you are invited to argue with, which is the point of publishing them.

---

## About the AI

### Where is the AI?

**Deduplication uses the frozen local Phase 19 matcher, not MiniLM.** The backend also records
typed advisory outputs from five-class NLP, deterministic event grouping, local credibility,
scratch-CNN image analysis, and statistical-plus-local-logistic anomaly detection. These models
have synthetic-development evidence, not production or field validation. They do not automatically
confirm a report or decide that a duplicate or anomaly is fake.

### Why are `vision_analysis` and `anomaly_detection` offline?

They are **excluded from the older fusion score**, not absent as components. The frozen image and
anomaly models write separate advisory evidence when caller-supplied image bytes or sufficient
causal station history exist; missing inputs are `NOT_RUN`. The receipt never fills an unavailable
fusion factor with a plausible number, so its stated coverage remains honest.

Earlier in this project those two factors were filled with **random numbers**. Removing that is
what dropped the test cluster's confidence from 0.76 to 0.43. We kept the lower, true number.

### You trained a classifier. Why isn't it running?

It was trained and **measured**, and it missed its acceptance gate: test macro-F1 0.787, but
NOT_RELEVANT recall 0.667 and 5 of 72 floods dismissed. Metrics are in
`backend/app/ml/artifacts/event_classifier_v1.metrics.json`.

That older below-gate classifier remains quarantined: `classify()` returns `None`. It is distinct
from the frozen five-class Phase 18 NLP development artifact now used only for advisory inference;
neither result is a production-validation claim.

---

## About the alerts

### Where are the alerts? Who gets the SMS?

**Nobody, from the core platform.** INDRA's backend sends no SMS, no email and no CAP broadcast, and
has no dispatch integration. Alerting (layer 8b) left the core platform's scope on 20 Sep rather
than being half-built. Its owner has since written a separate service, `alert_engine/` (PR #38),
with its own rules and SMTP e-mail. It is maintained independently and **does not run on the team
server**, so no alert is sent during a demo. See [Alert engine integration](ALERT_ENGINE_INTEGRATION.md).

What the Warnings page shows is **official warnings that others issued**: IMD, CWC and state SDMA
CAP alerts, collected every 5 minutes from NDMA's SACHET feed (`GET /api/alerts/agency`) and
credited to their issuers in their own words. INDRA's own severe events appear beside them,
labelled *"INDRA event · not an official warning"* with their review status.

Be ready for this one: until 22 Sep that page also showed four invented bulletins credited to IMD,
CWC and GSI — including a fictional "Cyclone Marut" — and presented INDRA events as NDMA warnings,
and the map drew a fictional cyclone track. All of it was found by reading every page and removed
the same day (BUG-047 to BUG-050 in the register). A browser test now fails if any of it returns.

The honest version of this platform's promise stops at: an event is verified, scored, explained,
and put in front of a commander who takes the decision. Automated dispatch on top of a 0.50
confidence score would be the most expensive mistake this system could make.

---

## About trust and failure

### What stops a false alarm?

Four things, in order:

1. **Deduplication** — the same message sent five times counts once. A suppressed duplicate is
   never counted as corroboration and **never grades severity**, so a reposted alarming text
   cannot inflate an event. A *second person* describing the same flood in their own words is
   kept: that is a witness. Historical 22 Sep MiniLM measurements showed resubmissions at
   0.91–0.99 and independent witnesses 0.81–0.91 against the 0.88 threshold (BUG-013).
2. **Coordinate validation** — anything outside India's bounds is rejected with a 422 and never
   stored. It is not snapped to the map.
3. **The corroboration rule** — a single report does not make an event. DBSCAN needs at least two.
4. **Human review** — nothing below 0.90 auto-publishes, and in practice nothing reaches 0.90,
   so every event goes to a person.

### What if a source lies?

Each source type carries a reliability prior — official dispatch 1.00, CWC 0.95, automatic weather
station 0.90, citizen app 0.60, news 0.55, social 0.50 — and each report is also scored on text
quality. One source cannot auto-publish an event on its own.

**A citizen cannot claim to be official.** The public endpoint stamps every report `CITIZEN_APP`
whatever the request says. A trusted report comes through `POST /api/reports/official`, which needs
a Commander or Admin token and stores who filed it; provenance shows that name beside the report.
Be precise about the limit: the route is exactly as trusted as the account behind it. Since 25 Sep
no password ships with the dashboard or the code; each operator signs in with a password set for
that deployment and stored only as a bcrypt hash. There is no MFA (BUG-025, closed 22 Sep).

### How do you catch a fake heatwave?

*(Phase 4, tested 27 Sep; the figures below were measured that evening.)*

With a thermometer. Every event is checked against **its own hazard's measurement**: a heatwave
against the maximum temperature, fog against visibility, a thunderstorm against the weather code
and CAPE, a flood against 24-hour rainfall. When an airport is within 50 km, its METAR (the
observation IMD's aerodrome office makes every half hour) is the evidence, and the model is shown
beside it; a measurement beats a model.

If five people report 47 °C and the airport nearby never went above 27 °C in the last 24 hours, the
receipt records a **contradiction**, names the station and the reading, scores the weather factor
0.0, and the event's verdict is **CONTRADICTED**. On 27 Sep, five labelled "47 degree" reports
5 km from Dehradun airport were contradicted by its own 20.0 °C maximum: confidence 0.4369, held
for a human. It cannot auto-publish, however many
reports agree, and it goes to the review queue's "contradicted" tab.

Two things it never does. **It never rejects automatically**: a missing or contrary signal is not
proof that nobody saw anything, so a human decides. **It never contradicts from missing data**: if
the weather feed is down, the factor is offline, not a strike against the report. The rules are
published (`backend/app/services/evidence.py`), for example a heatwave is contradicted below 35 °C
on the plains and 25 °C in the hills, a hailstorm is never contradicted (too local for any feed),
and a flood with 0 mm of rain says "waterlogging from another cause is possible; a human should
check".

### What if IMD issues the warning later?

*(Phase 4, tested 27 Sep.)*

The event rises. When the SACHET poller stores a new or revised warning, or an airport reports fog,
a thunderstorm or a squall, every open event of that hazard it covers (updated in the last 24 hours,
not rejected) is re-scored with the new evidence. If its confidence, verdict or status changes, the
event is updated, a `LATE_CORROBORATION` row goes into the ledger with the before and after, and
the dashboard is told. A commander's decision stands: an approved event stays approved, and only its
confidence and verdict move. The history endpoint shows exactly when and why. In the test, a Severe
warning arriving after the five Patna reports lifts the event by 0.85 × 0.10 / 0.80 = 0.106, from
UNCONFIRMED and quarantined to CORROBORATED and in front of a reviewer.

### What if the photo is old?

*(Phase 5, tested 28 Sep.)*

It is flagged, with the reason in words, and it counts for less. Every photo and video INDRA
stores, from citizens and from every Mastodon post it has collected, gets an exact fingerprint
(SHA-256) and a perceptual one (a 64-bit pHash that survives resizing and re-compression), and its
EXIF capture time and place are read. Then published rules apply:

- near-identical to an image first seen **more than 48 hours earlier** → `recycled_suspect`,
  credibility × 0.3, "near-identical to an image first seen on 23 Oct 2024 (Mastodon)";
- camera date **more than 48 hours before** the report → `old_capture`, × 0.4, "taken 14 Aug 2023,
  3 years before the report";
- taken **more than 25 km** from where the report was filed → `location_mismatch`, × 0.5;
- the **same file** from two people → one witness, not two (a WhatsApp forward is one sighting).

A photo with no EXIF is not held against anyone: WhatsApp strips it from everything. **Nothing is
rejected automatically**; the report stays, flagged, in front of a human. And INDRA never claims to
know what a picture shows: `vision_analysis` stays offline.

This is not hypothetical. Hashing 60 real #IMD posts on 28 Sep (a copy of the team database) found
two re-posted images: a Bengaluru rain meme from 25 May 2025, near-identical (2 of 64 bits) to one
first posted on 23 Oct 2024, and a cyclone-alert graphic re-posted a week after it first appeared.
The demo's case C shows the rule end to end (`scripts/run_verification_demo.py`).

### What stops someone flooding you with fake reports?

*(Phase 5, tested 28 Sep.)*

Three things. **Rate limits**: 10 reports per device and 300 per network address in 10 minutes,
then a 429 with the seconds to wait, and nothing stored. The per-address limit is high on purpose:
Indian mobile carriers put a whole town behind one address, and the per-device limit does the fine
work. A header sent from outside cannot pick its own address. With Redis down each server process
still limits on its own. Refusals are counted on `/api/meta/sources`. **One device is one witness**:
fifty reports from one phone count once in the density factor. And **reputation**: a device whose
events commanders keep rejecting counts for less on its next report, by a published formula,
`credibility × (0.5 + (approved + 1) / (approved + rejected + 2))`, at most 1.0. Only human
decisions count; the machine's own score is not ground truth.

The limit to be honest about: a determined attacker with many phones and many addresses gets many
witnesses. That is what the weather and official-warning factors are for; a flood of fake heatwave
reports beside an airport reading 24 °C is still contradicted.

### What about citizens' data?

*(Phase 5, tested 28 Sep.)*

- A citizen's device is known only by a keyed hash of a random id their phone generates; the id
  itself is never stored.
- Their original photos, which carry the GPS of where they stood, are private. Officials see a copy
  with **every metadata tag removed** (at most 1,600 px) through links that expire in 10 minutes;
  the original is available to an analyst only, and every such link is written to the ledger.
- Originals are deleted after 90 days unless the event was approved by a human, the copies after
  180 days, and the private copies of Mastodon images (kept only to hash them) after 30 days. The
  hashes stay, because they are what catches a recycled photo.
- A citizen can **withdraw** a report with the device that filed it: its text and position are
  redacted, its photos deleted, and its event re-scored without it.

Two limits, stated plainly: the data lake's archived copy of the report stream is not rewritten by a
withdrawal (BUG-123), and the open Field Reports list still returns report text and coordinates
until it is put behind sign-in (BUG-124). Faces and number plates are not blurred, which is why
photos are shown only to signed-in officials.

### How do you know the audit trail wasn't edited?

Every decision writes a row into a **SHA-256 hash chain**: each row hashes the previous row's hash
together with its own content. Editing, deleting or reordering any row breaks the chain at that
row, and `GET /api/events/{id}/provenance` verifies the whole ledger from genesis and tells you
the first broken row. The database also has a trigger that rejects `UPDATE` and `DELETE` outright.

**The limit, stated plainly:** rows cut off the **end** of the chain, or a `TRUNCATE` of the whole
table, leave a chain that still validates. Detecting that needs an external anchor for the head
hash — publishing it somewhere we do not control — and that is not built. Anyone who asks this
question deserves that sentence.

### What happens if the internet drops during the demo?

Show them. Stop Redis and the platform reports `degraded` on `/healthz`, keeps a 200, and keeps
scoring — the cache and the dedup set fall back to process memory. Block Open-Meteo and the
weather factor goes `offline` with a reason, coverage drops from 0.80 to 0.55, and the event is
still created and still scored.

The frozen local matcher loads an authorized artifact without network access. The stack still
boots and deduplicates with the external network unavailable.

Losing Postgres prevents a report from being stored, so the API refuses it. Losing Redpanda stops
processing and makes `/healthz` unhealthy, but the newer transactional outbox retains already
stored reports for the relay to publish after the broker recovers; a Kafka outage no longer loses
those reports.

---

## About the data

### What is real and what is synthetic?

**Everything the platform serves is real, and nothing in the repository generates data for show.**

| Source | What it is |
|---|---|
| NDMA SACHET, every 5 min | Official IMD, CWC and state SDMA CAP warnings, in the issuer's words |
| Open-Meteo, every 10 min | Modelled 24 h rainfall at six fixed city points, into `station_readings` |
| METAR, every 10 min (when enabled) | Observed weather at India's aerodromes |
| Mastodon and Google News (when enabled) | Public #IMD and weather posts, and weather headlines: `SOCIAL_MEDIA` 0.50 and `NEWS_MEDIA` 0.55, second-hand by nature |
| People | Citizen reports through the dashboard's form or `POST /api/reports/submit`; official dispatches filed by a signed-in commander |
| Computed | Every confidence, severity, coverage, polygon, H3 cell and audit row, from the rows in the database |

**Hand-written, and never served:** two labelled test sets, `data/labelled/reports_v1.csv` (300
rows, frozen with the AI/ML layer, `DATASHEET.md`) and `backend/tests/fixtures/hazards_v1.csv`
(360 rows, `hazards_v1.md`), each documented as written for this project. Tests write only to
their own databases (`indra_test`, `indra_e2e`).

There is **no IMD sensor feed, no CWC gauge feed and no Twitter/X feed**: they need credentials
this team does not have, decided on 16 Sep. IMD and CWC appear only through the warnings they
publish on SACHET.

### Did you seed this dashboard for the presentation?

No, and the repository can no longer do it. On 25 Sep the demo mode and its fallback events, the
seed script, the scripted report generators and the start command that ran them, the dashboard's
invented operator profiles and station telemetry, and the AI-generated hazard photos were deleted.
An empty database shows an empty event list. What is on screen came from SACHET, Open-Meteo, METAR,
Mastodon, Google News, or a person who filed a report. The browser tests now run against their own
backend and database, so not even a test report reaches the live one.

### The README used to show 94% confidence and 127 signals. What happened?

It was removed on 21 Sep because none of it existed. There was no IMD, CWC or social feed behind
those "48 social media posts" and "2 CWC river gauges", image verification was offline, and the
**94% never came from the scoring engine**. It was replaced with the engine's real output for a set
of test reports, labelled as a worked example, together with a note saying what had been there
before, so the change was auditable rather than quiet. The note is in the README's git history and
the fabricated event is in the [bug register](bug-register.md). On 25 Sep the rest went too: the demo mode and its fallback
events, the seed script, the scripted report generators and the dashboard's invented operator
profiles.

That is worth saying out loud if anyone has seen the old version: we found it, and we took it out.

### What is Redis actually for?

Five short-lived jobs: the Open-Meteo caches keyed by H3 cell; the set of report ids already
broadcast to the dashboard, so a Kafka re-delivery does not show the same report twice even across
a restart; the per-message failure counter that sends a message to the dead-letter topic after
three attempts; the filter-options cache; and the memory of which event–evidence pairs late
corroboration has already evaluated.

Every one falls back to process memory if Redis is gone, and `/healthz` then says `degraded`. `redis-cli dbsize` after a few minutes of live traffic
shows it holding real keys.

---

## About the engineering

### How do you know any of this works?

**1,788 automated backend tests passing** (27 Sep 2026, the code now on `main`), run against a
separate database, with the network stubbed. The only two failures are in layer 4's package
(BUG-106). A Playwright suite runs against the dashboard on a disposable backend. But the more
honest answer is the second half:

**Every one of the most serious defects in this project was invisible to a green suite.** With 518
tests passing, the demo would still have opened on a fabricated `0.94 / AUTO_PUBLISHED` event,
because every test either seeded rows or asserted that the fallback worked — none asked whether
the fallback could be mistaken for a real result. It was found by running the demo. A blocking
model load that froze the entire API for 13 seconds was mis-rated as "slow first event" for five
days until a cold rehearsal timed out. A rainfall poller stored one hour of rain where the curve
expected a day of it, and 29 passing tests agreed with it, because they tested the response and
the defect was in the request.

On 22 Sep the same lesson came from the other side: the dashboard carried invented figures written
straight into its pages — an uptime, a radar feed, official bulletins — which no fallback test
could see because nothing fell back. They were found by reading every page, and the browser suite
now names each one.

So: tests, plus rehearsing from an empty volume, plus disbelieving any number that flatters us.
All three are in the [bug register](bug-register.md), with dates.

### What would you do next, with more time?

The planned phases come first. Phase 5 adds photo and video upload, a citizen withdrawing their
own report and per-source credibility administration. Phase 6 adds the analytics endpoints, bulk
ingestion of real archives and a load test on an isolated backend. After those, in order: anchor
the audit chain's head hash externally so a truncated tail is detectable; a reporter identity for
the citizen channel, so dedup can tell the same person repeating from a second witness; shared
pub/sub for the WebSocket fan-out, so more than one backend process can run; and MFA for operator
accounts.

Three items from the old version of this list were done on 22 Sep: every write is now token-gated,
clustering uses a true great-circle radius instead of degrees, and the dedup threshold was
measured and kept. On 25 Sep the demo accounts were retired: operators sign in, and no password
ships with the dashboard. All of it is in the [bug register](bug-register.md). None of it is a
surprise.

### What is the single weakest part?

The perception layer's **field validation** is the weakest part. Frozen local NLP, image and
anomaly components now produce advisory results, but synthetic-development evidence does not
establish real-disaster accuracy. The platform still relies on corroboration, geometry, rainfall
and human review for operational decisions; missing model inputs remain explicit.
