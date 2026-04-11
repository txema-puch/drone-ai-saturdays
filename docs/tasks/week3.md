# Week 3 — LSTM Autoencoder Training

**Status:** Not started
**Must ship by end of week:** Trained model saved to Drive, loss curve shared, demo shows real anomaly scores

---

## Objective

Train the core ML model: an LSTM Autoencoder that learns what normal flight looks like
by reconstructing trajectory sequences. High reconstruction error means the model was surprised — that's the anomaly signal.

**Hard stop:** If the loss is not decreasing by Saturday, ship the IF-only demo and move on.
Do not carry a broken training loop into Week 4.

---

## Tasks

### LSTM Autoencoder
> Depends on: processed train/val splits from Week 2

- [ ] Read the LSTM Autoencoder section of the design doc before writing anything
- [ ] Design a sliding window dataset over the trajectories
- [ ] Implement an encoder-decoder LSTM architecture — encoder compresses a sequence to a latent vector, decoder reconstructs it
- [ ] Train on normal trajectories only — no anomaly labels needed
- [ ] Use a GPU runtime in Colab (Runtime → T4 GPU) — training on CPU will take hours
- [ ] Save the best weights (lowest val loss) to `models/lstm_ae.pt` in Drive
- [ ] Plot train and val loss curves and share in Discord

### Convergence check (do this Saturday, not Sunday)
- [ ] Is val loss consistently decreasing?
- [ ] Has it improved meaningfully from epoch 1 to the last epoch?
- [ ] **If no:** declare the hard stop, commit the IF-only demo, note the loss curve in Discord
- [ ] **If yes:** set the anomaly threshold at the 95th percentile of val reconstruction errors and save it to `models/threshold.npy`

### Anomaly injection for Week 4 evaluation
> Can be done in parallel with training

- [ ] Take the test set from Week 2 and generate synthetic anomalous trajectories
- [ ] Cover at least: abnormal altitude, speed spikes, hovering, and proximity to LEMD ARP
- [ ] Save to `data/processed/anomalies_test.parquet` with an `anomaly_type` column
- [ ] Sanity check: do the injected anomalies look visually different from normal trajectories?

### Streamlit demo — wire to real model
> Depends on: trained weights and threshold

- [ ] Update `demo.py` to load the LSTM model and score trajectories in real time
- [ ] Show the anomaly score updating as the trajectory plays; color the path green/red by threshold
- [ ] If the hard stop was triggered: wire to the IF model instead — the demo must work either way

---

## Done when

- [ ] `models/lstm_ae.pt` saved to Drive (or hard stop declared with IF fallback working)
- [ ] Loss curve and threshold value shared in Discord
- [ ] `data/processed/anomalies_test.parquet` saved to Drive
- [ ] `demo.py` shows real anomaly scores on a trajectory
