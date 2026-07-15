# Phase 4 — Context coverage EDA

## Coverage

| Cohort | Attempts | QNH | Wind components | Aircraft type |
|---|---:|---:|---:|---:|
| Train 2017–2018 | 4,272 | 99.72% | 81.46% | 99.20% |
| Validation 2019 | 2,740 | 100.00% | 85.04% | 98.50% |
| Newer source 2025 | 388 | 96.39% | 78.09% | 84.28% |

Fourteen newer-source attempts have no latest-prior weather inside the 30-minute join limit. They keep
the explicit no-weather fallback. The current registry covers less of the 2025 source than the
historical scientific cohort, reinforcing the temporal-identity warning.

Without QNH, barometric path is observable on only 1/388 newer-source attempts. The QNH proxy
makes it observable on 337 attempts and still leaves 51 without usable evidence. This is a
coverage result, not proof that the recovered criterion is correct.

## Type distribution and support

The train candidate contains 3,774 eligible attempts and 99.34% have a type designator. Minimum
support produces 91 exact type/direction/distance cells across 14 types plus 10 direction/distance
fallback cells. On the 2025 cohort, 84.28% use at least one exact type cell and 83.76% use exact
type cells for every supported reference row.

## Gate result

Passed for research feasibility with a failed optional wind gate. QNH and type exceed their
source-coverage gates; wind reaches 78.09% against 80%. Actual configuration, mass, and clearance
fail availability and do not enter later phases.
