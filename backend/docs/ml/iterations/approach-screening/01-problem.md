# Phase 1 — Problem

## Decision

Screen post-flight ADS-B records for review-worthy, observable patterns within LEMD approach
attempts. The system explains criterion evidence and abstains on telemetry, altitude-reference or
runway-inference uncertainty. It does not certify a stabilized approach or infer intent.

## User and action

The user is a post-flight analyst. The action is to prioritize an attempt for review and inspect
the exact evidence span, not issue a live operational instruction.

## Outputs

`not_assessable`, `partial_observation`, `criteria_observed`, or `review_required`, plus runway
specificity, attempt outcome, quality reasons, criterion spans and reproducibility provenance.

## Success gate

The ADS-B-only prototype must retain at least 65% of independently eligible approach attempts
after quality gates, reach at least 80% precision for review recommendations on a weighted human
audit, and expose no model result that can silently change the deterministic verdict.

## Cost of error

False review recommendations waste analyst time; false reassurance hides observable evidence.
Therefore uncertainty abstains, passing required criteria must all be observed, and evidence is
never inferred through interpolated rows.
