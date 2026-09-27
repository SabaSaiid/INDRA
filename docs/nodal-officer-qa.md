# INDRA — Questions You Will Be Asked, and the Honest Answer

**What this is:** the answer to every hard question a nodal officer, judge or teammate can ask
about this backend. Each one has a number, a file or a test behind it.

**The rule this whole project runs on:** *stating that a signal is absent is strictly better than
faking it.* Every answer below follows from that, including the uncomfortable ones. If you are
ever unsure what to say, say what is true and say where it is written down.

**Verified 21 Sep 2026; updated 22 Sep after the official-dispatch route and the dashboard audit.
Updated 25 Sep after every demo implementation was deleted.**
AI/ML evidence is separate and synthetic-development only: see [ML architecture](ML_ARCHITECTURE.md)
and [validation](ML_VALIDATION_REPORT.md).

---

## About the score

### How is confidence computed?

Six weighted factors. The score is the weighted mean **over the factors that actually reported**:

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

**Nobody. There is no alert engine.** INDRA sends no SMS, no email and no CAP broadcast, and has no
dispatch integration. It was scoped, then cancelled on 20 Sep rather than half-built.

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
of test reports, labelled as a worked example, and a note recording what was there before, so the
change is auditable rather than quiet. On 25 Sep the rest went too: the demo mode and its fallback
events, the seed script, the scripted report generators and the dashboard's invented operator
profiles.

That is worth saying out loud if anyone has seen the old version: we found it, and we took it out.

### What is Redis actually for?

Two jobs as of 21 Sep: the Open-Meteo cache keyed by H3 cell, and the set of report ids already
broadcast to the dashboard, so a Kafka re-delivery does not show the same report twice — now
across a restart, which process memory could not do.

Both fall back to memory if Redis is gone. `redis-cli dbsize` after a few minutes of live traffic
shows it holding real keys.

---

## About the engineering

### How do you know any of this works?

**948 automated backend tests**, run against a separate database, green with the network off, and
**26 browser tests** against the running dashboard. But the more honest answer is the second half:

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

In order: anchor the audit chain's head hash externally so a truncated tail is detectable; a
reporter identity for the citizen channel, so dedup can tell the same person repeating from a
second witness; shared pub/sub for the WebSocket fan-out, so more than one backend process can run;
and MFA for operator accounts.

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
