"""Tests for the Phase-5 feature module (`backend/core/features.py`).

Covers the shared derivation replay (the injection-bench consistency guarantee), the
go-around detector (every branch of the geometric rule), and the orchestrator's
contract (meta carries `is_go_around`; the firewall stays intact — no fit).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.core import features as fx
from backend.core import preprocessing as pp
from backend.core.geo import distance_to_closest_runway

RWY_LAT, RWY_LON = 40.4651, -3.5450  # 32L threshold


# ── shared derivation replay ──────────────────────────────────────────────────

def _seg_with_derived(n=20, lat=RWY_LAT, lon=RWY_LON, heading=90.0):
    t0 = 1_500_000_000
    df = pd.DataFrame({
        "segment_id": "s#1", "time": [t0 + i * 10 for i in range(n)],
        "lat": [lat + i * 0.001 for i in range(n)], "lon": [lon] * n,
        "baroaltitude": [float(i * 100) for i in range(n)],
        "velocity": [80.0] * n, "vertrate": [3.0] * n,
        "heading": [heading] * n, "onground": [False] * n,
    })
    df["hdg_sin"] = np.sin(np.radians(df["heading"]))
    df["hdg_cos"] = np.cos(np.radians(df["heading"]))
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"]).to_numpy()
    return df


def test_apply_segment_derivations_is_idempotent_on_clean_data():
    seg = _seg_with_derived()
    out = fx.apply_segment_derivations(seg)
    for c in fx.DERIVED_FEATURES:
        assert np.allclose(out[c].to_numpy(), seg[c].to_numpy(), atol=1e-12)


def test_replay_recomputes_dist_after_position_perturbation():
    seg = _seg_with_derived()
    seg2 = seg.copy()
    seg2["lat"] = seg2["lat"] + 0.05  # a route-deviation injection moves position
    out = fx.apply_segment_derivations(seg2)
    expected = distance_to_closest_runway(seg2["lat"], seg2["lon"]).to_numpy()
    assert np.allclose(out["dist_to_runway_m"].to_numpy(), expected)
    # and it actually changed (the stale value would have been wrong)
    assert not np.allclose(out["dist_to_runway_m"].to_numpy(), seg["dist_to_runway_m"].to_numpy())


def test_replay_recomputes_heading_components_and_keeps_unit_circle():
    seg = _seg_with_derived(heading=10.0)
    seg2 = seg.copy()
    seg2["heading"] = 350.0  # a holding/loiter injection turns the aircraft
    out = fx.apply_segment_derivations(seg2)
    assert np.allclose(out["hdg_sin"], np.sin(np.radians(350.0)))
    assert np.allclose(out["hdg_cos"], np.cos(np.radians(350.0)))
    assert np.allclose(np.hypot(out["hdg_sin"], out["hdg_cos"]), 1.0)


def test_replay_silently_reverts_a_direct_derived_perturbation():
    """CONTRACT LOCK (the footgun): perturbing a DERIVED channel directly (hdg_sin)
    instead of the measured handle (heading) is silently overwritten by the replay.
    The bench MUST perturb `heading`, not the sin/cos channels."""
    seg = _seg_with_derived(heading=90.0)
    seg2 = seg.copy()
    seg2["hdg_sin"] = 0.123  # wrong: perturbing the derived channel, not `heading`
    out = fx.apply_segment_derivations(seg2)
    assert np.allclose(out["hdg_sin"], np.sin(np.radians(90.0)))  # reverted to 1.0
    assert not np.allclose(out["hdg_sin"], 0.123)                 # the injection vanished


# ── go-around detector ────────────────────────────────────────────────────────

def _clean_seg(sid, alts, onground=None, dist=None, t0=1_500_000_000):
    n = len(alts)
    return pd.DataFrame({
        "segment_id": sid, "time": [t0 + i * 10 for i in range(n)],
        "baroaltitude": [float(a) for a in alts],
        "onground": (onground if onground is not None else [False] * n),
        "dist_to_runway_m": (dist if dist is not None else [2000.0] * n),
    })


def _fires(seg) -> bool:
    return bool(fx.detect_go_around(seg).iloc[0])


def test_go_around_fires_on_descend_low_then_climb():
    # 3000 -> 200 (low, near runway, airborne) -> climb back to 1500
    alts = list(range(3000, 200, -200)) + [200] + list(range(200, 1600, 200))
    assert _fires(_clean_seg("ga", alts)) is True


def test_go_around_then_land_still_fires():
    # descend -> low -> climb back -> descend -> touch down (the climb-back is the signal)
    alts = list(range(3000, 200, -300)) + [200] + list(range(200, 1500, 300)) + list(range(1500, 0, -300)) + [0, 0]
    og = [False] * (len(alts) - 2) + [True, True]
    assert _fires(_clean_seg("ga2", alts, onground=og)) is True


def test_normal_arrival_does_not_fire():
    # monotonic descent to touchdown, no climb-back
    alts = list(range(3000, 0, -200)) + [0, 0, 0]
    og = [False] * (len(alts) - 3) + [True, True, True]
    assert _fires(_clean_seg("arr", alts, onground=og)) is False


def test_departure_does_not_fire():
    # starts low and climbs out — no descent INTO the low point
    alts = [0, 0] + list(range(0, 3000, 200))
    og = [True, True] + [False] * (len(alts) - 2)
    assert _fires(_clean_seg("dep", alts, onground=og)) is False


def test_touch_and_go_does_not_fire():
    # descend -> touch down (onground) -> take off -> climb. It TOUCHED the ground,
    # so it is a touch-and-go, not a rejected landing — must NOT be in the cohort.
    descent = list(range(3000, 100, -300))
    alts = descent + [0, 0] + [100] + list(range(100, 1500, 300))
    og = [False] * len(descent) + [True, True] + [False] * (1 + len(list(range(100, 1500, 300))))
    assert _fires(_clean_seg("tg", alts, onground=og)) is False


def test_high_overflight_does_not_fire():
    # never gets low near a runway
    alts = [10000] * 20
    assert _fires(_clean_seg("cruise", alts, dist=[8000.0] * 20)) is False


def test_low_but_far_from_runway_does_not_fire():
    # descends low and climbs, but never within runway proximity
    alts = list(range(3000, 200, -200)) + [200] + list(range(200, 1600, 200))
    assert _fires(_clean_seg("far", alts, dist=[40000.0] * len(alts))) is False


# ── orchestrator + firewall ───────────────────────────────────────────────────

def _engaging_raw(n_air=60):
    """A minimal raw-parquet-shaped engaging flight (taxi->takeoff->climb)."""
    rows, t = [], 1_500_000_000
    for i in range(n_air):
        og = i < 8
        phase = "on_ground" if i < 8 else ("takeoff" if i < 16 else "climb")
        rows.append(dict(flight_id="f", icao24="aaa", time=t + i * 10,
                         lat=RWY_LAT + (i + 1) * 0.0008, lon=RWY_LON + (i + 1) * 0.0008,
                         baroaltitude=0.0 if i < 8 else float((i - 8) * 150),
                         velocity=5.0 + i * 2.0, vertrate=(5.0 if 8 <= i < 16 else 2.0),
                         heading=float((i * 6) % 360), onground=og, flight_phase=phase, squawk=0))
    df = pd.DataFrame(rows)
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])
    return df


def test_build_features_meta_has_go_around_column():
    clean, meta = fx.build_features(_engaging_raw())
    assert list(meta.columns) == fx.META_COLUMNS
    assert "is_go_around" in meta.columns
    assert meta["is_go_around"].dtype == bool
    assert len(meta) == len(clean)


def test_build_features_promotes_dist_into_contract_no_fit():
    clean, meta = fx.build_features(_engaging_raw())
    assert "dist_to_runway_m" in pp.AE_FEATURES and "dist_to_runway_m" in pp.SCALER_FEATURES
    assert not clean[pp.AE_FEATURES].isna().any().any()
    assert clean.columns[clean.columns.duplicated()].empty  # no double-listed column
    # firewall: build_features fits nothing — make_scaler stays unfitted
    assert not hasattr(pp.make_scaler(), "mean_")


def test_build_features_deterministic():
    raw = _engaging_raw()
    c1, m1 = fx.build_features(raw)
    c2, m2 = fx.build_features(raw)
    pd.testing.assert_frame_equal(c1, c2)
    pd.testing.assert_frame_equal(m1, m2)


def test_build_features_empty_input():
    """Empty raw → empty clean + empty meta, but meta still carries is_go_around so
    downstream consumers can bind to the column unconditionally."""
    cols = ["flight_id", "time", "icao24", "lat", "lon", "baroaltitude", "velocity",
            "vertrate", "heading", "onground", "flight_phase", "squawk", "dist_to_runway_m"]
    clean, meta = fx.build_features(pd.DataFrame(columns=cols))
    assert len(clean) == 0 and len(meta) == 0
    assert "is_go_around" in meta.columns
