# Design: Phase 6 — Train (split + Generator A val-injections + IF baseline + LSTM-AE bake-off)

> Work item: https://github.com/txema-puch/drone-ai-saturdays/issues/27
> Backend: github_project
> Branch: 27-task-phase6-train
> Date: 2026-06-01
> Spec: D-005 (metrics), D-006 (architecture + decision rule), D-009 (split + held-aside), D-008 (Layer-2 bench role)

## Problem (Why)

Phase 6 turns the unfitted Phase-3/5 pipeline into a trained, selected model. It is the
phase where **the test-set firewall becomes real**: the train/val/test split is DEFINED
and the test fold SEALED (`test_set.burned` stays `false` until Phase 7). It is also
where `model_track` confirms — LSTM-AE vs IsolationForest — by the pre-committed D-006
rule. Everything protected through P3/P5 ("no fit, no split, no `T`") is cashed in here,
on TRAIN only.

## Scope (What)

Build the split, the train-only fitted artifacts, the synthetic val-injection generator
(Generator A — a Phase-6 *prerequisite*, see below), the IF baseline, the LSTM-AE, and
run the bake-off. Produce `07-train.md` + flip the `train` gate.

## The split (LOCKED 2026-06-01)

Group-by-`icao24` (belt-and-suspenders) + **temporal hold-out by whole Monday**:

| Fold | Mondays | Segments (incl. held-aside) | Role |
|---|---|---|---|
| **TRAIN** | 2017–18 (9): 0605, 0731, 1002, 1204 / 0129, 0604, 0730, 1001, 1203 | 9,338 | fit everything; AE trains on TRAIN-normal only |
| **VAL** | 2019 (5): 0128, 0401, 0603, 0729, 0930 | 6,073 | model selection + tuning (synthetic AUROC) |
| **TEST** | 2020 (4): 0127, 0203, 0224, 0309 — **SEALED** | 4,438 | Phase 7 only; never scored here |

Rationale (full analysis in issue #27 thread): test = 2020 is the realistic deployment
test (score *future* flights) and SADAR-confirmed on the same data. **Honesty caveat:**
our 2020 is pre-COVID (cycle-3 excluded COVID from 2020-03-15), so this is a clean
temporal hold-out, **not** a distribution-shift stress test — stated in the writeup.
Temporal train/val (train < val < test) makes val AUROC a better predictor of test.
Group-by-`icao24` is belt-and-suspenders: we dropped identifiers, so the unsupervised AE
has no identity to memorise — the temporal criterion is the load-bearing one.

**Held-aside (D-009):** `is_emergency ∪ is_go_around ∪ (n_imputed_impossible>0)` are pulled
OUT before the split (never trained on) and scored in Phase 7 as real-anomaly cohorts.
The split operates on the **clean-normal** pool.

## Data flow

```
build_features(raw)  ──► clean_df (AE_FEATURES=9) + meta (cohorts)
        │
        ├── held-aside = is_emergency ∪ is_go_around ∪ n_imputed_impossible>0
        │       └──────────────────────────────────────────────► Phase 7 cohorts (sealed)
        │
        └── clean-normal pool ──► split by Monday (group-by icao24)
                 ├── TRAIN (2017-18) ──► fit StandardScaler ─┐
                 │                       compute T = P95(len) │  (TRAIN-only artifacts)
                 │                       to_sequences(train,T,scaler) ──► AE.fit / IF.fit
                 │                                            │
                 ├── VAL (2019) ──► to_sequences(val,T,scaler)
                 │        │              └──► [normal]  ─────────────┐
                 │        └──► Generator A inject (§6 calibrated) ──► [anomaly] ──┐
                 │                                                                ├─► val AUROC, F2, FPR, PR-AUC
                 │                                              IF.score / AE.RE ─┘   (D-005) ──► D-006 bake-off
                 │
                 └── TEST (2020) ──► SEALED ──────────────────────► Phase 7 (freeze Generator A, run once)

FIREWALL: inject anomalies on VAL/TEST only (AE trains on normal). TEST never touched in P6.
```

## Generator A — a Phase-6 PREREQUISITE (not Phase-7 prep)

The docs frame the synthetic bench as "Phase-7 prep," but it is **first needed in Phase
6**: D-006 model selection (`AE val AUROC ≥ IF val AUROC + 0.03`) and hyperparameter
tuning both score against *injected* anomalies — there are no real labels (D-008 OQ#1:
"model selection on synthetic val AUROC only"). So Generator A must exist and run on VAL
inside Phase 6.

- **Generator A** = the hand-coded, drone-incident-calibrated §6 injection types
  (`07-eval-prep.md §6`: zone-violation 40%, asymmetric-up altitude, sustained loiter,
  softened speed ≤10%, final-approach intercept, multi-drone) on the SADAR scaffold
  (`references/sadar_synthetic_bench.py`: ramp, onset masks, unscale→perturb→rescale).
- **Generator B** (real-derived, D-011) = Phase-7 stretch; NOT needed here.
- **Contract:** perturb the measured primitives on the per-segment frame, call
  `features.apply_segment_derivations` (replay `hdg_sin/cos` + `dist_to_runway_m`), then
  window + scale with the **TRAIN-fit** scaler. Inject on val/test only. Injected
  timesteps set `*_missing = 0`. Bind feature indices by name (`AE_FEATURES`).
- **Freeze after Phase 6** (seed + calibration) so the Phase-7 TEST run is byte-identical.

## Engineering plan

1. `split.py` — `split_by_monday(meta)` → train/val/test segment-id sets; pull held-aside;
   assert no `icao24` spans train↔val↔test (group check); assert test strictly latest.
   Persist the split (seeds, fold→Monday map, counts) → `manifest.test_set`.
2. Fit on TRAIN: `StandardScaler.fit(train[SCALER_FEATURES])`; `T = P95(train segment len)`;
   `to_sequences(·, T, scaler)`.
3. `inject.py` — Generator A wrapping the SADAR scaffold; `inject_val(val_df, scaler, T, seed)`.
4. Baseline: `IsolationForest` on flattened/pooled features (run FIRST — guardrail #10).
5. `lstm_ae.py` — encoder/decoder LSTM-AE; masked reconstruction loss (mask padding +
   imputed); **equal-weighted** (no per-feature down-weight — carry-forward from P5).
   Log train AND val curves (guardrail #7).
6. Bake-off: val AUROC/F2/FPR/PR-AUC (D-005) for IF vs AE on the injected val; apply D-006
   (ship AE iff `AE ≥ IF + 0.03`, else IF); record + confirm `model_track`.
7. `dist_to_runway_m` ablation: AE val AUROC with vs without the feature (the P5-deferred
   empirical test).
8. `07-train.md` + manifest `train` gate.

## Rejected alternatives (split)

- **Random group-only split** — weaker temporal story; doesn't test "score the future"
  (the deployment scenario). Temporal is the realistic discipline.
- **Pure SADAR year mirror with COVID-shift claim** — our 2020 is pre-COVID, so we can't
  claim the shift stress test; we keep the temporal cut but drop the claim.
- **Bigger-train temporal (train into 2019)** — considered; start with the clean
  train=2017-18 / val=2019 block, widen only if train/val curves show AE underfit.

## NOT in scope (deferred)

- Generator B (real-derived injections, D-011) → Phase 7 stretch.
- The TEST run / final eval → Phase 7 (one shot; `burned` flips there).
- Per-phase (arrival vs departure) separate models → revisit post-bake-off if needed.
- ENU `x_rel/y_rel` feature → only if the `dist` ablation shows path-structure underfit.

## Firewall guarantees

- TEST (2020) is sealed at split time; **never** loaded/scored in Phase 6.
- Scaler + `T` fit on TRAIN only; val/test only transformed.
- AE trains on TRAIN-normal only; injections never touch train.
- Generator A frozen after Phase 6 → Phase-7 test run identical.

## Open questions

1. IF input shape — pooled per-segment summary stats vs flattened sequence? (decide at impl).
2. AE capacity / `T` cap interaction — if P95 `T` is large, truncation rate vs compute (Finding C).
3. Val-injection rate — what fraction of val gets injected, and the per-type mix for a
   stable AUROC (follow §6 proportions; confirm N is enough for a tight CI).
