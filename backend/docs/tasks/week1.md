# Week 1 — Foundation + Data Recon

**Status:** In progress
**Must ship by end of week:** EDA results shared in Discord, raw data saved to Drive, CI green, Streamlit skeleton running

---

## Objective

Before writing any model code, confirm the data exists and is usable.
Answer three concrete questions about the LEMD bounding box data.
Set up the shared infrastructure everyone else depends on.

---

## Tasks

### OpenSky account
- [ ] Register for an OpenSky research account at opensky-network.org
  - Goes to a review queue — can take 1-3 days, so do this today
  - While waiting: the public REST API works without an account (limited to live traffic)

### Google Drive shared folder
- [ ] Create a shared `drone-ai-saturdays/` folder with subfolders `data/raw/`, `data/processed/`, `models/`
- [ ] Share with all 4 teammates (Editor access)
- [ ] Verify at least one other person can mount it in Colab and post the path in Discord

### Data recon
- [ ] Query OpenSky for one month of ADS-B state vectors inside the LEMD bounding box
- [ ] Save raw data to `data/raw/lemd_jan2024.parquet` in the shared Drive folder
- [ ] Answer these questions and share results in Discord:
  - How many unique ICAO24 tracks are in the bounding box?
  - What do the altitude and speed distributions look like?
  - After filtering to alt < 1500m and speed < 50 m/s: how many tracks survive?
  - Anything plausibly drone-sized (alt < 200m, speed < 15 m/s)?
- [ ] If fewer than 500 usable tracks after filtering: flag in Discord immediately and discuss fallback (wider bbox, longer time range, relaxed filters)

### GitHub Actions CI
- [ ] Create a CI workflow that runs on push to main: install dependencies and verify basic imports
- [ ] Goal: green checkmark on the repo so everyone knows the environment installs cleanly
- [ ] Does not need to run notebooks — just confirm the package setup works

### Streamlit skeleton
- [ ] Create `demo.py`: a minimal Streamlit app with a Folium map centered on LEMD, a hardcoded sample trajectory, a threshold slider, and a placeholder anomaly score display
- [ ] Verify it runs: `uv run streamlit run demo.py`

---

## Done when

- [ ] Discord has the data recon summary (track counts, distributions, drone candidates)
- [ ] `data/raw/lemd_jan2024.parquet` is in the shared Drive folder
- [ ] All 4 teammates can mount the Drive folder in Colab
- [ ] GitHub Actions CI is green
- [ ] `demo.py` runs without errors
