# SADAR merge — design & scoping

**Status:** PROPOSAL (discovery only — no merge code written, nothing committed to the teammate's repo).
**Date:** 2026-06-03.
**Owner:** Txema. **Coordination with:** devrup404 — for **C** a courtesy heads-up only (his frontend is MIT; we deploy our own Space). His consent is a gate **only for the optional B** (a PR into his Space).
**Inputs read:** `external/sadar/` (vendored, gitignored) full serve + data + model contract; our `backend/core/` contract + frozen Phase-6 artifacts.
**Related:** [[project_sadar_merge_next]], [[project_sadar_parallel]], [[project_ml_lifecycle]]; `backend/docs/ml/07-eval.md`.

---

## 1. The goal in one line

Two parallel Saturdays.AI projects on identical OpenSky-LEMD data should converge into one deliverable: **his vis** (his MIT React radar demo + the serve skeleton) **brought into OUR repo, around our pipeline + model** (the better-on-real-anomalies LSTM-AE, clean Phase 1–7 lifecycle) — giving our rigorous lifecycle the deployable face we never built, in the repo that already owns everything that matters.

Phase 7 result that motivates this: on the held-aside real-anomaly cohort our AE scored **ROC 0.667** vs his VAE-LSTM **0.659** (a dead heat, slight edge to us); our pipeline carries the eval discipline (firewall split, five-layer credibility stack, per-type table). His repo carries the reusable frontend. Merge = take the best of each.

**Direction (decided 2026-06-03):** **C primary** — his vis → our repo, we own the build + deploy our own Space. **B is an optional downstream** — once C exists, the *same* serve rewrite can be offered to devrup as a PR so his Space also runs our model. See §4. (The earlier framing had B primary; reading the contracts + the HF-Space/LFS/packaging facts flipped it — §4.0.)

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

So a raw→ENU feature adapter is a dead end. The only coherent merge keeps **our pipeline + our model + our rep end-to-end** and swaps **the scoring core**, keeping the **API skeleton + frontend + Docker** shape. The "adapter" that remains is a thin **response adapter** (our scored outputs → his JSON shapes), which is trivial. The remaining question is purely *where that lands* — our repo (C) or his (B).

---

## 4. Decision — Direction C primary (his vis → our repo), B as optional downstream

The serve rewrite below is **identical** whether it lands in our repo or his — it rewrites the scoring core against our contract either way. So the only real choice is *where the frontend + the rewritten serve live*, and three independent facts all point to **our repo (C)**:

1. **Packaging.** Our `backend/core` is *not* cleanly installable (no `__init__.py` markers — PEP-420 namespace via path; pyproject named `drone-rute`; imports are `from backend.core import …` resolved by repo-root-on-path). In **our** repo it is imported **natively** — zero packaging work. In **his** repo (B) it must be wheel-packaged or vendored as a drifting snapshot.
2. **His repo is an HF Space, LFS-backed** (`origin = huggingface.co/spaces/devrup404/sadar`; his weights + `data/processed/*` are git-LFS). Direction B means pushing **our** model artifacts as new **LFS objects into his personal account's storage**, via the clunkier HF-Hub PR flow — intrusive.
3. **Ownership of the deliverable.** This is Txema's ML-lifecycle deliverable (the rigor, the writeup, ch.11 all live here). The demo belongs next to them.

What we take from SADAR is the genuinely reusable artifact — **his MIT-licensed React frontend** (`frontend/src/*`) + the serve *skeleton shape* — not his data/model/training code, which we replace with ours.

### 4.0 C primary, B optional — and what "both" means

- **C (the build, source of truth):** vendor his `frontend/` + a `Dockerfile` into **our** repo (e.g. `backend/serve/` + `frontend/`); write a **fresh FastAPI serve** that imports `backend.core` natively; deploy **our own** HF Space. Our repo owns the whole stack; the writeup links here.
- **B (optional downstream, his call):** because the serve rewrite is the same code, it can later be **offered to devrup as a PR** so his Space also runs our model. This is the only sane "do both" — *build once in C, offer B*; it is **not** a second, separately-engineered integration.

**Sequencing rule:** **C first, always.** Never do B in parallel or B-first — that re-incurs the packaging + LFS + cross-account-PR friction for a redundant second deploy. B is take-it-or-leave-it for devrup, after C works.

### What the new serve layer does (same core, now in OUR repo)

| His step (`ConformanceService`) | Our replacement (fresh `backend/serve/`) |
|---|---|
| load `test.npy/val.npy` | precompute a **scene cohort** at build time: load `phase6/clean_df.parquet` + `meta.parquet`, select 2020-test-normal (+ a few held-aside go-around/emergency segments for a compelling demo), `to_sequences(clean_df, T=260, scaler)` → `(X, mask)` |
| `StandardScaler3D.load(.npz)` | `joblib.load(scaler.joblib)` (sklearn, 6 feat); sin/cos/onground passthrough |
| `load_autoencoder` | our `lstm_ae.load_checkpoint(lstm_ae_best.pt)` |
| `reconstruction_error(model, w)` | our `lstm_ae.reconstruction_error(model, X, mask, agg="mean")` |
| `per_step_error` | a masked per-step variant (we already compute per-step `se`; expose it, trim to valid mask length so the timeline matches the real path) |
| `_to_path` (ENU inverse-proj) | emit raw `lat/lon/baroalt` directly from the unscaled segment frame — **simpler than his** (we store lat/lon natively) |
| `synthetic.<kind>` (simulate) | our `inject.inject_segment` via `features.apply_segment_derivations` replay: perturb measured channel → recompute derived (`dist_to_runway_m`, `hdg_sin/cos`) → re-window+scale → re-score |
| `metrics()` static file | reshape our `phase7_burn_results.json` (headline + per-type) into his `MetricRow[]` schema |

Keep `app.py`'s route shapes + `api.ts`'s response interfaces **unchanged** so his frontend works against our serve verbatim (the response adapter from §3.1).

### Frontend changes (minimal — to the vendored copy in our repo)
- `Simulator.tsx` `KINDS` array + `i18n.tsx` labels: swap his 5 kinds for ours (`zone_violation, altitude_high, sustained_loiter, final_approach_intercept, speed_spike`) with our slider ranges. (Note: `zone_violation` is out-of-remit under D-012 but stays a valid *injectable* — fine to expose in a sandbox simulator.)
- Everything else (radar plot, score timeline, alert banner, scene animation) consumes `{lat,lon,alt,t}` + score arrays unchanged.

### Docker (in our repo)
- Adapt his two-stage Dockerfile (Node frontend build → Python backend). Bake our scene artifacts + `lstm_ae_best.pt` + `scaler.joblib` instead of his `data/processed/*.npy`.
- Backend deps are our `backend/pyproject.toml` (`torch`, `scikit-learn`, `pandas`, `pyproj` already present; add `joblib`, `fastapi`/`uvicorn` already present). No `optuna` (training-only).
- Deploy as **our** HF Space (same container, new Space under our account — no push to his).

---

## 5. Known frictions (flag, not blockers)

1. **Whole-segment vs sliding-window radar feel.** His `/api/scene` animates many ~10-min slices; our segments are full approach/departure tracks (fewer, longer). Renders fine, but the radar *looks* different — a handful of long arcs vs a swarm of short ones. Worth a deliberate scene-curation choice (maybe cap segment length for the animation).
2. **Variable-length timelines.** His per-step arrays are fixed length 60; ours vary (≤260, masked). The score-timeline + onset slider must trim to valid length. Mechanical.
3. **Frontend toolchain into our repo (C).** We add a Node/pnpm + Vite frontend + a serve layer to a previously pure-Python ML repo. Bigger surface, but self-contained under `frontend/` + `backend/serve/`. This is C's main cost — and it is far smaller than B's packaging + LFS friction.
4. **Attribution.** His frontend is MIT — reuse is granted; keep his licence/attribution in the vendored `frontend/`. Courtesy: give devrup a heads-up before vendoring (he'll almost certainly be glad his vis gets used).
5. **No CI on either repo.** Tests pass locally only (our 84 tests). Integration is verified by hand + the Space health check.
6. **B is devrup's call.** If we later offer B, it is a PR *he* reviews/merges into *his* Space — never a push from us, and never overwriting his own SADAR work.

---

## 6. Proposed sequencing (a FOLLOWING session)

Normal per-phase pattern on our side (issue + branch + PR to `develop`). **C is self-contained — it needs no permission from devrup**, only the courtesy heads-up (step 1).

**C — the build (we own all of it):**
1. **Heads-up to devrup** — share this doc; tell him we're reusing his MIT frontend (courtesy, not a gate).
2. **Vendor his frontend** — copy `external/sadar/frontend/` into our repo (`frontend/`), keep his licence/attribution.
3. **Scene precompute script** — `phase6/clean_df.parquet` → curated scene cohort → `(X, mask, paths, scores)` baked artifact (mirrors his `test.npy` role).
4. **Write `backend/serve/`** — fresh FastAPI app reusing his route shapes + `api.ts` response interfaces; scoring core per §4 table, importing `backend.core` natively.
5. **Frontend** simulator vocabulary swap + i18n (our 5 kinds).
6. **Docker** — adapt his two-stage build; bake our artifacts; **deploy our own HF Space**; verify `/api/health` + a manual radar walkthrough.
7. **Writeup** — add a "deployment" section pointing at our live Space; **ch.11 numbers unchanged** (merge ≠ model change).

**B — optional downstream (devrup's call, only after C works):**
8. Offer the same serve rewrite to devrup as an **HF-Hub PR to his Space** so it also runs our model. Requires wheel-packaging or vendoring our core into his tree + pushing our LFS artifacts to his account — only if *he* wants it. Take-it-or-leave-it.

---

## 7. Decision record candidate

Promote §4 to **ADR D-013 (deployment architecture)** under `backend/docs/ml/decisions/` + a pointer in `manifest.yml > decisions[]` once C lands. Until then this stays a proposal.
