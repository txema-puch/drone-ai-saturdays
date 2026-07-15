# Phase 2 — Data

## Sources and roles

- 2017–2018 OpenSky scientific Mondays: training/reference fitting only.
- 2019 OpenSky scientific Mondays: development validation only.
- Burned 2020 fold: historical diagnostic only; excluded from this iteration.
- March 2025 audited snapshot: later-source temporal/source validation.
- March 2026 audited snapshot: burned once on 2026-07-14 only after the assessment contracts and
  metrics were frozen; it cannot be reused as a fresh release gate.

## Geometry

ENAIRE AIP LEMD AD 2.12, effective 2026-07-09, is versioned at
`backend/core/resources/lemd_runways_2026-07-09.json`. Applying current geometry historically is
a disclosed prototype assumption until historical effective charts are sourced.

## Feasibility audit

`backend/scripts/approach_feasibility.py` rejects the burned test fold. On train and 2019
validation, runway-attempt inference independently matches the older Phase-4 approach-rule
population. Attempt assessability is 88.8% / 82.3%. The separate 2025 source audit retains 68.0%
and exposed the legacy runway-coordinate error plus systematic low-altitude coverage loss.

The train-only reference uses 3,764 eligible attempts. Calendar-year stratification passes; fleet
conditioning is unavailable and explicit `unknown`. The published reference digest is
`b485f747154ea8d84ba6b5c980501e3a22bca9caff40c41711de107b03496c56`.

## Open data-gate work

- Validate candidate-record reconstruction and attempt outcomes on a probability sample.
- Obtain aircraft-type data before claiming fleet-conditioned speed evidence.
- Define lawful joins and missingness for the later weather/QNH/wind/aircraft iteration.

## Holdout outcome

The one-time 2026 burn reconstructed 613 attempts from 1,426 operations and retained 387 (63.1%)
as assessable. This missed the 65% gate. See `07-eval.md`; no data or criterion decision may be
retuned from this cohort.
