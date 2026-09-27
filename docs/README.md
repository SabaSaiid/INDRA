# INDRA — Documentation

Start here. Every document below was verified against the code and a running stack on
**21 Sep 2026**, the last day of the backend sprint, and updated on **25 Sep**, when every demo,
scripted and placeholder row was removed and operators got their own passwords.

The AI/ML layer's own documents (PR #39, 26 Sep) are its owner's, and state its status:

| Current ML document | Purpose |
| --- | --- |
| [ML architecture](ML_ARCHITECTURE.md) | Six components, backend boundary, actual wiring |
| [ML model card](ML_MODEL_CARD.md) | Frozen methods, labels, versions, hashes |
| [ML data card](ML_DATA_CARD.md) | Synthetic provenance and dataset hashes |
| [ML inference contract](ML_INFERENCE_CONTRACT.md) | Exact typed statuses and missing-input semantics |
| [ML validation report](ML_VALIDATION_REPORT.md) | Executed tests and blocked infrastructure gates |
| [ML limitations](ML_LIMITATIONS.md) | Unvalidated and high-risk claims |

| Document | Read it when |
|---|---|
| [`setup.md`](setup.md) | You want the stack running from a fresh clone |
| [`demo-runbook.md`](demo-runbook.md) | You are about to present INDRA: what to show from the live feeds, how a real report is filed on the day, what to expect, and a recovery line for each thing that can go wrong |
| [`nodal-officer-qa.md`](nodal-officer-qa.md) | Someone is about to ask a hard question. The honest answer to each, with a number or a file behind it |
| [`api-contract.md`](api-contract.md) | You are calling the API — every endpoint, shape and status code |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | You want the original nine-layer design and historical 21 Sep ledger |
| [`backend-architecture.md`](backend-architecture.md) | You are working inside `backend/` — module boundaries, the scoring model, the data platform |
| [`frontend-handover.md`](frontend-handover.md) | You own the dashboard. Everything the backend changed that you can see, and what was changed in the dashboard itself on 22 and 25 Sep |
| [`bug-register.md`](bug-register.md) | Something is behaving oddly, or you want to know what is known-broken before a demo |

## Historical 21 Sep backend-sprint takeaways

**The score is never quoted without its coverage.** Confidence is a weighted mean over the factors
that actually reported, and `factor_coverage` says how much of the designed model that was — 0.80
today, because two factors are permanently offline. The honest form is the score and its coverage
together (`… at coverage 0.80`); the score alone is not.

**Absent signals are stated, not filled in.** Where a factor has nothing behind it, the receipt
prints `offline` with a reason rather than a plausible number. The visible cost is that nothing
auto-publishes and events reach a human through review. That is the design, not a shortfall.
The API follows the same rule: a read with no rows returns the real empty result, an unknown id is
a `404` and a database error a `503`. There is no demo mode and no fallback data.

**The scope decision changed after this snapshot.** Six local AI/ML components were later frozen
for synthetic development, but five are not wired into the backend. The alert-engine status is
separate. Do not present synthetic ML tests as a live or production validation.
