# Trajectory-anomaly experiment

This is the original learned-model track. It trained an LSTM autoencoder on nominal
LEMD ADS-B trajectory segments and compared it with Isolation Forest and summary-space
k-nearest-neighbor baselines.

The sealed test showed useful discrimination for some dynamic events, but the model
did not meet the original overall target and anomaly score did not map to emergency,
incident, or approach-conformance meaning. It is retained as executable historical
evidence and cannot affect the current product.

- [`reproducibility.yml`](reproducibility.yml) — replay contract and immutable artifacts.
- [`lifecycle/manifest.yml`](lifecycle/manifest.yml) — full gate ledger and dataset hashes.
- [`original-design.md`](original-design.md) — original two-layer project design.
- [`data-workflow.md`](data-workflow.md) — historical acquisition and audit workflow.
- [`../../../research/trajectory-anomaly/notebooks/`](../../../research/trajectory-anomaly/notebooks/)
  — lifecycle notebooks and exploratory archive.
