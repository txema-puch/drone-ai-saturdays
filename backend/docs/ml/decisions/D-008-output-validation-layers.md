# D-008 — Multi-layer output validation, including real-emergency external set

**Status:** decided
**Date:** 2026-05-23
**Phase:** eval (prep)
**Supersedes:** none (extends D-005, D-006, and the design doc's "geofence baseline" realism check)
**Affects:** Phase 7 (eval) and the writeup's experimental contribution section

## Context

The LSTM autoencoder produces a single scalar per trajectory: the
reconstruction error (mean squared error between input and reconstructed
state-vector sequence). Higher = more "anomalous." This is the entire output
of the model.

The number itself has no semantic meaning. It is a real-valued reconstruction
score whose interpretation depends entirely on what we choose to compare it
against. **Until grounded externally, "anomaly score = 0.5" tells us nothing
about whether the trajectory was actually anomalous.**

This is the foundational challenge of unsupervised anomaly detection: with no
labels, you cannot directly measure "accuracy." You have to construct meaning
for the score through layered validation, each layer answering a different
question.

The Phase 1 problem doc and the design doc partially address this via:

- **D-005 metric stack:** AUROC > 0.85 primary; F2 operational; FPR ≤ 15%
  guardrail; PR-AUC sanity. All measured against **synthetic anomaly
  injections** (the four perturbation types).
- **Geofence baseline realism check (design doc, lines 269 + 349 of
  01-problem.md):** the geofence baseline must score < 0.80 AUROC on the
  same injected test set. If a simple rule beats 0.80, the injections are
  too easy and the ML approach is not earning its complexity.
- **D-006 decision rule:** LSTM AE val AUROC ≥ IF val AUROC + 0.03 → ship
  the AE; otherwise ship IF. Pre-committed in Phase 1 to prevent retconning.

Together these establish *discriminative* validation — does the model score
known synthetic anomalies higher than normal trajectories? — and *competitive*
validation — does it beat simpler baselines?

What they do not address: **does the model behave meaningfully on
anomalies it has never seen?** A high AUROC against the four injection types
we hand-designed can still reflect imagination leakage (Phase 1 doc, lines
138-141): the model learns the *injection function*, not real-world anomaly
behavior. The synthetic AUROC is necessary but not sufficient.

This decision adds the missing layers, with a concrete external set.

## Decision

Validate the model output through **five layers**, each answering a distinct
question:

| # | Layer | Question | Method | Sufficient alone? |
|---|---|---|---|---|
| 1 | Sanity | Does the AE converge and reconstruct normal flights well? | Training loss curves; input-vs-reconstruction overlay plots for a sample of normal trajectories | No |
| 2 | Discriminative | Do injected synthetic anomalies score higher than normal? | AUROC, F2, PR-AUC (per D-005) on the four injection types and any added types (cf. 07-eval-prep.md) | No |
| 3 | Realism | Is a dumb rule too good at this? | Geofence baseline AUROC < 0.80 on the injected set; STCA/APW/MSAW/APM safety-net analogs (added 2026-05-23 session) per-type AUROC vs AE per-type AUROC | No |
| 4 | External | Does the model flag REAL anomalies it never trained on or saw injected? | OpenSky scientific Dataset #6 (Olive et al., 2020): flights that triggered the 7700 transponder squawk (real emergencies). LEMD-area subset, score with trained AE, report reconstruction-error percentile vs normal validation distribution + Mann-Whitney U | **NO, but the single highest-credibility layer for the writeup** |
| 5 | Qualitative | Do the top-K flagged "normal" flights look weird to a human? | Top 20 reconstruction-error scores from the normal validation set, plotted on a map + altitude profile, reviewed by hand | No |

**No single layer is sufficient. Together they validate the output is meaningful.**

## Layer 4 — the missing piece, in detail

OpenSky scientific Dataset #6 is the practical solution to the "we have no
real anomalies" problem.

- **What it is:** Reference Datasets for In-Flight Emergency Situations,
  curated by Xavier Olive (ONERA), derived from full OpenSky ADS-B data.
  Spans flights seen by OpenSky receivers between 1 January 2018 and 29
  January 2020 that triggered the **7700 transponder squawk** (pilot-set
  general emergency code). Principally sourced from OpenSky's Alerts page.
- **Why it matters:** The 7700 squawk is a real-world signal that ATC,
  pilots, and emergency services treated the flight as significant. These
  trajectories are the closest publicly available proxy for "ground truth
  anomalies" in commercial-aviation airspace. Crucially: **the model is
  never trained on them, never injected with them, never told they exist
  until Phase 7 evaluation.**
- **Source:** Linked from
  https://opensky-network.org/data/scientific (entry #6). Paper:
  *OpenSky Report 2020: Analysing In-Flight Emergencies Using Big Data*,
  Olive et al., 2020 IEEE/AIAA DASC.

### Protocol for using Dataset #6

1. **In Phase 4 EDA:** pull Dataset #6, filter to LEMD-area trajectories
   (same 200 km bbox + Filter B used for cycle 3). Inspect: how many
   flights, what kinds of emergencies (medical, technical, fuel, security),
   what altitude / approach profiles. Document in Phase 4 EDA artifact.
2. **In Phase 6 training:** do not use Dataset #6 in any training,
   validation, or threshold-tuning step. Treat it as a sealed external set,
   same firewall posture as the test set (Guardrail #1 / D-005).
3. **In Phase 7 eval (after model selection per D-006 is finalized):** run
   the trained AE on Dataset #6 trajectories. Report:
   - N (number of LEMD-area 7700-flagged flights)
   - Per-flight reconstruction error
   - Percentile placement vs the normal validation distribution
   - Mann-Whitney U test (non-parametric, robust to small N): is the
     emergency-flight error distribution stochastically larger than the
     normal-flight distribution?
4. **Pre-commit the finding template** (this prevents retconning):

   > "Real-emergency reconstruction errors fell at the **Nth percentile**
   > of the normal-flight distribution (Mann-Whitney U p = **X**), based on
   > **K** LEMD-area 7700-squawk trajectories from OpenSky Dataset #6
   > (Olive et al., 2020) that the model had never seen during training or
   > injection."

### Expected N and statistical posture

Dataset #6 covers ~2 years globally. 7700 squawks are rare — global rate is
a few hundred per year. The LEMD-area subset will be small:

- **Realistic expectation:** 5-30 LEMD-area emergency flights
- **Statistical posture:** small-N qualitative + non-parametric test,
  not a headline AUROC. Mann-Whitney U with N=10 is informative but its
  confidence interval is wide. Report it honestly.
- **What this is FOR:** a credibility check, not a primary metric. The
  primary metric stays D-005's synthetic AUROC. Layer 4 supplements it.

### Both directions are publishable

This is critical to commit before running the analysis:

- **If real emergencies score systematically high (e.g., >90th percentile of
  normal):** the model is doing something real. The architectural-critique
  Medium piece is strengthened.
- **If real emergencies score at random (~50th percentile) or low:** the
  synthetic AUROC was overstating capability. The "imagination leakage"
  problem Phase 1 flagged actually materialized. This is *more interesting*
  for the writeup — a negative result that disciplines the field.

Either outcome must be reported. The protocol prevents post-hoc reframing.

## Layer 5 — qualitative top-K review

Cheap, fast, high signal for the practitioner-audience writeup.

### Protocol

After Phase 6 model selection per D-006:

1. Score the full normal validation set with the trained AE.
2. Take the **top 20 highest reconstruction-error scores**. These are
   trajectories the model considers anomalous among data we labeled
   "normal."
3. For each, produce:
   - 2D map of the trajectory (lat/lon)
   - Altitude profile vs time
   - Velocity profile vs time
   - Reconstruction overlay (input vs AE output)
4. One reviewer (the writeup owner) inspects each one for ~2 minutes.
   Classify each as: obvious anomaly that should have been excluded /
   subtle anomaly worth flagging / actually normal (model false positive).

### What it tells us

- **If most top-20 look like genuine anomalies** (mode confusion, holding
  patterns, aborted approaches, unusual rerouting): the model generalizes
  beyond synthetic injection patterns. Strong evidence Layer 4's
  expected-positive result would be earned, not spurious.
- **If most top-20 look normal:** the model overfit to noise or to the
  specific injection shapes. Weak.

This becomes a 1-paragraph addition to the Medium piece's experimental
contribution: "We hand-reviewed the top-20 reconstruction-error flights
from the normal validation set. X of 20 exhibited mode confusion, holding
patterns, or aborted approaches; Y appeared normal."

## Why the existing realism check is not enough

The design doc's geofence baseline check (line 269 of 01-problem.md) tests
whether the injected anomalies are too easy:

> *"The geofence baseline must score < 0.80 AUROC on the same injected test
> set."*

This is necessary — if a simple rule catches our injections at >0.80, the
ML is unjustified — but it's not sufficient. It only proves the injections
are non-trivial. It does not prove the AE is detecting real-world anomaly
*shapes*. Layer 4 closes that gap.

## Alternatives considered

1. **Skip external validation; rely on synthetic AUROC alone.** Cheapest.
   Rejected because the Phase 1 doc itself acknowledges the
   imagination-leakage risk (lines 138-141). Skipping the external check
   leaves a known credibility gap in the writeup.
2. **Use Dataset #6 globally, not LEMD-area only.** Larger N. Rejected
   because the model was trained on LEMD-specific patterns; emergency
   flights elsewhere would conflate "anomaly" with "different airport."
   Layer 4 should isolate the model's claim to its training domain.
3. **Cross-reference with FAA UAS Sighting Reports as additional external
   set.** Already used to calibrate synthetic injection (per
   07-eval-prep.md), but FAA reports describe drone *sightings* (a
   different population than the model is trained on — drones, not manned
   aviation). Not useful for Layer 4. Stays in 07-eval-prep.md as
   injection-calibration data only.
4. **Build a labeled validation set from incident press reports** (the
   LEMD incidents catalogued in 07-eval-prep.md §7 — Feb 2020, Feb 2024,
   Nov 2024, etc.). Rejected because journalistic reports don't include
   track-level data. The flights involved cannot be linked to specific
   ADS-B records. Useful as narrative context only.

## Consequences

**Gain:**

- The Medium piece can credibly claim "we tested the model against real
  emergencies, not just our own synthetic anomalies." This is the single
  highest-leverage sentence in the writeup.
- Both possible outcomes (real-emergency scores high / random / low) are
  publishable and pre-committed to a finding template — no retconning
  risk.
- Closes the imagination-leakage gap Phase 1 explicitly flagged.

**Cost:**

- ~half day in Phase 4 EDA to pull and inspect Dataset #6.
- ~half day in Phase 7 to run the analysis and write the finding.
- ~2 hours for the Layer 5 qualitative review.
- Total: ~1 day across Phases 4 and 7.

**Risk acknowledged:**

- Small-N (5-30 flights) makes the Layer 4 finding statistically weak.
  Mitigated by pre-committing the finding template and reporting Mann-
  Whitney U with honest confidence intervals.

## Implementation links

- Phase 4 EDA pull and inspect: tracked in Phase 4 entry-gate work
  (artifact TBD when Phase 4 starts).
- Phase 7 protocol: codified in
  `backend/docs/ml/07-eval-prep.md > External validation (Layer 4)`
  (added in same session as this ADR).
- Cross-references: this ADR will be linked from
  `manifest.yml > gates.eval.summary` once Phase 7 entry gate is reviewed.

## Related decisions

- [D-005 — Metric stack (synthetic AUROC primary)](D-005-metric-stack.md)
- [D-006 — LSTM AE vs IF decision rule](D-006-architecture-and-baseline.md)
- [D-007 — OpenSky scientific dataset as primary cycle-3+ data source](D-007-opensky-scientific-data-source-pivot.md) — provides infrastructure for Dataset #6 use
- Design doc's geofence-baseline realism check (`backend/docs/architecture/design-trajectory-anomaly-detection.md`)
- 07-eval-prep.md's synthetic-injection calibration (Layer 2 source)

## Open questions

1. **Do we lift the test-set firewall posture to Dataset #6 as well?** I.e.,
   does Phase 6 model selection get to peek at Dataset #6 to choose between
   AE and IF, or does that decision stay strictly on the synthetic
   validation set (per D-006)? **Recommended: keep D-006 as-is** (synthetic
   val AUROC only). Dataset #6 stays sealed until the AE-vs-IF question is
   already resolved.
2. **What counts as "LEMD-area" for Dataset #6 filtering?** Recommend the
   same 200 km bbox + Filter B used in cycle 3, with the same
   `distance_to_closest_runway < 10 km` proximity criterion. Document
   choice; expected small effect on which flights make the cut.
3. **What to do if Layer 4 finds zero LEMD-area emergencies?** N=0 is
   possible given how rare 7700 squawks are. Fallback: expand to "within
   1000 km of LEMD" or use the full Western-European subset, with the
   caveat that this conflates LEMD-specific signal with the broader manned-
   aviation distribution. Decide if it happens; don't pre-commit.
