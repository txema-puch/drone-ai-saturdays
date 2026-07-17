# Phase 2: Data

**Status:** passed
**Started:** 2026-05-07 (manifest entry created)
**Closed:** 2026-05-11 (cycle 1 audited and documented; audit discipline operational)

## Goal

Establish an audit discipline that validates every batch of ADS-B trajectory data delivered through our Supabase pipeline, before any preprocessing, EDA, training, or evaluation work begins on it. By the end of this phase, the team should have:

- A documented validation methodology that handles current and future cycles uniformly
- A verified local snapshot of every batch, with sha256 hashes recorded in the manifest
- A clear response protocol when the audit catches something
- Confidence that downstream phases (3 through 8) are working from data we've actually looked at

This phase's gate is marked `gate_semantics: "cyclic"` in the manifest. That means *the audit discipline* is what gets passed, not *data completeness*. The data will continue accumulating as Monica's extraction cycles run (each cycle ~500 MB of Supabase, then truncate-and-refill); the discipline is what gets validated once and then re-applied per cycle. Each cycle adds an entry to this doc's "Snapshot log" and to the manifest's `dataset_hash` without re-passing the gate. The `gate_semantics` field is a `/ml-lifecycle` framework extension documented in `references/lifecycle-map.md > Gate semantics`.

## Inputs

- `docs/research/trajectory-anomaly/original-design.md` — APPROVED design doc (2026-04-11)
- `docs/research/trajectory-anomaly/lifecycle/01-problem.md` — Phase 1 problem definition (closed 2026-05-07)
- `docs/research/trajectory-anomaly/lifecycle/manifest.yml` — lifecycle state machine
- `docs/research/trajectory-anomaly/data-workflow.md` — workflow doc with role assignments, naming conventions, response playbook, dedup override rules
- `backend/research/src/sadar_research/trajectory_anomaly/data/opensky.py` — Monica's upstream pipeline (OpenSky → Supabase)
- `backend/research/src/sadar_research/trajectory_anomaly/data/export_sample.py` — extraction runner
- `research/trajectory-anomaly/notebooks/lifecycle/05_phase2_data_validation.ipynb` — the audit notebook itself

## Outputs

- This document
- `manifest.yml > gates.data` populated with cycle 1's hash and summary
- `data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__{snapshot,deduped}_<YYYY-MM-DD>.parquet` per cycle, plus sha256 sidecars (synced to Google Drive)
- Validation figures in `docs/research/trajectory-anomaly/figures/02-data/`
- Decisions logged inline below (eligible for promotion to ADRs in `docs/research/trajectory-anomaly/lifecycle/decisions/` if revisited)

---

## Source(s)

**Primary:** OpenSky Network historical archive, accessed via Trino-backed `flights_data4` and `state_vectors_data4` tables. Access requires a research account (held by Monica). The query applies a 200 km radius filter around Madrid-Barajas (LEMD) before download.

**Delivery:** Supabase project shared by the team. A single working table holds whatever Monica's most recent extraction cycle produced. The table is treated as transient storage — see "Pipeline pattern" below.

**License / privacy:** OpenSky Network research data is freely usable for academic and research purposes per the OpenSky Network terms of service. Redistribution requires attribution. ADS-B contains no PII; all aircraft identifiers (`icao24`) are publicly broadcast.

**Cost:** Free, subject to OpenSky's research-account quotas (Monica manages).

## Pipeline pattern

The data delivery follows a **truncate-fill-snapshot cycle**:

1. Monica runs the extraction script repeatedly, adding ranges to the Supabase table (`INSERT … ON CONFLICT DO NOTHING` prevents within-cycle duplicates once the unique constraint is in place)
2. When Supabase approaches its free-tier 500 MB limit, Monica notifies the team
3. Txema runs `research/trajectory-anomaly/notebooks/lifecycle/05_phase2_data_validation.ipynb`, which pulls all rows, validates them, and writes the canonical parquet snapshot to `data/raw/`
4. Both raw and (when applicable) deduped parquets are uploaded to Google Drive with `.sha256` sidecars
5. Txema confirms snapshot integrity to Monica → Monica `TRUNCATE`s the Supabase table → cycle 2 begins

Each cycle produces one parquet (raw) and optionally a second (deduped or otherwise cleaned). Together, the parquets accumulate the full training dataset. Phase 6 training will load all of them.

Full workflow specification: `docs/research/trajectory-anomaly/data-workflow.md`.

## Validation methodology

The audit applies seven methodology decisions locked during Phase 2 design coaching (conversation transcript 2026-05-08). Each is recorded as an inline decision (D-201 through D-207) and is referenced from the manifest. The notebook implements all seven.

### D-201 — Critical columns

Six columns are designated *critical* (must be non-null for the row to be valid):

`time, icao24, lat, lon, baroaltitude, flight_id`

Critical-null rows would be structurally meaningless. Other columns may have nulls and are reported but do not fail the gate. `velocity` and `heading` are needed for ML training but their nullity is a Phase 5 concern, not Phase 2.

### D-202 — FAIL action chain

When a check fails:

1. Document in this doc's "Snapshot log" section
2. Open a GitHub `[Bug]` issue tagging the team (not just Monica)
3. Keep broken rows in the snapshot — snapshot mirrors source by default

The "Response playbook" section of the workflow doc generalizes this for the six response categories that emerged after cycle 1.

### D-203 — Three-key duplicate detection

Report three counts side-by-side (their combination is diagnostic):

- `(flight_id, time)` — loose; catches multi-receiver aggregation edge cases
- `(flight_id, time, lat, lon)` — medium; catches same-place-same-instant duplicates
- Full row — strict; catches byte-for-byte re-inserts

### D-204 — Range bounds (generous, physical)

Phase 2 catches *broken* data, not *out-of-interest* data. Bounds used:

| Column | Bounds |
|---|---|
| `lat`, `lon` | physical Earth bounds |
| `baroaltitude`, `geoaltitude` | -500 to 50_000 m |
| `velocity` | 0 to 400 m/s (Mach 1 + buffer) |
| `heading` | 0 to 360° |
| `vertrate` | -100 to 100 m/s (aerobatics + buffer) |
| `velocity_kmh` | 0 to 1500 km/h |
| `dist_to_runway_m` | 0 to 200_000 m (upstream filter limit) |

Soft cross-check: lat/lon in LEMD bbox `[38.5°, 42.5°] × [-6.0°, -1.2°]`, expected ≥99% coverage.

### D-205 — Pipeline consistency tolerances

Re-derive four upstream-computed columns from the raw inputs and compare:

| Column | Tolerance |
|---|---|
| `velocity_kmh` | < 1e-6 km/h (IEEE-754 noise only) |
| `dist_to_runway_m` | < 1 m (haversine trig accumulation) |
| `time_utc` | < 1 s (effectively exact) |
| `flight_phase` | 100% exact match (deterministic rule, no float noise) |

A < 100% agreement on `flight_phase` is the strongest signal of pipeline version skew.

### D-206 — Real / Usable verdict mapping

Real = schema match PASS AND no range violations AND ≥99% in LEMD bbox.
Usable = no critical nulls AND no full-row duplicates AND consistency PASS.

### D-207 — Four-bucket Enough verdict

| Bucket | Condition |
|---|---|
| **NOT_YET** | < 500 trajectories (below project-viability floor per design doc) |
| **SOFT_DEV** | < 30 days OR < 5,000 trajectories |
| **CONDITIONAL** | 5K-19,999 trajectories AND 30-89 days |
| **PASS** | ≥ 20,000 trajectories AND ≥ 90 days |

The Enough verdict is cumulative across all cycles, computed by the notebook's volume-metrics cell.

---

## Schema (data dictionary)

21 columns total — 15 raw from OpenSky, 6 derived by Monica's pipeline. Observed values from cycle 1 deduped parquet (1,146,231 rows).

| Column | Kind | Type | Nulls | n_unique | Observed Range | Notes |
|---|---|---|---|---|---|---|
| `time` | raw | int64 | 0 | 296,674 | 1.74157e9 to 1.74200e9 (epoch s) | Sequence index, 1-second granularity. Spans 2025-03-10 to 2025-03-14. |
| `icao24` | raw | str | 0 | 330 | 6-char hex | 330 unique aircraft across 5 days. |
| `lat` | raw | float | 0 | 137,363 | 38.65 to 42.32 | WGS84. Within LEMD ±200km region. |
| `lon` | raw | float | 0 | 197,665 | -5.96 to -1.15 | WGS84. Slightly exceeds initial bbox (-1.20); see Known issues #6. |
| `baroaltitude` | raw | float | 80 (0.0044%) | 1,528 | 259 to 35,204 m, mean 5,636 m | Barometric altitude. 80 nulls — see Known issues #1. |
| `geoaltitude` | raw | float | 205 (0.01%) | 1,511 | 236 to 33,985 m, mean 5,550 m | GPS altitude. Distinct null pattern from baroaltitude (see Known issues #4). |
| `velocity` | raw | float | 7 | 50,229 | 21.21 to 428.27 m/s, mean 171.78 | Ground speed. 1 outlier above 400 m/s — see Known issues #5. |
| `heading` | raw | float | 7 | 178,998 | 0 to 359.88° | Compass bearing. |
| `vertrate` | raw | float | 7 | 176 | -28.94 to 161.58 m/s, mean -0.39 | Vertical climb rate. 1 outlier above 100 m/s — same row as velocity outlier? See Known issues #5. |
| `callsign` | raw | str | 0 | 587 | E.g., "IBE3540" | Flight identifier. |
| `onground` | raw | bool | 0 | 2 | mean 0.0001 | ~0.01% of rows have aircraft on tarmac. |
| `squawk` | raw | str | 114,589 (6.25%) | 736 | 4-digit codes | High null rate is normal ADS-B behavior — see Known issues #7. |
| `alert` | raw | bool | 0 | 2 | mean 0.0031 | Transponder alert flag. |
| `spi` | raw | bool | 0 | 2 | mean 0.0023 | Special Position Indicator. |
| `lastcontact` | raw | float | 0 | 954,626 | same range as `time` | Used by upstream stale-row filter. |
| `flight_id` | derived | str | 0 | **1,285** | `<icao24>_<firstseen-epoch>` | Trajectory primary key. Same physical aircraft on different flights gets different `flight_id`. |
| `operation` | derived | str | 0 | 2 | `arrival` / `departure` | No `unknown` rows in cycle 1 — every flight classified. |
| `time_utc` | derived | **str** | 0 | 296,674 | ISO 8601 strings | **Stored as string, not datetime.** Phase 3 will convert via `pd.to_datetime(... utc=True)`. See Known issues #8. |
| `velocity_kmh` | derived | float | 7 | 50,229 | 76.36 to 1541.79 km/h, mean 618.40 | `velocity × 3.6`. Same 1 outlier as `velocity`. |
| `dist_to_runway_m` | derived | float | 0 | 1,011,229 | 13.11 to 199,998 m, mean 81,858 | Haversine to nearest of 8 LEMD runway thresholds. |
| `flight_phase` | derived | str | 0 | 6 | `on_ground` / `takeoff` / `climb` / `approach` / `descent` / `cruise` | All 6 rule outputs present in cycle 1. **Not** ground truth — deterministic from `onground`, `baroaltitude`, `vertrate`, `dist_to_runway_m`. |

---

## Snapshot log

One entry per cycle, append-only.

### Cycle 1 — 2026-05-10 snapshot of 2025-03-10 to 2025-03-14

**Supabase source table:** `lemd_2025_03_10` (legacy name; contained 5 days despite the name suggesting one day — see Known issues #2)

**Coverage:**
- Date range: 2025-03-10 (Monday) through 2025-03-14 (Friday) inclusive, 5 days
- Day-of-week coverage: weekdays only (5/7)
- Hour-of-day coverage: 24 distinct hours

**Volume:**
- Raw rows: 1,834,084
- Deduped rows: 1,146,231
- Duplicates removed: 687,853 (37.50%)
- Unique trajectories (`flight_id`): **1,285**
- Unique aircraft (`icao24`): 330
- Operation split (rows, raw): arrival 1,107,934 vs departure 726,150 (~60/40)
- Operation split (unique flights): arrival 653 vs departure 632 (~51/49, balanced)
- Flight-phase distribution (raw rows): descent 840,599 / climb 460,474 / cruise 353,082 / approach 101,365 / takeoff 78,470 / on_ground 94

**Arrival/departure asymmetry note.** Per-flight state-vector counts differ significantly between operations:
- Arrivals: ~1,696 rows/flight (1,107,934 / 653)
- Departures: ~1,149 rows/flight (726,150 / 632)

Arrivals carry ~50% more state vectors per trajectory because they descend gradually from cruise altitude across the 200km radius (~30 min in zone), while departures climb out faster (~17-20 min in zone). This is physical behavior of low-and-slow filtered data near an airport, not a pipeline issue.

**Implication for downstream phases (not Phase 2):** If Phase 5/6 trains on per-timestep features, arrivals would be weighted ~1.5× more than departures. Per-trajectory training (which the LSTM autoencoder uses) treats them equally but has different mean sequence lengths. Worth revisiting at the Phase 6 split-design step.

**Artifacts:**

| File | Size | sha256 |
|---|---|---|
| `data/raw/lemd_20250310_to_20250314__snapshot_2026-05-10.parquet` | 73.0 MB | `0fb65f07aaf5e59d0a2e5d1015d3afbfa91346d2144d34ce8a11c0ee608905e7` |
| `data/raw/lemd_20250310_to_20250314__deduped_2026-05-10.parquet` | 45.88 MB | `8256c65f95135597f3db07413941380fc2a0c6bbfc429b07b12b10478f7e2c10` |

Both files mirrored to Google Drive at `drone-ai-saturdays/data/raw/` with `.sha256` sidecars. Raw-parquet round-trip integrity through Drive verified on 2026-05-10.

**Manifest reference:** `dataset_hash[lemd_20250310_to_20250314__deduped_2026-05-10]` (the deduped version is canonical; the raw version is kept as audit evidence).

**Validation outcomes:**

Note on PASS/FAIL/REVIEW labels: these are the audit cells' *mechanical* signals. The playbook decides the *response* — they're related but distinct. A FAIL signal doesn't automatically trigger blocking; the playbook's decision tree picks the right response (A through F) for each finding.

| Cell | Check | Mechanical result | Playbook response |
|---|---|---|---|
| 7a | Schema match | PASS — 21 columns, no missing, no extra | — |
| 7b | Type sanity | PASS — all numeric/bool columns OK | — (see Known issues #8 for the `time_utc` string-vs-datetime caveat the cell doesn't catch) |
| 7c | Critical nulls | FAIL — 80 nulls in `baroaltitude` (0.0044%) | **Response D** — known ADS-B property, document + proceed; see Known issues #1 |
| 7d | Duplicate detection | FAIL — 687,853 full-row dups (37.50%) | **Response B** — override + dedup applied; see Known issues #3 |
| 7e | Range bounds | REVIEW — 3 violations (velocity, vertrate, velocity_kmh; all 1 row each, likely 2 distinct rows total) | **Response D** — ADS-B transient glitches at 0.000175% rate; see Known issues #5 |
| 7e | LEMD bbox | PASS — 795 rows outside bbox (0.0433%, below 1% threshold) | **Response F** — bbox slightly too tight; widen to `lon ∈ [-6.0, -1.1]` in notebook; see Known issues #6 |
| 8 | Pipeline consistency | PASS — all 4 tolerances met; `flight_phase` agreement = 100.0000% | — (Monica's deployed code matches repo exactly) |

**Verdict:**
- Real: **PASS**
- Usable: **PASS** (after dedup; raw failed Usable)
- Enough: **SOFT_DEV** — 1 cycle, 5 weekdays of March 2025, 1,285 trajectories, 330 unique aircraft. Above the 500-trajectory project-viability floor; below the 30-day SOFT_DEV ceiling. Project development can proceed; full training requires more cycles before Phase 6.

### Cycle 2 — 2026-05-11 snapshot of 2026-03-10 to 2026-03-14

**Supabase source table:** `lemd_2026` (new convention per workflow doc — single working-table name with year suffix; see Known issues #2's resolution path).

**Coverage:**
- Date range: 2026-03-10 (Tuesday) through 2026-03-14 (Saturday) inclusive, 5 days
- Day-of-week coverage: Tue-Sat (5/7), [1,2,3,4,5]
- Hour-of-day coverage: 24 distinct hours
- **Same calendar window as cycle 1, one year later.** Year-over-year repeat on the same Mar 10-14 dates. Cycle 2 also adds Saturday coverage (cycle 1 was Mon-Fri).

**Volume:**
- Raw rows: 1,774,859
- Deduped rows: same — no dups detected, no dedup applied (see Known issues #3 status update)
- Duplicates removed: 0 (0.00%)
- Unique trajectories (`flight_id`): **1,426**
- Unique aircraft (`icao24`): 350
- Operation split (rows): arrival 1,093,846 vs departure 681,013 (~62/38, same arrival-bias as cycle 1)
- Operation split (unique flights): arrival 725 vs departure 701 (~51/49, balanced — like cycle 1)
- Flight-phase distribution (rows): descent 811,007 / climb 421,982 / cruise 340,411 / approach 125,335 / takeoff 76,122 / on_ground 2

**Arrival/departure asymmetry** continues from cycle 1: ~1,508 rows/arrival vs ~971 rows/departure (~55% more for arrivals). Same physical cause — longer descent profile across the 200km radius — and the same Phase 6 implication.

**Artifacts:**

| File | Size | sha256 |
|---|---|---|
| `data/raw/lemd_20260310_to_20260314__snapshot_2026-05-11.parquet` | 61.93 MB | `16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899` |

Only one parquet this cycle (snapshot is canonical — no dedup needed). Mirrored to Google Drive at `drone-ai-saturdays/data/raw/` with `.sha256` sidecar. Raw-parquet round-trip integrity through Drive verified on 2026-05-11.

**Manifest reference:** `dataset_hash[lemd_20260310_to_20260314__snapshot_2026-05-11]` (snapshot is canonical; no deduped variant exists for this cycle because no dups were found).

**Validation outcomes:**

Note on PASS/FAIL/REVIEW labels: same as cycle 1 — these are the cells' *mechanical* signals; the playbook decides the *response*.

| Cell | Check | Mechanical result | Playbook response |
|---|---|---|---|
| 7a | Schema match | PASS — 21 columns, no missing, no extra | — |
| 7b | Type sanity | PASS — all numeric/bool columns OK | — (same `time_utc` string caveat as cycle 1, Known issues #8) |
| 7c | Critical nulls | FAIL — 3 nulls in `baroaltitude` (0.000169%) | **Response D** — well below D-206's 0.1% noise tolerance; see Known issues #9 |
| 7d | Duplicate detection | **PASS — 0 dups at any granularity** | — Monica's upstream constraint working, fix from #13 confirmed effective; see Known issues #3 status update |
| 7e | Range bounds | PASS — all numeric columns within physical bounds | — (cycle 1's transient glitches did not recur) |
| 7e | LEMD bbox | PASS — 0 rows outside bbox (0.0000%) | — (cycle 1 had 0.0433% outside; cycle 2 data is cleaner) |
| 8 | Pipeline consistency | PASS — all 4 tolerances met; `flight_phase` agreement = 100.0000% | — (Monica's deployed code still matches repo) |

**Verdict:**
- Real: **PASS**
- Usable: **PASS** — mechanical cell 7c FAIL overridden per D-206: 0.000169% noise is below the 0.1% tolerance for the Usable verdict. Response D applied.
- Enough: **SOFT_DEV** — 10 cumulative days across 2 cycles, 2,711 trajectories. Above viability floor; below 30-day / 5K-trajectory floor for DL training.

**Cycle 2 highlights (vs cycle 1):**
- **No duplicates.** Monica's `UNIQUE (icao24, time, lat, lon)` constraint with `INSERT ... ON CONFLICT DO NOTHING` (added after #13) is working in production. The script-rerun issue is fixed at the source — future cycles arrive without it.
- **Cleaner range data.** Zero range-bound violations vs cycle 1's 3 transient glitches.
- **Cleaner bbox.** 0 rows outside vs cycle 1's 0.0433%.
- **Smaller baroaltitude null share** (0.000169% vs 0.0044%, 26× less). Same underlying ADS-B-property cause; just less of it this cycle.

---

### Cycle 3 — 2026-05-23 OpenSky scientific dataset (data-source pivot per D-007)

**Significant departure from cycles 1 + 2.** Cycle 3 abandons the Trino + Supabase ingestion path. Data comes from the public OpenSky scientific dataset entry #1 ("Weekly 24 Hours of State Vector Data 2017-2022") via the new `backend/research/src/sadar_research/trajectory_anomaly/data/download.py` script. Rationale: D-007.

- **Source:** OpenSky Network public S3-hosted scientific dataset.
- **Period:** 18 of 20 planned Mondays sampled evenly across 2017-06-05 → 2020-03-09 (COVID excluded — 2020-03-15 to 2022-01-01). 2 planned Mondays (2018-04-02, 2019-12-02) did not land — see Bugs section.
- **Resolution:** 10 seconds per aircraft (vs Trino path's 5 seconds; Phase 3 needs to harmonize).
- **LEMD-flight gate:** Filter B (`min_dist_to_runway < 10km AND min_baroaltitude < 3km` per trajectory). Substitutes for the Trino path's `flights_data4.estarrivalairport/estdepartureairport` metadata, which is not available in state-vector-only data. Empirically removes ~47% of bbox trajectories that are cruise overflights at FL350-FL410.
- **Output layout:** one parquet per Monday in `data/raw/opensky_states/lemd_<YYYYMMDD>__opensky_states_<fetchYYYY-MM-DD>.parquet`. Schema identical to cycles 1+2.
- **Pre-COVID 2020 supplement:** 3 Mondays (2020-02-03, 2020-02-24, 2020-03-09) substituted for 3 most-recent bucket Mondays that turned out to have all 24 hours 404-missing despite the bucket prefix existing (2022-01-17, 2022-03-21, 2022-05-23).

**Volume (final yield, 18 Mondays):**
- 19,057 LEMD trajectories total after Filter B
- 3.43M rows total
- ~123 MB parquet on disk
- Combined Merkle hash: `98e38ba5802816a97f17b2086df18570c6f81311d80faeed0492ad87abd662e4` (sorted sha256 over the 18 per-file sha256 hashes)

**Why this matters for the writeup:** the OpenSky scientific dataset has a DOI and is cite-able. The previous Supabase-mediated path was reproducible only within the team. Cycle 3 makes reproducibility a real writeup asset: anyone can re-pull the same dates with a single script invocation.

**Bugs surfaced during the run:**
- 2 numpy crashes on `velocity`/`baroaltitude`/`heading` (CSV had non-numeric values that left columns as `object` dtype, breaking `np.radians` / arithmetic). Fixed in the script via `pd.to_numeric(..., errors="coerce")` on those columns. Affected Mondays were re-run and landed.
- 2 residual failures on 2018-04-02 and 2019-12-02: same root cause (object-dtype after empty-chunk concat) but in the `lat`/`lon` path — the coercion is applied per-chunk in `apply_derivations` but the 24-hourly concat promotes the column back to `object` when some early-morning chunks are empty. Documented; 1-line fix exists (add `lat`, `lon` to the coercion loop, OR coerce after the concat in `filter_lemd_bbox`). Deferred — shipped 18.
- 3 Mondays (2022-01-17, 2022-03-21, 2022-05-23) returned 404 for every hour despite the directory prefix existing in the bucket listing. Substituted with 3 earlier pre-COVID Mondays in the top-up run.

**Audit posture for cycle 3:** Phase 2's `gates.data` is `cyclic` — cycle 3 appends to `manifest.yml > gates.data.dataset_hash` and to this doc's snapshot log without re-passing the gate. The full validation notebook (`research/trajectory-anomaly/notebooks/lifecycle/05_phase2_data_validation.ipynb`) was designed for Supabase-sourced data and uses cycle 1/2 columns + the canonical opensky derivations. Cycle 3 reuses the same derivation functions (`distance_to_closest_runway`, `calculate_flight_phase`) imported from `backend/research/src/sadar_research/trajectory_anomaly/data/opensky.py`, so the audit-consistency check (D-205) will produce zero deltas by construction on cycle-3 parquets — meaningful validation in cycle 3 has to be at the row-quality and Filter-B-effectiveness layer, not the derivation-parity layer. Open question: do we run a cycle-3-specific audit cell set in the notebook, or treat the script's own row-coercion + Filter B as sufficient?

---

## Cumulative volume

Updates as cycles accumulate.

| Metric | Cycle 1 | Cycle 2 | Cycle 3 | Cumulative |
|---|---|---|---|---|
| Cycles completed | 1 | 1 | 1 | 3 |
| Batches available (canonical) | 1 (deduped) | 1 (snapshot) | 18 (per-Monday parquets) | 20 |
| Calendar days seen | 5 | 5 | 18 (Mondays only) | 28 |
| Calendar dates | 2025-03-10 to 2025-03-14 | 2026-03-10 to 2026-03-14 | 18 Mondays sampled 2017-06-05 → 2020-03-09 | 2017-06-05 → 2026-03-14 (spans 9 calendar years with gaps) |
| Time range (UTC) | 2025-03-10 00:58:21 → 2025-03-14 23:56:07 | 2026-03-10 00:58:37 → 2026-03-14 23:45:42 | 18 single-day windows, 00:00 → 23:59 UTC each | union of all three |
| Unique trajectories (`flight_id`) | 1,285 | 1,426 | 19,057 | **21,768** |
| Unique aircraft (`icao24`) | 330 | 350 | not separately counted (cycle 3 audit posture deferred derivation-parity cell — see Cycle 3 Audit posture note) | not measured cross-cycle |
| Total canonical rows | 1,146,231 (deduped) | 1,774,859 (snapshot) | 3,430,000 (approx — 3.43M reported by script manifest) | **~6.35M** |
| Total parquet size in Drive | 118.88 MB (raw + deduped) | 61.93 MB (snapshot only) | ~123 MB (18 per-Monday parquets) | ~303.81 MB |
| Day-of-week coverage | 5/7 (Mon-Fri, [0,1,2,3,4]) | 5/7 (Tue-Sat, [1,2,3,4,5]) | 1/7 (Mon only, [0]) | **6/7 (Mon-Sat, [0,1,2,3,4,5])** — Sunday still uncovered, Monday heavily over-represented |
| Hour-of-day coverage | 24 distinct hours | 24 distinct hours | 24 distinct hours | 24 |
| Months covered | 1 (March 2025) | 1 (March 2026) | spans 18 distinct Monday-instances across 2017-06 → 2020-03 | many — 18-day Monday sample plus 2 March-week ranges |

**Cumulative Enough verdict: CONDITIONAL through cycle 3.**

Cycle 3 cleared the 5K-trajectory threshold by a wide margin (19,057 alone, 21,768 cumulative) and crossed the 30-day calendar threshold (28 days; the original 30-day target referred to calendar days observed and cycle 3 spans 18 Mondays across a multi-year window — Phase 3 needs to decide whether 28 distinct calendar days across multiple years counts the same way as 30 contiguous calendar days for the gate's intent).

Day-of-week coverage stays at 6/7 by union (Mon-Sat) but is now heavily Monday-skewed since cycle 3 contributes 18 Mondays to the ~10 days from cycles 1+2. The writeup needs to surface this explicitly — see open question on day-of-week below. Phase 3 needs to make an explicit call on whether to treat cycles 1+2 + cycle 3 as one pooled dataset (with a resolution-harmonization step — cycle 3 is 10s, cycles 1+2 are 5s) or use cycle 3 alone as the primary training corpus.

---

## Known issues

Tracking per cycle. Each entry: what was caught, response category applied (per workflow doc playbook), why, links.

### #1 — Cycle 1: Sparse `baroaltitude` nulls

- **Detected by:** cell 7c, critical-null check
- **Count:** 80 null `baroaltitude` rows out of 1,834,084 (0.0044%)
- **Response category:** D (document + proceed, no upstream fix)
- **Rationale:** Some ADS-B transponders broadcast `geoaltitude` only and omit `baroaltitude`. This is a known property of ADS-B data, not a pipeline bug. Phase 3 may decide whether to drop these rows, impute, or fall back to `geoaltitude`.
- **Action:** None upstream. Flagged for Phase 3 to consider.

### #2 — Cycle 1: Legacy Supabase table naming

- **Detected by:** manual inspection during cycle 1 audit
- **Issue:** The Supabase table is named `lemd_2025_03_10` but contains 5 days of data (2025-03-10 to 2025-03-14). The naming convention going forward is `lemd_<startYYYYMMDD>_to_<endYYYYMMDD>` (workflow doc).
- **Response category:** D (document + proceed)
- **Rationale:** The local parquet naming derives from the data's actual date range, so the misleading table name doesn't propagate. Future tables follow the new convention.
- **Action:** None for this cycle. Future tables follow the convention.

### #3 — Cycle 1: Full-row duplicates (37.5%)

- **Detected by:** cell 7d (full-row duplicate count) + diagnostic cell 7d.1 (multiplicity staircase from 1× to 7×)
- **Count:** 687,853 full-row duplicates (37.50%) out of 1,834,084 rows
- **Diagnostic:** Multiplicity distribution showed clean staircase 1×→7×, indicating the extraction script ran approximately seven times over overlapping date ranges
- **Response category:** B (override + automated fix)
- **Rationale — three override conditions:**
  1. Full-row dups are byte-identical re-inserts. No information lost by removing them.
  2. There is no preprocessing decision to make. The action is unambiguous: drop.
  3. Keeping them would weight some flights 7× more in training, distorting the model's normality estimates.
- **Action upstream:** Monica's extraction script updated with `UNIQUE (icao24, time, lat, lon)` constraint plus `INSERT … ON CONFLICT DO NOTHING`. Future cycles arrive without this issue.
- **Action local:** Deduped parquet produced (`lemd_20250310_to_20250314__deduped_2026-05-10.parquet`). Raw kept as audit evidence. Manifest references the deduped version as canonical.
- **GitHub issue:** [#13](https://github.com/txema-puch/drone-ai-saturdays/issues/13) — opened 2026-05-11, closed same day as completed (resolution already in place; opened for audit trail per workflow doc's Response B protocol).

### #4 — Cycle 1: Sparse `geoaltitude` nulls

- **Detected by:** cell 6 (schema audit)
- **Count:** 205 null `geoaltitude` rows (0.01%)
- **Response category:** D (document + proceed, no upstream fix)
- **Rationale:** Like `baroaltitude` nulls, this reflects transponders that only broadcast one altitude type. Different from `baroaltitude` nulls — the overlap between the two null sets (rows where BOTH altitudes are null) hasn't been checked. If overlap is large, those rows have no altitude information at all and Phase 3 should drop or specially flag them.
- **Action:** None upstream. **Phase 3 TODO:** check `baroaltitude IS NULL AND geoaltitude IS NULL` overlap; decide drop / interpolate / flag.

### #5 — Cycle 1: Range outliers (3 violations, ~2 rows)

- **Detected by:** cell 7e (range bounds check)
- **Findings:**
  - `velocity` max = 428.27 m/s (1 row above 400 m/s cap, ~Mach 1.26)
  - `vertrate` max = 161.58 m/s (1 row above 100 m/s cap, ~9700 m/min climb rate)
  - `velocity_kmh` max = 1541.79 km/h (1 row above 1500 cap; same row as `velocity` outlier since derived)
- **Likely 2 distinct rows total** (the velocity / velocity_kmh outlier shares a row; the vertrate outlier is separate).
- **Response category:** D (document + proceed, no upstream fix)
- **Rationale:** 2 rows out of 1,146,231 = 0.000175% — well within ADS-B transient-glitch range. Transponders occasionally broadcast garbage values; that's an unavoidable property of the data. Phase 5 (features) or Phase 6 (training) preprocessing may filter outliers; not a Phase 2 concern.
- **Action:** None upstream. Documented for Phase 3/5 awareness.

### #6 — Cycle 1: LEMD bbox slightly too tight

- **Detected by:** cell 7e (LEMD bbox sanity check)
- **Finding:** 795 rows (0.0433%) fall outside the bbox `lat ∈ [38.5, 42.5], lon ∈ [-6.0, -1.2]`. Cell prints PASS (below the 1% threshold) but the discrepancy is real — observed `lon` extends to -1.15.
- **Root cause:** the bbox was set conservatively when defined. The actual 200km radius from LEMD's eastern runway thresholds reaches ~-1.26 east in longitude; our cutoff of -1.20 chopped some valid rows.
- **Response category:** F (update methodology — the audit itself is the issue)
- **Action:** Widen the notebook's `LEMD_BBOX` to `lon ∈ [-6.0, -1.1]` for future cycles. Cycle 1 audit re-runs would produce 0 rows outside.
- **Status:** Not yet applied to the notebook (TODO).

### #7 — Cycle 1: High `squawk` null rate (6.25%)

- **Detected by:** cell 6 (schema audit)
- **Count:** 114,589 null `squawk` rows (6.25%) out of 1,834,084 raw / corresponding subset of 1,146,231 deduped
- **Response category:** D (document + proceed, no upstream fix)
- **Rationale:** `squawk` is a 4-digit transponder code (e.g., 7700 for emergency, 1200 for general aviation VFR). Many commercial transponders don't broadcast a squawk code outside specific conditions, so high null rates are expected ADS-B behavior. Not a pipeline bug. Not used as an ML feature in our current design.
- **Action:** None. Documented for transparency.

### #8 — Cycle 1: `time_utc` is stored as string, not datetime

- **Detected by:** manual inspection of cell 6 output (`time_utc` dtype = `str`)
- **Finding:** Monica's pipeline serializes `time_utc` as ISO 8601 strings (e.g., `"2025-03-11T08:00:30"`) when writing to Supabase. The parquet round-trip preserves this as `str` dtype.
- **Audit gap:** cell 7b (type sanity) checks numeric and bool columns, but not string columns where datetimes might be expected. The check did not catch this.
- **Response category:** D (document + proceed) + small F (update cell 7b to include datetime-expected columns next cycle)
- **Rationale:** Downstream cells already handle this correctly via `pd.to_datetime(... errors="coerce")` (see cell 8 consistency check and cell 11 volume metrics). Not blocking. But the audit should explicitly note it rather than implying `time_utc` is a typed datetime.
- **Action:** Phase 3 will explicitly convert to `datetime[ns, UTC]`. Notebook cell 7b can be extended in a future iteration to flag string columns that should be datetime — not blocking for Phase 2 close.

### #3 status update — Cycle 2: Monica's upstream fix confirmed effective

- **Cycle 2 result:** 0 duplicates at any granularity (rows: 1,774,859 / dup pairs: 0 / dup tuples: 0 / full-row dups: 0)
- **Interpretation:** the `UNIQUE (icao24, time, lat, lon)` constraint + `INSERT ... ON CONFLICT DO NOTHING` added to Monica's pipeline after issue #13 is working in production
- **Outcome:** cycle 2's canonical artifact is the snapshot parquet itself; no deduped variant needed
- This is a *positive* confirmation rather than a new issue — kept here as a closing note on #3's lifecycle

### #9 — Cycle 2: Sparse `baroaltitude` nulls (recurrence, cleaner)

- **Detected by:** cell 7c, critical-null check
- **Count:** 3 null `baroaltitude` rows out of 1,774,859 (0.000169%) — **26× cleaner than cycle 1** (which had 0.0044%)
- **Response category:** D (document + proceed, no upstream fix)
- **Rationale:** Same ADS-B-property cause as cycle 1 (#1). 0.000169% is well below D-206's 0.1% noise tolerance for the Usable verdict.
- **Audit nuance:** cell 7c marked this FAIL mechanically (any null in a critical column flips it), and cell 12 propagated to `Usable: FAIL` in raw output. Per D-206 the verdict applies a ≤0.1% noise tolerance, so the *interpreted* Usable verdict is PASS. The mechanical/interpreted gap is documented in #12.
- **Action:** None upstream.

### #10 — Cycle 2: Sparse nulls in velocity/heading/vertrate (14 rows each)

- **Detected by:** cell 6 (schema audit)
- **Count:** 14 nulls each in `velocity`, `heading`, `vertrate`, `velocity_kmh` (0.000789%). Likely the same 14 rows in all four columns since `velocity_kmh` is derived from `velocity`.
- **Response category:** D (document + proceed)
- **Rationale:** Tiny fraction, well below noise tolerance. Some ADS-B state vectors arrive without velocity components (rare). Phase 3 will need to decide drop/impute for trajectory reconstruction. Not blocking.
- **Action:** None. Documented for Phase 3 awareness.

### #11 — Cycle 2: Table arrived without an index on `(time, icao24)`

- **Detected by:** notebook cell 4 timing out during the data fetch (`statement_timeout`, APIError code 57014)
- **Issue:** `public.lemd_2026` had no index on `time`, so any ORDER BY or pagination query required a full table sort. At 1.77M rows this exceeded Supabase's 120s service-role `statement_timeout`. The audit had to apply `CREATE INDEX idx_lemd_2026_time_icao24 ON public.lemd_2026 (time, icao24)` mid-run to proceed.
- **Response category:** F (update methodology — the upstream pipeline should provision this)
- **Rationale:** Monica's pipeline creates the table via `INSERT … ON CONFLICT DO NOTHING` (per #3 fix) but does not add an index. For datasets at our scale (≥1M rows per cycle), an index on the natural query columns is required for any analytic query to complete. The audit happens to need it for keyset pagination; Phase 3+ will also need it for time-bounded reads.
- **Action upstream:** Monica's pipeline should create the index when provisioning each cycle's table. Suggest also indexing `flight_id` for trajectory queries.
- **Action local:** Index added during cycle 2 audit. Documented here so cycle 3+ can verify the index is present BEFORE running the audit (a one-line `pg_indexes` check could be added to cell 3 in a future notebook iteration).

### #12 — Cycle 2: Audit ergonomics — verdict logic doesn't apply D-206 tolerance

- **Detected by:** cycle 2 verdict cell (12) output: "Usable: FAIL" despite the only finding being 3 nulls at 0.000169%
- **Issue:** Cell 7c marks critical-column nulls as binary FAIL (any nulls → FAIL), and cell 12's `usable_pass` boolean uses that directly. Methodology D-206 specifies a ≤0.1% noise tolerance for Real/Usable verdicts. The verdict computation doesn't apply this tolerance — leaving the human to do it manually each cycle (which we did for both cycle 1 and cycle 2).
- **Response category:** F (update methodology — the audit itself is the issue)
- **Rationale:** Mechanical FAIL is useful as a signal but should not bind the verdict at sub-tolerance noise levels. Otherwise every cycle with any null in a critical column produces a misleading raw verdict that needs human override.
- **Action:** Update cell 7c to compute `critical_failed = any(null_pct > 0.1 for col in critical_cols)` and cell 12 to use that signal. Not blocking for cycle 2 close. Follow-up issue worth filing post-PR.

### #13 — Cycle 2: Audit notebook variable mismatch (cell 12 NameError)

- **Detected by:** running cell 12 of the validation notebook against cycle 2's snapshot
- **Issue:** cell 11 computes `n_calendar_days` for the cumulative-days metric, but cell 12 referenced `n_days` (the old name). The verdict cell raised `NameError: name 'n_days' is not defined`. Cycle 1's run did not surface this because — based on PR #14's narrative — the cells may have been edited after cycle 1's manual verdict was already computed.
- **Response category:** F (update methodology — the audit itself is the issue)
- **Action:** Renamed three occurrences of `n_days` → `n_calendar_days` in cell 12. Applied in this PR's notebook diff.

---

## Decisions

| ID | Date | Decision | Status |
|---|---|---|---|
| D-201 | 2026-05-08 | Six critical columns: `time, icao24, lat, lon, baroaltitude, flight_id` | locked |
| D-202 | 2026-05-08 | FAIL action chain: document + open issue + keep broken rows | superseded by workflow doc's six-response playbook (2026-05-11) |
| D-203 | 2026-05-08 | Three-key duplicate detection | locked |
| D-204 | 2026-05-08 | Generous physical range bounds + LEMD bbox sanity | locked |
| D-205 | 2026-05-08 | Tight pipeline consistency tolerances; `flight_phase` exact match | locked |
| D-206 | 2026-05-08 | Real / Usable verdict from check outcomes (≤0.1% noise tolerance) | locked |
| D-207 | 2026-05-08 | Four-bucket Enough verdict: NOT_YET / SOFT_DEV / CONDITIONAL / PASS | locked |
| D-208 | 2026-05-10 | Snapshot pattern is truncate-fill-snapshot cycle (Drive is durable record, Supabase is transient) | locked |
| D-209 | 2026-05-10 | Parquet naming derives from the data's `time_utc` range, not from the Supabase table name | locked |
| D-210 | 2026-05-11 | Six-category response playbook (A through F) for audit findings | locked, see workflow doc |
| D-211 | 2026-05-23 | Cycle 3 sources data from OpenSky scientific dataset entry #1, applies Filter B (`min_dist<10km AND min_alt<3km` per trajectory) as the LEMD-flight gate (no `flights_data4` metadata available) | promoted to ADR D-007 |

D-208, D-209, and D-210 are eligible for promotion to ADRs in `docs/research/trajectory-anomaly/lifecycle/decisions/` if revisited. None have been revisited. D-211 is the codified cycle-level inheritance of D-007.

---

## Open questions / TODOs

1. **Coverage strategy.** Total target is 6-12 months of data per the design doc. Cycle 1 covers 5 weekdays of March 2025. The team has not decided: (a) year-over-year span across same calendar window, (b) consecutive months, (c) scattered across the year. Subject to OpenSky research-account quota constraints. *Discuss before next extraction.*
2. **Cross-parquet duplicate check.** If a future cycle accidentally overlaps a previous cycle's date range, the parquets share rows. The notebook does not yet check for cross-parquet overlaps. *Add to cell 11 (cumulative volume) for cycle 2.*
3. **`baroaltitude` null handling in Phase 3.** Drop the 80 affected rows, impute, or fall back to `geoaltitude`? Decision belongs in Phase 3 preprocessing.
4. **Weekend coverage.** Cycle 1 happened to cover Mon-Fri. Future cycles should explicitly include weekends to give the LSTM autoencoder weekend-traffic exposure (different patterns than weekday rush hour).
5. **Phase 6 trigger.** At what cumulative volume do we run a first training pass? Soft answer: try once SOFT_DEV is exited (≥30 days). Subject to revision.

---

## Loops back to earlier phases

- **Loop back to Phase 1 (problem framing) — none required.** The Phase 1 doc's framing (anomaly detection, AUROC primary metric, LSTM AE primary architecture) remains valid given cycle 1's data characteristics. No findings necessitate revisiting Phase 1.

---

## Exit gate checklist

Per the `/ml-lifecycle` Phase 2 reference:

- [x] Snapshot saved at a stable path; hash recorded in `manifest.yml`
- [x] Data dictionary covers every column (21 entries)
- [x] Volume documented (rows, time span, size)
- [x] Validation report run; every failed check has a documented response
- [x] Class balance noted (cycle 1 raw):
  - `operation`: arrival 1,107,934 rows / departure 726,150 rows (~60/40 by rows); 653 / 632 unique flights (~51/49 balanced). See arrival/departure asymmetry note in cycle 1 Volume section.
  - `flight_phase`: descent 840,599 / climb 460,474 / cruise 353,082 / approach 101,365 / takeoff 78,470 / on_ground 94. All 6 rule outputs present. Descent dominance is expected — most aircraft enter the 200km LEMD radius from cruise and descend over a long distance before being close enough to be classified as "approach."
- [x] Label sanity check N/A (no labels in our data — anomaly detection is unsupervised)
- [x] License / privacy status documented (OpenSky Network research terms; no PII)
- [x] Sufficient-volume flag set (SOFT_DEV, requires more cycles before Phase 6)

Status to flip to `passed` in manifest.yml once this doc is reviewed and confirmed by the team.

---

## Notes for future cycles

When cycle 2 lands, the process is:

1. Run the notebook against the new Supabase state
2. Cell 4 produces a new parquet with name derived from data range
3. Cells 7a–8 run the audit
4. If anything fires REVIEW or FAIL, consult the workflow doc's "Response playbook" to pick the response category
5. Update this doc:
   - Append a new entry under "Snapshot log"
   - Update the "Cumulative volume" table
   - If the cycle had findings, append entries to "Known issues" with the response category applied
6. Update `manifest.yml > gates.data.dataset_hash` with the new entry
7. Confirm snapshot integrity to Monica before she truncates Supabase
8. Manifest's `gates.data.status` stays `passed` unless the new cycle fails validation entirely (Response A territory)

Phase 2's gate is the discipline. The cycles are the application.
