# Week 2 — Data Pipeline + Identity Gate + IF Baseline

**Status:** Not started
**Must ship by end of week:** Processed splits in Drive, identity gate working, IF AUROC reported in Discord

---

## Objective

Turn the raw parquet from Week 1 into clean, model-ready data.
Build the identity gate (Layer 1 — no ML needed).
Train a first anomaly detection model and get a baseline AUROC number.

**Gate check before starting:** `data/raw/lemd_jan2024.parquet` must exist in the shared Drive folder.

---

## Tasks

### Trajectory segmentation + feature engineering
> Depends on: raw parquet from Week 1

- [ ] Split each aircraft track into continuous flight segments (decide your own gap threshold)
- [ ] Discard segments that are too short to be meaningful
- [ ] Engineer features per time step — at minimum: position, altitude, speed, heading, distance to LEMD ARP, time of day
- [ ] Handle missing values in altitude and speed
- [ ] Split segments into train/val/test sets — think carefully about how you split (per segment, not per time step)
- [ ] Normalize using training set statistics only; save normalization stats
- [ ] Save `data/processed/train.parquet`, `val.parquet`, `test.parquet` to Drive

### Identity gate
- [ ] Download the OpenSky aircraft registry (public CSV, ~30MB)
- [ ] Build a lookup: given an ICAO24 identifier, return "CLEARED" or "UNIDENTIFIED"
- [ ] Spot-check on a sample of ICAO24s from the dataset — what % are in the registry? Share in Discord
  - Most traffic around LEMD should be registered commercial aircraft. If it's very low, something is wrong.
- [ ] Note: this gate runs at inference time only — it does not affect training data

### Isolation Forest baseline
> Depends on: processed train/test splits

- [ ] Summarize each trajectory segment as a fixed-length feature vector (your choice of aggregation)
- [ ] Train an Isolation Forest on normal trajectories
- [ ] Inject synthetic anomalies into the test set to evaluate — at minimum cover: abnormal altitude, abnormal speed, hovering behavior
- [ ] Compute AUROC and report in Discord
- [ ] If AUROC < 0.65: stop and revisit feature engineering before Week 3

### Streamlit demo update
- [ ] Update `demo.py` to show a real trajectory from the processed data on the map
- [ ] Add an identity gate status badge per track (CLEARED / UNIDENTIFIED)
- [ ] Anomaly score can stay hardcoded for now — real wiring comes in Week 3

---

## Done when

- [ ] `data/processed/train.parquet`, `val.parquet`, `test.parquet` are in Drive
- [ ] Identity gate spot-check result shared in Discord
- [ ] IF AUROC reported in Discord (target > 0.65)
- [ ] `demo.py` shows a real trajectory with identity gate status
