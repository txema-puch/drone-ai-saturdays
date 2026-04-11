# Week 4 — Integration + Evaluation + Demo Polish

**Status:** Not started
**Owner(s):** P3 (evaluation) + P4 (demo polish) + P1+P2 (support)
**Notebook:** `notebooks/04_evaluation.ipynb`
**Must ship by end of week:** Full metrics table, end-to-end pipeline, demo works on laptop with no external calls

---

## Objective

Put everything together and measure it properly.
At the end of this week you should be able to run the full pipeline — raw data in, anomaly score out —
on a laptop, with no internet connection, in under 1 second per trajectory.

This is the last week for new functionality. Week 5 is writeup and polish only.

---

## P3 — Full Evaluation

**Depends on:** LSTM weights + threshold from Week 3, anomaly test set from Week 3

### Build the evaluation set
- [ ] Combine: held-out normal test segments + 300 injected anomalies from Week 3
- [ ] Verify label balance: roughly how many normal vs anomalous? Write it down.
- [ ] Run a basic sanity check: do the injected anomalies look visually different from normals?
  Plot 3 normals and 3 anomalies side by side (altitude over time, speed over time)

### Score both models
- [ ] Score all test segments with the LSTM Autoencoder (load `models/lstm_ae.pt`)
- [ ] Score all test segments with the Isolation Forest (load `models/isolation_forest.pkl`)
- [ ] For LSTM: use sliding window scoring, take the **max** reconstruction error across windows as the segment score

### Compute metrics
- [ ] AUROC (primary — threshold-free, use `sklearn.metrics.roc_auc_score`)
- [ ] F1 at the 95th percentile threshold (load from `models/threshold.npy`)
- [ ] FPR at the 95th percentile threshold (false alarm rate on normal trajectories)
- [ ] Precision-recall curve (plot and save to `docs/weekly/figures/week4_pr_curve.png`)

### Check success criteria
- [ ] LSTM AUROC > 0.85? → report PASS or FAIL
- [ ] FPR ≤ 15%? → report PASS or FAIL
- [ ] LSTM AUROC > IF AUROC? → confirms ML adds value beyond the baseline

### Geofence baseline sanity check
- [ ] Build a simple rule-based checker: flag any trajectory whose average `dist_lemd` < X km
  (tune X to get the best AUROC possible with this simple rule)
- [ ] Its AUROC should be **below 0.80** — if it's above, our injected anomalies are too easy
  and the LSTM isn't actually learning anything the rules couldn't catch

### Ablation study
- [ ] Retrain the LSTM without the `dist_lemd` feature (7 features instead of 8)
- [ ] Compare AUROC with vs without `dist_lemd`
- [ ] Record the delta in a table — this goes in the writeup

---

## P4 — Demo Polish

**Depends on:** Working LSTM from Week 3

### End-to-end pipeline
- [ ] `demo.py` must work with no internet connection and no external calls
  - Models loaded from local Drive mount (Colab) or `models/` folder (local)
  - Data loaded from Drive or `data/processed/`
  - No live OpenSky API calls during demo presentation
- [ ] Test: disconnect WiFi and run the demo — it must still work

### Trajectory selector
- [ ] Let the user pick "normal trajectory" or "anomalous trajectory" from a dropdown
- [ ] Anomalous trajectories: load from the injected anomaly set
- [ ] Show the anomaly type label (altitude / speed spike / hovering / zone approach) in the UI

### Anomaly overlay
- [ ] On the map, color each trajectory point by its local reconstruction error:
  - Green: below threshold
  - Yellow: near threshold (80–100% of threshold)
  - Red: above threshold
- [ ] This makes it visually obvious where in the trajectory the model was "surprised"

### Identity gate display
- [ ] Show a status badge per track: "CLEARED" (green) or "UNIDENTIFIED" (grey)
- [ ] CLEARED tracks should have a note: "Anomaly scoring still runs as sanity check"

### Performance check
- [ ] Measure inference time for one trajectory segment (30 time steps)
- [ ] Must be < 1 second on a laptop CPU (no GPU required for demo)
- [ ] If it's slower: simplify the model or reduce window size, but keep AUROC above 0.85

---

## P1 — Support

- [ ] If data quality issues surface during evaluation (e.g., NaN-heavy segments skewing results):
  fix the preprocessing in notebook 02 and re-export the parquet files
- [ ] Double-check normalization: make sure val and test used the **training set** μ/σ, not their own

## P2 — Support

- [ ] If LSTM AUROC is below 0.85: one targeted fix attempt is allowed
  - Options: train for more epochs, try hidden size 128, try learning rate 0.0005
  - Only one change at a time — don't tune everything at once
  - Hard stop: if still below 0.75 after one fix attempt, ship with IF-only results

---

## Done when

- [ ] Metrics table (AUROC, F1, FPR for both models) shared in Discord
- [ ] PR curve plot saved to `docs/weekly/figures/`
- [ ] Success criteria check result shared in Discord (PASS/FAIL per criterion)
- [ ] Demo works end-to-end on a laptop with WiFi off
- [ ] Inference time measured and < 1s
- [ ] Ablation AUROC delta recorded
