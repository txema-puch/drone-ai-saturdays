# Phase 3 — Preprocessing (entry artifact)

**Status:** complete
**Date:** 2026-06-01
**Phase:** preprocess (Phase 3)
**Work item:** issue #22 · branch `22-task-phase3-preprocessing`
**Spec:** [D-010](decisions/D-010-filter-d-and-multi-detector-preprocessing.md) (+ amendments below)
**Evidence base:** `research/trajectory-anomaly/notebooks/lifecycle/07_phase3_preprocess.ipynb` Findings A–E + Part 2 decisions
**Code:** `backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py` · **Tests:** `backend/tests/test_preprocessing.py`

Phase 3 produces the **unfitted pipeline definition** — the deterministic, fit-free
transform that turns raw cycle-3 ADS-B into a clean, uniform-grid, imputed,
segment-keyed dataframe ready for sequence-tensor construction. It does **not** split
and does **not** `.fit()` anything. The train/val/test split, the `StandardScaler`
fit, and the sequence length `T` are computed on **TRAIN only in Phase 6** (the
fit/transform firewall, guardrail #5). This is the load-bearing invariant of the phase.

## `pipeline_definition`

```
sort_segment_3min + filter_d + stage1_bounds + idle_trim + interpolate_mask
  + standardscaler(train) + pad_mask
```

**Model unit = SEGMENT** — a trajectory cut at every internal gap > 3 min. Flight-level
aggregation is deferred to Phase 7/8. Scored as a **complete trajectory, post-hoc
(batch)** — never streamed (see *Assumptions*).

## Ordered pipeline (the order is load-bearing)

The order is mandatory: segment/derive before anything crosses a gap; split before
interpolate; flag impossible→NaN before imputation; counters measured at a fixed
point (post-flag, pre-interpolate).

| # | Step | What it does | Why |
|---|---|---|---|
| 1 | `sort_and_dedupe` | sort by `(flight_id, time)`; drop exact-duplicate timestamps (`dt == 0`) | a zero `dt` would divide in speed/interp (codex #3) |
| 2 | `segment` | new `segment_id` at any gap > 3 min (`{flight_id}#k`) | a multi-minute hole breaks the 10 s grid; split, don't bridge (Finding C) |
| 3 | `filter_d` | keep flights with ≥1 engaging row, then drop post-split segments with **zero** engaging rows | LEMD-operation gate (D-010 Part 1); the segment-drop removes distant cruise fragments of engaging flights |
| 4 | `compute_speed` | `haversine(displacement)/dt` per segment | movement detector (NOT a velocity estimate — Finding E); position is never null |
| 5 | `trim_idle` | keep the active span (first→last moving/airborne row); drop pure-ground segments | flight-behaviour model shouldn't burn capacity on parked filler; in-queue waits stay in-span (Finding D) |
| 6 | `flag_kinematic_impossibility` | set hard-bound violations → `NaN`; airborne `velocity==0` placeholder → `NaN` | impossible values must be imputed, not trained on (codex #4 real bug) |
| 7 | `compute_counters` | per-segment `n_imputed_impossible` (hard bounds) vs `n_imputed_missing` (routine + placeholder) | measured post-flag/pre-interpolate (codex #5); the split keeps the D-008 cohort small (a merged counter tags ~69% of the corpus) |
| 8 | `resample_to_grid` | reindex each segment to a strict 10 s grid; linear-interpolate continuous; heading via sin/cos; ffill categorical; re-derive `dist_to_runway_m`; set `*_missing` masks | makes the uniform grid actually true (codex #2); interpolation never crosses a segment boundary (per-segment) |
| 9 | `encode_heading` | `hdg_sin`, `hdg_cos` from interpolated components | heading is cyclic — raw degrees put 359° and 1° two units apart |
| 10 | `tag_holdaside` | `is_emergency = squawk ∈ {7500,7600,7700}` per segment | held aside from TRAIN at the Phase-6 split (D-009); tagged here, not dropped |
| 11 | `filter_min_length` | drop segments < 30 rows after resample + trim | too short to carry behaviour |
| 12 | `make_scaler` | **unfitted** `StandardScaler` over `[lat, lon, baroaltitude, velocity, vertrate]` | scaling is fitted → fit on TRAIN only in Phase 6 (guardrails #5/#8) |
| — | `to_sequences(df, T, scaler)` | **definition only** — pad/mask/truncate contract | never called with real values in Phase 3; `T` + scaler fit are Phase 6 |
| — | `preprocess(raw) → (clean_df, meta)` | orchestrates 1–11; `meta` preserves `icao24, time, flight_id, segment_id, squawk, is_emergency, n_imputed_impossible, n_imputed_missing` | meta carries the Phase-6 split + held-aside keys (codex #7) |

## Feature contract

**AE input vector:** `[lat, lon, baroaltitude, velocity, vertrate, sin(hdg), cos(hdg), onground]`
+ per-feature `*_missing` masks (on `lat, lon, baroaltitude, velocity, vertrate, heading`).

- **Scaled** (`StandardScaler`, fit on train): `lat, lon, baroaltitude, velocity, vertrate`.
- **Passthrough** (not scaled): `hdg_sin, hdg_cos` (already [-1,1]), `onground` (binary).
- **Dropped:** `velocity_kmh` (exact ×3.6 copy), `geoaltitude` (25% null vs baro's 13%, same quantity),
  `squawk/callsign/alert/spi`/identifiers (not kinematic; identity lets the AE memorise aircraft).
- **Retained for Phase 5 (not an AE input):** `dist_to_runway_m` (ENU/runway-relative frame is Phase 5).

## Fit/transform boundary (the firewall)

Steps 1–11 are **fit-free** and run identically on train, val, test, and inference.
The only fitted objects — the scaler stats, `T`, and the split itself — are computed
on **TRAIN only in Phase 6**. `make_scaler()` returns an *unfitted* scaler;
`to_sequences()` is a pure function that takes `T` + a fitted scaler as arguments.
Phase 3 ends at the cleaned dataframe; it never crosses the split.

## Assumptions & limitations

- **Complete-trajectory, offline-only interpolation (guardrail #9 parity).**
  Linear interpolation reads *future* neighbours, which only exist if the trajectory
  is complete. We score whole segments post-hoc (batch), so offline/online parity
  holds *by construction* — but it silently breaks if anyone streams partial
  trajectories. This is also why the realistic user is a *retrospective* safety
  analyst, not a live controller.
- **Feed-specific value-repeat parity (Finding E).** ~20–27% of rows repeat the prior
  value (position/velocity/baro alike) — a property of the OpenSky 10 s scientific
  feed. Trained, validated, and held-out-tested on the same feed, so parity holds
  within the project; a different feed would need re-checking.
- **In-segment gap bound.** The > 3 min split guarantees no in-segment gap exceeds
  3 min (≤ 18 grid steps), so linear interpolation is always well-posed; the code
  asserts the post-imputation grid is strict 10 s and NaN-free.

## Validation (notebook `07` Part 3, against the real corpus)

The module reproduces the EDA numbers exactly:

| Quantity | Pipeline | EDA target |
|---|---|---|
| Filter D flights kept | 18,928 / 19,057 (99.3%) | 18,928 / 19,057 (99.3%) ✓ |
| Gap-split extra segments (> 3 min) | 2,598 | ~2,598 ✓ |
| `n_imputed_impossible > 0` cohort | 513 segments | 500–800 ✓ |
| `is_emergency` segments | 4 | ~4 ✓ |
| Final clean corpus | 3,155,859 rows / 19,849 segments | — |
| AE feature NaN after imputation | none | none ✓ |
| Strict 10 s grid per segment | all | all ✓ |

**Idle-trim reconciliation.** The notebook's Finding D measured idle-trim *per flight,
before gap-split*: **5.9%** of rows, **68** pure-ground flights. The pipeline trims
*per segment* (the locked model unit), giving **7.8%** of rows and **1,317** dropped
pure-ground segments — the extra coming from gap-split fragments that are entirely
on-ground plus the undefined-speed first row of each segment. The per-flight
computation reproduces 5.9% / 68 to the row (test-verified logic); the per-segment
7.8% is the operative pipeline number.

## Refactor (A1 — shared helpers extracted)

`haversine` + runway distance → `backend/research/src/sadar_research/trajectory_anomaly/data/geometry.py`; `flight_phase` + Filter-B
derivations → `backend/research/src/sadar_research/trajectory_anomaly/data/derivations.py` (leaf modules, no credentials).
`crud/opensky.py` re-exports them so notebook 05 and `download_opensky_states.py`
keep working unchanged; the downloader's own copies are migrated later under test.
This is what lets `preprocessing.py` and the test-suite import the helpers without
triggering `Settings()` (which needs `.env`).

## Open questions (deferred, not blocking)

1. **Imputation method refinement** — linear is the starting point; revisit only if
   Phase 7 D-008 Layer-1 Channel 2 shows high RE on the imputed cohort (D-010 OQ #1).
2. **`T` and split mechanics** — fixed `T ≈ P95` + pad/mask; computed on TRAIN in
   Phase 6. Group (`icao24`) + temporal (whole Monday) split, SADAR-confirmed.
3. **Per-phase (arrival vs departure) models** — flagged for Phase 5/6.
4. **`n_imputed` as an AE side-feature** — defer to Phase 5 feature engineering (D-010 OQ #4).

## Links

- Spec: [D-010](decisions/D-010-filter-d-and-multi-detector-preprocessing.md) (+ 2026-06-01 amendment)
- Cohorts / attribution: [D-008](decisions/D-008-output-validation-layers.md) (+ amendment)
- Hold-aside split rule: [D-009](decisions/D-009-day-of-week-covariate-shift-probe.md) (+ amendment)
- Architecture reconfirmation: [D-006](decisions/D-006-architecture-and-baseline.md) (+ amendment)
- Evidence: `research/trajectory-anomaly/notebooks/lifecycle/07_phase3_preprocess.ipynb` (Findings A–E, Part 2 decisions, Part 3 validation)
- EDA: [04-eda.md](04-eda.md)
