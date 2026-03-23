# Drone AI — Saturdays.AI

Collaborative project for Saturdays.AI Madrid Deep Learning course.

## Team
- txema-puch
- *(add teammates here)*

## Project
*(describe the project goal here once decided)*

## Setup

This project uses [`uv`](https://docs.astral.sh/uv/) to manage Python dependencies.

```bash
# 1. Install uv (if you haven't)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repo
git clone https://github.com/txema-puch/drone-ai-saturdays.git
cd drone-ai-saturdays

# 3. Install dependencies and activate environment
uv sync

# 4. Copy secrets template
cp .env.example .env
# Edit .env and fill in your values
```

## Structure

```
data/           # Datasets (not committed — too large for git)
  raw/          # Original, unprocessed data
  processed/    # Train/test splits
models/         # Trained model artifacts (not committed)
notebooks/      # Jupyter notebooks for exploration
src/            # Source code / modules
tests/          # Tests
```

## Working with Claude Code + gstack

This project is set up for AI-assisted development with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's CLI coding assistant).

**Install Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```
Then open it in the project folder: `claude` — it will pick up `CLAUDE.md` automatically.

**gstack** is a set of AI slash-command skills already included in this repo at `.claude/skills/gstack/`. After cloning, build it once:
```bash
# Requires bun: https://bun.sh/
curl -fsSL https://bun.sh/install | bash
cd .claude/skills/gstack && ./setup
```

Useful gstack commands inside Claude Code:
- `/browse <url>` — open a URL in a headless browser for testing
- `/qa <url>` — automated QA testing with bug reports
- `/review` — code review of your current branch before a PR
- `/investigate` — systematic debugging when something is broken
- `/retro` — weekly summary of what the team shipped

See `CLAUDE.md` at the root for the full skill list.

## Contributing

- Work on feature branches, not directly on `main`
- Open a Pull Request to merge changes — teammates review before merging
- Never commit `.env` or large files — see `.gitignore`
