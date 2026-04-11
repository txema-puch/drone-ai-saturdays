# Week 1 — Foundation + Data Recon

**Status:** In progress
**Owner(s):** P1 (data recon) + P4 (DevOps/infra)
**Notebook:** `notebooks/01_data_recon.ipynb`
**Must ship by end of week:** EDA notebook with histograms, summary shared in Discord, CI green, shared Drive folder live

---

## Objective

Before writing any model code, confirm the data exists and is usable.
Answer three concrete questions about the LEMD bounding box data.
Set up the shared infrastructure everyone else depends on.

---

## P1 — Data Recon

### Setup
- [ ] Register for OpenSky research account at opensky-network.org
  - Goes to review queue, can take 1-3 days — **do this today, not at the weekend**
  - While waiting: use the live REST API fallback in the notebook (works without account)

### Run the notebook
- [ ] Open `notebooks/01_data_recon.ipynb` in Google Colab
- [ ] Run Option B (live REST API) first — verify the bbox returns real data
- [ ] Once research account approved: run Option A (Impala) for one full month of data
- [ ] Save the raw output as `data/raw/lemd_jan2024.parquet` to shared Google Drive

### Answer these questions (share in Discord)
- [ ] How many unique ICAO24 tracks are in the bounding box?
- [ ] What does the altitude distribution look like? (histogram)
- [ ] What does the speed distribution look like? (histogram)
- [ ] After applying alt < 1500m AND velocity < 50 m/s: how many tracks survive?
- [ ] How long are the tracks? (distribution of state vectors per ICAO24)
- [ ] Anything plausibly drone-sized? (alt < 200m AND velocity < 15 m/s)

### Fallback decision
- [ ] If fewer than 500 usable tracks after filtering: flag in Discord immediately
  - Fallback options in order: widen bbox → extend time range → relax altitude filter
  - See design doc Open Question 2 for full fallback tree

---

## P4 — DevOps / Infra

### Google Drive shared folder
- [ ] Create `drone-ai-saturdays/` folder in Google Drive
- [ ] Create subfolders: `data/raw/`, `data/processed/`, `models/`
- [ ] Share with all 4 teammates (Editor access)
- [ ] Test: verify at least one other person can mount it in Colab successfully
- [ ] Paste the mount path in Discord: `/content/drive/MyDrive/drone-ai-saturdays/`

### GitHub Actions CI
- [ ] Create `.github/workflows/ci.yml`
- [ ] What it should do: run `uv sync` and a basic import check on push to main
- [ ] Goal: green checkmark on the repo so everyone knows the environment is installable
- [ ] Does NOT need to run the notebooks — just verify dependencies install

### Streamlit skeleton
- [ ] Create `demo.py` in the repo root
- [ ] What it needs to show (stub only, no real model yet):
  - A Folium map centered on LEMD (lat 40.4719, lon -3.5626)
  - A hardcoded sample trajectory drawn as a line on the map
  - A sidebar with a threshold slider (0.0 to 1.0)
  - A placeholder "Anomaly score: —" text that updates when slider moves
- [ ] Verify it runs locally: `uv run streamlit run demo.py`

### .env template
- [ ] Create `.env.example` with placeholders for OpenSky credentials:
  ```
  OPENSKY_USERNAME=
  OPENSKY_PASSWORD=
  ```
- [ ] Verify `.env` is in `.gitignore` (it already should be)

---

## Done when

- [ ] Discord has the data recon summary (track count, histograms, drone candidates)
- [ ] `data/raw/lemd_jan2024.parquet` is in the shared Drive folder
- [ ] GitHub Actions CI is green
- [ ] `demo.py` skeleton runs without errors
- [ ] All 4 teammates can mount the Drive folder in Colab
