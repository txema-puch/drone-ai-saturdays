# D-010 — Filter D as LEMD-operation gate; multi-detector preprocessing pipeline for Phase 3

**Status:** decided
**Date:** 2026-05-30
**Phase:** preprocess (Phase 3)
**Supersedes:** the C2-based filter decision implied by `04-eda.md` Round 1 (the original 6-insight EDA); never formally ADR'd, retired before reaching Phase 3
**Affects:** Phase 3 (preprocess — defines `pipeline_definition`), Phase 6 (training corpus), Phase 7 (D-008 Layer 1 sanity cohort, D-008 Layer 4 inference-time preprocessing), the writeup

## Context

Phase 4 EDA (`backend/docs/ml/04-eda.md`, `notebooks/06_phase4_eda.ipynb`) produced two intertwined Phase 3 decisions that together define the preprocessing pipeline: **which trajectories enter training** (the LEMD-operation gate) and **how to handle gross sensor outliers within those trajectories** (the kinematic-impossibility handling rule).

Both decisions evolved during Phase 4 work:

- The original cycle-3 EDA (Round 1) introduced **Filter C2** as the LEMD-operation gate under the project's original drone-detection framing. C2 was tuned for landings-only (first/last 5 obs at low altitude near a runway).
- The project's post-Phase-1 architectural critique (`backend/docs/writeup/09-the-architectural-critique.md`, formal references in `01-problem.md > Scope evolution` and `D-006 > Scope reframe (post-Phase 1)`) reframed the model as **behavioral anomaly detection on cooperating aircraft**. Under that framing, C2 was wrong: it excluded legitimate operational variety (holds, missed approaches, go-arounds) that the model will see at inference.
- Round 2 of Phase 4 derived **Filter D** (three-criterion engagement gate) from the corrected operational intent, validated each criterion via Phase 0a/b/c, replaced Insights 3/5/6 with Filter D versions, and added Insight 7 (motion-feature normality audit).
- Insight 7's findings surfaced a separate architectural question: how to handle gross kinematic-impossibility observations (Mach 5 velocity, 38 km altitude, 32k ft/min vertrate). A reviewer caught that naive drop-at-training risks blinding the system to spoofed ADS-B signals. The resolution: **multi-detector preprocessing** where Stage 1 (physical-bounds rule) is a separate detection channel from Stage 3 (the AE), with Stage 2 (imputation) bridging them for offline/online parity.

This ADR locks both decisions and the relationships between them.

## Decision

### Part 1 — Filter D as the LEMD-operation gate

A trajectory passes Filter D if ANY observation satisfies ANY of these criteria:

| # | Criterion | Validated by |
|---|---|---|
| 1 | `flight_phase == "approach"` AND `dist_to_runway_m < 10000` | Phase 0a (clean runway-aligned approach cones in geographic plot) |
| 2 | `onground == True` AND `dist_to_runway_m < 5000` | Insight 2 (matches native ADS-B `onground` bit to 0.05%) |
| 3 | `flight_phase == "takeoff"` AND `dist_to_runway_m < 5000` AND `baroaltitude < 2000` | Phase 0c (97.9% real LEMD departures with delayed ADS-B; proximity+altitude bounds rule out non-LEMD population) |

The three criteria are **complementary, not redundant**: criterion 1 catches arrivals + holds + missed approaches + go-arounds; criterion 2 catches operations with on-ground touch at LEMD; criterion 3 catches departures whose ADS-B started post-rotation.

Filter D keeps **18,928 / 19,057 = 99.3%** of Filter-B-passing cycle-3 trajectories. The 0.7% rejected (129 trajectories) are visually verified as transit/overflight traffic with no LEMD engagement (Insight 5 map).

### Part 2 — Multi-detector preprocessing pipeline

Phase 3 implements three stages, applied identically at training and inference:

```text
raw ADS-B trajectory
     ↓
Stage 1: physical-bounds rule
   Flag observations violating any of:
   - velocity > 400 m/s
   - |vertrate| > 50 m/s
   - baroaltitude > 16,000 m
   - baroaltitude < -100 m
   - velocity == 0 m/s AND baroaltitude > 1,000 m  (missing-data placeholder)
   Per-trajectory `n_imputed` count is persisted as the "kinematic impossibility alert" channel.
     ↓
Stage 2: imputation
   Linear interpolation from valid neighbors for flagged observations.
   Preserves trajectory length and uniform 10s time grid.
   Same code at training and inference (Guardrail #9 offline/online parity).
     ↓
Stage 3: LSTM AE
   Trained and scored on the imputed (clean-by-construction) trajectories.
   Outputs reconstruction-error anomaly score.
     ↓
Combined operator view
   Stage 1 alerts (rule-based, deterministic) AND Stage 3 score (model-based, continuous).
   Different anomaly classes covered by appropriate detectors.
```

### Part 3 — No filter on heading-change or SW-corner observations

Insight 7d confirmed the 2.78% "suspicious" heading-change observations are **normal flight maneuvering** (vectoring, wind effects, standard-rate turns) — not contamination. Insight 7e confirmed the SW-corner cluster is the **southern arrival corridor**, not anomalous. Both stay in the training distribution unfiltered.

The originally-proposed "suspicious" threshold of 15°/10s was 50% of the IFR-standard rate-one turn (30°/10s) and was retired.

## Why multi-detector architecture, not "drop and forget"

The naive alternative — drop bad observations at training, never see them at inference — has two failure modes:

1. **Loss of glitch-detection capability.** A sloppy ADS-B spoofer producing impossible kinematics would be silently corrected by preprocessing; the AE never sees them; no alert fires. The system blinds itself to that anomaly class.
2. **Train/inference asymmetry.** If we drop at training but forget to drop at inference, the AE sees raw glitches and produces large RE spikes → false-positive alerts on legitimate trajectories whose sensors briefly glitched. Guardrail #9 violation.

The multi-detector design addresses both:

- **Stage 1 logs the flag and persists `n_imputed` per trajectory**, so glitch detection becomes a parallel channel rather than a discarded signal.
- **Stages 1 and 2 are applied identically at training and inference** (per the Guardrail #9 offline/online parity rule), so the AE always sees imputed (clean) trajectories. False-positive risk on glitched inference data is eliminated.

The architectural principle, also captured in the post-Phase-1 reframe: **different anomaly classes deserve different detectors.** Kinematic impossibility is caught better by a 5-line physical-bounds rule than by an LSTM AE — it's cheaper, faster, deterministic, and interpretable. The AE's complexity is justified only for behavioral anomalies (its actual domain, per D-006).

## Filter D criteria rationale (per-criterion)

### Criterion 1 — approach < 10 km

The phase-derivation validation in Phase 0a showed `flight_phase == "approach"` observations cluster tightly on LEMD's runway approach corridors (visible in the saved figure `00-phase-validation-approach.png`). The 10 km radius bound rules out approaches to neighboring fields (LECU at 13 km, LEGT at 12 km) while admitting LEMD's TMA approach geometry.

Criterion 1 catches:

- Standard arrivals (final approach phase observations within 10 km)
- Holds with eventual approach (any approach-phase observation during sequencing)
- Missed approaches (approach phase observed before go-around)
- ADS-B-clipped real landings whose approach phase was captured before the coverage drop

### Criterion 2 — onground == True within 5 km

Insight 2 confirmed that the derived `flight_phase == "on_ground"` matches the native ADS-B `onground` bit to within 0.05%. Using the native `onground` flag directly is cleaner; the 5 km radius bound is very tight because being on the ground at LEMD without operating there is essentially impossible.

Criterion 2 catches:

- Departures whose ADS-B started in taxi (gate-to-runway taxi observations)
- Arrivals whose touchdown was observed (touchdown-and-rollout observations)
- Taxi-only or aborted-takeoff trajectories that touched ground at LEMD

### Criterion 3 — takeoff < 5 km AND altitude < 2 km

Phase 0c discovered that 9% of the "takeoff" / "onground in first 5 obs" overlap masks a third population: trajectories tagged `flight_phase == "takeoff"` but with no `onground == True` in the first 5 observations. Diagnostic 7c showed 97.9% of these are **real LEMD departures whose ADS-B started after liftoff** (first obs at altitude 411–914 m, distance 41–3,286 m from runway). The proximity+altitude bounds rule out the 2.1% non-LEMD class (climb-throughs from elsewhere, phase-derivation false positives).

Criterion 3 catches:

- LEMD departures whose ADS-B activated after rotation (some transponders only activate after Weight-on-Wheels goes false)
- LEMD departures whose ground-side ADS-B coverage was poor

Without criterion 3, these ~3,300 trajectories would be excluded — a meaningful share of the legitimate cooperating-aircraft variety the AE should learn.

## Alternatives considered

### Filter D alternatives (LEMD-operation gate)

| Alternative | Why rejected |
|---|---|
| **Filter C2 (landings-only, the original cycle-3 EDA decision)** | Optimizes for landings purity. Under the post-Phase-1 reframe, the model needs to learn the full legitimate cooperating-aircraft operational variety (holds, missed approaches, go-arounds) — not just landings. C2 excludes most of this variety, producing systematic false-positive risk on routine non-landing operations. |
| **Filter B alone (just the ingestion bbox)** | Filter B (`min_dist < 10 km AND min_alt < 3 km` per trajectory) is too permissive; it admits trajectories that briefly clipped into the proximity-altitude cube during cruise. Filter D's three criteria add the operational-engagement signal that B lacks. |
| **Phase-only filter (Option B: phase ∈ {approach, takeoff, on_ground} within 15 km)** | Phase 0c demonstrated that `takeoff` is reliable only when bounded by proximity + altitude (else it admits 2.1% non-LEMD climb-throughs and false positives). The naive phase-only formulation would have leaked those into training. |
| **Sustained-engagement (Option A: ≥3 min within 15 km at altitude < 4.5 km)** | A reviewer's check showed standard LEMD departures spend only 60-90 seconds in the engagement zone before climbing out. A 3-min threshold would have excluded most legitimate departures. Dropping K_min to 90s would have admitted brief proximity dips from neighboring traffic. The endpoint-aware multi-criterion design avoids this trade-off entirely. |

### Multi-detector preprocessing alternatives

| Alternative | Why rejected |
|---|---|
| **Drop bad observations at training; do nothing at inference** | Train/inference mismatch (Guardrail #9 violation). Glitches at inference produce false-positive AE spikes. |
| **Drop bad observations at both training and inference, no logging** | Loses the sloppy-spoof detection signal. Reviewer-flagged: the AE becomes blind to one anomaly class entirely. |
| **Filter trajectories entirely (drop the whole flight)** | The diagnostic in Insight 7f showed most affected trajectories have <1% bad observations (single-obs spikes). Dropping the whole trajectory loses 5-30 minutes of legitimate flight data per affected flight. |
| **Train the AE to ignore bad observations via masking** | Requires modifying the LSTM AE architecture (masked attention or similar). Heavyweight for the course-deliverable scope and doesn't add value over imputation: the AE sees a clean signal either way. |
| **Use the bad observations themselves as a training-time anomaly class (semi-supervised)** | Defeats the unsupervised framing the project committed to in Phase 1 (D-001). Also: bad observations are a different anomaly class than the model is trying to detect (sensor glitch ≠ behavioral anomaly). |

## Consequences

### Gains

- **Filter D's training corpus matches the inference distribution.** The AE learns the full legitimate operational variety at LEMD; routine non-landing operations don't trigger false positives in production.
- **Multi-detector design covers two anomaly classes with appropriate detectors.** Stage 1 (rule-based) catches kinematic impossibility; Stage 3 (model-based) catches behavioral anomaly. Different cost-profile + different latency + different interpretability properties.
- **Sloppy ADS-B spoof is now detected** as a side effect of Stage 1 logging `n_imputed`. This was lost in the original "drop and forget" framing.
- **Offline/online parity is preserved by design.** Stages 1 + 2 are the same code at training and inference.
- **D-008 Layer 1 sanity test becomes concrete and meaningful.** The `n_imputed > 0` cohort is the test; the two-channel pass criterion validates the system, not the AE in isolation.

### Costs

- **~1 day of Phase 3 implementation work** for the three-stage preprocessing pipeline (Filter D filter + physical-bounds rule + imputation + n_imputed tracking).
- **Per-trajectory metadata grows by 1 integer column (`n_imputed`).** Negligible storage cost.
- **The sanity cohort (500–800 trajectories) is excluded from training,** reducing the training-set size by ~3-4%. Negligible impact on AE training quality given the cohort is removed before training reaches it.

### Risks acknowledged

- **Imputation may introduce artifacts at the spike locations.** Mitigation: Phase 7 D-008 Layer 1 Channel 2 explicitly tests for this — if the AE produces high RE on imputed cohort trajectories, the imputation rule needs refinement (e.g., wider neighbor window, or different interpolation method like cubic spline).
- **Filter D admits 0.7% of trajectories Filter B included that are operationally borderline** (transit traffic that briefly engaged). Mitigation: visual sanity check in Insight 5 confirms the rejected set is clean transit traffic and the kept set is operationally engaged. If Phase 6 reveals systematic noise from the borderline cases, criterion thresholds can be tightened.
- **Sophisticated ADS-B spoofing (kinematically plausible) is undetectable by this design.** Documented as out-of-scope in `01-problem.md > Out of scope` and the Medium piece; requires multi-sensor crosscheck which we don't have access to.

## Implementation links

- **Phase 3 entry artifact** (to be written): `backend/docs/ml/03-preprocess.md` will codify the three-stage pipeline as `pipeline_definition`.
- **Code-level implementation** (Phase 3 deliverable): `backend/core/preprocessing.py` (or similar) implements:
  - `filter_d(per_traj: pd.DataFrame) -> pd.DataFrame` — applies the three criteria, returns trajectories that pass
  - `flag_kinematic_impossibility(df: pd.DataFrame) -> pd.DataFrame` — Stage 1: adds per-row flag column
  - `impute_flagged_observations(df: pd.DataFrame) -> pd.DataFrame` — Stage 2: linear interpolation
  - `compute_n_imputed(df: pd.DataFrame) -> pd.DataFrame` — per-trajectory aggregate for the alert channel
- **Phase 4 evidence base:** `backend/docs/ml/04-eda.md` (current state) and `notebooks/06_phase4_eda.ipynb` (full methodology trail including the C2-to-D evolution and the multi-detector architecture derivation).
- **Phase 7 sanity cohort consumer:** D-008 Layer 1 (`backend/docs/ml/decisions/D-008-output-validation-layers.md > Layer 1 — sanity cohort, in detail`).
- **Manifest cross-references** (to be updated when Phase 3 closes):
  - `manifest.yml > gates.preprocess.artifact = backend/docs/ml/03-preprocess.md`
  - `manifest.yml > gates.preprocess.pipeline_definition = "filter_d + stage1_physical_bounds + stage2_imputation + ae_input"`
  - `manifest.yml > decisions[]` appends D-010 reference

## Related decisions

- [D-001 — Anomaly detection framing](D-001-anomaly-vs-classification.md) — defines the unsupervised AE setup that requires this preprocessing design
- [D-005 — Metric stack](D-005-metric-stack.md) — defines what "good" looks like in Phase 7; Filter D's choice affects val/test distributions
- [D-006 — LSTM AE primary, IF baseline](D-006-architecture-and-baseline.md) — defines what's downstream of this preprocessing pipeline; D-006's interpretation note documents the same post-Phase-1 reframe that drove D-010
- [D-007 — OpenSky scientific dataset](D-007-opensky-scientific-data-source-pivot.md) — supplies the cycle-3 data this preprocessing operates on; introduced Filter B (the ingestion bbox) that Filter D supersedes operationally
- [D-008 — Multi-layer output validation, including real-emergency external set](D-008-output-validation-layers.md) — D-010's `n_imputed > 0` cohort is the concrete instantiation of D-008 Layer 1's sanity test
- [D-009 — Day-of-week covariate-shift probe via Supabase cycles 1+2](D-009-day-of-week-covariate-shift-probe.md) — defines the cycles 1+2 inference-side preprocessing protocol that uses this same Stage 1 + Stage 2 pipeline applied at inference

## Open questions

1. **Imputation method refinement.** Linear interpolation is the starting point. If Phase 7 Layer 1 Channel 2 fails (AE produces high RE on imputed cohort trajectories), consider:
   - Cubic spline interpolation (smoother)
   - Median-filter smoothing across a wider neighbor window
   - Kalman-filter-style state estimation
   Decide based on the actual Layer 1 Channel 2 result; do not pre-commit.

2. **`n_imputed` operator alert threshold.** Below what `n_imputed` value should the alert NOT fire? A single-obs spike is unambiguous noise. A trajectory with 30 imputed observations is suspect. Decide based on operational use case in Phase 8 design (course demo scope: no threshold, just display the count).

3. **Filter D borderline trajectories.** The 0.7% of Filter B trajectories that Filter D rejects could in principle be inspected one-by-one. Worth doing only if Phase 6 surfaces systematic noise traceable to Filter D's loose tail. Not pre-committed.

4. **Should `n_imputed` be a feature for the LSTM AE?** Adding it as a per-trajectory side feature would let the AE condition its reconstruction on "this trajectory had N imputations." Likely small effect; defer to Phase 5 feature engineering.
