# Project

Saturdays.AI Madrid Deep Learning course project (March 2026). 4-person team, collaborative.
Repo: https://github.com/txema-puch/drone-ai-saturdays
Local: `/Users/txemapuch/Claude/drone-ai-saturdays`

## Teammate setup (run once after cloning)

```bash
# 1. Install uv (Python dependency manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Copy secrets template — fill in your values, never commit .env
cp .env.example .env

# 4. Build gstack browser tools (requires bun: https://bun.sh)
cd .claude/skills/gstack && ./setup
```

## Start of session checklist
1. `git pull` — sync latest from teammates before doing anything
2. `git status` — confirm you're on the right branch and have no stale changes
3. Create a branch for your work: `git checkout -b <your-feature>`
4. When done: `git add`, `git commit`, `git push`, open PR on GitHub

## Key conventions
- Python managed with `uv` — use `uv add <pkg>` not `pip install`, `uv run python` not `python`
- **The team uses a dev container for reproducibility (`.devcontainer/devcontainer.json`)** — `uv.lock` is intentionally not committed; the container's `python:3-3.11-bookworm` base image pins versions. Do NOT propose committing `uv.lock` without discussing with the team first.
- `data/` and `models/` are not committed — too large for git. Add download scripts or reference external storage instead.
- Secrets go in `.env` only — never committed. Share keys via password manager (1Password, Bitwarden).
- Work on feature branches, not directly on `main`. Open PRs so teammates can review.
- Commits use `<type>(scope): <description> (#issue)` format with explanatory bodies that capture the *why*, not just enumerated changes. See recent commits for the established pattern.

## Project workspace
`backend/docs/` is the shared working space — treat it like Notion. Key files:
- `backend/docs/README.md` — navigation index
- `backend/docs/problem/use-cases.md` — use case decision log (D-001 closed: airports/LEMD selected)
- `backend/docs/research/datasets.md` — all datasets found, with status and notes
- `backend/docs/research/links.md` — papers, tools, APIs, categorized
- `backend/docs/architecture/design-trajectory-anomaly-detection.md` — full approved design doc (two-layer system, 5-week plan, feature spec, evaluation criteria)
- `backend/docs/decisions/README.md` — log of key decisions (use case, modality, dataset)
- `backend/docs/weekly/README.md` — session notes
- `backend/docs/tasks/README.md` — week-by-week task boards with checkboxes (one file per week)

### ML lifecycle artifacts (read by `/ml-lifecycle` and `/develop`)
- `backend/docs/ml/manifest.yml` — single source of truth for which lifecycle phase we're in and which gates have passed. **The skill defaults to looking at `docs/ml/manifest.yml` at repo root — pass `backend/docs/ml/manifest.yml` explicitly when invoking `/ml-lifecycle` so it finds our manifest.**
- `backend/docs/ml/01-problem.md` — Phase 1 problem definition (closed 2026-05-07)
- `backend/docs/ml/02-data.md` — Phase 2 data audit doc (closed 2026-05-11, cyclic gate)
- `backend/docs/ml/07-eval-prep.md` — Phase 7 anomaly-injection research synthesis (prep notes, Phase 7 not started)
- `backend/docs/ml/decisions/` — ADR-style records for high-stakes ML decisions (D-001, D-005, D-006, …)

The data gate has `gate_semantics: "cyclic"` — passed means audit discipline operational, NOT data complete. Future cycles append to `manifest.yml > gates.data.dataset_hash` and to `02-data.md`'s snapshot log without re-passing the gate. See `references/lifecycle-map.md > Gate semantics` in the `/ml-lifecycle` skill.

### Data pipeline workflow
- `backend/docs/workflow/data-pipeline.md` — single source of truth for the data workflow: truncate-fill-snapshot cycle, role assignments (Monica = OpenSky → Supabase; Txema = validate + parquet + Drive), naming conventions, the six-category response playbook (A-F) for audit findings, the "audit cells safe to run blindly" principle. **Hard rule: Monica must NOT truncate Supabase until Txema confirms snapshot is in Drive with verified hash.**
- Local parquets in `data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__{snapshot,deduped}_<YYYY-MM-DD>.parquet` are the canonical record. Supabase is transient storage (500MB free-tier cycles).

When the team makes a decision (use case, modality, dataset), record it in `backend/docs/decisions/README.md`. ML-methodology decisions (metric choice, architecture, split strategy) get an ADR under `backend/docs/ml/decisions/` AND a pointer in `backend/docs/ml/manifest.yml > decisions[]`.

## Project status (as of 2026-05-11)

**ML lifecycle position:** Phase 2 closed; `current_phase: preprocess`. Phase 3 design coaching not yet started.

| Phase | Status | Artifact |
|---|---|---|
| 1. Problem | passed (2026-05-07) | `backend/docs/ml/01-problem.md` |
| 2. Data | passed (2026-05-11, cyclic gate) — cycle 1 validated | `backend/docs/ml/02-data.md` |
| 3. Preprocess | in_progress — not yet started | (none yet) |
| 4. EDA | pending | |
| 5. Features | pending | |
| 6. Train | pending | |
| 7. Eval | pending — prep notes exist | `backend/docs/ml/07-eval-prep.md` |
| 8. Deploy | pending — course demo only, not production | |

**Cycle 1 (2025-03-10 to 2025-03-14)** validated and snapshotted:
- 1,146,231 deduped rows, 1,285 unique trajectories, 330 unique aircraft
- Verdict: Real=PASS, Usable=PASS, Enough=SOFT_DEV (1 cycle, below 30-day floor)
- Snapshot in Drive at `drone-ai-saturdays/data/raw/lemd_20250310_to_20250314__{snapshot,deduped}_2026-05-10.parquet`

**Cycle 2** expected next session — Monica has data ready in a second Supabase account (2026 data range). Will be tracked as a new issue (~#15 stacked on #14).

**What we're building:** Two-layer unauthorized drone detection anchored to Madrid-Barajas (LEMD).
- Layer 1: Identity gate — ICAO24 registry lookup + U-Space flight plan match
- Layer 2: LSTM Autoencoder anomaly scorer trained on OpenSky ADS-B data

**Timeline:** 5 weeks, ~24h/person/week. Option B (visual) CUT. Option C (Android Remote ID) stretch only post Week 4.

**Open PRs:** #11 (Phase 1) and #14 (Phase 2). #14 is stacked on #11; will rebase when #11 merges.

**Notebooks (audit + reference):**
- `notebooks/05_phase2_data_validation.ipynb` — Phase 2 audit notebook (canonical for every cycle)
- `notebooks/01_data_recon.ipynb` through `04_evaluation.ipynb` — early reference notebooks, not the prescribed path

**Shared data:** Google Drive folder `drone-ai-saturdays/data/raw/` — canonical record; local parquets in `data/raw/` (gitignored) are working copies.

**Design doc (initial scoping):** `backend/docs/architecture/design-trajectory-anomaly-detection.md`
**All decisions:** `backend/docs/decisions/README.md`
**Writeup material** (Medium piece + presentation drafts): `backend/docs/writeup/*.md`

# gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.

Available gstack skills:
- `/office-hours` — YC-style brainstorming and idea pressure-testing
- `/plan-ceo-review` — CEO/founder-mode plan review
- `/plan-eng-review` — Eng manager-mode architecture review
- `/plan-design-review` — Designer's eye plan review
- `/design-consultation` — Full design system creation
- `/review` — Pre-landing PR code review
- `/ship` — Ship workflow: tests, changelog, PR creation
- `/land-and-deploy` — Merge PR, wait for CI/deploy, verify production
- `/canary` — Post-deploy canary monitoring
- `/benchmark` — Performance regression detection
- `/browse` — Fast headless browser for QA and testing
- `/qa` — Systematically QA test and fix bugs
- `/qa-only` — Report-only QA (no fixes)
- `/design-review` — Visual QA with before/after screenshots
- `/setup-browser-cookies` — Import real browser cookies for authenticated testing
- `/setup-deploy` — Configure deployment settings
- `/retro` — Weekly engineering retrospective
- `/investigate` — Systematic debugging with root cause analysis
- `/document-release` — Post-ship documentation update
- `/codex` — OpenAI Codex second opinion / adversarial review
- `/cso` — Chief Security Officer security audit
- `/autoplan` — Auto-run all reviews (CEO + design + eng) sequentially
- `/careful` — Warn before destructive commands
- `/freeze` — Restrict file edits to a specific directory
- `/guard` — Full safety mode (careful + freeze combined)
- `/unfreeze` — Clear freeze boundary
- `/gstack-upgrade` — Upgrade gstack to latest version

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
