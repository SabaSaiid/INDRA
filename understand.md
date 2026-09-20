# 🌩️ UNDERSTAND.md

## National Weather Big Data Analytics Platform — explained from zero

> **Purpose of this document:** teach the entire project to a person who has never written code before, while still explaining the real engineering underneath it.
>
> Think of this document as the **story, map, dictionary, and instruction manual** for the system we are building.

---

# 0. First: what are we building?

Imagine that a huge storm happens in India.

At almost the same moment, many different things happen:

- A weather station measures heavy rain.
- A citizen takes a photo of a flooded road.
- Someone writes a public post saying, “My street is underwater.”
- Another person reports thunder and strong wind.
- A government source publishes weather information.
- Some people repost the same old photograph.
- Some reports are wrong.
- Some reports describe the **same event** using different words.

So the computer receives a giant pile of information.

Our job is **not** simply to show all of that information on a map.

Our job is to answer:

> **“What is actually happening, where is it happening, how serious is it, how sure are we, what evidence supports it, and where did that evidence come from?”**

The official problem statement asks for a scalable national weather big-data platform that can ingest information from many internet-based sources, process it, store it, classify weather events, detect misleading information, remove duplicates, and provide real-time visualization and administration tools.

The project blueprint we are using goes further and proposes an event-driven architecture, deterministic verification, spatiotemporal clustering, multimodal deduplication, and auditable provenance.

The separate INDRA design shows a practical hackathon implementation using FastAPI, PostgreSQL/PostGIS, H3, Redpanda/Kafka, Redis, PyTorch/NLP and Next.js.

---

# 1. The easiest mental picture

Imagine a **factory**.

But instead of making cars, the factory makes **trusted weather events**.

```text
                  WEATHER INTELLIGENCE FACTORY

 Raw information → Cleaning → Understanding → Checking → One useful event
      │                 │             │           │            │
      │                 │             │           │            ▼
      │                 │             │           │       “Flood here”
      │                 │             │           │       Confidence 94/100
      │                 │             │           │
      ▼                 ▼             ▼           ▼
  many reports      same format    AI + rules   evidence
```

The important idea is this:

**A report is not the same thing as an event.**

For example:

```text
Report 1: “Road underwater near X”
Report 2: “Gandhi Maidan flooded”
Report 3: “Water entering shops”
Report 4: photo of flooded road
Report 5: heavy rainfall reading
Report 6: another post copied from Report 1
```

These may be:

- six pieces of information,
- four independent observations,
- one duplicate,
- and ultimately **one weather event**.

That transformation is the heart of the project.

---

# 2. The whole system in one picture

![Big picture](understand_diagrams/01_big_picture.png)

Read the picture from left to right:

| Part | Child-friendly meaning | Real technology |
|---|---|---|
| World | Where the information comes from | IMD, sensors, public datasets, citizen reports, permitted public/social sources |
| Kafka/Redpanda | A very fast conveyor belt | Apache Kafka or Redpanda |
| Processing | People who sort and understand the incoming information | Python, FastAPI, workers, ML, geospatial processing |
| Verification | A careful detective checking evidence | deterministic rules + evidence fusion |
| Databases | The project's memory | PostgreSQL/PostGIS, Redis, MinIO, later ClickHouse/Iceberg |
| Command Center | The control room | Next.js + TypeScript + maps/charts |

The system therefore has six big jobs:

1. **Collect** information.
2. **Normalize** it so different sources speak a common language.
3. **Understand** it using AI/ML and geospatial logic.
4. **Combine and verify** it.
5. **Remember** the evidence and history.
6. **Show** the useful result to humans.

---

# 3. What does “big data” mean here?

“Big data” does not simply mean “a big file.”

It means we may receive a huge amount of information, from many places, at high speed, in different shapes.

For example:

| Source | Example | Shape |
|---|---|---|
| Weather station | 92 mm rain | number + time + location |
| Citizen | “Street flooded” | text + GPS + photo |
| Public post | “Heavy rain in Patna” | text + time |
| Image | flooded road | image |
| Government data | warning issued | structured data |
| Historical dataset | rainfall records | tables/files |

The computer has to process these together.

That is why the architecture uses a **streaming/event system** instead of one giant script.

---

# 4. What is a “report”?

A **report** is one observation or piece of information.

For example:

```json
{
  "text": "Water entered the road",
  "time": "2026-09-14T15:42:00Z",
  "latitude": 25.5941,
  "longitude": 85.1376,
  "source": "citizen",
  "image": "flood_123.jpg"
}
```

Do not be scared by the curly braces.

This is simply a structured way of writing:

> “Someone reported flooding here, at this time, and attached this photo.”

### Important words

| Word | Simple meaning |
|---|---|
| Field | One piece of information, such as `latitude` |
| Record | One complete item, such as one report |
| Schema | The agreed list of fields and their meanings |
| Timestamp | Exact time something happened/was received |
| Metadata | Information about the information |
| Source | Where the report came from |

---

# 5. Report vs Event

This distinction is so important that it deserves its own section.

### Report

> “I see flooding.”

### Event

> “A flood incident is currently affecting this area.”

One event can have many reports.

```text
                         ONE FLOOD EVENT
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
       citizen report      image             sensor
           │                  │                  │
           ▼                  ▼                  ▼
       “street wet”     “cars underwater”   92 mm rain
```

The platform's intelligence comes from moving from **many reports** to **one event**.

---

# 6. The complete journey of information

![Event journey](understand_diagrams/02_event_journey.png)

This is the most important flow to understand.

## Step 1 — Raw report

Something comes in exactly as received.

Example:

> “Patna road is under water!!! 😨” + photo + GPS

We should preserve the original.

Why?

Because later we may need to prove exactly what entered the system.

---

## Step 2 — Normalize

Different sources use different names and formats.

Example:

```text
Source A: time = 14:32
Source B: time = 2026-09-14T14:32:00Z
Source C: date = 14/09/26
```

We convert them into a common form.

It is like putting three differently shaped puzzle pieces into the same standard box.

---

## Step 3 — Classify

The machine asks:

> “What is this about?”

Possible categories include:

- rainfall
- flood
- thunderstorm
- lightning
- heatwave
- fog
- dust storm
- strong wind
- cyclone
- hail
- cold wave
- other

This is where machine learning can help.

---

## Step 4 — Deduplicate

Suppose 100 people repost the same photograph.

We do **not** want 100 copies to become 100 separate events.

We therefore ask:

> “Is this exactly the same thing?”

and then:

> “Even if the words are different, is it probably the same thing?”

---

## Step 5 — Cluster

Now we ask:

> “Which reports describe the same real-world incident?”

For example:

```text
Report A → 25.5940, 85.1374
Report B → 25.5942, 85.1378
Report C → 25.5939, 85.1376
```

All are close together.

If they also happened close together in time and talk about flooding, the computer can group them into one **event cluster**.

This is called **spatiotemporal clustering**.

- Spatial = where
- Temporal = when
- Clustering = grouping similar things

---

## Step 6 — Verify

Now we become detectives.

We ask:

- Do authoritative weather observations support this?
- Are the coordinates reasonable?
- Is the timestamp sensible?
- Do independent sources agree?
- Does the image appear relevant?
- Are the values physically possible?

Only after this step should the system produce a strong alert.

---

## Step 7 — Create a verified event

Instead of showing 127 messy reports, the system can show:

```text
PATNA URBAN FLOOD

Severity: CRITICAL
Confidence: 94 / 100
Independent reports: 103
Authoritative confirmations: 3
Media evidence: 2
Status: VERIFIED
```

The exact numbers in the demonstration are scenario values; they are not a claim that every real event will achieve those numbers.

---

## Step 8 — Show the result

A person sees the important information on the dashboard.

That is the final purpose of the system.

---

# 7. Architecture: what does “architecture” mean?

Architecture is simply the **blueprint of the software**.

Imagine building a house.

You would ask:

- Where is the kitchen?
- Where are the bedrooms?
- How does electricity reach each room?
- Where does water enter the house?

Software has the same questions:

- Where does data enter?
- Where is it processed?
- Where is it stored?
- How do components communicate?
- How does the user see the result?

That plan is the software architecture.

---

# 8. Our architecture in layers

![System layers](understand_diagrams/03_system_layers.png)

The system can be explained as six layers.

| Layer | Job | Main technology |
|---|---|---|
| Frontend | What humans see | Next.js + TypeScript |
| Backend | Talks to the frontend and coordinates the system | FastAPI + Python |
| Stream | Moves incoming events reliably | Kafka / Redpanda |
| AI worker | Understands text/images | PyTorch + Transformers + OpenCV |
| Deterministic verifier | Checks hard facts with rules | Python + PostGIS |
| Data layer | Stores events/files/history | PostgreSQL/PostGIS + Redis + MinIO |

Later, for larger deployments, we can add ClickHouse and Iceberg for analytics and large-scale storage.

## The same thing, in the official nine layers

The six layers above are a teaching simplification. The team's **official system-architecture
diagram** splits the same system into nine layers, and that is the version to use when
talking to anyone outside the team. Here it is, with an honest mark on each one showing
whether it is actually built yet (checked against the code on 16 Sep 2026, end of backend sprint Day 3).

Legend: ✅ built · 🟡 partly built · ⬜ designed, not built yet

| # | Layer | What it does | Built? |
|---|---|---|---|
| 1 | **Data Sources** | Where information comes from: IMD/Govt APIs, weather APIs, public datasets, social media, citizen reports, images/videos | 🟡 **Citizen reports, plus rainfall from Open-Meteo** fetched whenever an event is scored. No other outside source is read yet. |
| 2 | **Data Ingestion** | The front door: REST API/webhooks, Kafka/Redpanda, batch and stream ingestion | 🟡 Live reports flow in through the API and the stream, and a report that couldn't be saved is told so (503) instead of being silently lost. Reports with coordinates outside India are refused. Batch loading is only a fake-data seed script, clearly labelled as such. |
| 3 | **Data Processing** | Tidying up: cleaning, normalization, deduplication, timestamps, geocoding, metadata | 🟡 Deduplication (a repeated report is remembered as a copy and never counted as extra evidence), coordinate checking and geocoding work, and every report gets a credibility score; cleaning and metadata extraction don't exist. |
| 4 | **AI / ML Layer** | Understanding: NLP classifier, event detection, fake detection, duplicate matching, image analysis, anomaly detection | 🟡 **Duplicate matching works.** A classifier that reads a report and names the flood type has been trained and tested on 300 practice reports we wrote, but it isn't good enough yet (it dismisses too many real floods as chatter, and it struggles with Hindi), so it's switched off. No image analysis, no anomaly detection — the receipt openly marks those as "offline". |
| 5 | **Geo-Analytics** | Everything about *where*: location mapping, spatial clustering, heatmaps, event boundaries, risk zones, time-space trends | ✅ Clustering and mapping are real; heatmaps and risk zones aren't built. |
| 6 | **Event Fusion Engine** | The heart: correlate observations, merge duplicates, calculate confidence, determine severity, build the weather event | ✅ Working, with no random numbers: 4 of the 6 confidence factors are real measurements and 2 are honestly marked offline. A human's approval is never undone by later reports. |
| 7 | **Data Platform** | The memory: PostgreSQL+PostGIS, Redis, object storage, historical datasets | 🟡 The database is real, and the audit log is a working tamper-evident hash chain. Redis runs but nothing uses it; object storage isn't deployed. |
| 8a | **Real-Time API** | Serving it out: FastAPI, WebSocket, REST | ✅ Working. A commander can approve or reject an event, and that endpoint (plus provenance) requires login; the older dashboard endpoints still don't. |
| 8b | **Alert Engine** | Telling people: critical events, SMS/email, dashboard alerts | ⬜ **Does not exist at all.** |
| 9 | **IMD Command Center** | The control room humans look at | 🟡 The dashboard is built; risk zones and critical alerts have nothing behind them. |

**If you remember one thing from this section:** the middle of the system — ingestion,
clustering, fusion, and serving — genuinely works. A citizen report really does travel all
the way through and come out as a scored event, a human can approve it, and every decision is
written to a tamper-evident audit log. What is missing is at the two ends: we pull in only one
outside source (rainfall, layer 1), and we don't yet *send alerts out* (layer 8b).
And the "AI" layer is thinner than its name suggests: it matches duplicates. A text
classifier has been built and measured, but it missed its quality bar, so it stays switched off.

---

# 9. What is a frontend?

The **frontend** is what a human sees and touches.

Think of:

- buttons,
- maps,
- tables,
- charts,
- alerts,
- search boxes,
- filters.

Our frontend uses:

### Next.js

A framework for building the web application.

### TypeScript

JavaScript with stronger rules that help developers avoid many mistakes.

### MapLibre

Used to draw interactive maps.

### ECharts

Used to draw charts and graphs.

The frontend should feel like a **weather command center**, not a normal consumer weather app.

---

# 10. What is a backend?

The backend is the part the user usually does not see.

Imagine a restaurant:

```text
Customer = frontend
Kitchen = backend
Food = result/data
```

The customer says:

> “Show me critical flood events in Bihar.”

The frontend sends that request to the backend.

The backend then:

1. checks the request,
2. asks the database,
3. gets the events,
4. returns the results.

We use **FastAPI** for this.

FastAPI is a Python framework for building APIs.

---

# 11. What is an API?

API means **Application Programming Interface**.

That sounds complicated, but the idea is simple.

An API is like a waiter in a restaurant.

You do not walk into the kitchen.

You tell the waiter:

> “Bring me the flood events.”

The waiter communicates with the kitchen and brings back the result.

In software:

```text
Frontend → API → Backend/Database → API → Frontend
```

Example:

```text
GET /events?state=Bihar&severity=critical
```

Meaning:

> “Give me critical events in Bihar.”

---

# 12. What is Kafka / Redpanda?

![Kafka conveyor](understand_diagrams/04_kafka.png)

Imagine a very fast conveyor belt in a factory.

Reports arrive from many sources.

Instead of forcing one worker to process everything immediately, we place the reports on the conveyor belt.

Then different workers can take jobs from the belt.

That is the basic idea of **Kafka**.

**Redpanda** is another system that follows a very similar event-streaming model and is convenient for lightweight deployments.

### Why do we need a streaming system?

Because weather events can arrive in bursts.

For example:

```text
Normal:
10 reports/minute

Sudden storm:
10,000 reports/minute
```

A queue helps absorb the sudden rush.

### Simple rule

> **Kafka does not decide whether a report is true. It helps move the report safely and quickly.**

That distinction matters.

---

# 13. What is a worker?

A **worker** is a program that does one kind of job.

For example:

```text
NLP Worker       → reads text
Vision Worker    → reads images
Clustering Worker → groups events
Verification Worker → checks evidence
```

Imagine a team in a factory:

| Worker | Job |
|---|---|
| Text worker | Reads text |
| Image worker | Looks at photos |
| Map worker | Checks location |
| Verification worker | Checks evidence |

This is much easier to manage than one giant program doing everything.

---

# 14. What is AI/ML doing here?

Machine learning is best used for problems where the answer is difficult to write as a simple rule.

### Good ML jobs

- Understand messy human language.
- Recognize what an image contains.
- Find semantically similar reports.
- Detect unusual patterns.
- Help classify weather events.

### Bad ML jobs

Do not ask a language model:

> “Is 5000 mm of rainfall physically valid?”

That should be checked with deterministic rules and domain constraints.

The blueprint deliberately separates AI/ML from deterministic validation.

---

# 15. NLP: teaching the computer to understand text

NLP means **Natural Language Processing**.

It deals with human language.

Suppose the report says:

> “Bhai road pe ghutne tak paani hai.”

Another report says:

> “Street flooded with water.”

Another says:

> “Water entering shops.”

Different words can still describe the same event.

An NLP system can extract:

```text
EVENT = FLOOD
SEVERITY = HIGH
LOCATION = inferred/mentioned location
CLAIM = water inundation
```

Possible technologies:

- Hugging Face Transformers
- multilingual transformer models
- sentence embeddings

The model is a tool, not an oracle.

Its output becomes **evidence** for later reasoning.

---

# 16. Computer vision: teaching the computer to look

A photo can contain useful information.

A computer-vision model may estimate whether an image appears consistent with:

- flood water,
- storm damage,
- road inundation,
- other relevant visual categories.

Possible technologies:

- PyTorch
- OpenCV
- image-embedding models
- object detection/classification models

Important:

A vision model saying:

> “This looks like flood water.”

does **not** prove:

> “This photo was taken today in Patna.”

We still need timestamp, location, source and corroboration.

---

# 17. What is an embedding?

This is one of the most useful AI ideas in the whole system.

Imagine every sentence becomes a point in a huge invisible mathematical space.

Sentences with similar meanings land near each other.

```text
“Road is flooded”          ●
“Water covering the street”   ●
“Street underwater”        ●

“Temperature very high”                         ●
“Dense fog near airport”                              ●
```

The computer can compare the distance between these points.

This helps us find **semantic duplicates**.

---

# 18. Deduplication: removing repeated information

![Deduplication concept](understand_diagrams/02_event_journey.png)

Deduplication means preventing the same information from being counted repeatedly.

We use multiple levels.

### Level 1 — Exact match

If two files have the exact same content hash, they may be identical.

### Level 2 — Image similarity

Two photos may have different filenames but still be the same image.

### Level 3 — Semantic similarity

Two text reports may use different words but mean the same thing.

### Level 4 — Spatiotemporal similarity

Two reports may refer to the same event because they are:

- very close in space,
- close in time,
- and about the same event type.

The strongest system combines these checks.

---

# 19. What is H3?

H3 is a system for dividing the world into hexagon-shaped map cells.

Think of placing a honeycomb over India.

```text
       ⬡ ⬡ ⬡
     ⬡ ⬡ ⬡ ⬡
       ⬡ ⬡ ⬡
     ⬡ ⬡ ⬡ ⬡
```

Each report can be assigned to a cell.

That makes it easier to ask:

> “How many flood reports appeared in this small area?”

H3 is especially useful for fast spatial aggregation.

---

# 20. What is PostGIS?

PostgreSQL is a database.

PostGIS adds advanced geographical abilities to PostgreSQL.

Instead of storing only:

```text
name = Patna
```

we can store:

```text
latitude = 25.5941
longitude = 85.1376
```

and then ask questions such as:

> “Which reports are within 2 km?”

or:

> “Which events lie inside this district?”

This makes PostGIS one of the most important pieces of the project.

---

# 21. What is spatiotemporal clustering?

This sounds scary but means something simple.

**Spatio** = where.

**Temporal** = when.

**Clustering** = grouping.

Suppose we have:

```text
A: flood report at 15:00 near point X
B: flood report at 15:02 near point X
C: flood photo at 15:03 near point X
D: rain sensor at 15:04 near point X
```

The system may conclude:

> These observations are likely connected.

This creates an event cluster.

The blueprint specifically proposes this style of processing, including database/geospatial clustering.

---

# 22. Verification: the detective part

![Verification pipeline](understand_diagrams/05_verification.png)

Verification is where the system asks:

> “How much should I trust this event?”

A useful workflow has several stages.

### Stage 1 — Format check

Is the data shaped correctly?

Example:

- Is latitude actually a number?
- Is the timestamp valid?
- Does the record contain required fields?

### Stage 2 — Deterministic / physics checks

Does the value make sense under known constraints?

For example:

- rainfall cannot be negative,
- a coordinate must fall within valid geographic ranges,
- units must match,
- timestamps must be sensible,
- station values must satisfy configured quality bounds.

### Stage 3 — Consensus check

Do independent sources agree?

Example:

```text
citizen report       ✓
weather station      ✓
second citizen       ✓
radar/official feed  ✓
```

Confidence becomes stronger.

### Stage 4 — Evidence score

The system combines the available evidence into an explainable score.

---

# 23. Confidence and severity are different

This is a very important design rule.

### Severity asks:

> “How dangerous is this event if it is real?”

### Confidence asks:

> “How sure are we that this event is actually happening?”

These are different questions.

Example:

```text
ONE UNCONFIRMED DAM-BREAK REPORT

Severity: CRITICAL
Confidence: LOW
```

That should not automatically be treated as a confirmed disaster.

Instead:

> **High severity + low confidence = immediate human review.**

Compare:

```text
100+ independent flood reports
+ station agreement
+ location agreement
+ image evidence

Severity: CRITICAL
Confidence: HIGH
```

That is a very different situation.

The INDRA design explicitly uses a 2×2 confidence/severity matrix for this reason.

---

# 24. The Verification Receipt

One of the strongest ideas in the project is to avoid showing only:

> Confidence = 94%

Instead, show **why**.

Example:

| Evidence factor | Weight | Example |
|---|---:|---|
| Authoritative agreement | 25 | weather observation agrees |
| Independent reports | 20 | many independent reports |
| Location/time consistency | 20 | reports cluster together |
| Image evidence | 10–15 | visual model supports claim |
| Source reliability | 10–15 | trusted sources |
| Historical anomaly | 5 | unusual compared with baseline |
| Deterministic validation | 10 | hard checks passed |
| **Total** | **100** | **explainable confidence** |

The exact weights should be treated as a **design choice to be calibrated and benchmarked**, not as a scientifically proven universal formula.

---

# 25. What is deterministic validation?

“Deterministic” means:

> Give the same input to the same rule → get the same answer.

Example:

```python
def valid_latitude(latitude):
    return -90 <= latitude <= 90
```

The computer does not “guess.”

It checks the rule.

This is especially valuable for hard constraints and numerical sanity checks.

### The rule of thumb

```text
AI/ML → helps interpret messy information
Rules  → enforce hard guarantees and known constraints
```

Use both.

Do not make one pretend to be the other.

---

# 26. What is provenance?

![Provenance chain](understand_diagrams/06_provenance.png)

Provenance means:

> **“Where did this result come from?”**

Imagine the dashboard says:

```text
FLOOD EVENT #1842
Confidence: 94
```

A serious user should be able to click it and see:

```text
Alert
 ↓
Verification
 ↓
Event cluster
 ↓
Reports
 ↓
Original raw inputs
```

That is provenance.

---

# 27. What is a hash?

A hash is like a digital fingerprint.

A program takes some data and creates a fixed-looking code.

If the data changes, the fingerprint changes.

Think of it like sealing a box:

```text
Original data
    ↓
 SHA-256
    ↓
Digital fingerprint
```

We can use hashes to build an audit trail.

A simplified chain might look like:

```text
Raw report → Hash A
      ↓
Normalize → Hash B
      ↓
Cluster   → Hash C
      ↓
Verify    → Hash D
      ↓
Alert     → Hash E
```

This does not magically make the data true.

It helps us prove that the recorded processing history has not silently changed.

### Important distinction

**Cryptographic provenance is not the same as blockchain.**

We do not need blockchain merely to create an auditable chain of hashes.

---

# 28. Our databases: the project's memory

![Database roles](understand_diagrams/07_databases.png)

Different databases have different jobs.

| Technology | What it is like | Main job |
|---|---|---|
| PostgreSQL | Main notebook | events, reports, users, relationships |
| PostGIS | Notebook with map powers | location and geospatial queries |
| Redis | Sticky notes beside you | very fast temporary data/cache |
| MinIO/S3 | Big storage cupboard | photos, videos, raw files |
| ClickHouse* | Super-fast statistics room | large-scale analytics |
| Iceberg* | Organized data-lake filing system | historical/replayable analytical data |

`*` means these are especially useful for the larger scale-out architecture, but are not required for the first working prototype.

---

# 29. Why not put everything in one database?

Because different jobs need different kinds of storage.

Imagine a library.

You would not store:

- a small sticky note,
- a 5 GB video,
- a list of millions of numbers,
- and a detailed map

in exactly the same physical way.

Each tool should do the job it is good at.

---

# 30. What is ClickHouse?

ClickHouse is a database designed for very fast analytics over large amounts of data.

Imagine asking:

> “How many flood reports arrived in every Indian state during the last 24 hours?”

You may have millions of records.

An analytical database can answer this type of question efficiently.

We do not need it to make the first demo work.

We add it when scale and analytics matter.

---

# 31. What is a data lake / lakehouse?

A data lake is a large place for storing data in its original or near-original form.

A lakehouse adds more structure and data-management features so the same stored data can support analytics and downstream processing.

A useful mental model is:

```text
BRONZE
Raw data exactly as received
       ↓
SILVER
Cleaned + normalized + enriched
       ↓
GOLD
Trusted events + useful analytics
```

The blueprint explicitly uses this Bronze/Silver/Gold idea.

This is useful because you should never throw away the original evidence just because you cleaned it later.

---

# 32. Why keep the raw data?

Because a future investigator may ask:

> “Why did the system make this decision?”

Without the raw input, we cannot properly reconstruct the decision.

So we preserve:

```text
RAW
 ↓
TRANSFORMED
 ↓
VERIFIED
 ↓
DISPLAYED
```

That is one of the most important ideas in trustworthy data systems.

---

# 33. What is a dashboard?

A dashboard is the control panel for humans.

The dashboard should answer, at a glance:

```text
Where are the serious events?
What type are they?
How severe are they?
How confident are we?
How many sources support them?
What changed recently?
Can I inspect the evidence?
```

A strong dashboard might have:

### Top row

```text
LIVE SOURCES   ACTIVE EVENTS   CRITICAL EVENTS   SYSTEM HEALTH
```

### Center

Large India map.

### Right side

List of critical events.

### Bottom

Charts:

- events over time,
- event types,
- state/district counts,
- verification states,
- source health.

---

# 34. Admin panel

The problem statement asks for administration and monitoring features.

An administrator should be able to:

- filter by date,
- filter by location,
- filter by event type,
- view verification status,
- inspect sources,
- inspect events,
- review suspicious cases,
- monitor system health.

A human reviewer should be able to override or annotate an event when required, while preserving the audit trail.

---

# 35. What is WebSocket?

Normally, a browser asks the server:

> “Anything new?”

Then the server answers.

A WebSocket allows the server to keep a live connection and push updates when something happens.

Imagine:

```text
Old method:
Browser → “Anything new?”
Server  → “No.”
Browser → “Anything new?”
Server  → “Yes.”

WebSocket:
Server → “NEW CRITICAL EVENT!”
```

This is useful for live dashboards.

---

# 36. What is Docker?

Docker packages software into containers.

A container is like a small box containing:

- the program,
- its dependencies,
- the setup needed to run it.

Instead of saying:

> “Install this exact version of Python, this database, this library, this configuration...”

we can often say:

> “Start the containers.”

For a hackathon, this dramatically reduces setup problems.

---

# 37. Why use Docker Compose?

Docker Compose lets us start multiple pieces together.

For example:

```text
PostgreSQL
Redis
Redpanda
Backend
Frontend
Worker
```

with one command:

```bash
 docker compose up
```

This is one of the practical strengths of the INDRA-style hackathon architecture.

---

# 38. What is Kubernetes?

Kubernetes is for managing containers at larger scale.

Imagine one restaurant becoming 500 restaurants.

You now need systems for:

- placing workers,
- replacing broken workers,
- scaling up during rush hour,
- scaling down when quiet.

Kubernetes helps do this for software containers.

### For our project

Do not make Kubernetes a requirement for the first prototype.

Design so the project **can** move to Kubernetes later.

---

# 39. Why we should not start with 15 microservices

A microservice is simply a separately deployable software component.

That can be useful at huge scale.

But during a hackathon, too many services mean:

- more configuration,
- more network problems,
- more deployment problems,
- more logs,
- more things to break.

Therefore, the practical first architecture is a **modular monolith + dedicated AI worker + event stream**.

That gives us clean boundaries without unnecessary operational pain.

---

# 40. What is a modular monolith?

One application can still have separate internal modules.

Think of a school building:

```text
ONE BUILDING
├── office
├── library
├── science room
└── computer room
```

It is one building, but each room has a clear purpose.

Similarly:

```text
FASTAPI APPLICATION
├── authentication
├── reports
├── events
├── alerts
├── analytics
└── provenance
```

This is a sensible first deployment model.

---

# 41. Security: why it matters

Weather data can become important during emergencies.

We therefore need basic security principles:

- authenticated administrative users,
- role-based permissions,
- protected APIs,
- input validation,
- secret management,
- rate limits where needed,
- audit logs.

### Role-based access control

Different people can have different powers.

| Role | Example permission |
|---|---|
| Viewer | see events |
| Analyst | inspect evidence, review events |
| Admin | manage configuration and users |
| System operator | monitor infrastructure |

---

# 42. What happens if an external API stops working?

This is a major practical problem.

Imagine the system normally receives a weather feed.

Then the API crashes.

If our whole demo depends on that API, the system can appear broken.

So we need a **replay/mock data generator**.

It can replay historical or synthetic scenarios into the exact same ingestion pipeline.

```text
LIVE MODE
External source → Kafka → processing

FAILSAFE MODE
Replay generator → Kafka → same processing
```

This is important:

**The fallback should still use the real pipeline.**

Do not create a fake shortcut that directly writes the final event into the database.

---

# 43. Why the demo must use the real pipeline

Bad demo:

```text
Button click → directly insert “94% verified flood” into database
```

It looks impressive but proves almost nothing.

Good demo:

```text
Generate 127 reports
        ↓
Kafka
        ↓
classification
        ↓
deduplication
        ↓
clustering
        ↓
verification
        ↓
real event
        ↓
dashboard
```

Now the judges can see the system actually working.

---

# 44. The demo story

![Demo storyline](understand_diagrams/08_demo.png)

The demonstration should tell a simple story.

### Scene 1 — Calm

The dashboard shows normal conditions.

### Scene 2 — Sudden spike

A replay script injects a weather incident with many reports.

### Scene 3 — Chaos arrives

The system receives duplicates, conflicting messages and useful evidence.

### Scene 4 — The machine organizes the chaos

Reports are classified, deduplicated and spatially clustered.

### Scene 5 — Evidence agrees

Authoritative data and other sources support the incident.

### Scene 6 — Verified event

A single incident appears on the map.

### Scene 7 — Explain it

The judge clicks the event and sees the evidence receipt.

### Scene 8 — Trace it

The judge clicks provenance and sees the path back to raw data.

That last part is particularly important because it shows **trust**, not just visualization.

---

# 45. What does the code look like?

You do not need to know every line immediately.

Think of code as instructions for a machine.

Example:

```python
if report.event_type == "FLOOD":
    send_to_flood_pipeline(report)
```

Read it like English:

> “If the report says FLOOD, send it to the flood pipeline.”

Another example:

```python
def valid_latitude(latitude):
    return -90 <= latitude <= 90
```

Read it as:

> “Create a rule named `valid_latitude` that says latitude must be between -90 and 90.”

You do not need to become an expert programmer to understand the architecture.

You need to understand:

- what data enters,
- what each module does,
- what comes out,
- and why.

---

# 46. What is a Python module?

A module is just a file containing related code.

For example:

```text
verification.py
```

may contain verification logic.

```text
clustering.py
```

may contain clustering logic.

```text
reports.py
```

may contain report API routes.

Organizing code this way makes the system easier to understand and maintain.

---

# 47. What is a library?

A library is code that someone else has already written that we can reuse.

Examples:

| Library | What it helps with |
|---|---|
| FastAPI | APIs |
| Pydantic | data validation |
| SQLAlchemy | database access |
| GeoPandas | geospatial data |
| Shapely | geometry |
| PyTorch | machine learning |
| OpenCV | image processing |
| Transformers | language/vision models |
| Redis client | cache |
| Kafka client | streaming |

Using libraries does not mean we are cheating.

Almost all modern software is built from libraries.

---

# 48. What is a database query?

A query asks the database a question.

For example:

> “Give me all critical flood events in Bihar today.”

The database executes a query and returns the answer.

You can think of SQL as asking structured questions.

Example:

```sql
SELECT *
FROM events
WHERE event_type = 'FLOOD'
  AND severity = 'CRITICAL';
```

Read it as:

> “Find all events whose type is FLOOD and severity is CRITICAL.”

---

# 49. What is geospatial data?

Geospatial data is data tied to a location.

Examples:

- latitude/longitude,
- district boundary,
- road,
- river,
- station location,
- hazard polygon.

A normal database might know:

```text
Patna
```

A geospatial database can also know:

```text
Patna = shape on Earth
```

That is why PostGIS matters.

---

# 50. What is an event polygon?

Sometimes one point is not enough.

Suppose a flood affects an entire neighborhood.

We may want to draw an area around the affected reports.

That area becomes an **event polygon** or hazard area.

It can help humans see:

> “This is the affected region, not just one GPS point.”

---

# 51. What is anomaly detection?

An anomaly is something unusual.

Example:

Historical rainfall:

```text
Typical: ~35 mm

Observed today: 140 mm
```

That does not automatically mean a disaster happened.

But it is useful evidence that something unusual may be happening.

A model such as Isolation Forest can help detect unusual patterns.

Again:

> anomaly ≠ proof

It is evidence, not a final verdict.

---

# 52. What is source reliability?

Not every source deserves the same weight.

For example:

| Source | Potential reliability role |
|---|---|
| Official calibrated station | very strong for its measured variable |
| Official warning | strong for published warning information |
| Reputable public dataset | depends on dataset |
| Known citizen contributor | useful but still needs context |
| Anonymous public post | useful signal, weaker alone |
| Reposted old image | potentially misleading |

The system should not decide reliability by emotion.

It should use explicit policies and measurable signals.

---

# 53. Why “independent sources” matter

Suppose 100 posts all copy the same original post.

That is **not** the same as 100 independent observations.

True corroboration means different sources provide independent evidence.

That is why deduplication and source lineage matter before we calculate confidence.

Otherwise the system could accidentally say:

> “100 people agree!”

when in reality one person posted and 99 people copied it.

---

# 54. What is a confidence score?

A confidence score is a summary of evidence strength.

For example:

```text
94 / 100
```

means:

> “Based on the defined evidence rules, the system considers this event highly supported.”

It does **not** mean:

> “There is a universal scientific law saying the event is exactly 94% true.”

The score must be:

- explainable,
- testable,
- calibrated using evaluation data,
- and accompanied by the evidence that produced it.

---

# 55. What is calibration?

Suppose the system says “90% confident” 100 times.

If 90 of those cases really are correct, the score is well calibrated.

If only 40 are correct, the system is overconfident.

Calibration is therefore important if we want to present confidence as a meaningful measure.

---

# 56. What are evaluation metrics?

We should measure each important subsystem.

| Component | Example metric |
|---|---|
| Ingestion | throughput, latency, failed messages |
| Classification | precision, recall, F1 |
| Deduplication | duplicate removal quality |
| Clustering | cluster precision/recall or event matching quality |
| Verification | precision, recall, false-positive rate |
| API | p50/p95 response latency |
| Dashboard | update latency |
| System | uptime/error rate |

The blueprint proposes target metrics such as ingestion latency, classification F1, false-positive rate and API response time. Those numbers should be treated as **targets to benchmark**, not as facts we can claim in advance.

---

# 57. What is F1 score?

F1 combines two ideas:

### Precision
When we say “this is a flood,” how often are we right?

### Recall
Of all the real floods, how many did we successfully detect?

F1 balances both.

Think of it as asking:

> “Did we avoid too many false alarms without missing too many real events?”

---

# 58. What is latency?

Latency means **how long something takes**.

Example:

```text
Report arrives at 15:00:00
Dashboard updates at 15:00:02

Latency = 2 seconds
```

For streaming systems, lower latency is usually better, but only if correctness remains strong.

A 1 ms system that produces wrong alerts is worse than a 2-second system that produces reliable ones.

---

# 59. Throughput

Throughput means:

> “How much can the system process per unit of time?”

Example:

```text
10,000 reports / second
```

is a throughput statement.

Latency and throughput are different.

- Latency = how quickly one item moves through.
- Throughput = how many items we can handle.

---

# 60. Horizontal scaling

Suppose one worker can process 100 reports/second.

If we add another worker:

```text
Worker A = 100
Worker B = 100
Total ≈ 200
```

With more workers, the system can process more work.

That is the basic idea of **horizontal scaling**.

Streaming infrastructure makes this style of scaling practical.

---

# 61. Why event-driven architecture?

Traditional program:

```text
Step 1
  ↓
Step 2
  ↓
Step 3
  ↓
Step 4
```

Event-driven system:

```text
Something happens
      ↓
EVENT
      ↓
Interested workers react
```

Example:

```text
new report
   ↓
classification worker
   ↓
dedup worker
   ↓
cluster worker
   ↓
verification worker
```

This is a natural fit for real-time data.

---

# 62. Why not simply use one giant Python script?

You could for a tiny demo.

But it becomes difficult when:

- data arrives continuously,
- several sources arrive at once,
- some jobs are slow,
- ML uses GPUs,
- some components need scaling,
- you need auditability.

The architecture gives us clean boundaries.

---

# 63. The project's “brain” vs “body” analogy

This analogy makes the architecture easier to remember.

### Body = infrastructure

- Kafka
- databases
- servers
- network
- storage

### Brain = intelligence

- NLP
- computer vision
- clustering
- anomaly detection
- evidence fusion

### Eyes and screen = frontend

- maps
- charts
- alerts

### Memory = databases

- reports
- events
- evidence
- history

### Rulebook = deterministic verification

- geographic rules
- physical constraints
- schema checks
- data quality rules

All of them work together.

---

# 64. Final architecture, explained as a story

Here is the whole system in plain English:

> A weather signal arrives.
>
> Kafka safely receives it.
>
> FastAPI and workers route the information.
>
> AI reads the text or image and extracts meaning.
>
> Geospatial code checks where it happened.
>
> Deduplication removes repeated copies.
>
> Clustering groups nearby related reports.
>
> Deterministic rules check hard facts.
>
> The verification engine combines the evidence.
>
> PostgreSQL/PostGIS stores the event and its location.
>
> MinIO stores large files such as photos.
>
> Redis keeps frequently used information fast.
>
> The provenance system records how the result was produced.
>
> The frontend shows a live map and explains the event to a human.

That is the entire machine.

---

# 65. The recommended first version

We do **not** need every future technology on the first day.

### Build first

```text
Next.js + TypeScript
FastAPI + Python
Kafka / Redpanda
PostgreSQL + PostGIS
Redis
MinIO
PyTorch / Transformers / OpenCV
H3
Docker Compose
```

### Add when needed

```text
ClickHouse
Iceberg
Flink
Kubernetes
MLflow
advanced distributed inference
```

The reason is simple:

> **First make the entire machine work. Then make each part bigger and faster.**

---

# 66. The exact data flow we want

```text
                   ┌───────────────────┐
                   │   SOURCE DATA     │
                   └─────────┬─────────┘
                             │
                             ▼
                  ┌────────────────────┐
                  │ Kafka / Redpanda   │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Normalize           │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ AI / ML             │
                  │ text + image        │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Deduplicate         │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Spatial + time      │
                  │ clustering           │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Deterministic rules │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Verification        │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Trusted event       │
                  └─────────┬──────────┘
                            │
             ┌──────────────┼───────────────┐
             ▼              ▼               ▼
        PostgreSQL       MinIO           Analytics
             │
             ▼
       Next.js Dashboard
```

---

# 67. The three most important ideas to remember

## Idea #1 — Streaming

Information does not arrive once.

It keeps arriving.

So the platform is built around a stream of events.

## Idea #2 — Evidence fusion

One report is not enough.

The platform should combine independent evidence.

## Idea #3 — Auditability

When the system creates an important alert, a person should be able to ask:

> **“Why?”**

and trace the answer back to the original evidence.

Those three ideas make the project much stronger than a simple weather dashboard.

---

# 68. What we should never claim without evidence

Do not claim:

- 100% prediction accuracy.
- The system replaces IMD meteorologists.
- Every social-media post is trustworthy.
- An ML model can prove an image is real or fake by itself.
- A confidence score is automatically equal to a real-world probability unless calibrated.
- National-scale throughput has been achieved unless benchmarked.
- External APIs are always available.
- A cryptographic hash means the original source itself was truthful.

The correct positioning is:

> **A decision-support and intelligence system that combines heterogeneous weather information into auditable, evidence-backed events.**

---

# 69. What is actually novel?

The novelty is not:

> “We used Next.js.”

Technology names alone do not win a competition.

The stronger novelty story is:

### 1. Streaming event intelligence

Continuous incoming signals are transformed into incidents.

### 2. Multimodal understanding

Text + images + sensors + geospatial information are considered together.

### 3. Deterministic safety layer

AI is not allowed to make every decision by itself.

### 4. Event resolution

Many noisy signals are combined into one meaningful incident.

### 5. Explainable evidence

The system says **why** it trusts an event.

### 6. Auditable provenance

A final alert can be traced back to its inputs and processing steps.

---

# 70. Competition strategy

Our goal should be:

> **Build one complete, believable vertical slice before building dozens of features.**

The vertical slice is:

```text
Input
 ↓
Kafka
 ↓
AI
 ↓
Dedup
 ↓
Cluster
 ↓
Verify
 ↓
Store
 ↓
Dashboard
 ↓
Provenance
```

Once that works perfectly, expand it.

Do not build:

```text
50 disconnected features
```

Build:

```text
1 strong end-to-end system
```

---

# 71. Recommended build order

## Phase 1 — Foundation

1. Docker Compose
2. PostgreSQL/PostGIS
3. Redis
4. Kafka/Redpanda
5. FastAPI
6. Next.js
7. basic health checks

## Phase 2 — Canonical data

1. report schema
2. event schema
3. source schema
4. evidence schema
5. database tables

## Phase 3 — Real pipeline

1. ingestion
2. normalization
3. classification
4. deduplication
5. clustering
6. event creation

## Phase 4 — Verification

1. deterministic rules
2. source reliability
3. consensus
4. confidence score
5. evidence receipt

## Phase 5 — Trust

1. hashes
2. provenance chain
3. lineage UI

## Phase 6 — Command center

1. live map
2. event list
3. filters
4. event details
5. verification receipt
6. provenance inspector

## Phase 7 — Demo

1. replay scenario
2. load spike
3. duplicates
4. verification
5. dashboard alert
6. provenance trace

---

# 72. What Claude Code will eventually receive

This document is the **understanding layer**.

It should be followed by more precise engineering documents:

```text
UNDERSTAND.md
    ↓
REQUIREMENTS.md
    ↓
ARCHITECTURE.md
    ↓
DATA_MODEL.md
    ↓
EVENT_SCHEMA.md
    ↓
VERIFICATION.md
    ↓
PROVENANCE.md
    ↓
API.md
    ↓
DEMO.md
```

### Why separate them?

Because “understanding” and “implementation” are different jobs.

This document answers:

> What are we building and why?

The architecture document answers:

> Exactly how do the pieces fit together?

The schema document answers:

> Exactly what shape should the data have?

The API document answers:

> Exactly how do programs communicate?

---

# 73. If you remember only one diagram

```text
               MANY NOISY REPORTS
                       │
                       ▼
              ┌────────────────┐
              │      KAFKA     │
              │  move safely   │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │      AI/ML     │
              │ understand     │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │  DEDUPLICATE   │
              │ remove copies  │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │    CLUSTER     │
              │ group one      │
              │ incident       │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │    VERIFY      │
              │ check evidence  │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │  TRUSTED EVENT │
              │ confidence +   │
              │ severity +     │
              │ evidence       │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │   DASHBOARD    │
              │ human action   │
              └────────────────┘
```

That is the project in one page.

---

# 74. Glossary — the words you will hear constantly

| Term | Very simple meaning |
|---|---|
| API | A way for programs to talk to each other |
| Backend | The hidden server-side part of the app |
| Frontend | What the user sees |
| Database | Software that stores and retrieves information |
| Stream | Data arriving continuously |
| Kafka | A system for moving event messages safely at high speed |
| Worker | A program that performs a job |
| ML | Machine learning |
| NLP | Computer processing of human language |
| CV | Computer vision, processing images/video |
| Embedding | Numbers representing meaning/similarity |
| H3 | A hexagonal map-grid system |
| PostGIS | Geographic capabilities for PostgreSQL |
| Cluster | A group of related observations |
| Deduplication | Removing repeated copies |
| Verification | Checking evidence and trustworthiness |
| Confidence | How strongly the evidence supports the conclusion |
| Severity | How dangerous the event is |
| Provenance | Where the result came from |
| Hash | A digital fingerprint of data |
| WebSocket | A live two-way connection to a browser |
| Cache | Fast temporary storage |
| Object storage | Storage for large files |
| Latency | How long something takes |
| Throughput | How much can be processed per unit time |
| F1 | A metric balancing precision and recall |
| RBAC | Role-based access control |
| Lakehouse | Large managed data storage for analytics |
| Docker | A way to package/run software consistently |
| Kubernetes | A system for managing containers at scale |
| Modular monolith | One deployable app with clean internal modules |
| Microservice | A separately deployable software service |

---

# 75. Final mental model

Imagine the system as a **team of detectives working inside a super-fast post office**.

### The post office

Kafka moves the messages.

### The readers

NLP and computer vision understand them.

### The map team

PostGIS and H3 understand where things happen.

### The anti-spam team

Deduplication removes copies and reposts.

### The investigator

The deterministic engine checks hard facts.

### The judge

The verification engine combines evidence.

### The historian

The database stores what happened.

### The security guard

Provenance keeps the processing trail.

### The control room

Next.js shows humans what needs attention.

Put all of that together and you get:

> **A system that turns a noisy flood of weather information into a smaller number of explainable, evidence-backed weather events.**

---

# 76. Source basis for this document

This document is based on the materials provided for this project:

1. **SIH 2026 Problem Statement 26069 — National Weather Big Data Analytics Platform**
2. **National Weather Analytics Blueprint** (15-page blueprint)
3. **INDRA — Intelligent National Disaster & Weather Platform** design/document

The blueprint contributes the national-scale reference architecture, streaming/lakehouse direction, deterministic verification, spatiotemporal clustering, multimodal deduplication, provenance, evaluation concepts and defensive demo strategy.

The INDRA document contributes a practical modular-monolith implementation strategy, verification receipt, confidence/severity matrix, concrete technology stack, repository organization and reproducible demonstration workflow.

Where this document describes a **recommended design decision** rather than something explicitly required by the sources, it is written as guidance and should later be validated in the engineering specification.

---

# 77. One-sentence summary

> **INDRA is a real-time evidence-processing factory: it collects many weather signals, understands them, removes duplicates, groups related observations, checks them against independent evidence and hard rules, stores the full history, and shows humans a small number of explainable weather events.**

---

## Next document in the project

**`REQUIREMENTS.md`** should translate this understanding into a precise checklist of everything the software must do, how we test it, and what is explicitly out of scope.
