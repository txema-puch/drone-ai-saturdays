"""Stable operation segmentation shared by uploads and historical research."""

from __future__ import annotations

import pandas as pd

GAP_THRESHOLD_SEC = 1800


def add_flight_id(
    frame: pd.DataFrame,
    gap_threshold_sec: int = GAP_THRESHOLD_SEC,
) -> pd.DataFrame:
    """Segment observations by aircraft and temporal gap."""
    if frame.empty:
        result = frame.copy()
        result["flight_id"] = pd.Series(dtype=str)
        return result
    result = frame.sort_values(["icao24", "time"]).reset_index(drop=True)
    gap = result.groupby("icao24", sort=False)["time"].diff()
    new_flight = gap.isna() | (gap > gap_threshold_sec)
    result["_flight_num"] = new_flight.groupby(result["icao24"]).cumsum()
    first_seen = result.groupby(["icao24", "_flight_num"])["time"].transform("min")
    result["flight_id"] = (
        result["icao24"].astype(str) + "_" + first_seen.astype(int).astype(str)
    )
    return result.drop(columns=["_flight_num"])
