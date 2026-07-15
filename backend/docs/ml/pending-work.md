# ML Pending Work and Findings

> **2026-07-14 outcome:** approach-screening consumed the 2026 snapshot exactly once and failed
> qualification (63.1% retention vs 65%; precision unknown). The cohort cannot be reused or tune
> thresholds. A contextual or replacement release needs independent labels and another untouched
> release-gate cohort. Earlier LSTM findings below remain historical inputs.

**Snapshot date:** 2026-07-11  
**Purpose:** close the current course-project iteration without losing the findings needed
to restart the work responsibly. This is a future-work register, not an active sprint.

## Current iteration boundary

The current model remains frozen at the Phase-6 contract: LSTM autoencoder, `T=260`,
first-T windowing, validation-selected threshold `0.222`, and segment-level scoring. The
SADAR demo annotates known coverage and gate artifacts, but does not change training,
thresholds, or evaluation results.

Closing this iteration means:

- preserve the existing model and reported numbers as historical artifacts;
- do not tune a replacement pipeline against the 2020 test cohort;
- keep known artifacts visible and honestly classified in the demo;
- start a new preprocessing/training/evaluation cycle only if the project resumes.

## Priority

- **P0:** methodological prerequisite before a new model or performance claim.
- **P1:** high-value data/model work for the next iteration.
- **P2:** product, research, or deployment extension.

## Register

| ID | Priority | Finding | Current disposition |
|---|---|---|---|
| PW-001 | P0 | The 2020 test cohort has informed redesign decisions and cannot evaluate a revised pipeline. | Provenance reconciled: burned once on 2026-06-02. A fresh holdout remains required for future redesign. |
| PW-002 | P0 | First-T windowing discards the terminal phase of long arrivals and inflates normal reconstruction error. | Demo mitigation only; redesign windowing, retrain, and re-evaluate in a future cycle. |
| PW-003 | P1 | Rare neighbour-airfield/overflight cases pass Filter D, while absolute-bound cleaning separately misses some relative-jump glitches. | Audit each failure class; validate targeted gate and cleaning refinements before retraining. |
| PW-004 | P1 | Evaluation and thresholding are segment-level while analyst decisions are operation-level. | Add operation-level metrics and length-aware aggregation before claiming workflow performance. |
| PW-005 | P1 | Phase-7/model-selection history was inconsistent across the manifest, burn artifacts, and demo documentation. | Resolved for this iteration on 2026-07-11 by restoring the recorded burn provenance and evaluation close-out. |
| PW-006 | P1 | The cohort is Monday-heavy, misses Sunday, and uses 2020 as a temporally unusual test period. | Expand calendar coverage and use later operations for the next untouched holdout. |
| PW-007 | P1 | Go-arounds and 7700 emergencies are useful external events but are not ground truth for unauthorized-drone behavior. | Seek stronger event data; keep claims limited to trajectory conformance. |
| PW-008 | P2 | The demo is retrospective, ADS-B-only, and has detailed case files for a curated subset. | Treat it as a course audit tool, not a production counter-drone system. |
| PW-009 | P2 | The optional historical research benchmark lacks a fully versioned attempt-to-segment mapping contract. | Keep it verdict-independent; version the mapping before adding another benchmark implementation. |
| PW-010 | P2 | FastAPI currently documents generic response objects for the public approach/evaluation endpoints. | Add typed request/response schemas and freeze generated OpenAPI fixtures before external API consumers depend on them. |
| PW-011 | P2 | Upload parsing and request-limit middleware remain coupled to the approach service module. | Extract neutral, shared boundaries only when a second evaluator needs them; preserve the current tested behavior first. |
| PW-012 | P1 | Midpoint weather is retrospective attempt-level context and can postdate early attempt rows. | Use start-time/per-row causal joins before any real-time or time-local weather claim. |

## Findings

### PW-001 - Test-cohort status and fresh holdout

**Evidence.** Git commit `7b7bbf3` records the one-shot Phase-7 burn on 2026-06-02 and contains
the original `07-eval.md`, manifest transition, burn script, notebook, and result JSON. A later
branch state retained the result JSON and demo use of the 2020 cohort but lost the evaluation
doc and reverted the manifest to pending/`burned: false`. D-014 subsequently used observations
from the open test population to recommend gate and windowing changes.

**Why it matters.** Once test-set behavior influences a redesign, that cohort becomes part
of the development process for the redesigned system. It can remain a diagnostic cohort and
support explicitly labelled same-cohort ablations, but it cannot provide an unbiased final
estimate for the next pipeline.

**Resolved now.** The evaluation close-out and manifest state were restored from recorded Git
provenance without rerunning evaluation. Phase 7 is passed and the 2020 cohort is permanently
burned. For a future redesign, freeze a new, later-date holdout grouped by `operation_ref`.
Do not inspect that new holdout until the new
pipeline, threshold, and operation-level metrics are locked on train/validation data.

**Done for this iteration.** The manifest, evaluation artifact, and burn provenance now agree.
The remaining P0 condition applies only when a new iteration starts: record a new untouched
holdout before making revised-pipeline claims.

### PW-002 - Terminal-anchored windowing

**Evidence.** First-T keeps the first 260 ten-second steps. For long arrivals, this can retain
only cruise/descent entry and discard the runway encounter. Test-normal mean RE is `0.418`
for truncated segments versus `0.104` for non-truncated segments. `CASE-2375` is a concrete
example: its scored prefix ends 90.6 km from LEMD at 4,412 m, while its discarded tail reaches
the runway.

**Why it matters.** The model is measuring phase/coverage mismatch rather than terminal
behavior. Increasing `T` alone would add cost and preserve phase heterogeneity.

**Resume work.** Define a deterministic terminal encounter from the full operation, select a
fixed window around it (candidate: mostly pre-encounter with enough post-encounter context for
go-arounds), split by operation before creating windows, refit the scaler on train only,
retrain the AE and baselines, and select the threshold on validation only.

**Validation checks.** Report normal RE and FPR by duration/truncation bucket, terminal-window
coverage, anomaly recall by type, and operation-level metrics. The truncated/non-truncated
normal gap must materially shrink without sacrificing dynamic-anomaly recall.

### PW-003 - Residual gate admissions and relative glitches

**Evidence.** Filter D is already a three-criterion operational gate: approach within 10 km,
on-ground within 5 km, or bounded takeoff within 5 km. It rejects obvious non-engaging
traffic, but a small residual remains. An approach to LECU/LEGT/LETO can pass within 10 km of
a LEMD runway even though it terminates elsewhere; an altitude-blind horizontal-distance
check can also admit a phase-labelled overflight. Separately, Stage-1 cleaning checks absolute
bounds, so an implausible one-step jump can remain when both endpoints are individually in
range. That glitch is a cleaning failure inside an admitted operation, not itself a Filter-D
criterion.

**Measured scope (2026-07-11 audit).** Among 4,480 scored segments, 72 non-truncated,
non-terminal segments pass within 5 km horizontally while remaining above 1,500 m at closest
approach. Of these, 57 are sustained-high without a >1,500 m one-step altitude jump, but they
all score `0.00` under the current loss mask and many are degenerate/missing-heavy resampled
records (for example, 31 rows but only one or two unique positions). They do not drive the
anomaly queue. Fourteen of the 72 contain a >1,500 m altitude jump. The queue-impacting example
`CASE-2995` (`3c6487_1583753730#2`, RE `0.914`, 99.6th percentile) jumps from about 648 m to
11,582 m; it contains a physically inconsistent altitude transition inside an otherwise
terminal segment. The cause could be sensor error, ingestion/interpolation behavior, or
telemetry manipulation, so the system should flag a data-quality conflict and abstain rather
than assign a final cause. It is not evidence of a sustained high-altitude overflight. The
future work is therefore primarily data-quality hardening; the sustained-overflight queue
impact is currently unproven.

**Resume work.** Inspect the residual cases by class. Test targeted candidates such as an
altitude bound on the approach criterion, runway-alignment/endpoint evidence, and nearest-field
comparison, while measuring retention of legitimate departures, holds, missed approaches, and
go-arounds. Evaluate the demo's low-and-close rule as one candidate; do not automatically
replace Filter D with it. Add train-defined relative rate-of-change rules as a separate cleaning
change. Run the full Phase-2/3 audit after changing either population or cleaning.

### PW-004 - Operation-level evaluation

**Evidence.** The detector scores segments, but the analyst investigates operations containing
one or more segments. A simple maximum preserves segment evidence but can still create a
multiple-comparisons/length effect: operations with more segments have more chances to contain
an extreme score. Coverage-artifact segments can also become the displayed worst segment.

**Resume work.** Precommit operation-level aggregation and abstention rules on validation data.
Report operation FPR, event recall, workload at top-K, coverage-artifact abstention rate, and
results stratified by segment count and duration. Never sum segment anomaly scores.

### PW-005 - Evaluation and model-selection close-out (resolved 2026-07-11)

**Evidence.** Provenance commit `7b7bbf3` shows that kNN won the synthetic test comparison but
the AE won the pre-registered held-aside real-event comparison. That commit selected the AE,
closed Phase 7, and burned the test once. The current branch had lost those documentation
changes while keeping the burn results.

**Resolution.** Restored an authoritative `07-eval.md`, set `gates.eval` to passed,
`model_track` to the confirmed DL track, and `test_set.burned` to true. No evaluation was rerun
and no metrics were changed. Reopen model selection only as part of a future retraining cycle.

### PW-006 - Temporal and calendar representativeness

**Evidence.** Cycle 3 is heavily Monday-weighted, Sunday is absent from accumulated coverage,
and 2020 includes an unusual aviation regime. The open day-of-week probe has only one Monday
in cycles 1 and 2.

**Resume work.** Add Sunday and multiple non-overlapping Mondays, quantify day-of-week and
calendar-regime drift, and source later-date operations for the new holdout.

### PW-007 - Ground-truth limits

**Evidence.** Held-aside go-arounds and emergency squawks provide real unusual trajectories,
but neither identifies an unauthorized drone. Public LEMD incident sources provide operational
impact, not track-level intruder geometry.

**Resume work.** Pursue AENA/AESA or research-partner incident data, or define a human-reviewed
conformance annotation protocol. Continue to describe the current output as trajectory
conformance/anomaly evidence, not drone identity or intent.

### PW-008 - Deployment and demo limits

**Evidence.** The tool scores completed ADS-B segments retrospectively, observes cooperating
aircraft only, and bakes detailed case files for a curated subset. It has no production identity
gate, U-Space match, streaming model, monitoring, or operational safety case.

**Resume work.** Only pursue production work after revalidating the problem framing. Candidate
work includes complete case storage, monitoring and drift policy, streaming-capable inference,
and integration with identity/flight-plan evidence.

### PW-009 to PW-012 - Contract and temporal-context follow-ups

The schema-v3 product review found no release blocker in these areas, but it identified four
boundaries that should be explicit before the demonstrator grows. The historical LSTM benchmark
needs a versioned attempt/segment mapping if it is ever expanded. External API use needs typed
OpenAPI schemas rather than framework-inferred generic objects. Parser/middleware extraction is
justified only by real reuse, not as a pre-emptive refactor. Finally, the current latest-prior
midpoint weather join is suitable for retrospective attempt context, but not for per-row causal or
real-time claims; those require a start-time or row-level temporal join.

## Restart order

1. Review resolved PW-001/PW-005 provenance before starting a new iteration.
2. Acquire and freeze the new holdout from later operations (remaining PW-001 requirement).
3. Address PW-003 and PW-006 at the data/preprocessing layer.
4. Design PW-002 and PW-004 on train/validation data; precommit metrics and abstention rules.
5. Retrain the AE and baselines, select once on validation, then run one final fresh-holdout eval.
6. Revisit PW-007/PW-008 only if the project moves beyond a retrospective course demo.

## Source decisions

- [D-009 - day-of-week covariate-shift probe](./decisions/D-009-day-of-week-covariate-shift-probe.md)
- [D-010 - Filter D and preprocessing](./decisions/D-010-filter-d-and-multi-detector-preprocessing.md)
- [D-014 - window truncation and gate artifacts](./decisions/D-014-window-truncation-of-long-arrivals.md)
- [Phase-6 training record](./07-train.md)
- [Phase-7 preparation](./07-eval-prep.md)
