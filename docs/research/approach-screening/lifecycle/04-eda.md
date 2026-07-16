# Phase 4 — Attempt-level EDA

## Cohorts

| Cohort | Attempts | Assessable | Not assessable | Review among assessable |
|---|---:|---:|---:|---:|
| Train 2017–2018 | 4,272 | 3,794 (88.8%) | 478 | 307 (8.1%) |
| Development 2019 | 2,740 | 2,255 (82.3%) | 485 | 271 (12.0%) |
| Newer source 2025 | 388 | 264 (68.0%) | 124 | 40 (15.2%) |

Direction mix is materially imbalanced: train contains 3,403 direction-32 and 869 direction-18
attempts; validation contains 2,214 / 526. All reference diagnostics remain stratified by
direction.

## Notebook findings retained

- Phase-4 `pass_d_approach=4,268` independently validates the new 4,272-attempt population.
- End-ground rates around 28% explain why final approach is observable more often than landing.
- Historical go-around work established that descent/climb must occur within one uninterrupted
  airborne run; the new outcome detector preserves that distinction on observed rows.
- The route-density baseline was weak and is not revived as analyst evidence.

## New-source finding

The 2025 pressure test proved the legacy runway coordinates were wrong by kilometres for current
displaced thresholds. Most low-altitude arrival records also end before the true threshold. The
new system therefore uses AIP geometry, calls 6 km `final_gate_observed`, and reserves
`landing_observed` for on-ground evidence.

Barometric path is unavailable on 387/388 newer-source attempts because no trustworthy bias can
be estimated. This is a first-class partial-observation result, not imputation.

## Gate result

Passed for experimental attempt screening. Source and altitude limitations are explicit; no
independent precision claim is made.
