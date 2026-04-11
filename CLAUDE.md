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
- `data/` and `models/` are not committed — too large for git. Add download scripts or reference external storage instead.
- Secrets go in `.env` only — never committed. Share keys via password manager (1Password, Bitwarden).
- Work on feature branches, not directly on `main`. Open PRs so teammates can review.

## Project workspace
`docs/` is the shared working space — treat it like Notion. Key files:
- `docs/README.md` — navigation index
- `docs/problem/use-cases.md` — use case decision log (D-001 closed: airports/LEMD selected)
- `docs/research/datasets.md` — all datasets found, with status and notes
- `docs/research/links.md` — papers, tools, APIs, categorized
- `docs/architecture/design-trajectory-anomaly-detection.md` — full approved design doc (two-layer system, 5-week plan, feature spec, evaluation criteria)
- `docs/decisions/README.md` — log of key decisions (use case, modality, dataset)
- `docs/weekly/README.md` — session notes
- `docs/tasks/README.md` — week-by-week task boards with checkboxes (one file per week)

When the team makes a decision (use case, modality, dataset), record it in `docs/decisions/README.md`.

## Project status (as of 2026-04-11)
Design approved. 5-week plan locked. Heading into Week 1 execution.

**What we're building:** Two-layer unauthorized drone detection anchored to Madrid-Barajas (LEMD).
- Layer 1: Identity gate — ICAO24 registry lookup + U-Space flight plan match
- Layer 2: LSTM Autoencoder anomaly scorer trained on OpenSky ADS-B data

**Timeline:** 5 weeks, ~24h/person/week. Option B (visual) CUT. Option C (Android Remote ID) stretch only post Week 4.

**Notebooks (reference only — not the prescribed path):**
- `notebooks/01_data_recon.ipynb` — Week 1: OpenSky EDA
- `notebooks/02_pipeline.ipynb` — Week 2: segmentation, features, IF baseline
- `notebooks/03_lstm.ipynb` — Week 3: LSTM autoencoder training
- `notebooks/04_evaluation.ipynb` — Week 4: full metrics, ablation

The team writes their own code. Notebooks are one possible implementation — use as inspiration or ignore.

**Shared data:** Google Drive folder `drone-ai-saturdays/data/` — mount in Colab as `/content/drive/MyDrive/drone-ai-saturdays/data/`.

**Design doc:** `docs/architecture/design-trajectory-anomaly-detection.md`
**All decisions:** `docs/decisions/README.md`
**Week 1 task:** See `docs/tasks/week1.md` — register OpenSky account, set up Drive, query LEMD data, share recon summary in Discord, set up CI and Streamlit skeleton.

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
