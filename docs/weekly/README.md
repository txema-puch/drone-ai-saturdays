# Weekly Progress

Session notes and progress log. Add an entry each Saturday session.

---

## Template

Copy this for each session:

```
## Session N — YYYY-MM-DD

**Attendees:**
**Duration:**

### What we did
-

### What we learned
-

### Blockers
-

### Next session goals
-

### Links / artifacts
-
```

---

## Session 1 — 2026-03-22 (pre-kickoff)

**Attendees:** txema (solo)
**Status:** Project definition in progress

### What we did
- Reviewed planning document (Identificación y Predicción de Rutas de Drones)
- Catalogued all dataset links found so far
- Set up repo structure (docs workspace)
- Drafted team Discord message to align on use case and modality

### Open questions going into Session 2
- Which use case to focus on? → [D-001](../decisions/README.md)
- Which signal modality? → [D-002](../decisions/README.md)
- Which dataset to start with? → [D-003](../decisions/README.md)

### Key insight
The architecture in the planning doc is solid but assumes all data sources work. The ADS-B / OpenSky path is the lowest-risk starting point because the data is free, accessible immediately, and the ML task (time-series anomaly detection + trajectory prediction) is well-matched to what we're learning. **BUT:** OpenSky only covers cooperative drones with transponders — this is a fundamental limitation if illegal drones are the target.

---

## Session 2 — 2026-04-11 (design session)

**Attendees:** txema (solo, design + architecture)
**Duration:** ~3 hours

### What we did
- Pressure-tested Scenario 8 (Urban Environments / three-class intent classification)
- Rejected original framing: no labeled "hostile" data exists, intent is unobservable
- Designed alternative: airport-anchored trajectory anomaly detection (Scenario B)
- Wrote full design doc, ran two adversarial spec review rounds (6/10 → 8.5/10)
- Added identity gate layer (ICAO24 registry + U-Space) in response to professor challenge
- Closed all four open decisions (D-001 through D-004)
- Pushed design doc + updated architecture to GitHub

### Key decisions made
- **D-001:** Use case = unauthorized drone detection anchored to LEMD
- **D-002:** ADS-B as training source, source-agnostic model (RF/visual can feed same scorer)
- **D-003:** OpenSky Network (Impala bulk + aircraft DB CSV + live REST API)
- **D-004:** Anomaly scoring only, no trajectory prediction in core scope

### Key insights
- Reframing from classification to anomaly detection sidesteps the unsolvable hostile-labeling problem
- The LSTM Autoencoder is source-agnostic: train on ADS-B, score RF-triangulated or visual-tracked trajectories without retraining. Training data and inference data come from different sources.
- Two-layer architecture: identity gate (fast, no ML) + anomaly scorer (ML). Neither alone is sufficient.
  - Identity gate fails on spoofed transponders and pre-2021 consumer drones
  - Anomaly scorer alone generates noise on the large volume of authorized traffic
- Architecture is location-agnostic: change the bounding box, retrain, deploy elsewhere

### Week 1 assignment (before next session)
One person registers OpenSky research account and runs data recon on LEMD bounding box.
See [design doc](../architecture/design-trajectory-anomaly-detection.md#the-assignment) for exact steps.
Share in team chat: track count, altitude/speed histograms, segment count, drone-candidate check.

### Links / artifacts
- [Design doc](../architecture/design-trajectory-anomaly-detection.md)
- [Decisions log](../decisions/README.md)

---

## Session 3 — TBD

*(Fill in after next session)*
