---
id: 33
title: Approach-conformance product and ML lifecycle reframe
status: contextual_research_candidate_review_pending
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
- The new analysis unit is one approach attempt nested in an observed operation record;
  `flight_id` is only a candidate record identity.
- Exact runway inference may fall back to runway direction/pair or abstain.
- Vertical-path and speed outputs are proxies, not certified glide-slope or airspeed compliance.
- Go-around is a maneuver, not a failed criterion.
- A supervised model is blocked on independent labels and incremental value over rules.

## Build checklist

- [x] Run an observed-row feasibility spike: reconstruction audit, runway-direction diagnostics,
  altitude fallback coverage, envelope conditioning diagnostics and criterion prevalence.
- [x] Freeze the reconstruction/rule/reference contracts only if feasibility gates pass.
- [x] Version runway geometry/elevation provenance and approach schemas.
- [x] Implement reconstruction, inference, attempt extraction, quality gates and criteria.
- [x] Fit and serialize the train-only empirical reference envelope.
- [x] Add approach assessments to immutable release generation and serving.
- [x] Make upload evaluation rules-first and model preparation optional.
- [x] Reframe queue, operation, case and evaluation UI around approach evidence.
- [x] Add deterministic fixtures, contract tests, integration tests and user-flow tests.
- [x] Run lifecycle validation on development data and burn the sealed 2026 holdout once.
- [x] Record the failed qualification: 63.1% retention vs 65%; precision unknown.
- [x] Update product, architecture, lifecycle and limitation documentation.
- [ ] Run `/review`, `/qa` and `/ship`; push the branch and open a PR.

## Subsequent contextual iteration

- [x] Source and audit time-aligned METAR/QNH/wind and aircraft-type joins.
- [x] Search lawful reproducible sources for configuration, mass and ATC clearance; gate each
  independently on availability, join quality, leakage and licensing.
- [x] Rebuild contextual features and the typed empirical reference through lifecycle phases 1–6.
- [x] Compare contextual and ADS-B-only systems on development cohorts without touching burned
  or sealed data.
- [x] Record the failed contextual qualification: independent labels and a fresh holdout do not
  exist; deployment is research/evidence-labeling only.
- [ ] Compare on a newly precommitted holdout after another cohort is acquired.
- [ ] Promote contextual evidence beyond research only when it adds measured analyst value.
- [ ] After the public contextual deployment is live, provide OpenSky the link/citation notice
  required by its non-profit research data terms (external owner communication).

## Validation evidence

- Geometry, observed-row, reference and firewall tests: `22 passed`.
- Train feasibility: 4,272 attempts; 3,794 assessable (88.8%).
- Validation feasibility: 2,740 attempts; 2,255 assessable (82.3%).
- Audited 2025 source: 388 attempts; 264 assessable (68.0%).
- Independent notebook cross-check: 4,272 attempts versus 4,268 Phase-4 approach-rule records.
- Full evidence: `backend/docs/ml/08-approach-feasibility.md`.
- Sealed 2026 burn: 613 attempts; 387 assessable (63.1%); 82 review-required; qualification
  failed and no independent precision estimate is available.
- Contextual 2025 audit: QNH 96.39% (pass), wind 78.09% (fail), type 84.28% (pass); review
  status 40→50 and barometric-path observability 1→337, with correctness unknown because labels
  are absent.
- Context lifecycle: `backend/docs/ml/iterations/approach-context/manifest.yml`.

## Risks

- Barometric altitude without QNH can invalidate vertical-path evidence.
- Parallel runways may support direction-only inference.
- Domain-expert threshold review remains required before external operational claims.
- A new classifier may not be justified by the available labels; that is an acceptable result.
