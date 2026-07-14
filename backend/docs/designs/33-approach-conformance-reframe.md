# SADAR approach-conformance reframe

**Status:** approved for implementation  
**Date:** 2026-07-14  
**Branch:** `feature/approach-conformance-reframe`

## Decision

Reframe SADAR from generic trajectory-anomaly analysis into a post-flight screen for ADS-B-observable approach instability at LEMD.

The product must answer which observable approach criteria failed, where they failed, whether the telemetry is trustworthy, and what evidence a human should inspect. It must not claim to certify an unstable approach or infer aircraft intent, configuration, weather, or emergency cause.

## Product boundary

- Completed post-flight records containing one or more LEMD approach attempts; no live-control
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

An **eligible attempt** must enter the approach gate and end in an explicit outcome. An
**assessable attempt** must additionally:

- contain at least 20 observed approach samples (about three minutes at the source cadence) and at least 70% observed values in required
  channels after the final-approach gate;
- enter within 20 km along-track of a LEMD threshold below 2,500 m above the airport reference;
- reach either the terminal gate (within 1.5 km and below 250 m above reference), a detected
  go-around after entering 5 km, or an on-ground observation near a threshold. This proves an
  approach attempt, not necessarily a completed LEMD landing;
- have no physical-rate conflict and no approach gap longer than 60 seconds;
- resolve at least a runway direction. Parallel-runway ambiguity may return `14_pair`,
  `18_pair`, `32_pair`, or `36_pair`; failure to resolve a direction returns a nullable runway
  and `not_assessable`.

`ApproachAssessment` is schema-versioned and contains:

- record identity, reconstruction confidence, attempt identity, start/end times, outcome,
  assessment status and reasons;
- runway candidate, specificity (`exact`, `direction`, `unknown`), confidence, score margin,
  geometry version and supporting observations;
- approach-window bounds, outcome (`landing_observed`, `closest_approach`, `go_around`),
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
2. Extract a runway-relative final-approach window ending at touchdown, closest approach, or
   go-around initiation plus bounded post-event context.
3. Evaluate telemetry quality and coverage before behavioral criteria.
4. Evaluate provisional ADS-B-observable criteria:
   - lateral centreline-proxy deviation;
   - barometric/geometric path-proxy deviation, never claimed as glide-slope compliance;
   - excessive or unstable observed vertical rate;
   - unusual observed ground-speed level or variation relative to a train-fitted cohort;
   - persistent late track corrections using wrap-safe smoothed heading;
   - go-around as a separate maneuver/outcome.
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
conditioning supported by sample size: distance bin plus runway direction and broad ground-speed
class, with source/year stratification diagnostics. An envelope is rejected if collection source,
calendar, fleet mixture or runway configuration dominates it. This is a statistical reference
model, not a certified classifier.

## Geometry and altitude provenance

Runway threshold coordinates, opposite physical ends, true bearings, displaced-threshold notes,
threshold elevations, coordinate reference, effective period, and source metadata live in one
versioned data file. The source of record is ENAIRE AIP `LEMD AD 2.12`, effective 2026-07-09;
historical data use is disclosed unless an effective historical chart is sourced. The
implementation records the source URL, retrieval date, units, and file digest in every generated
assessment artifact.

Vertical evidence uses this fallback hierarchy: independently supplied QNH/pressure-corrected
height; otherwise per-attempt bias estimated from trustworthy on-ground or threshold-adjacent
samples; otherwise geometric altitude when present and consistent; otherwise vertical-path
criteria abstain. Barometric altitude minus airport elevation alone is never treated as height
above runway.

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
  track, invalid below a configured ground-speed floor, smoothed circularly, and never described
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

## UX contract

- Queue rows show approach status, inferred runway, failed criteria, and assessability before any model score.
- Case files lead with the approach verdict and evidence timeline.
- Reference labels such as emergency squawk or go-around heuristic are contextual metadata, never model detections.
- The frozen LSTM appears only under `Research benchmark`, with text stating that it does not determine the verdict.
- Upload evaluation uses the same approach assessment contract and exports its evidence.

## Delivery contract

Retain the existing FastAPI/React same-origin container, immutable model bundle, GitHub Actions checks, and Fly deployment configuration. The clean-checkout build must run backend tests, frontend tests/build, release-contract validation, and HTTP/container smoke tests.

This is a release-schema migration, not an additive field patch. Schema v3 makes geometry,
criteria configuration, empirical reference and approach assessments required. Historical LSTM
artifacts become an optional `research/` component. The server may read schema v2 during local
rollback, but the new UI and uploads bind to schema v3. Rules-first uploads work without preparing
Torch; the research benchmark is lazy and optional.

Every assessment records digests/versions for geometry, reconstruction policy, rule configuration,
persistence settings, empirical reference, cohort definition and assessment engine.

## Definition of done

- [ ] Approach-domain types and provisional criteria are versioned and documented.
- [ ] Runway inference, final-approach extraction, quality abstention, and rule evaluation are implemented.
- [ ] Precomputed and uploaded arrivals share the assessment contract.
- [ ] Queue, case file, filters, exports, and copy are approach-first.
- [ ] The LSTM is benchmark-only and cannot affect the verdict.
- [ ] Deterministic backend and frontend regression suites pass.
- [ ] Clean build and deployed-like smoke test pass.
- [ ] README, architecture, ML limitations, and design documentation match the shipped behavior.

## NOT in scope

- Live monitoring or ATC decision support: the available pipeline is retrospective.
- Certified stabilized-approach or regulatory conformance: required avionics and operational
  context are absent.
- Weather, QNH, wind, aircraft configuration, mass, clearance or intent inference.
- Exact parallel-runway assignment when ADS-B geometry does not support it.
- A supervised production model before independent labels and a fresh holdout exist.
- Database, durable upload storage, job queue or runtime LLM reports for the course demo.

These exclusions apply only to the ADS-B-only iteration. After it is complete, a second lifecycle
iteration will actively source and gate time-aligned weather, QNH, wind and aircraft-type data,
then configuration, mass and ATC-clearance data where lawful reproducible sources can be found.
It will retrain/recalibrate and compare against the frozen ADS-B-only baseline under the same
holdout discipline. Missing sources are recorded as failed data gates, not assumed unavailable.

## What already exists

- Reuse raw-schema validation, derivations, missingness masks, gap segmentation and physical-rate
  diagnostics from `backend/core` and `backend/serve/evaluation.py`.
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

- [ ] **T1 (P1)** — Finish observed-row reconstruction and feasibility; freeze v1 contracts.
- [ ] **T2 (P1)** — Fit, validate and serialize source-stratified empirical references.
- [ ] **T3 (P1)** — Generate schema-v3 approach evidence and migrate serving/upload contracts.
- [ ] **T4 (P1)** — Build the validated analyst information architecture and evidence views.
- [ ] **T5 (P1)** — Complete lifecycle artifacts, backend/frontend/release tests and QA.
- [ ] **T6 (P2)** — Start the contextual data/model lifecycle after ADS-B-only release closure.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | Product scope resolved through office-hours and user direction |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | CLEAR | 14 findings accepted into the design and sequencing |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 14 issues resolved, 0 critical gaps left in the plan |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | pending after feasibility | Information architecture intentionally follows validated workflow |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Not required for feasibility |

**CODEX:** Forced observed-row evidence, reconstruction validation, explicit attempt outcomes,
schema-v3 migration, complete provenance and a feasibility-first sequence.

**VERDICT:** ENG CLEARED — implement feasibility first, then the full vertical slice.

NO UNRESOLVED DECISIONS
