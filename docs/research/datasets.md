# Datasets

All datasets identified so far. **None have been validated yet** — this is a raw list for exploration.

Status key: `🔍 Not explored` | `⚠️ In progress` | `✅ Validated` | `❌ Rejected`

---

## ADS-B / Trajectory

### OpenSky Network
- **Status:** 🔍 Not explored
- **URL:** https://opensky-network.org/
- **What it is:** Global community network of ADS-B receivers. Covers drones and aircraft that broadcast a transponder signal. Free REST API + historical data.
- **Signal:** Position (lat/lon/alt), speed, heading, callsign — updated every 10-30s
- **Coverage (Spain):** ~15-20 active receivers around Madrid, ~50km combined radius
- **Key limitation:** Only captures drones WITH a transponder. Illegal drones (~70-95%) won't appear. Their absence is itself a signal.
- **Access:** Free account at https://opensky-network.org/ — API key not required for basic use
- **Notes:** Best starting point. 11 years of historical data available.

---

## Visual / Image Detection

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

### IEEE DataPort — Thermal Imaging (AMD3IR)
- **Status:** 🔍 Not explored
- **URL:** https://ieee-dataport.org/keywords/thermal-imaging
- **Notes:** Tagged "Security". Relevant for night detection use case (prisons, anti-poaching).

---

## RF / Radio Frequency

### Kaggle — Noisy Drone RF Signal Classification
- **Status:** 🔍 Not explored
- **URL:** https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification
- **What it is:** RF signal dataset for classifying drone vs. non-drone radio emissions.
- **Notes:** 2.4GHz / 5.8GHz bands. Relevant if we go the RF detection route.

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

## Exploration notes

> Add notes here as you explore each dataset. What's the format? How many samples? Is it labeled? Any quality issues?
