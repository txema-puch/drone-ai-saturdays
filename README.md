# SADAR Analyst Console

SADAR Analyst Console is a research demonstrator for post-flight screening of
ADS-B-observable approach attempts at Madrid-Barajas Airport (LEMD). It reconstructs attempts,
checks telemetry quality, infers a runway direction where the observed geometry supports it, and
shows deterministic criterion evidence on a synchronized trajectory and timeline.

- **Application:** <https://sadar-analyst-console.fly.dev>
- **Immutable approach-screening artifact:** <https://huggingface.co/Txemapuch/sadar-demo-release>
- **Source:** <https://github.com/txema-puch/drone-ai-saturdays>

This is not emergency detection, stabilized-approach certification, ATC decision support, or a
safety verdict. The sealed 2026 evaluation retained 63.1% of reconstructed attempts, below the
precommitted 65% target, and no independent labels exist to measure review precision. The
candidate therefore failed operational qualification. It remains useful for inspecting evidence,
collecting labels, and learning what additional context is required.

Uploaded files and results are not intentionally retained by the application. Fly may preserve
Machine memory during suspension; do not upload confidential or proprietary data.

## What is served

1. **Observed-row reconstruction** — canonicalizes bounded OpenSky-style CSV or Parquet data and
   separates approach attempts inside each operation record.
2. **Quality and runway inference** — abstains on coverage gaps, telemetry conflicts, missing
   terminal evidence, or unsupported runway direction.
3. **Rules-first evidence** — evaluates lateral-path, barometric-path proxy, observed descent
   rate, ground-speed envelope, and late track correction. When loaded, the contextual research
   candidate can
   use supplied QNH for the pressure-altitude proxy, show airport-wind components, and select
   supported aircraft-type reference cells. It still does not infer airspeed, mass, configuration,
   clearance, or intent.
4. **Analyst workflow** — queue, attempt dossier, operation context, and ephemeral upload results.

The historical LSTM autoencoder is research history only. It is not required by the current
release and cannot change a status or queue position.

## Run the research candidate locally

```bash
docker build --platform linux/amd64 -t sadar-analyst-console .
docker run --rm -p 7860:7860 -e SADAR_ENABLE_EVALUATION=true sadar-analyst-console
```

Open <http://localhost:7860>. The tracked [`fly.toml`](fly.toml) enables bounded evaluation and
uses Fly autostart with zero minimum running Machines.

For local development:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
cp .env.example .env

cd frontend
npm ci
npm run dev
```

## Evidence and lifecycle

- [Active design](backend/docs/designs/33-approach-conformance-reframe.md)
- [Rules-first decision](backend/docs/ml/decisions/D-015-rules-first-approach-screening.md)
- [Approach-screening lifecycle](backend/docs/ml/iterations/approach-screening/manifest.yml)
- [Contextual lifecycle](backend/docs/ml/iterations/approach-context/manifest.yml)
- [Context source manifest](backend/docs/ml/iterations/approach-context/source-manifest.json)
- [Sealed evaluation](backend/docs/ml/iterations/approach-screening/07-eval.md)
- [Project workspace](backend/docs/README.md)

The original course scope—unauthorized-drone detection with an identity gate and LSTM anomaly
scorer—is preserved as historical research in
[`backend/docs/architecture/design-trajectory-anomaly-detection.md`](backend/docs/architecture/design-trajectory-anomaly-detection.md).
The notebooks under [`notebooks/`](notebooks/) remain reproducible evidence: they informed the
data audit, exposed limitations in terminal coverage, and provide independent checks against the
new attempt reconstruction.

Context inputs use NOAA NCEI Global Hourly weather and the OpenSky Network aircraft database.
OpenSky data are used only for this non-profit research/education demonstrator under its
[data terms](https://opensky-network.org/about/terms-of-use). Citation: Matthias Schäfer, Martin
Strohmeier, Vincent Lenders, Ivan Martinovic and Matthias Wilhelm, “Bringing up OpenSky: A
large-scale ADS-B sensor network for research,” ACM/IEEE IPSN, 2014. No raw source database is
redistributed in the release artifact.

## Team

Collaborative Saturdays.AI Madrid Deep Learning course project:

- Monica Gomez
- Pablo Rodriguez Campos
- Roberto Molero
- Txema Puch

Team members independently explored different implementations and ways to productize the shared
course problem. This repository is Txema Puch's analyst-workflow implementation.

## Repository layout

```text
backend/core/       approach geometry, reconstruction, quality and criteria
backend/serve/      immutable release loading, API and upload evaluation
backend/docs/       decisions, lifecycle evidence, designs and historical research
backend/tests/      deterministic and contract tests
frontend/src/       React analyst console
notebooks/          data, pipeline, training and evaluation investigations
data/               local working data; gitignored
backend/models/     local release artifacts; gitignored
```

Large data and model artifacts are not committed. Work on feature branches, keep secrets in
`.env`, and open a pull request for teammate review.
