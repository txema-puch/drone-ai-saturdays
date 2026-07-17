# SADAR Analyst Console

SADAR Analyst Console is a research demonstrator for post-flight screening of
ADS-B-observable approach attempts at Madrid-Barajas Airport (LEMD). It reconstructs
attempts, checks observation quality, infers runway-relative geometry when supported,
and presents deterministic criterion evidence in an analyst workflow.

- **Live application:** <https://sadar-analyst-console.fly.dev>
- **Release registry:** <https://huggingface.co/Txemapuch/sadar-demo-release>
- **Documentation:** [`docs/`](docs/)
- **Release card and limitations:** [`docs/product/release-card.md`](docs/product/release-card.md)

This is not emergency detection, stabilized-approach certification, ATC decision
support, or a safety verdict. The sealed 2026 evaluation retained 63.1% of
reconstructed attempts, below the precommitted 65% target, and there are no
independent labels from which to estimate review precision or recall. The application
is therefore a research and evidence-labeling demonstrator, not an operational system.

## Current product

The deployed product is rules-first and does not load the historical LSTM model.

1. Bounded OpenSky-style CSV or Parquet rows are canonicalized and separated into
   operations and approach attempts.
2. Observation quality and runway inference explicitly abstain on insufficient or
   conflicting evidence.
3. Transparent criteria cover lateral path, barometric-path proxy, observed descent
   rate, ground-speed envelope, and late track correction.
4. Contextual releases can display supplied QNH, wind components, and supported
   aircraft-type reference cells. They do not infer mass, configuration, clearance,
   intent, airspeed, or operational safety.

Uploaded files and results are not intentionally retained. Fly may preserve machine
memory while suspended; do not upload confidential or proprietary data.

## Run locally

The production-equivalent route is the container:

```bash
docker build --platform linux/amd64 -t sadar-analyst-console .
docker run --rm -p 7860:7860 -e SADAR_ENABLE_EVALUATION=true sadar-analyst-console
```

Open <http://localhost:7860>.

For backend development, from the repository root:

```bash
uv sync --project backend --group dev
mkdir -p .artifacts
uv run --project backend sadar-fetch-release \
  --lock backend/src/sadar/releases/approach_bundle.lock.json \
  --destination .artifacts/approach-release
SADAR_APPROACH_RELEASE_DIR="$PWD/.artifacts/approach-release" \
SADAR_ENABLE_EVALUATION=true \
  uv run --project backend sadar-api --port 8077
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The API loads the immutable release identified by
`backend/src/sadar/releases/approach_bundle.lock.json`. Configure an alternate verified
release or frontend directory through the documented `SADAR_*` environment variables.

## Evidence and research history

The repository preserves why the product changed direction:

- [`docs/product/`](docs/product/) — current behavior, architecture, design decision,
  and release limitations.
- [`docs/research/trajectory-anomaly/`](docs/research/trajectory-anomaly/) — the
  original LSTM autoencoder and classical-baseline lifecycle.
- [`docs/research/approach-screening/`](docs/research/approach-screening/) — the
  rules-first reframe and failed qualification result.
- [`docs/research/approach-context/`](docs/research/approach-context/) — the subsequent
  weather and aircraft-context investigation.
- [`research/trajectory-anomaly/notebooks/`](research/trajectory-anomaly/notebooks/) —
  executable lifecycle evidence and clearly labeled exploratory archive notebooks.

The historical model is benchmark evidence only. It cannot change an Analyst Console
status, verdict, or queue position.

## Repository layout

```text
backend/
  src/sadar/              deployable product distribution
  research/src/           historical research distribution
  tests/{product,research,delivery}/
delivery/container/       generated, hash-locked Linux dependency contract
frontend/                 React analyst console
docs/                     curated public documentation and evidence
research/                 research-track notebooks and replay entrypoints
scripts/                  repository and delivery checks
```

Git owns source, methodology, decisions, checksums, and artifact locks. Hugging Face
owns trained weights and generated release archives. Raw datasets, local models,
collaboration notes, and writeup drafts are intentionally excluded from source Git.

## Data and attribution

The research uses OpenSky Network ADS-B observations around LEMD. Optional contextual
inputs use NOAA NCEI Global Hourly weather and the OpenSky aircraft database. The
currently pinned application archives include bounded, downsampled row-level
OpenSky-derived observations needed by the demonstrator, including trajectory fields
and aircraft identifiers. They are not a copy of the full source database, but they
are still upstream data.

**Distribution gate:** the current [OpenSky terms of use](https://opensky-network.org/about/terms-of-use)
do not permit redistributing those datasets without authorization. The existing
registry artifacts must therefore not be mirrored or reused, and a public replacement
release must use authorized or synthetic evidence. Operational OpenSky API ingestion
also requires a written agreement. This unresolved gate blocks the next public
deployment; it does not change the repository's non-profit research purpose.

This began as a collaborative Saturdays.AI Madrid course project by Monica Gomez,
Pablo Rodriguez Campos, Roberto Molero, and Txema Puch. Team members independently
explored implementations and product directions; this repository is Txema Puch's
analyst-workflow version.
