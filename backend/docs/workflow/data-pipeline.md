# Data pipeline workflow

How raw ADS-B data gets from OpenSky to a validated parquet snapshot the
team can use. Documents who does what, what artifacts get produced, and
how naming + tracking work across multiple extractions.

> Last updated: 2026-05-23. Owners: data pipeline (Monica, Trino+Supabase
> path) and Txema (OpenSky scientific path), validation (Txema), pipeline
> coordination (whole team). Updates require a PR against this file with
> at least one reviewer from outside the change author.

> **Two ingestion paths in service as of cycle 3:**
> - **Trino + Supabase path** (original, cycles 1-2): described in
>   sections below. Monica owns. Lower latency (5s) but human-side
>   bottleneck for cycle scheduling.
> - **OpenSky scientific dataset path** (new, cycle 3+, see D-007):
>   `backend/scripts/download_opensky_states.py` pulls public S3 data
>   directly with no credentials. Higher latency (10s) but no
>   coordination cost. See "Alternative path" section below.

---

## End-to-end data flow

The pipeline runs in **cycles**, driven by Supabase's free-tier 500 MB
storage limit. Each cycle produces one canonical parquet snapshot in
Drive. Together, the parquets accumulate the full training dataset.

```
   OpenSky Network (historical archive, Trino)
                │
                │  query via pyopensky + Trino client
                ▼
   backend/scripts/export_lemd_2025_sample.py    ← Monica
                │  applies 200km LEMD radius filter
                │  derives flight_id, operation, time_utc, ...
                ▼
   Supabase (a single working table — accumulates rows
             across multiple extraction passes; unique
             constraint prevents within-cycle duplicates)
                │
                │  Monica runs script repeatedly, adding new ranges
                │  Continues until ~400-500 MB used in Supabase
                │  Notifies Txema: "ready to snapshot"
                ▼
   notebooks/05_phase2_data_validation.ipynb     ← Txema
                │  pulls everything currently in the Supabase table
                │  derives date range from the data itself
                │  runs 7-decision audit
                ▼
   data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__snapshot_<YYYY-MM-DD>.parquet
   data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__deduped_<YYYY-MM-DD>.parquet  (only if needed)
                │
                │  upload to Drive with .sha256 sidecars
                │  update manifest.yml > gates.data.dataset_hash
                │  Txema confirms to Monica: "snapshot safe in Drive"
                ▼
   Monica TRUNCATEs the Supabase table → cycle restarts
                │
                ▼
   data/raw/ accumulates one canonical parquet per cycle.
   Union of all parquets = full training dataset.
                │
                ▼
   Phase 3+ (Preprocess, EDA, Train) load from local parquets
                │  (parquets are the source of truth; Supabase is
                │   transient working storage that gets recycled)
```

### What the notebook touches (imports + outputs)

The flow diagram above shows the notebook as a single box. Inside, it
depends on two modules and writes two things outside the parquet record:

- **Imports from `backend/crud/`:**
  - `supabase_io.py` — `discover_lemd_tables`, `load_table_paginated`,
    `save_snapshot_parquet`, `compute_file_hash` (operational helpers).
  - `opensky.py` — `calculate_flight_phase`, `distance_to_closest_runway`
    (used as **reference implementations** in the consistency check, see
    next subsection).
- **Outputs not shown in the flow:**
  - Per-feature histograms to `backend/docs/ml/figures/02-data/`.
  - Printed verdict and counts that **a human transcribes** into
    `backend/docs/ml/02-data.md`'s snapshot log and the
    `manifest.yml > gates.data.dataset_hash[]` entry. The notebook does
    not write to either doc directly.

### Why `opensky.py` is dual-use

`backend/crud/opensky.py` is both Monica's production extraction code and
the audit's reference implementation. Monica's `export_lemd_2025_sample.py`
and the audit notebook import `calculate_flight_phase` and
`distance_to_closest_runway` from the same module.

Operationally:

- Monica's extraction writes Supabase rows with values produced by today's
  `opensky.py`.
- The audit re-runs `opensky.py` against those rows and asserts the deltas
  are below the consistency tolerances (`velocity_kmh < 1e-6`,
  `dist_to_runway_m < 1m`, `time_utc < 1s`, `flight_phase` exact).

Implication: any change to those functions silently changes the audit's
tolerance for past cycles. If Monica updates the math and **rebackfills**,
the audit passes — the new code produces the same values it just wrote. If
Monica updates the math and **doesn't** rebackfill, the next cycle's audit
will flag the deltas as inconsistencies. Both outcomes are correct; just be
aware that the consistency check is "agreement with current code," not
"agreement with code at the time of extraction."

### The hard timing rule

**Monica must NOT truncate the Supabase table until Txema confirms the
snapshot is safely in Drive with a verified hash.**

If Monica truncates first, that data is gone forever — Supabase has no
backup, and the local parquet doesn't exist yet. Txema's confirmation
message ("snapshot safe in Drive: <hash>") is the green light for
truncation.

---

## Roles

### Monica — data ingestion and Supabase

- Maintains `backend/scripts/export_lemd_2025_sample.py` and the
  `OpenSkyService` class in `backend/crud/opensky.py`
- Runs the export script against new date ranges as the team agrees
- Manages OpenSky research-account credentials (private to her)
- Writes to a single Supabase project the team shares (URL + key
  populated in `.env` template; service-role key shared via
  password manager, never committed)
- Notifies the team when a new batch is on Supabase, with the table
  name and the date range it covers

### Txema — validation and parquet management

- Runs `notebooks/05_phase2_data_validation.ipynb` against each new
  Supabase batch
- Produces a local parquet snapshot per batch (raw and, if needed,
  deduped — see "When dedup is appropriate" below)
- Uploads parquets + `.sha256` sidecars to the team's Google Drive
- Updates `backend/docs/ml/manifest.yml > gates.data.dataset_hash`
  with the new sha256 entry
- Documents any anomalies in `backend/docs/ml/02-data.md` and opens
  a GitHub `[Bug]` issue tagging the team

### Whole team — coordination and review

- Reviews PRs that change `pyproject.toml`, `.gitignore`, this file,
  or anything touching the data pipeline
- Discusses extraction-coverage decisions (which months, how many
  days, ordered by priority) before Monica runs new exports

---

## Naming conventions

Names are descriptive, not opaque. Anyone glancing at a filename should
see what date range it covers and when it was snapshotted.

Because the Supabase table is a transient working store (truncated and
refilled across cycles), its name is *not* the source of truth for the
data's date range. The parquet filename is — and it's derived from the
data itself.

### Supabase table

A single working table. The team can keep its current name (e.g.,
`lemd_<some-suffix>`) for the project's lifetime, since the data inside
turns over with each cycle. The table name is just a query target, not
a description of contents.

### Local parquet files (the canonical record)

```
data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__snapshot_<YYYY-MM-DD>.parquet      (raw mirror)
data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__deduped_<YYYY-MM-DD>.parquet       (only if dedup override applied)
data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__snapshot_<YYYY-MM-DD>.sha256       (sidecar)
data/raw/lemd_<startYYYYMMDD>_to_<endYYYYMMDD>__deduped_<YYYY-MM-DD>.sha256
```

The `<startYYYYMMDD>_to_<endYYYYMMDD>` part is computed from the data's
own `time_utc` min and max — derived after loading, not before. The
`<YYYY-MM-DD>` after `__snapshot_` is the snapshot *date* (when Txema
ran the audit), not from the data.

Example: `lemd_20250310_to_20250314__snapshot_2026-05-10.parquet` is a
parquet of data spanning 2025-03-10 to 2025-03-14 inclusive, snapshotted
on 2026-05-10.

Same names mirror to Google Drive at `drone-ai-saturdays/data/raw/`.

### Manifest entries

`gates.data.dataset_hash` accumulates one entry per cycle, keyed by
parquet basename:

```yaml
dataset_hash:
  lemd_20250310_to_20250314__deduped_2026-05-10: "sha256-hex..."
  lemd_20250320_to_20250403__snapshot_2026-05-25: "sha256-hex..."
  # ... grows as cycles complete
```

### Manifest entries

`gates.data.dataset_hash` accumulates one entry per *canonical*
parquet (the deduped version when both exist; the raw version when
no dedup was needed). Format:

```yaml
dataset_hash:
  lemd_20250310_to_20250314__deduped_2026-05-10: "sha256-hex..."
  lemd_20260310_to_20260314__snapshot_2026-05-15: "sha256-hex..."
```

---

## When dedup is appropriate

Default: **the snapshot mirrors Supabase**. Phase 2 documents what's
broken; Phase 3 cleans. Don't dedup invisibly.

Override (dedup at Phase 2): all three conditions must hold.

1. The "broken" data is known garbage with no signal value (not just
   imperfect data we might want to handle differently).
2. There is universal agreement on what to do with it (no preprocessing
   decision to be made — just remove).
3. Keeping it would actively mislead downstream phases (e.g., training
   a model on duplicated rows that distort distributions).

When all three hold, produce both files:

- The raw parquet (audit evidence — proof that the issue existed)
- The deduped parquet (canonical — what downstream phases load)

The manifest references the deduped one. `02-data.md` documents both,
the rule used for dedup, and why dedup was justified.

Example case where override applied: 2025-03-10 batch had 37.5%
byte-for-byte duplicate rows from Monica's export script running ~7
times over overlapping ranges. We deduped on full row equality.

---

## Response playbook — when the audit finds something

The audit notebook detects ten distinct kinds of findings across cells
7a–7e, 8, and 11. Each fires its own PASS / FAIL / REVIEW signal, but
the *action to take* depends on the finding's nature, not just the
cell number. This playbook documents the response patterns we use.

### Findings catalog

| Cell | Finding | Likely root cause |
|------|---------|-------------------|
| 7a | Missing or extra columns | Upstream schema change, wrong dataset |
| 7b | Wrong dtype on a column | Pipeline version / library change |
| 7c | Critical column has nulls | Pipeline bug, receiver issue, missing rows |
| 7d | Loose dups only | Multi-receiver merge edge case |
| 7d | Medium dups (same place, same time) | Sub-second broadcast bucketed at 1s |
| 7d | Full-row dups | Script re-run, pipeline re-insert bug |
| 7e | Physical range violation | Sentinel value, unit error, sign bug |
| 7e | LEMD bbox violation | Spatial filter bug, wrong airport |
| 8 | Pipeline consistency drift | Code version skew vs the repo |
| 11 | Insufficient volume / coverage gaps | Expected during ramp-up |

### Response categories

There are six response patterns. They differ in how seriously the
finding impacts the cycle's usability and whether upstream action
is required.

#### Response A — Block the cycle

**When:** the data is so broken or wrong that downstream use would
produce nonsense. Examples: schema completely different from
expected (cell 7a missing critical columns), wildly out-of-range
data suggesting a wrong query entirely.

**What to do:**
1. Do NOT update the manifest with this cycle's hash
2. Do NOT upload to Drive (the parquet exists locally, but isn't
   canonical)
3. Open a `[Bug]` issue tagging Monica + team, urgent label
4. Coordinate a re-extract; ask Monica to fix the upstream issue
5. Do NOT signal Monica to truncate — the broken data is still our
   only record of what went wrong, keep it
6. Re-run validation against the corrected cycle

#### Response B — Override + automated fix

**When:** the finding meets all three override conditions
(see "When dedup is appropriate" below — these conditions generalize
beyond duplicates):
1. The "broken" data is known garbage with no signal value
2. There is universal agreement on what to do with it
3. Keeping it would actively mislead downstream phases

**What to do:**
1. The notebook applies the fix automatically (e.g., the dedup
   cell does this)
2. Produces a second parquet with a descriptive suffix
   (`__deduped_<date>`, `__rangeclipped_<date>`, etc.)
3. The deduped/fixed parquet becomes the canonical version in
   the manifest's `dataset_hash`
4. The raw parquet is kept as audit evidence
5. Surface to Monica so the upstream fix happens for future cycles
6. Document in `02-data.md` with the rule used and rationale

**Example:** Cycle 1 (2025-03-10 batch) hit this for full-row
duplicates. The override applied; deduped parquet produced; Monica's
script updated with a unique constraint.

#### Response C — Surface upstream + proceed

**When:** the finding indicates an upstream bug that should be fixed,
but the current cycle's data is still usable as-is. Examples: a
small percentage of nulls in a non-critical column that should be
non-null, mild pipeline consistency drift, slight range violations
that don't affect ML training.

**What to do:**
1. Open `[Bug]` issue tagging the team
2. Document in `02-data.md > Known issues`
3. Manifest still references this cycle's hash as canonical
4. Phase 3+ can proceed
5. Monica fixes upstream; future cycles arrive without the issue
6. Do not block on resolution

#### Response D — Document + proceed (no upstream fix)

**When:** the finding is expected, known about, or doesn't have a
practical upstream fix. Examples: 0.0044% nulls in `baroaltitude`
from transponders that only report `geoaltitude`, low cycle-1
volume below the SOFT_DEV floor (resolved by accumulating more
cycles, not by changing upstream code).

**What to do:**
1. Document in `02-data.md > Known issues` with a brief explanation
2. No GitHub issue (would just sit there indefinitely)
3. No upstream action requested
4. Manifest unchanged
5. Phase 3+ proceeds normally

#### Response E — Investigate first

**When:** the finding's nature isn't immediately clear. The audit
fires REVIEW but you don't know whether it's a B (override), C
(surface upstream), or D (just document). Examples: unexpected
dups in cycle 2 after Monica's fix was supposed to prevent them,
range violations on one specific column with no clear cause.

**What to do:**
1. Inspect offending rows in the notebook (uncomment the sample
   prints in each cell)
2. Cross-check with `02-data.md` history — was this seen before?
3. Talk to Monica if it might involve her pipeline
4. Decide which of A / B / C / D applies, then act
5. Whatever the answer, document the investigation itself in
   `02-data.md` — the reasoning is as valuable as the conclusion

Default to Response E whenever in doubt. Better to spend an hour
investigating than to mis-apply Response B and silently mutate
the data.

#### Response F — Update the methodology

**When:** the finding suggests our *audit* needs to change. Examples:
a check that's too strict and flags real data as broken; a missing
check that should have caught something we now know about; a
threshold that should be tighter or looser.

**What to do:**
1. Don't apply any in-cycle response yet — the audit itself is
   the bug
2. Discuss as team; reach an explicit decision
3. Update the relevant audit cell(s) in the notebook
4. Update this workflow doc + `02-data.md` to record the
   methodology change
5. Re-run validation on the current cycle with the updated logic
6. Note in `02-data.md` that prior cycles were validated under
   the old methodology

### Decision tree

```
Audit fired FAIL or REVIEW.
│
├── Is the data so broken downstream use would produce nonsense?
│       → Response A (block)
│
├── Does the finding meet the 3-condition override?
│       (known garbage, unambiguous fix, no preprocessing decision)
│       → Response B (override + automated fix)
│
├── Is the upstream fix possible AND worth doing?
│       → Response C (surface + proceed)
│
├── Is the finding expected / has no practical fix?
│       → Response D (document + proceed)
│
├── Is the finding's nature unclear?
│       → Response E (investigate, then act)
│
└── Does the finding reveal a problem with the audit itself?
        → Response F (update methodology)
```

### Tracking responses in 02-data.md

For each cycle's "Known issues" section in `02-data.md`, document
each finding with:

- What the audit caught
- Which response category was applied (A through F)
- Why (the override conditions for B; the rationale for D; the
  investigation summary for E)
- Link to the relevant GitHub issue (if applicable)

This way `02-data.md` becomes a running ledger of every audit finding
across all cycles, not just cycle 1. Future cycles append their own
sub-sections; the playbook stays stable.

---

## Audit cells must be safe to run blindly

Validation cells in the notebook should handle **both clean and dirty
batches uniformly**. A teammate running the notebook on a future batch
should never have to remember "skip this cell if X" or "manually toggle
that block when Y."

Each audit cell should:

- **Self-detect whether action is needed** (e.g., dedup only fires when
  duplicates are present; otherwise the cell prints "no action needed"
  and produces no artifact)
- **Print loud signals when action does fire** — clear ACTION REQUIRED
  notices, not silent cleanups
- **Use dynamic dates** (`date.today().isoformat()`) rather than
  hardcoded snapshot dates, so filenames are correct on every run

The principle: **a cell that only makes sense for one batch shouldn't
be in the audit notebook**. Either it's part of the standing audit
pattern (and handles all cases), or it lives somewhere else (e.g., a
one-off analysis notebook).

For unexpected outcomes — a non-zero dedup count on a batch we thought
was clean, a schema mismatch, a sudden range violation — the audit
should make those impossible to miss. An audit you forget to read is
worse than no audit, because it creates the illusion of safety.

---

## Cycle checklist

Each time Monica notifies the team that the Supabase table is ready
to be snapshotted (~400-500 MB used):

**Txema's responsibilities:**

- [ ] Run `notebooks/05_phase2_data_validation.ipynb` against the
      current state of the Supabase table
- [ ] Cell 4 derives the parquet name from the data's `time_utc` range
      and saves to `data/raw/<derived-name>.parquet`
- [ ] Compute and save sha256 sidecar
- [ ] Review validation outcomes (cells 7a–7e, 8) — any FAIL or REVIEW
      gets an inline note in `02-data.md`
- [ ] If dedup applies (per "When dedup is appropriate" below), produce
      and save the deduped parquet + its sha256
- [ ] Upload parquet(s) + sha256 sidecar(s) to Drive
- [ ] Update `manifest.yml > gates.data.dataset_hash` with new entry
      (keyed by parquet basename, not Supabase table name)
- [ ] Update `02-data.md` cumulative volume metrics (Real / Usable /
      Enough across all parquets in `data/raw/`)
- [ ] Open a `[Bug]` issue if any FAIL surfaced
- [ ] **Send confirmation to Monica:** "snapshot safe in Drive: <hash>" —
      this is the green light for her to truncate
- [ ] Notify team: validation summary in Discord / Slack

**Monica's responsibilities:**

- [ ] Wait for Txema's confirmation message before any truncate
- [ ] On confirmation: `TRUNCATE` the Supabase table
- [ ] Confirm to Txema: "table truncated, ready to fill"
- [ ] Resume extraction script for the next time range

---

## Alternative path — OpenSky scientific dataset (cycle 3+)

Background: D-007. Pivot rationale: the Trino + Supabase path was the
dominant human-side bottleneck for cycle scheduling. The OpenSky public
scientific dataset gives schema-compatible data with no credentials and
no inter-teammate coordination.

### Script
`backend/scripts/download_opensky_states.py` — ~370 lines, runs
overnight, atomic per-Monday writes, resumable.

### Source
[OpenSky scientific datasets, entry #1](https://opensky-network.org/data/scientific) — "Weekly 24 Hours of State Vector Data 2017-2022."
One full 24-hour snapshot per Monday, 2017-06-05 through 2022-05-23.
Hosted on S3 at `https://s3.opensky-network.org/data-samples/states/.<YYYY-MM-DD>/<HH>/states_<YYYY-MM-DD>-<HH>.csv.tar`.
Schema identical to the Trino `state_vectors_data4` table.

### Resolution and metadata trade-offs

- 10s sampling (vs Trino 5s). Phase 3 needs to harmonize if mixing data
  sources.
- **No `flights_data4` table available.** The Trino path filters flights
  by `estarrivalairport='LEMD' OR estdepartureairport='LEMD'`. The
  scientific path has only state vectors — no origin/destination
  metadata. Substituted by **Filter B** (see below).
- 138 non-COVID Mondays available in the 259-Monday bucket.

### Filter B — LEMD-flight gate without metadata

After bbox + 200 km haversine cut, segment state vectors into flights
by `icao24 + 30-minute gap`. Then keep a flight iff:

```
min(dist_to_runway_m) < 10_000  AND  min(baroaltitude) < 3_000
```

Empirically (validated on 2019-10-07): removes ~47% of bbox flights
that are cruise overflights at FL350-FL410 transiting central Spain.
Median kept flight has min_dist 0.8 km and min_alt 533 m — clean LEMD
arrivals/departures.

Filter B substitutes for the Trino path's origin/destination metadata.
Not equivalent — a cruise flight that descends below 3 km within 10 km
of LEMD (e.g., low-altitude diversion) would be kept by Filter B; the
metadata would correctly exclude it. Spot-check rate expected low.

### Output naming

Per-Monday parquets in `data/raw/opensky_states/`:

```
lemd_<MondayYYYYMMDD>__opensky_states_<fetchYYYY-MM-DD>.parquet
```

E.g., `lemd_20170605__opensky_states_2026-05-23.parquet`. The naming
shape stays compatible with the cycle 1+2 Trino-path convention.

### Schema parity

The script imports `distance_to_closest_runway` and
`calculate_flight_phase` from `backend/crud/opensky.py` — same
derivations the Trino path uses. Output column set is identical to the
Trino-path snapshots (21 columns, verified by smoke test on 2017-06-05).
The `operation` column is set to `"unknown"` (no flights metadata
available); downstream preprocessing can derive heuristically.

### Cycle-3 audit posture

Per D-211 (in `02-data.md`), the cycle-3 audit reuses the same
derivation functions as the Trino path, so the audit-consistency check
(D-205) produces zero deltas by construction. Meaningful validation in
cycle 3 has to be at the row-quality and Filter-B-effectiveness layer,
not the derivation-parity layer. Open question: do we adapt
`notebooks/05_phase2_data_validation.ipynb` for cycle 3, or treat the
script's coercions + Filter B as sufficient?

---

## Coverage strategy (pending team decision)

The design doc target is 6-12 months of training data. Current state
(2026-05-10): 5 days from 2025-03-10 → 03-14, plus a second batch from
2026 pending validation. Total: ~10 days, well below the 30-day
SOFT_DEV floor.

Decision pending — which months to extract, in what order:

- **Year-over-year span across same calendar window** (e.g., 3 weeks
  from March across 2024, 2025, 2026) — controls for season, captures
  drift
- **Consecutive months** (e.g., Jan-Feb-Mar 2025, ~90 days) — smooth
  seasonal coverage
- **Scattered** (e.g., 1 week per month for 12 months) — maximum
  diversity per row

The constraint is OpenSky research-account quota, which Monica knows
best. Discuss in a team session before next extraction; record decision
in `backend/docs/decisions/README.md`.

---

## Authentication and credentials

- `.env` at repo root holds OpenSky and Supabase credentials. Never
  committed (in `.gitignore`).
- `.env.example` documents required keys.
- Monica's OpenSky research-account credentials live only in her copy
  of `.env`; she runs the export script.
- Supabase service-role URL+key shared via password manager
  (1Password, Bitwarden); the team validates against the same project.
- If the team ever needs multiple Supabase projects (e.g., for testing
  isolation), update `.env.example` to use suffixed keys
  (`SUPABASE_URL_<SLUG>` / `SUPABASE_KEY_<SLUG>`) and update the
  notebook to iterate.

---

## When in doubt

- Found something weird in the data → don't silently work around it,
  open a GitHub issue, tag the team, decide together
- Not sure if it's a bug or a feature → ask Monica (data pipeline)
  or whoever wrote the relevant code
- Need to change shared config (`pyproject.toml`, `.gitignore`,
  `manifest.yml`, this file) → PR with reviewer, not direct push
