# Project workspace

Versioned working space for the SADAR course project and its product iterations.

## Current status — 2026-07-15

Three lifecycle tracks are preserved explicitly:

- **Historical LSTM anomaly experiment:** closed after its one-time 2020 evaluation. Its model,
  metrics, notebooks and decisions remain immutable research history; it is not the current
  product verdict.
- **Approach-screening v1:** implementation and schema-v3 artifact complete. The sealed 2026
  evaluation retained 63.1% of attempts against a 65% target and has no independent precision
  labels. Qualification failed and operational deployment is blocked. The console may only be
  presented as a post-flight research and evidence-labeling demonstrator.
- **Contextual approach v1:** NOAA QNH and OpenSky aircraft type pass development coverage gates;
  latest-prior airport wind reaches 78.09% and misses its 80% gate. The evidence is packaged as an
  explicit research candidate. Context changes coverage and workload, but no independent labels
  or fresh holdout exist, so it is not qualified as an accuracy improvement or operational product.

## Start here

1. [Issue #33 design](./designs/33-approach-conformance-reframe.md)
2. [D-015 rules-first decision](./ml/decisions/D-015-rules-first-approach-screening.md)
3. [Approach lifecycle manifest](./ml/iterations/approach-screening/manifest.yml)
4. [Context lifecycle manifest](./ml/iterations/approach-context/manifest.yml)
5. [Sealed evaluation](./ml/iterations/approach-screening/07-eval.md)
6. [Hugging Face model card](./ml/model-card.md)
7. [Data workflow](./workflow/data-pipeline.md)

## Navigation

| Section | Contents |
|---|---|
| [Problem](./problem/overview.md) | Current outcome, boundary and historical origin |
| [Architecture](./architecture/README.md) | Current rules-first system and historical designs |
| [Designs](./designs/) | Per-ticket implementation contracts |
| [ML lifecycle](./ml/) | Aggregate history and append-only iteration records |
| [Decisions](./decisions/README.md) | Product and data decisions |
| [Research](./research/) | Datasets, sources, papers and links |
| [Workflow](./workflow/data-pipeline.md) | OpenSky → snapshot → audit discipline |
| [Tasks](./tasks/README.md) | Historical weekly boards and active work items |
| [Writeup](./writeup/README.md) | Narrative material, mostly historical unless marked otherwise |
| [Weekly](./weekly/README.md) | Session notes |

The canonical validation notebook is
[`notebooks/05_phase2_data_validation.ipynb`](../../notebooks/05_phase2_data_validation.ipynb).
Other notebooks are evidence, not specifications: use them to reproduce or challenge lifecycle
claims, while the manifests and decision records remain the source of truth for current status.
