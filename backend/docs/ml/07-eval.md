# Phase 7 — Evaluation (the test burn + the blind real-anomaly head-to-head)

**Status:** passed · **Date:** 2026-06-02 · **Issue:** #29 · **Test:** BURNED (once)
**Artifacts:** `backend/scripts/phase7_burn.py`, `backend/models/phase6/phase7_burn_results.json`,
`notebooks/13_phase7_eval.ipynb`
**Decides:** ship the **LSTM-AE** (model_track `dl` confirmed) on the pre-registered
real-anomaly criterion. Primary synthetic AUROC > 0.85 **not** met (0.731) — reported honestly.

> Read this top-down. The headline is **not** the synthetic mean — it is (1) the per-type
> AE-vs-rules table and (2) the real-anomaly head-to-head. Both were pre-registered before the
> burn (07-eval-prep.md "Layer 6", 2026-06-01; D-012 entry decision, 2026-06-02).

---

## 1. The result that matters — real anomalies (Layer 6)

Real go-arounds + emergencies neither model trained on, scored blind. This is the contest a
synthetic bench cannot be calibrated toward. Negatives = **2020-test-normal** (same year/regime
SADAR uses, so the cross-project comparison is apples-to-apples; this is post-burn — the test is
open). Model selection itself used **val-normal** (firewall-clean, §5).

| model | real-anomaly ROC | real-anomaly PR | notes |
|---|---|---|---|
| **our LSTM-AE** (small/mean) | **0.667** | 0.088 | the representative (ships) |
| our kNN-on-summary (k=5) | 0.595 | 0.067 | synthetic winner, loses on real |
| IsolationForest (D-006) | 0.495 | 0.043 | ≈ chance |
| SADAR VAE-LSTM (his native rep) | 0.659 | 0.299 | reproduced exactly from his weights |

Cohort: held-aside `emergency ∪ go_around` = 195 segments (191 GA + 4 emergency), prevalence
4.4% vs the 4,285-segment test-normal.

**Two findings, both pre-committed:**

1. **The AE beats the kNN on real anomalies** (ROC 0.667 vs 0.595; PR 0.088 vs 0.067) — and also
   on val-normal (0.591 vs 0.551; 0.048 vs 0.043, §5). This **inverts** the synthetic result,
   where the kNN wins (§2). The pre-registration anticipated exactly this: a summary-stat kNN can
   be *summary-normal but order-abnormal* on real go-arounds, which the AE's sequence model
   catches. Per the pre-committed rule (higher real-anomaly PR-AUC → representative), **we ship
   the AE.** The deep model earns its complexity precisely where it matters.

2. **The AE matches SADAR on real anomalies.** ROC 0.667 (ours) vs 0.659 (his) — a dead heat on
   the prevalence-invariant lens, scored against the same 2020-normal. We did not "beat" him by
   any margin worth claiming, and we say so. The **PR gap (0.088 vs 0.299) is a prevalence +
   windowing artifact, not model quality**: his 12.1% prevalence comes from 60-step *sliding
   windows* (1,076 windows from ~104 flights); ours is 4.4% from *whole segments* (195). Chance
   PR-AUC is ~0.044 (ours) vs ~0.121 (his), so both land ~2× chance. The un-gameable fact is
   that both numbers are on real anomalies neither side designed.

**Pre-committed finding sentence (filled):**

> On a shared class of real anomalies (191 go-around + 4 emergency segments) neither model
> trained on, our LSTM-AE scored ROC-AUC **0.667** / PR-AUC **0.088** vs SADAR's VAE-LSTM
> **0.659** / **0.299**. We **matched** it on real anomalies (ROC, the prevalence-fair lens) —
> the comparison that, unlike synthetic AUROC, neither project could calibrate toward.

**Honest confounds (stated, not buried):** SADAR trains on 2017–2019 (we hold 2019 as val → he
has more training data); different features (ENU x/y vs our raw+dist); whole-segment vs 10-min
sliding windows; different go-around definitions. A true shared-`flight_id` intersection was not
possible — his published processed arrays carry no `flight_id`, so it would need re-running his
raw pipeline. This is "systems as each was actually built," not a controlled ablation.

---

## 2. The per-type story — the AE owns dynamics, not spatial (synthetic, test fold)

Per-type AUROC on the sealed test fold (each type injected alone, scored vs test-normal). **Lead
the writeup with this table, not the mean.** It is the D-010 / writeup-09 pre-commitment made
concrete: the AE earns its complexity on the *dynamic conformance* anomalies the deployed safety
nets (APW/MSAW) cannot catch, and is out-of-remit on spatial ones they already own.

| anomaly type | AE | kNN | IF | in the AE's remit (D-010)? |
|---|---|---|---|---|
| `sustained_loiter` | **0.971** | 0.986 | 0.952 | **yes** — APW/MSAW miss it |
| `final_approach_intercept` | **0.789** | 0.786 | 0.745 | **yes** |
| `speed_spike` | 0.580 | **0.815** | 0.587 | yes, but kNN's max-velocity summary wins |
| `altitude_high` | 0.558 | 0.594 | 0.556 | partial — MSAW-adjacent |
| `zone_violation` | 0.551 | 0.541 | 0.503 | **no** — APW owns it (out-of-remit; D-012) |

The AE is near-chance on `zone_violation` (0.551) — **by design**, not as a deficiency: small
zone/position violations are the deployed APW's job (D-008 Layer 3), and `zone` is a §6
pre-reframe drone-era category. Per **D-012** it is re-weighted out of the headline mix and kept
here only as an out-of-remit diagnostic.

---

## 3. The synthetic headline (reported, secondary)

D-012 re-weighted mix (4 dynamic types; zone out), sealed test fold, 50% inject rate:

| model | synthetic AUROC | 95% CI | PR-AUC |
|---|---|---|---|
| LSTM-AE (ships) | **0.731** | [0.714, 0.745] | 0.770 |
| kNN-on-summary | 0.786 | — | 0.827 |
| IsolationForest | 0.717 | — | 0.734 |

- **Primary target (AUROC > 0.85) is NOT met (0.731).** This is the honest Phase-1 verdict. The
  ceiling is architectural, not under-tuning — established by the Phase-6 loop-back (07-train.md
  §4b) and confirmed here on the held-out fold.
- **The kNN still wins on synthetic (0.786 > 0.731)**, as it did on val. The re-weight did not
  rescue the AE-vs-kNN synthetic gap (predicted in D-012). Synthetic does not decide the model —
  real anomalies do (§1).
- **AE operating point** (threshold 0.222, fixed on val, **no retune on test**): F2 0.520,
  **FPR 0.089 — the ≤15% guardrail holds**, recall 0.474.

CI: 1000× bootstrap over test windows.

---

## 4. External + qualitative validation (Layers 4 & 5)

**Layer 4 — real emergency, external (OpenSky #6 7700, Olive et al. 2020).** Of 832 global 7700
flights, exactly 7 have any track within 200 km of LEMD; Filter B keeps the one genuine close-in
LEMD operation — **BCS63A**, an A306 that declared emergency and **turned back to LEMD**. Scored
with the trained models it lands at the **98.8th percentile (AE)** / **100th (kNN)** of the
normal distribution — a real emergency the model never saw flags as highly anomalous. N=1 case
study (the other 6 are en-route transit, correctly excluded as the cross-airport confound); the
quantitative external-grounding role is D-011 (deferred). This is the doc's pre-reframed Layer 4.

**Layer 5 — qualitative top-20 normal-val by reconstruction error.** The 20 highest-error
"normal" flights are long full-profile segments; **7/20 show circling/holding signatures**
(>400° cumulative turn), several have oscillating vertrate (unstable/holding descent), and
**3/20 are AE-flagged but kNN-normal** — order-abnormal yet summary-normal, the exact cases the
AE's sequence model catches and a summary kNN cannot. None were already-tagged go-arounds. The
final per-flight visual classification (obvious / subtle / actually-normal) is the writeup
owner's ~2-hour pass; the diagnostic table is in `notebooks/13_phase7_eval.ipynb`.

---

## 5. Firewall discipline (how the burn stayed honest)

- **Model selection and threshold were fixed before the burn.** The AE threshold (0.222) is the
  val-chosen operating point; the representative choice (AE over kNN) was decided on the
  **held-aside cohort vs val-normal** (ROC 0.591 vs 0.551, PR 0.048 vs 0.043) — never the test
  fold. The test fold opened once, in `phase7_burn.py`, after both were locked.
- **`test_set.burned: false → true`** (manifest), `burned_at: 2026-06-02`, with the burn reason
  recorded. The 2020 fold was never scored, tuned on, or peeked at in Phases 3–6.
- **All three models reported, none dropped** (user-amended Layer-6 guardrail) — including the
  kNN that beats the AE on synthetic and the IF that is at chance on real.
- **D-012 bench change is a signed-off, pre-dated deviation**, not a post-hoc goalpost move
  (rationale architectural and pre-registered; zone preserved as a diagnostic; original mix
  preserved as `MIX_V1_WITH_ZONE`; Phase-6 notebooks pinned to it — codex-reviewed).

---

## 6. Verdict

- **Ship the LSTM-AE** (`model_track: dl` confirmed). Justification: it is the best model on the
  pre-registered real-anomaly criterion (beats kNN, matches SADAR), and its per-type profile is
  the D-010 complementary role made real (owns loiter/intercept; cedes zone to APW).
- **Primary metric target unmet on synthetic (0.731 < 0.85)** — stated plainly. The honest
  framing is the per-type table + the real-anomaly head-to-head, not a single mean.
- **kNN remains a strong, simpler alternative** — it wins on synthetic and is cheaper to deploy
  (the AE is fixed-size once trained; the kNN carries the train reference set). It is retained,
  frozen, and reported; the choice between them is a deployment-cost-vs-real-anomaly-quality call
  the writeup names explicitly.
- Phase 8 is course-demo only (not a production deploy).

## Exit-gate checklist

- [x] Test burned ONCE; `burned: true`, `burned_at`, `burn_reason` set; firewall intact through P6.
- [x] Final metrics on sealed fold: AUROC/F2/FPR/PR-AUC + bootstrap CI, vs IF baseline, all 3 models.
- [x] Real-anomaly head-to-head (Layer 6) run blind; representative chosen by real PR-AUC; confounds stated.
- [x] `track_confirmed` resolved (dl) on the real-anomaly criterion; honest target-miss recorded.
- [x] Layer 4 (BCS63A case study) + Layer 5 (top-20 qualitative) run and reported.
- [x] D-012 entry decision recorded + codex-reviewed; bench reproducibility preserved.
- [x] `07-eval.md` + `manifest.yml` eval gate `passed`; `current_phase: deploy`.
- [x] Tests green (`cd backend && uv run pytest`).
