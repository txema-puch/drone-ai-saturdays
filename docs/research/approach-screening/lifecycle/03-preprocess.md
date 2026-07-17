# Phase 3 — Preprocess and attempt reconstruction

## Contract

`backend/src/sadar/approach/assessment.py` reconstructs evidence from canonical observed rows. Rows marked missing
by historical interpolation masks are excluded. Time is ordered and deduplicated; gaps remain
observable rather than filled.

Candidate `flight_id` records can yield zero, one or multiple attempts. Corridor re-entry after
180 seconds creates a new attempt, so a go-around and later approach are not collapsed. Parallel
runway candidates are clustered temporally before transparent exact/direction inference.

## Rate-invariant quality

- minimum 20 observed samples over 90 seconds;
- runway-inference evidence spans at least 60 seconds inside a 600-second window;
- criterion exceedance persists for at least three rows and 20 seconds;
- gaps over 60 seconds, impossible position rates and failure to reach the 6 km analysis gate
  abstain the attempt;
- impossible barometric rates abstain the altitude channel only.

Tests cover interpolation exclusion, multiple attempts, persistence, coverage gaps, corrupt
telemetry, touchdown and go-around outcomes. The sealed-holdout firewall hashes before reading.

## Gate result

Passed. The extractor reproduces the notebook approach population (4,272 vs 4,268) while exposing
13 extra train attempts beyond the operation count, confirming attempt-level reconstruction.
