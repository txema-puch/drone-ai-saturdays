# Problem Overview

## What are we building?

A two-layer system to **detect unauthorized drones** operating near Madrid-Barajas (LEMD) using ADS-B trajectory data.

**Layer 1 — Identity gate:** ICAO24 registry lookup + U-Space flight plan match. Pre-clears known authorized aircraft.

**Layer 2 — Anomaly scorer:** LSTM Autoencoder trained on normal ADS-B flight patterns near LEMD. Flags trajectories that deviate from learned normal behavior. Binary output: normal / anomalous.

Decision log: [decisions/README.md](../decisions/README.md)

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

## Pipeline (as built)

1. **Data ingestion** — OpenSky ADS-B via Impala SQL (historical) and REST API (live demo). Bounding box: lat 40.3–40.6, lon -3.8–-3.5, alt < 1500m, velocity < 50 m/s.
2. **Feature engineering** — per time step: `[lat, lon, alt, speed, heading, distance_to_lemd_arp, in_restricted_zone, time_of_day_sin, time_of_day_cos]`. Resampled to 10s intervals.
3. **Identity gate** — ICAO24 lookup against OpenSky aircraft DB + U-Space flight plan match. Pre-clears known authorized vehicles; unidentified tracks proceed to scoring.
4. **Anomaly scorer (two milestones):**
   - Milestone 1 (Week 3): Isolation Forest on trajectory feature statistics — baseline
   - Milestone 2 (Week 3): LSTM Autoencoder — reconstructs normal sequences; high reconstruction error = anomalous
5. **Alerting** — flag anomalous tracks for operator review in Streamlit demo

Full system design: [architecture/design-trajectory-anomaly-detection.md](../architecture/design-trajectory-anomaly-detection.md)

---

## What we are NOT building

- Trajectory prediction (cut from scope — D-004; stretch goal only after Week 4)
- Multi-modal fusion with RF, visual, or weather signals (ADS-B only for this course)
- A drone interception / countermeasure system
- A real-time production system (proof of concept)
- A system that works globally (focus: LEMD bounding box)
