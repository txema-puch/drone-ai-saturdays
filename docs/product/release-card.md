---
license: other
tags:
  - aviation
  - ads-b
  - trajectory-analysis
  - approach-conformance
  - anomaly-detection
  - research
---

# SADAR Analyst Console release artifacts

This repository publishes the immutable release artifacts used by
[SADAR Analyst Console](https://sadar-analyst-console.fly.dev), a research demonstrator for
post-flight screening of ADS-B-observable approach attempts at Madrid-Barajas Airport (LEMD).

This repository is an artifact registry, not a Hugging Face Transformers model or hosted
inference endpoint. It contains application release evidence plus a frozen historical training
archive. The current product is rules-first: it reconstructs approach attempts, checks telemetry
quality, infers runway-relative geometry when supported, and exposes criterion evidence for
analyst review.

## Why there are three artifact groups

| Artifact | Status | What it contains |
|---|---|---|
| `sadar-approach-release.tar.gz` | **Current release candidate** | Schema-v3 approach evidence, deterministic rules, statistical references, contextual provenance and precomputed analyst records. Release `491f81fb1d896b0d793e`, engine `approach_context_v1`. |
| `sadar-demo-bundle.tar.gz` | **Historical benchmark only** | Schema-v2 behavioral-anomaly demo bundle with the earlier whole-segment LSTM autoencoder evidence. Release `fb116d628a274309a387`. It cannot affect current statuses or queue priority. |
| `research/trajectory-anomaly/phase6/sadar-phase6-training-artifacts.tar.gz` | **Historical training replay only** | Frozen Phase-6 LSTM checkpoint, fitted scaler, and kNN summary matrix used to reproduce the old model comparison. This is neither a served model nor an application release. |

The schema-v2 bundle is a precomputed application-evidence bundle: it combines historical model
outputs with the records needed by that older demo. The Phase-6 archive contains the smaller
training outputs needed to replay the model comparison. Neither is a second production model or
part of the current decision path.

The Phase-6 archive is pinned at revision
`fd21b357b7e24a8f1f3f1c8de6c5927cedaab7ad` with SHA-256
`1bc57e16c03773875335bdf38b94e3c8377250f0b933dfe5bcf149a8f1b946d0`; its per-file hashes
are recorded in
`backend/research/src/sadar_research/trajectory_anomaly/releases/phase6_training_artifacts.lock.json`.

## Current immutable release

- Release ID: `491f81fb1d896b0d793e`
- Hub revision: `db1a1a9232b3b96276a169a070852f619eec7c21`
- Archive SHA-256: `1f135728a0c235c245b5107a509cb73f1757ac4ced7346f123a1ea70a732c093`
- Reference digest: `68ea1a974a077e0b2ef8322564d7799c5fd52cbd21db42b8d5bf1badad57d328`
- Schema: `3`

Download the exact pinned artifact:

```bash
hf download Txemapuch/sadar-demo-release sadar-approach-release.tar.gz \
  --revision db1a1a9232b3b96276a169a070852f619eec7c21 \
  --local-dir .
```

The application verifies the archive hash, release manifest, file hashes, schema, provenance
links and safe extraction boundaries before serving it.

## What the current release does

1. Reconstructs bounded OpenSky-style CSV or Parquet rows into operations and separate approach
   attempts.
2. Abstains when coverage, telemetry consistency, terminal evidence or runway geometry is not
   sufficient.
3. Evaluates transparent evidence for lateral path, barometric-path proxy, observed descent rate,
   ground-speed envelope and late track correction.
4. Uses supplied QNH, wind and supported aircraft-type references when available, with explicit
   fallback when context is missing.
5. Produces analyst-facing statuses and evidence exports. It does not produce a safety verdict.

## Evaluation status

This candidate is **not operationally qualified**.

- The sealed 2026 ADS-B-only evaluation retained 63.1% of reconstructed attempts, below the
  precommitted 65% target.
- No independent analyst labels exist, so review precision, recall and calibration are unknown.
- The contextual successor has no fresh untouched holdout. Its changes measure different
  rule/reference behavior, not improved correctness.
- The earlier LSTM autoencoder was evaluated as a trajectory-anomaly research benchmark. Its
  anomaly score does not establish emergency, incident or unstable-approach detection.

The release is useful for inspecting evidence, collecting independent labels, testing the analyst
workflow and learning which additional data are required.

## Intended and prohibited uses

Appropriate uses:

- non-profit research and education;
- post-flight evidence inspection;
- analyst workflow evaluation and label collection;
- reproducibility and comparison with the historical LSTM benchmark.

Do not use it for:

- emergency or incident detection;
- real-time alerts or operational monitoring;
- stabilized-approach certification;
- ATC, flight-crew or safety decisions;
- claims about aircraft intent, clearance, configuration, mass or airspeed.

## Data and limitations

The research uses OpenSky Network ADS-B observations around LEMD. Optional contextual inputs use
NOAA NCEI Global Hourly weather and the OpenSky aircraft database. ADS-B does not directly provide
many operational variables required for a true stabilized-approach assessment, including aircraft
configuration, mass, clearance, intent and indicated airspeed.

No raw OpenSky or NOAA source database is redistributed in these archives. OpenSky-derived work is
limited to non-profit research and education under the
[OpenSky terms of use](https://opensky-network.org/about/terms-of-use). The `other` license marker
reflects the mixed code, artifact and source-data conditions; review the source repository and
upstream data terms before reuse.

## Reproducibility and documentation

- [Source repository](https://github.com/txema-puch/drone-ai-saturdays)
- [Application](https://sadar-analyst-console.fly.dev)
- [Active design](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/product/design.md)
- [Rules-first decision](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/product/decision-rules-first.md)
- [Sealed evaluation](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/research/approach-screening/lifecycle/07-eval.md)
- [Contextual evaluation](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/research/approach-context/lifecycle/07-eval.md)

## Citation

For OpenSky data, cite: Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic and
Matthias Wilhelm, “Bringing up OpenSky: A large-scale ADS-B sensor network for research,” ACM/IEEE
IPSN, 2014.
