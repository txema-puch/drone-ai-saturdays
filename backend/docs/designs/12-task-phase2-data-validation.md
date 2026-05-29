# Design: Phase 2 — validate Supabase lemd_* data

> **Work item:** [#12](https://github.com/txema-puch/drone-ai-saturdays/issues/12)
> **Backend:** github_project
> **Branch:** `12-task-phase2-data-validation` (stacked on `10-task-close-phase1-prepare-eda`)
> **Date:** 2026-05-07
> **Author:** Txema (with Claude `/develop` + `/ml-lifecycle`)

## Problem (Why)

Phase 1 (problem framing) is closed. Phase 6 (training) cannot start without
a validated dataset, and any preprocessing decisions in Phase 3 depend on
knowing what's actually in the data. Monica produced the data via
`backend/scripts/export_lemd_2025_sample.py` (which depends on
`backend/crud/opensky.py`) and uploaded to Supabase tables named
`lemd_YYYY_MM_DD`. We have not yet inspected what arrived. Without that
inspection, downstream work would build on an unvalidated foundation.

Important: Monica's pipeline is **not a raw passthrough of OpenSky data** —
it applies a 200km LEMD radius filter and computes six derived columns
(see "Data lineage" below). Phase 2 must therefore validate the *delivered*
schema and document the upstream transformations so future phases know what
is already done and what is not.

This ticket closes Phase 2 (Data) per `/ml-lifecycle`. Phase 3 (Preprocess)
and Phase 4 (EDA) are deliberately *not* in scope here — they follow as
separate tickets.

## Data lineage (upstream of Phase 2)

What Monica's pipeline does before we receive the data:

```
OpenSky Trino flights_data4 + state_vectors_data4
        │
        │  Trino query (backend/crud/opensky.py:OpenSkyService)
        │   - Filter: estarrivalairport='LEMD' OR estdepartureairport='LEMD'
        │   - Per state-vector: time - lastcontact <= 15 (drop stale)
        ▼
15 raw state-vector columns:
  time, icao24, lat, lon, baroaltitude, geoaltitude, velocity, heading,
  vertrate, callsign, onground, squawk, alert, spi, lastcontact
        │
        │  build_master_table (backend/crud/opensky.py)
        │   - Drop rows with dist_to_runway_m > 200 km (MAX_RADIUS_M)
        │   - Add flight_id      = "{icao24}_{firstseen}"
        │   - Add operation      = arrival|departure|unknown
        │   - Add time_utc       = ISO datetime from epoch
        │   - Add velocity_kmh   = velocity * 3.6
        │   - Add dist_to_runway_m = haversine to closest of 8 LEMD runways
        │   - Add flight_phase   = rule-based classification (see below)
        ▼
21 columns delivered to Supabase tables `lemd_YYYY_MM_DD`
```

### `flight_phase` is rule-based, not labeled

Critical point for our anomaly-detection framing: `flight_phase` is **not a
label from any external truth**. It is computed deterministically from
`onground`, `baroaltitude`, `vertrate`, and `dist_to_runway_m` per the
`calculate_flight_phase` function. The rule (paraphrased):

| Phase | Condition |
|---|---|
| `on_ground` | `onground == True` OR `baroaltitude < 50 m` |
| `takeoff` | `vertrate > 3 m/s` AND `baroaltitude < 3000 m` |
| `climb` | `vertrate > 1 m/s` (else previous matched) |
| `approach` | `vertrate ≤ -1 m/s` AND `baroaltitude < 3000 m` AND `dist_to_runway_m < 20 km` |
| `descent` | `vertrate < -1 m/s` (else previous matched) |
| `cruise` | otherwise (default) |

Because the rule is deterministic, we can **trust** flight_phase as a derived
feature — but we must NOT treat it as ground truth for anything. It cannot be
"correct" or "incorrect" beyond whether the rule itself is appropriate.

### Phase 3 work already done upstream

Three of the six derived columns are arguably Phase 3 (preprocess) work that
Monica's pipeline already did:

- **`velocity_kmh`** — unit conversion (Phase 3-style)
- **`dist_to_runway_m`** — feature engineering: haversine to nearest runway
  threshold (Phase 5-style, but spatial-only)
- **`flight_phase`** — feature engineering: rule-based classification
  (Phase 5-style)

Phase 3 will need to decide whether to accept these as-is or re-derive them
in a reproducible pipeline of our own. That decision is **out of scope here**;
flag and defer.

## Working with the upstream pipeline

Monica's pipeline is a starting point, **not a fixed contract**. Phase 2
validation is also an opportunity to identify gaps or corrections needed at
the source.

Three kinds of findings can arise during validation:

| Finding | Response |
|---|---|
| **Schema matches expectations + data is sane** | Accept. Document in `02-data.md`. Move on. |
| **Bug / inconsistency** — e.g., `flight_phase` rule misclassifies a clear case, range violations that indicate a unit error, systematic null patterns suggesting a Trino query issue, duplicate rows pointing at a re-run bug | Surface to Monica. Agree on a fix. Update upstream code. Re-run the export. Re-snapshot. |
| **Gap / missing feature** — e.g., we need additional state-vector columns from OpenSky, more days, the radius filter should be wider/narrower, the per-day windowing missed boundary flights | Same protocol: surface, agree, update upstream, re-run. |

**Phase 2 does not silently accept whatever arrived.** If validation reveals
the pipeline produced something incorrect or insufficient, the right answer
is to fix the pipeline, not to work around it downstream. The accept-or-
rederive question (Open question 5) is about *reproducibility of derivations*,
not absolution of upstream errors.

**Coordination protocol with Monica:**

- Surface findings as comments on the corresponding GitHub issue/PR, or open
  a new issue with a clear title (e.g., `[Bug]: flight_phase rule misclassifies
  helicopters as on_ground`).
- Monica owns the upstream pipeline; we (this ticket) own validation.
- Pull requests to `backend/crud/opensky.py` or
  `backend/scripts/export_lemd_2025_sample.py` go through normal review.
- For non-trivial pipeline changes, batch them — don't ask for a re-export
  every time we find one issue. Accumulate, then propose a coordinated update.

This stance applies even to the snapshot and hash. If we re-export, the hash
changes; we update the manifest accordingly. Snapshot integrity is about
auditability of *what was used*, not immutability of *what was produced*.

## Scope (What)

### In scope

- Source documentation (Supabase project, table naming, access path)
- Volume per available day (rows, time range, unique flights, storage size)
- Schema dictionary for all 21 columns (name, type, unit, range, null
  policy, notes)
- Validation report (schema match, type, null, duplicate, range,
  distribution sanity)
- Class balance (arrival/departure split, flight_phase distribution)
- Local snapshot of the data with sha256 hash
- License / OpenSky ToS documentation
- `backend/docs/ml/02-data.md` filled in
- Manifest update: `gates.data.status = passed`, `dataset_hash` recorded

### Out of scope (deferred to later phases)

- Trajectory segmentation, resampling, scaling — Phase 3 (Preprocess), Week 2
- Distribution patterns, correlations, ≥5 substantive insights — Phase 4 (EDA), Week 2-3
- Feature engineering — Phase 5
- Train/val/test split definition — Phase 6
- Anomaly injection — Phase 6+

## User experience

Internal-facing only. No UI. The "users" are the four team members. By the
end of this ticket, anyone on the team can read `02-data.md` in 10 minutes
and know:

- Exactly what's in the Supabase tables (schema, ranges, nulls)
- How much data there is (rows, days, flights)
- What's been validated and what failed
- Where the snapshot lives and how to verify its integrity

## Buy-vs-build scan

Skipped per `/develop`'s scan-trigger rules. Size is S (1–2 days of
validation work). Domain (data validation) is not in the trigger list (auth,
payments, comms, AI/LLM, search, scheduling, file/media, notifications,
OCR, geolocation, sensors/IoT, infra).

For completeness, options briefly considered:

| Option | Why not |
|---|---|
| Great Expectations / Pandera | Heavyweight for 21 columns; learning-curve cost > benefit at this scale |
| Pydantic schema validation only | Catches schema, not null/dup/range issues |
| Custom pandas + assertion checks | What we'll use — simple, readable, no new deps |

## Engineering plan

### Architecture

A short-running validation notebook (canonical workspace per the team
convention: top-level `notebooks/`), backed by a small helper module if any
function is reused across days.

```
notebooks/
  05_phase2_data_validation.ipynb   ← the validation walkthrough

backend/scripts/
  fetch_supabase_lemd.py            ← optional: thin reusable helper
                                       to discover + load lemd_* tables

data/
  raw/
    lemd-2025-03-11.parquet         ← snapshot for the day Monica ran
    (additional days as available)
```

The notebook does the validation work step-by-step (so the team can read
the reasoning); the script (if extracted) wraps the loader so reruns are
clean. Default to notebook-only unless a function is reused.

### Steps

1. **Connect** — load Supabase URL + key from `.env`, verify connectivity.
2. **Discover** — probe candidate `lemd_YYYY_MM_DD` table names and list
   which exist. Document Monica's reported coverage. (As of writing,
   `lemd_2025_03_11` is the only known day, since `export_lemd_2025_sample.py`
   has `DIA = datetime(2025, 3, 11)` hardcoded.)
3. **Pull snapshot** — for each available day, pull the full table to
   `data/raw/lemd-YYYY-MM-DD.parquet`. Use Supabase pagination (1000-row
   default page).
4. **Schema audit** — for each column: type, null count, unique values
   (if low cardinality), range (if numeric), one-line definition. Mark
   each as **raw** (15 columns from OpenSky) or **derived** (6 columns
   added by Monica's pipeline) — see Data lineage above.
5. **Validation checks** — run programmatic assertions:
   - Schema match (column names + types as documented in design doc)
   - Type sanity (no string-as-numeric, no NaN-as-string sentinels)
   - Null check per column (counts, interpretation)
   - Duplicate check (`flight_id` + `time` as composite key)
   - Range check (lat ∈ [-90,90], lon ∈ [-180,180], altitude ≥ 0,
     velocity ≥ 0, heading ∈ [0,360])
   - **Pipeline consistency check**: re-derive `velocity_kmh`,
     `dist_to_runway_m`, and `flight_phase` from raw columns and verify
     they match Monica's values (within float tolerance). Catches any
     pipeline drift or version skew.
   - Distribution sanity (per-feature histogram — sanity only,
     deeper EDA is Phase 4)
6. **Class balance** — count `operation` (arrival/departure/unknown) and
   `flight_phase` (on_ground/takeoff/climb/cruise/approach/descent).
   Note imbalance for downstream awareness.
7. **Snapshot hash** — compute sha256 of each parquet file; record in
   `manifest.yml > gates.data.dataset_hash` (use a list/dict if multiple days).
8. **Write `02-data.md`** — fill in every section from the Phase 2
   template (`/ml-lifecycle/references/docs-template.md`). Include the
   data lineage diagram so the team understands what Monica's pipeline
   does and where Phase 2 validation begins.
9. **Update manifest** — flip `gates.data.status` to `passed`, record
   `passed_at`, point `artifact` at `02-data.md`, record `dataset_hash`.
10. **Commit + PR** — close issue #12 via PR.

### Dependencies

All in `backend/pyproject.toml` already (added in PR #11):
`supabase`, `pandas`, `matplotlib`, `python-dotenv`, `ipykernel`, plus
`pyarrow` (transitive via pandas/parquet support) — verify the parquet
write works; if not, add `pyarrow` explicitly.

### Effort estimate

~1 working day. Single contributor. No coordination dependency on others.

## AI lifecycle plan

### Phase 2 entry gate (ml-lifecycle)

- ✅ Phase 1 passed (committed in PR #11)
- ✅ `model_track` set tentatively to `dl`
- ✅ `manifest.yml > current_phase` is `data`
- ✅ `gates.data.status` is `in_progress`

### Phase 2 work-in-flight

- Validate without modeling. No predictions, no training.
- Test-set firewall not yet active (test set defined at Phase 6 entry).
  But: be careful what insights we draw — patterns we notice now can
  bias future modeling decisions. Document distributions only;
  defer interpretation to Phase 4 EDA.

### Phase 2 exit gate (ml-lifecycle exit checklist)

- [ ] Snapshot saved at stable path; hash recorded in `manifest.yml`
- [ ] Data dictionary in `02-data.md` covers every column (21)
- [ ] Volume documented (rows, time span, size)
- [ ] Validation report run; every failed check has a documented response
- [ ] Class balance noted (relevant for anomaly detection framing)
- [ ] Label sanity not applicable (no labels in our data — anomaly
      detection is unsupervised)
- [ ] License / privacy status documented (OpenSky research-account terms)
- [ ] Sufficient-volume check (will the data support DL training?)

### Phase advance

On exit gate pass: flip `manifest.yml > gates.data.status` to `passed` and
`current_phase` to `preprocess`. Phase 3 (Preprocess) gets its own ticket.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Skip Phase 2, jump straight to EDA / training | Violates `/ml-lifecycle` ordering; risks discovering data issues during modeling, when they're 10× more expensive to address |
| Validate only one day of data | Risks missing day-to-day variability or pipeline drift |
| Skip snapshot, work directly off Supabase | Violates Phase 2's "lock a snapshot" rule; Supabase contents can change |
| Heavy validation framework (Great Expectations) | Overkill for 21 columns; adds dependency weight + learning curve |

## ADRs created or referenced

- **Referenced:** [D-001 — anomaly detection framing](../ml/decisions/D-001-anomaly-vs-classification.md) — confirms unsupervised framing, so no label sanity check needed
- **No new ADRs anticipated.** If schema validation surfaces unexpected
  issues (e.g., systematic null patterns suggesting a pipeline bug),
  raise an ADR at that point.

## Open questions

1. **Snapshot scope.** All days Monica has uploaded, or a representative
   sample? Decision: pull all available days for the snapshot, since the
   total volume is likely <1GB per day and we want to detect cross-day
   issues. Revisit if snapshot grows to >10GB.
2. **Re-validation cadence.** When Monica adds new days, do we re-run
   Phase 2? Decision: not blocking for this ticket. Open a follow-up if
   new days arrive after Phase 2 is closed; for now, snapshot the current
   contents.
3. **OpenSky redistribution rights.** Research account ToS likely
   restricts redistribution. Need to confirm before publishing the
   snapshot anywhere public. Document in `02-data.md`. Does NOT block
   internal use for the project.
4. **Sufficient-volume sanity.** If Monica has only 1-2 days uploaded so
   far, that may not be enough for a DL anomaly model. Surface this in
   `02-data.md` as a flag, recommend pulling more days if low.
5. **Accept-or-rederive (Phase 3 decision, surfaced here).** Monica's
   pipeline produces three Phase-3-style columns: `velocity_kmh`,
   `dist_to_runway_m`, `flight_phase`. We can either accept them as-is
   (faster, but less reproducible) or re-derive them in our own pipeline
   (slower, but our preprocessing is auditable end-to-end from raw).
   The Phase 2 consistency check (step 5 in Engineering plan) verifies
   they agree with re-derivation, so accepting them later is safe. **The
   final accept-or-rederive choice belongs in Phase 3** and will be
   logged as an ADR there.
6. **Coverage of `lemd_*` tables vs the export script.** The hardcoded
   `DIA = datetime(2025, 3, 11)` in `export_lemd_2025_sample.py` suggests
   only one day exists today. Confirm with Monica: is this a one-off
   sample or has she been re-running the script with different `DIA`
   values? If only one day exists, flag insufficient volume and recommend
   running the script for additional days before Phase 6.

## Implementation notes for Build phase

- Don't fit any preprocessing in Phase 2 — fitting is a Phase 6 / Phase 3
  pipeline activity (Guardrail #5: fit on train, transform everywhere).
  Phase 2 only describes the data; it does not transform it.
- Save the validation script's outputs (figures, summary tables) under
  `backend/docs/ml/figures/02-data/` so `02-data.md` can reference them.
- Commit messages should follow the team convention: `docs(ml): ...` for
  documentation, `feat(scripts): ...` for the helper script if added.
