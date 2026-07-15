# Phase 1 — Contextual problem

## Decision

Test whether lawful, reproducible context can make the existing post-flight approach screen more
complete and more appropriately conditioned. Context may change which proxy is observable or
which train-only reference cell applies; it does not turn the system into emergency detection,
certified stabilized-approach monitoring, or causal analysis.

## User and action

The user remains a post-flight analyst. The action is to inspect and label observed evidence.
QNH can recover a first-order barometric path proxy, airport wind can contextualize ground-speed
conditions, and aircraft type can select a more comparable empirical envelope. The analyst must
still decide whether an attempt merits domain review.

## Success gates

- at least 95% QNH coverage, 80% airport-wind coverage, and 80% aircraft-type coverage on the
  newer-source audit;
- deterministic temporal joins, explicit missingness, and no use of a future weather report;
- no configuration, mass, clearance, or intent field unless an observed lawful source exists;
- independent labels and a new untouched holdout before any claim of better review precision or
  operational promotion;
- measured incremental analyst value over the ADS-B-only screen, not merely more flags.

QNH and aircraft-type source gates pass; airport wind misses its gate at 78.09%. The
qualification gates also fail: there are no independent labels and no fresh holdout. The result
is therefore a research candidate only, with wind treated as optional display evidence.
