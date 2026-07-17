# Phase 5 — Feature Engineering (entry artifact)

**Status:** complete
**Date:** 2026-06-01
**Phase:** features (Phase 5)
**Work item:** issue #25 · branch `25-task-phase5-features`
**Spec:** D-010 (runway-relative deferral), D-009 amendment (go-around hold-aside), D-008 Amendment 2 (go-around validation cohort)
**Code:** `backend/research/src/sadar_research/trajectory_anomaly/pipeline/features.py` (+ contract promotion in `backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py`) · **Tests:** `backend/tests/research/test_features.py`

Phase 5 turns the Phase-3 clean per-segment frames into the representation the LSTM-AE
trains on, and builds the held-aside **go-around** cohort the Phase-6 split and Phase-7
eval depend on. The test-set firewall is intact: **no split, no scaler fit, no `T`** —
all Phase 6 on TRAIN only. Every Phase-5 feature is **leak-free by construction**
(computed per segment from a fixed reference; no fitted statistic).

## The AE feature vector (the contract)

The single source of truth is `backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py` — `AE_FEATURES` /
`SCALER_FEATURES`. The synthetic-injection bench, the per-feature reconstruction-error
attribution, and the Layer-3 baseline all bind to these lists **by name**.

```
AE_FEATURES     = [lat, lon, baroaltitude, velocity, vertrate, dist_to_runway_m,   # 9
                   hdg_sin, hdg_cos, onground]
SCALER_FEATURES = [lat, lon, baroaltitude, velocity, vertrate, dist_to_runway_m]    # 6 (scaled, fit on TRAIN in P6)
```

| Feature | Kind | Rationale |
|---|---|---|
| `lat`, `lon` | measured | raw position; kept raw (degrees) so D-011's real-derived transplant stays lat/lon→lat/lon with no metre/degree conversion |
| `baroaltitude` | measured | altitude; the AE's vertical channel |
| `velocity` | measured | raw ADS-B groundspeed (NOT position-derived) — the kinematic channel the rules don't cover |
| `vertrate` | measured | raw vertical rate; climb/descent behaviour |
| **`dist_to_runway_m`** | **derived (new in P5)** | **nonlinear min-over-8-runway-thresholds haversine the LSTM-AE shouldn't have to rediscover; the zone signal the APW/geofence baseline + zone injection share.** Scaled (range 5–200,000 m). |
| `hdg_sin`, `hdg_cos` | derived | cyclic heading; unscaled (already [-1,1]) |
| `onground` | measured | binary ground state; unscaled |

`heading`, `flight_phase`, and the `*_missing` masks ride along in `clean_df` for
reference/diagnostics but are not AE inputs. `dist_to_runway_m` has no `*_missing` mask
of its own — its missingness rides on `lat`/`lon`'s masks (it is a pure function of them).

## Selection rationale (kept / rejected)

- **KEPT — `dist_to_runway_m` (promoted to a scaled AE input).** A sharp nonlinearity
  (min of 8 haversines) that encodes "how far from the operational zone am I." Already
  computed + re-derived after interpolation in Phase 3, never NaN.
- **REJECTED — full ENU `x_rel`/`y_rel` (runway-aligned metres).** Largely redundant
  with raw `lat/lon` for an LSTM (an affine transform the scaler already centres), adds
  2 features, and complicates D-011's clean lat/lon transplant. Revisit as a **Phase-6
  ablation** only if the AE underperforms on path structure.
- **REJECTED — runway bearing (sin/cos).** Direction-to-runway is derivable by the AE
  from `lat/lon`; the genuinely new signal is the *distance* nonlinearity, which we kept.
- **REJECTED — `n_imputed_*` as an AE input.** It is per-segment **constant**, so as a
  per-timestep channel it carries no within-sequence signal for a reconstruction AE. It
  stays where it belongs: a **meta cohort key** (D-008 Layer-1), not a model feature.

## Provenance — what each claim is based on (measured vs reasoned)

So the "✓" on this artifact is auditable, not asserted. Three bases: **measured** (a
number from the corpus or notebook 07), **decision** (a locked ADR), **reasoned** (domain
/ structural argument). The honest boundary: Phase 5 picks a *justified* representation;
whether it is the *best* representation is a Phase-6 ablation — you cannot score a feature
against val without the split + training, which is behind the firewall.

| Claim | Basis | Measured / decision / reasoned |
|---|---|---|
| Drop `velocity_kmh` (×3.6 copy) | notebook 07 cell 3 (ratio = 3.600) | **measured** |
| Drop `geoaltitude` (keep baro) | ~25% null vs baro ~13% (cell 3) | **measured** |
| Drop identifiers / `squawk` / heading→sin/cos | not kinematic; identity memorisation; cyclic wrap (Findings) | reasoned |
| Promote `dist_to_runway_m` (the deferred runway-relative signal) | D-010 deferral + eval-prep shared-geometry need | **decision** |
| `dist_to_runway_m` must be scaled | corpus range **5–200,000 m** | **measured** (this session) |
| `dist_to_runway_m` is a nonlinear signal worth giving the AE | min-of-8 haversines | reasoned (structural) — *not an ablation* |
| Reject ENU `x_rel/y_rel`, bearing | redundant-with-lat/lon (affine); keeps D-011 transplant clean | reasoned → **deferred to a P6 ablation** |
| Reject `n_imputed`-as-input | per-segment constant → constant channel | reasoned (true by construction) |
| Go-around cohort = 191 (0.96%) | single-airborne-run rule on the corpus + eyeballed profiles | **measured** (this session) |
| Derivation replay is exact | `apply_segment_derivations` vs `clean_df`: \|Δ\|≤1e-16, dist=0 | **measured** (this session) |
| Loss stays equal-weighted | writeup 09 reframe (AE's niche = kinematic anomalies the rules miss) | **decision** (carry to P6) |

**The one claim that is reasoned, not proven:** that `dist_to_runway_m` *improves* the AE
(and that ENU/bearing *wouldn't*). Its empirical test is the **Phase-6 feature ablation**
(incremental val score per feature group), run on TRAIN only. Phase 5's job is the
justified pick; Phase 6 proves it against the IF baseline.

## Go-around detector (held-aside cohort)

`meta['is_go_around']` — a per-segment boolean (parallel to `is_emergency`), set by a
geometric rule in `detect_go_around`, evaluated **within a single contiguous airborne run**:

> Within one airborne run, the aircraft **descends ≥ 300 m** into a low point **< 500 m
> within 5 km of a runway**, then **climbs back ≥ 300 m** — all without touching down.

The single-airborne-run constraint is the discriminator: departures start low (no descent
before the low point); normal arrivals descend to a touchdown (no airborne climb after);
**touch-and-gos touch down, which splits the airborne run** so the approach (descent, no
climb) and the takeoff (climb, no descent) fall in different runs and neither carries the
full signature. (An earlier global airborne-min rule misfired here — it counted a
touch-and-go's post-touchdown takeoff as the low point; the eng review + a touch-and-go
test caught it. See `test_features.py::test_touch_and_go_does_not_fire`.)

Domain constants (`GA_*` in `features.py`), validated against cycle-3 — not data-fit.

**Cohort: 191 / 19,849 segments (0.96%).** Spot-checked examples descend to ~410–480 m
near a runway then climb back to FL (~11,000–12,000 m) — textbook missed approaches.

**This is a HIGH-PRECISION, not exhaustive, cohort.** The 500 m cut + the single-run
(no-touchdown) constraint deliberately favour clean positives: go-arounds initiated above
500 m and touch-and-gos are excluded. Eval-prep should treat `is_go_around` as a **clean
positive set** (a real-anomaly cohort to score), **not a recall benchmark**.

**Routing:** held aside, **never trained on** — routed OUT of TRAIN at the Phase-6 split
(D-009 amendment), scored in Phase 7 as a real-anomaly validation cohort alongside the
Olive-7700 emergency set (D-008 Layer-4 companion). Eval-prep binds to `meta['is_go_around']`.

## Leakage check (mandatory)

For each feature, the inference-time question — *"at time T for segment E, is F defined,
correct, and computable without the future or the target or whole-dataset statistics?"*:

- `lat, lon, baroaltitude, velocity, vertrate, onground` — measured per row. ✓
- `dist_to_runway_m`, `hdg_sin`, `hdg_cos` — pure functions of the row's measured values
  + **fixed** runway geography. No fitted statistic, no cross-segment aggregation. ✓
- `is_go_around` — a per-segment geometric rule over that segment's own rows; **fixed**
  thresholds, no data fit. ✓
- **The only fitted object is the StandardScaler** over `SCALER_FEATURES` — and it is
  **NOT fit here**. `make_scaler()` stays unfitted; the fit is Phase 6 on TRAIN only.

No rolling stats, no target/count encoding, no whole-corpus normalisation — the usual
Phase-5 leakage traps don't appear because trajectory geometry is per-segment from a
fixed reference. The firewall holds.

## Carry-forward decisions (Phase 6)

- **No per-feature loss down-weighting.** The Phase-6 reconstruction loss stays
  **equal-weighted / framing-agnostic**. Down-weighting speed/heading (an old
  `07-eval-prep §6` rec, pre-reframe) is backwards: APW/MSAW already cover zone/altitude
  geometrically, so the AE exists to catch the kinematic/sequence anomalies (hover,
  speed spikes) the rules miss — exactly the channels a down-weight would kneecap
  (writeup `09`). **Per-feature RE is a diagnostic only** (a Phase-6 output), never a
  tuned weight, and never tuned against the synthetic bench.

## Injection-bench contract (for D-011 / the synthetic bench)

- **Derived → recompute, never perturb:** `dist_to_runway_m`, `hdg_sin`, `hdg_cos`.
  **Measured primitives → safe to perturb:** `lat, lon, baroaltitude, velocity, vertrate,
  onground` (+ `heading` as the measured handle behind the heading components).
- **Structural guarantee:** the bench perturbs the measured columns on the per-segment
  frame, calls **`apply_segment_derivations(seg)`** (replays `hdg_sin/cos` + `dist`),
  *then* windows + scales — so derived features stay consistent automatically, with no
  hand-maintained recompute-list. Verified idempotent on clean data to float precision.
- **⚠ Footgun (verified, test-locked):** perturb only the **measured handles** — `heading`
  for a heading change, `lat/lon` for a route/zone shift. `apply_segment_derivations`
  RECOMPUTES the derived channels, so a direct edit to `hdg_sin`/`hdg_cos`/`dist_to_runway_m`
  is **silently overwritten** (a holding injection that writes `hdg_sin` instead of
  `heading` vanishes). Locked by `test_replay_silently_reverts_a_direct_derived_perturbation`.
- **Injected timesteps set their `*_missing` masks to 0** (synthetic-but-present).
- **Contract bump:** `SCALER_FEATURES` is now **6** (adds `dist_to_runway_m`),
  `AE_FEATURES` is **9**. The bench binds by name (`feature_indices(AE_FEATURES, …)`) so
  it survives, but the prose in `07-eval-prep.md` / `D-011` / `sadar_synthetic_bench.py`
  was updated to match.

## Exit gate checklist

- [x] Final feature list documented with per-feature rationale.
- [x] Leakage check performed and documented (every feature leak-free; scaler fit is P6).
- [x] Selection rationale documented (kept `dist_to_runway_m`; rejected ENU/bearing/`n_imputed`-as-input).
- [x] Feature pipeline implemented as code, callable, deterministic, version-controlled (`features.py`, 13 tests).
- [x] Go-around cohort built before the P6 split, tagged, routed out of TRAIN; cohort size reported (287).

## Links

- Code: `backend/research/src/sadar_research/trajectory_anomaly/pipeline/features.py`; contract in `backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py`.
- Spec: [D-010](decisions/D-010-filter-d-and-multi-detector-preprocessing.md), [D-009](decisions/D-009-day-of-week-covariate-shift-probe.md), [D-008](decisions/D-008-output-validation-layers.md).
- Downstream: [D-011](decisions/D-011-real-derived-synthetic-anomalies.md), `07-eval-prep.md` (§6 + Feature-contract reconciliation), `references/sadar_synthetic_bench.py`.
- Phase-3 input contract: [03-preprocess.md](03-preprocess.md).
