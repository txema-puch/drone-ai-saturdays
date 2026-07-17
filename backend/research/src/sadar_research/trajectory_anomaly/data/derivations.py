"""Per-row + per-trajectory derivations shared by the OpenSky ingestion paths.

Leaf module: numpy/pandas + `sadar_research.trajectory_anomaly.data.geometry` only. No credentials, no Trino,
no Supabase (see `backend/research/src/sadar_research/trajectory_anomaly/data/geometry.py` docstring for why that matters).

This is the canonical home for `calculate_flight_phase`, `apply_filter_b`, and
`apply_derivations`. Both the public-dataset downloader and upload evaluator use
these implementations. Flight segmentation is owned by `sadar.trajectory.segmentation`.

The derivation math is consumed by the Phase 2 audit (notebook 05) as a
consistency check — any change here silently changes that check. See
`docs/research/trajectory-anomaly/data-workflow.md > Why opensky.py is dual-use`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sadar.trajectory.segmentation import GAP_THRESHOLD_SEC, add_flight_id
from sadar_research.trajectory_anomaly.data.geometry import (
    MAX_RADIUS_M,
    distance_to_closest_runway,
)

# ── Constants (mirrored from download_opensky_states.py) ──────────────────────

# Filter B thresholds — empirically validated on 2019-10-07 full-day probe.
FILTER_B_MAX_MIN_DIST_M = 10_000
FILTER_B_MAX_MIN_ALT_M = 3_000

OUTPUT_COLUMNS = [
    "time", "icao24", "lat", "lon",
    "baroaltitude", "geoaltitude",
    "velocity", "heading", "vertrate",
    "callsign", "onground", "squawk", "alert", "spi", "lastcontact",
    "flight_id", "operation", "time_utc",
    "velocity_kmh", "dist_to_runway_m", "flight_phase",
]


def calculate_flight_phase(track: pd.DataFrame) -> pd.Series:
    """Derive a coarse flight phase per row from altitude + vertical rate.

    Requires columns: onground, baroaltitude, vertrate, dist_to_runway_m.
    """
    conditions = [
        track["onground"].fillna(False).astype(bool),
        track["baroaltitude"].notna() & (track["baroaltitude"] < 50),
        track["vertrate"].notna() & (track["vertrate"] > 3) & track["baroaltitude"].notna() & (track["baroaltitude"] < 3000),
        track["vertrate"].notna() & (track["vertrate"] > 1),
        track["vertrate"].notna() & (track["vertrate"] <= -1) & track["baroaltitude"].notna() & (track["baroaltitude"] < 3000) & track["dist_to_runway_m"].notna() & (track["dist_to_runway_m"] < 20000),
        track["vertrate"].notna() & (track["vertrate"] < -1),
    ]
    values = ["on_ground", "on_ground", "takeoff", "climb", "approach", "descent"]
    return np.select(conditions, values, default="cruise")


def apply_filter_b(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only trajectories where min_dist < 10 km AND min_alt < 3 km.

    Run after segmentation (flight_id present) and after distance/altitude
    columns are available. Removes cruise overflights transiting the bbox.
    """
    if df.empty:
        return df
    stats = df.groupby("flight_id").agg(
        min_dist=("dist_to_runway_m", "min"),
        min_alt=("baroaltitude", "min"),
    )
    keep_ids = stats[
        (stats["min_dist"] < FILTER_B_MAX_MIN_DIST_M)
        & (stats["min_alt"] < FILTER_B_MAX_MIN_ALT_M)
    ].index
    return df.loc[df["flight_id"].isin(keep_ids)].copy()


def apply_derivations(
    df: pd.DataFrame,
    *,
    diagnostics: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Apply the per-row derivations + Filter B (trajectory level).

    Mirrors `OpenSkyService.build_master_table`'s derivation block.
    """
    if diagnostics is not None:
        diagnostics["input_rows"] = int(len(df))
        diagnostics["outside_radius_rows"] = 0
        diagnostics["filter_b_rows"] = 0
        diagnostics["filter_b_trajectories"] = 0
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = df.copy()
    # Defensive coercion — OpenSky CSV sometimes has malformed cells that keep
    # whole columns as object dtype, which breaks ufuncs downstream.
    for col in ("velocity", "baroaltitude", "geoaltitude", "vertrate", "heading", "time"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["callsign"] = df["callsign"].astype(str).str.strip()
    df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["velocity_kmh"] = df["velocity"] * 3.6
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])

    # Exact 200 km haversine filter (the bbox was a cheap pre-cut).
    in_radius = df["dist_to_runway_m"] <= MAX_RADIUS_M
    if diagnostics is not None:
        diagnostics["outside_radius_rows"] = int((~in_radius).sum())
    df = df.loc[in_radius].copy()
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = add_flight_id(df)

    before_filter_b = df
    df = apply_filter_b(df)
    if diagnostics is not None:
        kept_ids = set(df["flight_id"].astype(str))
        rejected = ~before_filter_b["flight_id"].astype(str).isin(kept_ids)
        diagnostics["filter_b_rows"] = int(rejected.sum())
        diagnostics["filter_b_trajectories"] = int(
            before_filter_b.loc[rejected, "flight_id"].nunique()
        )
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["operation"] = "unknown"
    df["flight_phase"] = calculate_flight_phase(df)
    df["time"] = pd.to_numeric(df["time"], errors="coerce").fillna(0).astype(int)
    df["flight_id"] = df["flight_id"].astype(str)

    for c in OUTPUT_COLUMNS:
        if c not in df.columns:
            df[c] = None

    if diagnostics is not None:
        diagnostics["output_rows"] = int(len(df))
        diagnostics["output_trajectories"] = int(df["flight_id"].nunique())
    return df[OUTPUT_COLUMNS]
