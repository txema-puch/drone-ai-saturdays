"""Per-row + per-trajectory derivations shared by the OpenSky ingestion paths.

Leaf module: numpy/pandas + `backend.core.geo` only. No credentials, no Trino,
no Supabase (see `backend/core/geo.py` docstring for why that matters).

Canonical home (refactor A1, 2026-06-01) for:
  - `calculate_flight_phase`  — was in `backend/crud/opensky.py`
  - `add_flight_id`, `apply_filter_b`, `apply_derivations` — were in
    `backend/scripts/download_opensky_states.py`

`crud/opensky.py` re-exports `calculate_flight_phase`. The download script keeps
its own copies of `apply_derivations`/`apply_filter_b`/`add_flight_id` until it
has test coverage to migrate against (deferred per the eng-review A1 note); this
module is the single source of truth they will converge on.

The derivation math is consumed by the Phase 2 audit (notebook 05) as a
consistency check — any change here silently changes that check. See
`backend/docs/workflow/data-pipeline.md > Why opensky.py is dual-use`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.core.geo import MAX_RADIUS_M, distance_to_closest_runway

# ── Constants (mirrored from download_opensky_states.py) ──────────────────────

GAP_THRESHOLD_SEC = 1800  # 30 min → new flight segment (ingestion-time flight_id)

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


def add_flight_id(df: pd.DataFrame, gap_threshold_sec: int = GAP_THRESHOLD_SEC) -> pd.DataFrame:
    """Derive flight_id by segmenting same icao24 with a temporal gap threshold.

    Matches the Trino-path convention: `{icao24}_{firstseen_unix}`.
    """
    if df.empty:
        df = df.copy()
        df["flight_id"] = pd.Series(dtype=str)
        return df
    df = df.sort_values(["icao24", "time"]).reset_index(drop=True)
    gap = df.groupby("icao24", sort=False)["time"].diff()
    new_flight = gap.isna() | (gap > gap_threshold_sec)
    df["_flight_num"] = new_flight.groupby(df["icao24"]).cumsum()
    firstseen = df.groupby(["icao24", "_flight_num"])["time"].transform("min")
    df["flight_id"] = df["icao24"].astype(str) + "_" + firstseen.astype(int).astype(str)
    return df.drop(columns=["_flight_num"])


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


def apply_derivations(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the per-row derivations + Filter B (trajectory level).

    Mirrors `OpenSkyService.build_master_table`'s derivation block.
    """
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
    df = df.loc[df["dist_to_runway_m"] <= MAX_RADIUS_M].copy()
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = add_flight_id(df)

    df = apply_filter_b(df)
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["operation"] = "unknown"
    df["flight_phase"] = calculate_flight_phase(df)
    df["time"] = pd.to_numeric(df["time"], errors="coerce").fillna(0).astype(int)
    df["flight_id"] = df["flight_id"].astype(str)

    for c in OUTPUT_COLUMNS:
        if c not in df.columns:
            df[c] = None

    return df[OUTPUT_COLUMNS]
