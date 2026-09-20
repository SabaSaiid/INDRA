# INDRA — Documentation

Start here. Every document below was verified against the code and a running stack on
**21 Sep 2026**, the last day of the backend sprint.

| Document | Read it when |
|---|---|
| [`setup.md`](setup.md) | You want the stack running from a fresh clone |
| [`demo-runbook.md`](demo-runbook.md) | You are about to demonstrate INDRA. Exact commands, expected numbers, and a recovery line for each thing that can go wrong |
| [`nodal-officer-qa.md`](nodal-officer-qa.md) | Someone is about to ask a hard question. The honest answer to each, with a number or a file behind it |
| [`api-contract.md`](api-contract.md) | You are calling the API — every endpoint, shape and status code |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | You want the whole nine-layer design, and §0, the ledger of what is actually built |
| [`backend-architecture.md`](backend-architecture.md) | You are working inside `backend/` — module boundaries, the scoring model, the data platform |
| [`frontend-handover.md`](frontend-handover.md) | You own the dashboard. Everything the backend changed that you can see, and the one thing that needs a change |
| [`bug-register.md`](bug-register.md) | Something is behaving oddly, or you want to know what is known-broken before a demo |

## The three things worth knowing before reading anything else

**The score is never quoted without its coverage.** Confidence is a weighted mean over the factors
that actually reported, and `factor_coverage` says how much of the designed model that was — 0.80
today, because two factors are permanently offline. `0.4984 at coverage 0.80` is the honest form;
`0.4984` alone is not.

**Absent signals are stated, not filled in.** Where a factor has nothing behind it, the receipt
prints `offline` with a reason rather than a plausible number. The visible cost is that nothing
auto-publishes and events reach a human through review. That is the design, not a shortfall.

**Two layers are out of scope, not late.** AI/ML (classification, vision, anomaly detection) and
the alert engine (SMS, email, dispatch) were cancelled on 20 Sep. Nothing in this repository, the
API or the dashboard claims either exists.
