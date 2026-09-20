# INDRA — Questions You Will Be Asked, and the Honest Answer

**What this is:** the answer to every hard question a nodal officer, judge or teammate can ask
about this backend. Each one has a number, a file or a test behind it.

**The rule this whole project runs on:** *stating that a signal is absent is strictly better than
faking it.* Every answer below follows from that, including the uncomfortable ones. If you are
ever unsure what to say, say what is true and say where it is written down.

**Verified 21 Sep 2026.**

---

## About the score

### How is confidence computed?

Six weighted factors. The score is the weighted mean **over the factors that actually reported**:

```
confidence = Σ_online(weight × score) / Σ_online(weight)
```

For the demo event: `0.3987 / 0.80 = 0.4984`. The receipt prints every factor, its weight, its
score, its points and whether it was `computed` or `offline`, so the arithmetic can be checked on
the spot.

### What does `factor_coverage` mean?

**The share of the designed model that actually reported.** `0.80` means factors worth 20% of the
scale produced nothing, so the score is a mean over the 80% that did.

It exists because the alternative is worse. If an offline factor scores zero and keeps its weight,
a system missing two factors can never exceed 0.80 — and then a cluster with every available
signal at maximum still could not be auto-published. That is not honesty, it is a broken scale.
Re-normalising makes the score usable; publishing the coverage keeps it honest.

**Never quote the score without the coverage.**

### Why is the demo event only 0.4984? Isn't that a failure?

No — it is the system working.

That event is five unverified citizen reports, from one source type, in a city that got 0.2 mm of
rain. Nobody has confirmed it, no official channel has reported it, and there is no photograph.
A platform that called that a verified disaster would be the broken one.

Watch what it does instead: it quarantines the event and puts it in front of a human, and the
receipt shows exactly which evidence produced the number. **Add more independent reports and the
density factor rises. Add real rainfall and the weather factor rises.** Both are visible, live, in
the receipt.

### Could you not just raise the numbers?

Yes, trivially, and every one of them would be a lie. The curves are deliberately not tunable to
taste: rainfall is scored against **IMD's own published daily rainfall categories** (2.5 mm light,
15.6 moderate, 64.5 heavy, 115.6 very heavy, 204.5 extremely heavy). The severity depth cuts are
operational facts — 20 cm stops a two-wheeler, 60 cm floats a small car, 120 cm turns wading into
a rescue. They are numbers you are invited to argue with, which is the point of publishing them.

---

## About the AI

### Where is the AI?

**Deduplication runs on MiniLM sentence embeddings.** That is the model in the data path, and it
does real work: it is why five reports of one flood become one event instead of five.

Classification, anomaly detection and image analysis are designed and specified, and they are
**out of my layer** — I own data sources, ingestion, processing, geo-analytics, fusion, the data
platform and the real-time API. **Nothing in this demo pretends to be a model that isn't one.**

### Why are `vision_analysis` and `anomaly_detection` offline?

Because they are not built, and saying so is the design. The AI/ML layer left this project's scope
on 20 Sep. Rather than filling those factors with a plausible number, the receipt marks them
`offline` with a reason on every single event and lowers the stated coverage to 0.80.

Earlier in this project those two factors were filled with **random numbers**. Removing that is
what dropped the demo event's confidence from 0.76 to 0.43. We kept the lower, true number.

### You trained a classifier. Why isn't it running?

It was trained and **measured**, and it missed its acceptance gate: test macro-F1 0.787, but
NOT_RELEVANT recall 0.667 and 5 of 72 floods dismissed. Metrics are in
`backend/app/ml/artifacts/event_classifier_v1.metrics.json`.

A model that throws away one flood in fourteen does not go in front of a disaster response system.
`classify()` returns `None` and the code stays frozen in the repository so the measurement can be
audited.

---

## About the alerts

### Where are the alerts? Who gets the SMS?

**Nobody. There is no alert engine.** No SMS, no email, no dispatch integration, no
`GET /api/alerts`. It was scoped, then cancelled on 20 Sep rather than half-built.

The honest version of this platform's promise stops at: an event is verified, scored, explained,
and put in front of a commander who takes the decision. Automated dispatch on top of a 0.50
confidence score would be the most expensive mistake this system could make.

Nothing in the UI, the API or these documents claims an alert was sent.

---

## About trust and failure

### What stops a false alarm?

Four things, in order:

1. **Deduplication** — one incident reposted five times is one event, not five. A suppressed
   duplicate is never counted as corroboration and **never grades severity**, so a reposted
   alarming text cannot inflate an event.
2. **Coordinate validation** — anything outside India's bounds is rejected with a 422 and never
   stored. It is not snapped to the map.
3. **The corroboration rule** — a single report does not make an event. DBSCAN needs at least two.
4. **Human review** — nothing below 0.90 auto-publishes, and in practice nothing reaches 0.90,
   so every event goes to a person.

### What if a source lies?

Each source type carries a reliability prior — official dispatch 1.00, CWC 0.95, automatic weather
station 0.90, citizen app 0.60, social 0.50 — and each report is also scored on text quality. One
source cannot auto-publish an event on its own.

**Be precise about a limit here:** today every report submitted through the public endpoint is
stamped `CITIZEN_APP`, so source reliability reads 0.60 in a live demo and cannot be moved by the
text of a report. That is deliberate — letting a client declare itself an official source would
make the factor meaningless. It is recorded as BUG-025.

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

The embedding model loads from a local cache, so with the network fully off the stack still boots
and still deduplicates.

The one thing that is genuinely fatal is losing Postgres or Redpanda, and `/healthz` returns 503
within five seconds when either goes — because at that point a citizen's report would be lost, and
the platform should say so rather than accept it.

---

## About the data

### What is real and what is synthetic?

| Real | Synthetic |
|---|---|
| Open-Meteo rainfall — live, and polled every 10 minutes into `station_readings` | The demo report texts (five sentences about Kankarbagh) |
| Every confidence, severity, coverage and polygon — computed from the rows in the database | The seed dataset, which is labelled synthetic and whose script **refuses to run without `--synthetic`** |
| The audit chain, the H3 cells, the cluster geometry | The labelled ML dataset (300 rows, `DATASHEET.md`) |

There is **no IMD feed, no CWC feed and no social media feed.** Those integrations need API keys
this team does not have, decided on 16 Sep. Open-Meteo is the one external source, and it needs no
key, which is why it is the one that is real.

### The README used to show 94% confidence and 127 signals. What happened?

It was removed on 21 Sep because none of it existed. There was no IMD, CWC or social feed behind
those "48 social media posts" and "2 CWC river gauges", image verification was offline, and the
scoring engine **cannot reach 0.94**. It was replaced with a measured run, and a note recording
what was there before, so the change is auditable rather than quiet.

That is worth saying out loud if anyone has seen the old version: we found it, and we took it out.

### What is Redis actually for?

Two jobs as of 21 Sep: the Open-Meteo cache keyed by H3 cell, and the set of report ids already
broadcast to the dashboard, so a Kafka re-delivery does not show the same report twice — now
across a restart, which process memory could not do.

Both fall back to memory if Redis is gone. `redis-cli dbsize` after a demo run shows it holding
real keys.

---

## About the engineering

### How do you know any of this works?

**568 automated tests**, run against a separate database, green with the network off. But the more
honest answer is the second half:

**Every one of the most serious defects in this project was invisible to a green suite.** With 518
tests passing, the demo would still have opened on a fabricated `0.94 / AUTO_PUBLISHED` event,
because every test either seeded rows or asserted that the fallback worked — none asked whether
the fallback could be mistaken for a real result. It was found by running the demo. A blocking
model load that froze the entire API for 13 seconds was mis-rated as "slow first event" for five
days until a cold rehearsal timed out. A rainfall poller stored one hour of rain where the curve
expected a day of it, and 29 passing tests agreed with it, because they tested the response and
the defect was in the request.

So: tests, plus rehearsing from an empty volume, plus disbelieving any number that flatters us.
All three are in the [bug register](bug-register.md), with dates.

### What would you do next, with more time?

In order: gate the rest of the API behind the login flow the dashboard does not have yet; anchor
the audit chain's head hash externally so a truncated tail is detectable; re-project the clustering
into metres instead of degrees (~10% anisotropy at Patna's latitude); and get labelled data good
enough to move the dedup threshold off 0.88 with evidence rather than by feel.

All four are written down with severities in the [bug register](bug-register.md). None of them is
a surprise.

### What is the single weakest part?

The perception layer, and it is weak because it was cut rather than because it failed. There is no
classification of what a report describes, no verification of an image, no anomaly detection
against history. The platform compensates with corroboration, geometry, rainfall and a human —
and tells you, on every event, that it is doing so.
