"""Observed-row normalization and evidence-quality checks."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sadar.approach.configuration import DEFAULT_CONFIG, ApproachConfig
from sadar.trajectory.geo import haversine_dist


def observed(frame: pd.DataFrame, channel: str) -> pd.Series:
    mask_name = f"{channel}_missing"
    valid = (
        frame[channel].notna()
        if channel in frame
        else pd.Series(False, index=frame.index)
    )
    if mask_name in frame:
        valid &= ~frame[mask_name].fillna(True).astype(bool)
    return valid


def canonical_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Return unique, ordered position observations without invented grid rows."""
    required = {"time", "lat", "lon"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"approach frame missing required columns: {sorted(missing)}")
    ordered = frame.copy()
    ordered["time"] = pd.to_numeric(ordered["time"], errors="coerce")
    ordered = ordered.loc[
        ordered["time"].notna()
        & observed(ordered, "lat")
        & observed(ordered, "lon")
    ].copy()
    ordered["time"] = ordered["time"].astype("int64")
    return (
        ordered.sort_values("time")
        .drop_duplicates("time", keep="first")
        .reset_index(drop=True)
    )


def track_values(
    frame: pd.DataFrame,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> tuple[np.ndarray, np.ndarray]:
    track = frame.get(
        "heading", pd.Series(np.nan, index=frame.index)
    ).to_numpy(dtype="float64")
    valid = observed(frame, "heading").to_numpy(copy=True)
    if "velocity" in frame:
        speed = frame["velocity"].to_numpy(dtype="float64")
        valid &= observed(frame, "velocity").to_numpy() & (
            speed >= config.minimum_track_speed_mps
        )
    return track, valid


def quality(frame: pd.DataFrame, config: ApproachConfig) -> dict[str, Any]:
    time = frame["time"].to_numpy(dtype="float64")
    gaps = np.diff(time) if len(time) > 1 else np.array([], dtype="float64")
    max_gap = float(gaps.max()) if len(gaps) else 0.0
    max_ground = 0.0
    max_vertical = 0.0
    if len(frame) > 1:
        usable = gaps > 0
        distance = haversine_dist(
            frame["lat"].to_numpy()[:-1],
            frame["lon"].to_numpy()[:-1],
            frame["lat"].to_numpy()[1:],
            frame["lon"].to_numpy()[1:],
        )
        if usable.any():
            max_ground = float(
                np.nanmax(np.asarray(distance)[usable] / gaps[usable])
            )
        altitude_valid = observed(frame, "baroaltitude").to_numpy()
        pair_valid = usable & altitude_valid[:-1] & altitude_valid[1:]
        if pair_valid.any():
            altitude = frame["baroaltitude"].to_numpy(dtype="float64")
            max_vertical = float(
                np.nanmax(np.abs(np.diff(altitude)[pair_valid] / gaps[pair_valid]))
            )
    fatal_reasons = []
    channel_advisories: dict[str, list[str]] = {}
    if len(frame) < config.minimum_samples:
        fatal_reasons.append("insufficient_observations")
    if len(frame) and time[-1] - time[0] < config.minimum_duration_s:
        fatal_reasons.append("insufficient_duration")
    if max_gap > config.maximum_gap_s:
        fatal_reasons.append("approach_coverage_gap")
    if max_ground > config.maximum_implied_ground_speed_mps:
        fatal_reasons.append("position_rate_conflict")
    if max_vertical > config.maximum_implied_vertical_rate_mps:
        channel_advisories["barometric_altitude"] = ["altitude_rate_conflict"]
    return {
        "observed_samples": int(len(frame)),
        "maximum_gap_s": round(max_gap, 1),
        "maximum_implied_ground_speed_mps": round(max_ground, 1),
        "maximum_implied_vertical_rate_mps": round(max_vertical, 1),
        "fatal_reasons": fatal_reasons,
        "channel_advisories": channel_advisories,
    }


def persistent_spans(
    mask: np.ndarray,
    time: np.ndarray,
    minimum_rows: int,
    minimum_duration_s: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(mask.tolist() + [False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            end = index - 1
            if (
                index - start >= minimum_rows
                and time[end] - time[start] >= minimum_duration_s
            ):
                spans.append((start, end))
            start = None
    return spans
