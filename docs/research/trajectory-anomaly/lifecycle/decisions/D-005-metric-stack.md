# D-005: Metric stack — AUROC primary, F2 operational, FPR≤15% guardrail, PR-AUC sanity, all vs IF baseline

**Phase:** problem
**Date:** 2026-05-07
**Status:** decided

## Context

Phase 1 requires committing to a primary success metric *before training*, with a target value. The design doc specifies AUROC > 0.85 and FPR ≤ 15% but does not name the operational metric or the cost asymmetry it should express. This decision consolidates the full metric stack and the rationale for each slot.

The four-slot framing (primary / operational / guardrail / sanity) is borrowed from the `/ml-lifecycle` skill. Each slot answers a different question; the metrics aren't redundant.

## The four slots

| Slot | Behavior | Question it answers |
|---|---|---|
| Primary | Optimize for it; report it as the headline number | Is the model good? |
| Operational | Report at the chosen threshold; talks to deployment quality | Is it useful in the real setting? |
| Guardrail | Hard pass/fail; if violated, the project doesn't ship regardless of the others | Is it safe / acceptable? |
| Sanity | Cross-check against the primary; not a target | Is the headline lying? |

## Options considered (per slot)

### Primary metric

**Candidates:** Accuracy / F1 / F2 / F0.5 / AUROC / PR-AUC.

- **Accuracy** rejected — meaningless on imbalanced data (Guardrail #3). A "always normal" predictor gets 99.5% accuracy on a typical day with 5 anomalies in 1000 flights.
- **F1** considered — balanced precision-recall, but threshold-dependent. We don't know the operating threshold at Phase 1, so committing to an F1 target requires an arbitrary threshold guess.
- **F2** considered — operationally well-aligned (recall-heavy), but threshold-dependent for the same reason.
- **AUROC** selected as primary — threshold-free, summarizes the model's ranking ability across all operating points, design-doc commitment with target > 0.85.
- **PR-AUC** considered as primary — threshold-free and handles imbalance better than AUROC, but the design doc commits to AUROC.

**Decision:** **AUROC, target > 0.85**, threshold-free, primary.

### Operational metric

The operational metric is reported at the chosen threshold and expresses how the model performs at the deployment operating point.

**Candidates:** F1 / F2 / F0.5 / Precision@k / Recall.

The choice depends on the cost asymmetry of FP vs FN:

```
F_β  =   (1 + β²) ·  precision · recall  /  (β² · precision + recall)

β = 0.5  → weights precision more (FP is the worse error)
β = 1.0  → balanced
β = 2.0  → weights recall more (FN is the worse error)
```

**Cost asymmetry (operational lens, deployed at LEMD):**
- FN (missed hostile drone): potential collision, airport closure (Gatwick December 2018: 36-hour closure, ~£50M cost).
- FP (false alarm): operator investigates, finds nothing, alert fatigue.

→ FN dominates. Recall-heavy preference. **F2.**

**Decision:** **F2 at the chosen operating threshold.**

### Guardrail

**Why we need one:** the other metrics can be gamed by a lax threshold. A model can show AUROC = 0.95 and F2 = 0.90 while alerting on 30% of normal flights — useless in deployment, even if "good" by the headline numbers.

**Candidate guardrails:** FPR cap, FN cap, latency cap, cost-per-prediction cap.

**Decision:** **FPR ≤ 15% at the chosen operating threshold.** From the design doc. Caps the false-alarm rate at a level that's notionally acceptable for a counter-drone advisory system. Below 15% is the threshold for "shippable"; above is "do not ship."

### Sanity check

**Candidate:** PR-AUC alongside AUROC.

**Why:** AUROC has a known weakness on heavily imbalanced data. The denominator `FP + TN` (in FPR) is dominated by `TN` when normals vastly outnumber anomalies, so FPR stays low even when precision is mediocre. PR-AUC uses precision, which doesn't suffer that dilution.

**Decision:** **PR-AUC reported alongside AUROC.** Costs nothing extra. If AUROC and PR-AUC tell different stories, that's a finding worth investigating.

### Comparison protocol

**Decision:** all four metrics computed for both models — Isolation Forest baseline AND LSTM Autoencoder primary. The model is judged against the baseline (Guardrail #10), not in absolute terms. A 0.88 AUROC LSTM is meaningless if IF gets 0.87.

## Decision

```
Primary:     AUROC > 0.85 (threshold-free)
Operational: F2 at chosen threshold
Guardrail:   FPR ≤ 15% at chosen threshold (hard cap, ship/no-ship gate)
Sanity:      PR-AUC alongside AUROC

All four computed for both:
  - Isolation Forest baseline (per-trajectory aggregate features)
  - LSTM Autoencoder primary (per-timestep sequence features)
```

## Consequences

- Phase 6 produces both an IF baseline AUROC and an LSTM AE val AUROC for comparison.
- Phase 7 evaluation reports all four metrics on the held-out test set, for both models, with bootstrap confidence intervals where applicable.
- The threshold choice (95th percentile of recon error on val normal) gives FPR ≈ 5% by construction, comfortably within the guardrail.
- The demo includes an operator-tunable threshold slider so the audience can see precision/recall trade-offs live.
- Writeup includes a short "metrics" subsection explaining the four-slot logic — readable for non-ML audiences, useful for the Medium piece.

## Revisit triggers

- If the LSTM AE shows AUROC ≥ 0.85 but PR-AUC is dramatically worse (say < 0.5), the AUROC is being flattered by imbalance; we'd discuss whether to use PR-AUC as the headline instead.
- If FPR at the 95th-percentile threshold consistently exceeds 15%, we'd raise the threshold (toward 99th percentile) at the cost of recall, and report both operating points.
- If F2 at the chosen threshold is dominated by precision (i.e., recall is poor), we'd reconsider whether the cost asymmetry is being expressed correctly or whether the model needs more recall-favored training.

## References

- Design doc: `docs/research/trajectory-anomaly/original-design.md` (Evaluation, Success Criteria sections)
- `/ml-lifecycle` Phase 1 reference: `references/phase-1-problem.md` (Success metric subsection)
- Guardrail #3 (class imbalance) and Guardrail #10 (baseline required) — `/ml-lifecycle/references/guardrails.md`
