---
license: other
tags:
  - aviation
  - ads-b
  - approach-conformance
  - synthetic-data
  - research
---

# SADAR Analyst Console public evidence release

This card describes the published schema-v4 archive for SADAR Analyst Console,
a research demonstrator for post-flight inspection of ADS-B-observable approach
criteria at Madrid-Barajas Airport (LEMD).

The archive is a **dataset/application evidence bundle**, not a Hugging Face model,
hosted inference endpoint, or model-serving package. The rules-first application does
not load the historical LSTM model.

## Release identity

- Dataset repository: `Txemapuch/sadar-analyst-console-release`
- Artifact: `sadar-approach-public-release.tar.gz`
- Artifact revision: `5f6b8522acf2e73e3478ba9033698fd44d5b6a1d`
- Release ID: `86a6eba6309600f56cd5`
- Schema: `4`
- Release kind: `sadar_approach_public_evidence`
- Deterministic archive SHA-256:
  `a1ce22743243b845c69d71f31d520a05ffb8e752efac4a12e858327fe74a7143`
- Synthetic generator: `sadar_synthetic_approach_v1`
- Seed: `20260718`
- OpenSky publication notice: **sent 2026-07-20**; acknowledgement is not claimed
- Hub publication status: **public**, anonymously verified
- Reviewed source revision:
  [`193c45604c1f644803c8547924b822bbd892215c`](https://github.com/txema-puch/drone-ai-saturdays/tree/193c45604c1f644803c8547924b822bbd892215c)

The immutable revision was anonymously redownloaded and revalidated before the
product lock was replaced.

## Three evidence lanes

| Lane | Included in archive | Meaning |
|---|---:|---|
| Deterministic synthetic demo | Yes | Fourteen generated scenarios, one attempt/case/operation each, for exercising the analyst workflow. Their position, speed, track, altitude and vertical-rate channels share one runway-relative kinematic construction. They are not recorded flights and do not estimate prevalence. |
| Aggregate real-data research | Yes | Suppression-safe counts, rates, coverage, provenance and limitations derived from real OpenSky research cohorts. No row, trajectory, aircraft identifier or exact source timestamp is included. |
| Ephemeral user upload | No | Bounded CSV or Parquet data evaluated in memory. Inputs and results are not intentionally retained and never alter the demo queue or aggregate findings. |

The eight payload files are `demo/catalog.json`, `demo/attempts.json`,
`demo/cases.json`, `demo/operations.json`, `research/aggregate-results.json`,
`config/approach-config.json`, `config/lemd-geometry.json`, and
`reference/approach-reference.json`. A release manifest binds every byte and contract.

## Qualification

This candidate is
`not_qualified_no_independent_labels_or_fresh_holdout`. Its only allowed role is
`research_and_evidence_labeling_demonstrator`.

Blocked uses:

- operational monitoring;
- emergency detection;
- stabilized-approach certification;
- ATC decision support; and
- safety-performance claims.

There are no independent analyst labels from which to estimate precision, recall,
AUROC, calibration or safety performance. The 2026 cohort is already burned, the
contextual comparison has no fresh untouched holdout, and status transitions measure
rule/reference behavior rather than correctness.

## Data source, access and notice

The real aggregate lane was derived from OpenSky Network ADS-B observations around
LEMD. To obtain source observations, use
[OpenSky data access](https://opensky-network.org/data/trino) directly and comply
with the [OpenSky terms of use](https://opensky-network.org/about/terms-of-use).

Publication notice status is **sent**, dated 2026-07-20. This card does not claim that
OpenSky has acknowledged the notice.

OpenSky citation:

> Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic, and Matthias
> Wilhelm. “Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research.”
> IPSN 2014.

## What the application does

1. Shows deterministic, internally consistent synthetic scenarios in a queue and analyst dossier.
2. Separates insufficient observation quality from observed criterion evidence.
3. Uses runway-relative geometry and transparent rules for lateral path, barometric
   path proxy, observed descent rate, ground-speed envelope and late track correction.
   The dossier plots those five synchronized signals and marks persistent review
   intervals on the signal that produced them.
4. Shows real research findings only as aggregates with denominators, suppression and
   interpretation limits.
5. Evaluates a user-supplied bounded file ephemerally against the published rules and
   aggregate-derived reference parameters.

It does not detect emergencies, establish stabilized-approach compliance, infer intent,
clearance, configuration or mass, or certify operational safety.

## Withdrawal history

The former schema-3 application archive was withdrawn from the public-delivery path
because it contained row-level OpenSky-derived observations, including trajectory and
aircraft fields. It must not be mirrored or used as the basis for a new public release.
The schema-v2 LSTM demo bundle and Phase-6 training archive remain historical research
artifacts only; neither can affect the current Analyst Console verdict or priority.

## Reproducibility

Source Git explains and reproduces the release; the dataset registry stores the
generated immutable archive. A clean checkout deterministically generates the fourteen
synthetic cases without reading row-level source data, checks cross-channel kinematic
consistency, combines them with the tracked aggregate resource, validates schema 4,
rebuilds the archive and proves its digest matches the public lock. Production uses the
explicit `locked-public` path and fails closed if that immutable schema-v4 lock drifts.

- [Source repository](https://github.com/txema-puch/drone-ai-saturdays)
- [Product overview](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/product/overview.md)
- [Architecture](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/product/architecture.md)
- [Rules-first decision](https://github.com/txema-puch/drone-ai-saturdays/blob/main/docs/product/decision-rules-first.md)
