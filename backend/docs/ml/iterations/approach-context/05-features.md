# Phase 5 — Contextual features

## QNH pressure-altitude proxy

QNH produces a first-order correction relative to 1013.25 hPa using 30 ft/hPa. The resulting
altitude bias may make the existing barometric 3° path proxy observable. It is explicitly named
`ncei_metar_qnh_pressure_altitude_proxy`; it is not geometric height, radio altitude, or a
certified glide-path measurement.

## Airport wind

Observed wind-from direction and speed are projected onto the inferred runway course as headwind
and crosswind-from-right components. Wind missed its newer-source coverage gate and is optional
display/context evidence only in v1. It does not change a criterion or convert observed ground
speed into airspeed.

## Aircraft type reference

ICAO type designator becomes the empirical `speed_class`. Exact type/direction/distance cells are
used only when train support passes the existing minimum sample gates. Otherwise lookup falls
back to the immutable `unknown` cell. Manufacturer, model, and category are display-only.

## Unavailable features

Actual landing mass, flap/gear configuration, ATC clearance, and intent are never inferred. The
assessment serializes these fields under `context.unavailable` so downstream interfaces cannot
mistake absence for normality.

## Gate result

Passed for a research candidate with the optional wind gate failed. Every feature has source,
role, units, missingness, and fallback semantics; none is claimed to improve precision without
labels.
