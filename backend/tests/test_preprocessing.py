"""Tests for the Phase-3 preprocessing pipeline (`backend/core/preprocessing.py`).

Synthetic hand-built fixtures (committed as code — tiny, reviewable) exercise every
branch; one real-parquet smoke test runs end-to-end and skips if cycle-3 data is
absent (gitignored). Two tests are CRITICAL guards against silent training
contamination and are marked ★:

  ★ interpolation NEVER crosses a segment boundary  (test_interpolation_never_crosses_boundary)
  ★ make_scaler returns UNFITTED                    (test_make_scaler_returns_unfitted)

Numbers the synthetic fixtures assert are self-contained; the EDA-corpus numbers
(Filter D 99.3%, ~2,598 splits, ~5.9% idle-trim, 500–800 impossible cohort) are
validated against the real data in notebook `07` Part 3, not here.
"""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from sadar_research.trajectory_anomaly.pipeline import preprocessing as pp
from sadar_research.trajectory_anomaly.data.geometry import distance_to_closest_runway

REPO_ROOT = Path(__file__).resolve().parents[2]
# A point right at the 32L threshold — engaging by Filter D; and a far cruise point.
RWY_LAT, RWY_LON = 40.4651, -3.5450
FAR_LAT, FAR_LON = 41.6000, -3.5450  # ~125 km north → never engages

GRID = pp.GRID_S


# ── fixture builders ─────────────────────────────────────────────────────────

def _frame(rows: list[dict]) -> pd.DataFrame:
    """Assemble a raw-parquet-shaped frame and populate dist_to_runway_m exactly as
    the downloader does (real parquets always carry it)."""
    df = pd.DataFrame(rows)
    defaults = dict(icao24="aaa111", squawk=0, operation="unknown")
    for k, v in defaults.items():
        if k not in df.columns:
            df[k] = v
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])
    return df


def _engaging_flight(flight_id="f1", t0=1_500_000_000, n_air=50, lead_park=0,
                     trail_park=0, lat=RWY_LAT, lon=RWY_LON, icao24="aaa111"):
    """taxi(active)→takeoff→climb near the runway, optionally bracketed by parked idle.

    Positions are laid out so movement is unambiguous: parked rows are stationary at
    the park spot; the operation moves AWAY from it (so the first operation row reads
    as active via its incoming step); trailing park sits at the operation's END (no
    position jump back). The only boundary artifact is that a segment's very first
    row has undefined speed (no predecessor) — faithful to the notebook's per-flight
    `_speed = displacement.diff()`.
    """
    rows = []
    t = t0
    for _ in range(lead_park):  # parked before pushback (leading idle), stationary at P0
        rows.append(dict(flight_id=flight_id, icao24=icao24, time=t, lat=lat, lon=lon,
                         baroaltitude=0.0, velocity=0.0, vertrate=0.0, heading=0.0,
                         onground=True, flight_phase="on_ground"))
        t += GRID
    for i in range(n_air):  # operation moves away from P0 (step index i+1)
        og = i < 8
        phase = "on_ground" if i < 8 else ("takeoff" if i < 16 else "climb")
        alt = 0.0 if i < 8 else float((i - 8) * 150)
        vel = 5.0 + i * 2.0  # always moving (>2.5 m/s)
        rows.append(dict(flight_id=flight_id, icao24=icao24, time=t,
                         lat=lat + (i + 1) * 0.0008, lon=lon + (i + 1) * 0.0008,
                         baroaltitude=alt, velocity=vel, vertrate=(5.0 if 8 <= i < 16 else 2.0),
                         heading=float((i * 6) % 360), onground=og, flight_phase=phase))
        t += GRID
    end_lat, end_lon = lat + n_air * 0.0008, lon + n_air * 0.0008
    for _ in range(trail_park):  # parked after landing, stationary at the operation END
        rows.append(dict(flight_id=flight_id, icao24=icao24, time=t, lat=end_lat, lon=end_lon,
                         baroaltitude=0.0, velocity=0.0, vertrate=0.0, heading=0.0,
                         onground=True, flight_phase="on_ground"))
        t += GRID
    return rows


# ── steps 1–3: sort / dedupe / segment ───────────────────────────────────────

def test_dedupe_drops_zero_dt_duplicates():
    rows = _engaging_flight(n_air=30)
    df = _frame(rows)
    dup = df.iloc[[10]].copy()  # exact duplicate timestamp
    df = pd.concat([df, dup], ignore_index=True)
    out = pp.sort_and_dedupe(df)
    assert out.duplicated(subset=["flight_id", "time"]).sum() == 0
    assert len(out) == len(df) - 1


def test_segment_splits_above_180s_not_at_or_below():
    rows = _engaging_flight(n_air=20)
    df = _frame(rows)
    # original boundary gap is 10 s; +171 makes it 181 (> 180) → one extra split
    df.loc[10:, "time"] = df.loc[10:, "time"] + 171
    seg = pp.segment(pp.sort_and_dedupe(df))
    assert seg["segment_id"].nunique() == 2

    df2 = _frame(_engaging_flight(n_air=20))
    df2.loc[10:, "time"] = df2.loc[10:, "time"] + 170  # boundary gap exactly 180 → NO split
    seg2 = pp.segment(pp.sort_and_dedupe(df2))
    assert seg2["segment_id"].nunique() == 1


def test_segment_ids_are_monotonic_within_flight():
    df = _frame(_engaging_flight(n_air=30))
    df.loc[10:, "time"] += 200
    df.loc[20:, "time"] += 200
    seg = pp.segment(pp.sort_and_dedupe(df))
    nums = seg["segment_id"].str.split("#").str[1].astype(int).to_numpy()
    assert (np.diff(nums) >= 0).all()
    assert seg["segment_id"].nunique() == 3


# ── step 4: Filter D ─────────────────────────────────────────────────────────

def test_filter_d_keeps_engager_drops_overflight():
    eng = _frame(_engaging_flight(flight_id="eng", n_air=40))
    over = _frame([dict(flight_id="over", icao24="bbb222", time=1_500_000_000 + i * GRID,
                        lat=FAR_LAT + i * 0.001, lon=FAR_LON, baroaltitude=11000.0,
                        velocity=240.0, vertrate=0.0, heading=180.0, onground=False,
                        flight_phase="cruise") for i in range(40)])
    df = pd.concat([eng, over], ignore_index=True)
    df = pp.segment(pp.sort_and_dedupe(df))
    kept = pp.filter_d(df)
    assert set(kept["flight_id"]) == {"eng"}


def test_filter_d_drops_nonengaging_post_gap_segment():
    """An engaging flight whose post-gap tail is a distant cruise fragment: the flight
    passes (≥1 engaging row) but the non-engaging segment is dropped."""
    eng = _engaging_flight(flight_id="f", n_air=40)
    t_last = eng[-1]["time"]
    cruise = [dict(flight_id="f", icao24="aaa111", time=t_last + 600 + i * GRID,
                   lat=FAR_LAT + i * 0.001, lon=FAR_LON, baroaltitude=11000.0,
                   velocity=240.0, vertrate=0.0, heading=90.0, onground=False,
                   flight_phase="cruise") for i in range(30)]
    df = _frame(eng + cruise)
    df = pp.segment(pp.sort_and_dedupe(df))
    assert df["segment_id"].nunique() == 2
    kept = pp.filter_d(df)
    assert kept["segment_id"].nunique() == 1  # the cruise fragment is gone
    assert kept["flight_phase"].eq("cruise").sum() == 0


# ── step 7 + 11: impossible flag + counter split ─────────────────────────────

def test_each_physical_bound_fires():
    df = _frame(_engaging_flight(n_air=40))
    df = pp.segment(pp.sort_and_dedupe(df))
    df.loc[20, "velocity"] = 999.0      # > 400
    df.loc[21, "vertrate"] = 80.0       # > 50
    df.loc[22, "baroaltitude"] = 20000  # > 16000
    df.loc[23, "baroaltitude"] = -500   # < -100
    flagged, imp = pp.flag_kinematic_impossibility(df)
    assert np.isnan(flagged.loc[20, "velocity"])
    assert np.isnan(flagged.loc[21, "vertrate"])
    assert np.isnan(flagged.loc[22, "baroaltitude"])
    assert np.isnan(flagged.loc[23, "baroaltitude"])
    assert imp.loc[[20, 21, 22, 23]].sum().sum() == 4


def test_routine_nan_is_missing_not_impossible():
    df = _frame(_engaging_flight(n_air=40))
    df = pp.segment(pp.sort_and_dedupe(df))
    df.loc[25, "velocity"] = np.nan      # routine null
    df.loc[26, "velocity"] = 999.0       # impossible
    flagged, imp = pp.flag_kinematic_impossibility(df)
    counters = pp.compute_counters(flagged, imp)
    total = counters.sum()
    assert total["n_imputed_impossible"] == 1          # only the 999 spike
    assert total["n_imputed_missing"] >= 1             # the routine NaN counts here
    assert imp.loc[25].sum() == 0                       # routine NaN is NOT impossible


def test_velocity_zero_placeholder_counts_as_missing_not_impossible():
    df = _frame(_engaging_flight(n_air=40))
    df = pp.segment(pp.sort_and_dedupe(df))
    df.loc[30, "velocity"] = 0.0
    df.loc[30, "baroaltitude"] = 5000.0   # airborne velocity==0 → placeholder (missing)
    flagged, imp = pp.flag_kinematic_impossibility(df)
    assert np.isnan(flagged.loc[30, "velocity"])        # nulled
    assert imp.loc[30].sum() == 0                        # but NOT counted as impossible


# ── step 6: idle-trim ────────────────────────────────────────────────────────

def test_trim_keeps_operation_span_trims_parked_tails():
    rows = _engaging_flight(n_air=40, lead_park=6, trail_park=8)
    df = _frame(rows)
    df = pp.segment(pp.sort_and_dedupe(df))
    df = pp.compute_speed(df)
    trimmed = pp.trim_idle(df)
    # leading 6 + trailing 8 parked rows are gone; the 40-row operation span remains.
    assert len(trimmed) == 40
    assert trimmed["onground"].iloc[0] in (True, np.True_)  # first kept row is the taxi start


def test_trim_keeps_inflow_queue_wait_whole():
    """A long stationary wait BETWEEN taxi and takeoff sits inside the active span and
    must be kept at any length (it is bracketed by movement)."""
    rows = []
    t = 1_500_000_000
    # taxi-out moving (active)
    for i in range(5):
        rows.append(dict(flight_id="q", icao24="aaa111", time=t, lat=RWY_LAT + i * 0.0008,
                         lon=RWY_LON, baroaltitude=0.0, velocity=8.0, vertrate=0.0,
                         heading=90.0, onground=True, flight_phase="on_ground")); t += GRID
    # queue wait — stationary, on-ground, 30 rows (inside the span)
    wlat = RWY_LAT + 5 * 0.0008
    for _ in range(30):
        rows.append(dict(flight_id="q", icao24="aaa111", time=t, lat=wlat, lon=RWY_LON,
                         baroaltitude=0.0, velocity=0.0, vertrate=0.0, heading=90.0,
                         onground=True, flight_phase="on_ground")); t += GRID
    # takeoff + climb (airborne)
    for i in range(20):
        rows.append(dict(flight_id="q", icao24="aaa111", time=t, lat=wlat + i * 0.0008,
                         lon=RWY_LON, baroaltitude=float(i * 150), velocity=60.0 + i,
                         vertrate=6.0, heading=90.0, onground=i < 4,
                         flight_phase="takeoff" if i < 4 else "climb")); t += GRID
    df = _frame(rows)
    df = pp.compute_speed(pp.segment(pp.sort_and_dedupe(df)))
    trimmed = pp.trim_idle(df)
    # The 30-row stationary queue wait is interior to the active span → fully kept.
    # Only the very first taxi row is trimmed (undefined speed at the segment start),
    # so 54 of 55 survive; the operationally-meaningful invariant is the wait.
    assert (trimmed["velocity"] == 0.0).sum() == 30   # the whole queue wait survived
    assert (~trimmed["onground"]).sum() == 16         # all airborne rows survived (i>=4 of 20)
    assert len(trimmed) == 54


def test_pure_ground_segment_is_dropped():
    rows = [dict(flight_id="g", icao24="aaa111", time=1_500_000_000 + i * GRID,
                 lat=RWY_LAT, lon=RWY_LON, baroaltitude=0.0, velocity=0.0, vertrate=0.0,
                 heading=0.0, onground=True, flight_phase="on_ground") for i in range(40)]
    df = _frame(rows)
    df = pp.compute_speed(pp.segment(pp.sort_and_dedupe(df)))
    trimmed = pp.trim_idle(df)
    assert len(trimmed) == 0


def test_idle_before_first_movement_is_trimmed():
    rows = _engaging_flight(n_air=40, lead_park=10)  # 10 parked rows before pushback
    df = _frame(rows)
    df = pp.compute_speed(pp.segment(pp.sort_and_dedupe(df)))
    trimmed = pp.trim_idle(df)
    assert len(trimmed) == 40  # all 10 leading-idle rows trimmed


# ── step 8: resampling + interpolation (CRITICAL) ────────────────────────────

def _segmented_two_blocks():
    """Two already-segmented contiguous blocks, manually keyed — for resample tests."""
    rows = []
    for sid, base_v, t0 in [("A#1", 100.0, 1_500_000_000), ("B#1", 200.0, 1_500_900_000)]:
        for i in range(12):
            rows.append(dict(segment_id=sid, flight_id=sid.split("#")[0], icao24="aaa111",
                             time=t0 + i * GRID, lat=RWY_LAT + i * 0.0008, lon=RWY_LON,
                             baroaltitude=float(i * 100), velocity=base_v, vertrate=1.0,
                             heading=10.0, onground=False, flight_phase="climb", squawk=0,
                             operation="unknown"))
    df = pd.DataFrame(rows)
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])
    return df


def test_interpolation_never_crosses_boundary():  # ★ CRITICAL
    df = _segmented_two_blocks()
    # NaN the FIRST velocity of block B. If interpolation bled across the A|B boundary
    # it would blend toward A's 100; within-segment it must resolve to B's own 200.
    bmask = df["segment_id"] == "B#1"
    first_b = df.index[bmask][0]
    df.loc[first_b, "velocity"] = np.nan
    out = pp.resample_to_grid(df)
    b0 = out[(out["segment_id"] == "B#1")].sort_values("time").iloc[0]
    assert b0["velocity"] == pytest.approx(200.0)            # NOT a 100↔200 blend
    assert bool(b0["velocity_missing"]) is True             # and it is flagged imputed
    # A is untouched at its boundary.
    a_last = out[out["segment_id"] == "A#1"].sort_values("time").iloc[-1]
    assert a_last["velocity"] == pytest.approx(100.0)


def test_interpolation_fills_midsegment_and_sets_mask_and_preserves_grid():
    df = _segmented_two_blocks()
    df = df[df["segment_id"] == "A#1"].copy()
    n_in = len(df)
    df.loc[df.index[5], "baroaltitude"] = np.nan  # mid-segment hole
    out = pp.resample_to_grid(df)
    assert len(out) == n_in                                  # contiguous → no rows inserted
    assert np.isfinite(out["baroaltitude"]).all()           # filled
    assert bool(out.sort_values("time").iloc[5]["baroaltitude_missing"]) is True
    t = out.sort_values("time")["time"].to_numpy()
    assert (np.diff(t) == GRID).all()                       # uniform grid


def test_resample_inserts_rows_for_subgap_and_keeps_uniform_grid():
    df = _segmented_two_blocks()
    df = df[df["segment_id"] == "A#1"].copy().sort_values("time").reset_index(drop=True)
    # drop two interior rows to create a 30 s internal hole (< 3 min, so not split)
    df = df.drop(index=[5, 6]).reset_index(drop=True)
    out = pp.resample_to_grid(df)
    t = out.sort_values("time")["time"].to_numpy()
    assert (np.diff(t) == GRID).all()                       # holes filled to a strict grid
    assert out["baroaltitude_missing"].sum() == 2           # exactly the two inserted rows


# ── step 9: heading wrap ─────────────────────────────────────────────────────

def test_heading_interpolation_is_wrap_safe():
    rows = []
    t0 = 1_500_000_000
    headings = [359.0, np.nan, 1.0]  # the 359→1 wrap with a hole between
    for i, h in enumerate(headings):
        rows.append(dict(segment_id="h#1", flight_id="h", icao24="aaa111", time=t0 + i * GRID,
                         lat=RWY_LAT + i * 0.0008, lon=RWY_LON, baroaltitude=1000.0,
                         velocity=80.0, vertrate=1.0, heading=h, onground=False,
                         flight_phase="climb", squawk=0, operation="unknown"))
    df = pd.DataFrame(rows)
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])
    out = pp.resample_to_grid(df).sort_values("time").reset_index(drop=True)
    filled = out.loc[1, "heading"]
    # wrap-safe: the gap fills near 0/360, NOT ~180 (the linear-degree midpoint).
    near_zero = min(filled % 360, 360 - (filled % 360))
    assert near_zero < 5.0
    assert np.hypot(out.loc[1, "hdg_sin"], out.loc[1, "hdg_cos"]) == pytest.approx(1.0)


# ── step 12: min-length ──────────────────────────────────────────────────────

@pytest.mark.parametrize("n,kept", [(29, False), (30, True), (31, True)])
def test_filter_min_length_boundary(n, kept):
    rows = [dict(segment_id="s#1", time=1_500_000_000 + i * GRID) for i in range(n)]
    df = pd.DataFrame(rows)
    out = pp.filter_min_length(df)
    assert (len(out) > 0) is kept


# ── step 13: scaler (CRITICAL) ───────────────────────────────────────────────

def test_make_scaler_returns_unfitted():  # ★ CRITICAL
    scaler = pp.make_scaler()
    assert not hasattr(scaler, "mean_")          # never fitted
    with pytest.raises(NotFittedError):
        scaler.transform([[1.0, 2.0, 3.0, 4.0, 5.0]])


def test_scaler_fit_on_train_slice_does_not_see_val_rows():
    """Fitting on a TRAIN slice must derive stats from train only — the val rows are
    invisible (the Phase-6 firewall in microcosm)."""
    train = pd.DataFrame({c: np.arange(10, dtype=float) for c in pp.SCALER_FEATURES})
    val = pd.DataFrame({c: np.arange(1000, 1010, dtype=float) for c in pp.SCALER_FEATURES})
    scaler = pp.make_scaler()
    scaler.fit(train[pp.SCALER_FEATURES])
    assert scaler.mean_[0] == pytest.approx(train[pp.SCALER_FEATURES[0]].mean())
    # val's huge values had no effect on the fitted mean.
    assert scaler.mean_[0] < 100


# ── step 14: sequence builder contract ───────────────────────────────────────

def test_to_sequences_pad_and_mask_polarity():
    clean, _ = pp.preprocess(_frame(_engaging_flight(n_air=60)))
    scaler = pp.make_scaler()
    scaler.fit(clean[pp.SCALER_FEATURES])  # synthetic fit — allowed in a test
    n_real = int(clean.groupby("segment_id").size().iloc[0])
    T = n_real + 15
    X, mask, info = pp.to_sequences(clean, T=T, scaler=scaler)
    assert X.shape == (1, T, len(pp.AE_FEATURES))
    assert mask.shape == (1, T)
    assert mask[0, :n_real].sum() == n_real           # 1.0 = real timestep
    assert mask[0, n_real:].sum() == 0.0              # 0.0 = padding
    assert (X[0, n_real:] == 0.0).all()               # pad_value after scaling


def test_to_sequences_truncates_and_flags():
    clean, _ = pp.preprocess(_frame(_engaging_flight(n_air=60)))
    scaler = pp.make_scaler(); scaler.fit(clean[pp.SCALER_FEATURES])
    X, mask, info = pp.to_sequences(clean, T=10, scaler=scaler)
    assert X.shape[1] == 10
    assert bool(info["was_truncated"].iloc[0]) is True
    assert mask[0].sum() == 10.0


# ── orchestration: determinism + meta contract ───────────────────────────────

def test_preprocess_is_deterministic():
    raw = _frame(_engaging_flight(n_air=60))
    c1, m1 = pp.preprocess(raw)
    c2, m2 = pp.preprocess(raw)
    pd.testing.assert_frame_equal(c1, c2)
    pd.testing.assert_frame_equal(m1, m2)


def test_preprocess_meta_preserves_split_columns():
    raw = _frame(_engaging_flight(n_air=60))
    clean, meta = pp.preprocess(raw)
    assert list(meta.columns) == pp.META_COLUMNS
    assert len(meta) == len(clean)
    assert not np.isnan(clean[pp.AE_FEATURES].to_numpy(dtype=float)).any()


def test_preprocess_tags_emergency_squawk():
    raw = _frame(_engaging_flight(n_air=60))
    raw.loc[20, "squawk"] = 7700  # emergency
    clean, meta = pp.preprocess(raw)
    assert meta["is_emergency"].all()  # the whole segment is tagged


# ── real-parquet smoke (skips if cycle-3 data absent) ────────────────────────

def _find_cycle3_parquet():
    pattern = str(REPO_ROOT / "data" / "raw" / "opensky_states" / "lemd_*.parquet")
    files = sorted(glob.glob(pattern))
    return files[0] if files else None


@pytest.mark.skipif(_find_cycle3_parquet() is None, reason="cycle-3 parquet not present (gitignored)")
def test_real_parquet_smoke():
    raw = pd.read_parquet(_find_cycle3_parquet())
    clean, meta = pp.preprocess(raw)
    assert len(clean) > 0
    assert len(meta) == len(clean)
    assert not np.isnan(clean[pp.AE_FEATURES].to_numpy(dtype=float)).any()
    # every segment is on a strict 10 s grid
    for _, seg in clean.groupby("segment_id"):
        t = seg.sort_values("time")["time"].to_numpy()
        if len(t) > 1:
            assert (np.diff(t) == GRID).all()
    assert (clean.groupby("segment_id").size() >= pp.T_MIN).all()
