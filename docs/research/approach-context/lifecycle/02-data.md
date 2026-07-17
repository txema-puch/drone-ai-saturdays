# Phase 2 — Context data

## Sources used

### Weather and QNH

NOAA NCEI Global Hourly station `08221099999` supplies historical LEMD observations. The source
files are downloaded by year from
`https://www.ncei.noaa.gov/data/global-hourly/access/<YEAR>/08221099999.csv` and decoded from the
documented `WND`, `MA1`, temperature, dew-point, and report fields. The 2025 file digest is
`f18c8cabaaea572d6c46d70328bad40b7f732f3865a06dd865876567783b4939`.

AviationWeather's API was not used for historical fitting because its rolling availability is
too short for the 2017–2019 and 2025 cohorts.

### Aircraft type

The OpenSky aircraft database current snapshot supplies ICAO type designators under OpenSky's
non-profit research/education data terms. It was downloaded in bounded range parts and streamed
during joins. Logical content digest:
`d40c8a7b3825dfca896fe234de56040a70e7a215ee34a895468116e51e1afcae`.
Because the registry is current, every historical match carries a temporal-identity warning.
The exact URLs, local observation times, byte sizes, per-part hashes, terms, and publication
obligation are recorded in `source-manifest.json`; acquisition/audit code is
`backend/src/sadar/pipelines/acquire_context.py`.

## Availability gates

| Source | Gate | Result |
|---|---|---|
| Historical QNH | latest-prior match and ≥95% newer-source coverage | passed, 96.39% |
| Airport wind | latest-prior match and ≥80% usable components | failed, 78.09% |
| Aircraft type | lawful registry join and ≥80% coverage | passed, 84.28% |
| Aircraft configuration | observed per-operation source | failed; no public source found |
| Actual mass | observed per-operation source | failed; no public source found |
| ATC clearance/intent | observed per-operation source | failed; no public source found |

OpenAP and EUROCONTROL BADA can supply generic type-performance information, not actual flight
mass, configuration, clearance, or intent. BADA also requires licensed access. Neither is used to
invent unavailable operational facts.

## Leakage and retention

Weather uses the latest report at or before the attempt midpoint with a maximum age of 30 minutes;
future reports are never used. Current registry
metadata is allowed only as disclosed research context. Train fits the empirical reference;
2019 validation and the audited 2025 snapshot transform only. The burned 2020 and 2026 cohorts
are not accessed by this iteration.

Machine-readable coverage reports and their source hashes live under `artifacts/`.
