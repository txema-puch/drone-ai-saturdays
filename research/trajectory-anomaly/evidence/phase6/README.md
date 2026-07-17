# Phase-6 identity evidence

These JSON files are small, human-inspectable evidence needed to identify the frozen
experiment: the exact train/validation/test/held-aside segment split and the kNN
summary-space configuration.

The fitted scaler, kNN summary matrix, and LSTM checkpoint are binary artifacts. They
are not duplicated in Git; fetch and verify them with:

```bash
uv run --project backend/research sadar-research-fetch-training-artifacts \
  --lock backend/research/src/sadar_research/trajectory_anomaly/releases/phase6_training_artifacts.lock.json \
  --destination /tmp/sadar-phase6
```
