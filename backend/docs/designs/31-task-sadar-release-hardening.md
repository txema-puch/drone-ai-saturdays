# Issue #31 — SADAR application release hardening

**Status:** implementation complete through the pre-publication gate; external publication and deployment pending
**Date:** 2026-07-14
**Branch:** `task-sadar-merge-c`
**Scope:** close the release blockers and make frozen-model evaluation a first-class analyst workflow

## Goal

A clean checkout must be able to build and start the complete analyst application from a
version-pinned public artifact. Every process must observe one internally consistent model,
evidence, report, and identifier generation. Published case links must remain stable when the
cohort is reordered or regenerated without changing the segment's canonical identity.

The deployed product must also let an analyst upload new OpenSky-style trajectory data and run
it through the exact frozen derivation, preprocessing, quality, and model-scoring contract used
by the baked cohort. Upload evaluation is ephemeral and bounded: it produces an inspectable,
downloadable result without mutating the release, queue, cases, reports, or model.

This is a course-demo deployment, not a production counter-drone system. The target is one
Docker image on Hugging Face Spaces, one immutable release artifact, and one reproducible
smoke-test path.

## Scope challenge

The release findings plus the analyst-product correction reduce to four implementation units:

1. **Stable identity contract** — replace sequence-position case IDs before baking another
   artifact.
2. **Immutable release builder** — stage, validate, hash, and atomically promote a complete
   model/evidence/report generation.
3. **Upload and evaluate** — accept bounded raw trajectory files, reuse the frozen online
   preprocessing/scoring contract, and return an ephemeral analyst dossier.
4. **Clean-checkout delivery** — fetch the pinned artifact, build the React and FastAPI image,
   and smoke-test the exact container that will run on the Space.

Packaging and atomic promotion are one boundary, not separate systems. Upload evaluation reuses
the existing leaf derivations, preprocessing, quality guardrails, scorer, and dossier
visualizations. Building a second registry service, database, durable job queue, or runtime LLM
report generator would add machinery without improving this single-process demo.

The plan crosses more than eight files because identity and inference contracts are shared by the
bake, API, UI, tests, and deployment. Reduce merge risk through four stacked actuations, not by
dropping a layer. Each actuation must end with its scoped tests green and its own rollback
commit. Only Actuation 4 is publicly deployable; Actuations 1 through 3 are internal gates and do
not require compatibility with the ignored legacy bundle.

| Gate | Ends with | Rollback |
|---|---|---|
| 1. Identity | Schema-v2 fixtures and backend/frontend identity tests pass | Revert the identity commit; no public URL exists yet |
| 2. Release | One locally verified immutable schema-v2 release | Select the prior local release directory; no lock file changes |
| 3. Evaluate | One bounded CSV/Parquet upload produces an ephemeral multi-segment result with frozen-model provenance | Disable the evaluation route/page; baked dossier and What-If remain intact |
| 4. Delivery | One committed lock and one verified Space revision | Revert the lock/image commit or redeploy the prior Space revision |

## What already exists

| Existing component | Reuse decision |
|---|---|
| `backend/serve/precompute.py` | Keep as the sole evidence/model bake; change only its output protocol. |
| `backend/core/derivations.py` | Reuse `apply_derivations`; uploaded derived columns are ignored and recomputed from raw observations. |
| `backend/core/preprocessing.py` | Reuse the exact Phase-3 transform; never create a serving-only preprocessing fork. |
| `backend/serve/scoring.py` | Keep vectorized scoring; share batch/single evidence assembly across precompute, What-If, and uploads. |
| `backend/serve/quality.py` | Reuse the existing assessability/data-quality guardrails for every uploaded segment. |
| `backend/serve/report.py` | Keep reports offline and baked; never add a production LLM call. |
| `backend/serve/operations.py` | Keep operation grouping; make the case identity helper live here. |
| `backend/serve/app.py` | Keep one FastAPI process; load one verified release and serve the SPA. |
| `TrajectoryMap`, `TemporalPanel`, and `Attribution` | Reuse them in the evaluation result view; do not fork chart implementations. |
| `frontend/` | Keep the current Vite build and relative `/api` client; add one `/evaluate` workflow. |
| `backend/models/phase6/lstm_ae_best.pt` and `scaler.joblib` | Treat these as trusted bake inputs; export tensor-only weights and a JSON scaler into the release. Do not ship the 138 MB training frames or either pickle. |
| Hugging Face Spaces target | Use a public pinned artifact URL plus Docker Space; no new registry vendor. |

Primary-documentation check:

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) is the recommended boundary
  for loading shared ML resources without import-time side effects.
- [Docker multi-stage builds](https://docs.docker.com/build/building/multi-stage/) support named
  build stages and copying only final artifacts into the runtime image.
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) supports locked
  execution, lock checks, exports, and partial installs for Docker caching.
- [Hugging Face Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker) documents port
  7860, build/runtime secret separation, and UID 1000 file-ownership requirements.

## Architecture

```text
OFFLINE RELEASE BUILD

phase6 inputs + report cache + source commit
                  |
                  v
        precompute into .staging/<uuid>/
                  |
          validate schema + references
          hash every shipped file
          copy model + scaler
                  |
                  v
       releases/<content-release-id>/       immutable directory
                  |
       package .tar.gz + SHA-256
                  |
                  v
       public HF artifact @ pinned revision
                  |
                  v
       committed demo_bundle.lock.json

CLEAN CHECKOUT / DEPLOY

lock file -> download -> verify archive hash -> safe extract
                                    |
                                    v
Node build -> frontend/dist     verified release directory
          \                         /
           \                       /
            +---- multi-stage Docker ----+
                       |
                 FastAPI lifespan
              verify manifest + hashes
                       |
             /api/* + SPA route fallback
                       |
                 HF Docker Space

ANALYST EVALUATION

browser /evaluate
   |
   +-- prepare frozen model --> health polling --> ready
   |
   +-- .csv/.parquet upload (bounded multipart stream)
             |
             v
      validate flat raw schema + resource limits
             |
      apply_derivations -> preprocess
             |
      score_segments + shared evidence assembly
             |
             v
   ephemeral results + reject reasons + client-side JSON export
   (no release, queue, case, report-cache, or server-state mutation)
```

### Release layout

```text
release/<release_id>/
├── release-manifest.json
├── queue.json
├── operations.json
├── cases.json
├── metrics.json
├── cases_raw.parquet
└── model/
    ├── state_dict.pt
    ├── scaler.json
    ├── model-contract.json
    └── cohort-score-reference.json
```

`release-manifest.json` contains:

- `schema_version` (start at `2` because case identity changes)
- `release_id`
- source commit plus SHA-256 values for every ignored build input
- prompt fingerprint and report coverage count
- frozen scoring contract (`T`, threshold, step threshold, feature names)
- frozen percentile contract: weak empirical CDF,
  `100 * count(cohort_score <= candidate_score) / cohort_size`, with inclusive ties
- frozen online-input contract (`input_schema_version`, SI/epoch units,
  `derivation_contract_version`, and `preprocessing_contract_version`)
- SHA-256 and byte length for every other release file

The release manifest contains no volatile timestamp. `release_id` is the first 20 hexadecimal
characters of SHA-256 over canonical JSON of the complete manifest payload with only the
`release_id` field omitted. That payload includes the sorted file-hash list, schema, source and
input provenance, report/evidence fingerprints, and scoring/model contracts. Validation
recomputes this value. Producer storage requires the immutable directory name to match the
release ID. Runtime storage is deliberately path-independent: Docker copies the verified
content to `/opt/sadar/release`, sets `SADAR_RELEASE_DIR` to that fixed path, and validates the
manifest's release ID instead of the directory basename. A release directory is never edited
after promotion; publication time belongs in the external lock/publication record.

### Safe model and scaler artifacts

Do not ship either Python object pickle as a serving input:

- `state_dict.pt` contains tensors only and is loaded with
  `torch.load(..., map_location="cpu", weights_only=True)`.
- `model-contract.json` contains model class, architecture parameters, exact feature order,
  expected tensor keys/shapes/dtypes, threshold contract, and producing library versions.
- `scaler.json` contains the ordered `SCALER_FEATURES` plus finite `mean`, `scale`, `var`, and
  sample-count values. A small `FrozenStandardScaler` implements only `transform` and
  `inverse_transform`; it rejects zero/non-finite scales and wrong feature widths.
- `cohort-score-reference.json` contains the sorted full-precision cohort scores encoded as
  IEEE-754 float64 hex strings plus count, formula/tie-policy ID, and digest. Display-rounded queue
  scores are never reconstructed into the statistical reference.

The release validator constructs the model from the JSON architecture, checks every tensor
key/shape/dtype before `load_state_dict`, and runs a fixed-vector scaler parity test against the
training artifact during the bake. This replaces the current unrestricted `joblib.load` and
checkpoint-object load while preserving the frozen numerical contract.

The manifest's online-input versions bind upload results to the exact derivation/preprocessing
code generation that produced the model features. They are returned in every evaluation response
and changed deliberately whenever input columns, units, filters, segmentation, imputation, or
feature derivation semantics change.

`backend.core.derivations` and `backend.core.preprocessing` export their contract-version
constants. Release validation compares them with the manifest and fails startup on mismatch;
provenance fields are compatibility gates, not labels. Model validation also requires the exact
cohort-reference count/digest/formula declared by `model-contract.json`.

### Stable case identity

Current numeric IDs are the array index produced by `enumerate(seg_ids)`. Reordering the
cohort changes URLs and analyst references even when the underlying segment is unchanged.

Add one pure helper in `backend/serve/operations.py`:

```text
digest               = SHA-256(UTF-8(segment_id)).raw_bytes
case_id(segment_id)  = "c_" + RFC-4648-base32(digest[:10]).lower().rstrip("=")
case_ref(segment_id) = "CASE-" + RFC-4648-base32(digest[:8]).upper().rstrip("=")
```

- `case_id` is the machine key used by JSON maps, API routes, React routes, and simulation.
- `case_ref` is the human label shown in the dossier.
- `segment_id` remains visible evidence and is the identity input.
- The exact output lengths are 18 characters for `case_id` and 18 for `case_ref`.
- Precompute checks both identifiers and fails on any collision. No suffix or array index
  fallback is allowed because it would reintroduce order dependence.

Use explicit contract names: `case_id`, `worst_case_id`, and
`behavioral_worst_case_id`. Remove the numeric `id` and `*_segment_id_num` fields rather than
keeping two competing identities. The application has not been publicly deployed, so this is
the least risky moment for the schema break.

This contract is stable across cohort ordering and membership changes only while the canonical
`segment_id` is unchanged. `segment_id` incorporates aircraft identity, first-seen time, and a
gap-derived segment number; corrected source telemetry can legitimately create a new case
identity. The UI and write-up must say “stable segment reference,” not “permanent flight ID.”

### Report evidence binding

Cached prose is valid only for the evidence generation that produced it. Define a canonical
`evidence_digest` as SHA-256 over canonical JSON containing the report-relevant structured
evidence: `segment_id`, aggregate score and percentile, aggregate and step thresholds, sorted
attribution values, channel summaries, assessment state/verdict/flags, and valid-observation
fraction. Include `report_generator_version` in that payload; do not hash the full path arrays.

The report cache key is `(evidence_digest, prompt_digest, report_generator_version)`. Precompute
omits prose whose key does not match the freshly computed evidence instead of attaching stale
text to a new score. The manifest records aggregate evidence and prompt fingerprints plus report
coverage, while each case retains its evidence digest for exact validation.

### Runtime loading

Move bundle loading into the FastAPI lifespan through a small `ReleaseStore` module:

```text
startup
  ├── resolve explicit SADAR_RELEASE_DIR
  ├── read release-manifest.json
  ├── require schema_version == 2
  ├── require image input/derivation/preprocessing contract versions == manifest
  ├── verify required files and SHA-256 values
  ├── load queue/operations/cases/metrics once
  └── publish immutable state to app.state.release

request
  └── read app.state.release only; never switch release mid-process
```

Module import must not read ignored files. A missing or corrupt release fails startup with a
single actionable error naming the absent file or bad hash. This makes test collection work
on a clean checkout while keeping deployment fail-fast.

The frozen model and scaler stay lazy inside the selected immutable release. A running
process never changes releases; rollback means starting the prior image or release ID.

Model readiness is an explicit state machine because the observed first load can take
minutes while warmed calls complete in about 95 ms:

```text
not_loaded ──prepare/model request──> loading ──success──> ready
                                  │
                                  └──error──> failed(retry_remaining=1)
                                                  │
                                  next prepare/model request retries once
                                                  │
                                  success ─────────┴──> ready
                                  error ──────────────> failed(retry_remaining=0)
```

The current non-blocking single-flight lock is retained. While state is `loading`, concurrent
requests return HTTP 429 with `Retry-After`; a browser timeout never implies that server-side
loading stopped. A failed load returns HTTP 503 with a bounded public message, records detail in
server logs, and retries only when `retry_remaining` is one. `/api/health` always reports release
readiness separately from `model_state` and `model_retry_remaining`, so model loading
or failure never blocks the read-only dossier.

Production is same-origin. Remove wildcard CORS instead of carrying a cross-origin trust surface
the deployed application does not use. Unknown `/api/*` paths return JSON 404 responses and must
never fall through to the SPA.

### Upload-and-evaluate contract

Add an analyst page at `/evaluate` and two model-facing endpoints:

- `POST /api/model/prepare` starts the existing single model-load attempt in a background thread
  and returns the current state immediately. Repeated calls are idempotent. The UI polls
  `/api/health` and enables evaluation only when `model_state == "ready"`.
- `POST /api/evaluations` accepts one multipart `file` part and synchronously evaluates a warm,
  bounded upload. The route takes a raw `Request`, checks model readiness and acquires the
  analysis slot before invoking multipart parsing, so rejected callers do not spool files. It
  returns `429` when another simulation/evaluation owns the slot, `503` when the model is not
  ready, and never queues work in process memory.

Both are fail-closed behind `SADAR_ENABLE_EVALUATION`. The setting defaults to `false`; the final
Space deployment enables it explicitly after the upload smoke/security gates pass.
`/api/health` exposes `evaluation_enabled`, disabled endpoints return a bounded 404, and frontend
navigation follows the capability instead of hard-coding the route. This is the rollback/abuse
kill switch for Actuation 3 without removing the baked dossier or What-If.

Supported input is a flat UTF-8 CSV or flat Parquet file containing OpenSky-style observations.
The required raw columns are `time`, `icao24`, `lat`, `lon`, `baroaltitude`, `velocity`,
`heading`, `vertrate`, and `onground`. `callsign`, `squawk`, `geoaltitude`, `alert`, `spi`, and
`lastcontact` are optional and receive explicit null/default values. Client-supplied
`flight_id`, `segment_id`, `operation`, `flight_phase`, `dist_to_runway_m`, and other derived
fields are ignored and recomputed by `backend.core.derivations.apply_derivations` followed by
`backend.core.preprocessing.preprocess`.

Null and boolean handling follows the frozen training transform:

- `time`, `icao24`, `lat`, and `lon` are structural for the online derivation boundary and
  non-null; one invalid value rejects the upload.
- `baroaltitude`, `velocity`, `heading`, and `vertrate` may be null because the core masks,
  imputes, and counts missing measured values. Positive/negative infinity is rejected everywhere,
  and an all-null/insufficient measured segment is rejected by the shared pipeline.
- `onground` accepts only booleans, case-insensitive `true`/`false`, numeric/string `0`/`1`, or
  null. Null follows the existing contract by becoming `false` and increments an
  `onground_defaulted` diagnostic; every other encoding is a field error.
- Optional fields use explicit typed null/defaults. No missing value is silently converted to a
  measured zero except the documented `onground` behavior.

The boundary is deliberately small and measurable:

| Limit | Contract |
|---|---:|
| Multipart request body | 10 MiB, counted while streaming rather than trusting `Content-Length` |
| Upload time | 5 s maximum idle gap and 60 s total body-read deadline; timeout returns 408 |
| Raw rows | 50,000 before derivation |
| Projected preprocessing | 100 segments and 100,000 ten-second grid rows before resampling allocation |
| Accepted post-preprocess segments | 25; reject the upload rather than silently truncate |
| CSV | UTF-8, comma-delimited, one header row, no duplicate columns |
| Parquet | one flat schema, metadata inspected before materialization, ≤50 MiB declared uncompressed bytes |
| Numeric values | finite after coercion; latitude/longitude and epoch-second bounds validated |
| Concurrency | one shared analysis slot across What-If and upload evaluation |
| Persistence | none; temporary bytes are deleted in `finally`, results live only in the browser |

An `UploadEvaluationService` owns parse, normalization, derivation, preprocessing, scoring, and
response assembly. It calls existing leaf functions rather than copying their math. Keep
precompute's vectorized model pass: add `score_segments` for one-or-many aligned segments and a
pure `assemble_segment_evidence` helper in `backend/serve/scoring.py`. Precompute scores the full
cohort in batches, uploads score up to 25 segments in one batch, and What-If scores one; all three
use the same assembly contract for reconstruction, per-step error, attribution, percentile,
severity, and quality assessment.

Percentiles use the manifest's weak empirical-CDF formula everywhere. This replaces the current
split behavior where precompute assigns positional `rank/(N-1)` while live simulation counts
`cohort_score <= score`. Minimum, maximum, tied, baked, simulated, and uploaded scores therefore
share one exact definition.

```text
file bytes
  ├── invalid type/size/schema ----------------------------> bounded 4xx + field errors
  └── parsed raw observations
        ├── derive flight IDs/phase/distance
        ├── Phase-3 preprocess (filter, segment, impute)
        │     ├── no LEMD-engaging segment ----------------> 422 + rejection counts
        │     └── >25 accepted segments -------------------> 413, never partial scoring
        └── for each accepted segment
              ├── physical/data-quality assessment
              ├── frozen scaler + LSTM AE score
              ├── percentile against frozen release cohort
              └── result dossier
```

Before derivation, normalize typed raw scalars and canonicalize observations sorted by
`(icao24, time)`. Collapse byte-for-byte-equivalent observation duplicates and report their
count; reject two rows with the same `(icao24, time)` but different accepted field values. The
canonical JSON hash is `dataset_digest`, stable across row order and CSV/Parquet container
format. The raw-byte hash remains `upload_sha256` for request tracing only.

The response contains the release/model identity, both digests, raw/derived/accepted row and
segment counts, bounded rejection reasons, and an array of upload-only `EvaluationResult` DTOs.
Each result uses an `evaluation_ref` derived from `(dataset_digest, segment_id)` for UI
identity but is not a case ID and is never addressable through `/api/flights/{case_id}`. The UI
shows a result list plus neutral existing map, temporal, reconstruction-error, attribution, and
data-quality components. The DTO has `model_status` (`above_threshold` or `below_threshold`) but no
ground-truth `label`, `case_ref`, `operation_ref`, report, or neighboring operation fields. The UI
states that the percentile is relative to the frozen release cohort and offers client-side JSON
export. It never labels a result emergency, go-around, unauthorized, or confirmed anomalous.
Refreshing or leaving `/evaluate` clears the result by design.

Uploaded evidence never receives cached or runtime-generated LLM prose. A neutral assessment
panel shows deterministic quality copy and “No generated narrative for uploaded data.” React
renders filenames and errors as text only. The server never logs the filename/body/raw rows and
never includes them in errors; a successful response intentionally returns only the bounded
evidence allowlist (processed path, selected channels, model outputs, derived IDs/counts, and
provenance), whose values may coincide with uploaded measurements.

Before file selection, `/evaluate` exposes the downloadable synthetic sample/template and the
complete required/optional column, SI-unit, epoch-second, null/boolean, LEMD-only, row/segment,
ephemeral-processing, and public-demo rules. It says: do not upload confidential or proprietary
data; this public anonymous demo has no authentication or server-side history. Private analyst
files require an authenticated deployment and are outside this release.

### Evaluation experience design

`/DESIGN.md` is the visual source of truth. This plan fixes the implementation-level hierarchy so
the new route cannot become a generic upload card followed by a dashboard mosaic:

```text
persistent SADAR header
  ├── Audit queue (default)
  └── Evaluate data (capability-gated)
        ├── orientation + release/model identity
        ├── always-visible public-demo/privacy boundary
        ├── prepare state + one file action + schema/sample/limits
        └── success workspace
              ├── dataset summary + accepted/rejected counts
              ├── accepted-segment selector
              └── evidence, in trust order
                    1. assessability/data quality
                    2. neutral threshold status + score + frozen-cohort percentile
                    3. trajectory and temporal reconstruction evidence
                    4. feature attribution
                    5. local export / explicit clear
```

The first viewport has only three jobs: orient the analyst, state the trust/privacy boundary, and
make the compatible file action obvious. Existing `TrajectoryMap`, `TemporalPanel`, and
`Attribution` components are reused only after a segment has been accepted; baked `Stamp`,
`ReportPanel`, case navigation, ground-truth label, and operation-context components are forbidden
for uploaded evidence.

| State | Visible behavior | Recovery/action |
|---|---|---|
| Evaluation disabled | Direct route explains that this deployment is read-only; nav item hidden | Return to audit queue |
| Model not loaded | Exact release shown; file control disabled; no error styling | Prepare model |
| Loading model | Indeterminate status, no percentage; audit remains available | Browse audit / wait |
| Model failed | Bounded failure and one retry when health permits | Retry / return to audit |
| Ready, empty | Privacy notice, exact schema/sample/limits, native select + drop target | Select file |
| Reading/validating | Indeterminate phase text and filename; replacement aborts browser request | Cancel/replace |
| Busy | Structured 429 message and `Retry-After` timing | Retry when available |
| Validation error | Focused summary beside control plus bounded field/rejection groups | Replace file |
| Zero accepted | Contextual LEMD/assessability explanation, not `No results` | Review schema / replace |
| Partial preprocessing | Accepted and rejected counts; no rejected raw values | Inspect accepted |
| Success | Segment selector, quality-first evidence, export and clear | Inspect/export/clear |
| Cleared/refreshed | Returns to ready empty state; no history implication | Select file |

Keyboard and screen-reader behavior is part of acceptance: drag/drop is optional; the native file
input, prepare/retry, segment selector, export, and clear all work by keyboard; status changes use
one restrained live region; validation focus moves to the summary; active segment state is
programmatic; chart data-table fallbacks remain available. At 1440 px the dataset rail is 320 px;
at 1024–1439 px it is 260 px and evidence panels stack inside the main column. Below 1024 px the
route shows `Desktop workspace required` and disables evaluation rather than shipping an unusable
mobile upload flow.

The emotional arc is deliberate: orientation → informed consent → honest wait → recoverable
validation → skeptical evidence review → controlled export/clear. Provenance, quality, uncertainty,
and the fixed cohort remain visible at the moment the score appears. This is how the interface
earns trust without overstating what the model knows.

## Implementation sequence

### Actuation 1 — Stable identity contract (P1)

1. Add deterministic `case_id` and `case_ref` helpers with collision detection.
2. Bake those identifiers into every queue row before operation grouping.
3. Key `cases.json` by `case_id`; replace numeric operation summary fields.
4. Change `/api/flights/{case_id}` and `SimulationRequest.case_id` to strings.
5. Update TypeScript contracts, routes, navigation, and component props to `case_id`.
6. Rebuild fixtures and assert the same segment keeps the same identifiers across reordered
   inputs.
7. Update route/module comments that still document numeric `{id}` contracts. Do not add a
   long-lived dual-read adapter; this application has no published schema-v1 URLs to migrate.

**Acceptance:** reversing or extending the cohort does not change any existing segment's
case ID, case reference, or URL.

### Actuation 2 — Immutable atomic release (P1)

1. Add a standard-library-only `backend/serve/release.py` with canonical hashing, structural
   manifest/hash validation, `ReleaseStore`, staging, promotion, and archive helpers. The same
   module must run in the packaging process, minimal Docker fetch stage, FastAPI startup, and
   tests without Pydantic or the training dependency set. Keep dataframe/parquet referential
   checks in one build-time `release_semantics.py` validator instead of making the transport
   layer import pandas/pyarrow.
2. Make precompute accept explicit input/output paths. It writes only into a unique staging
   directory, exports safe serve-time model/scaler artifacts, and reads the report cache from a
   separate build-input path.
3. Validate referential integrity before promotion:
   - queue `case_id` and `case_ref` values are unique;
   - cases are exactly the curated `has_case` subset of the queue;
   - operation membership exactly equals grouping the queue by `operation_ref`;
   - raw and behavioral worst IDs equal recomputed maxima;
   - duplicated segment fields agree byte-for-byte across queue, operations, and cases;
   - `cases_raw.parquet` contains exactly the case segment IDs and required columns;
   - every case's operation reference exists;
   - report text passed the deterministic guard and cache evidence digest matches;
   - thresholds and features match `model/model-contract.json`, state-dict tensor metadata, and
     `model/scaler.json` feature order;
   - image-exported input/derivation/preprocessing contract versions match the manifest;
   - `model/cohort-score-reference.json` count, full-precision values, formula ID, and digest
     match the model contract and recomputed bake scores;
   - fixed-vector output from `FrozenStandardScaler` matches the training `StandardScaler` within
     `1e-12` absolute tolerance.
4. Export the tensor-only state dict, model contract, JSON scaler, and full-precision cohort-score
   reference described above. Validate them before calculating any release hash; no `joblib`,
   unrestricted checkpoint pickle, or display-rounded score reconstruction is accepted by runtime.
5. Compute hashes and derive `release_id`, then rename staging on the same filesystem to the
   immutable `releases/<release_id>` directory. The explicit directory is the promotion; no
   mutable `current` pointer is needed.
6. Add `backend/scripts/package_demo_release.py` to create the deterministic archive: sorted
   entries, fixed modes/owner/group/mtime, and gzip timestamp zero.
7. Remove failed staging directories by default after logging the failure. A diagnostic
   `--keep-failed-staging` flag may preserve one explicitly; startup and packaging never inspect
   `.staging/`.

**Acceptance:** killing precompute before the final rename exposes no partial release and leaves
all prior immutable releases readable; corrupting any shipped byte makes validation and startup
fail.

### Actuation 3 — Analyst upload and frozen-model evaluation (P1)

1. Add a path-scoped streaming request-size guard for `/api/evaluations` before multipart parsing
   and include a pinned `python-multipart` dependency in the serving lock. The route must not
   declare `UploadFile` as an eager body parameter: acquire model/admission state first, then
   parse the raw `Request`. Reject absent/duplicate file parts, unsupported media
   types/extensions, bodies above 10 MiB, idle body gaps above 5 seconds, total body reads above
   60 seconds, and malformed multipart data with bounded JSON errors.
2. Add `backend/serve/evaluation.py` with one `UploadEvaluationService`. Inspect CSV/Parquet
   schema and Parquet metadata before materializing data; enforce the byte, row, flat-schema,
   column, primitive-type, and finite-value contracts above. Always close and delete temporary
   storage in `finally`, including disconnects and parse/model errors.
3. Normalize optional raw fields and discard every client-supplied derived field. Extend the core
   `apply_derivations` and `preprocess` orchestrators with an opt-in diagnostics collector at
   their existing stage boundaries; default callers and numerical outputs remain unchanged.
   Upload evaluation uses those same functions and returns explicit counts for rows outside the
   LEMD radius, Filter-B/Filter-D rejection, idle/short segments, impossible/missing
   observations, and empty results. Do not silently reinterpret milliseconds as seconds or feet
   as metres. Canonically collapse exact observation duplicates, reject conflicting duplicate
   `(icao24, time)` keys, and derive the order/format-independent `dataset_digest`.
4. Preserve precompute's vectorized inference and extract `score_segments` plus a pure
   `assemble_segment_evidence` helper in `backend/serve/scoring.py`. Together they produce aligned
   reconstruction, per-step and aggregate error, feature attribution, percentile/band, quality
   assessment, path, channels, truncation/coverage metadata, and model/release provenance for one
   or many segments. Move precompute's nested terminal-window classification into a pure
   `quality.is_terminal_window` helper used by bake and uploads. Precompute, What-If, and upload
   evaluation use the same weak empirical-CDF percentile helper; zero-intensity What-If and
   baked-case parity remain exact, including ties.
5. Replace the simulation-only lock/container with one `ModelRuntime`: idempotent background
   prepare, the four load states and one retry, plus one non-queueing analysis semaphore shared
   by simulation and evaluation. `POST /api/model/prepare` never blocks on model import/load;
   `POST /api/evaluations` requires `ready` before parsing and scoring.
   Add `SADAR_ENABLE_EVALUATION`, disabled by default, to health and route/navigation capability
   checks.
6. Add `POST /api/evaluations` and structured error codes for `408`, `413`, `415`, `422`, `429`,
   and `503`. Add one bounded frontend response/error decoder used by every API call; it preserves
   `status`, stable `code`, safe message, field issues, and parsed `Retry-After`, with safe fallback
   for non-JSON/malformed bodies. The response uses deterministic `evaluation_ref` values, never
   mutates release state, never inserts into queue/cases, never attaches a cached report, and
   never logs filenames or raw telemetry. Multipart streaming stays async; pandas/pyarrow
   preprocessing and PyTorch inference run in the threadpool so the event loop continues serving
   health and baked reads.
7. Add `/evaluate` to the application navigation. Build accessible file selection/drop,
   readiness, honest indeterminate `preparing_model/uploading/evaluating/done/error` states,
   busy/retry, rejection summary, multi-segment result selection, neutral evidence visualizations,
   model/cohort/product-claim caveats, clear-result action, and client-side JSON export. Abort
   in-flight requests and ignore stale responses after replacement or route exit. Document that
   aborting during threadpool preprocessing/inference suppresses the stale response but cannot
   safely cancel the running Python task; the shared slot remains owned until cleanup completes.
8. Document the accepted template schema and ship a tiny synthetic sample CSV fixture for the UI
   and smoke test. Make both downloadable from `/evaluate` beside exact schema/units/null/boolean/
   limit/privacy guidance. The sample is generated test data, not project training/evaluation
   evidence.

**Acceptance:** from a clean container, an analyst opens `/evaluate`, waits for the frozen model
to become ready, uploads a valid OpenSky-style CSV or Parquet file, sees every accepted segment's
quality and model evidence, exports the result, and can clear it. Sample download → upload →
result works without repository access. Invalid, slow, or oversized inputs are actionable and
bounded; no upload survives the request or changes baked evidence; UI/export copy says trajectory
conformance/anomaly evidence and never claims authorization or drone detection.

### Actuation 4 — Clean-checkout image and Space deployment (P1)

1. Add one transactional publish command: require a clean Git tree, package deterministically,
   upload to a public Hugging Face model repository, obtain the immutable revision, redownload
   and verify it, then write `backend/serve/demo_bundle.lock.json`. Failed upload or verification
   leaves the existing lock untouched. The lock contains URL, revision, archive SHA-256,
   release ID, schema version, and publication timestamp. Do not commit model binaries or the
   generated bundle to this repository. `HF_TOKEN` is accepted only by this local/CI publish
   command; it is never a Docker build argument, Space variable, archive member, or runtime secret.
2. Add a standard-library fetch script that downloads the locked archive, verifies SHA-256,
   reads the bounded manifest member without extracting, accepts only that manifest's exact
   allowlist of bounded regular files, rejects absolute or parent paths, links, devices,
   duplicates, extra files, and decompression-size excess, extracts without following links to a
   temporary directory, validates the release manifest, and renames it into place.
3. Replace the legacy backend-only Dockerfile with one root multi-stage Dockerfile:
   - Node stage builds `frontend/dist`;
   - Python stage installs a generated, hashed `backend/serve/requirements-linux-x86_64.lock`
     from a minimal `backend/serve/requirements.in`, resolving Python 3.11 and CPU-only PyTorch
     for `x86_64-manylinux`, with `uv` copied from a digest-pinned image;
   - fetch stage retrieves the pinned public release;
   - runtime copies source, SPA, and verified release;
   - runtime runs as UID 1000, owns its work directory at copy time, sets
     `SADAR_RELEASE_DIR=/opt/sadar/release`, and starts one Uvicorn worker on `${PORT:-7860}`.
4. Serve `/assets/*` directly and use an index fallback for React routes after all `/api/*`
   routes. Keep production API calls same-origin and remove permissive CORS.
5. Add CI that starts from a clean checkout, runs backend and frontend suites, builds the
   image, starts it, and checks health, a deep SPA route, one case response, and a zero-
   intensity simulation. It also prepares the model, uploads the synthetic sample, verifies one
   evaluation result, and proves no temporary upload remains. Regenerate the serving lock in a
   clean Linux resolver and fail if the committed lock differs.
6. Pin Node/Python/uv base images by digest and target `linux/amd64`, the Hugging Face runtime
   platform. CI and Hugging Face rebuild the same Dockerfile from the same locked inputs; do not
   claim they run the same image digest.
7. Deploy that image definition to the Hugging Face Docker Space. Record the Space URL
   and release ID in the write-up, then run desktop visual QA and send the requested `devrup`
   message.
8. Wire the shared `ModelRuntime` lifecycle into health, What-If, and evaluation. Return 429 +
   `Retry-After` while the analysis slot is busy, and keep the baked read-only dossier available
   when model preparation or uploaded evaluation fails.

**Acceptance:** a machine with only Git, Docker, and network access can clone and build the
`linux/amd64` image; it runs as UID 1000; `/api/health` reports the expected release ID, model
state, and evaluation capability; refreshing a deep case route works; no publish token is present in image
history or runtime environment; the sample upload returns release-bound model evidence without
leaving a file or server-side result behind.

## Code quality rules

- One standard-library structural/hash validator is shared by build, fetch, startup, and tests;
  one build-time semantic validator owns dataframe/parquet cross-file rules. Do not reproduce
  either rule set in shell or create a second Pydantic manifest schema.
- All paths are explicit parameters or environment variables; no hidden dependency on the
  caller's current directory.
- Generated release data is immutable. Only `.staging/` is mutable.
- Error messages name the release ID, file, expected value, and observed value.
- Use typed release exceptions (`ReleaseFormatError`, `ReleaseIntegrityError`,
  `ReleaseCompatibilityError`) internally. FastAPI startup logs the detailed exception and exits;
  HTTP responses expose bounded messages without filesystem paths or tokens.
- Keep publishing dependencies out of the serving lock. The publisher may use
  `huggingface_hub`; build and runtime fetch use the public HTTPS URL and standard library only.
- `UploadEvaluationService` is the only upload orchestrator. Parsing/normalization errors use
  stable machine codes plus bounded human messages; raw rows, filenames, and exception payloads
  never enter logs or error responses. Successful evaluation serialization is an explicit DTO
  allowlist, never a dataframe/dict dump.
- Derivation, preprocessing, scoring, assessment, and chart contracts stay in their existing
  modules. The evaluation service coordinates them; it does not duplicate formulas or thresholds.
- Percentile ranking and terminal-window quality classification are pure shared helpers. Bake,
  simulation, and upload code must not carry local variants.
- Pipeline diagnostics are recorded inside the existing core orchestrators under an opt-in
  collector. The evaluation service must not infer stage reasons by replaying filters.
- `ModelRuntime` owns model readiness and the shared analysis slot. Route handlers must not
  manipulate locks, retries, thread state, or model caches directly.
- File parsing, dataframe transforms, and model inference must not run on the async event loop;
  the one analysis slot bounds threadpool work while read endpoints remain responsive.
- One frontend API decoder owns bounded JSON/error parsing and `Retry-After`; route-specific
  clients must not discard structured errors or parse response bodies independently.
- `EvaluationResult` is distinct from `FlightDetail`. Reuse only neutral evidence components;
  never fabricate labels, case/operation identity, reports, or ground truth for uploaded data.
- The release pipeline diagram above should also appear as a short module comment in
  `backend/serve/release.py`; it is the non-obvious state transition being protected.
- The model lifecycle diagram belongs beside `ModelRuntime`; the upload pipeline diagram belongs
  in `backend/serve/evaluation.py`.

## Test coverage diagram

```text
CODE PATHS                                           DEPLOY / USER FLOWS

case_identity(segment_id)                            analyst opens stable case URL
├── known UTF-8/base32 vector [UNIT]                  ├── queue -> case [E2E]
├── order and membership independence [UNIT]          ├── operation -> sibling case [E2E]
├── corrected segment -> new identity [UNIT]          ├── deep-link refresh [E2E]
└── either-ID collision -> abort [UNIT]                └── simulation returns same case_id [E2E]

bind_cached_report(case)
├── all three digests match -> retain [UNIT]
├── evidence mismatch -> omit [UNIT]
├── prompt/generator mismatch -> omit [UNIT]
└── non-reviewable evidence -> abstention prose [UNIT]

build_release(staging)
├── complete build -> immutable producer path [UNIT]
├── interrupted before rename -> no visible release [UNIT]
├── duplicate identical release -> idempotent [UNIT]
├── duplicate ID/different bytes -> reject [UNIT]
├── missing/extra/cross-file reference -> reject [UNIT]
├── malformed JSON/parquet or hash/size mismatch -> reject [UNIT]
├── model/scaler contract mismatch -> reject [UNIT]
└── failure -> staging cleaned unless explicitly kept [UNIT]

load_model_artifacts(release)
├── tensor-only state dict + exact contract -> ready [INTEGRATION]
├── image/manifest derivation/preprocess version mismatch -> reject
├── cohort reference count/digest/formula mismatch -> reject [UNIT]
├── object-bearing checkpoint -> weights_only rejection [UNIT]
├── JSON scaler parity with training scaler [UNIT]
├── zero/non-finite/wrong-width scaler -> reject [UNIT]
└── missing/extra tensor key, shape, or dtype -> reject [UNIT]

publish_release(release)
├── deterministic archive across two runs [INTEGRATION]
├── dirty Git tree -> reject before upload [UNIT]
├── upload failure -> prior lock unchanged [UNIT]
├── immutable revision returned and recorded [INTEGRATION]
├── redownload mismatch -> prior lock unchanged [INTEGRATION]
└── verified publish -> atomic lock replacement [INTEGRATION]

fetch_locked_release(lock)
├── valid archive -> fixed runtime path [INTEGRATION]
├── HTTP/download failure -> non-zero build [INTEGRATION]
├── archive hash mismatch -> reject [UNIT]
├── path traversal/absolute member -> reject [UNIT]
├── link/device/duplicate member -> reject [UNIT]
├── extra/oversized/malformed manifest member -> reject [UNIT]
└── fixed runtime basename still trusts manifest release_id [UNIT]

FastAPI lifespan                                    clean-checkout linux/amd64 container
├── valid release -> release_ready [INTEGRATION]     ├── tracked files + public artifact build [CI]
├── missing/corrupt/unsupported -> startup fails     ├── runs as UID 1000 [CI]
├── health separates release/model/evaluation state  ├── serving lock regeneration has no diff [CI]
├── evaluation disabled -> endpoint/nav absent       ├── evaluation explicitly enabled [CI]
└── unknown /api/* -> JSON 404                        ├── /api/health expected release_id [CI]
                                                     ├── /assets/* and /case/<id> refresh [CI]
model lifecycle                                      ├── no wildcard CORS [CI]
├── not_loaded -> loading -> ready [INTEGRATION]      ├── zero-intensity parity [CI]
├── prepare is non-blocking + idempotent [INTEGRATION]├── sample CSV evaluation [CI]
├── loading + concurrent request -> 429/Retry-After   ├── upload temp directory empty [CI]
├── simulation/evaluation share one slot [INTEGRATION]└── no token in image/env/history [CI]
├── client timeout -> server load continues [INTEGRATION]
├── first failure -> bounded 503 + one retry [INTEGRATION]
└── retry failure -> terminal bounded 503 [INTEGRATION]

multipart request boundary                           analyst evaluates new data
├── valid single file under 10 MiB [INTEGRATION]      ├── open /evaluate -> prepare/poll [E2E]
├── missing/duplicate part -> 422 [INTEGRATION]       ├── select/drop valid CSV [E2E]
├── streamed body exceeds limit -> 413 [INTEGRATION]  ├── replace file mid-request -> stale ignored [E2E]
├── false/smaller Content-Length -> still bounded     ├── uploading/evaluating states [E2E]
├── idle/total body timeout -> 408 + cleanup           ├── honest indeterminate states only [E2E]
├── disconnect -> temp cleanup [INTEGRATION]          ├── multi-segment result selection [E2E]
└── busy slot -> 429 + Retry-After [INTEGRATION]      ├── clear result removes evidence [E2E]
                                                      ├── client-side JSON export [E2E]
parse_upload(file)                                    ├── invalid file shows actionable errors [E2E]
├── valid UTF-8 CSV + optional columns [UNIT]         ├── 429/503 recovery without lost baked view [E2E]
├── valid flat Parquet + primitive columns [UNIT]     ├── keyboard/screen-reader file workflow [E2E]
├── extension/media mismatch -> 415 [UNIT]            └── refresh explains ephemeral result loss [E2E]
├── duplicate/missing required column -> 422 [UNIT]
├── nested/unsupported Parquet type -> 422 [UNIT]
├── declared rows/uncompressed bytes exceed cap -> 413
├── malformed CSV/Parquet -> bounded 422 [UNIT]
├── invalid UTF-8/non-finite/out-of-range -> field 422
├── onground true/false/0/1 -> real bool; other/null -> 422 [UNIT]
├── exact duplicates collapse + count [UNIT]
├── conflicting (icao24,time) duplicate -> 422 [UNIT]
├── canonical dataset digest ignores row order/format [UNIT]
└── original filename/raw values never echoed or logged

normalize_and_preprocess(raw)
├── client-derived columns discarded [UNIT]
├── optional fields receive explicit defaults [UNIT]
├── structural null or ±Inf -> field 422 [UNIT]
├── sparse measured nulls -> masks/imputation/counters [UNIT]
├── all-null measured segment -> explicit rejection [UNIT]
├── epoch seconds accepted; milliseconds rejected [UNIT]
├── flight ID/phase/distance re-derived [INTEGRATION]
├── exact core preprocessing parity [INTEGRATION]
├── opt-in diagnostics do not change numerical output [REGRESSION]
├── empty/outside-LEMD/non-engaging/short -> exact reasons [UNIT]
├── impossible/missing counters preserved [UNIT]
├── 1..25 accepted segments -> continue [UNIT]
└── >25 segments -> reject whole upload [UNIT]

evaluate_uploaded_segments(clean)
├── baked case == uploaded raw observations parity [INTEGRATION]
├── batch score/reconstruction/attribution/quality assembled once [UNIT]
├── weak-ECDF percentile min/max/ties/shared parity [UNIT]
├── terminal-window quality helper shared with bake [UNIT]
├── deterministic order/format-independent evaluation_ref [UNIT]
├── EvaluationResult omits label/case/operation/report [UNIT]
├── response schema rejects non-allowlisted raw fields [UNIT]
├── release/model provenance returned [UNIT]
├── no report-cache lookup or runtime LLM [UNIT]
├── model error -> bounded 503 + cleanup [INTEGRATION]
└── response leaves release/queue/cases unchanged [INTEGRATION]

frontend API/error contract                          product-claim boundary
├── JSON error code/message/fields retained [UNIT]   ├── sample/template download -> upload [E2E]
├── Retry-After parsed and exposed [UNIT]             ├── public/no-confidential-data warning [E2E]
├── malformed/non-JSON body -> bounded fallback       ├── high score shown as model evidence [E2E]
└── all API functions use one decoder [REGRESSION]    └── no drone/authorization/incident verdict [E2E]
```

Required test locations:

- `backend/tests/test_case_identity.py` — known vectors, reorder/extension invariance,
  collision failure through an injected digest function.
- `backend/tests/test_release.py` — manifest, referential integrity, corruption, interrupted
  promotion, canonical manifest identity, deterministic archive bytes, strict extraction, and
  idempotency.
- `backend/tests/test_model_artifacts.py` — safe state-dict rejection/acceptance, tensor contract,
  JSON scaler validation, and fixed-vector parity.
- `backend/tests/test_publish_demo_release.py` — clean-tree gate, failed upload/redownload without
  lock mutation, immutable revision capture, and atomic successful lock update.
- `backend/tests/test_serve_app_factory.py` — clean import, lifespan success/failure, release
  ID health response, fixed runtime path, SPA fallback, API 404 precedence, and absent wildcard
  CORS.
- `backend/tests/test_upload_evaluation.py` — request streaming limit, multipart cleanup, CSV and
  Parquet schema/metadata matrices, raw normalization, preprocessing parity, segment caps,
  boolean encodings, exact/conflicting duplicate handling, canonical dataset digest, rejection
  reasons, deterministic references, provenance, no persistence, and no filename/raw data
  leakage. Cover disconnect during multipart and document/suppress stale responses when
  disconnect occurs during non-cancellable threadpool computation.
- Existing scoring/quality tests — add weak-ECDF minimum/maximum/tie vectors, baked/live/upload
  percentile parity, and shared terminal-window classification parity.
- `backend/tests/test_model_runtime.py` — non-blocking idempotent prepare, four states, one retry,
  shared simulation/evaluation admission, busy headers, and terminal failure.
- Existing backend operation/simulation tests — migrate from integer IDs to string case IDs.
- Existing frontend queue/operation/case/what-if/flow tests — assert string routes and stale
  request protection still work; add visible warming, busy, recoverable failure, and terminal
  failure states.
- `frontend/src/test/Evaluate.test.tsx` and API tests — file selection/drop, schema guidance,
  honest request states, replace/abort/stale response, multi-segment selection, upload-only DTO,
  bounded JSON/non-JSON errors, field issues, retry header, clear, JSON export, sample/template,
  public-data/product-claim copy, ephemeral refresh, and keyboard/screen-reader behavior.
- Container smoke script or CI job — build and run only from tracked files plus the public
  locked artifact; assert `linux/amd64`, UID 1000, serving-lock parity, token absence, static
  assets, API 404 precedence, deep links, health identity, simulation parity, valid sample upload,
  release provenance, and temporary-file cleanup.

The report-cache key changes but the prompt and report rubric do not. No LLM quality eval is
required for this actuation; deterministic report guard and cache-binding tests are required.
Uploaded files receive no generated prose, so upload tests assert the deterministic assessment
copy and explicit no-narrative state instead of adding an LLM eval.

## Engineering review findings absorbed

The user requested full-auto plan updates, so the recommended complete option was applied for
each finding below.

### Architecture

| Finding | Verified evidence | Resolution in this plan |
|---|---|---|
| **P1, confidence 10/10:** ignored bundle loading blocks clean checkout | `backend/serve/app.py:73`: `QUEUE, OPERATIONS, CASES, METRICS, MANIFEST = _load_bundle()` | Lifespan loads one explicit verified runtime release; import stays clean. |
| **P1, confidence 10/10:** current deployment starts the wrong app | `backend/Dockerfile:25`: `CMD ["uvicorn", "main:app", ...]` | Root multi-stage image starts `backend.serve.app:app` and includes the SPA. |
| **P1, confidence 9/10:** producer directory identity conflicts with a stable Docker mount | Prior plan required “directory name to match” and also `SADAR_RELEASE_DIR` without defining a dynamic image path. | Producer basename is enforced; runtime identity comes from the verified manifest at `/opt/sadar/release`. |
| **P1, confidence 10/10:** safe checkpoint work still left a pickle-backed scaler | `backend/serve/app.py:93`: `scaler = joblib.load(...)`; `backend/core/lstm_ae.py:236`: `weights_only=False` | Tensor-only state dict plus JSON scaler; no runtime object pickle. |
| **P1, confidence 9/10:** model cold load needs a real in-progress state | `backend/serve/app.py:292`: `SIMULATION_LOCK.acquire(blocking=False)`; observed learning records minutes cold vs ~95 ms warm. | Four-state lifecycle, 429 + `Retry-After`, one retry, and read-only availability. |
| **P1, confidence 10/10:** runtime inference is limited to baked cases | `backend/serve/app.py:288`: `case = CASES.get(str(request.id))`; line 296 selects only `cases_raw.parquet` rows matching that baked case. | Add bounded raw-file evaluation that derives, preprocesses, quality-checks, and scores new observations without mutating baked state. |
| **P1, confidence 10/10:** uploaded inference must use the training transform, not a UI-specific feature mapper | `backend/core/derivations.py` already owns `apply_derivations`; `backend/core/preprocessing.py:424` owns `preprocess`. | Reuse both leaf contracts and ignore/recompute uploaded derived columns. |
| **P1, confidence 9/10:** a public upload route creates a resource-exhaustion and data-retention boundary | The current app has no upload parser, request-size guard, or persistence policy. | Stream-count 10 MiB, inspect before materialization, cap rows/segments, serialize analysis, delete temp data in `finally`, and never log raw content. |
| **P1, confidence 9/10:** online input versions were provenance-only | The manifest recorded derivation/preprocessing versions while runtime loading required only schema v2. | Export image contract constants and fail release validation on any version mismatch. |
| **P1, confidence 10/10:** rounded queue JSON cannot be the exact live percentile reference | `backend/serve/app.py:79` reads queue scores; `backend/serve/precompute.py:227` rounds them to six decimals. | Ship a hash-bound full-precision float64-hex cohort reference and formula/tie policy. |
| **P1, confidence 10/10:** public uploads invalidate the prior no-auth rationale | Uploaded analyst telemetry is not necessarily the public baked course evidence. | Keep this release anonymous only with explicit public/no-confidential-data copy; private files require an authenticated deployment. |
| **P1, confidence 9/10:** Actuation 3 had no independent rollback mechanism | The gate promised route/page disablement but specified no capability flag. | Add fail-closed `SADAR_ENABLE_EVALUATION`, health capability, conditional navigation, and disabled-mode tests. |
| **P1, confidence 10/10:** uploaded evidence cannot reuse the ground-truth case DTO | `frontend/src/api.ts:106-142` requires labels/case/operation/report fields; `CaseFile.tsx:94-149` renders them as facts. | Add a separate `EvaluationResult` and reuse neutral evidence components only. |
| **P1, confidence 10/10:** upload scoring does not complete unauthorized-drone detection | `backend/serve/app.py:100` correctly identifies the current system as post-hoc trajectory anomaly triage; no identity/U-Space gate exists. | UI/export claims only trajectory conformance/anomaly evidence, never authorization or drone/incident verdicts. |
| **P1, confidence 10/10:** deployment security/runtime constraints were incomplete | `backend/Dockerfile:4`: `FROM python:3.11-slim`; no `USER`; Hugging Face Docker docs specify port 7860 and UID 1000. | Digest-pinned `linux/amd64`, UID 1000, port 7860, and publish-token separation. |
| **P2, confidence 10/10:** wildcard CORS is unnecessary for same-origin production | `backend/serve/app.py:102`: `allow_origins=["*"]` | Remove CORS and preserve JSON 404 precedence for `/api/*`. |

### Code quality

| Finding | Verified evidence | Resolution in this plan |
|---|---|---|
| **P1, confidence 9/10:** one “shared validator” would either duplicate logic or pull pandas into the fetch stage | Release semantics include parquet membership; the Docker fetch stage is specified as standard-library-only. | Split one structural/hash validator from one build-time semantic validator. |
| **P1, confidence 10/10:** the project dependency set is open-ended and too broad for serving | `backend/pyproject.toml` uses lower bounds and includes notebooks, geospatial, database, and training packages. | Add a minimal hashed Python 3.11 CPU-only `linux/amd64` serving lock with regeneration CI. |
| **P2, confidence 9/10:** release failures need stable internal categories and bounded public errors | Current startup performs raw file reads at `backend/serve/app.py:45-70`. | Typed format/integrity/compatibility errors; detailed logs, bounded HTTP text. |
| **P2, confidence 9/10:** publisher dependencies and secrets could leak into runtime | Publication and Docker fetch were previously described in one actuation without a dependency boundary. | Publisher may use Hub tooling; build/runtime fetch stays public HTTPS + standard library. |
| **P1, confidence 10/10:** precompute and live scoring cannot assemble different evidence shapes | `backend/serve/scoring.py:84-112` returns only a partial score frame while `backend/serve/precompute.py:285-315` separately assembles full case evidence. | Preserve vectorized inference; share `score_segments` and pure evidence assembly across bake, What-If, and uploads. |
| **P2, confidence 9/10:** upload orchestration could become a second preprocessing implementation | The existing derivation and preprocessing modules are already credential-free leaf modules. | One evaluation service coordinates existing functions; formulas and thresholds stay in their current modules. |
| **P1, confidence 10/10:** baked and live percentiles use different formulas | `backend/serve/precompute.py:211-214` assigns sorted `rank/(N-1)`; `backend/serve/scoring.py:156` counts `cohort_scores <= score`. | Freeze one inclusive weak-ECDF helper and test minimum, maximum, ties, and cross-path parity. |
| **P1, confidence 10/10:** terminal-quality parity is impossible while classification is nested in precompute | `backend/serve/precompute.py:169-182` defines `_is_terminal`; `backend/serve/quality.py:19-26` only consumes `terminal_op`. | Move terminal-window classification into `quality.py` and call it from bake and uploads. |
| **P1, confidence 9/10:** conflicting duplicate timestamps make upload results order-dependent | `backend/core/preprocessing.py:88-91` sorts then keeps the first duplicate `(flight_id,time)` without checking value conflicts. | Collapse exact duplicates, reject conflicting `(icao24,time)` rows, and derive evaluation identity from canonical normalized observations. |
| **P1, confidence 9/10:** CSV boolean strings can silently become true | `backend/core/derivations.py:51-53` uses `.astype(bool)`, so object string `"false"` is truthy. | Normalize only the explicit boolean/0/1 contract before derivation and reject other encodings. |
| **P1, confidence 10/10:** an all-finite rule would erase the training missingness contract | `backend/core/preprocessing.py:187-235` masks, imputes, and counts missing measured values. | Define structural non-null fields, nullable measured fields, infinity rejection, and sparse/all-null tests. |
| **P1, confidence 10/10:** current frontend API errors discard actionable detail | `frontend/src/api.ts:189-208` and `:252-259` retain only HTTP status. | Add one bounded decoder for code/message/fields/Retry-After and malformed/non-JSON fallback. |
| **P1, confidence 10/10:** “raw values never enter responses” contradicted the dossier payload | Evaluation responses intentionally contain processed path/channel evidence. | Prohibit raw content in logs/errors and enforce a successful-response evidence allowlist. |
| **P2, confidence 9/10:** synchronous evaluation cannot expose real stage percentages | One POST has no durable job/status channel. | Show honest indeterminate preparing/uploading/evaluating/done/error states only. |

### Tests and performance

- **P1, confidence 9/10:** the earlier 55-path diagram omitted the entire file boundary,
  parse/schema matrix, preprocessing parity, ephemeral result lifecycle, and evaluation UX.
  The revised diagram specifies more than 100 paths, including the full upload/evaluation matrix.
- **P1, confidence 9/10:** the prior plan had no measurable container budgets. It now gates
  startup, memory, image size, warm simulation p95, and read endpoint p95.
- **P1, confidence 10/10:** prewarming at startup would hide the observed cold-load cost by
  making every dossier user wait. Lazy single-flight loading remains, with visible state and
  independent read availability.
- **P2, confidence 9/10:** Docker cache invalidation was unspecified. Lock files are copied
  before source so dependency and artifact fetch layers survive source-only edits.
- **P1, confidence 9/10:** byte limits alone do not bound Parquet memory or response size.
  Metadata/row/segment caps, peak-RSS measurement, and an 8 MiB response gate now close that gap.
- **P1, confidence 9/10:** the published 50,000-row/25-segment maximum lacked a wall-time gate.
  Add a max-boundary latency gate and lower the public limits if synchronous execution misses it.
- **P1, confidence 8/10:** admission before parsing lets a slow client hold the analysis slot.
  Five-second idle and 60-second total body-read deadlines bound that exposure and return 408.
- **P1, confidence 9/10:** browser abort cannot cancel a running threadpool transform/model call.
  Tests distinguish cancellable multipart reads from stale-response suppression during compute;
  the slot and temp data are released when the background call actually completes.

## Production failure modes

| Failure | Detection and handling | User outcome |
|---|---|---|
| Artifact URL unavailable | Docker build/fetch exits non-zero; prior image remains deployed. | No broken partial release. |
| Archive tampered or truncated | Lock SHA-256 mismatch before extraction. | Deployment blocked. |
| One release file corrupt | Manifest validation fails at build and app startup. | Container never reports healthy. |
| Precompute killed mid-write | Staging is never referenced; final rename has not happened. | Existing immutable releases stay readable. |
| Case digest collision | Precompute aborts and names both segment IDs. | No ambiguous analyst reference ships. |
| Wrong schema/image pairing | Lifespan rejects unsupported schema version. | Clear startup error instead of malformed UI. |
| Image preprocessing code differs from release contract | Lifespan compares exported contract constants with manifest values and fails startup. | No upload is scored with a transform different from the model generation. |
| Deep React route refresh | SPA fallback serves `index.html`; `/api/*` remains API-only. | Shared case links open directly. |
| Simulation model is still cold-loading | State is `loading`; concurrent requests return 429 + `Retry-After`; client polling reads health. | Read-only dossier remains available and the analyst sees “model warming.” |
| Simulation client times out | Server load continues under the single-flight lock; response identity is still checked if it arrives. | Analyst can keep reading and retry after health reports `ready`. |
| Simulation model cannot load | State becomes `failed`; endpoint returns 503, logs detail, and permits one next-request retry. | Read-only dossier remains available; failure is visible. |
| Evidence changed but cached report did not | Report cache key includes canonical evidence digest, prompt digest, and generator version. | Stale prose is omitted rather than attached to new evidence. |
| Malicious pickle replaces model/scaler | Runtime accepts tensor-only `weights_only` state and JSON scaler only; hashes and contracts are checked first. | Container startup or lazy model load fails before object construction. |
| Runtime release is copied to a fixed path | Runtime validates manifest identity, not the directory basename; producer paths still enforce content naming. | Docker can use one stable environment path without weakening release identity. |
| Publish token leaks into build | Publisher is separate; Docker performs public unauthenticated download and token-absence CI scans image/env/history. | Public Space contains no release credential. |
| Public model work is spammed | Shared non-blocking analysis admission returns 429 instead of queueing simulation/evaluation work. | Read endpoints stay responsive; callers receive a retry signal. |
| Oversized body lies about `Content-Length` | ASGI receive wrapper counts actual streamed bytes and aborts above 10 MiB before multipart materialization. | Analyst sees 413; memory/disk use stays bounded. |
| Slow client holds the shared admission slot | Five-second idle and 60-second total body-read deadlines return 408 and clean the spool. | Other model work is delayed for a bounded interval, never indefinitely. |
| Parquet declares huge row groups or nested data | Metadata is inspected before reading; flat primitive schema, row, and declared-uncompressed limits are enforced. | Analyst sees a bounded schema/size error. |
| Uploaded derived columns disagree with raw telemetry | Server drops them and recomputes IDs, phase, distance, segmentation, and model features. | Results use the same transform as training rather than trusting client calculations. |
| Same timestamp contains conflicting observations | Typed normalization detects a repeated `(icao24,time)` with differing accepted values and rejects the upload. | No row-order-dependent “first value wins” score ships. |
| Same observations arrive reordered or as another supported format | Canonical normalized `dataset_digest` drives evaluation references; raw upload hash is provenance only. | The logical dataset keeps stable result references. |
| Upload contains no usable LEMD segment | Derivation/preprocessing returns explicit row/segment rejection counts. | Analyst sees why nothing could be evaluated and can fix the source file. |
| Upload creates more than 25 segments | Whole request is rejected before scoring; no silent subset or partial result. | Analyst can split the file intentionally. |
| Browser replaces a file during evaluation | Prior request is aborted and generation-token checked; late responses are discarded. | The page never shows results for the wrong file. |
| Browser disconnects during dataframe/model work | The response is suppressed, but the non-cancellable thread retains admission until completion and then runs cleanup. | No stale result appears; temporary data is deleted after actual task completion. |
| Evaluation fails after temp creation | All exit paths close and delete the spooled file in `finally`; CI asserts the temp directory is empty. | No server-side upload history remains. |
| Uploaded score is misread as an absolute safety verdict | UI labels the percentile as relative to the frozen cohort and preserves data-quality/coverage warnings. | Analyst sees model evidence with its limits, not a certification claim. |

## Performance and size budget

- Current serve data is about 24 MB; model + scaler add under 100 KB. The 128 MB clean frame
  and 10 MB metadata frame are build inputs and must not enter the image.
- Keep JSON gzip enabled. The immutable release is loaded once per worker; run one worker on
  the free Space to avoid duplicating the in-memory queue/cases payload.
- Archive download happens at image build, not on every process start.
- Generate the dedicated hashed `requirements-linux-x86_64.lock` from the minimal serving input
  in a Linux resolver. The repository-wide `uv.lock` remains intentionally uncommitted per team
  policy; CI proves regeneration is stable instead of relying on a developer's active environment.
- Record Python, PyTorch, scikit-learn, NumPy, pandas, and pyarrow versions in the model contract;
  startup enforces incompatible major versions and reports minor-version drift.
- Docker layer order copies the serving lock and release lock before application source, so
  dependency and public-artifact layers stay cached across frontend/backend-only edits.

Performance gates, measured inside the final `linux/amd64` container:

| Metric | Gate |
|---|---:|
| SPA + `/api/health` available | ≤ 10 s after process start |
| Idle resident memory after bundle load | ≤ 1 GiB, one worker |
| Final compressed image | ≤ 1.5 GiB |
| Warm zero-intensity simulation p95 over 20 runs | ≤ 2 s |
| Read endpoint p95 over 100 local requests | ≤ 250 ms |
| `/api/health` p95 while a max-boundary evaluation runs | ≤ 500 ms |
| Warm evaluation p95, 5,000 rows / ≤10 accepted segments over 10 runs | ≤ 10 s |
| Warm max-boundary evaluation, 50,000 rows / 25 segments, each of 3 runs | ≤ 30 s |
| Peak RSS during the 10 MiB / 50,000-row boundary test | ≤ 1.5 GiB |
| Successful evaluation response body | ≤ 8 MiB |
| Temp/admission cleanup after request or background compute completion | ≤ 1 s |

Record cold model-load time separately rather than hiding it in startup. `model/prepare` starts
it in the background only when an analyst enters a model feature. If it exceeds three minutes in
the final Space, profile import, parquet, checkpoint, and scaler phases independently before
changing the lazy contract; never block FastAPI startup or the baked dossier on model readiness.
If the 50,000-row/25-segment synchronous gate misses 30 seconds, lower the published row/segment
limits to the largest measured boundary that passes; do not ship limits the one-process product
cannot honor.

## Parallelization

| Step | Modules touched | Depends on |
|---|---|---|
| A. Identity contract | `backend/serve/`, `backend/tests/`, `frontend/src/` | — |
| B. Release + safe model artifacts | `backend/serve/`, `backend/scripts/`, `backend/tests/` | A |
| C. Evaluation backend + shared scorer | `backend/core/`, `backend/serve/`, `backend/tests/` | Model/release interfaces from B |
| D. Evaluation UI | `frontend/src/`, frontend tests/fixtures | API/error contract from C |
| E. Publisher + container skeleton | root container files, `.github/`, `backend/scripts/` | Manifest interface from B; serving lock includes C dependencies |
| F. Deployment verification | `.github/`, Space repo/config, `backend/docs/` | B + C + D + E |

Lane A runs first because every downstream artifact encodes its schema. Lane B follows within
`backend/serve/`. Once B freezes model/release interfaces, Lane C builds the shared runtime and
upload service while Lane E prepares Docker/CI around fixture manifests. Lane D starts after C
freezes API types and may then run in parallel with the rest of E. Merge C + D + E, generate and
publish one release, then run F.

Conflict flags:

- A, B, and C all touch `backend/serve/`; do not run those edits concurrently.
- B and E both touch `backend/scripts/`; assign packaging/publishing scripts to B until their
  interfaces are frozen, then let E consume them.
- A and D both touch `frontend/src/`; merge identity before evaluation routes/types/UI.
- C and D share generated/request-response types conceptually; freeze the API contract before
  parallel UI work to avoid a merge-by-guessing cycle.

## NOT in scope

- Runtime artifact hot-reload: immutable container restarts are simpler and safer for the demo.
- Runtime LLM report generation: retains cost, latency, and prompt-injection risk; reports stay baked.
- Database-backed case registry: stable content-derived IDs solve the current problem without a service.
- Authentication and multi-user authorization: this release is explicitly a public anonymous
  demo and warns against confidential/proprietary uploads. Any deployment intended for private
  analyst telemetry must add access control before enabling evaluation.
- Distributed simulation workers: one serialized CPU simulation is adequate for the demo.
- Durable upload history, shareable evaluation URLs, accounts, and server-side result storage:
  ephemeral evaluation proves the model feature without introducing a database/privacy product.
- ZIP, JSON, ADS-B exchange formats, arbitrary column mapping, and unit auto-detection: CSV and
  Parquet with one explicit SI/epoch schema keep preprocessing auditable.
- Background evaluation jobs and a durable work queue: bounded warm requests fit one process;
  admission returns 429 instead of pretending to offer multi-user throughput.
- Mobile/touch redesign and the deferred typography/token migration: unrelated to release integrity.
- Dual-model serving: remains a post-release stretch goal.
- A permanent identity across corrected/resegmented raw telemetry: no durable upstream event ID
  exists; a changed canonical segment is deliberately a new case.
- Production aviation claims, live ADS-B ingestion, continuous monitoring, and operational
  alerting: file evaluation is post-hoc analyst tooling, not a surveillance feed.
- Multi-architecture images: Hugging Face runs `linux/amd64`; adding arm64 doubles artifact and
  wheel validation without helping the deployment target.
- Artifact signing infrastructure: the committed Git lock, immutable Hub revision, and SHA-256
  verification are the trust boundary for this public course demo. Revisit signing only if artifacts
  are consumed outside this repository-controlled release flow.
- Model prewarming at process startup: observed cold load is too slow and would delay every
  read-only user; lazy single-flight loading keeps the dossier available.

## Implementation tasks

- [x] **T1 (P1, human: ~1 day / CC: ~45 min)** — Identity — replace positional IDs with the
  exact schema-v2 `case_id`/`case_ref` contract across bake, API, UI, docs, fixtures, and tests.
  - Surfaced by: architecture — numeric IDs currently derive from cohort position.
  - Files: `backend/serve/`, `backend/tests/`, `frontend/src/`.
  - Verify: known vectors, reorder/extension/correction cases, route flow, and collision abort.
- [x] **T2 (P1, human: ~1.5 days / CC: ~60 min)** — Release — add the standard-library
  manifest core, immutable staging, full referential validation, atomic promotion, cleanup, and
  deterministic archive packaging.
  - Surfaced by: architecture — current precompute writes one mutable ignored directory.
  - Files: `backend/serve/release.py`, `backend/serve/release_semantics.py`, precompute, release tests.
  - Verify: corruption matrix, interrupted promotion, duplicate IDs, deterministic bytes.
- [x] **T3 (P1, human: ~1 day / CC: ~45 min)** — Model artifacts — export tensor-only weights,
  JSON scaler, enforced online-transform versions, and full-precision cohort-reference contracts;
  reject pickle objects and model/scaler/statistical-reference drift.
  - Surfaced by: security/code quality — `weights_only` did not remove `scaler.joblib` risk.
  - Files: `backend/serve/model_artifacts.py`, precompute, scoring, model-artifact tests.
  - Verify: checkpoint object rejection, tensor metadata, scaler parity, transform-version
    mismatch, cohort digest/count/formula, and invalid-number cases.
- [x] **T4 (P1, human: ~0.5 day / CC: ~30 min)** — Reports — bind cached prose to canonical
  evidence, prompt, and generator digests before the schema-v2 bake.
  - Surfaced by: architecture — a report must prove it belongs to the shipped evidence.
  - Files: `backend/serve/report.py`, precompute, report tests.
  - Verify: matching retention, three mismatch omissions, deterministic abstention.
- [x] **T5 (P1, human: ~0.5 day / CC: ~30 min)** — Publication — publish transactionally,
  redownload/verify, and atomically replace the immutable lock without leaking `HF_TOKEN`.
  - Surfaced by: distribution — ignored serving data is unavailable to a clean checkout.
  - Files: `backend/scripts/`, `backend/serve/demo_bundle.lock.json`, publisher tests.
  - Verify: dirty tree, failed upload/redownload, immutable revision, unchanged prior lock.
  - Completed 2026-07-14: release `fb116d628a274309a387` was published publicly to
    `Txemapuch/sadar-demo-release` at immutable revision
    `11f998c76434bbaf443401e51e2070d105be7bdf`, redownload-verified, and pinned in
    `backend/serve/demo_bundle.lock.json`.
- [x] **T6 (P1, human: ~1 day / CC: ~60 min)** — Delivery — replace the legacy Dockerfile
  with a digest-pinned, non-root `linux/amd64` multi-stage image and tracked serving-only lock.
  - Surfaced by: architecture/performance — current image starts `main:app` and ships no SPA.
  - Files: root `Dockerfile`, `.dockerignore`, serving requirement locks, FastAPI static routes.
  - Verify: UID 1000, port 7860, image/lock budgets, same-origin SPA and JSON API 404.
- [x] **T7 (P1, human: ~0.5 day / CC: ~30 min)** — Model lifecycle — preserve
  non-blocking preparation and expose `not_loaded/loading/ready/failed`, one retry, shared
  analysis admission, 429 busy, and visible frontend recovery states.
  - Surfaced by: performance/prior learning — first model load may outlive the browser timeout.
  - Files: `backend/serve/model_runtime.py`, `backend/serve/app.py`, What-If UI, related tests.
  - Verify: prepare idempotency, capability disabled/enabled states, client timeout continuation,
    health transitions, shared busy retry header, terminal failure.
- [x] **T8 (P1, human: ~1.5 days / CC: ~75 min)** — Evaluation backend — add bounded
  multipart CSV/Parquet parsing, raw normalization, exact online preprocessing, shared complete
  scoring, deterministic evaluation references, provenance, and ephemeral cleanup.
  - Surfaced by: product/architecture — the model currently re-scores baked cases only.
  - Files: `backend/serve/evaluation.py`, shared scoring/runtime/app modules, core derivations,
    serving lock, backend tests.
  - Verify: format/schema/null/boolean/duplicate/deadline matrix, canonical digest,
    baked-vs-upload score/percentile/terminal-quality parity, upload-only DTO/allowlist,
    no persistence/log/error leakage, and resource caps.
- [x] **T9 (P1, human: ~1 day / CC: ~60 min)** — Evaluation UI — add `/evaluate`, model
  preparation/readiness, accessible file workflow, rejection summary, multi-segment dossier,
  shared structured-error decoding, cohort/privacy/product caveats, sample/template onboarding,
  abort/stale protection, clear action, and client-side JSON export.
  - Surfaced by: product — analysts need to apply the frozen model to their own observations.
  - Files: frontend routing/API/types, evaluation page/styles/tests, reused dossier components.
  - Verify: keyboard/drop/select flows, replacement race, 4xx/408/429/503 and malformed-body
    recovery, result switching, high-score non-verdict copy, sample round-trip, export, clear,
    disabled capability, and refresh behavior.
- [ ] **T10 (P1, human: ~1 day / CC: ~60 min)** — Verification — add clean-checkout CI,
  serving-lock regeneration, container security checks, performance budgets, and critical-flow
  smoke coverage.
  - Surfaced by: test review — unit suites do not prove the distributed application works.
  - Files: `.github/`, container smoke scripts, backend/frontend tests.
  - Verify: every path in the 100+ coverage diagram plus the eleven performance/size gates.
  - Status 2026-07-14: CI, smoke, latency, response-size, RSS, compressed-image, and cleanup
    gates are implemented; final `linux/amd64` execution awaits T5 and a Docker runner.
- [ ] **T11 (P1, human: ~0.5 day / CC: ~30 min)** — Release — deploy the pinned inputs to the
  Space, run live desktop visual QA, record rollback evidence, reconcile Issue #31, and notify
  `devrup`.
  - Surfaced by: distribution — code is incomplete until the exact public artifact is running.
  - Files: Space config/repo, `backend/docs/writeup/`, Issue #31 checklist.
  - Verify: live release ID, deep links, sample upload/evaluation/export, read-only case during
    model warming, cleanup evidence, and prior-revision rollback.

## Definition of done

- [x] Stable case IDs pass reorder and extension tests.
- [x] Documentation states that corrected/resegmented telemetry creates a new case identity.
- [x] Release builder cannot expose a partial or mixed generation.
- [x] Every shipped file is hash-verified against schema v2 manifest metadata.
- [x] Runtime loads no unrestricted model or scaler pickle.
- [ ] Clean checkout backend test collection does not require local ignored files.
- [ ] Clean checkout Docker build needs no untracked local input.
- [x] Serving-only Linux dependency lock regenerates with no diff in CI.
- [ ] Container smoke checks UID/platform, token absence, health, deep SPA routing, API 404,
  case response, and zero-intensity parity.
- [x] `/api/health` exposes deployed release/schema identity and the four-state model status.
- [x] Public simulation returns 429 while busy and never queues unbounded work.
- [x] `/api/model/prepare` is non-blocking/idempotent and simulation/evaluation share one bounded
  analysis slot.
- [x] CSV and Parquet upload limits are enforced on streamed bytes, metadata, rows, schema, and
  accepted segments before unbounded materialization or scoring.
- [x] Uploaded raw observations pass through the exact core derivation/preprocessing contract;
  client-derived columns are ignored.
- [x] Runtime rejects a release whose input/derivation/preprocessing versions or full-precision
  cohort statistical reference do not match the image/model contract.
- [x] Exact duplicates are counted/collapsed, conflicting timestamp observations are rejected,
  and canonical dataset/evaluation references ignore row order and CSV/Parquet container format.
- [ ] Baked-vs-upload parity proves one segment receives the same score, reconstruction,
  attribution, terminal quality assessment, inclusive weak-ECDF percentile, and thresholds.
- [x] `/evaluate` handles readiness, upload, rejection reasons, multiple results, JSON export,
  shared structured errors, sample/template onboarding, abort/replacement, clear, and ephemeral
  refresh states accessibly without fake progress percentages.
- [ ] Uploads never mutate release/queue/cases/reports and leave no temp file or server-side result.
- [x] `EvaluationResult` and its serializer contain no ground-truth label, case/operation/report
  fields, or non-allowlisted raw payload; UI/export make no authorization/drone/incident claim.
- [x] Public-demo copy rejects the expectation of private handling and warns not to upload
  confidential/proprietary data; evaluation is fail-closed behind its deployment capability.
- [ ] Eleven performance/size gates pass in the final `linux/amd64` image.
- [ ] Hugging Face Space is live and visually approved on desktop.
- [ ] Deployment URL and release ID are recorded in project documentation.
- [ ] Issue #31 checklist is reconciled and `devrup` is notified.

## Review completion summary

- Step 0: user-expanded scope accepted as four stacked, rollback-safe actuations; completeness
  was not cut.
- Architecture review: 16 issues found and folded into the plan.
- Code quality review: 14 issues found and folded into the plan.
- Test review: the coverage diagram specifies more than 100 code, integration, container, and
  analyst paths; every identified gap is an implementation requirement.
- Performance review: eight issues found; eleven measurable container/resource gates are mandatory.
- NOT in scope and What already exists: written.
- Backlog: this plan is the task source; no duplicate `TODOS.md` entries are proposed.
- Failure modes: zero silent, untested critical gaps remain in the plan.
- Outside voice: current independent pass found 17 upload/evaluation gaps; all were verified and
  folded into the plan. The prior release-focused pass's 13 findings remain absorbed.
- Design review: `/evaluate` moved from an API-centric description to a complete product journey.
  Information architecture 5→10, state coverage 6→10, journey 4→9, AI-slop resistance 8→10,
  design-system alignment 8→10, and responsive/accessibility 6→10. Seven design decisions were
  fixed in the plan; zero remain unresolved. The image mockup path was unavailable because the
  configured gstack designer has no API key, so the approved Forensic Dossier prototypes and the
  new ASCII workspace/state specification are the implementation references.
- Parallelization: six dependency steps; evaluation backend and container skeleton can run in
  parallel after release interfaces freeze, then evaluation UI can overlap final container work.
- Lake score: 31/31 review recommendations chose the complete option under full-auto.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | USER DECIDED | Upload evaluation explicitly added as product scope |
| Outside Voice | automatic independent challenge | Missed assumptions | 3 | CLEAR | Current 17 + prior 13 findings absorbed |
| Eng Review | `/plan-eng-review` | Architecture and tests | 3 | CLEAR | 38 findings folded, 100+ test paths, 0 critical gaps |
| Design Review | `/plan-design-review` + `/design-review` | UI/UX gaps | 2 | CLEAR | Score 6/10 → 9/10; 7 decisions fixed, 0 unresolved |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Clean-checkout CI and lock regeneration are covered by Eng Review |

**OUTSIDE VOICE:** The current pass required enforced online-transform compatibility, one exact
percentile/reference contract, shared terminal quality, deterministic duplicate handling,
resource/privacy boundaries, an upload-only DTO, honest API states, and a feature kill switch.

**CROSS-REVIEW:** The prior release review, current engineering pass, and independent upload pass
agree on the dependency order: identity → immutable release/model interfaces → bounded upload
evaluation → clean-checkout delivery. No unresolved tension remains.

**VERDICT:** ENG + DESIGN CLEARED — ready to implement as four stacked actuations; run live
`/design-review` after `/evaluate` is implemented and deployed.

NO UNRESOLVED DECISIONS
