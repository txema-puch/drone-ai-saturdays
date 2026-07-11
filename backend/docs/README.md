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
| [ML lifecycle](./ml/) | Phase-by-phase ML work — `manifest.yml`, phase artifacts, [`pending-work.md`](./ml/pending-work.md), and `decisions/` (ADRs) |
| [Workflow](./workflow/data-pipeline.md) | Data pipeline workflow — cycle pattern, roles, naming, response playbook, hard timing rule |
| [Designs](./designs/) | Per-ticket design docs (locked scope before implementation) |
| [Writeup](./writeup/README.md) | Material for the Medium piece + final presentation |
| [Weekly](./weekly/README.md) | Session notes and progress log |
| [Tasks](./tasks/README.md) | Week-by-week task boards with checkboxes — use these during sessions |

The validation notebook itself lives outside this tree at [`notebooks/05_phase2_data_validation.ipynb`](../../notebooks/05_phase2_data_validation.ipynb) — it produces inputs for `ml/02-data.md` and `ml/manifest.yml` each cycle.

---

## Current Status (2026-07-11)

**ML lifecycle phase:** Phase 7 passed on 2026-06-02; `current_phase: deploy`. The test
cohort was burned once and its provenance is recorded in
[`ml/07-eval.md`](./ml/07-eval.md). The current course-demo iteration is closed with
deployment guardrails and deferred findings in
[`ml/pending-work.md`](./ml/pending-work.md).

**What we're building:** Two-layer unauthorized drone detection system anchored to Madrid-Barajas (LEMD).
- Layer 1: Identity gate (ICAO24 registry + U-Space flight plan lookup)
- Layer 2: LSTM Autoencoder trajectory anomaly scorer trained on OpenSky ADS-B data

**Recent milestones:**
- Phase 1 closed 2026-05-07 — see [`ml/01-problem.md`](./ml/01-problem.md)
- Phase 2 closed 2026-05-11 (cycle 1 validated, snapshot in Drive) — see [`ml/02-data.md`](./ml/02-data.md)
- Phase 7 closed 2026-06-02 after one sealed-test burn — see [`ml/07-eval.md`](./ml/07-eval.md)
- Deployment audit closed 2026-07-11 with eight explicit future-work findings

**Key reads to onboard:**
1. [Design doc](./architecture/design-trajectory-anomaly-detection.md) — the full approved system design
2. [`ml/01-problem.md`](./ml/01-problem.md) — Phase 1 problem framing + metric stack
3. [`ml/02-data.md`](./ml/02-data.md) — audit methodology + per-cycle snapshot log + known issues
4. [`ml/07-eval.md`](./ml/07-eval.md) — burned-test results and model selection
5. [`ml/pending-work.md`](./ml/pending-work.md) — deferred findings and restart order
6. [`workflow/data-pipeline.md`](./workflow/data-pipeline.md) — how data moves from OpenSky → Drive → training
