# Architecture

## Current system — approach-screening schema v3

The active specification is
[`../designs/33-approach-conformance-reframe.md`](../designs/33-approach-conformance-reframe.md).

```text
bounded observed rows
  -> schema validation and canonicalization
  -> operation continuity and attempt reconstruction
  -> AIP runway-relative geometry and direction inference
  -> telemetry/coverage quality gates
  -> deterministic observable criteria + train-only reference bands
  -> immutable evidence contract
  -> FastAPI same-origin API
  -> React attempt queue / dossier / upload results
```

The deployable artifact contains geometry, criterion configuration, the empirical reference,
precomputed approach evidence and provenance digests. Torch and the historical LSTM are not
runtime dependencies. Uncertain evidence produces `partial_observation` or `not_assessable`, not
an inferred result.

The sealed evaluation failed qualification; this architecture is a research and labeling
demonstrator, not operational conformance or safety software. See
[`../ml/iterations/approach-screening/07-eval.md`](../ml/iterations/approach-screening/07-eval.md).

## Historical architecture

The original unauthorized-drone, identity-gate and LSTM anomaly concept is preserved in
[`design-trajectory-anomaly-detection.md`](./design-trajectory-anomaly-detection.md). The later
score-first console is preserved in [`sadar-merge-design.md`](./sadar-merge-design.md). Both are
superseded product designs and must not be read as descriptions of the current release.
