# Phase 7 — Contextual evaluation

## Development comparison

The frozen contextual candidate was compared with the ADS-B-only engine on development cohorts.
The burned 2020 and sealed 2026 data were not read.

| Cohort | ADS-B-only review | Context review | Context-only | ADS-B-only only |
|---|---:|---:|---:|---:|
| Validation 2019 | 253 | 345 | 131 | 39 |
| Newer source 2025 | 40 | 50 | 12 | 2 |

On 2025, statuses move from 124 not-assessable / 224 partial / 40 review to 124 not-assessable /
163 partial / 51 criteria-observed / 50 review. Barometric path becomes observable on 337 rather
than 1 attempt. Ground-speed flags rise from 55 to 67 because supported types use attempt-balanced
train references. Of all attempts, 84.28% use at least one exact type cell and 83.76% use exact
type cells for every supported reference row.

## Interpretation

These transitions measure changed rule/reference behavior, not correctness. More observable
criteria and more review flags may help, hurt, or merely shift analyst workload. There are no
independent labels to estimate precision, recall, calibration, or incremental analyst value.

The ADS-B-only 2026 holdout is already burned and cannot qualify this successor. No new untouched
release cohort is available. Context thresholds and reference bands therefore remain development
choices and must not be presented as holdout-validated.

## Decision

Qualification **fails** with reason `no_independent_labels_or_fresh_holdout`. The candidate may
be deployed as a transparent research/evidence-labeling demonstrator if its limitations are
visible. Operational claims, alerting, or safety decisions remain blocked.

Reports: `artifacts/val-comparison.json` and `artifacts/2025-comparison.json`.
