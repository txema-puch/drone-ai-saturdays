# SADAR approach-conformance reframe

**Status:** research deployment live; qualification failed; operational use blocked
**Date:** 2026-07-14
**Implementation branch:** `feature/approach-conformance-reframe` (merged into `develop` via PR #34)

## Decision

Reframe SADAR from generic trajectory-anomaly analysis into a post-flight screen for ADS-B-observable approach instability at LEMD.

The product must answer which observable approach criteria failed, where they failed, whether the telemetry is trustworthy, and what evidence a human should inspect. It must not claim to certify an unstable approach or infer aircraft intent, configuration, weather, or emergency cause.

## Product boundary

- Post-flight records containing one or more LEMD approach attempts; no live-control
  claim. A landing, low pass, go-around, diversion, and incomplete record are distinct outcomes.
- Observable inputs: position, barometric altitude, ground speed, vertical rate, heading, on-ground state, fixed runway geometry.
- Missing context: wind, indicated airspeed, aircraft configuration and mass, ATC clearance, weather category, authoritative runway assignment.
- Output language: `stable within observable criteria`, `review recommended`, or `not assessable`.
- Data-quality and runway-inference failures abstain before behavioral assessment.
- Deterministic rules own the verdict. ML is a research benchmark until independent labels prove incremental value.

## Why the current model is demoted

The frozen LSTM autoencoder learned to reconstruct whole 2017-2018 clean-normal segments across mixed flight phases. It scores the mean reconstruction error of the first 260 ten-second steps against a validation threshold of `0.222`. That contract does not identify final-approach instability, and it can neither name a cause nor recommend an action.

The current model and threshold remain available only as a clearly labelled research comparison. They cannot modify the approach verdict or queue priority.

## Approaches considered

1. **Rules only:** fastest and clearest, but no explicit path for learned ranking.
2. **Rules-first plus ML benchmark:** rules decide; the frozen model documents the current negative result; future ML crosses an evidence gate before influencing ranking. **Chosen.**
3. **Supervised approach classifier:** strongest later architecture, blocked on independently reviewed labels and domain validation.

## State and data model

The unit of analysis is an **approach attempt** nested inside an **observed operation record**.
The existing `flight_id` (`icao24` plus a 30-minute gap) is only a candidate record identity:
source-day boundaries, coverage loss, overlapping callsigns and terminal continuity checks may
split, merge or reject it. Reconstruction quality is measured before any attempt is assessed.

Assessment operates on canonical observed rows. The model-era 10-second interpolation may be
retained for display or the historical LSTM only; it is never criterion evidence. Gaps over 60
seconds inside the approach gate cause attempt-level abstention, including gaps that the old
three-minute segmentation would have interpolated.

```text
raw observations
      |
derive + clean, preserving missingness/gaps
      |
candidate record -> continuity validation -> one or more approach attempts
      |
infer runway: exact runway -> runway direction/pair -> unknown
      |
extract final approach and assess quality
      |
not_assessable | criteria_observed | review_required
      |
criterion evidence + separate maneuver/context + research benchmark
```

An **eligible attempt** must enter the approach gate and end in an explicit observed outcome. An
**assessable attempt** must additionally:

- contain at least 20 observed approach samples spanning at least 90 seconds;
- enter within 20 km along-track of a LEMD threshold below a provisional 3,000 m barometric
  proxy above threshold elevation;
- reach the analysis gate within 6 km (approximately the nominal 1,000 ft point on a 3° path),
  a detected go-around after entering 5 km, or an on-ground observation near a threshold. This
  proves observed final-approach coverage, not a completed LEMD landing;
- have no position-rate conflict and no approach gap longer than 60 seconds. An altitude-rate
  conflict suppresses barometric-path evidence without discarding independent geometry/speed;
- resolve at least a landing-runway direction. Under the current AIP, parallel-runway ambiguity
  may return `18_pair` or `32_pair`; failure to resolve a direction returns a nullable runway
  and `not_assessable`.

`ApproachAssessment` is schema-versioned and contains:

- record identity, reconstruction confidence, attempt identity, start/end times, outcome,
  assessment status and reasons;
- runway candidate, specificity (`exact`, `direction`, `unknown`), confidence, score margin,
  geometry version and supporting observations;
- approach-window bounds, outcome (`landing_observed`, `final_gate_observed`, `go_around`,
  `incomplete`),
  coverage and quality diagnostics;
- ordered `CriterionAssessment` records with `not_observed`, `within_limit`, or
  `review_required` status plus configured severity;
- one or more evidence spans, each with start/end indices and times, a worst-point index,
  measured value, limit/reference band, unit, along-track distance and altitude proxy;
- a separate maneuver block (including go-around) and a separate research-benchmark block.

Go-around is an observed maneuver, not a failed criterion. Criteria preceding it remain
independently assessable.

## Functional contract

For every candidate arrival:

1. Infer the runway through a transparent hierarchy: exact threshold when geometry separates
   parallel runways, runway direction/pair when only alignment is supported, otherwise abstain.
   Pair-level results retain the lowest-scoring threshold only as a provisional computation
   anchor; the API and UI expose that anchor separately and never present it as the observed
   runway assignment.
2. Extract a runway-relative final-approach window ending at touchdown, the final analysis gate, or
   go-around initiation plus bounded post-event context. Criterion evaluation ends at go-around
   initiation or touch-and-go ground contact, so the subsequent climb/turn cannot create a failed
   approach criterion; post-event rows remain available only as outcome evidence.
3. Evaluate telemetry quality and coverage before behavioral criteria.
4. Evaluate provisional ADS-B-observable criteria:
   - lateral centreline-proxy deviation;
   - barometric/geometric path-proxy deviation, never claimed as glide-slope compliance;
   - excessive or unstable observed vertical rate;
   - unusual observed ground-speed level or variation relative to a train-fitted cohort;
   - persistent late ground-track corrections using wrap-safe circular differences;
   - go-around and touch-and-go as separate maneuvers/outcomes.
5. Produce duration-aware evidence spans plus a worst point, actual value, provisional limit,
   time, along-track distance, altitude proxy, persistence, and plain-language explanation.
6. Aggregate without hiding evidence. Overall status uses the same public vocabulary everywhere:
   - `not_assessable` when required quality/inference gates fail;
   - `review_required` when one or more high-severity criteria fail;
   - `criteria_observed` only when every required criterion is observed and none fails;
   - `partial_observation` when observed criteria pass but one or more required criteria abstain.

All thresholds are marked `prototype_v1`. Fixed safety/quality gates are code-versioned.
Behavioral ground-speed and descent envelopes are empirical quantiles fit on training attempts
only and serialized as a small JSON reference artifact. The feasibility gate chooses the minimum
conditioning supported by sample size: distance bin plus runway direction and, when available,
broad aircraft speed class. The current historical artifact records speed class as `unknown` and
exposes that limitation rather than inferring it from the target speed. An envelope is rejected if collection source,
calendar, fleet mixture or runway configuration dominates it. This is a statistical reference
model, not a certified classifier.

## Geometry and altitude provenance

Runway threshold coordinates, opposite physical ends, true bearings, displaced-threshold notes,
threshold elevations, coordinate reference, effective period, and source metadata live in one
versioned data file. The source of record is ENAIRE AIP `LEMD AD 2.12`, effective 2026-07-09;
historical data use is disclosed unless an effective historical chart is sourced. The
implementation records the source URL, retrieval date, units, and file digest in every generated
assessment artifact.

The ADS-B-only vertical path uses a per-attempt bias estimated from trustworthy on-ground or
threshold-adjacent samples; otherwise it abstains. Context engine v1 may instead apply an
independently supplied QNH first-order pressure-altitude correction, with the proxy source and
value serialized. It remains distinct from geometric/radio altitude. Barometric altitude minus
airport elevation alone is never treated as height above runway.

## Edge-case policy

- Multiple approaches or runway changes: split and assess each eligible attempt; a go-around ends
  one attempt and a later intercept begins another.
- Holds/diversions/non-LEMD termination: exclude or abstain with an explicit reason.
- Parallel-runway ambiguity: fall back to direction/pair; never manufacture exact precision.
- Touch-and-go: record the maneuver and do not treat it as a normal completed landing.
- Sparse telemetry, long gaps, non-monotonic time, impossible position/altitude rates, or
  altitude-datum conflict: abstain from affected criteria or the whole assessment.
- Wind-dependent speed: describe observed ground-speed behavior only; never claim airspeed or
  stabilized-speed compliance.
- Curved intercepts and vectoring: centreline and track rules activate only inside their
  configured distance gates and require persistence. OpenSky `heading` is treated as ground
  track, invalid below a configured ground-speed floor, compared circularly, and never described
  as aircraft heading.

## ML lifecycle iteration

This reframe opens a new, append-only lifecycle iteration without rewriting the completed
LSTM experiment.

- **Problem:** post-flight screening for observable approach-instability proxies at LEMD.
- **Data:** historical 2017-2019 arrivals for train/development, 2025 for temporal validation,
  and the hashed 2026 snapshot sealed before final evaluation. The burned 2020 cohort is
  diagnostic only.
- **Preprocess/features:** whole-arrival reconstruction, runway-relative geometry, approach
  attempts, distance bins, persistence and quality masks.
- **Baseline/model:** deterministic criteria plus a train-fitted empirical reference envelope.
  The frozen LSTM remains a historical negative benchmark.
- **Supervised model gate:** only after two reviewers independently label a stratified set and
  agreement is adequate. A learned ranker/classifier must beat rules-only workload/precision
  and find useful incremental cases on the untouched temporal holdout before it can influence
  priority. Otherwise the lifecycle records that ML did not earn a product role.

The historical LSTM benchmark remains segment-level. The operation/attempt record may list all
overlapping segment scores with coverage, but no aggregate score or direct rules comparison is
manufactured; the incompatible units are stated in the API and UI.

## Validation contract

- Deterministic fixtures cover stable approach, descent-rate exceedance, speed exceedance, lateral/glide-path deviation, late correction, go-around, insufficient coverage, low-confidence runway inference, and corrupt telemetry.
- Existing 2020 data is a development/audit cohort, not a fresh final holdout.
- Thresholds are provisional and must be visibly labelled as such.
- Feasibility starts with a probability sample for unbiased coverage/workload estimates plus
  separately reported enrichment samples for rare criteria. Sampling probabilities and weights
  are retained. The labelled set expands until each reported criterion has enough positives for
  a precommitted confidence-interval width; `200` is a floor, not a cap.
- Two reviewers use a blinded rubric to label `review-worthy observable pattern`, not certified
  stability. Report raw agreement and Cohen's kappa, per-criterion precision/recall with
  confidence intervals, assessable coverage, abstention rate, review workload at top-K, and
  runway-direction accuracy only where an independent source label exists.
- Prototype targets are at least 90% runway-direction precision on independently labelled
  assessable arrivals, at least 80% precision for `review_required`, no more than 35% overall
  abstention on the labelled eligible set, and processing below 100 ms per 1,000 observations on
  the reference development machine. Failure keeps the feature labelled experimental.
- Before any operational claim, create the independently reviewed set and use the untouched 2026
  temporal holdout. Prototype targets are learning gates, not certification thresholds.
- Any future model must beat the rules-only baseline on the independent set and demonstrate useful incremental cases at an acceptable false-positive rate.

Holdout order is fixed: record the 2026 file hash and eligible-operation count; keep it unread by
the assessment/training scripts; lock geometry, reconstruction, rules, envelope, sampling plan and
metrics on historical/2025 data; tag the candidate release; then perform one scripted 2026 burn.

### Contextual iteration result

The follow-on lifecycle is recorded at
`docs/research/approach-context/lifecycle/manifest.yml`. NOAA NCEI Global Hourly QNH and the
OpenSky current aircraft registry pass development coverage gates; latest-prior wind reaches
78.09% and misses its 80% gate. Actual configuration, mass, and ATC clearance fail
source-availability gates and are not inferred. QNH recovers a barometric-path proxy; wind is
optional display-only evidence; supported ICAO types select attempt-balanced train-only reference
cells with an explicit unknown fallback.

The 2019/2025 comparisons show changed coverage and workload, not correctness. Independent
labels and a fresh holdout do not exist, so contextual qualification fails and operational claims
remain blocked. A schema-v3 contextual release may be served only as a research and
evidence-labeling candidate with these limitations visible.

## UX contract

- A persistent shell boundary states that cases are synthetic and real research results
  are aggregate-only on every route, at desktop and mobile widths.
- Queue, case and operation views name the synthetic scenario and teaching goal; generated
  clocks and paths never imply a recorded flight.
- The Research evidence route is the only UI surface for real cohort findings. It uses
  captioned tables, explicit denominators and suppression-safe text, never charts whose
  denominator must be guessed.
- Upload evaluation is a third, ephemeral lane. It discloses non-retention, use of public
  rules/reference parameters, user responsibility for permission and separation from both
  published lanes before a file is selected and again after success.
- Queue rows show approach status, inferred runway, failed criteria, and assessability before any model score.
- Case files lead with the approach verdict, synchronized criterion signal profiles,
  and evidence timeline; the runway-relative map remains supporting spatial context.
- Reference labels such as emergency squawk or go-around heuristic are contextual metadata, never model detections.
- The frozen LSTM appears only under `Research benchmark`, with text stating that it does not determine the verdict.
- Upload evaluation uses the same approach assessment contract and exports its evidence.

### Information architecture

This is an analyst application, not a KPI dashboard. The primary workspace is a dense attempt
list; secondary context lives in a fixed summary rail on wide screens and an on-demand disclosure
on narrow screens. Cards are reserved for interactive evidence modules, not page layout.

```text
SADAR Analyst Console
├── Attempts (default, synthetic demonstration)
│   ├── synthetic scenario scope + demo-only status counts
│   ├── filters: status / direction / criterion / outcome / quality
│   └── attempt table: status → runway → evidence → coverage → time
├── Attempt dossier
│   ├── synthetic origin + scenario teaching goal
│   ├── plain-language status + assessability reason
│   ├── runway-relative trajectory and synchronized evidence timeline
│   ├── criterion rows with observed band, span and provenance
│   ├── quality / missing-context disclosure
│   └── Research benchmark (collapsed, visually separated)
├── Research evidence (aggregate real-data findings only)
│   ├── reviewed cohort counts/rates + suppression-safe tables
│   ├── interpretation and qualification limits
│   └── OpenSky source access, citation + publication notice
└── Evaluate data (ephemeral user upload)
    ├── schema/privacy/limits
    ├── upload progress and bounded errors
    └── results using the identical attempt dossier vocabulary
```

The first viewport answers only three questions: what synthetic demo set is loaded, which
scenarios demonstrate review states, and why the first row is prioritized. Raw model score
is never one of those three. Real research totals remain on the separate evidence route.

### Interaction states

| Feature | Loading | Empty | Error | Success | Partial |
|---|---|---|---|---|---|
| Attempt queue | stable skeleton rows | explain active filters; clear-filter action | retry without losing filters | sorted table + count | quality-limited rows remain visible and filterable |
| Attempt dossier | preserve header footprint | missing attempt with queue link | bounded retry and release ID | synchronized map/timeline/criteria | observed criteria render; unavailable channels explain why |
| Upload | capability check then progress | schema sample + choose-file action | field-level issue list, file retained for retry | attempt summaries + export | zero attempts or partial attempts explain gate failures |
| Research benchmark | lazy collapsed disclosure | “not included in this release” | failure cannot suppress rules | incompatible-unit metrics | coverage explicitly states which segment was scored |

Navigation and filters survive reload through URL query state. Empty states always provide the
next valid action; no screen ends at “No items found.”

### Analyst journey

| Horizon | User experience | Design response |
|---|---|---|
| First 5 seconds | Understands this screens approach attempts, not emergencies | explicit product subtitle; status vocabulary dominates numerical evidence |
| First 5 minutes | Filters review candidates and verifies one evidence span | keyboard-operable table, linked dossier, synchronized map/timeline |
| Long-term | Can reproduce why an attempt was or was not assessable | visible release/config/reference digests and exported evidence contract |

### Visual system and anti-slop constraints

Reuse the existing dark aviation-audit palette, serif display face, monospace identifiers, route
shell, trajectory map and temporal-panel primitives. Replace score red/yellow semantics with a
small status palette: review red, partial amber, observed neutral, unavailable muted. Body text is
at least 16 px and 4.5:1 contrast. Dense tables use spacing and type hierarchy instead of boxed
cards, thick borders, gradients, ornamental icons or uniform rounded containers.

### Responsive and accessibility contract

- At >=1200 px, queue and dossier use a workspace + context-rail layout. At 768–1199 px the rail
  moves below the workspace. Below 768 px, table rows become labeled two-column records; evidence
  values never disappear or clip horizontally.
- All filters and rows are keyboard reachable. A row has one primary link, visible focus and a
  descriptive accessible name. Status is never color-only.
- Map evidence has a textual criterion/timestamp equivalent. Timeline scrubbing updates an
  `aria-live=polite` summary without announcing every pointer movement.
- Touch targets are at least 44 px. Reduced-motion disables animated scrub transitions. Loading
  retains layout dimensions to avoid focus jumps.
- CSV/Parquet upload labels remain visible after selection; validation errors focus the summary
  and link to field-level details.
- Pair-level runway inference visibly separates the public direction/pair from the provisional
  exact-threshold geometry anchor used to calculate proxies.

### Design decisions resolved

1. Prioritization is categorical (`review_required`, then partial/observed/not-assessable) and
   deterministic; within a status, failed-criterion count then time breaks ties.
2. Partial evidence is a normal first-class state, not an error banner.
3. Attempt dossier is the canonical detail unit; operation grouping is secondary context.
4. Research evidence is collapsed and cannot share the verdict color or ranking surface.
5. Mobile preserves all evidence as labeled records instead of hiding columns.
6. No generated narrative is required to interpret a criterion; direct evidence copy leads.
7. Visual QA after implementation must exercise loading, empty, error, success and partial states.

## Delivery contract

Retain the existing FastAPI/React same-origin container, immutable model bundle, GitHub Actions checks, and Fly deployment configuration. The clean-checkout build must run backend tests, frontend tests/build, release-contract validation, and HTTP/container smoke tests.

This is a release-schema migration, not an additive field patch. Schema v3 makes geometry,
criteria configuration, empirical reference and approach assessments required. Historical LSTM
artifacts become an optional `research/` component. The server may read schema v2 during local
rollback, but the new UI and uploads bind to schema v3. Rules-first uploads work without preparing
Torch; the research benchmark is lazy and optional.

Every assessment records digests/versions for geometry, reconstruction policy, rule configuration,
persistence settings, empirical reference, cohort definition and assessment engine.
Anonymous evaluation additionally enforces request-body, row, attempt, rolling global and
rolling per-client admission limits. A parsed operation with no supported attempt is retained in
the response as a structured rejection reason. Evidence export preserves the complete native
evaluation contract, including attempt index, runway specificity/confidence, sampled trajectory,
channels and rejection reasons.

## Definition of done

- [x] Approach-domain types and provisional criteria are versioned and documented.
- [x] Runway inference, final-approach extraction, quality abstention, and rule evaluation are implemented.
- [x] Precomputed and uploaded arrivals share the assessment contract.
- [x] Queue, case file, filters, exports, and copy are approach-first.
- [x] The LSTM is benchmark-only and cannot affect the verdict.
- [x] Deterministic backend and frontend regression suites pass.
- [x] Clean container build and HTTP smoke test pass in GitHub Actions and the Fly remote builder.
- [x] README, architecture, ML limitations, and design documentation match the candidate behavior.

## Qualification outcome

The one-time sealed 2026 burn retained 387/613 attempts (63.1%), below the precommitted 65%
target. Independent review labels do not exist, so precision and safety performance are unknown.
The qualification gate failed. The schema-v3 candidate may be used only as a research and
evidence-labeling demonstrator; it must not be retuned from the burned holdout or described as
operational conformance software. See
`../research/approach-screening/lifecycle/07-eval.md`.

## NOT in scope

- Live monitoring or ATC decision support: the available pipeline is retrospective.
- Certified stabilized-approach or regulatory conformance: required avionics and operational
  context are absent.
- Inferred weather, QNH, wind, aircraft configuration, mass, clearance or intent. The completed
  contextual iteration accepts supplied QNH and wind, and uses supported aircraft-type reference
  cells, but does not infer these values from ADS-B.
- Exact parallel-runway assignment when ADS-B geometry does not support it.
- A supervised production model before independent labels and a fresh holdout exist.
- Database, durable upload storage, job queue or runtime LLM reports for the course demo.

The contextual follow-on is complete. It sourced and gated time-aligned weather, QNH, wind and
aircraft-type data, and recorded configuration, mass and ATC-clearance as failed source gates.
Its comparisons do not establish improved correctness because no fresh holdout or independent
labels exist. Missing sources remain failed data gates rather than implied inputs.

## What already exists

- Reuse raw-schema validation and upload evaluation from `sadar.api`, stable trajectory
  segmentation from `sadar.trajectory`, and historical diagnostics from `sadar_research`.
- Reuse operation identities, immutable release packaging, same-origin FastAPI/React serving,
  upload bounds, Fly deployment and release-contract tests.
- Reuse the map and temporal-panel primitives, but change their primary evidence from AE
  reconstruction to runway-relative approach criteria.
- Preserve the frozen LSTM artifact and metrics unchanged under `Research benchmark`; it is not
  a dependency of the approach verdict.

## Engineering implementation plan

```text
OFFLINE LIFECYCLE
observed historical rows -> reconstruction/attempt feasibility -> train-only reference
          |                         |                               |
          +-> geometry/config digests + validation fixtures <------+
                                      |
                              immutable schema-v3 release

ONLINE/UPLOAD
bounded raw file -> canonical observed rows -> approach assessment -> evidence export
                                                    |
                                      optional lazy LSTM research block

ANALYST
attempt queue -> approach dossier -> criterion spans / quality / provenance
```

1. **Feasibility and contracts:** prove observed-row reconstruction, inference, altitude fallback,
   criterion prevalence and source-stratification behavior on train/validation only. Freeze the
   2026 hash before any burn.
2. **Core pipeline:** keep AIP geometry, reconstruction, attempt extraction, quality, reference
   fit/load and criterion assessment as leaf modules with typed/versioned JSON outputs.
3. **Lifecycle artifacts:** write the iteration problem/data/preprocess/EDA/features/train/eval
   records append-only. A supervised training phase may close with no model selected.
4. **Release/API migration:** introduce schema v3 with required approach/config/reference files
   and optional `research/` model files. Rules-first uploads do not require Torch readiness.
5. **UX reframe:** select the information architecture from the validated analyst task; replace
   score-first ranking with status/criteria/quality evidence and isolate research comparisons.
6. **Verification:** unit-test every inference/status/criterion branch, integration-test bake/API
   parity and schema v2 rollback, exercise queue/dossier/upload user flows, build the container,
   then run review and QA.

Failure handling is explicit: invalid geometry/reference aborts release startup; reconstruction or
quality uncertainty abstains per attempt; upload resource/format errors return bounded structured
responses; optional research-model failure does not suppress rules evidence; oversized release
evidence fails the build before publication.

Implementation is sequential through the feasibility/config freeze because every later layer
depends on those contracts. After that, core/release work and UX prototypes may proceed in
parallel, then converge for contract and end-to-end tests.

## Implementation Tasks

- [x] **T1 (P1)** — Finish observed-row reconstruction and feasibility; freeze v1 contracts.
- [x] **T2 (P1)** — Fit, validate and serialize source-stratified empirical references.
- [x] **T3 (P1)** — Generate schema-v3 approach evidence and migrate serving/upload contracts.
- [x] **T4 (P1)** — Build the validated analyst information architecture and evidence views.
- [x] **T5 (P1)** — Complete lifecycle artifacts, review, live QA and PR handoff.
- [x] **T6 (P2)** — Run the contextual data/reference lifecycle and record failed qualification.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | Product scope resolved through office-hours and user direction |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | CLEAR | 14 findings accepted into the design and sequencing |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 14 issues resolved, 0 critical gaps left in the plan |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR | score 6/10 → 9/10; 7 interaction decisions added |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Not required for feasibility |

**CODEX:** Forced observed-row evidence, reconstruction validation, explicit attempt outcomes,
schema-v3 migration, complete provenance and a feasibility-first sequence.

**VERDICT:** ENG + DESIGN CLEARED — implement the attempt-first vertical slice.

NO UNRESOLVED DECISIONS
