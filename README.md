# SADAR Analyst Console

Post-hoc trajectory-anomaly analysis around Madrid-Barajas Airport (LEMD). Analysts can review
the frozen release cohort, upload bounded OpenSky-style CSV or Parquet observations, apply the
immutable release model, and inspect trajectory, temporal, attribution, and data-quality evidence.

SADAR began as a collaborative exploration of trajectory-anomaly detection around
Madrid-Barajas Airport. From that shared foundation, team members developed independent model
implementations and approaches to productizing the concept. **SADAR Analyst Console** is Txema
Puch's implementation, focused on the analyst workflow: evaluating operational data and
investigating trajectory-anomaly evidence.

- **Application:** <https://sadar-analyst-console.fly.dev>
- **Immutable model release:** <https://huggingface.co/Txemapuch/sadar-demo-release>
- **Source:** <https://github.com/txema-puch/drone-ai-saturdays>

The model output is investigative evidence, not an authorization, identity, incident, intent, or
safety verdict. The application does not intentionally retain uploaded files or results, but Fly
may snapshot Machine memory during idle suspension. Do not upload confidential or proprietary
data.

## Course project

Collaborative project for Saturdays.AI Madrid Deep Learning course.

## Team
- Monica Gomez
- Pablo Rodriguez Campos
- Roberto Molero
- Txema Puch
  

## Original project scope

Unauthorized drone detection system anchored to Madrid-Barajas Airport (LEMD), built for the Saturdays.AI Madrid Deep Learning course.

**Two-layer approach:**
1. **Identity gate** — checks ICAO24 transponder codes against the OpenSky aircraft registry and U-Space flight plans. Known aircraft pass instantly. Unknown transponders go to Layer 2.
2. **LSTM Autoencoder anomaly scorer** — trained on months of normal ADS-B trajectories around LEMD. Flags trajectories whose reconstruction error exceeds the 95th percentile of the validation set. Anomaly score is per-trajectory MSE.

The initial scope proposed live ADS-B ingestion, an identity gate, and anomaly scoring. The
Analyst Console release deliberately serves the completed Phase-6 LSTM autoencoder as a
post-hoc audit tool instead: it scores complete trajectory segments and does not claim live
monitoring or an implemented U-Space authorization decision.

**What we're NOT doing:** visual/camera-based detection (cut for timeline) and Android Remote ID (stretch goal only after Week 4).

Full design: [`backend/docs/architecture/design-trajectory-anomaly-detection.md`](backend/docs/architecture/design-trajectory-anomaly-detection.md)

## Run the analyst console

The production image is the Docker target configured for Fly.io. Evaluation remains
fail-closed unless the deployment explicitly enables it.

```bash
docker build --platform linux/amd64 -t sadar-analyst-console .
docker run --rm -p 7860:7860 -e SADAR_ENABLE_EVALUATION=true sadar-analyst-console
```

Open <http://localhost:7860>. The tracked [`fly.toml`](fly.toml) enables evaluation for the
public demo and suspends its single 2 GiB Machine while idle. Incoming requests automatically
resume it without keeping an always-running instance. Autostart is not a spending cap: continuous
traffic can keep the Machine active, with a current full-month compute ceiling of about $10.70
plus root-filesystem storage and network usage ([Fly pricing, checked 2026-07-14](https://fly.io/docs/about/pricing/)).

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

## Tasks

Week-by-week task boards live in [`docs/tasks/`](docs/tasks/). Each file lists what needs to happen that week — objectives, deliverables, and checkboxes. No person assignments, no prescribed implementation. Start here each session, pick up what makes sense for you, and figure out the code together.

| Week | Focus | File |
|---|---|---|
| 1 | Data recon + Streamlit skeleton | [`docs/tasks/week1.md`](docs/tasks/week1.md) |
| 2 | Pipeline, features, identity gate, IF baseline | [`docs/tasks/week2.md`](docs/tasks/week2.md) |
| 3 | LSTM Autoencoder training | [`docs/tasks/week3.md`](docs/tasks/week3.md) |
| 4 | Evaluation, demo polish, offline check | [`docs/tasks/week4.md`](docs/tasks/week4.md) |
| 5 | Writeup, rehearsal, repo cleanup, v1.0 tag | [`docs/tasks/week5.md`](docs/tasks/week5.md) |

## Notebooks

Reference notebooks are in `notebooks/` — one per week, covering the same scope as the task boards. They are one possible implementation, not the prescribed one. Use them as inspiration if you're stuck, or ignore them and build your own approach.

Run in Google Colab (T4 GPU for Week 3). Data lives in a shared Google Drive folder — mount it when prompted.

| Notebook | Week | Scope |
|---|---|---|
| `notebooks/01_data_recon.ipynb` | 1 | OpenSky ADS-B query for LEMD bounding box, EDA |
| `notebooks/02_pipeline.ipynb` | 2 | Trajectory segmentation, feature engineering, Isolation Forest |
| `notebooks/03_lstm.ipynb` | 3 | LSTM Autoencoder training, anomaly threshold |
| `notebooks/04_evaluation.ipynb` | 4 | Full metrics, PR curve, ablation |

## Data

Large files are not committed. Everything lives in Google Drive: `drone-ai-saturdays/data/`.

Mount in Colab:
```python
from google.colab import drive
drive.mount('/content/drive')
DATA_DIR = '/content/drive/MyDrive/drone-ai-saturdays/data'
```

Locally, put files under `data/` (gitignored). Trained model weights go in `models/` (also gitignored — share via Drive or Hugging Face Hub link in the release README).

## Structure

```
notebooks/      # Colab-ready notebooks (01–04)
src/            # Source modules (imported by notebooks)
docs/
  architecture/ # System design doc
  tasks/        # Week-by-week task boards (plain language, no code)
  decisions/    # Key decisions log
  research/     # Dataset notes, links, papers
  weekly/       # Session notes
demo.py         # Streamlit animated map (Week 1 skeleton, wired in Week 2+)
data/           # Not committed — too large for git
models/         # Not committed — share via Drive
```

## Working with Claude Code + gstack

This project is set up for AI-assisted development with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's CLI coding assistant).

**Install Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```
Then open it in the project folder: `claude` — it will pick up `CLAUDE.md` automatically.

**[gstack](https://github.com/garrytan/gstack)** is a set of AI slash-command skills already included in this repo at `.claude/skills/gstack/`. After cloning, build it once:
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
