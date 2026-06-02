"""Tests for Generator A (`backend/core/inject.py`).

CRITICAL guards (the inject-bench firewall):
  ★★★ inject is VAL/TEST only — never the train fold.
  ★★★ inject uses the PASSED TRAIN-fit scaler — never make_scaler() (unfitted).
  ★★★ derived channels stay consistent — perturb measured, replay recomputes dist/hdg.
Plus: injected timesteps clear *_missing; determinism in seed; per-type mix ≈ §6.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.core import inject as ij
from backend.core.geo import distance_to_closest_runway
from backend.core.preprocessing import AE_FEATURES, MASKED_FEATURES, SCALER_FEATURES, make_scaler

RWY32L = (40.4651, -3.5450)


# ── fixtures: a clean per-segment frame matching preprocess() output ──────────

def clean_segment(sid: str, n: int = 40, lat0: float = 40.40, lon0: float = -3.50) -> pd.DataFrame:
    t0 = 1_500_000_000
    df = pd.DataFrame({
        "segment_id": sid,
        "flight_id": sid.split("#")[0],
        "time": [t0 + i * 10 for i in range(n)],
        "lat": np.linspace(lat0, RWY32L[0], n),
        "lon": np.linspace(lon0, RWY32L[1], n),
        "baroaltitude": np.linspace(2_000.0, 200.0, n),
        "velocity": np.linspace(120.0, 70.0, n),
        "vertrate": np.full(n, -5.0),
        "heading": np.full(n, 320.0),
        "onground": np.full(n, False),
    })
    df["hdg_sin"] = np.sin(np.radians(df["heading"]))
    df["hdg_cos"] = np.cos(np.radians(df["heading"]))
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"]).to_numpy()
    for f in MASKED_FEATURES:
        df[f + "_missing"] = False
    df["flight_phase"] = "approach"
    return df


def clean_pool(n_segs: int = 8) -> pd.DataFrame:
    return pd.concat(
        [clean_segment(f"f{i}#0", lat0=40.40 + 0.005 * i) for i in range(n_segs)],
        ignore_index=True,
    )


def fitted_scaler(pool: pd.DataFrame):
    sc = make_scaler()
    sc.fit(pool[SCALER_FEATURES])
    return sc


# ── ★★★ CRITICAL — inject is VAL/TEST only, with a TRAIN-fit scaler ──────────

def test_critical_inject_refuses_train_fold():
    sc = fitted_scaler(clean_pool())
    with pytest.raises(AssertionError, match="VAL/TEST only"):
        ij.assert_injectable(sc, "train")


def test_critical_inject_refuses_unfitted_scaler():
    with pytest.raises(AssertionError, match="TRAIN-FIT"):
        ij.assert_injectable(make_scaler(), "val")  # make_scaler() is unfitted


def test_critical_make_eval_set_blocks_train():
    pool = clean_pool()
    with pytest.raises(AssertionError, match="VAL/TEST only"):
        ij.make_eval_set(pool, ["f0#0"], fitted_scaler(pool), T=40, seed=0, fold="train")


# ── ★★★ CRITICAL — derived channels stay consistent (replay ran) ─────────────

def test_critical_zone_violation_recomputes_dist_via_replay():
    seg = clean_segment("f0#0")
    perturbed, onset = ij.inject_segment(seg, "zone_violation", np.random.default_rng(1))
    # position moved post-onset ...
    assert not np.allclose(perturbed["lat"].to_numpy(), seg["lat"].to_numpy())
    # ... and dist_to_runway_m matches the perturbed position (replay, not stale).
    expected = distance_to_closest_runway(perturbed["lat"], perturbed["lon"]).to_numpy()
    assert np.allclose(perturbed["dist_to_runway_m"].to_numpy(), expected)


def test_critical_heading_components_stay_on_unit_circle_after_loiter():
    seg = clean_segment("f0#0")
    perturbed, _ = ij.inject_segment(seg, "sustained_loiter", np.random.default_rng(2))
    hs, hc = perturbed["hdg_sin"].to_numpy(), perturbed["hdg_cos"].to_numpy()
    assert np.allclose(np.hypot(hs, hc), 1.0, atol=1e-9)


# ── injected timesteps clear *_missing (synthetic-but-present) ────────────────

def test_injected_timesteps_clear_missing_flags():
    seg = clean_segment("f0#0")
    seg["velocity_missing"] = True  # pretend Phase 3 imputed everything
    perturbed, onset = ij.inject_segment(seg, "altitude_high", np.random.default_rng(3))
    post = perturbed.index[onset:]
    for f in MASKED_FEATURES:
        assert not perturbed.loc[post, f + "_missing"].any(), f"{f}_missing still set post-onset"


# ── determinism ───────────────────────────────────────────────────────────────

def test_inject_segment_deterministic_in_seed():
    seg = clean_segment("f0#0")
    a, _ = ij.inject_segment(seg, "zone_violation", np.random.default_rng(7))
    b, _ = ij.inject_segment(seg, "zone_violation", np.random.default_rng(7))
    assert np.allclose(a["lat"].to_numpy(), b["lat"].to_numpy())


def test_make_eval_set_deterministic_in_seed():
    pool = clean_pool(8)
    sc = fitted_scaler(pool)
    ids = [f"f{i}#0" for i in range(8)]
    a = ij.make_eval_set(pool, ids, sc, T=40, seed=42, fold="val")
    b = ij.make_eval_set(pool, ids, sc, T=40, seed=42, fold="val")
    assert np.array_equal(a.y, b.y)
    assert a.kind == b.kind
    assert np.allclose(a.X, b.X)


# ── per-type mix ≈ §6 ─────────────────────────────────────────────────────────

def test_assign_kinds_matches_calibrated_mix():
    rng = np.random.default_rng(0)
    kinds = ij.assign_kinds(20_000, rng)
    counts = pd.Series(kinds).value_counts(normalize=True)
    for k, target in ij.DEFAULT_MIX.items():
        assert abs(counts[k] - target) < 0.02, f"{k}: {counts[k]:.3f} vs target {target}"


# ── make_eval_set shape + labeling ────────────────────────────────────────────

def test_make_eval_set_shapes_and_labels():
    pool = clean_pool(10)
    sc = fitted_scaler(pool)
    ids = [f"f{i}#0" for i in range(10)]
    s = ij.make_eval_set(pool, ids, sc, T=40, seed=1, fold="val", inject_rate=0.5)
    assert s.X.shape == (10, 40, len(AE_FEATURES))
    assert s.loss_mask.shape == (10, 40)
    assert set(s.y.tolist()) == {0, 1}                 # both classes present
    assert s.y.sum() == 5                              # 50% injected
    # injected windows carry a real onset; normals carry −1
    for yi, oi in zip(s.y, s.onset):
        assert (oi >= 0) == bool(yi)


def test_inject_onset_stays_within_window_len():
    # codex finding #1: on a long segment the onset must land inside the kept window (< T),
    # else the windowed sample is labeled anomaly but contains no perturbation.
    seg = clean_segment("f0#0", n=600)
    _, onset = ij.inject_segment(seg, "zone_violation", np.random.default_rng(0), window_len=260)
    assert onset < 260


def test_speed_spike_raises_velocity_at_onset():
    seg = clean_segment("f0#0")
    perturbed, onset = ij.inject_segment(seg, "speed_spike", np.random.default_rng(5))
    assert perturbed["velocity"].iloc[onset] > seg["velocity"].iloc[onset]
