# Week 2 — Data Pipeline + Identity Gate + IF Baseline

**Status:** Not started
**Owner(s):** P1 (pipeline) + P2 (IF model) + P3 (identity gate) + P4 (demo wiring)
**Notebook:** `notebooks/02_pipeline.ipynb`
**Must ship by end of week:** Processed Parquet in Drive, identity gate working, IF AUROC number reported

---

## Objective

Turn the raw parquet from Week 1 into clean, model-ready data.
Build the identity gate (Layer 1 — no ML).
Train the first model (Isolation Forest) and get an AUROC number.
This number is the baseline everything else will be compared to.

**Gate check before starting:** `data/raw/lemd_jan2024.parquet` must exist in Drive.
If it doesn't, unblock P1 first — nothing else can proceed without data.

---

## P1 — Trajectory Segmentation + Feature Engineering

### Segmentation
- [ ] Load raw parquet from Drive
- [ ] Split each ICAO24 track into segments where gap > 60s or distance > 5km
- [ ] Discard segments shorter than 10 state vectors (~100 seconds of flight)
- [ ] Verify: how many segments do you have after splitting? Share count in Discord

### Feature engineering (per time step)
- [ ] Compute `dist_lemd`: Haversine distance from each point to LEMD ARP (40.4719°N, 3.5626°W)
- [ ] Compute `tod_sin` and `tod_cos`: sin/cos encoding of hour of day (cyclical)
- [ ] Fill missing altitude: use `baroaltitude` first, fall back to `geoaltitude`, then interpolate
- [ ] Fill missing speed and heading: linear interpolation within segment
- [ ] Final feature columns per time step: `[lat, lon, alt, speed, heading, dist_lemd, tod_sin, tod_cos]`

### Normalization + split
- [ ] Split into train/val/test **per segment** (80/10/10) — not per time step
  - Splitting per time step causes leakage (consecutive points are nearly identical)
- [ ] Compute mean and std on training set only
- [ ] Apply normalization to all three splits using training stats
- [ ] Save normalization stats as `data/processed/norm_stats.parquet`
- [ ] Save `data/processed/train.parquet`, `val.parquet`, `test.parquet` to Drive

---

## P3 — Identity Gate

### ICAO24 registry lookup
- [ ] Download OpenSky aircraft database CSV from opensky-network.org/datasets#acas (~30MB)
- [ ] Load into a pandas DataFrame, set `icao24` as index for O(1) lookup
- [ ] Save as `data/processed/aircraft_db.parquet` to Drive
- [ ] Write a function `identity_gate(icao24: str) -> str` that returns `"CLEARED"` or `"UNIDENTIFIED"`

### Validation
- [ ] Run identity gate on a random sample of 50 ICAO24s from the raw dataset
- [ ] Report: what % are in the registry? Share result in Discord
  - Expected: most flights around LEMD should be registered commercial aircraft — if < 60% clear, something is wrong with the CSV

### Integration note
- [ ] The identity gate runs at inference time, not training time
- [ ] It does NOT affect the training data — all raw tracks are treated as normal for training

---

## P2 — Isolation Forest Baseline

**Depends on:** `data/processed/train.parquet` and `test.parquet` from P1

### Train
- [ ] Compute per-trajectory summary statistics: mean, std, min, max of each feature
  - Result: one row per segment, ~32 columns (8 features × 4 stats)
- [ ] Fit Isolation Forest with `n_estimators=200, contamination=0.05`
- [ ] Save model to `models/isolation_forest.pkl` on Drive

### Evaluate
- [ ] Inject 200 synthetic anomalies into the test set:
  - Altitude violation: shift alt up by 3 standard deviations
  - Speed spike: multiply speed × 3 for 5 consecutive time steps
  - Hovering: set speed to 0 for 5 consecutive time steps
- [ ] Score: test normal trajectories + injected anomalies
- [ ] Compute AUROC — report in Discord
- [ ] **Gate check:** if AUROC < 0.65, stop and fix feature engineering before Week 3 starts

---

## P4 — Streamlit Demo (skeleton → real map)

**Depends on:** Drive folder from Week 1

- [ ] Update `demo.py` to load a real trajectory from the processed parquet
  - Pick one random segment from `test.parquet`
  - Draw it on the Folium map as animated points (not just a static line)
- [ ] Add identity gate status display: show "CLEARED" or "UNIDENTIFIED" badge per track
- [ ] Anomaly score is still hardcoded (0.0) — that's fine, wiring to real model is Week 3
- [ ] Verify it runs locally without errors: `uv run streamlit run demo.py`

---

## Done when

- [ ] `data/processed/train.parquet`, `val.parquet`, `test.parquet` are in Drive
- [ ] `data/processed/aircraft_db.parquet` is in Drive
- [ ] `models/isolation_forest.pkl` is in Drive
- [ ] IF AUROC reported in Discord (target > 0.65, ideally > 0.75)
- [ ] Identity gate spot-check result shared in Discord
- [ ] `demo.py` shows a real trajectory on the map
