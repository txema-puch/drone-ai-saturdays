# Phase 7 - Evaluation

**Status:** passed
**Date:** 2026-06-02
**Issue:** #29
**Test set:** burned once
**Provenance:** Git commit `7b7bbf3` (`feat(phase7): burn sealed test + blind
real-anomaly head-to-head - close eval gate`)

## Evaluation contract

The 2020 temporal test fold contained 4,285 normal segments. Model artifacts, the AE
threshold (`0.222`), synthetic anomaly definitions, and the representative-selection rule
were fixed before opening it. The burn evaluated the AE, kNN, and Isolation Forest; none was
dropped from reporting.

Artifacts created by the recorded burn:

- `backend/research/src/sadar_research/trajectory_anomaly/evaluation/report_eval.py` (present in the provenance commit; absent from the current
  working tree and therefore not silently recreated here)
- `backend/models/phase6/phase7_burn_results.json`
- Phase-7 evaluation notebook (preserved in the provenance commit; it was not part
  of the curated executable notebook set)
- this evaluation record and the corresponding manifest state

The local burn result file was created `2026-06-03 11:22 +0200` and records `n_test=4285`
and `cohort_n=195`, matching the split and held-aside real-event cohort.

## Synthetic test results

D-012 dynamic mix, with zone violation excluded from the headline and retained as a
diagnostic:

| Model | AUROC | PR-AUC |
|---|---:|---:|
| LSTM-AE | 0.731 | 0.770 |
| kNN summary baseline | 0.786 | 0.827 |
| Isolation Forest | 0.717 | 0.734 |

AE bootstrap 95% CI: `[0.714, 0.745]`. At the validation-selected threshold, AE F2 was
`0.520`, FPR `0.089`, and recall `0.474`. The Phase-1 AUROC target `>0.85` was not met.

Per-type AUROC:

| Type | AE | kNN | IF |
|---|---:|---:|---:|
| zone violation (diagnostic/out of remit) | 0.551 | 0.541 | 0.503 |
| altitude high | 0.558 | 0.594 | 0.556 |
| sustained loiter | 0.971 | 0.986 | 0.952 |
| final-approach intercept | 0.789 | 0.786 | 0.745 |
| speed spike | 0.580 | 0.815 | 0.587 |

## Real-event head-to-head

Held-aside go-around and emergency segments (`n=195`) were compared with 2020 test-normal:

| Model | ROC-AUC | PR-AUC |
|---|---:|---:|
| LSTM-AE | 0.667 | 0.088 |
| kNN summary baseline | 0.595 | 0.067 |
| Isolation Forest | 0.495 | 0.043 |
| SADAR VAE-LSTM, native representation | 0.659 | 0.299 |

The pre-registered representative-selection rule favored the LSTM-AE over kNN on real
events. The AE and SADAR ROC results are effectively a dead heat; their PR-AUC values are not
directly comparable because prevalence and windowing differ.

## External and qualitative checks

- The single close-in LEMD emergency from OpenSky Dataset #6 (BCS63A) scored at the AE's
  98.8th percentile and kNN's 100th percentile. This is a case study (`n=1`), not a population
  estimate.
- The top-20 validation-normal review found long/full-profile and holding-like trajectories;
  it was qualitative evidence, not a new threshold-selection pass.

## Decision

Ship the LSTM-AE for the course demo because it won the pre-registered real-event comparison
against kNN and represents dynamic sequence behavior. Keep kNN documented as the stronger
synthetic and cheaper baseline. Report the unmet primary target honestly.

## Post-burn findings

D-014 and the deployment audit later inspected the open 2020 cohort and found first-T
truncation, residual gate/data-quality cases, and segment-to-operation workflow issues. Those
findings do not alter this historical burn or its metrics. They do mean the 2020 cohort is now
development evidence for any redesigned pipeline. A future redesign requires a new untouched
holdout; see [`pending-work.md`](../../../archive-manifest.yml).

## Firewall close-out

- The historical record establishes one test burn on 2026-06-02.
- No test rerun was performed during the 2026-07-11 documentation reconciliation.
- `test_set.burned` must remain `true` permanently for this cohort.
- Future deployment annotations may preserve and explain scores but must not be presented as a
  new unbiased evaluation.
