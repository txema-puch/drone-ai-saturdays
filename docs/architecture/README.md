# Architecture

**Status: Proposed — not committed**

This is the working architecture. It will evolve as we narrow down the use case and dataset.

---

## Active Design Doc

**[design-trajectory-anomaly-detection.md](./design-trajectory-anomaly-detection.md)** — *2026-04-11, APPROVED*

Full design for the selected approach: ADS-B trajectory anomaly detection on OpenSky data
around Madrid Barajas (LEMD). Covers architecture, preprocessing, model (Isolation Forest
+ LSTM Autoencoder), evaluation, team division, 10-week milestone plan, and the assignment
for Week 1. Read this before the architecture overview below.

---

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│          DRONE DETECTION & PREDICTION SYSTEM             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  LAYER 1: DATA SOURCES                                  │
│  ├─ ADS-B (OpenSky) — cooperative drones               │
│  ├─ RF signals — any radio-emitting drone               │
│  ├─ Visual (camera) — physical detection                │
│  ├─ Weather (AEMET) — wind for trajectory correction    │
│  └─ Geofences (OSM) — restricted zone polygons         │
│            ↓                                            │
│                                                          │
│  LAYER 2: FEATURE ENGINEERING                           │
│  ├─ Speed, heading, turn rate, vertical rate            │
│  ├─ Distance to restricted zones                        │
│  ├─ Time context (hour of day, day of week)             │
│  ├─ Registration status (cross-check AESA)              │
│  └─ Wind-adjusted trajectory components                 │
│            ↓                                            │
│                                                          │
│  LAYER 3: ANOMALY DETECTION                             │
│  ├─ Isolation Forest (baseline, unsupervised)           │
│  └─ LSTM Autoencoder (learned normal patterns)          │
│            ↓                                            │
│                                                          │
│  LAYER 4: TRAJECTORY PREDICTION                         │
│  └─ GRU encoder-decoder                                 │
│     Input: last N positions → Output: next 10 min      │
│            ↓                                            │
│                                                          │
│  LAYER 5: RISK SCORING                                  │
│  └─ XGBoost / fusion layer → risk score 0-10           │
│     Weights: geofence proximity > anomaly > trajectory  │
│            ↓                                            │
│                                                          │
│  LAYER 6: OUTPUT                                        │
│  ├─ Risk 0-3: Normal, passive monitoring                │
│  ├─ Risk 4-6: Watch — increased monitoring              │
│  ├─ Risk 7-8: Alert — notify operators                  │
│  └─ Risk 9-10: Critical — immediate action              │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Modality options

We don't need to implement all layers. The architecture is modular — pick 1-2 data sources and build depth there.

| Approach | Data sources | ML tasks | Complexity | Demo impact |
|---|---|---|---|---|
| **A: ADS-B only** | OpenSky | Anomaly detection + trajectory prediction | Medium | Medium |
| **B: Visual only** | Roboflow/Kaggle images | Object detection (YOLO) | Low-Medium | High |
| **C: RF only** | Kaggle RF signals | Signal classification | Medium | Low (hard to visualize) |
| **D: ADS-B + Visual** | OpenSky + images | Detection + tracking | Medium-High | High |
| **E: Full multi-modal** | All of the above | All of the above | High | Very high — but risky in 6 weeks |

**Current lean:** Option D (ADS-B + Visual) gives the best risk/reward. Option A is the safest starting point.

---

## Data flow (Option A — ADS-B)

```
OpenSky API (polling every 30s)
    ↓
Parse states: [icao24, lat, lon, alt, speed, heading, timestamp]
    ↓
Cross-check vs. AESA registry → is_registered flag
    ↓
Feature extraction (rolling window, geofence distances)
    ↓
Isolation Forest → anomaly_score
    ↓
GRU → predicted_positions (next 10 min)
    ↓
Geofence intersection check on predicted path
    ↓
Risk score → alert if threshold exceeded
```

---

## Key technical questions to resolve

- [ ] What's the input sequence length for the GRU? (30 points? 60 points?)
- [ ] How do we label "anomalies" for supervised training given no ground truth?
- [ ] How do we handle the 10-30s polling gap in OpenSky — interpolate or accept sparsity?
- [ ] If we add visual: how do we fuse a bbox detection with an ADS-B track?
- [ ] Evaluation metric for trajectory prediction: ADE (Average Displacement Error)? FDE?

---

## Week-by-week plan (draft)

| Week | Focus | Deliverable |
|---|---|---|
| 1 | Setup + EDA | OpenSky API working, 30 days of data downloaded, EDA notebook |
| 2 | Feature engineering + baseline | 30+ features, Isolation Forest baseline with metrics |
| 3 | DL models | GRU trajectory model + LSTM anomaly detection |
| 4 | Integration + risk scoring | XGBoost fusion, end-to-end pipeline |
| 5 | Demo + evaluation | Working demo, evaluation report |
| 6 | Polish + presentation | Final slides, cleaned code, documented repo |
