# New iteration feasibility — whole-arrival approach screening

**Date:** 2026-07-14  
**Status:** feasible with explicit abstention; contracts still provisional  
**Script:** `backend/scripts/approach_feasibility.py`

## Firewall

The script accepts only the historical `train` and `val` folds and rejects `test`. The burned
2020 cohort was not used. The 2026 snapshot remains an unburned candidate holdout with manifest
hash `16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899`.

## Geometry correction

The prototype now binds to ENAIRE AIP `LEMD AD 2.12`, AMDT 408/26, effective 2026-07-09. The
source PDF digest is `65e114a09a8ce06d50a36b96eb5f7b333ac625effdbfa5c7f78a98524a683d1b`.
The old model geometry omitted provenance, displaced thresholds and per-threshold elevations;
several coordinates differ from the current AIP. Historical applicability remains disclosed.

## Observed-row feasibility

Criterion evidence excludes rows marked missing by the model-era resampling masks. No 10-second
interpolation is treated as an observation. The approach gate requires at least 20 observed
position samples and rejects gaps over 60 seconds or physical-rate conflicts.

| Measure | Train (2017–2018) | Validation (2019) |
|---|---:|---:|
| Candidate operation records | 8,594 | 5,508 |
| Runway direction inferred | 4,256 | 2,730 |
| Survived quality + terminal gates | 2,937 (69.0% of inferred) | 1,868 (68.4% of inferred) |
| Review-required by current non-speed criteria | 65 | 50 |
| Direction ambiguous / unsupported | 4,338 | 2,778 |
| Altitude reference available among inferred attempts | 2,519 | 1,719 |

The inference count independently matches the Phase-4 notebook's `pass_d_approach` population:
4,256 inferred train records versus 4,268 rule-tagged approach records. The notebook also reports
that 27.9% of train records end on-ground and 49.7% satisfy the broader approach rule, explaining
why approach attempts outnumber observed landings; go-arounds, incomplete approaches and other
near-runway records are intentionally distinct outcomes.

## Findings

- The product is viable as an **attempt screen**, not as proof that every record landed at LEMD.
- About 31% of inferred attempts abstain under strict observed-row quality/terminal gates. This is
  within the prototype ceiling but must be stratified by source, year and outcome.
- Barometric/geometric path evidence is available for only about 59–63% of inferred attempts;
  QNH/weather context is therefore a high-value next iteration, not optional polish.
- Relative altitude/position conflicts are common enough to justify first-class data-quality
  evidence and abstention.
- Lateral and track criteria are rare under provisional rules. The empirical speed reference and
  manual audit are required before freezing ranking semantics.

## Next gate

Audit a probability sample plus enriched rare cases, validate exact/direction runway inference,
fit source-stratified empirical envelopes on train only, and measure validation stability. Do not
start the 2026 burn or make an operational performance claim before those contracts are frozen.
