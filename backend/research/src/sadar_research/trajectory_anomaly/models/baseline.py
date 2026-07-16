"""Phase 6 — the Isolation Forest baseline (D-006, guardrail #10: run FIRST).

The baseline exists so the LSTM-AE is never judged in isolation: D-006 ships the AE only
if `AE val AUROC ≥ IF val AUROC + 0.03`, else it ships IF. So IF and the AE must score the
SAME injected val windows, apples-to-apples.

INPUT = pooled per-segment SUMMARY STATS, not the flattened `T×9` sequence (eng-review
open-Q1). Per window, over its VALID timesteps (padding + imputed excluded via the loss
mask), compute mean / std / min / max of each of the 6 `SCALER_FEATURES` → a 24-dim vector.

Why summary stats, not the flattened sequence:
  - Padding-robust: a flattened `T×9` makes IF score the pad zeros, so a short trajectory
    (lots of padding) looks artificially "normal". Summary stats over valid steps don't.
  - The fair "simple baseline": IF is a tabular/feature-vector detector; handing it a
    per-trajectory feature summary is the honest comparison, not a 360-dim flattened tensor.

Fit on TRAIN-normal only (train has no injections; held-aside is pulled pre-split). Score =
`-score_samples` so HIGHER = more anomalous, matching the AE's reconstruction-error polarity.

Leaf imports (numpy + sklearn + the feature contract). No torch, no `.env`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import NearestNeighbors

from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES, SCALER_FEATURES

# Indices of the 6 scaled features within the 9-dim AE vector (bound by name — survives a
# contract change). sin/cos + onground are deliberately excluded: the baseline summarises
# the same channels the scaler standardises.
SCALER_IDX: list[int] = [AE_FEATURES.index(c) for c in SCALER_FEATURES]
STAT_NAMES: tuple[str, ...] = ("mean", "std", "min", "max")


def summary_features(X: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """`(N, T, 9)` scaled windows + `(N, T)` loss mask → `(N, 24)` per-segment summary
    stats (mean/std/min/max × 6 `SCALER_FEATURES`), computed over VALID timesteps only.

    Masked so padding and imputed rows never enter the stats — the padding-robustness the
    flattened alternative lacks. A window with no valid timestep (shouldn't occur: `T_MIN`
    is 30) falls back to zeros rather than dividing by zero.
    """
    if X.shape[0] == 0:
        return np.empty((0, len(SCALER_IDX) * len(STAT_NAMES)), dtype="float32")

    Xs = X[:, :, SCALER_IDX].astype("float64")          # (N, T, 6)
    m = (mask > 0).astype("float64")[:, :, None]        # (N, T, 1)
    cnt = np.clip(m.sum(axis=1), 1.0, None)             # (N, 1) valid-step count

    mean = (Xs * m).sum(axis=1) / cnt                                  # (N, 6)
    var = ((Xs - mean[:, None, :]) ** 2 * m).sum(axis=1) / cnt
    std = np.sqrt(var)
    mn = np.where(m > 0, Xs, np.inf).min(axis=1)                       # valid-only min
    mx = np.where(m > 0, Xs, -np.inf).max(axis=1)                      # valid-only max

    feats = np.concatenate([mean, std, mn, mx], axis=1)
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0).astype("float32")


@dataclass
class IsolationForestBaseline:
    """Thin IF wrapper that fits on TRAIN-normal summary stats and scores any windows.

    `anomaly_score(X, mask)` returns HIGHER = more anomalous (negated `score_samples`) so it
    drops straight into the same AUROC/F2/FPR/PR-AUC stack the AE's reconstruction error uses.
    """

    model: IsolationForest

    @classmethod
    def fit(cls, X_train: np.ndarray, mask_train: np.ndarray, *,
            seed: int = 42, n_estimators: int = 200) -> "IsolationForestBaseline":
        model = IsolationForest(
            n_estimators=n_estimators, contamination="auto", random_state=seed,
        )
        model.fit(summary_features(X_train, mask_train))
        return cls(model=model)

    def anomaly_score(self, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Per-window anomaly score; higher = more anomalous."""
        return -self.model.score_samples(summary_features(X, mask))


@dataclass
class KNNSummaryBaseline:
    """kNN distance-to-manifold on the SAME pooled summary stats (Phase-6 wider-baseline panel).

    Added after the D-006 panel (AE vs IsolationForest only) was found too narrow: on synthetic
    val this simple detector OUTSCORED the LSTM-AE (0.707 vs 0.664). Score = distance to the
    k-th nearest TRAIN-normal segment in 24-dim summary space — "how far from any known normal
    flight?". Higher = more anomalous (same polarity as the AE / IF). Carried (frozen) into the
    Phase-7 real-anomaly burn alongside the AE; the real anomalies decide (07-train.md §4c,
    07-eval-prep Layer 6). Stateful at inference (holds the train reference set).
    """

    nn: NearestNeighbors
    k: int

    @classmethod
    def fit(cls, X_train: np.ndarray, mask_train: np.ndarray, *, k: int = 5) -> "KNNSummaryBaseline":
        nn = NearestNeighbors(n_neighbors=k).fit(summary_features(X_train, mask_train))
        return cls(nn=nn, k=k)

    @classmethod
    def from_reference(cls, train_summary: np.ndarray, *, k: int = 5) -> "KNNSummaryBaseline":
        """Rebuild from a frozen train-summary matrix (reproducible Phase-7 entry — no retrain)."""
        return cls(nn=NearestNeighbors(n_neighbors=k).fit(train_summary), k=k)

    def anomaly_score(self, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Per-window anomaly score = distance to the k-th nearest train segment (higher = more
        anomalous)."""
        if X.shape[0] == 0:
            return np.empty(0, dtype="float32")
        return self.nn.kneighbors(summary_features(X, mask))[0][:, -1].astype("float32")
