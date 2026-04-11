# Week 3 — LSTM Autoencoder Training

**Status:** Not started
**Owner(s):** P2 (model) + P4 (demo wiring) + P3 (anomaly injection prep)
**Notebook:** `notebooks/03_lstm.ipynb`
**Must ship by end of week:** `models/lstm_ae.pt` saved, loss curve plotted, demo shows real scores

---

## Objective

Train the core ML model: an LSTM Autoencoder that learns what normal flight looks like
by trying to reconstruct trajectory sequences. High reconstruction error = anomalous.

This week has a hard stop: **if the loss is not decreasing by Saturday, ship the IF-only demo.**
Do not carry a broken training loop into Week 4.

---

## P2 — LSTM Autoencoder

**Depends on:** `data/processed/train.parquet` and `val.parquet` from Week 2

### Understand the architecture before coding
- [ ] Read the LSTM Autoencoder section of the design doc
- [ ] Understand the data flow:
  - Input: a sliding window of 30 consecutive time steps from one trajectory
  - Encoder LSTM compresses this to a latent vector
  - Decoder LSTM tries to reconstruct the original 30 steps from the latent vector
  - Anomaly score = MSE between input and reconstruction (higher = more surprising = more anomalous)
- [ ] The model is trained on **normal trajectories only** — no anomaly labels needed during training

### Training setup
- [ ] Set up the sliding window dataset:
  - Window size: 30 time steps
  - Stride: 15 (50% overlap so we don't skip data)
  - Each window is one training sample
- [ ] Architecture:
  - Encoder: 2-layer LSTM, hidden size 64
  - Decoder: 2-layer LSTM, hidden size 64
  - Output layer: Linear(64 → 8) to reconstruct the 8 features
- [ ] Loss: MSE between input window and reconstructed window
- [ ] Optimizer: Adam, learning rate 0.001
- [ ] LR scheduler: reduce on plateau (patience=5, factor=0.5) — prevents getting stuck
- [ ] Gradient clipping: max norm 1.0 — prevents exploding gradients

### Training run
- [ ] Run on Colab T4 GPU (Runtime → Change runtime type → T4 GPU)
  - On CPU this takes ~2 hours. On T4: ~15 minutes.
- [ ] Train for 50 epochs
- [ ] Save the best weights (lowest val loss) to `models/lstm_ae.pt` on Drive
- [ ] Plot loss curve: train loss and val loss vs epoch — save to `docs/weekly/figures/week3_loss_curve.png`

### Convergence check (do this Saturday, not Sunday)
- [ ] Is val loss decreasing over time? Even slowly?
- [ ] Has val loss improved at least 10% from epoch 1 to epoch 50?
- [ ] **If no:** call it — ship IF-only demo. Note the failure in Discord with the loss curve.
  Do NOT spend the weekend debugging a training loop. The IF baseline is the fallback.
- [ ] **If yes:** proceed to threshold setting

### Anomaly threshold
- [ ] Load best weights
- [ ] Score all sequences in the validation set (normal trajectories only)
- [ ] Set threshold = 95th percentile of those reconstruction errors
  - This means: 5% of normal flights will be falsely flagged (acceptable FPR)
- [ ] Save threshold to `models/threshold.npy` on Drive
- [ ] Plot reconstruction error distribution with threshold line marked

---

## P3 — Anomaly Injection (prep for Week 4 evaluation)

**Can be done in parallel with P2 training**

- [ ] Take the test set from Week 2 (`data/processed/test.parquet`)
- [ ] Generate 300 synthetic anomalies by perturbing normal segments:
  - **Altitude violation:** add 3 standard deviations to the `alt` feature
  - **Speed spike:** multiply `speed` × 3 for 5 consecutive time steps at the midpoint
  - **Hovering:** set `speed` to 0 for 5 consecutive time steps at the midpoint
  - **Zone approach:** subtract 2 standard deviations from `dist_lemd` (drone gets closer to airport)
- [ ] Each injected trajectory keeps the same length as the original
- [ ] Save as `data/processed/anomalies_test.parquet` on Drive with a column `anomaly_type`
- [ ] Quick sanity check: do the injected anomalies look visually different from normal?
  Plot a few side by side (alt over time, speed over time)

---

## P4 — Demo: wire to real model scores

**Depends on:** `models/lstm_ae.pt` and `models/threshold.npy` from P2

- [ ] Update `demo.py` to load the LSTM model at startup:
  - `model.load_state_dict(torch.load('models/lstm_ae.pt'))`
  - `threshold = np.load('models/threshold.npy')`
- [ ] For the trajectory shown on the map:
  - Score each window of 30 steps as the "animation" progresses
  - Display the current anomaly score (0.0–1.0 normalized) in the sidebar
  - Color the trajectory line: green below threshold, red above
- [ ] Threshold slider in sidebar should now actually affect the alert color
- [ ] If LSTM weights are not ready (P2 hard stop triggered): load `isolation_forest.pkl` instead
  - The demo must work either way — don't block on model type

---

## Done when

- [ ] `models/lstm_ae.pt` saved to Drive (or hard stop declared and IF fallback committed)
- [ ] Loss curve shared in Discord
- [ ] Threshold value shared in Discord
- [ ] `data/processed/anomalies_test.parquet` saved to Drive
- [ ] `demo.py` shows real anomaly scores updating as trajectory plays
