# Decisions

Log of key decisions the team needs to make or has made.
Add a row when something is decided. Link to the discussion (Discord, PR, etc.) if relevant.

---

## Current product decision

**D-015 — Rules-first whole-arrival approach screening** supersedes D-001 through D-004 as the
served product direction. The schema-v3 candidate is implemented, but its sealed qualification
failed (63.1% retention vs 65%; precision unknown), so it is limited to research and evidence
labeling. See
[`../ml/decisions/D-015-rules-first-approach-screening.md`](../ml/decisions/D-015-rules-first-approach-screening.md)
and [`../ml/iterations/approach-screening/07-eval.md`](../ml/iterations/approach-screening/07-eval.md).

## Open decisions

The contextual-data iteration must decide which external sources pass availability, licensing,
time-alignment, missingness and leakage gates. Configuration, mass and ATC clearance remain open
source-availability questions.

---

## Decided

D-001 through D-004 below are the historical initial course scope, not the current product.

| ID | Decision | Rationale | Date | Owner |
|---|---|---|---|---|
| D-001 | Use case: unauthorized drone detection anchored to LEMD | Airport airspace has the best free data (OpenSky), a concrete threat model, and a real stakeholder (AENA/AESA). Reframed from Scenario 8 classification to anomaly detection. | 2026-04-11 | whole team |
| D-002 | Modality: ADS-B primary, source-agnostic model for stretch goal | ADS-B gives free abundant normal-flight data for training. The LSTM model takes [lat, lon, alt, speed, heading] sequences regardless of source — RF triangulation or visual tracking can feed the same scorer without retraining. | 2026-04-11 | whole team |
| D-003 | Dataset: OpenSky Network (primary) + OpenSky aircraft DB (identity gate) | OpenSky historical data via Impala SQL for training (free research account). Live REST API for demo. Aircraft DB CSV (~500k entries) for ICAO24 identity lookup. | 2026-04-11 | whole team |
| D-004 | Scope: anomaly scoring only (no trajectory prediction) | Trajectory prediction (GRU) adds a full extra milestone with unclear payoff. Anomaly detection alone is publishable and demonstrable. Prediction is a stretch goal only if time permits after Week 8. | 2026-04-11 | whole team |

---

## Decision detail

### D-001 — Use case

**Selected:** Airport-Anchored Trajectory Anomaly Detection (LEMD)

The original Scenario 8 framing (three-class intent classification: cooperative / negligent /
hostile) was rejected because:
- No labeled "hostile" dataset exists or can be built in 10 weeks
- Intent is unobservable from trajectory alone
- Three-class framing requires ground truth that isn't available

**Alternative approach:** Framed as anomaly detection. Learn what normal authorized flight looks
like near LEMD from ADS-B data. Flag anything that deviates. No intent classification needed.
Binary output: normal / anomalous.

Full design: [architecture/design-trajectory-anomaly-detection.md](../architecture/design-trajectory-anomaly-detection.md)

---

### D-002 — Signal modality

**Selected:** ADS-B as training source, source-agnostic model for inference

Key insight: training data and inference data can come from different sources. The LSTM
Autoencoder learns normality from ADS-B (abundant, free). At inference, it scores any
trajectory regardless of source: ADS-B, RF triangulation, or visual tracking. Speed and
heading are derived from consecutive position deltas if not directly available.

**Detection pipeline (two layers):**
1. Identity gate: ICAO24 registry lookup + U-Space flight plan match → pre-clear authorized vehicles
2. Anomaly scorer: LSTM Autoencoder on unidentified tracks and as sanity check on cleared vehicles

**Why both layers are needed:** Identity-only fails on spoofed transponders, pre-2021 consumer
drones, and vehicles deviating from their filed plans. Anomaly-only generates noise on the large
volume of authorized traffic. Together they cover the full threat surface.

---

### D-003 — Dataset

**Selected:** OpenSky Network

- **Training data:** Impala SQL bulk export, bounding box lat 40.3–40.6 lon -3.8–-3.5,
  alt < 1500m AND velocity < 50 m/s, 6-12 months historical
- **Identity gate:** OpenSky aircraft database CSV (free download, ~500k registered aircraft)
- **Live API:** `GET /states/all` for real-time demo polling (no account needed, 10s rate limit)
- **Research account:** Required for Impala bulk access — register at opensky-network.org before Week 1

Fallback if data is thin: widen bbox → extend time range → relax altitude filter.
See design doc Open Question 2 for full fallback tree.

---

### D-004 — Scope of prediction

**Selected:** Anomaly scoring only

The 10-week timeline is tight for trajectory prediction as a core deliverable. The LSTM
Autoencoder already uses sequence modeling — it reads a trajectory and reconstructs it, which
requires learning temporal dynamics. Adding a GRU prediction head would consume Weeks 5-7 and
risk the core anomaly detection deliverable.

Prediction is listed as a stretch goal in the design doc. Attempt only if LSTM evaluation
(Week 6) finishes ahead of schedule.
