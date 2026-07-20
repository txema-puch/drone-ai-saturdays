# Phase 4 — Exploratory Data Analysis

**Status:** passed for Phase 3 entry purposes (per-source extensions remain owed for Phase 7)
**Phase:** 4 (EDA)
**Lifecycle position:** Manifest's `current_phase: preprocess`. Phase 4 was worked in parallel with Phase 3 close-out because the EDA findings are the evidence base for Phase 3's preprocessing decisions.
**Updated:** 2026-05-30

## Scope and outcome

Phase 4 covers the structural EDA needed to inform Phase 3's preprocessing pipeline definition. The work spans two rounds of iteration documented in `research/trajectory-anomaly/notebooks/lifecycle/06_phase4_eda.ipynb` (single notebook, append-only with retrospective markers):

**Round 1 (2026-05-29) — original cycle-3 structural EDA.**

Six insights logged with figures under the project's original drone-detection framing. Decisions surfaced: T_min = 30 rows, 30-min segmentation gap validation, Filter C2 (landings-only) as the LEMD-operation gate. The 6-insight bar was met and the exit gate could have been declared passed at that point.

**Round 2 (2026-05-30) — reframe-driven re-derivation.**

The project's post-Phase-1 architectural critique (the archived architectural-critique draft listed in `docs/archive-manifest.yml`, referenced from `01-problem.md > Scope evolution` and D-006's interpretation note) reframed the model as **behavioral anomaly detection on cooperating aircraft** — not drone detection. Under that reframe, C2 was wrong for the opposite reason it had been tight: the training corpus should match the full legitimate operational variety the model will see at inference (landings, takeoffs, holds, missed approaches, go-arounds). C2 systematically excluded most of those.

Round 2 produced:

- **Phase 0 phase-derivation validation** (0a approach corridors, 0b takeoff vs onground, 0c takeoff-only diagnostic) — confirmed `approach` and validated `takeoff` derivations with proximity+altitude bounds.
- **Filter D** — three-criterion engagement gate replacing C2.
- **Insight 7** — motion-feature normality audit (7a histograms, 7b cross-feature scatter, 7c top-K outlier maps, 7d ground vs air split, 7e SW-corner investigation, 7f impossible-altitude inspection).
- **Multi-detector preprocessing pipeline design** for Phase 3 — physical-bounds rule + imputation + LSTM AE as separate detection channels.
- **Sanity-validation cohort proposal** for D-008 Layer 1 — concrete cohort definition and two-channel test.

This document captures the current-state summary. The full methodology trail lives in the notebook's concluding narrative section (cell 40).

## Structural EDA — full dataset, pre-split

Per the Phase 4 reference's two-EDA-kinds framing, this work is **structural EDA**: runs on the whole dataset before any train/val/test split is defined. No test-set firewall concern (the split is defined in Phase 6 entry). The activity is "look at distributions to understand the data and inform the split + preprocessing decisions."

## The seven insights — summary

Detailed narrative for each insight + figures live in the notebook. Headline findings:

| # | Insight | Finding | Phase 3 implication |
|---|---|---|---|
| 1 | Trajectory length distribution | P5=98, P50=175, P95=276 rows at 10s resolution | T_min = 30 rows (drops <0.1% of trajectories; ensures sufficient sequence context for LSTM compression) |
| 2 | Row-level phase composition | 20% of rows tagged `on_ground`; matches native ADS-B `onground` bit to 0.05% | Confirms the derived `flight_phase` field can drive a filter — provenance check passed |
| 3 | Filter D calibration | Filter D keeps 18,928 / 19,057 = 99.3% of Filter-B-passing trajectories. Per-criterion subset breakdown shows all three criteria pull distinct weight (complementary, not redundant) | Lock Filter D as the LEMD-operation gate |
| 4 | Arrival/departure endpoint structure | 31% start on_ground (departures), 26% end on_ground (arrivals), 0.8% round-trips | 30-min segmentation gap validated; potential Phase 5 feature: `is_arrival` flag |
| 5 | Filter D map: kept vs rejected | Kept trajectories show classic LEMD operational mix (approach cones, holds, departure cones); rejected trajectories show a clean north-south through-traffic pattern with no LEMD engagement | Filter D's visual sanity passes |
| 6 | Operational engagement signature | Whole-trajectory (min distance, min altitude) cleanly separates D-kept (low-low corner) from D-rejected (transit/overflight regions) | Empirical defense of Filter D's three-criterion design |
| 7 | Motion-feature normality audit | Velocity / vertrate / altitude have 0.04-0.08% kinematic-impossibility tails (sensor glitches, single-obs spikes per 7f). Heading-change tail (2.78%) is NORMAL flight maneuvering (vectoring, wind gusts, standard turns per 7d), NOT contamination. SW-corner cluster (7e) is the southern arrival corridor, not anomalous | Phase 3 multi-detector preprocessing rule (physical-bounds → imputation → AE); no filter on heading-change or SW corner |

## Filter D — specification

A trajectory passes Filter D if ANY observation satisfies ANY of these criteria:

| # | Criterion | Validated by |
|---|---|---|
| 1 | `flight_phase == "approach"` AND `dist_to_runway_m < 10000` | Phase 0a (clean runway-aligned approach cones) |
| 2 | `onground == True` AND `dist_to_runway_m < 5000` | Insight 2 (matches native ADS-B onground bit to 0.05%) |
| 3 | `flight_phase == "takeoff"` AND `dist_to_runway_m < 5000` AND `baroaltitude < 2000` | Phase 0c (97.9% real LEMD departures with delayed ADS-B; proximity+altitude bounds rule out non-LEMD class) |

The three criteria are **complementary, not redundant**: criterion 1 catches arrivals + holds + missed approaches + go-arounds; criterion 2 catches operations with on-ground touch at LEMD; criterion 3 catches departures whose ADS-B started post-rotation.

Filter D supersedes Filter C2 (landings-only formulation from the original drone-detection framing). C2's pass flag is still computed in the notebook for historical reference but no longer drives any Phase 3 decision.

## Multi-detector preprocessing pipeline (locked for Phase 3 / D-010)

Phase 4 derived an architectural decision about how to handle the gross outliers Insight 7 surfaced. The design:

```text
raw ADS-B trajectory
     ↓
Stage 1: physical-bounds rule
   - velocity > 400 m/s OR |vertrate| > 50 m/s OR baroaltitude > 16,000 m
     OR baroaltitude < -100 m OR velocity = 0 at altitude > 1000 m
   - if violated: LOG "kinematic impossibility alert" per observation
   - per-trajectory n_imputed count is the sloppy-spoof / glitch detection channel
     ↓
Stage 2: imputation
   - linear interpolation from valid neighbors for flagged observations
   - preserves trajectory length and uniform 10s time grid
   - same code at training and inference (Guardrail #9 offline/online parity)
     ↓
Stage 3: LSTM AE
   - trained and scored on imputed (clean-by-construction) trajectories
   - outputs reconstruction-error anomaly score
     ↓
Combined operator dashboard
   - Stage 1 alerts (rule-based, deterministic) AND Stage 3 score (model-based, continuous)
   - Different anomaly classes covered by appropriate detectors
```

**Architectural rationale:** different anomaly classes deserve different detectors. The original two-layer framing (which the project explicitly retired) assumed the AE catches everything. Kinematic impossibilities are cheaper, faster, and more reliably caught by a 5-line rule than by an LSTM AE. The AE focuses on its actual domain: behavioral anomalies on kinematically plausible trajectories. Stage 1's per-trajectory `n_imputed` count provides a parallel detection channel that catches sloppy ADS-B spoofs (sophisticated spoofs producing plausible kinematics are out of scope — they require multi-sensor crosscheck, which we don't have, per `09-the-architectural-critique.md`).

## Sanity-validation cohort proposal (for D-008 Layer 1)

D-008's Layer 1 (sanity) was previously underspecified. Insight 7 produces a concrete cohort definition:

**Cohort:** trajectories with `n_imputed > 0` (i.e., contained at least one observation that violated Stage 1 physical bounds before imputation).

**Estimated size:** 500-800 trajectories (rough union of velocity-affected ~69, vertrate-affected ~164, and altitude-affected 453 trajectories).

**Phase 7 two-channel test:**

| Channel | Test | Pass criterion |
|---|---|---|
| 1 — Stage 1 (rule-based) | Apply the physical-bounds rule to the raw cohort trajectories | Yes, by construction (defines cohort). Sanity-check that the rule code is correct. |
| 2 — Stage 3 (AE-based) | Apply preprocessing + AE to the cohort. Does the AE produce normal-range RE on the imputed versions? | Yes — imputation removes the spike; the AE shouldn't false-positive on the cleaned shape. If the AE produces high RE, imputation is leaving residual artifacts and the imputation rule needs refinement. |

**Both channels passing = the multi-detector system works as designed.** This tests the *system*, not the AE in isolation.

D-008 Layer 1 is updated separately (`D-008-output-validation-layers.md`) with this concrete cohort definition.

## Decisions surfaced for Phase 3

Locked for `03-preprocess.md` and D-010:

| Decision | Choice | Evidence |
|---|---|---|
| LEMD-operation gate | **Filter D** (three-criterion engagement; replaces C2) | Phase 0 (a/b/c validation) + Insights 3, 5, 6 |
| Trajectory length minimum | T_min = 30 rows (5 min @ 10s) | Insight 1 |
| Segmentation gap threshold | 30 min (already shipped at cycle-3 ingestion; validated by 0.8% round-trip rate) | Insight 4 |
| Distance-jump teleport guard | Split when consecutive observations are > 5 km apart | Design doc Phase 1 (additional safety net) |
| Sequence length T (LSTM input) | Pad/truncate to ~P90 (~250 steps) OR variable-length with packed sequences | Insight 1 |
| Multi-detector preprocessing | Stage 1 physical-bounds + Stage 2 imputation + Stage 3 AE; per-trajectory `n_imputed` count as separate alert channel | Insight 7 + multi-detector architectural decision |
| Heading-change handling | No filter (normal flight maneuvering per 7d) | Insight 7d |
| SW-corner handling | No filter (normal southern arrival corridor per 7e) | Insight 7e |

**Retired decision:** Filter C2 (landings-only gate from the original drone-detection framing). Superseded by Filter D under the behavioral-anomaly reframe.

## Exit gate status

Per Phase 4 reference's exit gate checklist:

- [x] At least 5 substantive insights logged in `04-eda.md`, each with a saved figure (7 logged)
- [x] Distribution checked for every input feature relevant to Phase 3 decisions (trajectory length, phase composition, motion features)
- [x] Outliers from Phase 3 / motion features examined and explained (Insight 7)
- [x] Class balance / target distribution — N/A for unsupervised anomaly detection
- [x] Bivariate target relationships — N/A; cross-feature relationships explored via Insight 7b
- [x] Insights confirm framing — Filter D and multi-detector design match the post-Phase-1 reframe
- [ ] D-008 Layer 4 (OpenSky Dataset #6) inspection — **deferred** (does not gate Phase 3; feeds Phase 7)
- [ ] D-009 probe pre-work — **deferred** (depends on Phase 6 trained model)
- [ ] Synthetic anomaly plausibility check per `07-eval-prep.md` — **deferred** (feeds Phase 7)

**Phase 4 is closed for Phase 3 entry purposes.** The remaining three deferred items feed Phase 7, not Phase 3, so Phase 3 design can proceed without them landing first.

## What this notebook informs downstream

- **Phase 3 (`03-preprocess.md`, D-010):** Filter D, T_min, multi-detector pipeline (Stage 1 + Stage 2 + Stage 3 design), heading-change non-filter, SW-corner non-filter.
- **Phase 5 (features):** potential `is_arrival` binary flag (per Insight 4).
- **Phase 6 (train):** training corpus is the imputed cleaned trajectories from cycle 3 that pass Filter D.
- **Phase 7 (eval):**
  - D-008 Layer 1: two-channel sanity test on the `n_imputed > 0` cohort.
  - D-008 Layer 4: external validation against OpenSky Dataset #6 (separate Phase 4 deliverable, deferred).
  - D-009: covariate-shift probe via cycles 1+2 (separate notebook when run).

## References to the notebook

The full methodology trail (questions asked, hypotheses tested, decisions made, retrospective on C2 retirement, multi-detector architecture derivation, sanity-cohort design) lives in `research/trajectory-anomaly/notebooks/lifecycle/06_phase4_eda.ipynb`'s concluding narrative section (cell 40).

Each insight's code + figures are in their respective cells:

- Cell 8 — Insight 1 (trajectory length)
- Cell 10 — Insight 2 (phase composition)
- Cells 11-16 — Phase 0 phase-derivation validation
- Cell 17 — retrospective on C2 retirement
- Cells 18-19 — Insight 3 (Filter D calibration)
- Cells 20-21 — Insight 4 (arrival/departure structure)
- Cells 22-23 — Insight 5 (Filter D map)
- Cells 24-25 — Insight 6 (engagement signature)
- Cells 26-35 — Insight 7 (motion-feature normality audit) including 7a-f
- Cell 36 — sanity-cohort proposal (multi-detector architecture)
- Cell 37 — final verdict with locked numbers
- Cell 38 — decisions surfaced for Phase 3
- Cell 40 — conclusions narrative

## Reproducibility

- Notebook: `research/trajectory-anomaly/notebooks/lifecycle/06_phase4_eda.ipynb`. "Run All" in Jupyter or VSCode to regenerate all figures.
- Cache parquet: `data/raw/opensky_states/_cycle3_per_traj_endpoint_audit.parquet` (gitignored; re-derived on notebook run).
- Data dependencies: 18 cycle-3 parquets in `data/raw/opensky_states/lemd_*.parquet` (sha256 Merkle: `98e38ba5...662e4` per `manifest.yml > gates.data.dataset_hash`).
- Figures persisted to: `docs/research/trajectory-anomaly/figures/04-eda/` (7 figures for Insights 1-7 plus Phase 0 validation figures).
