# Problem Overview

## What are we building?

A system to **detect and predict the routes of unauthorized drones** in restricted or sensitive airspace.

The key word is *predict*. Existing systems (radar, ADS-B, visual monitoring) react after a drone is already in a restricted zone. Our goal is to anticipate where a drone is heading — with enough lead time for operators to act.

---

## Why now (2026)?

- **3.5M+ civil drones registered globally** (2024), growing 37% YoY
- **Only 10-15% of drones in circulation are legally registered** — the rest are invisible to current systems
- **Traditional radar doesn't see drones under ~5kg** — RCS too small
- **ADS-B only covers drones with a transponder** — ~70-95% of illegal drones have none
- **Current systems react after the event** — no trajectory prediction exists at scale

**Regulatory tailwind:** EASA's Remote ID mandate (2026) requires all drones to broadcast identification. This creates both a detection surface and a compliance gap worth filling.

---

## The gap

| What exists | What doesn't |
|---|---|
| ADS-B detection of cooperative drones | Prediction of where a drone is going |
| Visual spotting by humans | Automated multi-signal fusion |
| Rule-based geofence alerts | Risk scoring with context |
| Radar for large aircraft | Detection of small (<1kg) drones |

---

## Scale of the problem (2025 data)

- 2,847 drone sightings near airports reported in Spain (AESA, 2025)
- 150+ flight delays/day in the US due to drone incidents
- 140+ drone incidents over prisons in Spain (contraband delivery)
- 6 incidents over nuclear plants in Europe
- 500+ border incidents/year (US-Mexico, drone-assisted trafficking)

---

## Proposed solution (high level)

A layered ML system:

1. **Data ingestion** — ADS-B (OpenSky), RF signals, visual feeds, weather (AEMET), geofences (OSM)
2. **Feature engineering** — speed, heading, turn rate, altitude, proximity to restricted zones, time context
3. **Anomaly detection** — identify flights that don't match "normal" civil aviation patterns
4. **Trajectory prediction** — predict where the drone will be in the next 5-10 minutes
5. **Risk scoring** — combine signals into a 0-10 risk score per drone
6. **Alerting** — threshold-based notifications to operators

The architecture is designed to be modular: each data source and each model is a pluggable component.

---

## What we are NOT building

- A drone interception / countermeasure system
- A real-time production system (we're building a proof of concept)
- A system that works globally (focus: Spain / Madrid area)
