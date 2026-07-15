# Phase 6 — Contextual reference fitting

## Selected approach

No classifier is trained. The selected candidate remains deterministic rules plus a train-only
empirical reference, now conditioned on supported aircraft type. Independent outcome labels do
not exist, so a learned model would either imitate the rules or manufacture a target.

`backend/scripts/fit_contextual_approach_reference.py` fits only the 2017–2018 train cohort:

- candidate operations: 8,594;
- eligible attempts: 3,804;
- accepted attempts: 3,792;
- typed-attempt rate: 99.29%;
- reference cells: 100 (90 exact-type, 10 unknown fallback);
- exact supported types: 14;
- equal-attempt empirical-CDF quantiles prevent long attempts from dominating row counts;
- fitted speed values are bounded to 0–150 m/s and vertical rate to ±25 m/s before fitting;
- maximum published upper-speed bound: 128.66 m/s;
- artifact digest: `68ea1a974a077e0b2ef8322564d7799c5fd52cbd21db42b8d5bf1badad57d328`;
- fit source commit: `305166924590940b6fad9ad62dd0a736fcd698ee`.

The original polluted A319/direction-18/0–1.5 km cell (246.07 m/s upper bound) is 80.77 m/s after
attempt balancing and value gating. The immutable artifact is
`backend/core/resources/lemd_approach_context_reference_v1.json`. Validation and 2025 data do
not affect its bands or support thresholds.

## Gate result

Passed with a contextual statistical reference and no supervised model selected. This is a
legitimate lifecycle result: available labels do not justify a learned product feature.
