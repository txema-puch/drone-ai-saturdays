# Project Workspace

Working space for the Saturdays.AI Madrid drone detection project.
Use this as your Notion — everything lives here, versioned alongside the code.

---

## Navigation

| Section | What's inside |
|---|---|
| [Problem](./problem/overview.md) | Context, why this matters, executive summary |
| [Use Cases](./problem/use-cases.md) | 8 scenarios we're considering as project focus |
| [Datasets](./research/datasets.md) | All datasets found — status, notes, access |
| [Links](./research/links.md) | Research links, papers, tools — categorized |
| [Architecture](./architecture/README.md) | Proposed system design |
| [Decisions](./decisions/README.md) | Key choices the team needs to make / has made |
| [Weekly](./weekly/README.md) | Session notes and progress log |

---

## Current Status

**Phase:** Design approved — heading into Week 1 execution (data recon).

**All four key decisions made on 2026-04-11. See [Decisions](./decisions/README.md) for rationale.**

**What we're building:** Two-layer unauthorized drone detection system anchored to Madrid-Barajas (LEMD).
- Layer 1: Identity gate (ICAO24 registry + U-Space flight plan lookup)
- Layer 2: LSTM Autoencoder trajectory anomaly scorer trained on OpenSky ADS-B data

**Week 1 task (one person):** Register OpenSky research account, pull one month of LEMD bounding box data, run the data recon notebook. See [design doc](./architecture/design-trajectory-anomaly-detection.md#the-assignment) for exact steps.

**Design doc:** [architecture/design-trajectory-anomaly-detection.md](./architecture/design-trajectory-anomaly-detection.md) — read this first.
