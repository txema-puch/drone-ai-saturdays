# Issue #31 — SADAR application release hardening

**Status:** reviewed and implementation-ready
**Date:** 2026-07-14
**Branch:** `task-sadar-merge-c`
**Scope:** close the release-blocking findings from the full application review

## Goal

A clean checkout must be able to build and start the complete analyst application from a
version-pinned public artifact. Every process must observe one internally consistent model,
evidence, report, and identifier generation. Published case links must remain stable when the
cohort is reordered or regenerated without changing the segment's canonical identity.

This is a course-demo deployment, not a production counter-drone system. The target is one
Docker image on Hugging Face Spaces, one immutable release artifact, and one reproducible
smoke-test path.

## Scope challenge

The four critical review findings reduce to three implementation units:

1. **Stable identity contract** — replace sequence-position case IDs before baking another
   artifact.
2. **Immutable release builder** — stage, validate, hash, and atomically promote a complete
   model/evidence/report generation.
3. **Clean-checkout delivery** — fetch the pinned artifact, build the React and FastAPI image,
   and smoke-test the exact container that will run on the Space.

Packaging and atomic promotion are one boundary, not separate systems. Building a second
registry service, database, queue, or runtime report generator would add machinery without
improving this static demo.

The plan crosses more than eight files because the identity contract is shared by the bake,
API, UI, tests, and deployment. Reduce merge risk through three stacked actuations, not by
dropping a layer. Each actuation must end with its scoped tests green and its own rollback
commit. Only Actuation 3 is publicly deployable; Actuations 1 and 2 are internal gates and do
not require compatibility with the ignored legacy bundle.

| Gate | Ends with | Rollback |
|---|---|---|
| 1. Identity | Schema-v2 fixtures and backend/frontend identity tests pass | Revert the identity commit; no public URL exists yet |
| 2. Release | One locally verified immutable schema-v2 release | Select the prior local release directory; no lock file changes |
| 3. Delivery | One committed lock and one verified Space revision | Revert the lock/image commit or redeploy the prior Space revision |

## What already exists

| Existing component | Reuse decision |
|---|---|
| `backend/serve/precompute.py` | Keep as the sole evidence/model bake; change only its output protocol. |
| `backend/serve/scoring.py` | Keep as the shared build-time and simulation scoring contract. |
| `backend/serve/report.py` | Keep reports offline and baked; never add a production LLM call. |
| `backend/serve/operations.py` | Keep operation grouping; make the case identity helper live here. |
| `backend/serve/app.py` | Keep one FastAPI process; load one verified release and serve the SPA. |
| `frontend/` | Keep the current Vite build and relative `/api` client. |
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
    └── model-contract.json
```

`release-manifest.json` contains:

- `schema_version` (start at `2` because case identity changes)
- `release_id`
- source commit plus SHA-256 values for every ignored build input
- prompt fingerprint and report coverage count
- frozen scoring contract (`T`, threshold, step threshold, feature names)
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

The release validator constructs the model from the JSON architecture, checks every tensor
key/shape/dtype before `load_state_dict`, and runs a fixed-vector scaler parity test against the
training artifact during the bake. This replaces the current unrestricted `joblib.load` and
checkpoint-object load while preserving the frozen numerical contract.

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
  ├── verify required files and SHA-256 values
  ├── load queue/operations/cases/metrics once
  └── publish immutable state to app.state.release

request
  └── read app.state.release only; never switch release mid-process
```

Module import must not read ignored files. A missing or corrupt release fails startup with a
single actionable error naming the absent file or bad hash. This makes test collection work
on a clean checkout while keeping deployment fail-fast.

The simulation model and scaler stay lazy inside the selected immutable release. A running
process never changes releases; rollback means starting the prior image or release ID.

Simulation readiness is an explicit state machine because the observed first load can take
minutes while warmed calls complete in about 95 ms:

```text
not_loaded ──first simulate──> loading ──success──> ready
                                  │
                                  └──error──> failed(retry_remaining=1)
                                                  │
                                      next request retries once
                                                  │
                                  success ─────────┴──> ready
                                  error ──────────────> failed(retry_remaining=0)
```

The current non-blocking single-flight lock is retained. While state is `loading`, concurrent
requests return HTTP 429 with `Retry-After`; a browser timeout never implies that server-side
loading stopped. A failed load returns HTTP 503 with a bounded public message, records detail in
server logs, and retries only when `retry_remaining` is one. `/api/health` always reports release
readiness separately from `simulation_state` and `simulation_retry_remaining`, so model loading
or failure never blocks the read-only dossier.

Production is same-origin. Remove wildcard CORS instead of carrying a cross-origin trust surface
the deployed application does not use. Unknown `/api/*` paths return JSON 404 responses and must
never fall through to the SPA.

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
   - fixed-vector output from `FrozenStandardScaler` matches the training `StandardScaler` within
     `1e-12` absolute tolerance.
4. Export the tensor-only state dict, model contract, and JSON scaler described above. Validate
   them before calculating any release hash; no `joblib` or unrestricted checkpoint pickle is
   accepted by the runtime.
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

### Actuation 3 — Clean-checkout image and Space deployment (P1)

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
   intensity simulation. Regenerate the serving lock in a clean Linux resolver and fail if the
   committed lock differs.
6. Pin Node/Python/uv base images by digest and target `linux/amd64`, the Hugging Face runtime
   platform. CI and Hugging Face rebuild the same Dockerfile from the same locked inputs; do not
   claim they run the same image digest.
7. Deploy that image definition to the Hugging Face Docker Space. Record the Space URL
   and release ID in the write-up, then run desktop visual QA and send the requested `devrup`
   message.
8. Preserve the existing non-blocking simulation lock, expose the four-state load lifecycle,
   return 429 + `Retry-After` while busy, and make the What-If UI show “model warming” or
   “simulation unavailable” without hiding the read-only case.

**Acceptance:** a machine with only Git, Docker, and network access can clone and build the
`linux/amd64` image; it runs as UID 1000; `/api/health` reports the expected release ID and
simulation state; refreshing a deep case route works; no publish token is present in image
history or runtime environment.

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
- The release pipeline diagram above should also appear as a short module comment in
  `backend/serve/release.py`; it is the non-obvious state transition being protected.
- The simulation lifecycle diagram belongs beside the state container in `backend/serve/app.py`.

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
├── health separates release/simulation state        ├── serving lock regeneration has no diff [CI]
└── unknown /api/* -> JSON 404                        ├── /api/health expected release_id [CI]
                                                     ├── /assets/* and /case/<id> refresh [CI]
simulation lifecycle                                 ├── no wildcard CORS [CI]
├── not_loaded -> loading -> ready [INTEGRATION]      ├── zero-intensity parity [CI]
├── loading + concurrent request -> 429/Retry-After   └── no token in image/env/history [CI]
├── client timeout -> server load continues [INTEGRATION]
├── first failure -> bounded 503 + one retry [INTEGRATION]
└── retry failure -> terminal bounded 503 [INTEGRATION]
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
- Existing backend operation/simulation tests — migrate from integer IDs to string case IDs.
- Existing frontend queue/operation/case/what-if/flow tests — assert string routes and stale
  request protection still work; add visible warming, busy, recoverable failure, and terminal
  failure states.
- Container smoke script or CI job — build and run only from tracked files plus the public
  locked artifact; assert `linux/amd64`, UID 1000, serving-lock parity, token absence, static
  assets, API 404 precedence, deep links, health identity, and simulation parity.

The report-cache key changes but the prompt and report rubric do not. No LLM quality eval is
required for this actuation; deterministic report guard and cache-binding tests are required.

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
| **P1, confidence 10/10:** deployment security/runtime constraints were incomplete | `backend/Dockerfile:4`: `FROM python:3.11-slim`; no `USER`; Hugging Face Docker docs specify port 7860 and UID 1000. | Digest-pinned `linux/amd64`, UID 1000, port 7860, and publish-token separation. |
| **P2, confidence 10/10:** wildcard CORS is unnecessary for same-origin production | `backend/serve/app.py:102`: `allow_origins=["*"]` | Remove CORS and preserve JSON 404 precedence for `/api/*`. |

### Code quality

| Finding | Verified evidence | Resolution in this plan |
|---|---|---|
| **P1, confidence 9/10:** one “shared validator” would either duplicate logic or pull pandas into the fetch stage | Release semantics include parquet membership; the Docker fetch stage is specified as standard-library-only. | Split one structural/hash validator from one build-time semantic validator. |
| **P1, confidence 10/10:** the project dependency set is open-ended and too broad for serving | `backend/pyproject.toml` uses lower bounds and includes notebooks, geospatial, database, and training packages. | Add a minimal hashed Python 3.11 CPU-only `linux/amd64` serving lock with regeneration CI. |
| **P2, confidence 9/10:** release failures need stable internal categories and bounded public errors | Current startup performs raw file reads at `backend/serve/app.py:45-70`. | Typed format/integrity/compatibility errors; detailed logs, bounded HTTP text. |
| **P2, confidence 9/10:** publisher dependencies and secrets could leak into runtime | Publication and Docker fetch were previously described in one actuation without a dependency boundary. | Publisher may use Hub tooling; build/runtime fetch stays public HTTPS + standard library. |

### Tests and performance

- **P1, confidence 9/10:** the prior 25-path diagram omitted safe model/scaler rejection,
  publication rollback, runtime-path independence, non-root/token checks, and cold-load UX.
  The revised diagram specifies 55 paths, including 30 newly explicit gaps.
- **P1, confidence 9/10:** the prior plan had no measurable container budgets. It now gates
  startup, memory, image size, warm simulation p95, and read endpoint p95.
- **P1, confidence 10/10:** prewarming at startup would hide the observed cold-load cost by
  making every dossier user wait. Lazy single-flight loading remains, with visible state and
  independent read availability.
- **P2, confidence 9/10:** Docker cache invalidation was unspecified. Lock files are copied
  before source so dependency and artifact fetch layers survive source-only edits.

## Production failure modes

| Failure | Detection and handling | User outcome |
|---|---|---|
| Artifact URL unavailable | Docker build/fetch exits non-zero; prior image remains deployed. | No broken partial release. |
| Archive tampered or truncated | Lock SHA-256 mismatch before extraction. | Deployment blocked. |
| One release file corrupt | Manifest validation fails at build and app startup. | Container never reports healthy. |
| Precompute killed mid-write | Staging is never referenced; final rename has not happened. | Existing immutable releases stay readable. |
| Case digest collision | Precompute aborts and names both segment IDs. | No ambiguous analyst reference ships. |
| Wrong schema/image pairing | Lifespan rejects unsupported schema version. | Clear startup error instead of malformed UI. |
| Deep React route refresh | SPA fallback serves `index.html`; `/api/*` remains API-only. | Shared case links open directly. |
| Simulation model is still cold-loading | State is `loading`; concurrent requests return 429 + `Retry-After`; client polling reads health. | Read-only dossier remains available and the analyst sees “model warming.” |
| Simulation client times out | Server load continues under the single-flight lock; response identity is still checked if it arrives. | Analyst can keep reading and retry after health reports `ready`. |
| Simulation model cannot load | State becomes `failed`; endpoint returns 503, logs detail, and permits one next-request retry. | Read-only dossier remains available; failure is visible. |
| Evidence changed but cached report did not | Report cache key includes canonical evidence digest, prompt digest, and generator version. | Stale prose is omitted rather than attached to new evidence. |
| Malicious pickle replaces model/scaler | Runtime accepts tensor-only `weights_only` state and JSON scaler only; hashes and contracts are checked first. | Container startup or lazy model load fails before object construction. |
| Runtime release is copied to a fixed path | Runtime validates manifest identity, not the directory basename; producer paths still enforce content naming. | Docker can use one stable environment path without weakening release identity. |
| Publish token leaks into build | Publisher is separate; Docker performs public unauthenticated download and token-absence CI scans image/env/history. | Public Space contains no release credential. |
| Public simulation is spammed | Existing non-blocking single-flight returns 429 instead of queueing work. | Read endpoints stay responsive; callers receive a retry signal. |

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

Record cold model-load time separately rather than hiding it in startup. If it exceeds three
minutes in the final Space, open a follow-up optimization only after profiling import, parquet,
checkpoint, and scaler phases independently; do not prewarm at startup and block the dossier.

## Parallelization

| Step | Modules touched | Depends on |
|---|---|---|
| A. Identity contract | `backend/serve/`, `backend/tests/`, `frontend/src/` | — |
| B. Release + safe model artifacts | `backend/serve/`, `backend/scripts/`, `backend/tests/` | A |
| C. Publisher + container skeleton | root container files, `.github/`, `backend/scripts/` | Manifest interface from B; final artifact waits for B |
| D. Simulation-state UX | `backend/serve/`, `frontend/src/`, their tests | State contract from B |
| E. Deployment verification | `.github/`, Space repo/config, `backend/docs/` | B + C + D |

Lane A runs first because every downstream artifact encodes its schema. After A, run Lane B
sequentially within `backend/serve/`. Lane C may prepare the Docker/CI skeleton against fixture
manifests while B finishes. Lane D may start once B freezes the health/simulation contract.
Merge B + C + D, generate and publish one release, then run E.

Conflict flags:

- A, B, and D all touch `backend/serve/`; do not run those edits concurrently.
- B and C both touch `backend/scripts/`; assign packaging/publishing scripts to B until their
  interfaces are frozen, then let C consume them.
- A and D both touch `frontend/src/`; merge identity before warming/error-state UI.

## NOT in scope

- Runtime artifact hot-reload: immutable container restarts are simpler and safer for the demo.
- Runtime LLM report generation: retains cost, latency, and prompt-injection risk; reports stay baked.
- Database-backed case registry: stable content-derived IDs solve the current problem without a service.
- Authentication and multi-user authorization: the Space contains public course-demo evidence only.
- Distributed simulation workers: one serialized CPU simulation is adequate for the demo.
- Mobile/touch redesign and the deferred typography/token migration: unrelated to release integrity.
- Dual-model serving: remains a post-release stretch goal.
- A permanent identity across corrected/resegmented raw telemetry: no durable upstream event ID
  exists; a changed canonical segment is deliberately a new case.
- Production aviation claims, live ADS-B ingestion, and operational alerting: explicitly outside the
  course-deliverable product claim.
- Multi-architecture images: Hugging Face runs `linux/amd64`; adding arm64 doubles artifact and
  wheel validation without helping the deployment target.
- Artifact signing infrastructure: the committed Git lock, immutable Hub revision, and SHA-256
  verification are the trust boundary for this public course demo. Revisit signing only if artifacts
  are consumed outside this repository-controlled release flow.
- Model prewarming at process startup: observed cold load is too slow and would delay every
  read-only user; lazy single-flight loading keeps the dossier available.

## Implementation tasks

- [ ] **T1 (P1, human: ~1 day / CC: ~45 min)** — Identity — replace positional IDs with the
  exact schema-v2 `case_id`/`case_ref` contract across bake, API, UI, docs, fixtures, and tests.
  - Surfaced by: architecture — numeric IDs currently derive from cohort position.
  - Files: `backend/serve/`, `backend/tests/`, `frontend/src/`.
  - Verify: known vectors, reorder/extension/correction cases, route flow, and collision abort.
- [ ] **T2 (P1, human: ~1.5 days / CC: ~60 min)** — Release — add the standard-library
  manifest core, immutable staging, full referential validation, atomic promotion, cleanup, and
  deterministic archive packaging.
  - Surfaced by: architecture — current precompute writes one mutable ignored directory.
  - Files: `backend/serve/release.py`, `backend/serve/release_semantics.py`, precompute, release tests.
  - Verify: corruption matrix, interrupted promotion, duplicate IDs, deterministic bytes.
- [ ] **T3 (P1, human: ~1 day / CC: ~45 min)** — Model artifacts — export tensor-only weights
  and JSON scaler contracts; reject pickle objects and model/scaler drift.
  - Surfaced by: security/code quality — `weights_only` did not remove `scaler.joblib` risk.
  - Files: `backend/serve/model_artifacts.py`, precompute, scoring, model-artifact tests.
  - Verify: checkpoint object rejection, tensor metadata, scaler parity and invalid-number cases.
- [ ] **T4 (P1, human: ~0.5 day / CC: ~30 min)** — Reports — bind cached prose to canonical
  evidence, prompt, and generator digests before the schema-v2 bake.
  - Surfaced by: architecture — a report must prove it belongs to the shipped evidence.
  - Files: `backend/serve/report.py`, precompute, report tests.
  - Verify: matching retention, three mismatch omissions, deterministic abstention.
- [ ] **T5 (P1, human: ~0.5 day / CC: ~30 min)** — Publication — publish transactionally,
  redownload/verify, and atomically replace the immutable lock without leaking `HF_TOKEN`.
  - Surfaced by: distribution — ignored serving data is unavailable to a clean checkout.
  - Files: `backend/scripts/`, `backend/serve/demo_bundle.lock.json`, publisher tests.
  - Verify: dirty tree, failed upload/redownload, immutable revision, unchanged prior lock.
- [ ] **T6 (P1, human: ~1 day / CC: ~60 min)** — Delivery — replace the legacy Dockerfile
  with a digest-pinned, non-root `linux/amd64` multi-stage image and tracked serving-only lock.
  - Surfaced by: architecture/performance — current image starts `main:app` and ships no SPA.
  - Files: root `Dockerfile`, `.dockerignore`, serving requirement locks, FastAPI static routes.
  - Verify: UID 1000, port 7860, image/lock budgets, same-origin SPA and JSON API 404.
- [ ] **T7 (P1, human: ~0.5 day / CC: ~30 min)** — Simulation lifecycle — preserve
  single-flight behavior and expose `not_loaded/loading/ready/failed`, one retry, 429 busy, and
  visible frontend recovery states.
  - Surfaced by: performance/prior learning — first model load may outlive the browser timeout.
  - Files: `backend/serve/app.py`, `frontend/src/components/WhatIfPanel.tsx`, related tests.
  - Verify: client timeout continuation, health transitions, busy retry header, terminal failure.
- [ ] **T8 (P1, human: ~1 day / CC: ~60 min)** — Verification — add clean-checkout CI,
  serving-lock regeneration, container security checks, performance budgets, and critical-flow
  smoke coverage.
  - Surfaced by: test review — unit suites do not prove the distributed application works.
  - Files: `.github/`, container smoke scripts, backend/frontend tests.
  - Verify: all 55 paths in the coverage diagram plus the five performance gates.
- [ ] **T9 (P1, human: ~0.5 day / CC: ~30 min)** — Release — deploy the pinned inputs to the
  Space, run live desktop visual QA, record rollback evidence, reconcile Issue #31, and notify
  `devrup`.
  - Surfaced by: distribution — code is incomplete until the exact public artifact is running.
  - Files: Space config/repo, `backend/docs/writeup/`, Issue #31 checklist.
  - Verify: live release ID, deep link, read-only case during model warming, prior-revision rollback.

## Definition of done

- [ ] Stable case IDs pass reorder and extension tests.
- [ ] Documentation states that corrected/resegmented telemetry creates a new case identity.
- [ ] Release builder cannot expose a partial or mixed generation.
- [ ] Every shipped file is hash-verified against schema v2 manifest metadata.
- [ ] Runtime loads no unrestricted model or scaler pickle.
- [ ] Clean checkout backend test collection does not require local ignored files.
- [ ] Clean checkout Docker build needs no untracked local input.
- [ ] Serving-only Linux dependency lock regenerates with no diff in CI.
- [ ] Container smoke checks UID/platform, token absence, health, deep SPA routing, API 404,
  case response, and zero-intensity parity.
- [ ] `/api/health` exposes deployed release/schema identity and the four-state simulation status.
- [ ] Public simulation returns 429 while busy and never queues unbounded work.
- [ ] Five performance gates pass in the final `linux/amd64` image.
- [ ] Hugging Face Space is live and visually approved on desktop.
- [ ] Deployment URL and release ID are recorded in project documentation.
- [ ] Issue #31 checklist is reconciled and `devrup` is notified.

## Review completion summary

- Step 0: scope reduced into three stacked, rollback-safe actuations; completeness was not cut.
- Architecture review: seven issues found and folded into the plan.
- Code quality review: four issues found and folded into the plan.
- Test review: the coverage diagram now specifies 55 paths; 30 previously implicit gaps are
  explicit implementation requirements.
- Performance review: three issues found; five measurable container gates are now mandatory.
- NOT in scope and What already exists: written.
- Backlog: this plan is the task source; no duplicate `TODOS.md` entries are proposed.
- Failure modes: zero silent, untested critical gaps remain in the plan.
- Outside voice: current Codex process returned no text after two delivery methods; the prior
  successful Codex pass's 13 findings remain absorbed and traceable.
- Parallelization: five dependency steps, with container skeleton and simulation UX preparation
  parallel only after their release interfaces are frozen.
- Lake score: 14/14 internal recommendations chose the complete option under full-auto.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | — | Not required for release hardening |
| Codex Plan Review | automatic outside voice | Independent challenge | 2 | PRIOR CLEAR / CURRENT UNAVAILABLE | Prior 13 findings absorbed; current process returned no review text |
| Eng Review | `/plan-eng-review` | Architecture and tests | 2 | CLEAR | 44 findings/gaps folded, 55 test paths, 0 critical gaps |
| Design Review | `/plan-design-review` + `/design-review` | UI/UX gaps | 2 | CONTEXT ONLY | Formal plan review is stale; recent visual audit reached B+ before the new warming/error states |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Clean-checkout CI and lock regeneration are covered by Eng Review |

**CODEX:** The prior successful pass required canonical manifest identity, bounded segment
identity, evidence-bound reports, strict extraction, and transactional publishing. This run was
unavailable after both argument and stdin delivery returned no text.

**CROSS-MODEL:** The successful prior outside voice and both engineering passes agree on the
dependency order: identity → immutable artifact → clean-checkout delivery. No new tension could
be evaluated from the unavailable current run.

**VERDICT:** ENG CLEARED — ready to implement as three stacked actuations; the current outside-
voice failure is recorded and non-blocking.

NO UNRESOLVED DECISIONS
