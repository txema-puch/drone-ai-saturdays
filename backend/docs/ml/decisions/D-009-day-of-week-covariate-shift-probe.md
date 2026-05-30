# D-009 — Day-of-week covariate-shift probe via Supabase cycles 1+2

**Status:** decided
**Date:** 2026-05-23
**Phase:** preprocess (Phase 3)
**Supersedes:** none (extends D-007's data-source pivot and D-008's validation stack)
**Affects:** Phase 3 (preprocess — sets training corpus), Phase 4 (EDA — probe inspection), Phase 7 (eval — probe execution), the writeup

## Context

Phase 3 needs to settle whether the LSTM AE trains on cycle 3 alone, on
cycles 1+2+3 pooled (with 5s → 10s harmonization), or on parallel pipelines.
The trade-off was framed in the Phase 3 entry coaching session (2026-05-23):

- **Cycle 3 alone (option B):** 19,057 trajectories, single 10s resolution,
  no harmonization step. Cost: Monday-only — day-of-week coverage collapses
  from cumulative 6/7 to 1/7.
- **Cycles 1+2+3 pooled (option A):** 21,768 trajectories, 6/7 day-of-week.
  Cost: 5s data downsampled to 10s (deliberate information loss); training
  set spans 9 calendar years with plausibly non-stationary LEMD operations
  (post-COVID traffic, fleet renewal, route changes).
- **Parallel pipelines (option C):** doubles every Phase 4-7 task. Cut for
  the 3-week course timeline.

Option B was chosen as the **training corpus**. This leaves cycles 1+2 (the
Supabase-sourced 5s ADS-B data covering 2025-03-10 → 2026-03-14, 6/7
day-of-week) un-trained-on.

The natural question: **does training only on Mondays produce a model that
systematically scores non-Monday LEMD operations as anomalous?** That would
be a restricted-regime model — useful but with a real claim-level limitation
the writeup has to acknowledge.

Cycles 1+2 are the right corpus to test this with. They were validated under
the Phase 2 cyclic-gate protocol; their schemas align with cycle 3's; they
cover the full Mon-Sat week. They are out of the cycle-3 training
distribution by construction.

This decision formalizes that use.

## Decision

Use **cycles 1+2 (the Supabase-sourced 5s parquets) as a covariate-shift
diagnostic probe set**, not as additional training data and not as a sealed
external test set. Specifically:

1. **Not in training.** Cycle 3 alone trains the model (locked).
2. **Not the test set.** The Phase 6 train/val/test split happens within
   cycle 3. Cycles 1+2 are outside that firewall.
3. **Diagnostic, not single-shot.** Scored repeatedly during Phase 4-7
   development to characterize and mitigate (if possible) day-of-week
   regime risk. Iterative use is allowed because the probe answers a
   model-understanding question, not a model-selection one.

The probe is documented as a deliverable in its own right — a chapter or
subsection in the writeup characterising the restricted-regime claim — not
as a private debugging tool.

## Why diagnostic (not sealed test)

D-008's Layer 4 (OpenSky Dataset #6, real 7700-squawk emergencies) is
sealed-test-style — burned once in Phase 7, scored exactly once, with a
pre-committed finding template. That posture is correct there because the
question ("does the model react to real anomalies?") is the central
evaluation claim, and repeated peeking would contaminate it.

The day-of-week question is different. We're not asking "is the model
good?", we're asking "what does the model not generalize to?" — which is
exactly the kind of question the validation set was invented for. Treating
the probe as sealed would force a single Phase 7 measurement and prevent us
from iterating on, e.g., a debiasing strategy if Monday-bias is severe.

The cost: this probe is **not** evidence at the same credibility level as
Layer 4. The writeup must be explicit. Layer 4 is single-shot external
validation; D-009 is regime-characterisation diagnostic.

## Protocol

### Inference-side preprocessing (cycles 1+2 → 10s)

Cycles 1+2 are 5s ADS-B; the model expects 10s sequences. To score the
cycle-3-trained model on cycles 1+2, downsample at inference:

- **Method:** decimation — keep every other row per trajectory.
- **Rationale:** the simplest correctness-preserving operation. LEMD
  approach/departure profiles are smooth at the 5s scale; the 10s subsampled
  trajectory is geometrically and dynamically equivalent for the model's
  state-vector features. Per-trajectory resampling/interpolation was
  considered and rejected as unnecessary complexity.
- **Where it lives:** in the inference-side preprocessing pipeline, not the
  training-side preprocessor. Phase 3's `pipeline_definition` excludes it;
  Phase 7 / Phase 4 inference code applies it before calling the trained
  AE on cycles 1+2.

### Within-corpus delta — the actual measurement

Scoring cycles 1+2 directly and comparing the absolute RE to cycle 3's
validation RE confounds two effects:

- (a) Day-of-week effect — the thing we want to measure.
- (b) Calendar-year / regime effect — cycles 1+2 are 2025-2026, training is
  2017-2020. Post-COVID traffic, fleet, route changes likely shift the
  joint distribution.

To disentangle, compute the **within-corpus delta**:

| Subset | What it captures | Sample size today |
|---|---|---|
| Cycle 1+2 Monday rows | Both effects (year shift + Monday) | 1 Monday in cycles 1+2: 2025-03-10 (≤250 trajectories) |
| Cycle 1+2 non-Monday rows | Year shift only | Tue-Fri from cycle 1 + Tue-Sat from cycle 2 (~2,500 trajectories) |
| Delta = RE(non-Monday) − RE(Monday) | Day-of-week effect, with year-shift confound differenced out | — |

**Interpretation:**

- **|Delta| small (~ within the noise band of normal-validation RE):** day-
  of-week does not matter at the resolution our probe can measure. The
  restricted-regime claim is weakened (good).
- **Delta strongly positive (non-Monday RE >> Monday RE):** Monday is
  meaningfully easier for the model. The model has a day-of-week prior.
  The restricted-regime claim is strengthened; mitigation strategies (e.g.,
  Phase 5 day-of-week feature, or Phase 6 fine-tune on a few non-Monday
  examples) become considerable.
- **Delta strongly negative (Monday RE > non-Monday RE):** something weird —
  probably indicates the Monday side has too few trajectories for the
  measurement to be stable, or there's a separate confound. Report
  honestly; do not over-claim.

### Pre-committed finding template

> "The cycle-3-trained model's reconstruction error on cycles 1+2 Monday
> trajectories (N = **N_mon**) and non-Monday trajectories (N = **N_non**)
> showed a within-corpus delta of **delta_RE** (units: same as RE). The
> Monday-side sample size limits the statistical conclusion — the day-of-
> week effect is **{negligible / present / inconclusive}** at the
> resolution our probe can measure. Cycles 1+2 calendar period
> (2025-03-10 → 2026-03-14) differs from the training period (2017-06 →
> 2020-03); calendar-year / regime-shift effects are differenced out by
> the within-corpus comparison but persist in the absolute RE level."

### Known limitation: Monday sample size

At time of writing, cycles 1+2 contain exactly **one Monday** (2025-03-10
from cycle 1). Cycle 2 covered Tue-Sat. ~250 Monday trajectories — usable
for a confidence-interval-wide delta estimate but weak as a deliverable.

**Open follow-up:** Txema to source another Monday into the probe set
(either by re-running an existing cycle on the Monday boundary, or by
adding a small Supabase fetch for one more Monday in the cycle 1+2 calendar
range). Two Mondays gets the probe to a respectable lower bound on its
own confidence interval; ideally we want ≥3.

If a second Monday is sourced before Phase 7 runs, append it to the
`02-data.md` Cycle 1 or Cycle 2 section as an addendum and re-run the
probe.

## Alternatives considered

1. **No probe; ship option B as-is.** Cheapest. Rejected because the
   day-of-week regression to 1/7 is a known limitation we owe the writeup
   reader, and we have an unused validated corpus that can characterise it.
2. **Treat cycles 1+2 as a sealed external test set (single-shot, burn in
   Phase 7).** Higher credibility per measurement. Rejected because (a)
   iterative use is required if Monday-bias is severe and we need to test
   mitigations, (b) the question is regime-characterisation not
   discrimination, and (c) D-008 Layer 4 already provides the single-shot
   external evidence for the discrimination question.
3. **Pool cycles 1+2+3 with 5s → 10s harmonization (option A from Phase 3
   entry).** Eliminates the question entirely. Rejected because
   harmonization is real engineering work and the training set then spans
   2017-2026, mixing regimes; the day-of-week framing trades cleanly for a
   restricted-regime claim plus a probe.
4. **Validation aid for hyperparameter tuning** (i.e., let cycle 1+2 RE
   influence Phase 6 model selection between AE and IF). Rejected — that
   would contaminate D-006's decision rule, which is committed to synthetic
   val AUROC only.

## Consequences

**Gain:**

- The Monday-only training claim becomes a *characterised* limitation
  rather than an *acknowledged* one. The writeup can quantify it.
- Cycles 1+2's audit work (PRs #14, #16) gets a direct downstream use in
  the model evaluation, despite being out-of-training.
- Pairs with D-008 as the project's structured story about "what
  validation actually means in unsupervised anomaly detection."

**Cost:**

- ~1 hour in Phase 4 EDA to pull cycles 1+2 from Drive, decimate to 10s,
  inspect the resulting input format.
- ~2 hours in Phase 7 to compute the within-corpus delta, write the
  finding paragraph.
- The probe set's Monday side is currently N=1 (one calendar Monday) until
  another is sourced.

**Risk acknowledged:**

- The 2017-2020 vs 2025-2026 calendar gap means we can't fully
  disentangle day-of-week from year-shift without more data. The
  within-corpus delta is the best mitigation; report honestly.
- The probe is *not* evidence at D-008 Layer 4's credibility level. Writeup
  must be explicit about the difference.

## Implementation links

- Inference-side decimation: implemented in Phase 4 / Phase 7 inference
  code, not in `pipeline_definition`. Documented in
  `03-preprocess.md > Inference-side preprocessing for the cycle 1+2
  probe` (to be written as part of Phase 3 exit gate).
- Phase 4 EDA inspection of cycles 1+2 in the model's input space:
  artifact TBD when Phase 4 starts.
- Phase 7 protocol entry: cross-reference from
  `07-eval-prep.md > External validation` (to be added).
- Cross-reference from `manifest.yml > gates.preprocess.summary` and
  `gates.eval.summary` once each phase advances.

## Related decisions

- [D-005 — Metric stack (AUROC primary on synthetic injections)](D-005-metric-stack.md)
- [D-006 — LSTM AE vs IF decision rule (synthetic val AUROC only)](D-006-architecture-and-baseline.md)
- [D-007 — OpenSky scientific dataset as primary cycle-3+ data source](D-007-opensky-scientific-data-source-pivot.md) — establishes the cycle-3-alone training pattern that this probe is built around
- [D-008 — Multi-layer output validation including Dataset #6 external set](D-008-output-validation-layers.md) — establishes the framework this probe slots into (alongside, not inside, Layer 4)

## Open questions

1. **How many more Mondays should we source to make the probe respectable?**
   Recommend ≥2 additional Mondays before Phase 7 (total ≥3). The cost is
   one Supabase fetch + one audit cycle per additional Monday. Decision
   deferred to when Txema actually fetches; the probe runs with whatever
   N_mon exists at Phase 7 time and the limitation is reported honestly.
2. **What if delta is strongly positive — do we mitigate, or just
   characterise?** Recommend: characterise in Phase 7 first (no scope
   creep), then propose a Phase-5-style feature-engineering or
   Phase-6-style fine-tune mitigation as a future-work bullet in the
   writeup. Do not start a mitigation loop inside the existing 3-week
   timeline unless the delta is so severe it invalidates the headline
   result.
3. **Do we extend this probe pattern to other covariates (time-of-day,
   season, weather, runway-configuration)?** Out of scope for Phase 3. If
   Phase 4 EDA surfaces a candidate covariate that cycles 1+2 can probe
   (e.g., evening vs morning if cycle 3 happens to be morning-skewed),
   open a follow-up ADR. Don't bake speculative probes into Phase 3 now.
