# Phase 1: Problem Definition

**Status:** passed
**Started:** 2026-04-11 (via `/office-hours`, generating the design doc)
**Closed:** 2026-05-07 (consolidated into ml-lifecycle format)

## Goal

Define what we are building, why, for whom, and how we will know it works — with enough rationale that the writeup, the Medium piece, and a teammate joining in Week 3 can all reconstruct the reasoning.

This phase does not produce code or data. It produces a written agreement on:
- The business objective and the user-facing decision the model affects
- The ML framing and why this framing won over alternatives
- The success metric and a target value
- The cost asymmetry of false positives vs false negatives
- The architecture choice (tentative; locked in Phase 6)
- What is explicitly out of scope

## Inputs

- `backend/docs/architecture/design-trajectory-anomaly-detection.md` — APPROVED design doc (2026-04-11)
- `backend/docs/decisions/README.md` — D-001 to D-004 (use case, modality, dataset, scope)
- `/ml-lifecycle` Phase 1 reference + guardrails (testing-firewall, baseline-required, etc.)

## Outputs

- `backend/docs/ml/manifest.yml` — machine-readable state
- This document — narrative rationale
- `backend/docs/ml/decisions/D-001-anomaly-vs-classification.md` — framing ADR
- `backend/docs/ml/decisions/D-005-metric-stack.md` — metric stack ADR
- `backend/docs/ml/decisions/D-006-architecture-and-baseline.md` — architecture ADR

---

## Business objective

Detect unauthorized or anomalous drone activity in the airspace around Madrid-Barajas (LEMD). The realistic deployment context is a counter-drone advisory layer for AENA / AESA — not a replacement for ATC, but an additional signal an operator can act on (visual confirmation, radar verification, response coordination).

In a course-deliverable context, the user is the audience of the demo and the readers of the writeup. We are building a working anomaly scorer + animated demo + Medium-grade writeup, not a production service.

The decision the model affects: *given an unidentified track entering LEMD airspace, should an operator investigate it?* A positive prediction (anomaly) triggers investigation. A negative prediction lets the track pass without alert.

### Scope evolution (post-Phase 1)

The original Phase 1 framing of "unauthorized drone activity" was scoped down mid-project once two structural facts became unavoidable:

1. **Consumer drones do not broadcast ADS-B.** The training corpus is manned cooperating aircraft only; the model has structurally never seen a drone and cannot detect what it cannot see.
2. **Aviation's "Layer 1" is far cleaner than the cyber/fraud two-layer playbook assumes.** The regulatory ecosystem — ICAO24 registry, filed flight plans, ATC controllers actively watching the radarscope, plus Eurocontrol's deployed safety-net stack (STCA, APW, MSAW, APM) — leaves "Layer 2" with a much narrower niche than the original framing implied.

The operational restatement is: **a behavioral anomaly detector for cooperating aircraft at LEMD, designed to catch sequence-shaped behavioral deviations (hovering, speed spikes, late-trajectory deviation) that the deployed rule-based safety nets do not.** Per-anomaly-type expectation: AE loses to safety-net analogs on zone violation (APW) and altitude violation (MSAW); AE wins on hovering, speed spike, and late-trajectory deviation.

This reframe is the thesis of the Medium piece — see `backend/docs/writeup/09-the-architectural-critique.md`. It does not invalidate the metric stack, baseline, or architecture choices below; those remain operational. It does narrow what the model can honestly claim to detect, which the writeup carries explicitly. D-006 carries a parallel interpretation note.

## ML framing

**Task type:** `anomaly_detection`

**Input:** A trajectory — a sequence of state vectors over time. Each state vector is `(lat, lon, baroaltitude, velocity, heading, vertrate, ...)` with `time` as the sequence index. After segmentation and resampling, this becomes a fixed-frequency `(T, D)` tensor per trajectory (T = number of timesteps, D = number of features).

**Output:** A continuous **anomaly score** in [0, ∞), interpreted as how unusual the trajectory looks relative to learned normal-flight patterns near LEMD. Thresholding the score produces a binary alert.

### Why this framing won

The original framing (Scenario 8 from the course brief) was *three-class intent classification*: `cooperative / negligent / hostile`. We rejected it for three reasons:

1. **No labeled data exists for "hostile" or "negligent" drones**, and constructing such a dataset is both prohibitively expensive (per-example labeling cost) and ethically dubious (there is no legitimate corpus of hostile drone trajectories).
2. **Intent is unobservable from trajectory alone.** A drone hovering over a runway could be a wedding photographer who got lost or a deliberate attempt at airport disruption. The signal is the same; the intent is not in the data.
3. **Three-class framing requires ground truth that isn't available now and won't be in 5 weeks.**

Anomaly detection sidesteps all of this. We don't need labeled hostile data — we only need labeled normal data, which is abundant and free via OpenSky. The model learns what authorized flight near LEMD looks like; anything that deviates statistically is flagged. No intent classification, no synthetic hostile labels, no unobservable target.

This is the most fundamental decision in the project. See [D-001](decisions/D-001-anomaly-vs-classification.md).

---

## Model selection (tentative)

The architecture choice is *tentative* in Phase 1 and *confirmed* in Phase 6 once we see whether the chosen architecture meaningfully beats the baseline. The reasoning chain that gets us to the choice:

### Step 1 — No labels for anomaly → unsupervised / self-supervised

Without labeled anomalies, supervised classification is off the table. We need methods that learn from normal data alone:
- **Density estimation** — model `p(trajectory)` and flag low-density inputs
- **Reconstruction-based** — train a model to reproduce normal data; flag inputs it can't reproduce

We pick **reconstruction-based** because the score (reconstruction error, MSE) is a continuous, comparable scalar and the architecture (encoder-decoder) is well-trodden pedagogically.

### Step 2 — Trajectory has temporal structure → sequence model

Two trajectories with the same set of points in different orders can be one normal and one anomalous (e.g., a smooth descent vs a chaotic altitude oscillation). Models that take fixed-size feature vectors (logistic regression, random forest, vanilla autoencoder) can only operate on aggregated features and lose this temporal pattern. Models that take sequences (RNN, LSTM, GRU, Transformer, 1D CNN) preserve it.

The primary model is sequence-aware. The baseline deliberately is not — that contrast lets us measure how much value time order adds.

### Step 3 — LSTM Autoencoder

For the sequence model, we choose **LSTM** over GRU / Transformer / 1D CNN on three grounds:
- **Pedagogical clarity** — canonical architecture for sequence modeling, lots of teaching material; appropriate for a course project
- **Stability** — LSTM training is robust on small datasets; Transformers can be finicky and consume Week 3 in debugging
- **Hidden state as natural bottleneck** — the encoder's final hidden vector is a fixed-size summary the decoder reconstructs from

Architecture (from design doc):

```
Encoder:  Input (T, D)  →  LSTM(hidden=64)  →  LSTM(hidden=64)  →  hidden state (64,)
Decoder:  hidden state  →  LSTM(hidden=64)  →  LSTM(hidden=64)  →  Output (T, D)
Loss:     MSE(Output, Input), averaged over T and D
```

### Threshold by construction

After training, we score the validation set of normal trajectories and pick the **95th percentile** of the reconstruction-error distribution as the operating threshold. By construction, ~5% of normal trajectories are flagged at this threshold (FPR ≈ 5%), well within the 15% guardrail. The threshold is operator-tunable in the demo.

### Baseline: Isolation Forest

Per Guardrail #10, we never judge the primary model in isolation. Isolation Forest earns the baseline slot:
- Tree-based — no scaling, no LR, runs in seconds
- Operates on **per-trajectory aggregate features** (mean, std, min, max) — deliberately no time order
- Same self-supervised setting (train on normal, score everything)

The honest contrast: if the LSTM Autoencoder doesn't meaningfully beat IF, time order isn't pulling its weight on this problem and we ship the IF model. That's a publishable finding either way.

See [D-006](decisions/D-006-architecture-and-baseline.md) for the full alternatives table.

### Alternatives considered for the model family

D-006 enumerates the alternatives we considered *within* the sequence-reconstruction family (Transformer, GRU, VAE, GAN, normalizing flow, etc.). A separate question — and the one a reviewer is most likely to ask — is why we chose a sequence-reconstruction approach **at all** when simpler model families exist. The short answer is below; the longer answer is that each alternative is the right tool under a different set of constraints, and none of those constraint sets matches ours.

| Alternative family | Representative methods | Why it doesn't fit our setup | When it WOULD be the right answer |
|---|---|---|---|
| **Single-variable rules** | `flag IF altitude < 200m AND dist_to_LEMD < 5km` | Closed-set: catches anomalies we *imagine*, misses novel patterns. Brittle thresholds (why 200m and not 250m?). Loses the open-set property that motivated anomaly detection over classification. | Threat model is well-defined and small (e.g., "only worry about runway incursion below altitude X"). |
| **Supervised gradient boosting** | XGBoost, CatBoost, LightGBM | Need labeled `(trajectory, is_anomaly)` pairs we don't have. With synthetic anomalies for labels, we hit the imagination-leakage problem (model learns our synthetic anomaly distribution, fails on real anomalies). | We obtain real labeled drone-incident data — then this becomes the right tool on aggregate features. |
| **Clustering / density-based outlier detection** | DBSCAN, HDBSCAN, GMM, k-means + distance-to-centroid | Same aggregate-feature limitation as Isolation Forest. No clear advantage over IF for this data shape. Curse of dimensionality on `(T, D)` tensors hurts distance metrics. | Mixed-density data with clearly separated clusters in feature space — not our case. |
| **Statistical / Markov sequence models** | HMM, Kalman filter, conditional `p(state_t+1 \| state_t)` | Captures *some* sequence structure with less machinery than an LSTM. HMMs need state discretization (fiddly bucketing of altitude/lat/lon). Markov assumption misses long-range dependencies (e.g., 10-minute circling pattern). | Linear dynamics with short-range temporal dependencies. Partially fits but LSTM AE strictly subsumes. |
| **One-class SVM** | `OneClassSVM(kernel='rbf')` | Doesn't scale beyond ~10k samples on commodity hardware. Doesn't naturally handle variable-length sequences. | Small datasets with well-defined kernel structure. |
| **Sequence-aware reconstruction (our choice)** | LSTM Autoencoder | Sequence structure preserved, no labels needed, interpretable per-feature/per-timestep, fits Colab T4 budget. Complexity must still be earned via Phase 6 baseline comparison. | When trajectory order carries the signal — which is the hypothesis we're testing. |

The frame: **none of the simpler families is "wrong" in absolute terms** — they are right under different constraints. Ours are: no labels + open-set threat + sequence structure may matter + 5-week timeline + interpretability requirement. The LSTM AE matches all four. Whether the LSTM AE *meaningfully outperforms* the simpler IF baseline is the Phase 6 question — see [Decision rule for Phase 6](#decision-rule-for-phase-6-when-do-we-ship-lstm-ae-vs-isolation-forest) below.

#### Why "just one variable" isn't enough

The strongest version of the simplicity challenge: *can a single-variable threshold do the job?* Honest answer:

- **For some anomaly types: yes.** A drone hovering at 100m near LEMD is detectable from altitude alone.
- **For others: no.** A drone flying at airliner altitudes that mimics a normal approach has no single-feature signature. The anomaly is in the *combination* of features (lat/lon trajectory shape doesn't match an approach corridor, even if altitude is fine) and in their *temporal evolution* (the sequence makes no sense as a cohesive flight).

A single-variable approach catches the easy anomalies and misses the rest. It also can't catch what we don't think to threshold against. That's the open-set property again — and the AE preserves it precisely because it learns "what normal looks like" rather than "what bad looks like."

#### Why we did not pick supervised methods even though they're often best on tabular data

XGBoost / CatBoost / LightGBM are state-of-the-art on labeled tabular tasks. The reason they don't apply here is straightforward but worth being explicit about: **they are supervised methods.** They learn `f(X) → y` from labeled `(X, y)` pairs. Our project has zero labeled anomalies and no realistic path to obtaining them in 5 weeks. Without `y`, supervised methods have nothing to learn against.

The tempting workaround is to *generate* labels via synthetic anomaly injection, then train a supervised classifier. We discussed this trap explicitly: train and eval would both sample from the *same* synthetic anomaly distribution, so high AUROC measures fit-to-our-imagination rather than generalization to real anomalies. The unsupervised AE side-steps this because it never sees any anomaly during training — synthetic anomalies in eval are out-of-distribution to the model by construction.

If real labeled drone-incident data ever arrives (e.g., AENA / EASA / AESA share historical incursion records), reframing as a supervised problem with XGBoost on aggregate features is the natural next step. **Without labels, it's not a viable path.**

---

## Decision rule for Phase 6 (when do we ship LSTM AE vs Isolation Forest?)

The LSTM Autoencoder is *tentatively* primary in Phase 1. The complexity is conditional on it earning a measurable win over the Isolation Forest baseline. To prevent the model choice from being decided by belief or sunk cost, we publish the decision rule here — *before* the Phase 6 results land — so the criteria can't be retconned.

### The rule

After Phase 6 training and validation, with both models evaluated on the same val set:

| LSTM AE val AUROC | IF val AUROC | Margin (AE − IF) | What we ship | Headline finding for the writeup |
|---|---|---|---|---|
| Any | Any | **≥ +0.03** | **LSTM AE** | "Sequence structure adds measurable value at LEMD." |
| Any | Any | **< +0.03** | **Isolation Forest** | "Sequence structure does not add measurable value over aggregate features for trajectory anomaly detection at LEMD." |
| < 0.70 | < 0.70 | n/a | Neither — project pivots or fails honestly | "Neither approach generalizes; the framing or features need to change." |

The **0.03 margin** is the threshold for "meaningful" — small enough to flip on a clear signal, large enough that noise alone (across the bootstrap CI of a single val set) shouldn't trigger it. We commit to this margin in Phase 1 to prevent Phase 6 us from saying *"well it's only 0.01 worse, but we already built the LSTM, so let's ship that anyway."*

### What this protects against

1. **Sunk-cost bias.** If we've spent two weeks building the LSTM, we'll be tempted to ship it on a marginal win. Pre-committing the decision rule removes that pressure.
2. **Post-hoc justification.** Without a published rule, we'd write the writeup around whichever model we ended up with and reverse-engineer the reasoning. With a rule, the writeup explains *why the rule was set this way*, which is much more defensible.
3. **Reviewer challenge.** "Why did you pick the LSTM?" has a clean answer: "the IF baseline scored X AUROC, the LSTM scored X+M, M ≥ 0.03 — and we pre-committed in Phase 1 to ship the LSTM if the margin exceeded 0.03." That's reproducible reasoning, not asserted preference.

### Both directions are valid results

Either outcome produces a publishable result for the writeup:

- **AE wins** (margin ≥ 0.03): "Sequence structure provides a meaningful uplift over aggregate-feature baselines for trajectory anomaly detection at LEMD." Adds to the case for sequence models in this domain.
- **IF wins** (margin < 0.03): "Aggregate-feature methods are sufficient; sequence structure does not add measurable value for trajectory anomaly detection at LEMD." Goes against the field's bias toward complex sequence models — arguably the *more interesting* result for a course writeup, because it's a negative result that disciplines the field.

The LSTM AE is the *hypothesis*, IF is the *null*, and Phase 6 runs the experiment. We ship whichever wins.

### Tracked in the manifest

The decision is logged in `manifest.yml > gates.train.track_confirmed`, which flips from `false` to `true` once Phase 6 evaluation produces both AUROC numbers and the rule above is applied. Until that flip, `model_track: dl` is provisional. If the rule selects IF, `model_track` flips to `ml` at the same time `track_confirmed` flips to `true`.

### Caveats

- The rule uses **val** AUROC for the model-selection decision, not test. The test set stays burned for Phase 7 final evaluation only — never used for model selection (Guardrail #1, test-set firewall).
- Both models are trained on the same train split and evaluated on the same val split. Different hyperparameters per model are fine; different data is not.
- The 0.03 margin is on AUROC because AUROC is our primary metric (D-005). If a future revision changes the primary metric, the margin needs to be re-derived for the new metric.
- F2 and FPR are also reported for both models in Phase 6, but they don't drive the AE-vs-IF choice — they inform threshold selection within whichever model wins. (F2 ties broken in favor of the simpler model.)

---

## Success metric

| Slot | Metric | Why |
|---|---|---|
| **Primary** | AUROC > 0.85 | Threshold-free, model-quality, design-doc commitment. |
| **Operational** | F2 at chosen threshold | β=2 weights recall twice as much as precision — expresses "FN is the worse error" without changing the model's training objective. Reported in eval + demo. |
| **Guardrail** | FPR ≤ 15% at chosen threshold | Hard cap. If violated, the project is not shippable regardless of the other numbers. |
| **Sanity** | PR-AUC | Cross-check that AUROC isn't flattered by class imbalance (rare anomalies, abundant normals). |
| **Comparison** | All four computed for IF baseline AND LSTM AE | Per Guardrail #10 — the model is judged against the baseline, not in absolute terms. |

### Why these specifically

**AUROC primary** because Phase 1 commits to a metric *before training*, before we know the score distribution or operating point. AUROC summarizes separating power across all thresholds — it's a property of the model's ranking, not of any specific operating choice.

**F2 operational** because the operational cost asymmetry pulls toward recall: missing a hostile drone is catastrophic (Gatwick December 2018: 36-hour closure, 1000+ flights cancelled, ~£50M cost), while a false alarm is annoying. F2 weights recall 2× more than precision.

**FPR ≤ 15% guardrail** because without it, the other metrics can be gamed by a lax threshold. A model can get AUROC = 0.95 and F2 = 0.90 while alerting on 30% of normal flights — useless. The guardrail constrains the threshold choice, not the model choice.

**PR-AUC as sanity** because AUROC has a known weakness on heavily imbalanced data: the FPR denominator gets diluted by the huge number of true negatives. PR-AUC uses precision, which doesn't suffer that dilution. Costs nothing to compute alongside.

See [D-005](decisions/D-005-metric-stack.md) for the full derivation.

---

## Cost of FP vs FN

Two lenses pull opposite ways:

**Operational lens (deployed at LEMD):**
- FN (missed hostile drone) → potential collision, airport closure, multi-million-euro disruption, conceivable loss of life
- FP (false alarm) → operator investigates, finds nothing, cost = operator time + alert fatigue

→ Heavy recall preference. F2 at operating threshold expresses this.

**Demo lens (course presentation):**
- FP (false alert on Iberia flight) → audience loses confidence in the system
- FN (missed anomaly the audience knows is in the data) → harder to demonstrate but visible to evaluators

→ Slightly precision-leaning, or balanced.

**Resolution.** AUROC as primary metric does not take a side. The threshold is operator-tunable in the demo (slider) so the audience sees the precision/recall trade-off live. The F2 secondary expresses the operational priority. The FPR ≤ 15% guardrail prevents lax thresholds from gaming the other numbers.

---

## Inference modes (eval vs demo)

Two inference modes, two purposes — common in ML projects:

| Mode | When | What | Used for |
|---|---|---|---|
| **Batch** | After trajectory complete | Run AE on full sequence | Phase 7 evaluation. Headline AUROC, F2, FPR, PR-AUC come from here. |
| **Streaming** | At each new timestep | Run AE on prefix `[points 1..t]` | Demo. Animation shows score evolving as the trajectory unfolds. |

### The parity caveat (Guardrail #9)

The model is trained on full trajectories. Streaming inference feeds it partial trajectories. This is technically a train/inference parity mismatch.

**For the demo:** we accept the mismatch and document it in the writeup. The model is small and fast enough that re-running it on prefixes is computationally cheap; the score evolves over time in a visually compelling way.

**For Week 4 stretch (parity fix):** train the AE on **random subsequences** rather than always full ones. The model becomes parity-correct across both batch and streaming modes. Costs ~1 day of Phase 6 retraining. Attempt only if Week 3 finishes ahead of schedule.

This is a real systems trade-off worth discussing in the Medium piece.

---

## Synthetic anomalies for demo and evaluation

We use the same four anomaly injection types for both eval and demo (per design doc):

| Type | What it does | Visual on map |
|---|---|---|
| Zone violation | Reroute path through restricted polygon | Trajectory crosses red zone |
| Altitude violation | Shift altitude band (+/-300m) | Altitude profile breaks expected band |
| Hovering | Replace 30s segment with stationary point | Trajectory pauses mid-flight |
| Speed spike | 3× velocity for 20s window | Trajectory jumps unusually far |

For the demo we precompute, say, 20 trajectories: 15 with one of the four anomaly types injected, 5 unmodified normals. Audience picks one (or random), watches animation, watches score evolve, sees alert trigger or not.

The geofence baseline must score < 0.80 AUROC on the same injected test set. If a simple rule-based geofence beats 0.80 on our synthetic anomalies, our injections are too easy and the ML approach isn't earning its complexity. This is the realism sanity check from the design doc.

---

## Constraints

- **Latency.** Inference < 1 second per trajectory segment on a laptop (no GPU at demo time). LSTM hidden=64, 2 layers, easily satisfied.
- **Compute / memory.** Training fits on Colab T4 GPU free tier. CPU training acceptable up to a 6-month dataset. Inference is CPU-only.
- **Interpretability.** Basic per-feature and per-timestep contribution to anomaly score is **in scope** (see In-scope additions below). Deep methods (SHAP, LIME, attention-based) are out of scope.
- **Data privacy / PII.** ADS-B contains no PII. No constraint.
- **Connectivity.** Demo must work end-to-end on a laptop with no external API calls.

---

## In-scope additions (beyond the design doc)

Added during Phase 1 consolidation, in scope for the deliverable:

- **Per-feature reconstruction error.** For a flagged trajectory, decompose total MSE by feature → "the model couldn't reconstruct your altitude profile" vs "the model couldn't reconstruct your heading." Visualization in the demo and writeup.
- **Per-timestep error profile.** Line plot showing reconstruction error along the trajectory → "the anomaly is concentrated in the last 30 seconds." Helps the audience see *where* the model was surprised.
- **Actual-vs-reconstructed trajectory overlay.** Map shows the input path and what the AE "thought" it should have looked like. Revealing for the audience.

All three fall out of the autoencoder naturally — the reconstruction is a sequence, so we can compute `(actual - reconstructed)²` element-wise and slice it by feature or timestep. No new model needed.

---

## Out of scope

```
Out of scope (course deliverable):
  - Three-class intent classification (cooperative / negligent / hostile)
    Reason: rejected in Phase 1, intent is unobservable
  - Trajectory prediction / forecasting beyond reconstruction
    Reason: D-004, anomaly scoring only
  - Visual detection / camera tracking
    Reason: Option B CUT in design doc, no calibrated dataset
  - RF / SDR-based detection
    Reason: no hardware
  - DJI Remote ID via Android (Option C)
    Reason: Week 4+ stretch only, not in core 5-week plan
  - Real-time deployment to AENA / production service
    Reason: course demo only
  - Multi-airport generalization
    Reason: LEMD only; cross-airport is future work
  - Construction of a labeled hostile dataset
    Reason: ethically and economically infeasible
  - Camera calibration from raw video
    Reason: no calibrated dataset, no time
  - Deep interpretability (SHAP / LIME / attention attribution)
    Reason: basic recon-error decomposition is enough for the demo
  - Counterfactual generation ("what would have made this trajectory normal")
    Reason: out of scope; potential future work

Explicit non-goals:
  - Beating SOTA anomaly detection methods
  - Producing a deployable counter-drone system
  - Three-dimensional drone classification (consumer / industrial / military)
```

---

## Decisions

| ID | Date | Decision | Where |
|---|---|---|---|
| D-001 | 2026-04-11 | Frame as anomaly detection, not three-class intent classification | [decisions/D-001](decisions/D-001-anomaly-vs-classification.md) |
| D-002 | 2026-04-11 | ADS-B as training modality; source-agnostic model at inference | [project decisions log](../decisions/README.md) |
| D-003 | 2026-04-11 | OpenSky Network as primary dataset | [project decisions log](../decisions/README.md) |
| D-004 | 2026-04-11 | Anomaly scoring only; no trajectory prediction | [project decisions log](../decisions/README.md) |
| D-005 | 2026-05-07 | Metric stack (AUROC primary, F2 operational, FPR≤15% guardrail, PR-AUC sanity, all vs IF baseline) | [decisions/D-005](decisions/D-005-metric-stack.md) |
| D-006 | 2026-05-07 | LSTM Autoencoder primary, Isolation Forest baseline; alternatives considered and rejected | [decisions/D-006](decisions/D-006-architecture-and-baseline.md) |

---

## Open questions / TODOs (to revisit in later phases)

1. **Conditional normality (Phase 4 EDA, Phase 5 features).** LEMD's runway configuration changes with wind direction, time of day, day of week, season, and visibility. A model that sees only the trajectory will learn "normal" as a mixture of all configurations, widening the decision boundary. The design doc partially addresses this with `time_of_day_sin / cos`. Missing: day-of-week, month/season, inferred runway-in-use, and METAR (wind, visibility). Decision: revisit in Phase 4 once we can SEE whether configuration regimes are visible in the data; address as additional context features in Phase 5.

2. **Image + tabular features as alternative architecture (Phase 6 stretch).** Render trajectories as 2D images and use a CNN encoder + clustering, or fuse image + tabular features in a multi-modal model. Real approach with literature behind it. Out of scope for the primary model in 5 weeks; revisit as a Week 4 stretch or as future work in the writeup.

3. **Synthetic anomaly realism (Phase 6).** Confirm via the rule-based geofence baseline that injected anomalies aren't trivially detectable by simple rules. Geofence baseline must score < 0.80 AUROC on the same test set. If it scores higher, our injections are too easy and the ML approach doesn't earn its complexity.

4. **Forecast-and-residual fallback (Phase 6, hard stop).** If LSTM AE training is unstable in Week 3, swap to forecast-and-residual: train an LSTM to predict the next state vector from the previous N, score the residual. Easier to debug, naturally streaming, same threshold-by-construction approach. Architecture roughly the same.

---

## Exit gate checklist

- [x] `backend/docs/ml/01-problem.md` exists, all sections filled in
- [x] `manifest.yml > problem_type` set to `anomaly_detection`
- [x] `model_track` set tentatively to `dl` (confirmed in Phase 6)
- [x] Primary success metric chosen with target value (AUROC > 0.85)
- [x] Cost asymmetry of FP vs FN articulated (FN dominates operationally)
- [x] Non-ML baseline considered (rule-based geofence; design doc requires < 0.80 AUROC on injected anomalies)
- [x] Constraints listed (latency, compute, interpretability, PII, connectivity)
- [x] Out-of-scope section written
- [x] In-scope additions captured (interpretability)
- [x] High-stakes decisions ADR'd (D-001, D-005, D-006)
- [x] Open questions logged for later phases (conditional normality, image+features, synthetic anomaly realism, forecast-residual fallback)
- [x] Manifest gate `problem` flipped to `passed`
- [x] Manifest `current_phase` advanced to `data`
