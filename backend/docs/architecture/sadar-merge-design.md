# SADAR merge — design & scoping

**Status:** PROPOSAL (discovery only — no merge code written, nothing committed to the teammate's repo).
**Date:** 2026-06-03.
**Owner:** Txema. **Coordination with:** devrup404 — **no message until C is built + deployed** (Txema's call: message him once it's done so he can decide if he wants B — his Space on our model). C needs no permission anyway (his frontend is MIT; we deploy our own Space + keep his attribution). His consent gates **only the optional B / dual-view stretch**.
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

### Frontend changes — an IA rebuild, NOT a relabel (see §4.5)
- The serve/data contract is unchanged, but the **information architecture is rebuilt** into a post-hoc analyst-triage flow (ranked queue → case file). His *components* are reused; his *narrative* (live Monitor) is replaced. Detail in §4.5.
- `Simulator.tsx` `KINDS` + `i18n.tsx` labels: swap his 5 kinds for ours (`zone_violation, altitude_high, sustained_loiter, final_approach_intercept, speed_spike`) with our slider ranges. (`zone_violation` is out-of-remit under D-012 but stays a valid *injectable* — fine in a sandbox what-if.)

### Docker (in our repo)
- Adapt his two-stage Dockerfile (Node frontend build → Python backend). Bake our scene artifacts + `lstm_ae_best.pt` + `scaler.joblib` instead of his `data/processed/*.npy`.
- Backend deps are our `backend/pyproject.toml` (`torch`, `scikit-learn`, `pandas`, `pyproj` already present; add `joblib`, `fastapi`/`uvicorn` already present). No `optuna` (training-only).
- Deploy as **our** HF Space (same container, new Space under our account — no push to his).

---

## 4.5 UI framing — post-hoc analyst triage (NOT real-time control)

**Decided 2026-06-03.** His SADAR UI is framed for **real-time controllers** (live radar scope, a "Monitor" page, alert-as-it-happens, detection-latency). That framing fits neither our model nor our use case:

- **Our model is a whole-segment scorer.** The encoder bottleneck is gathered at the *last valid timestep* → it needs the **complete trajectory** to produce a score, and the threshold (0.222) is calibrated on whole segments. It yields **one score per completed flight.** A live-streaming view over it would render a number it *cannot compute until the flight is over* — theater, not capability.
- **The modality can't see the threat live anyway.** Per D-010, ADS-B observes only *cooperating* aircraft; a non-cooperating intruder doesn't transmit. The honest job is **retrospective conformance audit of cooperating traffic** — "which completed LEMD operations deviated from learned-normal behaviour, and how." That is an analyst question about finished flights.

**Decision: a genuine analyst-triage IA** (not a light relabel of his screens):

- **Ranked queue — the primary flow.** The landing screen is retrospective triage: score-ranked completed segments ("of N segments, here are the most anomalous"), filterable, with per-type attribution. Replaces his live "Monitor" / incoming-traffic scope.
- **Case file — per-flight detail.** Opening a flight shows the trajectory (his radar/plot component, recast as a **case viewer**, not a live scope), the **per-step reconstruction-error timeline** (scrub to watch the deviation emerge — honest temporal dynamism, no fake real-time), the actual-vs-reconstructed overlay, and which feature drove the RE.
- **Simulator → analyst what-if.** Keep his onset/perturbation simulator, reframed from "detection latency" to "*where in the flight did it diverge, and by how much*." **Demote** detection-latency as a headline metric (a real-time concept); don't delete the machinery.

**What survives vs what's rebuilt:** his *components* (radar/trajectory plot, score timeline, reconstruction overlay, per-type metrics panel) are reused; his *information architecture + narrative* (Monitor / live scope / alert banner / latency-headline) is rebuilt as queue → case-file. So the frontend work is **a real IA rebuild on reused components**, not a vocabulary swap.

**Because it is a real IA rebuild, it is gated by a design stage (gstack), not coded ad-hoc** — see §4.5.2.

### 4.5.2 UI design stage (gstack design skills) — gates the frontend build

The analyst-triage IA (queue → case-file) is new design, not a relabel, so it goes through a deliberate design pass before any React is written:

- **Explore** — `/design-shotgun` (or `/design-consultation` for a fuller system + a `DESIGN.md` source of truth): generate variants of the two core screens (ranked queue, case file) and compare. Decide how much of his SADAR dark-ops radar aesthetic to keep vs restyle — his visual language already suits an ops/analyst tool, so this is likely *reskin the IA, keep the palette*, but the shotgun makes that an evidenced choice, not an assumption.
- **Lock** — `/plan-design-review`: rate the chosen direction dimension-by-dimension, fix the plan to a 10 before building. **Done 2026-06-03: 6/10 → 8/10.** Four build-changing fixes applied to the prototypes + serve data: (1) score **percentile + band** (precompute bakes it; served on queue + case), (2) **altitude profile** stacked over the RE timeline in the case file, (3) **linked scrub** playhead (timeline → trajectory marker), (4) queue **density + percentile column + segment-id search + loading/empty states**. Tokens formalized in **`/DESIGN.md`** (repo root) = the React token source of truth. Deferred to the React build (in DESIGN.md): list virtualization, WCAG-AA contrast verify, chart screen-reader fallbacks, keyboard nav, a real sans typeface.
- **QA (post-deploy)** — `/design-review`: visual audit on the live Space with before/after screenshots.

Only after Explore + Lock does the frontend IA rebuild (§6 step 6) begin. The precompute (§6 step 3, **done**) already fixes the data the screens render, so the design stage works against a real contract, not a guess.

**Outcome (2026-06-03, `/design-shotgun`): direction C "Forensic Dossier" LOCKED.** The OpenAI-image path was unavailable (no key), so variants were built as live HTML prototypes wired to the serve API (:8077) — better here than gen-images (real 4,480-row queue, real trajectories). Three queue directions compared (A keep-SADAR ops-radar / B light analytics workbench / C dark forensic dossier); C won — best post-hoc "case review" framing, dark canvas fits the reused trajectory plot, distinctive for the demo; A rejected because the green-on-black scope re-asserts the real-time framing. Both core screens prototyped in C (queue + case file with trajectory + deviation-span overlay, RE-vs-step-threshold timeline, per-feature attribution, analyst what-if). Artifacts: `~/.gstack/projects/txema-puch-drone-ai-saturdays/designs/ranked-queue-20260603/` (`variant-{A,B,C}.html`, `case-C.html`, screenshots, `approved.json`). These HTML prototypes are the implementation reference for the React build.

**Honest credit (for the writeup):** his sliding-window design *is* the more real-time-deployable of the two — say so. Ours wins on the conformance metric; his wins on streaming-readiness. Different strengths.

### 4.5.1 Dual-model / dual-view — explicit STRETCH (gate before B)

The genuinely-both end state: serve **both** models, each in its honest mode — **his streaming VAE-LSTM → a live monitoring view; our whole-segment AE → the audit view.** This is the true convergence (each model where it wins: his sliding-window can stream; ours has the higher real-anomaly ROC). **Deferred**, because it ~doubles serve surface (vendoring his model + his 7-feat/60-step pipeline alongside ours) and makes the deliverable explicitly co-authored — a credit/coordination conversation with devrup, not just a courtesy.

**Sequencing (locked 2026-06-03):** build the **single post-hoc tool first**; once it works, evaluate the dual story; **only then** decide whether/how to involve his side. The dual-view question is the natural moment the optional **B** comes back on the table — not before.

---

## 5. Known frictions (flag, not blockers)

1. **Whole-segment vs sliding-window — mostly dissolved by §4.5.** His live `/api/scene` swarm is *replaced* by the ranked queue, so the "many short slices vs few long arcs" concern no longer drives the primary flow. It only survives inside the case viewer (one full trajectory at a time — fine, even better for a single-flight view).
2. **Variable-length timelines.** His per-step arrays are fixed length 60; ours vary (≤260, masked). The case-file score-timeline + onset slider must trim to valid length. Mechanical.
3. **Frontend is an IA rebuild (C's main cost).** Not just a Node/pnpm + Vite frontend into a previously pure-Python repo — we rebuild the information architecture into queue → case-file (§4.5) on top of his reused components. Bigger than a relabel, but self-contained under `frontend/` + `backend/serve/`, and still far smaller than B's packaging + LFS friction.
4. **Attribution.** His frontend is MIT — reuse is granted; keep his licence/attribution in the vendored `frontend/`. Courtesy: give devrup a heads-up before vendoring (he'll almost certainly be glad his vis gets used).
5. **No CI on either repo.** Tests pass locally only (our 84 tests). Integration is verified by hand + the Space health check.
6. **B is devrup's call.** If we later offer B, it is a PR *he* reviews/merges into *his* Space — never a push from us, and never overwriting his own SADAR work.

---

## 6. Proposed sequencing (a FOLLOWING session)

Normal per-phase pattern on our side (issue + branch + PR to `develop`). **C is self-contained — it needs no permission from devrup**, only the courtesy heads-up (step 1).

**C — the build, single post-hoc analyst tool (we own all of it):**
1. **No message to devrup yet** — Txema messages him only once C is built + deployed, so he can decide whether he wants B (his Space on our model). Keep his MIT licence/attribution in the vendored frontend regardless.
2. **Vendor his frontend** — copy `external/sadar/frontend/` into our repo (`frontend/`), keep his licence/attribution.
3. **Triage precompute script** ✅ **DONE** — `backend/serve/precompute.py`: `phase6/clean_df.parquet` → 2020-test ∪ held-aside real anomalies (4480 segs) → frozen-contract scoring (T=260, masked mean RE, thr 0.222) → `models/sadar_demo/{queue.json, cases.json, manifest.json}` (ranked queue + per-flight path / reconstructed path / per-step RE timeline / feature attribution). Verified: anomaly mean 0.186 vs normal 0.114 — reproduces the Phase-7 signal.
4. **Write `backend/serve/` API** — fresh FastAPI app reusing his route shapes + `api.ts` interfaces, serving the precompute bundle. Queue endpoint (ranked list) + case-file endpoint (per-flight detail) — the `/api/flights` + `/api/flights/{id}` shapes already fit. `/api/simulate` → our `inject` replay; `/api/metrics` → `phase7_burn_results.json`.
5. **UI DESIGN STAGE (gstack, §4.5.2)** — `/design-shotgun` (or `/design-consultation`) to explore queue + case-file variants → `/plan-design-review` to lock. Gates step 6. Works against the real precompute contract from step 3.
6. **Frontend IA rebuild (§4.5)** — implement the locked design: ranked queue as the landing/primary flow; case file (trajectory case-viewer + per-step RE timeline + reconstruction overlay + feature attribution) as detail; simulator reframed to analyst what-if; demote latency; swap inject kinds + i18n. Drop the live "Monitor" framing.
7. **Docker** — adapt his two-stage build; bake our artifacts; **deploy our own HF Space**; verify `/api/health` + a manual queue→case walkthrough. `/design-review` for visual QA on the live Space.
8. **Writeup** — add a "deployment" section pointing at our live Space, framed as a **post-hoc conformance-audit tool**; credit his sliding-window design as the more streaming-ready; **ch.11 numbers unchanged** (merge ≠ model change).

**STRETCH — dual-model / dual-view (§4.5.1), evaluate only after C ships:**
9. Add his streaming VAE-LSTM as a second "live monitoring" mode beside our audit view. This is the gate where **B** (offering his Space our model, or co-deploying the dual tool) comes back — a credit/coordination conversation with devrup, decided then, not now.

---

## 7. Decision record candidate

Promote §4 to **ADR D-013 (deployment architecture)** under `backend/docs/ml/decisions/` + a pointer in `manifest.yml > decisions[]` once C lands. Until then this stays a proposal.
