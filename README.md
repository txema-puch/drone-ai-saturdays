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

## Contributing

- Work on feature branches, not directly on `main`
- Open a Pull Request to merge changes — teammates review before merging
- Never commit `.env` or large files — see `.gitignore`
