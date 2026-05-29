# D-001: Frame as anomaly detection, not three-class intent classification

**Phase:** problem
**Date:** 2026-04-11
**Status:** decided
**Authors:** team (via `/office-hours` design doc generation)

## Context

The original brief (Scenario 8) framed the problem as a three-class intent classification task: classify each drone trajectory as `cooperative`, `negligent`, or `hostile`. We considered this framing carefully and rejected it.

## Options considered

### Option A — Three-class intent classification

**Pros:** matches the language of the original brief; output is directly actionable.

**Cons:**
- **No labeled data exists** for `hostile` or `negligent` classes. Constructing one requires either real-world hostile incidents (rare, sensitive, not reusable) or synthetic labels (introduces a label-generation procedure that becomes the project).
- **Intent is unobservable from trajectory alone.** The same flight profile (hovering near a runway) could be a wedding photographer who got lost or a deliberate disruption attempt. The signal in the data does not contain the information the label requires.
- **Three-class framing requires ground truth that isn't available** in 5 weeks at any quality.
- **Even with labels, the class boundaries are subjective** — what makes a flight "negligent" vs "hostile" is a legal / regulatory judgment, not a data-driven distinction.

### Option B — Binary classification (authorized vs unauthorized)

**Pros:** simpler than three-class; cleaner objective.

**Cons:** still requires labeled examples of "unauthorized," which we don't have. Same fundamental problem as Option A, slightly relaxed.

### Option C — Anomaly detection

**Pros:**
- **Only needs labeled normal data**, which is abundant and free via OpenSky.
- **Sidesteps the unobservable-intent problem** — we don't claim to detect intent, only statistical deviation from authorized flight patterns.
- **Threshold is operator-tunable** at deployment, separating model output from action policy.
- **Source-agnostic at inference** — the model takes `[lat, lon, alt, speed, heading]` regardless of whether those came from ADS-B, RF triangulation, or visual tracking. The training-data source and inference-data source can differ.

**Cons:**
- **Output is a continuous score, not a class label.** Requires a separate threshold-selection step. Acceptable.
- **No explicit handling of "negligent" vs "hostile"** — both look anomalous, the model doesn't distinguish. Acceptable: that distinction is a regulatory/operator judgment, not the model's job.

## Decision

**Option C — anomaly detection.**

## Consequences

- The model takes trajectories as input and outputs a continuous anomaly score in [0, ∞).
- A two-layer system at inference: identity gate (Layer 1, ICAO24 lookup, U-Space match) clears authorized vehicles cheaply; the anomaly scorer (Layer 2) handles unidentified or deviating tracks.
- Evaluation requires synthetic anomaly injection, since there are no labeled real anomalies. Four injection types specified: zone violation, altitude violation, hovering, speed spike.
- The geofence baseline must score < 0.80 AUROC on the same injected test set to confirm the ML approach adds value beyond simple rules.
- The framing shapes everything downstream: the data is unlabeled, the loss is reconstruction (or density), the metrics are threshold-tied, the evaluation requires an injection step.

## Revisit triggers

- If, in Phase 4 EDA, we discover that the data overwhelmingly contains a clear distinction between classes (e.g., the dataset has structurally different segments that map onto "drones vs aircraft" cleanly), reconsider whether a clustering-then-classify framing fits better.
- If the geofence baseline scores ≥ 0.80 AUROC on injected anomalies, the synthetic anomalies are too easy and the framing's value is questionable until we redesign the injections.

## References

- Design doc: `backend/docs/architecture/design-trajectory-anomaly-detection.md` (sections "Problem Statement," "Premises (Revised)," "Approaches Considered")
- Project-level decision log: `backend/docs/decisions/README.md` (D-001 entry)
