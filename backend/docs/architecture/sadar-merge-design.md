# SADAR merge — design & scoping

**Status:** PROPOSAL (discovery only — no merge code written, nothing committed to the teammate's repo).
**Date:** 2026-06-03.
**Owner:** Txema. **Coordination required with:** devrup404 (SADAR author — it is his repo + his HF Space deployment).
**Inputs read:** `external/sadar/` (vendored, gitignored) full serve + data + model contract; our `backend/core/` contract + frozen Phase-6 artifacts.
**Related:** [[project_sadar_merge_next]], [[project_sadar_parallel]], [[project_ml_lifecycle]]; `backend/docs/ml/07-eval.md`.

---

## 1. The goal in one line

Two parallel Saturdays.AI projects on identical OpenSky-LEMD data should converge into one deliverable: **our pipeline + model** (the better-on-real-anomalies LSTM-AE, clean Phase 1–7 lifecycle) running inside **his product shell** (FastAPI + React radar demo + Docker + HF Space) — the deployable face we never built.

Phase 7 result that motivates this: on the held-aside real-anomaly cohort our AE scored **ROC 0.667** vs his VAE-LSTM **0.659** (a dead heat, slight edge to us); our pipeline carries the eval discipline (firewall split, five-layer credibility stack, per-type table). His repo carries the demo. Merge = take the best of each.

**Critical honest flag:** this merge is a **deployment/visualisation change, not a model change.** The shipped detector stays our Phase-6 LSTM-AE (`small/mean`, thr 0.222). So **Phase-7 numbers and writeup ch.11 do NOT change** — the merge gives those exact results a deployable UI; it does not re-open the eval gate.

---

## 2. His runtime contract (what SADAR actually is)

**Key discovery: his serve layer is a STATIC demo over a pre-computed test set, not a live monitor.**

`ConformanceService` (`serve/inference.py`) loads at boot:
- `data/processed/{test,val}.npy` — scaled window arrays (shape `(N, 60, 7)`),
- `scaler.npz` (`StandardScaler3D`, 7 features),
- a checkpoint via `load_autoencoder` (arch read from checkpoint metadata).

It scores every window once with `reconstruction_error(model, windows)` = per-window mean MSE over `(T, F)`. Everything the API serves is an index into `self.test`:

| Endpoint | Returns | Backed by |
|---|---|---|
| `GET /api/flights?limit&order` | ranked `{id, score, anomalous}` | `window_scores` argsort |
| `GET /api/flights/{id}` | `path[]`, `reconstructed[]`, per-step `scores[]`, thresholds | `test[id]` → unscale → `_to_path` (ENU→lat/lon inverse-proj) + `per_step_error` |
| `GET /api/scene?count` | sampled "typical" flights for the radar animation | median-ranked `test` indices, fake callsigns |
| `GET /api/metrics` | `model_comparison.json` rows | static file |
| `POST /api/simulate` | perturb one window → re-score → detection latency | unscale → `synthetic.<kind>` → rescale → `per_step_error` |

**The API boundary speaks `{lat, lon, alt, t}` paths + per-step score arrays + thresholds** (`frontend/src/api.ts`). The React frontend is **representation-agnostic** with exactly two couplings to his internals:
1. **Simulator kind vocabulary** is hardcoded (`route_deviation / altitude / speed / holding / freeze`) with per-kind sliders + i18n labels (`Simulator.tsx`, `i18n.tsx`).
2. Radar center hardcoded to LEMD `(40.4936, -3.5668)` — same airport as us, no change.

`threshold` = `val_percentile`-th pctile of val window scores (99.0); `step_threshold` likewise for per-step. Resample grid **10 s** — same as our cycle-3 native resolution.

---

## 3. The representation gap

| Axis | HIS (SADAR) | OURS | Reconcilable? |
|---|---|---|---|
| Airport / ref | LEMD `(40.4936,-3.5668)`, EPSG:32630 | LEMD, same | ✅ identical |
| Resample grid | 10 s | 10 s | ✅ identical |
| Coord frame | **ENU runway-relative** (`x_rel,y_rel`) | **raw lat/lon** | path render: ours is *easier* (no inverse-proj) |
| Features | 7: `x_rel,y_rel,baroalt,velocity,sin_hdg,cos_hdg,vertrate` | 9: `lat,lon,baroalt,velocity,vertrate,dist_to_runway_m,hdg_sin,hdg_cos,onground` (6 scaled, sin/cos/onground passthrough) | different vectors |
| Window | **60-step sliding, stride 30** (≈10-min slices, many per flight) | **whole-segment, padded to T=260, MASKED** (1 window/segment) | biggest gap (§3.1) |
| Scaler | `StandardScaler3D` over 7, `.npz` | sklearn `StandardScaler` over 6, `.joblib` | different artifact |
| Mask | none (dense) | loss mask (padding + imputed → 0) | ours-only |
| Model | VAE-LSTM | LSTM-AE (`32h/16z/1L`) | swappable |
| Score | mean MSE `(T,F)` | masked `mean`/`topk`/`max` MSE | ours needs mask |
| Inject vocab | 5 kinds (above) | 5 kinds: `zone_violation, altitude_high, sustained_loiter, final_approach_intercept, speed_spike` | different vocab |

### 3.1 Why the "feature-translation adapter" direction is incoherent

The memory framed the choice as *"adapter (our raw frame → his ENU 60-step rep) vs full-pipeline-swap."* Reading the code kills the adapter option:

- Our **model is trained on OUR 9-feature, 260-masked rep.** It physically cannot score his 7-feature, 60-step windows.
- If we translate our data *into* his ENU rep, then **his model (not ours) scores it** — which throws away the entire reason to merge (our better model + our `dist_to_runway_m`/`onground`/masking contract).

So a raw→ENU feature adapter is a dead end. The only coherent merge keeps **our pipeline + our model + our rep end-to-end** and swaps **his scoring core**, keeping his **API skeleton + frontend + Docker**. The "adapter" that remains is a thin **response adapter** (our scored outputs → his JSON shapes), which is trivial.

---

## 4. Decision — Direction B: graft our pipeline into his shell

**Rewrite `serve/inference.py` against OUR contract; keep his `app.py` routes, his React frontend, his Dockerfile / compose / HF Space wiring.** His repo stays his deployable artifact; the diff is contained to the scoring core + one frontend vocabulary swap + the baked artifacts.

Two sub-variants on *how our code reaches his Docker build*:

- **B1 (recommended): our `backend/core` as an installed dependency** of his backend. Smallest conceptual change, no copy-paste drift. **Blocker found:** our code is *not cleanly installable today* — no `__init__.py` markers (PEP-420 namespace via path), pyproject named `drone-rute`, imports are `from backend.core import …` resolved by repo-root-on-path. So B1 needs a packaging task first (carve `backend/core/*` + the frozen artifacts into a minimal installable `drone_core` wheel, or add his `pyproject` a path/git dependency that exposes `backend.core`).
- **B2 (fallback): vendor a frozen snapshot** of `backend/core/{geo,derivations,preprocessing,features,split,inject,baseline,lstm_ae}.py` + artifacts into his repo under e.g. `src/sadar/drone/`. Zero packaging work, but creates fork-drift (his copy goes stale when we touch core). Acceptable for a one-shot course demo that won't track our repo.

Recommendation: **B1 if we expect the demo to keep tracking our model; B2 if this is a freeze-once course deliverable.** Default to B2 for the course timeline unless devrup wants a living integration.

### What gets rewritten in `ConformanceService`

| His step | Our replacement |
|---|---|
| load `test.npy/val.npy` | precompute a **scene cohort** at build time: load `phase6/clean_df.parquet` + `meta.parquet`, select 2020-test-normal (+ a few held-aside go-around/emergency segments for a compelling demo), `to_sequences(clean_df, T=260, scaler)` → `(X, mask)` |
| `StandardScaler3D.load(.npz)` | `joblib.load(scaler.joblib)` (sklearn, 6 feat); sin/cos/onground passthrough |
| `load_autoencoder` | our `lstm_ae.load_checkpoint(lstm_ae_best.pt)` |
| `reconstruction_error(model, w)` | our `lstm_ae.reconstruction_error(model, X, mask, agg="mean")` |
| `per_step_error` | a masked per-step variant (we already compute per-step `se`; expose it, trim to valid mask length so the timeline matches the real path) |
| `_to_path` (ENU inverse-proj) | emit raw `lat/lon/baroalt` directly from the unscaled segment frame — **simpler than his** (we store lat/lon natively) |
| `synthetic.<kind>` (simulate) | our `inject.inject_segment` via `features.apply_segment_derivations` replay: perturb measured channel → recompute derived (`dist_to_runway_m`, `hdg_sin/cos`) → re-window+scale → re-score |
| `metrics()` static file | reshape our `phase7_burn_results.json` (headline + per-type) into his `MetricRow[]` schema |

### Frontend changes (minimal)
- `Simulator.tsx` `KINDS` array + `i18n.tsx` labels: swap his 5 kinds for ours (`zone_violation, altitude_high, sustained_loiter, final_approach_intercept, speed_spike`) with our slider ranges. (Note: `zone_violation` is out-of-remit under D-012 but stays a valid *injectable* — fine to expose in a sandbox simulator.)
- Everything else (radar plot, score timeline, alert banner, scene animation) consumes `{lat,lon,alt,t}` + score arrays unchanged.

### Docker changes (minimal)
- Swap the `COPY data/processed/{scaler.npz,test.npy,val.npy}` line for our baked scene artifacts + `lstm_ae_best.pt` + `scaler.joblib`.
- Add our core (B1 dependency or B2 vendored dir) + its deps (`scikit-learn`, `joblib`, `pandas`, `pyproj` already present, `torch` already present). Drop `optuna` (training-only).

---

## 5. Known frictions (flag, not blockers)

1. **Whole-segment vs sliding-window radar feel.** His `/api/scene` animates many ~10-min slices; our segments are full approach/departure tracks (fewer, longer). Renders fine, but the radar *looks* different — a handful of long arcs vs a swarm of short ones. Worth a deliberate scene-curation choice (maybe cap segment length for the animation).
2. **Variable-length timelines.** His per-step arrays are fixed length 60; ours vary (≤260, masked). The score-timeline + onset slider must trim to valid length. Mechanical.
3. **Packaging (B1).** Our core isn't a wheel today — see §4. This is the single biggest *engineering* task if we go B1.
4. **No CI on either repo.** Tests pass locally only (our 84 tests; his pass locally). Integration is verified by hand + the HF Space health check.
5. **Coordination / ownership.** It is devrup's repo and his HF Space. We do **not** push to it from here. The merge proceeds as a proposal he agrees to, then a PR *he* reviews/merges (or we fork + he pulls).

---

## 6. Proposed sequencing (a FOLLOWING session, after devrup agrees)

Normal per-phase pattern (issue + branch + PR to `develop` on our side; coordinate the actual graft with devrup):

1. **Coordinate** with devrup — share this doc, agree B1 vs B2 and who owns the deploy.
2. **Packaging** (if B1): carve `drone_core` wheel from `backend/core/*` + frozen artifacts; or (B2) freeze-vendor into his tree.
3. **Scene precompute script** — `clean_df`→ curated scene cohort → `(X, mask, paths, scores)` baked artifact (mirrors his `test.npy` role).
4. **Rewrite `serve/inference.py`** core against our contract (§4 table) + thin response adapter to his JSON shapes.
5. **Frontend** simulator vocabulary swap + i18n.
6. **Docker** artifact + dependency swap; rebuild; verify `/api/health` + a manual radar walkthrough.
7. **Writeup** — add a "deployment" section pointing at the live Space; **ch.11 numbers unchanged** (merge ≠ model change).

---

## 7. Decision record candidate

If devrup agrees, promote §4 to **ADR D-013 (deployment architecture)** under `backend/docs/ml/decisions/` + a pointer in `manifest.yml > decisions[]`. Until then this stays a proposal.
