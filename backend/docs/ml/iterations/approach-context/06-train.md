# Phase 6 — Contextual reference fitting

## Selected approach

No classifier is trained. The selected candidate remains deterministic rules plus a train-only
empirical reference, now conditioned on supported aircraft type. Independent outcome labels do
not exist, so a learned model would either imitate the rules or manufacture a target.

`backend/scripts/fit_contextual_approach_reference.py` fits only the 2017–2018 train cohort:

- candidate operations: 8,594;
- eligible attempts: 3,774;
- accepted attempts: 3,764;
- typed-attempt rate: 99.34%;
- reference cells: 101 (91 exact-type, 10 unknown fallback);
- exact supported types: 14;
- equal-attempt empirical-CDF quantiles prevent long attempts from dominating row counts;
- fitted speed values are bounded to 0–150 m/s and vertical rate to ±25 m/s before fitting;
- maximum published upper-speed bound: 128.66 m/s;
- artifact digest: `53c6998329131d7fc6a86334b7b4e14f749a8e6c64b0944bd769f5ad123bb1cf`;
- fit source commit: `b2e31c4c477adc388cf38b03bbb2cfffe3f87fb3`.

The original polluted A319/direction-18/0–1.5 km cell (246.07 m/s upper bound) is 80.77 m/s after
attempt balancing and value gating. The immutable artifact is
`backend/core/resources/lemd_approach_context_reference_v1.json`. Validation and 2025 data do
not affect its bands or support thresholds.

## Gate result

Passed with a contextual statistical reference and no supervised model selected. This is a
legitimate lifecycle result: available labels do not justify a learned product feature.
