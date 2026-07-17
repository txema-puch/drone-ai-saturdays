# D-015 — Rules-first whole-arrival approach screening

**Status:** implemented; sealed qualification failed; operational deploy blocked
**Date:** 2026-07-14
**Phase:** new iteration, problem through evaluation
**Supersedes:** no historical result; the completed LSTM iteration remains immutable

## Context

The frozen LSTM autoencoder reconstructs the first 260 steps of mixed-phase segments. Its score
cannot answer which approach criterion failed, frequently omits the terminal phase, and did not
beat simple baselines consistently. The deployed UI therefore presents numerical anomaly evidence
that an analyst cannot translate into a clear action.

The available ADS-B data can support narrower post-flight observations: runway-relative path,
barometric altitude proxy, ground speed, vertical rate, track changes, touchdown proximity,
coverage quality and go-around geometry. It cannot support certified stabilized-approach judgments.

## Decision

Start an append-only ML lifecycle iteration around observed LEMD approach attempts.

1. Reconstruct whole arrivals and approach attempts before feature extraction.
2. Use deterministic quality gates and observable criteria for statuses and explanations.
3. Fit train-only, distance-binned empirical envelopes for cohort-relative ground-speed and
   vertical-rate evidence; serialize them as a small JSON reference artifact.
4. Keep the old LSTM and its metrics unchanged as a historical research benchmark that never
   changes status or priority.
5. Seal the 2026 snapshot before final evaluation. The burned 2020 cohort is diagnostic only.
6. Train a supervised model only after independent labels exist. It must add useful cases over
   rules at an acceptable workload on the fresh holdout before it can influence ranking.
7. Begin with an observed-row feasibility gate. Do not reuse interpolated model frames as rule
   evidence, and do not begin the release/UI migration until reconstruction, runway inference,
   altitude fallback and criterion prevalence are measured.
8. After the ADS-B-only iteration, run a separate contextual lifecycle for weather/QNH/wind,
   aircraft type, and any lawfully obtainable configuration/mass/clearance sources.

## Consequences

- The product becomes explainable and useful even if no new classifier is justified.
- Runway/altitude uncertainty and telemetry conflicts produce abstention, not false precision.
- Prototype thresholds and reference envelopes remain explicitly non-certified.
- Training may end with “ML adds no product value”; that is a valid lifecycle outcome.

## Outcome — 2026-07-14

The schema-v3 rules-first candidate was implemented and evaluated once on the sealed 2026
snapshot. Assessable retention was 63.1% against a 65% target, and independent review labels were
not available to estimate precision. Qualification therefore failed. The implementation remains
valid as a research and evidence-labeling demonstrator, but no operational conformance claim may
be made and the burned cohort cannot be used to tune a successor.

## References

- `docs/product/design.md`
- `docs/archive-manifest.yml` (the archived pending-work ledger, PW-001 through PW-004)
- `docs/research/trajectory-anomaly/lifecycle/decisions/D-014-window-truncation-of-long-arrivals.md`
- `docs/research/approach-screening/lifecycle/07-eval.md`
