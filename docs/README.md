# INDRA Documentation

The documentation for INDRA, the Intelligent National Disaster & Weather Platform. Start with the
[project README](../README.md) for an overview and a quick start. The documents below go deeper.

Last reviewed **28 Sep 2026**, against `main` after Phase 4 (PR #47).

## Architecture

| Document | Contents |
|---|---|
| [System architecture](ARCHITECTURE.md) | Context and goals, the nine layers and their state, data flow, verification model, geospatial and data models, deployment, quality attributes, decisions and limitations |
| [Backend architecture](backend-architecture.md) | Inside `backend/`: the request path, module map, scoring model, data platform, background tasks, configuration and testing |
| [Diagrams](architecture/) | [`indra-system-architecture.drawio`](architecture/indra-system-architecture.drawio), the editable source, and its four pages exported as SVG: [end-to-end system](architecture/01-end-to-end-system.svg), [report lifecycle](architecture/02-report-lifecycle.svg), [deployment](architecture/03-deployment.svg), [data model](architecture/04-data-model.svg) |

## Using and operating INDRA

| Document | Contents |
|---|---|
| [Setup](setup.md) | From a fresh clone to a running stack: environment, object store, migrations, operator accounts, tests, the dashboard and the browser-test backend |
| [API contract](api-contract.md) | Every endpoint, request and response shape, status code and auth rule, plus the WebSocket messages |
| [Demo runbook](demo-runbook.md) | Presenting INDRA on live data: pre-flight checks, the scenes, and a recovery line for each thing that can go wrong |
| [Questions & answers](nodal-officer-qa.md) | The hard questions a reviewer or officer asks, each answered with a number, a file or a test |
| [Bug register](bug-register.md) | Every defect found in the core platform, with its severity, status, fix and covering test |

## For other teams

| Document | Audience |
|---|---|
| [Frontend handover](frontend-handover.md) | Saba Saeed, owner of the command center (`frontend/`): every backend change the dashboard can see, and what it needs from the dashboard |
| [AI/ML architecture](ML_ARCHITECTURE.md) · [model card](ML_MODEL_CARD.md) · [data card](ML_DATA_CARD.md) · [inference contract](ML_INFERENCE_CONTRACT.md) · [validation report](ML_VALIDATION_REPORT.md) · [limitations](ML_LIMITATIONS.md) | Layer 4, maintained by its owner. Detailed working documents are in [`backend/app/ml/docs/`](../backend/app/ml/docs/) |
| [Alert engine integration](ALERT_ENGINE_INTEGRATION.md) · [frontend integration](ALERT_ENGINE_FRONTEND_INTEGRATION.md) · [reality audit](ALERT_ENGINE_REALITY_AUDIT.md) | Layer 8b, the standalone service in [`alert_engine/`](../alert_engine/), maintained by its owner |

## Conventions

These documents follow three rules:

- **They describe the system as built.** Anything planned is labelled with the phase that will
  deliver it. When a document and the code disagree, the code is right and the document gets fixed.
- **Numbers carry their source.** A measurement is quoted with its date and the run or test that
  produced it. A confidence score is always quoted with its factor coverage (0.80 today, because
  the vision and anomaly factors are offline).
- **Absent means absent.** A signal INDRA does not have is described as absent, never estimated.
  The API follows the same rule: no rows gives the real empty result, an unknown id gives `404`
  and a database error gives `503`. There is no demo mode and no fallback data.

When an endpoint changes, update [`api-contract.md`](api-contract.md) in the same pull request. If
the dashboard is affected, add a section to [`frontend-handover.md`](frontend-handover.md). Record a
defect in [`bug-register.md`](bug-register.md) when it is observed, not when it is fixed.
