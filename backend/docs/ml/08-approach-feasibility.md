# New iteration feasibility — observed approach-attempt screening

**Date:** 2026-07-14
**Status:** feasible with explicit partial evidence and abstention
**Scripts:** `backend/scripts/approach_feasibility.py`,
`backend/scripts/audit_approach_dataset.py`, `backend/scripts/fit_approach_reference.py`

## Firewall

Historical feasibility accepts only `train` and `val`; the burned 2020 fold is rejected. The
external audit hashes its input before reading and rejects the sealed 2026 digest
`16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899`.

## Geometry correction from notebook pressure-testing

The new pipeline binds to ENAIRE AIP `LEMD AD 2.12`, effective 2026-07-09. Its PDF digest is
`65e114a09a8ce06d50a36b96eb5f7b333ac625effdbfa5c7f78a98524a683d1b`. The legacy notebook
threshold constants are materially wrong: on audited 2025 arrivals they place a threshold about
2–3 km before the current AIP displaced threshold. The old `dist_to_runway_m` therefore made
coverage-limited final approaches look like runway arrivals. It is retained only for the frozen
historical model.

The new analysis gate is 6 km, approximately the nominal 1,000 ft point on a 3° path. Reaching it
is `final_gate_observed`, never proof of landing. Only an actual near-threshold `onground` row is
`landing_observed`.

## Observed-row feasibility

Interpolated rows marked by model-era missingness masks are excluded. Eligibility requires 20
observations over at least 90 seconds; evidence persistence is time-based so 1-second and
10-second sources have the same meaning. Position conflicts and >60-second gaps abstain the
attempt. Altitude-rate conflicts suppress only barometric-path evidence.

| Measure | Train 2017–2018 | Validation 2019 | Audited 2025 source |
|---|---:|---:|---:|
| Candidate operations | 8,594 | 5,508 | 1,285 |
| Operations with attempts | 4,259 | 2,731 | 388 |
| Attempts | 4,272 | 2,740 | 388 |
| Assessable | 3,794 (88.8%) | 2,255 (82.3%) | 264 (68.0%) |
| Review required among assessable | 307 (8.1%) | 271 (12.0%) | 40 (15.2%) |
| Not assessable | 478 (11.2%) | 485 (17.7%) | 124 (32.0%) |

The 4,272 train attempts independently match the Phase-4 notebook's 4,268 `pass_d_approach`
records within four attempts, while the extractor finds 4,272 attempts in 4,259 operations. This
confirms the notebook population and proves `flight_id` is not the final modeling unit.

## Train-only empirical reference

The published `approach_reference_v1` contains ten runway-direction/distance cells fit from 3,764
eligible train attempts. It uses 1st/99th percentile ground-speed and observed vertical-rate
bands. The artifact digest is
`b485f747154ea8d84ba6b5c980501e3a22bca9caff40c41711de107b03496c56`.

- Calendar stability passes: maximum 2017/2018 median shift is 0.0769 of the corresponding
  reference width, below the precommitted 0.5 limit.
- Fleet conditioning is unavailable in the historical artifact and is explicitly `unknown`.
- Historical fit has one OpenSky collection product. The separately collected 2025 source is a
  validation cohort, not reference-fitting data.

## Limitations carried forward

- In 2025, 387/388 attempts lack a trustworthy barometric-height bias because coverage usually
  ends before threshold-adjacent or on-ground observations. The path proxy abstains; independent
  lateral, ground-speed, vertical-rate and track evidence remains available.
- No independent runway label or human review-worthy-pattern labels exist yet. Geometry agreement
  and workload are feasibility evidence, not precision claims.
- Current AIP geometry applied historically is a disclosed prototype assumption.
- The reference is provisional and unconditioned on aircraft type, wind or QNH.

The ADS-B-only pipeline clears its assessable-coverage feasibility floor on historical,
development and newer-source data. It does not clear the independent-label evaluation gate.
