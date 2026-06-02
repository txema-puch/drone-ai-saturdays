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

## Firewall semantics — `icao24` overlap (eng-review-2, 2026-06-01)

Measuring the actual cycle-3 data: **413 airframes fly in both TRAIN and TEST, 281 in
all three folds** (commercial jets recur at LEMD year over year). A clean year-based
temporal split therefore **cannot** also satisfy the originally-specified CRITICAL test
"no `icao24` spans two folds." Resolution (eng-review-2 + Codex outside voice):

- **Temporal-by-Monday is the load-bearing firewall** (train years < val < test). Kept.
- **`icao24` overlap is NOT asserted-to-zero.** `icao24`/`flight_id`/`callsign` are NOT in
  `AE_FEATURES` — they live only in split metadata — so the unsupervised AE has no *direct*
  identity channel and no label to memorise. CRITICAL test #3 is reframed from the
  impossible "no `icao24` spans folds" to **no-identity-leak**: assert
  `icao24` ∧ `flight_id` ∉ the built feature matrix. The overlap count is reported, not asserted.
- **Recurrence-optimism is MEASURED, not assumed away (Codex finding).** "No identity
  feature" kills only *direct* leakage; the AE can still learn an airframe's recurring
  kinematic *template* from the features, so a recurring jet's test reconstruction error is
  optimistically low. We quantify this: **notebook 09 reports VAL AUROC split by
  seen-in-train vs unseen-in-train `icao24`**, and the same seen/unseen breakdown is
  **pre-registered for the Phase-7 TEST burn**. Small delta → overlap was ~harmless (shown,
  not claimed); large delta → caveat the headline AUROC. Folds into the D-009
  restricted-regime honesty note. The wording in `07-train.md` is "no *direct* identity
  leakage; recurrence-optimism quantified by the seen/unseen delta" — never "harmless".

Implementation amendment of D-009's split discipline (consistent with its "identifiers
dropped" rationale); recorded in `07-train.md` + `manifest.test_set` at the gate. The
*primary* split contract (the locked fold table above) is unchanged.

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
- **Freeze after Phase 6 — persist a bench artifact** so the Phase-7 TEST run is
  byte-identical. The frozen bundle is `{seed, §6 calibration params, the TRAIN-fit
  StandardScaler, T, code/scaffold version}` written to `backend/models/phase6/bench_frozen.*`
  (gitignored — large/binary) with a small committed manifest of the hashes. "Freeze =
  seed only" is insufficient: the injection *rescales* with the train scaler, so the
  scaler + T must be pinned too or P7 cannot reproduce the val-injection distribution.

## Deliverable shape — modules + one notebook

Two layers, matching the project pattern (logic in `backend/core/*.py` with tests; the
exploratory/visual run in `notebooks/0X`):

- **Reusable, testable `.py` modules** (deterministic, imported by the notebook AND by
  Phase 7): `split.py`, `inject.py` (Generator A), `lstm_ae.py`, `baseline.py`. Unit
  tested. These are what Phase 7 re-imports to run the *frozen* generator + the trained
  model on TEST — so they must be importable, not notebook-only.
  **Placement:** module *code* lives in `backend/core/` (alongside `preprocessing.py` /
  `features.py`). **Not** `backend/models/` — that path is **gitignored** (for saved
  weights / fitted artifacts). Trained weights + the frozen bench → `backend/models/phase6/`
  (gitignored); the code that produces them → `backend/core/`.
- **`notebooks/09_phase6_train.ipynb`** — the training RUN + diagnostics: import the
  modules, run split → fit-on-train → train with **train/val loss curves** (guardrail
  #7), the IF-vs-AE **bake-off table**, the `dist_to_runway_m` **ablation**, and
  reconstruction-overlay plots. This is where you *see* train/val behaviour; nothing
  here touches TEST (firewall stays clean — modules are deterministic, notebook is
  read-only on the sealed fold).

## Engineering plan

1. **`split.py`** (module + test) — `split_by_monday(meta)` → train/val/test segment-id
   sets; pull held-aside; **no-identity-leak guard** (`icao24`/`flight_id` ∉ feature matrix —
   see "Firewall semantics"); assert test strictly latest; report `icao24` overlap (not zero).
   Persist the split (fold→Monday map, counts; the split itself is RNG-free) → `manifest.test_set`.
2. **Fit on TRAIN** (in `09` + helpers) — `StandardScaler.fit(train[SCALER_FEATURES])`;
   `T = P95(train segment len)`; `to_sequences(·, T, scaler)`.
3. **`inject.py`** (module + test) — Generator A wrapping the SADAR scaffold;
   `inject(df, scaler, T, seed)`; perturb-measured → `apply_segment_derivations` → window+scale.
4. **`baseline.py`** (module + test) — `IsolationForest` wrapper (run FIRST — guardrail #10).
   **Input = pooled per-segment summary stats** (mean/std/min/max per `SCALER_FEATURES`),
   not the flattened `T×9` sequence: padding-robust and the fair "simple baseline"
   (flattened makes IF score the pad zeros). Both IF and AE score the **same** injected
   segments so the bake-off is apples-to-apples.
5. **`lstm_ae.py`** (module + test) — encoder/decoder LSTM-AE; masked reconstruction loss
   (mask padding + imputed); **equal-weighted** (no per-feature down-weight — P5 carry-forward).
6. **`notebooks/09_phase6_train.ipynb`** — orchestrates 1–5: train with curves, bake-off
   (val AUROC/F2/FPR/PR-AUC per D-005 for IF vs AE on injected val), apply the selection +
   threshold + guardrail logic below, confirm `model_track`, run the `dist` ablation, and
   report the **seen-vs-unseen-`icao24` VAL AUROC delta** (recurrence-optimism, eng-review-2).
7. **`07-train.md`** + manifest `train` gate (records baseline, best model + val score +
   CI, **threshold**, fitted-pipeline artifact, `track_confirmed`).

## Model selection, threshold & guardrail (the bake-off logic)

Three distinct steps — keep them separate (an AUROC win is not automatically a ship):

1. **Selection (D-006, threshold-free):** compute **val AUROC** for IF and AE on the
   injected val. Ship the AE iff `AE_AUROC ≥ IF_AUROC + 0.03`, else ship IF. Confirm
   `model_track`.
2. **Threshold (set on VAL, never test):** the shipped model's anomaly score → binary
   needs a cut. Pick the threshold on the injected-val ROC/PR curve at the operating point
   (e.g. the highest-F2 point subject to `FPR ≤ 15%`). The threshold is a Phase-6 artifact
   applied unchanged to TEST in Phase 7 — selecting it on test would be a firewall leak.
3. **Guardrail (D-005):** the shipped model + chosen threshold must satisfy `FPR ≤ 15%` on
   val. If the AE wins selection (step 1) but cannot hit `FPR ≤ 15%` at any usable
   recall, that is a guardrail failure — document it and fall back to IF (or re-tune).
   Selection orders the models; the guardrail is a veto.

## Test plan (modules; the notebook is diagnostic, not unit-tested)

```
split.py            (backend/tests/test_split.py)
  ★★★ CRITICAL  no-test-leak: no TEST segment-id appears in train or val (partition disjoint)
  ★★★           no-identity-leak: icao24 ∧ flight_id ∉ AE_FEATURES / the built X — the property that
                makes airframe recurrence unable to leak (replaces impossible "no icao24 spans folds")
  ★★★           temporal: every TEST Monday > every TRAIN/VAL Monday
  ★★            held-aside (emergency ∪ go_around ∪ impossible) absent from all 3 folds
  ★★            deterministic by construction (fixed Monday→fold map, no RNG); fold counts match locked table
  ★★            icao24 cross-fold overlap REPORTED (413 train∩test, 281 all-3), NOT asserted-zero
                (seen-vs-unseen-icao24 VAL AUROC delta lives in notebook 09 — needs a trained model)
inject.py           (backend/tests/test_inject.py)
  ★★★ CRITICAL  inject() is never applied to the train fold (val/test only)
  ★★★           uses features.apply_segment_derivations (derived stay consistent) + the PASSED
                train-fit scaler — asserts it never calls make_scaler() (unfitted)
  ★★            injected timesteps set *_missing = 0; deterministic (seed); per-type mix ≈ §6
lstm_ae.py          (backend/tests/test_lstm_ae.py)
  ★★★ CRITICAL  masked reconstruction loss excludes padding AND imputed rows (zero gradient there)
  ★★            forward/recon shape = (N,T,9); deterministic with a fixed seed
baseline.py         (backend/tests/test_baseline.py)
  ★★            IF fits on train pooled-stats, scores val/test; pooled-stats shape stable
```

The three CRITICAL tests are the Phase-6 firewall guards — the analogues of P3's
interpolation-never-crosses-boundary + make_scaler-UNFITTED. They must exist before the
training run, not after.

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

1. ~~IF input shape~~ — **RESOLVED (eng review): pooled per-segment summary stats** (mean/std/
   min/max per `SCALER_FEATURES`), padding-robust; see engineering plan step 4.
2. AE capacity / `T` cap interaction — if P95 `T` is large, truncation rate vs compute (Finding C).
3. Val-injection rate — what fraction of val gets injected, and the per-type mix for a
   stable AUROC (follow §6 proportions; confirm N is enough for a tight CI).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run (no product-scope change) |
| Codex Review | `/codex` (outside voice) | Independent firewall challenge | 1 | issues_found → resolved | proxy-recurrence AUROC optimism; mitigation accepted |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | issues_found → resolved | run 1: 6 completeness gaps; run 2: firewall semantics (icao24 overlap) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | N/A (backend/ML, no UI) |

- **ENG run 1 (6, all resolved):** threshold-on-VAL step added; module placement
  (code → `backend/core/`, not gitignored `models/`); frozen-bench artifact bundle
  spec'd (seed+§6 params+train scaler+T+version); IF input decided (pooled summary stats);
  selection→threshold→guardrail sequenced (AUROC win ≠ auto-ship; FPR≤15% is a veto);
  3 CRITICAL firewall tests + per-module unit tests added to the test plan.
- **ENG run 2 (firewall semantics, 2026-06-01):** measured 413 airframes span train∩test
  (281 all-3) → the locked "no `icao24` spans folds" CRITICAL test is impossible. Reframed
  test #3 to **no-identity-leak** (`icao24`/`flight_id` ∉ feature matrix — the property that
  actually makes airframe recurrence safe); `icao24` overlap reported, not asserted-zero.
  See "Firewall semantics — `icao24` overlap".
- **CODEX (outside voice):** refuted "harmless" — "no identity feature" kills only *direct*
  leakage; the AE can still learn an airframe's recurring kinematic template, inflating test
  AUROC. Mitigation accepted: notebook 09 reports **seen-vs-unseen-`icao24` VAL AUROC delta**,
  pre-registered for the Phase-7 TEST burn; wording softened from "harmless" to "no direct
  leak; optimism measured." Already-covered points (deployment-realism ≠ broad generalization,
  Monday-skew) map to existing D-009/D-008 caveats.
- **CROSS-MODEL:** the one tension (is overlap "harmless"?) resolved in Codex's favour — claim
  softened + optimism now measured rather than assumed.
- **Firewall integrity:** confirmed — TEST(2020) sealed at split, inject val/test only,
  fit-on-train only, threshold-on-val; `burned` stays false until Phase 7.
- **Scope:** right-sized — reuses `build_features`/`to_sequences`/SADAR scaffold/sklearn;
  one innovation token (LSTM-AE, justified by D-006).
- **VERDICT:** ENG CLEARED (run 2) — ready to implement `split.py` + the 3 reframed CRITICAL tests.
