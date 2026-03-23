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

## Session 2 — TBD

*(Fill in after next session)*
