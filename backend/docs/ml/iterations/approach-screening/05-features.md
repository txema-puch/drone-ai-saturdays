# Phase 5 — Observable criteria and empirical features

## Deterministic features

- AIP runway-relative along/cross-track position;
- runway direction and exact/pair specificity;
- lateral centreline proxy inside 6 km;
- bias-corrected barometric 3° path proxy where a trustworthy bias exists;
- observed vertical rate;
- wrap-safe ground-track difference inside 3 km;
- outcome and per-channel quality evidence.

All evidence spans require at least 20 seconds. `heading` is represented as observed ground track;
no aircraft-heading claim is made.

## Train-fitted reference features

Ground speed and observed vertical rate use 1st/99th percentile bands in five along-track distance
bins and two runway directions. Ten cells pass the minimum 20 attempts / 100 observations gate.
The current cohort has no aircraft type, so `speed_class=unknown` is explicit and lookup falls back
to that class rather than deriving class from the speed being assessed.

## Leakage check

Geometry and criteria are fixed per attempt. Reference fitting hard-fails for any fold other than
`train`; the artifact records the split-ID hash and a content digest. The 2019 and 2025 cohorts
transform only. The 2020 and sealed 2026 datasets cannot enter the fit path.

## Gate result

Passed. Feature output is deterministic, schema-versioned and criterion-readable.
