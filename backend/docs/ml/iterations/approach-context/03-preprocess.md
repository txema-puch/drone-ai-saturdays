# Phase 3 — Context preprocessing

## Weather decoding

`backend/core/approach_context.py` decodes NOAA quality flags before accepting QNH, wind,
temperature, or dew point. Sentinel values and suspect/error quality codes become missing. QNH
must remain within 850–1100 hPa; wind direction is normalized to `[0, 360)` and speed to m/s.

Observations are ordered by UTC time. An attempt receives the latest report at or before its
midpoint when it is no more than 1,800 seconds old. Future observations are never eligible.
Missing or stale context produces named reasons and preserves the ADS-B-only fallback.

## Aircraft join

Aircraft metadata is streamed from the chunked OpenSky snapshot and filtered to requested
`icao24` values. Type designators are normalized to uppercase. Missing, conflicting, or unknown
types use the published `unknown` reference cells; assessed speed is never used to infer class.

## Uploaded evidence

Analyst uploads may optionally include `qnh_hpa`, `wind_from_direction_deg`, `wind_speed_mps`,
and `aircraft_typecode`. Values are bounded and canonicalized with the input digest. One operation
may carry only one non-empty type code, and all weather fields supplied for an operation must be
co-located on the same report rows. Supplied facts are labeled `analyst_supplied`; absent context
remains explicit rather than fetched or imputed by the service.

## Gate result

Passed. Parsing, temporal joins, source digests, missingness, and fallback behavior are
deterministic and test-covered.
