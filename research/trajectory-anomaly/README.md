# Historical trajectory-anomaly research

This track records the original SADAR experiment: learning an OpenSky ADS-B
trajectory baseline and evaluating whether unusual segments could be ranked for
review. It explains how the project reached its current product direction, but it
is not the SADAR Analyst Console's active decision engine.

The current product screens observable LEMD approach-conformance criteria with
explicit rules and abstention. Its implementation lives in `backend/src/sadar`.
The historical LSTM autoencoder and statistical baselines live in the separately
installable `backend/research` package and may be used only as research evidence.

## Layout

- `notebooks/lifecycle/` — the prescribed Phase 2–6 evidence trail and companion
  experiments. These notebooks import the tested `sadar_research` package.
- `notebooks/archive/` — Week 1–4 exploratory precursors retained to show how the
  later lifecycle was reached. They are not the prescribed implementation.
- `backend/research/src/sadar_research/trajectory_anomaly/` — executable research
  pipeline, models, evaluation code, and release contracts.
- `backend/docs/ml/` — historical lifecycle decisions, gates, and interpretation.

## Environment

From the repository root:

```bash
uv sync --project backend/research --extra data --extra notebooks
uv run --project backend/research --extra data --extra notebooks jupyter lab
```

Open notebooks from their repository paths. Lifecycle notebooks locate the root
by walking upward and import `backend/research/src`; they no longer depend on the
removed `backend.core` or `backend.crud` namespaces.

Raw datasets and trained artifacts are intentionally external to source Git.
Follow the manifests and Hugging Face locks before attempting a full replay.
