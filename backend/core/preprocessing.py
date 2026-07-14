"""Phase 3 preprocessing pipeline — the *unfitted* definition (D-010 + amendments).

This module turns the locked Phase-3 design (notebook `07_phase3_preprocess.ipynb`,
Findings A–E, codex-reviewed twice) into code. It produces a clean, uniform-grid,
imputed dataframe whose **model unit is a SEGMENT** (a trajectory cut at every gap
> 3 min). It does **not** split and does **not** `.fit()` anything — the train/val/test
split, the scaler fit, and the sequence length `T` are computed on TRAIN only in
Phase 6 (guardrail #5, the fit/transform firewall). `make_scaler()` returns an
*unfitted* scaler; `to_sequences()` is a pure definition that takes `T` + a fitted
scaler as arguments and is never called with real values in Phase 3.

Pipeline order is load-bearing (segment/derive before anything crosses a gap; split
before interpolate). See `preprocess()` for the orchestration and
`backend/docs/ml/03-preprocess.md` for the prose spec.

Evidence base (measured numbers the notebook Part 3 validates against):
  - Filter D keeps 18,928 / 19,057 flights (99.3%).
  - Gap re-segmentation at > 3 min produces ~2,598 extra splits.
  - Idle-trim removes ~5.9% of rows; drops 68 pure-ground trajectories.
  - The `n_imputed_impossible > 0` cohort sizes to ~500–800 trajectories.

Leaf imports only (`backend.core.geo`, numpy/pandas/sklearn) — never `crud.opensky`
or `settings`, so this runs with no `.env` present (see `geo.py` docstring).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from backend.core.geo import distance_to_closest_runway, haversine_dist

# ── Pipeline constants (domain values, not data-fit parameters) ───────────────

GRID_S = 10                  # uniform resample grid (10 s — the feed cadence, Finding C)
GAP_SPLIT_S = 180            # re-segment at any inter-obs gap > 3 min (Finding C)
MOVE_THRESH_MS = 2.5         # active-movement speed threshold (Finding D; below taxi 5–15 m/s)
T_MIN = 30                   # drop segments shorter than this after resample + trim
EMERGENCY_SQUAWKS = (7500, 7600, 7700)

# Stage-1 physical bounds (D-010 Part 2). Out-of-bounds → set NaN (imputed, not trained on)
# AND counted as `n_imputed_impossible` (the D-008 Layer-1 sanity cohort).
MAX_VELOCITY_MS = 400.0
MAX_VERTRATE_MS = 50.0
MAX_BAROALT_M = 16_000.0
MIN_BAROALT_M = -100.0
# velocity == 0 while airborne is a missing-data PLACEHOLDER, not a kinematic
# impossibility → set NaN but count as `n_imputed_missing` (Insight 7b). Folding it
# into the impossible cohort would balloon it far past the ~500–800 target.
PLACEHOLDER_ALT_M = 1_000.0

# Filter D — the LEMD-operation gate (D-010 Part 1). A flight passes if ANY row
# satisfies ANY criterion; a post-split segment is dropped if NO row engages.
FILTER_D_APPROACH_DIST_M = 10_000
FILTER_D_ONGROUND_DIST_M = 5_000
FILTER_D_TAKEOFF_DIST_M = 5_000
FILTER_D_TAKEOFF_ALT_M = 2_000

# Feature contracts. THIS is the single source of truth the synthetic-injection
# bench + the per-feature RE attribution + the Layer-3 baseline all bind to
# dynamically (by name). Add/reorder here only, never scatter feature lists across
# notebooks — a silent change breaks all three (eval-prep reconciliation note).
CONTINUOUS_FEATURES = ["lat", "lon", "baroaltitude", "velocity", "vertrate"]  # linear-interp (measured primitives)
MASKED_FEATURES = ["lat", "lon", "baroaltitude", "velocity", "vertrate", "heading"]  # get *_missing flags
# `dist_to_runway_m` promoted to a scaled AE feature in Phase 5 (issue #25): the
# nonlinear min-over-8-runways zone signal. It is DERIVED (= distance_to_closest_runway
# (lat, lon)), so it is recompute-not-perturb for injections (see core/features.py
# apply_segment_derivations) and is not interpolated/masked (its missingness rides on
# lat/lon's masks).
SCALER_FEATURES = ["lat", "lon", "baroaltitude", "velocity", "vertrate", "dist_to_runway_m"]  # StandardScaler input (6)
AE_FEATURES = ["lat", "lon", "baroaltitude", "velocity", "vertrate", "dist_to_runway_m",
               "hdg_sin", "hdg_cos", "onground"]                              # the AE input vector (9)
META_COLUMNS = ["icao24", "time", "flight_id", "segment_id", "squawk",
                "is_emergency", "n_imputed_impossible", "n_imputed_missing"]


# ── Step 1–2: sort + dedupe ───────────────────────────────────────────────────

def sort_and_dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by (flight_id, time); drop exact-duplicate timestamps (dt == 0).

    Dedupe before any speed/interpolation so a zero dt never divides (codex #3).
    """
    df = df.copy()
    # `time` is epoch seconds (the downloader writes int). Coerce defensively so the
    # 10 s grid snap in resample_to_grid can never silently truncate a float time.
    df["time"] = pd.to_numeric(df["time"], errors="coerce").round().astype("int64")
    df = df.sort_values(["flight_id", "time"]).reset_index(drop=True)
    dup = df.duplicated(subset=["flight_id", "time"], keep="first")
    return df.loc[~dup].reset_index(drop=True)


# ── Step 3: gap re-segmentation ───────────────────────────────────────────────

def segment(df: pd.DataFrame, max_gap_s: int = GAP_SPLIT_S) -> pd.DataFrame:
    """Assign `segment_id` — a new segment starts at any gap > max_gap_s.

    Split BEFORE interpolation so a multi-minute temporal hole is never bridged by
    a bogus linear fill (Finding C; codex). `segment_id` is `{flight_id}#{k}`.
    """
    df = df.copy()
    gap = df.groupby("flight_id", sort=False)["time"].diff()
    new_seg = gap.isna() | (gap > max_gap_s)
    seg_num = new_seg.groupby(df["flight_id"]).cumsum().astype(int)
    df["segment_id"] = df["flight_id"].astype(str) + "#" + seg_num.astype(str)
    return df


# ── Step 4: Filter D (LEMD-operation gate) + drop non-engaging segments ───────

def _engaging_row_mask(df: pd.DataFrame) -> pd.Series:
    """Per-row: does this observation engage LEMD by any Filter-D criterion?"""
    phase = df["flight_phase"].astype("string")
    onground = df["onground"].fillna(False).astype(bool)
    dist = df["dist_to_runway_m"]
    alt = df["baroaltitude"]
    c1 = (phase == "approach") & (dist < FILTER_D_APPROACH_DIST_M)
    c2 = onground & (dist < FILTER_D_ONGROUND_DIST_M)
    c3 = (phase == "takeoff") & (dist < FILTER_D_TAKEOFF_DIST_M) & (alt < FILTER_D_TAKEOFF_ALT_M)
    return (c1 | c2 | c3).fillna(False)


def filter_d(df: pd.DataFrame) -> pd.DataFrame:
    """Keep flights with ≥1 engaging row (reproduces D-010's 99.3% gate), then drop
    post-split segments that have zero engaging rows (distant cruise fragments of an
    otherwise-engaging flight). Hybrid order per eng-review open-Q1.
    """
    eng = _engaging_row_mask(df)
    keep_flights = eng.groupby(df["flight_id"]).transform("any")
    df = df.loc[keep_flights].copy()
    if df.empty:
        return df
    eng = eng.loc[df.index]
    keep_segs = eng.groupby(df["segment_id"]).transform("any")
    return df.loc[keep_segs].reset_index(drop=True)


# ── Step 5: movement speed (displacement / dt) ────────────────────────────────

def compute_speed(df: pd.DataFrame) -> pd.DataFrame:
    """Per-segment movement speed = haversine displacement / dt (m/s).

    This is a *did-the-position-change* detector for the idle-trim, NOT a velocity
    estimate — disp/dt collapses on the ground where `velocity` is needed (Finding E).
    Position is never null, so it is the right signal for movement (Finding D).
    """
    df = df.copy()
    g = df.groupby("segment_id", sort=False)
    dt = g["time"].diff()
    step_m = haversine_dist(g["lat"].shift(), g["lon"].shift(), df["lat"], df["lon"])
    with np.errstate(divide="ignore", invalid="ignore"):
        df["_speed"] = step_m / dt
    return df


# ── Step 6: on-ground idle-trim ───────────────────────────────────────────────

def trim_idle(df: pd.DataFrame, move_thresh_ms: float = MOVE_THRESH_MS) -> pd.DataFrame:
    """Keep the active operational span (first→last moving/airborne row) per segment;
    trim leading/trailing parked-idle; drop segments with no airborne portion.

    Movement = airborne OR speed > move_thresh_ms. In-queue waits sit *inside* the
    span (bracketed by taxi + takeoff) so a long pre-takeoff wait is kept at any
    length; a stationary stretch before the first movement (parked-then-pushback) is
    leading-idle and trimmed (Finding D edge case). Pure-ground segments → dropped.
    """
    onground = df["onground"].fillna(False).astype(bool)
    active = (~onground) | (df["_speed"] > move_thresh_ms)

    keep_idx = []
    for _, idx in df.groupby("segment_id", sort=False).groups.items():
        idx = np.asarray(idx)
        a = active.loc[idx].to_numpy()
        has_air = bool((~onground.loc[idx]).any())
        if not has_air or not a.any():
            continue  # pure-ground / never-active → drop whole segment
        first = int(a.argmax())
        last = len(a) - 1 - int(a[::-1].argmax())
        keep_idx.extend(idx[first:last + 1].tolist())

    return df.loc[keep_idx].reset_index(drop=True)


# ── Step 7: Stage-1 physical-bounds flag (impossible → NaN) ───────────────────

def flag_kinematic_impossibility(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Set kinematically-impossible values to NaN (so they are imputed, not trained
    on — codex #4) and the airborne `velocity==0` placeholder to NaN.

    Returns `(df, impossible_cells)` where `impossible_cells` is a boolean frame over
    MASKED_FEATURES marking ONLY the hard-bound violations (not the placeholder) —
    the basis for `n_imputed_impossible`.
    """
    df = df.copy()
    imp = pd.DataFrame(False, index=df.index, columns=MASKED_FEATURES)

    imp["velocity"] = df["velocity"].notna() & (df["velocity"].abs() > MAX_VELOCITY_MS)
    imp["vertrate"] = df["vertrate"].notna() & (df["vertrate"].abs() > MAX_VERTRATE_MS)
    imp["baroaltitude"] = df["baroaltitude"].notna() & (
        (df["baroaltitude"] > MAX_BAROALT_M) | (df["baroaltitude"] < MIN_BAROALT_M)
    )

    # Missing-data placeholder: velocity 0 while airborne. Nulled, but counted as
    # *missing*, not *impossible* (kept out of the D-008 Layer-1 cohort).
    placeholder = (
        df["velocity"].notna() & (df["velocity"] == 0)
        & df["baroaltitude"].notna() & (df["baroaltitude"] > PLACEHOLDER_ALT_M)
    )

    for col in ("velocity", "vertrate", "baroaltitude"):
        df.loc[imp[col], col] = np.nan
    df.loc[placeholder, "velocity"] = np.nan
    return df, imp


# ── Step 11: counters (measured post-flag, pre-interpolate — codex #5) ────────

def compute_counters(df: pd.DataFrame, impossible_cells: pd.DataFrame) -> pd.DataFrame:
    """Per-segment `n_imputed_impossible` (hard-bound violations) and
    `n_imputed_missing` (routine nulls + placeholder), measured on observed rows
    BEFORE resampling/interpolation inserts grid rows.

    A single merged counter would tag ~69% of the corpus (almost every flight
    touches the ground); the split keeps the impossible cohort small + diagnostic
    (Findings A/E, D-008).
    """
    na = df[MASKED_FEATURES].isna()
    routine_missing = na & ~impossible_cells
    per_row = pd.DataFrame({
        "segment_id": df["segment_id"].to_numpy(),
        "n_imputed_impossible": impossible_cells.sum(axis=1).to_numpy(),
        "n_imputed_missing": routine_missing.sum(axis=1).to_numpy(),
    })
    return per_row.groupby("segment_id")[["n_imputed_impossible", "n_imputed_missing"]].sum()


# ── Step 8–9: resample to a strict 10 s grid + interpolate within segment ─────

def _resample_segment(seg: pd.DataFrame) -> pd.DataFrame:
    """Reindex one segment to a uniform 10 s grid, then impute within the segment.

    Continuous features linear-interpolated; heading via sin/cos components
    (wrap-safe); categorical forward/back-filled; `dist_to_runway_m` re-derived from
    interpolated position. A `*_missing` flag is set on every imputed/inserted value
    (codex #2 — makes the uniform grid actually true). Never crosses a segment
    boundary (we resample per segment).
    """
    seg = seg.sort_values("time")
    ident = {c: seg[c].iloc[0] for c in ("flight_id", "icao24", "segment_id", "operation")
             if c in seg.columns}

    t = seg["time"].to_numpy(dtype="int64")
    t0, t1 = int(t[0]), int(t[-1])
    if t1 == t0:
        grid = np.array([t0], dtype="int64")
    else:
        snapped = t0 + np.round((t - t0) / GRID_S).astype("int64") * GRID_S
        seg = seg.assign(time=snapped).drop_duplicates("time", keep="first")
        t0, t1 = int(seg["time"].iloc[0]), int(seg["time"].iloc[-1])
        grid = np.arange(t0, t1 + GRID_S, GRID_S, dtype="int64")

    seg = seg.set_index("time").reindex(grid)
    seg.index.name = "time"

    # *_missing masks: True where the value was absent or the row was inserted.
    for f in MASKED_FEATURES:
        seg[f + "_missing"] = seg[f].isna().to_numpy()

    # Heading: interpolate sin/cos components (handles the 0/360 wrap), renormalise.
    hs = np.sin(np.radians(seg["heading"])).interpolate("linear", limit_direction="both")
    hc = np.cos(np.radians(seg["heading"])).interpolate("linear", limit_direction="both")
    norm = np.hypot(hs, hc)
    seg["hdg_sin"] = np.where(norm > 0, hs / norm, 0.0)
    seg["hdg_cos"] = np.where(norm > 0, hc / norm, 1.0)
    # The AE consumes hdg_sin/hdg_cos; `heading` is reconstructed for reference only.
    # An all-NaN-heading segment yields heading==0 everywhere — consumers (Phase 5)
    # must key off `heading_missing`, not the value.
    seg["heading"] = np.degrees(np.arctan2(seg["hdg_sin"], seg["hdg_cos"])) % 360.0

    # Continuous: linear interpolation within the segment (no cross-segment fill).
    for f in CONTINUOUS_FEATURES:
        seg[f] = seg[f].interpolate("linear", limit_direction="both")
    seg[CONTINUOUS_FEATURES] = seg[CONTINUOUS_FEATURES].fillna(0.0)  # fully-NaN-in-segment safety

    # Categorical / bookkeeping: forward/back-fill.
    seg["onground"] = seg["onground"].ffill().bfill()
    if seg["onground"].isna().all():
        seg["onground"] = False
    seg["onground"] = seg["onground"].astype(bool)
    seg["flight_phase"] = seg["flight_phase"].ffill().bfill()
    if "squawk" in seg.columns:
        seg["squawk"] = seg["squawk"].ffill().bfill()

    for c, v in ident.items():
        seg[c] = v

    # Re-derive dist_to_runway from the interpolated position.
    seg["dist_to_runway_m"] = distance_to_closest_runway(seg["lat"], seg["lon"]).to_numpy()

    return seg.reset_index()


def resample_to_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Apply `_resample_segment` to every segment and re-concatenate."""
    parts = [_resample_segment(seg) for _, seg in df.groupby("segment_id", sort=False)]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["segment_id", "time"]).reset_index(drop=True)


# ── Step 10: hold-aside tag ───────────────────────────────────────────────────

def _segment_is_emergency(df: pd.DataFrame) -> pd.Series:
    """Per-segment `is_emergency` = any row squawks 7500/7600/7700.

    Held aside from TRAIN at the Phase-6 split (D-009), not dropped here — Phase 3's
    job is only to TAG. Computed on observed rows before resampling.
    """
    sq = pd.to_numeric(df["squawk"], errors="coerce")
    row_emerg = sq.isin(EMERGENCY_SQUAWKS)
    return row_emerg.groupby(df["segment_id"]).any()


# ── Step 12: minimum-length filter ────────────────────────────────────────────

def filter_min_length(df: pd.DataFrame, t_min: int = T_MIN) -> pd.DataFrame:
    """Drop segments shorter than `t_min` rows (after resample + trim)."""
    sizes = df.groupby("segment_id")["time"].transform("size")
    return df.loc[sizes >= t_min].reset_index(drop=True)


# ── Step 13: unfitted scaler ──────────────────────────────────────────────────

def make_scaler() -> StandardScaler:
    """Return an UNFITTED StandardScaler for SCALER_FEATURES.

    Phase 3 must never `.fit()` — the scaler is fit on TRAIN only in Phase 6
    (guardrail #5). sin/cos (already [-1,1]) and `onground` (binary) are passthrough.
    """
    return StandardScaler()


# ── Step 14: sequence builder (definition only — fit/run in Phase 6) ──────────

def to_sequences(
    clean_df: pd.DataFrame,
    T: int,
    scaler: StandardScaler,
    *,
    pad_value: float = 0.0,
):
    """PHASE-6 FUNCTION — defined here, never called with real values in Phase 3.

    Build fixed-shape `(N, T, len(AE_FEATURES))` tensors from per-segment frames.
    Contract (codex #9):
      - `scaler` is a StandardScaler ALREADY FITTED on TRAIN; SCALER_FEATURES are
        transformed, sin/cos + onground pass through unscaled.
      - Sequences longer than `T` are truncated to the first `T` rows; `was_truncated`
        is flagged (the long legitimate tail — holds, go-arounds — must not silently clip).
      - Padding is applied AFTER scaling with `pad_value` (0.0 ≈ the train mean for
        standardised columns → neutral).
      - `mask` polarity: 1.0 = real timestep, 0.0 = padding (multiply into the loss so
        the AE is not rewarded for reconstructing padding; same masking as imputed rows).

    Returns `(X[N,T,F] float32, mask[N,T] float32, info)` where `info` is a per-sequence
    DataFrame with `segment_id` + `was_truncated`.
    """
    seg_ids, rows, masks, truncated = [], [], [], []
    n_feat = len(AE_FEATURES)
    for sid, seg in clean_df.groupby("segment_id", sort=False):
        seg = seg.sort_values("time")
        feats = seg[AE_FEATURES].to_numpy(dtype="float64").copy()
        sc_idx = [AE_FEATURES.index(c) for c in SCALER_FEATURES]
        feats[:, sc_idx] = scaler.transform(seg[SCALER_FEATURES])
        n = len(feats)
        was_trunc = n > T
        feats = feats[:T]
        valid = len(feats)
        if valid < T:
            pad = np.full((T - valid, n_feat), pad_value, dtype="float64")
            feats = np.vstack([feats, pad])
        m = np.zeros(T, dtype="float32")
        m[:valid] = 1.0
        seg_ids.append(sid)
        rows.append(feats.astype("float32"))
        masks.append(m)
        truncated.append(was_trunc)

    X = np.stack(rows) if rows else np.empty((0, T, n_feat), dtype="float32")
    mask = np.stack(masks) if masks else np.empty((0, T), dtype="float32")
    info = pd.DataFrame({"segment_id": seg_ids, "was_truncated": truncated})
    return X, mask, info


def to_sequences_loss_mask(clean_df: pd.DataFrame, T: int):
    """PHASE-6 helper — the per-window `(N, T)` LOSS mask: `1.0` = real, observed timestep;
    `0.0` = padding OR imputed.

    The AE reconstruction loss (and the per-segment reconstruction-error score) multiplies
    by this so the model is rewarded for neither padding NOR imputed rows (guardrail: a row
    interpolated by Phase 3 carries no ground truth to reconstruct). A row is "imputed" iff
    ANY of its `MASKED_FEATURES` `*_missing` flags is set.

    Iterates exactly like `to_sequences` (group `sort=False`, sort by `time`, first `T`,
    pad) so window `i` here aligns with window `i` of the `X`/`mask` it returns. Torch-free
    (lives beside `to_sequences`) so the injection bench and the LSTM-AE both consume it
    without importing a model framework. Synthetic-injection timesteps set `*_missing = 0`
    upstream, so they read as real here and DO count toward the loss.
    """
    miss_cols = [f + "_missing" for f in MASKED_FEATURES]
    masks = []
    for _, seg in clean_df.groupby("segment_id", sort=False):
        seg = seg.sort_values("time")
        imputed = seg[miss_cols].to_numpy(dtype=bool).any(axis=1)
        valid = (~imputed).astype("float32")[:T]
        m = np.zeros(T, dtype="float32")
        m[: len(valid)] = valid
        masks.append(m)
    return np.stack(masks) if masks else np.empty((0, T), dtype="float32")


# ── Step 15: orchestration ────────────────────────────────────────────────────

def preprocess(
    raw_df: pd.DataFrame,
    *,
    diagnostics: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the unfitted Phase-3 pipeline (steps 1–12) on a raw cycle-3 frame.

    Returns `(clean_df, meta)`:
      - `clean_df`: uniform-grid, imputed, segment-keyed model frame — AE features
        (`AE_FEATURES`), the `*_missing` masks, `segment_id`, `time`, `flight_phase`,
        `dist_to_runway_m` (retained for Phase 5).
      - `meta`: row-aligned split/attribution columns (`META_COLUMNS`) — preserves
        `icao24`/`flight_id`/`segment_id` for the Phase-6 group+temporal split,
        `squawk`/`is_emergency`/`n_imputed_*` for the held-aside cohorts (codex #7).

    Never splits, never fits. The scaler fit, `T`, and the split are Phase 6.
    """
    if diagnostics is not None:
        diagnostics["input_rows"] = int(len(raw_df))
    df = sort_and_dedupe(raw_df)
    if diagnostics is not None:
        diagnostics["deduplicated_rows"] = int(len(raw_df) - len(df))
    df = segment(df)
    before_filter_d = set(df["segment_id"].astype(str))
    df = filter_d(df)
    if diagnostics is not None:
        after_filter_d = set(df["segment_id"].astype(str))
        diagnostics["filter_d_segments"] = len(before_filter_d - after_filter_d)
    if df.empty:
        return _empty_clean(), _empty_meta()

    df = compute_speed(df)
    before_trim = set(df["segment_id"].astype(str))
    df = trim_idle(df)
    if diagnostics is not None:
        after_trim = set(df["segment_id"].astype(str))
        diagnostics["idle_segments"] = len(before_trim - after_trim)
    if df.empty:
        return _empty_clean(), _empty_meta()

    df, impossible_cells = flag_kinematic_impossibility(df)
    counters = compute_counters(df, impossible_cells)          # per-segment, pre-interpolate
    if diagnostics is not None:
        diagnostics["impossible_observations"] = int(counters["n_imputed_impossible"].sum())
        diagnostics["missing_observations"] = int(counters["n_imputed_missing"].sum())
    emergency = _segment_is_emergency(df)                       # per-segment, pre-resample

    df = df.drop(columns=[c for c in ("_speed",) if c in df.columns])
    df = resample_to_grid(df)
    before_length = set(df["segment_id"].astype(str))
    df = filter_min_length(df)
    if diagnostics is not None:
        after_length = set(df["segment_id"].astype(str))
        diagnostics["short_segments"] = len(before_length - after_length)
    if df.empty:
        return _empty_clean(), _empty_meta()

    # Attach per-segment attributes.
    df["is_emergency"] = df["segment_id"].map(emergency).fillna(False).astype(bool)
    df["n_imputed_impossible"] = df["segment_id"].map(counters["n_imputed_impossible"]).fillna(0).astype(int)
    df["n_imputed_missing"] = df["segment_id"].map(counters["n_imputed_missing"]).fillna(0).astype(int)

    meta = df[META_COLUMNS].copy()
    clean_cols = (
        ["segment_id", "flight_id", "time"]
        + AE_FEATURES                                   # dist_to_runway_m now lives here
        + [f + "_missing" for f in MASKED_FEATURES]
        + ["heading", "flight_phase"]                   # dist promoted into AE_FEATURES (Phase 5)
    )
    # dedupe preserving order — guards against a feature appearing in both AE_FEATURES
    # and the trailing reference columns (e.g. dist_to_runway_m after the P5 promotion).
    clean_cols = list(dict.fromkeys(c for c in clean_cols if c in df.columns))
    clean_df = df[clean_cols].copy()

    _assert_clean(clean_df)
    if diagnostics is not None:
        diagnostics["output_rows"] = int(len(clean_df))
        diagnostics["output_segments"] = int(clean_df["segment_id"].nunique())
    return clean_df, meta


def _assert_clean(clean_df: pd.DataFrame) -> None:
    """Invariants the pipeline guarantees (cheap, catches silent regressions)."""
    feats = clean_df[AE_FEATURES].to_numpy(dtype="float64")
    assert not np.isnan(feats).any(), "AE feature matrix still has NaN after imputation"
    # Uniform 10 s grid within every segment.
    for _, seg in clean_df.groupby("segment_id", sort=False):
        t = seg["time"].to_numpy()
        if len(t) > 1:
            d = np.diff(t)
            assert (d == GRID_S).all(), "segment is not on a strict 10 s grid"


def _empty_clean() -> pd.DataFrame:
    cols = list(dict.fromkeys(
        ["segment_id", "flight_id", "time"] + AE_FEATURES
        + [f + "_missing" for f in MASKED_FEATURES]
        + ["heading", "flight_phase"]))
    return pd.DataFrame(columns=cols)


def _empty_meta() -> pd.DataFrame:
    return pd.DataFrame(columns=META_COLUMNS)
