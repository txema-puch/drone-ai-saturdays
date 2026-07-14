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

## Project status (as of 2026-05-23)

**ML lifecycle position:** Phase 2 still `passed` (cyclic gate); cycle 3 closed via a new data-source path (D-007). `current_phase: preprocess`. Phase 3 design coaching not yet started.

| Phase | Status | Artifact |
|---|---|---|
| 1. Problem | passed (2026-05-07) | `backend/docs/ml/01-problem.md` |
| 2. Data | passed (2026-05-11, cyclic gate) — cycles 1+2+3 landed (cycle 3 via D-007, 18 of 20 planned Mondays) | `backend/docs/ml/02-data.md` |
| 3. Preprocess | in_progress — not yet started | (none yet) |
| 4. EDA | pending | |
| 5. Features | pending | |
| 6. Train | pending | |
| 7. Eval | pending — prep notes exist | `backend/docs/ml/07-eval-prep.md` |
| 8. Deploy | pending — course demo only, not production | |

**Cycle 1 (2025-03-10 to 2025-03-14)** — Mon-Fri, validated and snapshotted:
- 1,146,231 deduped rows (1,834,084 raw, 37.5% dups removed), 1,285 unique trajectories, 330 unique aircraft.
- Verdict: Real=PASS, Usable=PASS, Enough=SOFT_DEV.
- Snapshot in Drive at `drone-ai-saturdays/data/raw/lemd_20250310_to_20250314__{snapshot,deduped}_2026-05-10.parquet`.

**Cycle 2 (2026-03-10 to 2026-03-14)** — Tue-Sat, validated and snapshotted (year-over-year repeat of cycle 1's window):
- 1,774,859 rows, **0 duplicates** (Monica's UNIQUE-constraint fix from #13 verified working in production), 1,426 trajectories, 350 aircraft.
- Snapshot is canonical (no dedup needed). Verdict: Real=PASS, Usable=PASS, Enough=SOFT_DEV.
- Snapshot in Drive at `drone-ai-saturdays/data/raw/lemd_20260310_to_20260314__snapshot_2026-05-11.parquet`.

**Cycle 3 (2017-06 → 2020-03, OpenSky scientific dataset)** — data-source pivot per **D-007**. Closed 2026-05-23 with 18 of 20 planned Mondays landed:
- New script `backend/scripts/download_opensky_states.py` pulls Mondays from OpenSky's public S3 scientific dataset entry #1, no credentials needed. Bypasses the Trino + Supabase coordination bottleneck.
- 10s resolution (Trino path was 5s — Phase 3 needs to harmonize if mixing sources).
- `flights_data4` metadata not available — replaced with **Filter B** (per-trajectory: `min_dist<10km AND min_alt<3km`) as the LEMD-flight gate. Empirically removes ~47% bbox cruise overflights.
- Per-Monday parquets in `data/raw/opensky_states/`. Final yield: **18 Mondays, 19,057 trajectories, 3.43M rows, ~123 MB on disk.**
- 2 Mondays (2018-04-02, 2019-12-02) failed on a residual lat/lon coercion bug in `apply_derivations` (object-dtype after empty-chunk concat). 1-line fix exists; decision was to ship 18 and document the gap as a Limitations entry in the writeup.
- Sampling notes: first-pass run hit 15/20; 2 numpy bug crashes (fixed mid-run via `pd.to_numeric` coercion on `velocity`/`baroaltitude`/`heading`); 3 missing 2022 Mondays replaced with pre-COVID 2020 substitutes in a top-up run; 2 residual failures remain (see above).
- Pre-existing settings-loader bug fixed in `backend/core/config.py` (`extra = "ignore"`) so cycle-N env vars don't crash settings.
- Combined Merkle hash: `98e38ba5802816a97f17b2086df18570c6f81311d80faeed0492ad87abd662e4` (sorted sha256 of per-file sha256).

**Cumulative (through cycle 3):** 28 days, **21,768 trajectories, 6.35M canonical rows.** Crosses the 5K-trajectory threshold → **Enough=CONDITIONAL.** Day-of-week coverage stays at 6/7 by union (Sunday still missing) but is now heavily Monday-skewed (18 Mondays + 1 Mon + 1 Tue/Wed/Thu/Fri/Sat) — call out in writeup as a restricted-regime claim.

**Cycle 2 framework improvements (live as of PR #16):**
- **Multi-account `.env` scheme**: `SUPABASE_URL_<SLUG>` / `SUPABASE_KEY_<SLUG>` with `ACCOUNT_SLUG` constant in notebook cell 1. No more manual `.env` overwrites per cycle.
- **`TABLE_NAME` constant** for the workflow-doc table-naming convention (`lemd_<suffix>`, not legacy `lemd_YYYY_MM_DD`).
- **Day-by-day OFFSET pagination** in `load_table_paginated` (after OFFSET-only and keyset both hit Postgres `statement_timeout` at depth). Robust to absent indexes; even faster with them.
- **Cross-references** at four canonical entry points (opensky.py docstring, notebook intro, workflow doc, project README) so future agents discover the validation graph within one hop.

**Open cycle-3+ asks (response F findings, awaiting follow-up):**
- Monica's pipeline should provision indexes upfront on each cycle's table: `(time, icao24)` and `(flight_id)`. Currently added manually mid-audit. See `02-data.md > Known issues > #11`.
- Cell 7c / cell 12 should apply D-206's 0.1% noise tolerance to the Usable verdict automatically instead of requiring manual interpretation. See `02-data.md > Known issues > #12`.

**What we're building:** Two-layer unauthorized drone detection anchored to Madrid-Barajas (LEMD).
- Layer 1: Identity gate — ICAO24 registry lookup + U-Space flight plan match
- Layer 2: LSTM Autoencoder anomaly scorer trained on OpenSky ADS-B data

**Timeline:** 5 weeks, ~24h/person/week. Option B (visual) CUT. Option C (Android Remote ID) stretch only post Week 4.

**Open PRs (stacked chain):** **#11** (Phase 1) → **#14** (Phase 2 framework + cycle 1) → **#16** (cycle 2) → **#18** (cycle 3, branch `17-task-phase2-cycle3-opensky-scientific`, issue #17). Each PR's base is the previous PR's branch; they rebase down the chain as each merges to develop.

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

## Deploy Configuration (configured by /setup-deploy)
- Platform: Fly.io
- Production URL: https://sadar-analyst-console.fly.dev
- Deploy workflow: `scripts/deploy-fly.sh`
- Deploy status command: `fly status --app sadar-analyst-console`
- Merge method: merge commit
- Project type: web app + API
- Post-deploy health check: https://sadar-analyst-console.fly.dev/api/health

### Custom deploy hooks
- Pre-merge: `uv run --project backend python scripts/check-delivery-contract.py && uv run --project backend pytest && npm --prefix frontend test -- --run && npm --prefix frontend run build`
- Deploy trigger: `scripts/deploy-fly.sh`
- Deploy status: `fly status --app sadar-analyst-console`
- Health check: `curl -fsS https://sadar-analyst-console.fly.dev/api/health`
