# Project

Saturdays.AI Madrid Deep Learning course project (March 2026). 4-person team, collaborative.
Repo: https://github.com/txema-puch/drone-ai-saturdays
Local: `/Users/txemapuch/Claude/Claude Saturdays AI/drone-saturdays AI`

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
