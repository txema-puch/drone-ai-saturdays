---
id: 33
title: Approach-conformance product and ML lifecycle reframe
status: build
branch: feature/approach-conformance-reframe
created: 2026-07-14
---

# Approach-conformance reframe

## Outcome

Replace generic segment anomaly triage with a post-flight, whole-arrival screen for
ADS-B-observable approach-instability proxies at LEMD. Rules and empirical reference envelopes
own the result; the old LSTM is research context only.

## Durable decisions

- The old 2020 holdout remains burned and cannot validate the new pipeline.
- The new model unit is one reconstructed `flight_id` with explicit gap evidence.
- Exact runway inference may fall back to runway direction/pair or abstain.
- Vertical-path and speed outputs are proxies, not certified glide-slope or airspeed compliance.
- Go-around is a maneuver, not a failed criterion.
- A supervised model is blocked on independent labels and incremental value over rules.

## Build checklist

- [ ] Run an observed-row feasibility spike: reconstruction audit, runway-direction precision,
  altitude fallback coverage, envelope conditioning diagnostics and criterion prevalence.
- [ ] Freeze the reconstruction/rule/reference contracts only if feasibility gates pass.
- [ ] Version runway geometry/elevation provenance and approach schemas.
- [ ] Implement reconstruction, inference, attempt extraction, quality gates and criteria.
- [ ] Fit and serialize the train-only empirical reference envelope.
- [ ] Add approach assessments to immutable release generation and serving.
- [ ] Make upload evaluation rules-first and model preparation optional.
- [ ] Reframe queue, operation, case and evaluation UI around approach evidence.
- [ ] Add deterministic fixtures, contract tests, integration tests and user-flow tests.
- [ ] Run lifecycle validation on development data; seal the 2026 holdout before any burn.
- [ ] Update product, architecture, lifecycle and limitation documentation.
- [ ] Run `/review`, `/qa` and `/ship`; push the branch and open a PR.

## Subsequent contextual iteration

- [ ] Source and audit time-aligned METAR/QNH/wind and aircraft-type joins.
- [ ] Search lawful reproducible sources for configuration, mass and ATC clearance; gate each
  independently on availability, join quality, leakage and licensing.
- [ ] Rebuild contextual features and candidate models through the same lifecycle stages.
- [ ] Compare contextual and ADS-B-only systems on a newly precommitted holdout.
- [ ] Promote contextual evidence only when it adds measured analyst value.

## Validation evidence

- Geometry and observed-row core tests: `12 passed`.
- Train feasibility: 4,256 inferred approaches; 2,937 survive quality/terminal gates (69.0%).
- Validation feasibility: 2,730 inferred approaches; 1,868 survive gates (68.4%).
- Independent notebook cross-check: train inference 4,256 versus 4,268 Phase-4 approach-rule records.
- Full evidence: `backend/docs/ml/08-approach-feasibility.md`.

## Risks

- Barometric altitude without QNH can invalidate vertical-path evidence.
- Parallel runways may support direction-only inference.
- Domain-expert threshold review remains required before external operational claims.
- A new classifier may not be justified by the available labels; that is an acceptable result.
