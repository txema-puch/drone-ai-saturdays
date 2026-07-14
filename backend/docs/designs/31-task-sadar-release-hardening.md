# Issue #31 — SADAR application release hardening

**Status:** planned  
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

## What already exists

| Existing component | Reuse decision |
|---|---|
| `backend/serve/precompute.py` | Keep as the sole evidence/model bake; change only its output protocol. |
| `backend/serve/scoring.py` | Keep as the shared build-time and simulation scoring contract. |
| `backend/serve/report.py` | Keep reports offline and baked; never add a production LLM call. |
| `backend/serve/operations.py` | Keep operation grouping; make the case identity helper live here. |
| `backend/serve/app.py` | Keep one FastAPI process; load one verified release and serve the SPA. |
| `frontend/` | Keep the current Vite build and relative `/api` client. |
| `backend/models/phase6/lstm_ae_best.pt` and `scaler.joblib` | Copy only these serve-time model files into the release; do not ship the 138 MB training frames. |
| Hugging Face Spaces target | Use a public pinned artifact URL plus Docker Space; no new registry vendor. |

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
    ├── lstm_ae_best.pt
    ├── scaler.joblib
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
recomputes this value and requires the directory name to match. A release directory is never
edited after promotion; publication time belongs in the external lock/publication record.

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

Simulation readiness is an explicit state machine: `not_loaded` at startup, `ready` after the
first successful lazy load, or `failed` after a load error. A failed load returns HTTP 503 with
a bounded public message, records the detailed exception in server logs, and may retry once on
the next request. `/api/health` exposes the state without exposing filesystem details.

## Implementation sequence

### Actuation 1 — Stable identity contract (P1)

1. Add deterministic `case_id` and `case_ref` helpers with collision detection.
2. Bake those identifiers into every queue row before operation grouping.
3. Key `cases.json` by `case_id`; replace numeric operation summary fields.
4. Change `/api/flights/{case_id}` and `SimulationRequest.case_id` to strings.
5. Update TypeScript contracts, routes, navigation, and component props to `case_id`.
6. Rebuild fixtures and assert the same segment keeps the same identifiers across reordered
   inputs.

**Acceptance:** reversing or extending the cohort does not change any existing segment's
case ID, case reference, or URL.

### Actuation 2 — Immutable atomic release (P1)

1. Add `backend/serve/release.py` with canonical hashing, manifest validation,
   `ReleaseStore`, staging, promotion, and archive helpers.
2. Make precompute accept explicit input/output paths. It writes only into a unique staging
   directory, copies the serve-time model/scaler, and reads the report cache from a separate
   build-input path.
3. Validate referential integrity before promotion:
   - queue `case_id` and `case_ref` values are unique;
   - cases are exactly the curated `has_case` subset of the queue;
   - operation membership exactly equals grouping the queue by `operation_ref`;
   - raw and behavioral worst IDs equal recomputed maxima;
   - duplicated segment fields agree byte-for-byte across queue, operations, and cases;
   - `cases_raw.parquet` contains exactly the case segment IDs and required columns;
   - every case's operation reference exists;
   - report text passed the deterministic guard and cache evidence digest matches;
   - thresholds and features match `model/model-contract.json`, checkpoint metadata, and
     scaler feature order.
4. Write a separate model contract and a state-dict checkpoint loadable with
   `torch.load(..., weights_only=True)`; do not publish an unrestricted pickle payload.
5. Compute hashes and derive `release_id`, then rename staging on the same filesystem to the
   immutable `releases/<release_id>` directory. The explicit directory is the promotion; no
   mutable `current` pointer is needed.
6. Add `backend/scripts/package_demo_release.py` to create the deterministic archive: sorted
   entries, fixed modes/owner/group/mtime, and gzip timestamp zero.

**Acceptance:** killing precompute before the final rename exposes no partial release and leaves
all prior immutable releases readable; corrupting any shipped byte makes validation and startup
fail.

### Actuation 3 — Clean-checkout image and Space deployment (P1)

1. Add one transactional publish command: require a clean Git tree, package deterministically,
   upload to a public Hugging Face model repository, obtain the immutable revision, redownload
   and verify it, then write `backend/serve/demo_bundle.lock.json`. Failed upload or verification
   leaves the existing lock untouched. The lock contains URL, revision, archive SHA-256,
   release ID, schema version, and publication timestamp. Do not commit model binaries or the
   generated bundle to this repository.
2. Add a standard-library fetch script that downloads the locked archive, verifies SHA-256,
   accepts only the manifest's exact allowlist of bounded regular files, rejects absolute or
   parent paths, links, devices, duplicates, extra files, and decompression-size excess, extracts
   without following links to a temporary directory, validates the release manifest, and
   renames it into place.
3. Replace the legacy backend-only Dockerfile with one root multi-stage Dockerfile:
   - Node stage builds `frontend/dist`;
   - Python stage installs a generated, exact Linux serve requirements lock with a pinned `uv`;
   - fetch stage retrieves the pinned public release;
   - runtime copies source, SPA, and verified release;
   - command runs `uvicorn backend.serve.app:app` on `${PORT:-7860}`.
4. Serve `/assets/*` directly and use an index fallback for React routes after all `/api/*`
   routes. Keep production API calls same-origin.
5. Add CI that starts from a clean checkout, runs backend and frontend suites, builds the
   image, starts it, and checks health, a deep SPA route, one case response, and a zero-
   intensity simulation.
6. Pin Node/Python base images by digest. CI and Hugging Face rebuild the same Dockerfile from
   the same locked inputs; do not claim they run the same image digest.
7. Deploy that image definition to the Hugging Face Docker Space. Record the Space URL
   and release ID in the write-up, then run desktop visual QA and send the requested `devrup`
   message.

**Acceptance:** a machine with only Git, Docker, and network access can clone and build the
image; `/api/health` reports the expected release ID; refreshing a deep case route works.

## Code quality rules

- One `ReleaseManifest`/validation implementation is shared by build, fetch, startup, and
  tests. Do not reproduce hash rules in shell.
- All paths are explicit parameters or environment variables; no hidden dependency on the
  caller's current directory.
- Generated release data is immutable. Only `.staging/` is mutable.
- Error messages name the release ID, file, expected value, and observed value.
- The release pipeline diagram above should also appear as a short module comment in
  `backend/serve/release.py`; it is the non-obvious state transition being protected.

## Test coverage diagram

```text
CODE PATHS                                         DEPLOY / USER FLOWS

case_identity(segment_id)                          analyst opens stable case URL
├── deterministic output [UNIT]                    ├── queue -> case [E2E]
├── input-order independence [UNIT]                 ├── operation -> sibling case [E2E]
└── collision abort [UNIT]                         └── simulation uses same case [E2E]

build_release(staging)
├── complete build -> immutable release [UNIT]
├── interrupted before rename -> no visible release [UNIT]
├── duplicate release -> idempotent success [UNIT]
├── missing reference -> reject [UNIT]
└── hash/size mismatch -> reject [UNIT]

fetch_locked_release(lock)
├── valid archive -> verified directory [INTEGRATION]
├── HTTP/download failure -> non-zero build [INTEGRATION]
├── archive hash mismatch -> reject [UNIT]
├── path/link/device/duplicate member -> reject [UNIT]
└── extra or oversized content -> reject [UNIT]

FastAPI lifespan                                  clean-checkout container
├── valid release -> ready [INTEGRATION]           ├── image builds [CI]
├── missing release -> clear startup failure       ├── /api/health release_id [CI]
├── unsupported schema -> clear failure            ├── /case/<id> refresh [CI]
└── corrupt file -> clear failure                   └── zero-intensity simulate [CI]

simulation readiness
├── not_loaded -> first request loads -> ready [INTEGRATION]
├── first load fails -> 503 + failed [INTEGRATION]
├── next request retries once -> ready [INTEGRATION]
└── retry fails -> bounded 503, no filesystem leak [INTEGRATION]
```

Required test locations:

- `backend/tests/test_case_identity.py` — known vectors, reorder/extension invariance,
  collision failure through an injected digest function.
- `backend/tests/test_release.py` — manifest, referential integrity, corruption, interrupted
  promotion, canonical manifest identity, deterministic archive bytes, strict extraction, and
  idempotency.
- `backend/tests/test_serve_app_factory.py` — clean import, lifespan success/failure, release
  ID health response, SPA fallback, API 404 precedence.
- Existing backend operation/simulation tests — migrate from integer IDs to string case IDs.
- Existing frontend queue/operation/case/what-if/flow tests — assert string routes and stale
  request protection still work.
- Container smoke script or CI job — build and run only from tracked files plus the public
  locked artifact.

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
| Simulation model cannot load | State becomes `failed`; endpoint returns 503, logs detail, and permits one next-request retry. | Read-only dossier remains available; failure is visible. |
| Evidence changed but cached report did not | Report cache key includes canonical evidence digest, prompt digest, and generator version. | Stale prose is omitted rather than attached to new evidence. |

## Performance and size budget

- Current serve data is about 24 MB; model + scaler add under 100 KB. The 128 MB clean frame
  and 10 MB metadata frame are build inputs and must not enter the image.
- Keep JSON gzip enabled. The immutable release is loaded once per worker; run one worker on
  the free Space to avoid duplicating the in-memory queue/cases payload.
- Archive download happens at image build, not on every process start.
- Generate a dedicated exact Linux serve requirements lock from the current working
  environment. The repository-wide `uv.lock` remains intentionally uncommitted per team policy.
- Record Python, PyTorch, scikit-learn, NumPy, pandas, and pyarrow versions in the model contract;
  startup enforces incompatible major versions and reports minor-version drift.

## Parallelization

| Lane | Work | Depends on |
|---|---|---|
| A | Stable case identity across backend and frontend | — |
| B | Release manifest, staging, validation, and archive helpers | Identity contract before final bake |
| C | Docker, fetch script, CI, Space configuration | Release archive and lock file |

Start Lane B's standalone manifest primitives while Lane A changes the schema, but merge A
before B wires final referential validation and generates the artifact. Lane C can prepare the
Docker/CI skeleton in parallel, then pins the artifact produced by B. Avoid parallel edits to
`precompute.py` and `app.py`; those are the merge-conflict boundary between A and B.

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

## Implementation tasks

- [ ] **T1 (P1, human: ~1 day / CC: ~45 min)** — Identity — replace positional numeric IDs
  with stable `case_id`/`case_ref` values across bake, API, UI, and tests.
- [ ] **T2 (P1, human: ~1.5 days / CC: ~60 min)** — Release — add immutable staging,
  referential validation, content hashes, atomic promotion, and archive packaging.
- [ ] **T3 (P1, human: ~0.5 day / CC: ~30 min)** — Reports — bind cached prose to the
  canonical evidence digest, prompt digest, and generator version before the schema v2 bake.
- [ ] **T4 (P1, human: ~0.5 day / CC: ~30 min)** — Artifact — package deterministically,
  publish transactionally, redownload/verify, and commit the immutable lock file.
- [ ] **T5 (P1, human: ~1 day / CC: ~60 min)** — Delivery — build the root multi-stage image,
  serve the SPA from FastAPI, and remove the legacy Docker entry point.
- [ ] **T6 (P1, human: ~1 day / CC: ~60 min)** — Verification — add clean-checkout CI and
  container smoke coverage for API, SPA deep links, case identity, and simulation parity.
- [ ] **T7 (P1, human: ~0.5 day / CC: ~30 min)** — Release — deploy the pinned inputs to the
  Space, run live visual QA, update the write-up/issue checklist, and notify `devrup`.

## Definition of done

- [ ] Stable case IDs pass reorder and extension tests.
- [ ] Documentation states that corrected/resegmented telemetry creates a new case identity.
- [ ] Release builder cannot expose a partial or mixed generation.
- [ ] Every shipped file is hash-verified against schema v2 manifest metadata.
- [ ] Clean checkout backend test collection does not require local ignored files.
- [ ] Clean checkout Docker build needs no untracked local input.
- [ ] Container smoke checks health, deep SPA routing, case response, and zero-intensity parity.
- [ ] `/api/health` exposes the deployed release ID and schema version.
- [ ] Hugging Face Space is live and visually approved on desktop.
- [ ] Deployment URL and release ID are recorded in project documentation.
- [ ] Issue #31 checklist is reconciled and `devrup` is notified.

## Review completion summary

- Scope reduced from four overlapping critical findings to three implementation actuations.
- Architecture: six issues resolved in the plan — identity scope, release identity, report
  evidence binding, safe model contract, reproducible delivery inputs, and transactional publish.
- Code quality: four contracts made exact — identifier encoding, shared validation, explicit
  release selection, and simulation readiness.
- Tests: 25 unit/integration/CI paths are specified; no critical branch is intentionally uncovered.
- Performance: one worker and a minimal exact serving lock prevent duplicate memory and training-
  dependency bloat; no training frame enters the image.
- Parallelization: manifest primitives and Docker skeleton may start concurrently, but the release
  path merges in the strict order identity → artifact → delivery.
- Backlog: this plan is the task source; no duplicate `TODOS.md` entries are proposed.
- Outside review: 13 adversarial findings were absorbed, including canonical manifest identity,
  bounded segment identity, cache evidence binding, strict extraction, and transactional publish.

## GSTACK REVIEW REPORT

| Review | Scope | Runs | Status | Findings |
|---|---|---:|---|---|
| Engineering review | Critical application-level actions | 1 | CLEAR | Three actuations, seven implementation tasks, zero unresolved critical gaps |
| Codex outside review | Adversarial architecture and delivery pass | 1 | CLEAR | 13 findings incorporated into contracts and acceptance gates |
| Test review | Unit, integration, container, and deploy paths | 1 | CLEAR | 25 paths specified; clean-checkout smoke is mandatory |
| Performance review | Demo bundle, memory, and image inputs | 1 | CLEAR | One worker; ~24 MB serving data; training frames excluded |

**CODEX:** Release identity must bind the complete canonical contract, not only file hashes;
stable case identity must be described at the canonical-segment boundary.

**CROSS-MODEL:** Both reviews converge on the same dependency order: stabilize identity, produce
one content-addressed release, then make the clean-checkout container the deployable unit.

**VERDICT:** ENGINEERING + CODEX CLEARED — ready to implement as three sequential actuations.

NO UNRESOLVED DECISIONS
