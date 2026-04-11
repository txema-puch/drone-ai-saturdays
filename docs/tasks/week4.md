# Week 4 — Integration + Evaluation + Demo Polish

**Status:** Not started
**Must ship by end of week:** Full metrics table, end-to-end pipeline, demo runs on a laptop with no internet

---

## Objective

Put everything together and measure it properly.
At the end of this week you should be able to run the full pipeline — raw data in, anomaly score out —
on a laptop, offline, in under 1 second per trajectory.

This is the last week for new functionality. Week 5 is writeup and polish only.

---

## Tasks

### Full evaluation
> Depends on: LSTM weights + threshold from Week 3, anomaly test set from Week 3

- [ ] Combine normal test segments and injected anomalies into a single labeled evaluation set
- [ ] Score all segments with both the LSTM Autoencoder and the Isolation Forest
- [ ] Compute AUROC, F1, and false positive rate for both models; share the table in Discord
- [ ] Generate a precision-recall curve and save to `docs/weekly/figures/`
- [ ] Check success criteria:
  - LSTM AUROC > 0.85?
  - FPR ≤ 15%?
  - LSTM AUROC > IF AUROC? (confirms the ML model adds value)
- [ ] Build a simple rule-based geofence baseline (flag trajectories that get too close to LEMD) — its AUROC should be below 0.80; if it's above, the injected anomalies are too easy
- [ ] Run an ablation: retrain without the distance-to-LEMD feature and compare AUROC — record the delta for the writeup

### Data quality fixes (if needed)
- [ ] If evaluation surfaces data issues (NaN-heavy segments, normalization bugs): fix them in the pipeline and re-export
- [ ] If LSTM AUROC is below 0.85: one targeted fix attempt is allowed (one change at a time)
  - Hard stop: if still below 0.75 after one attempt, ship with IF-only results

### Demo polish
> Depends on: working LSTM from Week 3

- [ ] `demo.py` must work fully offline — no live API calls, no external dependencies at demo time
- [ ] Add a dropdown to switch between a normal trajectory and an anomalous one; show the anomaly type label
- [ ] Color each trajectory point by its local reconstruction error (green / yellow / red)
- [ ] Show identity gate status per track with a badge
- [ ] Measure inference time for one trajectory — must be under 1 second on CPU; if not, simplify
- [ ] Test with WiFi off — it must still run

---

## Done when

- [ ] Metrics table (AUROC, F1, FPR for both models) shared in Discord
- [ ] PR curve saved to `docs/weekly/figures/`
- [ ] Success criteria result shared in Discord (PASS/FAIL per criterion)
- [ ] Demo runs end-to-end on a laptop with WiFi off
- [ ] Inference time measured and < 1s
- [ ] Ablation delta recorded
