# SADAR Analyst Console

SADAR Analyst Console is a research demonstrator for post-flight screening of
ADS-B-observable approach attempts at Madrid-Barajas Airport (LEMD). It reconstructs
attempts, checks observation quality, infers runway-relative geometry when supported,
and presents deterministic criterion evidence in an analyst workflow.

- **Application URL:** <https://sadar-analyst-console.fly.dev> (schema-v4 redeploy gated on publication)
- **Planned evidence registry:** <https://huggingface.co/datasets/Txemapuch/sadar-analyst-console-release>
- **Documentation:** [`docs/`](docs/)
- **Release card and limitations:** [`docs/product/release-card.md`](docs/product/release-card.md)

This is not emergency detection, stabilized-approach certification, ATC decision
support, or a safety verdict. The sealed 2026 evaluation retained 63.1% of
reconstructed attempts, below the precommitted 65% target, and there are no
independent labels from which to estimate review precision or recall. The application
is therefore a research and evidence-labeling demonstrator, not an operational system.

## Current product

The product is rules-first and does not load the historical LSTM model. Its public
boundary contains three independent lanes: deterministic synthetic demo scenarios,
suppression-safe aggregate findings from real OpenSky research cohorts, and bounded
user uploads evaluated ephemerally without joining either published lane.

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

Until the schema-v4 dataset artifact is published, build the production-equivalent
container from an explicitly generated and reviewed local release:

```bash
rm -rf /tmp/sadar-synthetic-demo /tmp/sadar-approach-release
uv run --project backend sadar-build-synthetic-demo \
  --seed 20260718 --output /tmp/sadar-synthetic-demo
uv run --project backend sadar-build-release \
  --aggregate-results backend/src/sadar/approach/resources/lemd_public_aggregate_results_v1.json \
  --synthetic-payload-dir /tmp/sadar-synthetic-demo \
  --output /tmp/sadar-approach-release
uv run --project backend sadar-validate-public-release \
  --release-dir /tmp/sadar-approach-release
docker build --platform linux/amd64 --target runtime \
  --build-context approach-release-context=/tmp/sadar-approach-release \
  --build-arg SADAR_RELEASE_SOURCE=local-reviewed \
  --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" \
  -t sadar-analyst-console .
docker run --rm -p 7860:7860 -e SADAR_ENABLE_EVALUATION=true sadar-analyst-console
```

Open <http://localhost:7860>.

For backend development, from the repository root:

```bash
uv sync --project backend --group dev
mkdir -p .artifacts
SADAR_APPROACH_RELEASE_DIR=/tmp/sadar-approach-release \
SADAR_ENABLE_EVALUATION=true \
  uv run --project backend sadar-api --port 8077
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The committed product lock still identifies the withdrawn schema-3 artifact and is
deliberately unused by pre-publication CI and local-reviewed builds. After publication,
locked-public mode will anonymously fetch the immutable schema-v4 dataset artifact.

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
owns trained weights and generated release archives; the schema-v4 application archive
is a dataset/application evidence bundle, not a model. Raw datasets, local models,
collaboration notes, and writeup drafts are intentionally excluded from source Git.

## Data and attribution

The real-data aggregate lane was derived from OpenSky Network ADS-B observations around
LEMD. It contains counts, rates, coverage, provenance and limitations only—no source
row, trajectory, aircraft identifier or exact timestamp. Obtain source data through
[OpenSky data access](https://opensky-network.org/data/data-access) and follow the
[OpenSky terms](https://opensky-network.org/about/terms-of-use).

Publication notice was sent to OpenSky on **2026-07-20**; acknowledgement is not
claimed. Cite:
Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic, and Matthias
Wilhelm. “Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research.” IPSN
2014.

The schema-3 application artifact was withdrawn from the public-delivery path because
it contained row-level upstream observations. The replacement keeps real findings only
in aggregate and uses synthetic records for the interactive demo. It is not qualified:
there are no independent labels or fresh holdout, and operational monitoring, emergency
detection, stabilized-approach certification, ATC decision support and
safety-performance claims are blocked.

This began as a collaborative Saturdays.AI Madrid course project by Monica Gomez,
Pablo Rodriguez Campos, Roberto Molero, and Txema Puch. Team members independently
explored implementations and product directions; this repository is Txema Puch's
analyst-workflow version.
