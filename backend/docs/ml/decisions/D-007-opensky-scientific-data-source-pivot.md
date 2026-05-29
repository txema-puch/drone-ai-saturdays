# D-007 — OpenSky scientific dataset as primary cycle-3+ data source

**Status:** decided
**Date:** 2026-05-23
**Phase:** data
**Supersedes:** none (extends D-002 / D-003)
**Affects:** Phase 2 (cycle 3+), Phase 3 (preprocessing resolution decision)

## Context

After Phase 2 cycles 1 + 2 (10 days, 2,711 trajectories — `gates.data` is cyclic
and "passed" but still SOFT_DEV per D-207), we tried to plan cycle 3 to extend
coverage. The Trino → Supabase ingestion path that produced cycles 1 + 2 had been
the dominant human-side bottleneck: it required cross-teammate coordination
(Monica owns the export script + Supabase fills), it accumulated quirks
(pagination strategy churn, indexes missing on table arrival, table-naming
convention drift), and it was slow to schedule another cycle on.

Independently this session, while pressure-testing whether the LSTM-AE framing
makes any "business sense at all," it surfaced that:

- The 2021 paper "Deep Autoencoder for Anomaly Detection in Terminal Airspace
  Operations" already established the methodology we're applying. Our honest
  contribution is empirical replication + careful baseline comparison at LEMD,
  not new method.
- For a peer-reviewed paper that bar would be too low. For a course-deliverable
  Medium piece aimed at practitioners, the bar is "when does this pay off
  against the rule-based safety nets that ATC actually uses today?" — a
  publishable, defensible question.
- That framing makes data reproducibility a real asset: a cite-able dataset
  beats a Supabase-only audit trail.

The OpenSky Network's public scientific dataset
[(opensky-network.org/data/scientific entry #1)](https://opensky-network.org/data/scientific)
publishes one full 24-hour state-vector snapshot every Monday for 2017-06-05
through 2022-05-23, downloadable directly from S3 with no credentials at
10-second resolution. Schema is identical to the columns OpenSky exposes via
Trino. Total 259 Mondays, 138 of which are non-COVID.

## Decision

Adopt the OpenSky scientific dataset as the **primary** data source for cycle
3 and likely all subsequent cycles. The Trino + Supabase path is retired as
primary; the existing `OpenSkyService` in `backend/crud/opensky.py` stays in
the codebase as a reference implementation and as the source of truth for the
per-row derivations the new path reuses.

For cycle 3 specifically:

- **20 Mondays** sampled evenly across 2017-06 → 2020-03 (COVID excluded)
- **Filter B** applied per trajectory: keep iff `min(dist_to_runway_m) < 10_000m`
  AND `min(baroaltitude) < 3_000m`. This excludes cruise overflights at
  FL350-FL410 that transit central Spain en route between unrelated airports
  but never touch LEMD. Empirically removes ~47% of bbox-only trajectories.
  See `backend/scripts/download_opensky_states.py` docstring.
- **Filter B is the cycle-3 replacement for D-002's "source-agnostic at
  inference"** in the data-collection sense: where the Trino path used the
  `flights_data4.estarrivalairport/estdepartureairport` metadata to keep only
  LEMD flights, the scientific path has no such metadata and substitutes a
  proximity + altitude heuristic. The 0 km median min_dist and 533 m median
  min_alt observed across 967-1,200 kept trajectories per Monday confirms the
  heuristic captures LEMD arrivals/departures cleanly.

## Alternatives considered

1. **Stay on Trino + Supabase.** Familiar, audited, has metadata. Rejected
   because the human-side bottleneck made cycle cadence unworkable for the
   remaining ~3 weeks of the course.
2. **OpenSky scientific dataset (chosen).** Public S3 download, no
   credentials, schema-compatible, cite-able. Trade-offs: 10s vs 5s
   resolution; no origin/destination metadata (Filter B substitutes); Monday
   sampling bias.
3. **Hybrid (Trino for cycles 1+2 + scientific for cycle 3+).** Architecturally
   honest but adds resolution-mismatch complexity at Phase 3 preprocessing
   (need to downsample 5s → 10s on the old data, or split into two parallel
   pipelines). Defer to Phase 3.
4. **TartanAviation (CMU AirLab).** Peer-reviewed alternative dataset, fully
   pre-cleaned. Rejected because its two airfields (KBTP, KAGC) are general
   aviation, not commercial-hub traffic; the LEMD framing would have to be
   dropped and the deployment narrative reframed around small-airport safety.

## Consequences

**Gain:**

- Cite-able primary dataset (Zenodo / OpenSky scientific DOI). Reproducibility
  becomes a real writeup asset: anyone can re-pull the same 20 Mondays.
- Zero human-side coordination for new cycles — running the script overnight
  produces the data.
- ~21K LEMD trajectories from cycle 3 alone, ~8x the cumulative trajectories
  from cycles 1 + 2 (2,711). Exits SOFT_DEV territory, well into CONDITIONAL
  per D-207.
- Atomic, resumable ingestion. Re-running skips Mondays already on disk.

**Lose:**

- 10s sampling vs the Trino path's 5s. Phase 3 needs to either downsample the
  older parquets to 10s for compatibility, or train two parallel pipelines.
  Recommend downsample-to-10s as the cheap path.
- `flights_data4` origin/destination metadata. The Filter B heuristic
  substitutes but it's not the same evidence — a cruise flight that happens
  to descend below 3 km within 10 km of LEMD (e.g., a low-altitude diversion)
  would be kept by Filter B; the Trino metadata would correctly exclude it as
  not LEMD-bound. Cross-spot-checking against Dataset #4 (COVID-19 Flight
  Dataset, OpenSky scientific entry #4) was considered as a rigor upgrade but
  deferred — small expected impact.
- Day-of-week diversity. Scientific dataset is Mondays only. Cycle 1 + 2 had
  Mon-Sat coverage. Phase 3 EDA should explicitly check whether the model
  trained on Mondays-only learns weekday-specific patterns.

**Risk acknowledged but accepted:**

- Some Mondays in the bucket return 404 for every hour (verified: 2022-01-17,
  2022-03-21, 2022-05-23 — the last three usable Mondays of the published
  range). These are out of our control and replaced with earlier-2020
  pre-COVID Mondays at run time.
- Some Mondays have malformed CSV rows (verified: 2018-04-02, 2019-12-02 —
  rows with non-numeric lat/lon strings break `np.radians`). Mitigated in the
  script via `pd.to_numeric(..., errors="coerce")` on lat/lon/numeric columns
  immediately on read.

## Implementation

- New script: `backend/scripts/download_opensky_states.py` (~370 lines).
  Documented inline; reuses `distance_to_closest_runway` and
  `calculate_flight_phase` from `backend/crud/opensky.py` to keep derivation
  consistency with the Trino path.
- New deps: `requests>=2.32` added explicitly to `backend/pyproject.toml`
  (was transitive).
- Pre-existing settings-loader bug fixed: `Settings.Config.extra = "ignore"`
  in `backend/core/config.py` so the multi-account cycle-N env vars from
  cycle 2 don't crash settings instantiation.
- Output layout: `data/raw/opensky_states/lemd_<YYYYMMDD>__opensky_states_<fetchYYYY-MM-DD>.parquet`,
  one file per Monday. Schema identical to the cycle 1+2 deduped parquets.

## Validation

- End-to-end smoke test on 2017-06-05 (first Monday in bucket): 967
  trajectories, 186,305 rows, 12 min wall-clock. Parquet schema verified
  identical to `data/raw/lemd_20260310_to_20260314__snapshot_2026-05-11.parquet`
  (21 columns, all present, no extras).
- Filter B 100% effective on test parquet — every kept trajectory satisfies
  the bounds.
- Full-day probe on 2019-10-07 (used to dimension Filter B): 1,174
  trajectories kept, 1,055 cruise overflights excluded (median min_alt
  10,668 m, median min_dist 55 km).

## Related decisions

- [D-002 — ADS-B as training modality; source-agnostic model at inference](../../decisions/README.md)
- [D-003 — OpenSky Network as primary dataset](../../decisions/README.md)
- [D-209 — Parquet naming derives from data's `time_utc` range](../02-data.md)
- [D-210 — Six-category response playbook for audit findings](../../workflow/data-pipeline.md)

## Open questions to revisit

1. **Per-cycle dataset_hash in manifest** — cycle 3 produces 20 per-Monday
   parquets instead of one snapshot. The manifest's `dataset_hash` map needs
   a convention for the new shape. Proposed: hash the sorted concatenation
   of per-Monday parquet hashes (Merkle-style); single entry per cycle.
   Decision needed before manifest commit.
2. **Phase 3 resolution decision** — downsample cycles 1+2 to 10s, or train
   two parallel pipelines. Recommend downsample at preprocess.
3. **Cross-reference with Dataset #4** — small-effort upgrade that would
   replace Filter B with rigorous origin/destination metadata lookup. Defer
   to a possible later cycle; not blocking.
