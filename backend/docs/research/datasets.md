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
