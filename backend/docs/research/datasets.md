# Datasets

All datasets identified so far. **None have been validated yet** — this is a raw list for exploration.

Status key: `🔍 Not explored` | `⚠️ In progress` | `✅ Validated` | `❌ Rejected`

---

## ADS-B / Trajectory — the in-scope modality (post 2026-04-11 design freeze)

Organized by friction to access. Tier 1 = use today, no gate.

### Tier 1 — Free, no application, usable today

#### OpenSky REST API (authenticated free tier) ⭐ WEEK-1 ENTRY POINT
- **Status:** 🔍 Not explored — scheduled for Week 1
- **URL:** https://openskynetwork.github.io/opensky-api/rest.html
- **What it is:** Live + 1h-historical ADS-B state vectors (lat/lon/alt, velocity, heading, callsign, ICAO24, squawk, on-ground flag).
- **Quota:** 4,000 credits/day authenticated (OAuth2 client). `/states/all` with LEMD bbox costs 1–4 credits/call → ~1 call/min well within budget.
- **LEMD bbox:** `lamin=40.3, lomin=-3.8, lamax=40.7, lomax=-3.3` (≈ 40 NM around ADLER/LEMD).
- **Role:** Primary live-harvest source for our own 5-week LEMD state-vector dataset if Trino/ADRR don't arrive in time.
- **Notes:** `/flights/arrival` and `/flights/departure` are historical (nightly batch) and free with auth — good for Layer-1 flight roster.

#### OpenSky Scientific Datasets — Zenodo "Crowdsourced air traffic data 2019–2022"
- **Status:** 🔍 Not explored
- **URL:** https://zenodo.org/records/7923702 — **DOI: 10.5281/zenodo.7923702**
- **Paper:** [ESSD — Crowdsourced Air Traffic Data from the OpenSky Network 2019–2020](https://essd.copernicus.org/articles/13/357/2021/)
- **What it is:** One gzipped CSV per month, ~42M flights. Fields: `callsign, icao24, registration, typecode, origin, destination, firstseen, lastseen, latitude_1/2, longitude_1/2, altitude_1/2`.
- **⚠️ Critical limitation:** Flight-level summaries only — **not** time-series state vectors. One row per flight with first/last position. Useful for Layer-1 (identity/flight roster) and baseline traffic statistics, but **insufficient for training the LSTM autoencoder** on Layer-2.
- **License:** Other (Non-Commercial). Saturdays.AI educational use is fine.
- **Coverage:** Jan 2019 – Dec 2022. No longer updated.

### Tier 2 — Free but requires application / Terms of Use

#### EUROCONTROL R&D Data Archive (ADRR) ⭐ STRONG CANDIDATE
- **Status:** 🔍 Not explored — apply early
- **URL:** https://www.eurocontrol.int/dashboard/rnd-data-archive
- **What it is:** 27M European commercial flights (2015–2024), avg 3M/year. Includes **detailed flight information + planned AND actual trajectories + airspace structure + route network**.
- **Why it fits our architecture:** The "planned vs actual" pairing mirrors our two-layer design (flight-plan match + trajectory anomaly) in a single dataset. LEMD traffic is covered.
- **Eligibility:** "Open for all R&D use" — no university affiliation required. Register OneSky Online → request access → sign Terms of Use → download.
- **Format:** Downloadable after login; "Structure and Sample" user guide (April 2025) describes schema.

#### OpenSky Trino (historical SQL database)
- **Status:** 🔍 Not explored — application uncertain
- **URL:** https://openskynetwork.github.io/opensky-api/trino.html
- **What it is:** Full historical SQL interface — 12 tables, main one is `state_vectors_data4` (10s-sampled pos/vel/status). Also `flights_data4`, `identification_data4`, `acas_data4`, `adsc`, `allcall_replies_data4`, `flarm_raw`.
- **Eligibility:** "University-affiliated researchers, governmental organisations, and aviation authorities." Saturdays.AI is educational, not a university — approval is **not guaranteed**. Pitch needs to lean on open-source + Medium article commitments.
- **Limits:** 2 concurrent + 2 queued queries, 30 min/query max. State vectors retained indefinitely; other tables ~1 year.
- **Access:** My OpenSky → Request Data Access.

#### ADS-B Exchange historical
- **Status:** 🔍 Not explored
- **URL:** https://www.adsbexchange.com/products/historical-data/ — S3 access: https://www.adsbexchange.com/pull-data/
- **What it is:** S3 buckets `adsbx-YYYY-readsb-hist`, `adsbx-YYYY-traces`, `adsbx-YYYY-hires-traces`. "Recent" buckets hold last 90 days live-updated.
- **Free tier:** First-of-the-month data free for non-commercial researchers. Saturdays.AI qualifies.
- **Why it's interesting:** Unfiltered feed — includes military/blocked aircraft OpenSky sometimes strips. Potentially useful for the "anomaly" story (aircraft that try to hide).
- **License:** Non-commercial only. Commercial license required for paid use.

### Tier 3 — Gated, skip

#### EUROCONTROL DDR2
- **Status:** ❌ Rejected — ANSPs and airline operators only. Use ADRR instead.
- **URL:** https://www.eurocontrol.int/ddr

### Spanish / LEMD-specific public sources

#### ENAIRE UAS geographical zones (AIP Spain)
- **Status:** 🔍 Not explored
- **URL:** https://aip.enaire.es/aip/UAS-en.html
- **What it is:** Public UAS no-fly / restricted zones around Spanish airports including LEMD. Sourced from AIP España.
- **Role:** Layer-1 geofence input. A drone inside the LEMD CTR U-Space zone without prior authorization is by definition anomalous.
- **No public API for individual flight plans** — ENAIRE Planea (flight-plan management) is operator-only. Plan to use **zone polygons**, not per-drone plans.

#### AIXM / AIP Spain via Eurocontrol AIX Confluence
- **Status:** 🔍 Not explored
- **URL:** https://ext.eurocontrol.int/aixm_confluence/display/AIX/Spain
- **What it is:** Airspace structure, runway thresholds, approach corridors in AIXM exchange format.

### Python libraries (tooling, not data)

- **pyopensky** — https://github.com/open-aviation/pyopensky — Python interface for both REST and Trino. PyPI: `pyopensky`.
- **traffic** — https://traffic-viz.github.io/ — High-level trajectory handling library on top of pyopensky. Built-in airport filtering, trajectory segmentation, resampling.

### Drone-specific anomaly datasets (evaluation / related work only)

Neither is ADS-B — cited as related work in the Medium article, not used for training:

- **UAV-SEAD** — https://arxiv.org/abs/2602.13900 — 1,396 real flight logs, 52h, labelled state-estimation anomaly classes. UAV-side IMU/GPS.
- **ALFA (CMU)** — 47 UAV flights, 37 with labelled faults (engine/aileron/rudder/elevator) and failure timestamps.

---

---

## Visual / Image Detection

### HuggingFace — Seraphim Drone Detection Dataset
- **Status:** 🔍 Not explored
- **URL:** https://huggingface.co/datasets/lgrzybowski/seraphim-drone-detection-dataset
- **What it is:** 23 open-source datasets merged and unified. All images resized/padded to 640×640, YOLO format annotations.
- **Labels:** Bounding boxes — drone present/absent. No behavior labels.
- **Notes:** Best single-source visual baseline on HuggingFace — broad scene variety from 23 sources.
- **Access:** Free on HuggingFace
- **Relevance:** 6/10 — solid detection baseline, no intent

### HuggingFace — USC MCL Drone Dataset
- **Status:** 🔍 Not explored
- **URL:** https://huggingface.co/datasets/uscmcl/MCL_drone_dataset
- **What it is:** USC drone detection + tracking dataset with user-labeled bounding boxes.
- **Labels:** Bounding boxes + tracking IDs
- **Access:** Free on HuggingFace
- **Relevance:** 5/10 — tracking data, no intent labels

### Roboflow Universe — Drone Detection (general search)
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/search?q=drone
- **What it is:** Aggregator of labeled computer vision datasets. Multiple drone detection datasets with bounding boxes.

### Roboflow — Drones (Mohamed Alaa)
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/mohamed-alaa-dewedar-cy0lj/drones-9cf8x

### Roboflow — Drone Obstacle Detection
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/test-mgani/drone-obstacle-detection-wpltc

### Roboflow — Drones (University of Texas)
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/university-of-texas-at-san-antonio/drones-ncspj/dataset/1

### Roboflow — Drone (sukay)
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/sukay/drone-8iddp/model/1

### Roboflow — Shahed drone
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/e-yjnj4/shahed-y4fsd
- **Notes:** Shahed = Iranian military drone type. May be useful for military/critical infrastructure use case.

### Kaggle — Drone Image Detection with Bounding Boxes
- **Status:** 🔍 Not explored
- **URL:** https://www.kaggle.com/datasets/cybersimar08/drone-detection

### USC GRAD-STDDB
- **Status:** 🔍 Not explored
- **URL:** https://citius.usc.es/investigacion/datasets/usc-grad-stddb
- **What it is:** University of Santiago de Compostela drone dataset.

### M3OT — Multi-Drone Multi-Modality Tracking
- **Status:** 🔍 Not explored
- **URL:** (from planning doc — search "M3OT dataset")
- **What it is:** 21,580 frames, 8h video, 10,790 paired RGB-IR images, 220,000 bounding boxes. Suburban, urban, daytime, dusk, night environments.
- **Notes:** Large and rich. Good for multi-object tracking and detection benchmarks.

### ScienceDirect dataset (video frames)
- **Status:** 🔍 Not explored
- **URL:** https://www.sciencedirect.com/article/pii/S2352340921007976

---

## Thermal / Infrared

### Roboflow — Infrared Imaging Based Drone Detection
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/infrared-imaging-based-drone-detection/infrared-imaging-based-drone-detection
- **What it is:** 5,654 IR/thermal drone images with bounding box annotations.
- **Labels:** Drone bounding boxes in thermal spectrum
- **Notes:** Good complement to RGB detection for night/low-visibility scenarios near infrastructure.
- **Access:** Free on Roboflow
- **Relevance:** 6/10 — thermal detection, no intent labels

### Roboflow — Thermal Drone Dataset
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/new-workspace-at15m/thermal_drone_dataset
- **What it is:** 1,568 thermal UAV images.
- **Labels:** Bounding boxes
- **Access:** Free on Roboflow
- **Relevance:** 5/10 — small dataset, detection only

### Roboflow — Visual + Thermal Drone Detection
- **Status:** 🔍 Not explored
- **URL:** https://universe.roboflow.com/thermal-drone-imagery/visual-drone-detection
- **What it is:** Paired visual + thermal drone detection dataset.
- **Notes:** Multi-modal pairing could support fusion experiments even without RF.
- **Access:** Free on Roboflow
- **Relevance:** 6/10

### IEEE DataPort — Thermal Imaging (AMD3IR)
- **Status:** 🔍 Not explored
- **URL:** https://ieee-dataport.org/keywords/thermal-imaging
- **Notes:** Tagged "Security". Relevant for night detection use case (prisons, anti-poaching).

---

## RF / Radio Frequency

### DroneRF ⭐ HIGHEST PRIORITY
- **Status:** 🔍 Not explored
- **URL:** https://al-sad.github.io/DroneRF/ (paper: https://www.sciencedirect.com/article/pii/S2352340919306675)
- **What it is:** RF signals from 3 drone models captured in the 2.4GHz band. 227 recorded segments.
- **Labels:** Drone operating mode — `off`, `on/connected`, `hovering`, `flying`, `video recording`
- **Why it matters:** Only public RF dataset with **hovering** as a labeled class — closest proxy to intent labels available anywhere.
- **Limitation:** 3 drones only (DJI Phantom, Bebop, AR), controlled lab environment, no infrastructure scenario.
- **Access:** Free, open access via GitHub/IEEE
- **Relevance:** 9/10 — use as RF modality baseline + seed for intent label methodology

### RFUAV — RF Benchmark Dataset (2025)
- **Status:** 🔍 Not explored
- **URL:** https://arxiv.org/html/2503.09033v2
- **HuggingFace mirror:** https://huggingface.co/datasets/kitofrank/RFUAV
- **What it is:** ~1.3 TB raw RF frequency data from 37 distinct UAV types, collected with USRP hardware. Covers wide range of SNR conditions.
- **Labels:** Drone type/model ID. No behavior/intent labels.
- **Notes:** Very large — not suitable for initial prototyping. Good for fine-tuning or transfer learning on RF fingerprinting.
- **Access:** Free on HuggingFace
- **Relevance:** 7/10 — good for drone-type classification, not intent

### DroneDetect — IEEE DataPort
- **Status:** 🔍 Not explored
- **URL:** https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine
- **What it is:** RF signals from 7 popular UAS models (DJI Mavic, Inspire 2, Phantom 4, Parrot Disco, etc.) using BladeRF SDR + GNURadio.
- **Labels:** Drone model classification. No behavior/intent labels.
- **Access:** Free, IEEE DataPort open access
- **Relevance:** 6/10 — drone ID, not intent

### Kaggle — Noisy Drone RF Signal Classification v2
- **Status:** 🔍 Not explored
- **URL:** https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2
- **Also:** https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification (v1)
- **What it is:** RF signal dataset with added noise augmentation. Classification task.
- **Notes:** 2.4GHz / 5.8GHz bands. Good for testing RF model robustness to noise.
- **Access:** Free on Kaggle
- **Relevance:** 5/10 — classification only, no intent labels

---

## Audio

### HuggingFace — Drone Audio Detection Samples
- **Status:** 🔍 Not explored
- **URL:** https://huggingface.co/datasets/zxl-hf-2026/drone-audio-detection-samples

### Kaggle — Drone Audio MFCC (preprocessed)
- **Status:** 🔍 Not explored
- **URL:** https://www.kaggle.com/datasets/vatsal2110/preprocessed
- **What it is:** MFCC features pre-extracted from drone audio. Classification-ready.
- **Notes:** Useful for close-range detection (<200m). High urban noise sensitivity.

---

## Multi-modal

### MMAUD — Multi-drone Multi-modality Dataset
- **Status:** 🔍 Not explored
- **URL:** https://github.com/ntu-aris/MMAUD
- **What it is:** NTU Singapore dataset. Multiple drone types, multiple sensor modalities.

### LRDDV2 — Drexel University
- **Status:** 🔍 Not explored
- **URL:** https://research.coe.drexel.edu/ece/imaple/lrddv2/

---

## Official / Regulatory

### AESA (Spain — drone registry)
- **Status:** 🔍 Not explored
- **URL:** https://www.aesa.gob.es/
- **What it is:** Official Spanish civil drone registry. ~15,000 registered drones.
- **Access:** Formal request required. 2-4 weeks response time.
- **Notes:** Cross-referencing OpenSky with this list = "known vs unknown" signal.

---

## Audio

### HuggingFace — Drone Audio Detection Samples (DADS)
- **Status:** 🔍 Not explored
- **URL:** https://huggingface.co/datasets/geronimobasso/drone-audio-detection-samples
- **What it is:** Largest publicly available drone audio database. Files at 16kHz, 16-bit, mono. Lengths from 500ms to several minutes.
- **Labels:** Drone presence / type
- **Notes:** Acoustic detection is effective at <200m. Could complement RF+visual for close-range scenarios.
- **Access:** Free on HuggingFace
- **Relevance:** 5/10 — useful as a third modality, not a primary signal

---

## Research Notes — Intent Classification Gap (April 2026)

> Recorded after systematic search across Kaggle, HuggingFace, and Roboflow Universe.

**Key finding:** No public dataset provides trajectory-level intent labels for drones (approaching, circling, hovering, retreating) in any critical infrastructure context.

**What exists closest to intent labels:**
- **DroneRF** (RF modality): labels drone operating mode including `hovering` and `flying`. 3 drones, controlled environment. The only dataset with a behavioral label in any modality.
- **VisDrone** (visual): has tracking boxes but no behavior labels.
- Physics-informed ML paper ([Nature Communications 2024](https://www.nature.com/articles/s44172-024-00179-3)): infers intent from trajectory dynamics — methodology is described but the dataset is not public.

**Implication for Scenario 2 (Critical Infrastructure):**
The label gap is a design decision, not a blocker. Two paths:
1. **Use DroneRF hovering/flying labels as proxy** — small but real. Train RF intent classifier, transfer to visual domain.
2. **Derive intent labels from geometry** — apply rule-based labeling to VisDrone or other tracking datasets (e.g., "circling" = heading variance > threshold over N frames; "approaching" = closing distance to fixed point). Then train a supervised classifier on the derived labels. This is the methodology in the physics-informed ML paper and represents the novel contribution a course team could make.

**Data availability reassessment:**
- Detection data: medium-high (many public datasets)
- RF behavior data: low (DroneRF only — 3 drones, 227 segments)
- Trajectory intent labels: near-zero (must be derived)
- Critical infrastructure scenario data: zero (no public dataset)

The team should pick ONE approach and commit, rather than attempting full RF+visual fusion which requires synchronized multi-modal data that doesn't exist publicly.

---

## Exploration notes

> Add notes here as you explore each dataset. What's the format? How many samples? Is it labeled? Any quality issues?

---

## Research Notes — ADS-B data access (2026-04-21)

> Recorded after systematic review of OpenSky Trino docs, Zenodo, EUROCONTROL, ADS-B Exchange, and ENAIRE.

**Saturdays.AI is educational, not university-affiliated** — Trino approval is therefore uncertain. The project needs a Plan A that doesn't depend on it.

**Recommended priority order:**

1. **EUROCONTROL ADRR** — apply first. Explicitly "open for all R&D use", 27M flights 2015–2024, includes planned *and* actual trajectories for European traffic. Lowest-friction path to a serious dataset that already pairs the two signals our architecture needs.
2. **OpenSky REST (authenticated)** — start harvesting LEMD bbox immediately in parallel. 4k credits/day covers ~1 call/min with no gate; three weeks of collection = usable training set.
3. **OpenSky Trino** — apply as a nice-to-have. Pitch strength lives in open-source + Medium commitments. If denied, project still ships.
4. **Zenodo 2019–2022 flightlist** — useful only for Layer-1 (flight roster / Origin-Destination baselines). **Do not train Layer-2 on it** — it's not state-vector data.
5. **ADS-B Exchange** — hedge. One free month for cross-validation against OpenSky coverage.

**What changed from the original design doc assumption:**
- Design doc assumes OpenSky Trino as primary source. Eligibility text ("university-affiliated") makes that a risk we didn't account for.
- EUROCONTROL ADRR emerged as a serious alternative that was not on our radar and arguably fits the two-layer architecture better.
- Zenodo dataset is flight-level only, not the hourly state-vector dumps we assumed existed. Schema verified from DOI 10.5281/zenodo.7923702.
