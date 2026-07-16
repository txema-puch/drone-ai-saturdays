"""Tests for the Isolation Forest baseline (`backend/research/src/sadar_research/trajectory_anomaly/models/baseline.py`).

  ★★ summary stats are padding-robust (masked) and shape-stable.
  ★★ IF fits on train, scores val/test; an obvious outlier scores higher than normals.
  ★★ deterministic in seed.
"""

from __future__ import annotations

import numpy as np

from sadar_research.trajectory_anomaly.models import baseline as bl
from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES, SCALER_FEATURES

N_STATS = len(SCALER_FEATURES) * 4  # mean/std/min/max × 6


def _windows(n: int, T: int = 30, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, size=(n, T, len(AE_FEATURES))).astype("float32")


# ── summary features ──────────────────────────────────────────────────────────

def test_summary_features_shape():
    X = _windows(7)
    mask = np.ones((7, 30), dtype="float32")
    assert bl.summary_features(X, mask).shape == (7, N_STATS)


def test_summary_features_ignores_padding():
    # A 30-step window vs the same 20 real steps + 10 padded steps → identical stats.
    T = 30
    X = _windows(1, T=T, seed=3)
    full_mask = np.ones((1, T), dtype="float32")

    Xpad = X.copy()
    Xpad[0, 20:, :] = 0.0                       # padding written as zeros
    pad_mask = np.ones((1, T), dtype="float32")
    pad_mask[0, 20:] = 0.0                      # ... but masked out

    X20 = X[:, :20, :]
    mask20 = np.ones((1, 20), dtype="float32")

    a = bl.summary_features(Xpad, pad_mask)
    b = bl.summary_features(X20, mask20)
    assert np.allclose(a, b, atol=1e-5)


def test_summary_features_empty():
    assert bl.summary_features(np.empty((0, 30, 9), "float32"),
                               np.empty((0, 30), "float32")).shape == (0, N_STATS)


# ── fit + score ───────────────────────────────────────────────────────────────

def test_outlier_scores_higher_than_normals():
    rng = np.random.default_rng(1)
    X_train = rng.normal(0.0, 1.0, size=(200, 30, len(AE_FEATURES))).astype("float32")
    mask = np.ones((200, 30), dtype="float32")
    base = bl.IsolationForestBaseline.fit(X_train, mask, seed=1)

    normal = rng.normal(0.0, 1.0, size=(20, 30, len(AE_FEATURES))).astype("float32")
    outlier = np.full((1, 30, len(AE_FEATURES)), 12.0, dtype="float32")  # way off-manifold
    nmask = np.ones((20, 30), dtype="float32")
    omask = np.ones((1, 30), dtype="float32")

    assert base.anomaly_score(outlier, omask)[0] > base.anomaly_score(normal, nmask).max()


def test_deterministic_in_seed():
    X_train = _windows(120, seed=2)
    mask = np.ones((120, 30), dtype="float32")
    s1 = bl.IsolationForestBaseline.fit(X_train, mask, seed=7).anomaly_score(X_train, mask)
    s2 = bl.IsolationForestBaseline.fit(X_train, mask, seed=7).anomaly_score(X_train, mask)
    assert np.allclose(s1, s2)


def test_score_length_matches_input():
    X_train = _windows(100, seed=4)
    mask = np.ones((100, 30), dtype="float32")
    base = bl.IsolationForestBaseline.fit(X_train, mask, seed=4)
    val = _windows(33, seed=5)
    vmask = np.ones((33, 30), dtype="float32")
    assert base.anomaly_score(val, vmask).shape == (33,)


# ── kNN-on-summary baseline (wider panel; carried to Phase 7) ─────────────────

def test_knn_outlier_scores_higher_than_normals():
    rng = np.random.default_rng(1)
    X_train = rng.normal(0.0, 1.0, size=(200, 30, len(AE_FEATURES))).astype("float32")
    mask = np.ones((200, 30), dtype="float32")
    knn = bl.KNNSummaryBaseline.fit(X_train, mask, k=5)
    normal = rng.normal(0.0, 1.0, size=(20, 30, len(AE_FEATURES))).astype("float32")
    outlier = np.full((1, 30, len(AE_FEATURES)), 12.0, dtype="float32")
    assert knn.anomaly_score(outlier, np.ones((1, 30), "float32"))[0] > \
        knn.anomaly_score(normal, np.ones((20, 30), "float32")).max()


def test_knn_from_reference_matches_fit():
    # The frozen-reference path (Phase-7 entry) reproduces the fitted detector exactly.
    X_train = _windows(120, seed=2)
    mask = np.ones((120, 30), dtype="float32")
    a = bl.KNNSummaryBaseline.fit(X_train, mask, k=5)
    ref = bl.summary_features(X_train, mask)
    b = bl.KNNSummaryBaseline.from_reference(ref, k=5)
    val = _windows(25, seed=9); vmask = np.ones((25, 30), "float32")
    assert np.allclose(a.anomaly_score(val, vmask), b.anomaly_score(val, vmask))


def test_knn_score_length_and_empty():
    X_train = _windows(80, seed=3); mask = np.ones((80, 30), "float32")
    knn = bl.KNNSummaryBaseline.fit(X_train, mask, k=5)
    assert knn.anomaly_score(_windows(17, seed=6), np.ones((17, 30), "float32")).shape == (17,)
    assert knn.anomaly_score(np.empty((0, 30, 9), "float32"), np.empty((0, 30), "float32")).shape == (0,)
