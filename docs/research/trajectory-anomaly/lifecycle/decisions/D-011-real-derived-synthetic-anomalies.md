# D-011 — Real-derived synthetic anomalies from Dataset #6 non-LEMD emergencies (onset-anchored maneuver transplant)

**Status:** decided — scoped as a **Phase-7 stretch** (not critical path; not yet implemented). Feasibility gate verified 2026-06-01.
**Date:** 2026-06-01
**Phase:** eval (Phase 7)
**Affects:** Phase 7 D-008 **Layer 2** (synthetic discriminative bench) and **Layer 4** (external validation — defines a firewall split); Phase 4 (the bbox-on-trajectories inspection feeds the split); the writeup (`09`, Methodology + Limitations).
**Related:** D-008 (validation stack), D-005/D-006 (metrics + model selection the bench scores against), D-010 (reframe + preprocessing the transplant must match).

## Context

OpenSky Dataset #6 — 832 flights that squawked **7700** (Olive et al., 2020) — is our Layer-4 external-validation set (D-008). The Phase-4 inspection (`research/trajectory-anomaly/notebooks/lifecycle/08_phase4_dataset6_emergency_eda.ipynb`) found only **N=6** LEMD-associated flights by airport code. That leaves **~826 non-LEMD emergency flights** otherwise unused.

Separately, the synthetic bench specified in `07-eval-prep.md §6` injects **hand-coded, drone-incident-calibrated** perturbations into LEMD-normal trajectories. Those are a *proxy* (drones don't broadcast ADS-B; the calibration is anchored to FAA/Bard drone statistics). Under the post-reframe framing (D-010, writeup `09`), the model is a **behavioral conformance monitor on cooperating manned aircraft** — and real emergency maneuvers (fuel-dump racetrack, depressurization rapid descent, engine/diversion turn-back) are *exactly* the "manned aircraft flying wrong" class the model's niche addresses. They are a **better-matched anomaly source than the drone proxy**, and we have ~826 of them sitting unused.

A concern was raised: extracting an anomaly "delta" seems to require knowing what *normal* looks like at each source airport — a per-airport modelling effort that would be prohibitive. This ADR records why that is **not** required, and the firewall discipline that makes reusing the non-LEMD flights safe.

## Decision

### Part 1 — Use the ~826 non-LEMD emergencies as an injection *source*, never for direct scoring
Direct scoring of non-LEMD emergencies with our LEMD-anchored model is **rejected** (see Alternatives A): it conflates "emergency" with "wrong airport / cross-airport distribution shift," and we have no non-LEMD *normal* control to separate the two. Instead, the non-LEMD flights are a source of **real anomaly kinematics** to inject into LEMD-normal trajectories — a Layer-2 (synthetic) enhancement.

### Part 2 — Onset-anchored, self-referential extraction (no per-airport normal model)
For each selected source flight:
- **Locate the emergency onset** = first timestamp where `squawk == "7700"`.
- **Baseline** = the flight's own **pre-onset** segment. **Maneuver** = the post-onset segment.
- **Extract relative delta sequences** of the maneuver against the baseline state: `Δtrack` (heading), `Δvertical_rate`, `Δgroundspeed`, `Δaltitude` over time.

The signature is **self-referential** (deviation from the flight's *own recent self*), so it needs neither a population/per-airport normal model nor change-point detection. This is the load-bearing reason the idea is tractable.

### Part 3 — Scope to discrete, trajectory-bearing emergency types
Select source flights via metadata; extract only a **handful of clean exemplar templates per type** (not all 826):
- **Fuel dump** (`avh_fueldump` / `tweet_fueldump` set) → racetrack/holding template.
- **Depressurization / rapid descent** (`avh_problem == cabin_pressure`) → sustained negative-vertrate template.
- **Engine / hydraulics / gear diversion + turn-back** (`diverted` set, heading reversal) → off-nominal reroute template.

**Skip** diffuse/gradual anomalies and medical-with-normal-landing (no separable trajectory signature).

### Part 4 — Transplant onto LEMD-normal with continuity
Graft the relative delta sequence onto the matching phase of a LEMD-normal trajectory, **ramping in at the splice** (the `_ramp` discipline in `docs/research/trajectory-anomaly/lifecycle/references/sadar_synthetic_bench.py`) to avoid discontinuities. Resample source 1 s → 10 s before extraction. Produce **ground-truth onset masks** (→ detection-latency metric). Re-apply the **train-fit scaler** (never re-fit).

### Part 5 — Firewall split (load-bearing)
- **Non-LEMD** emergencies → *spent* into the synthetic bench (Layer 2).
- **LEMD-area** emergencies → **sealed** as the Layer-4 external holdout. **The split line is the trajectory radius, not airport code** (see `dataset6-emergency-external-validation.md §9`, trajectory pass 2026-06-01): LEMD-area = flights with trajectory points **within 200 km of LEMD** (the 7 flights found). The airport-code-LEMD set is *not* the right boundary — 5 of those 6 flights have zero points in range and are unscoreable.
- The two sets **must never cross.** Deriving any injection template from a LEMD-area (within-200 km) flight would collapse the independent Layer-4 check into Layer-2 (circular). The geographic partition on *actual trajectory points* enforces this.

### Part 6 — Scope & sequencing
**Phase-7 stretch, not critical path.** The hand-coded `§6` bench ships regardless; this *enhances*, not replaces it. Sequenced after model selection (D-006) and the core synthetic eval. If Phase 6 runs long, ship without it and document as future work.

## Feasibility gate — VERIFIED (2026-06-01)

Read the trajectory parquet (`squawk7700_trajectories`, Zenodo 3937483): **4,344,359 rows, 11 columns** — `timestamp` (ms, UTC), `altitude`, `callsign`, `flight_id`, `groundspeed`, `icao24`, `latitude`, `longitude`, **`squawk` (string)**, `track`, `vertical_rate`.

- `squawk` is present **per timestamp**. The LEMD cabin-pressure flight `AFR11DN_20190816` transitions through `1000` (normal) → `7700` across its 3,193 rows. ⇒ **EASY tier**: the pre-7700 baseline is directly recoverable; **no change-point detection needed**.
- Kinematic columns (`altitude`, `groundspeed`, `track`, `vertical_rate`) are sufficient to extract maneuver deltas.
- Caveat: only a single `altitude` column (no baro/geo split). Harmless here — deltas are relative; map to our altitude feature on transplant.

This resolves the open question in `dataset6-emergency-external-validation.md §8` in favor of the cheap path.

## Alternatives considered and rejected

- **A. Direct scoring of non-LEMD emergencies** (even re-anchored to each flight's own destination runway) — rejected: conflates cross-airport distribution shift with emergency signal; no non-LEMD normal control. Permitted only as a weak, explicitly-caveated *secondary* signal (the `07-eval-prep` Layer-4 fallback), not a headline.
- **B. Population-normal delta extraction** (model normal at each of the ~50+ source airports, deviation against it) — rejected: a separate research project per airport; infeasible in a five-week timeline. This is the interpretation that *would* be "huge research"; Part 2 avoids it.
- **C. Use all 826 flights wholesale** — unnecessary; a few clean templates per discrete type suffice and keep quality high.

## Consequences

**Positive**
- Real-behavior-derived injections are strictly stronger evidence than hand-coded shapes, and better-matched to the post-reframe thesis than the drone proxy.
- Puts the otherwise-discarded ~826 flights to work; gives the per-type AE-vs-rules comparison (writeup `09`) a non-hand-designed anomaly class.
- Reuses the existing synthetic-bench scaffold (ramp, onset masks, scaler round-trip).

**Negative / risks**
- Added engineering: onset split is trivial, but **splice continuity + phase-matching** (inject a descent template into a descent-phase LEMD window, not a cruise window) are non-trivial.
- Validity rests on **maneuver/baseline separability** — holds for the discrete types in Part 3, not for diffuse anomalies (hence the scope limit).
- Emergency ≠ drone incursion — acceptable under the reframe (model is a general conformance monitor), but must be stated in the writeup.
- The firewall split must be policed rigorously; a single LEMD-derived template silently contaminates Layer 4.

**Writeup obligations (Limitations):** list the exact source flights/templates used; state they are real-emergency-derived (not drone); note diffuse anomalies were excluded; document the firewall split.

## Feature-contract reconciliation (2026-06 — post-#22 merge, Phase 3 closed)

This ADR (written before Phase 3 closed) used SADAR's feature vocabulary. The **shipped contract** (`backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py`) is:

```
AE_FEATURES     = [lat, lon, baroaltitude, velocity, vertrate, hdg_sin, hdg_cos, onground]   # the transplant TARGET
SCALER_FEATURES = [lat, lon, baroaltitude, velocity, vertrate]                               # standardized; the rest are not
to_sequences(df, T, scaler)  →  (N, T, 8)   # T + fitted scaler are Phase-6 artifacts
```

Source→target mapping for the transplant (Dataset #6 columns → our AE features), and the gotchas:

| Dataset #6 source (Part 2 delta) | → our AE feature | note |
|---|---|---|
| `latitude`, `longitude` | `lat`, `lon` | **both raw lat/lon — transplant is lat/lon→lat/lon, no metre/degree conversion needed** (cleaner than the hand-coded bench, which does need it) |
| `altitude` | `baroaltitude` | single source altitude col (no baro/geo split) |
| `groundspeed` | `velocity` | |
| `vertical_rate` | `vertrate` | |
| `track` | `hdg_sin`, `hdg_cos` | convert: `sin/cos(radians(track))` |
| — | `onground` | not in source; set consistently for the maneuver (airborne ⇒ 0) |

- **Scale only the 5 `SCALER_FEATURES`** in the unscale→perturb→rescale step; `hdg_sin/hdg_cos/onground` are unscaled.
- **Bind indices dynamically** via `feature_indices(AE_FEATURES, …)`, so the code survives Phase 5 adding runway-relative/zone features.
- Run **after the Phase-6 split**, against the fitted scaler — never `make_scaler()` (unfitted). The lat/lon→lat/lon transplant means Generator B (real-derived) is *less* affected by the contract change than the hand-coded Generator A (which assumed `x_rel/y_rel` metres).

**Update — post-#25 (Phase 5 closed):** the contract grew to `AE_FEATURES`=9 / `SCALER_FEATURES`=6 — **`dist_to_runway_m`** promoted into both (the shared zone signal). It is **derived** (`distance_to_closest_runway(lat, lon)`) → recompute-not-perturb. Since Generator B's transplant moves `lat/lon` directly, `dist_to_runway_m` follows for free via **`sadar_research.trajectory_anomaly.pipeline.features.apply_segment_derivations(seg)`** (perturb measured → replay derived → window+scale). "Scale only the 5 SCALER_FEATURES" above is now **6**. Go-around held-aside cohort: `meta['is_go_around']`. See `docs/research/trajectory-anomaly/lifecycle/05-features.md`.

## References
- `docs/research/trajectory-anomaly/lifecycle/decisions/D-008-output-validation-layers.md` — the 5-layer stack this slots into.
- `docs/research/trajectory-anomaly/lifecycle/07-eval-prep.md` — §6 hand-coded bench + "Reference implementation — SADAR synthetic bench" + "Post-reframe reconciliation".
- `docs/research/trajectory-anomaly/lifecycle/dataset6-emergency-external-validation.md` — Dataset #6 acquisition/firewall spec (§8 open question resolved here).
- `research/trajectory-anomaly/notebooks/lifecycle/08_phase4_dataset6_emergency_eda.ipynb` — the N=6 LEMD finding.
- `docs/research/trajectory-anomaly/lifecycle/references/sadar_synthetic_bench.py` — the injection scaffold (ramp, onset masks).
- the archived architectural-critique draft listed in `docs/archive-manifest.yml` — the framing + per-type comparison this feeds.
