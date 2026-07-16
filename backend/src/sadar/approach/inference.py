"""Runway-direction and parallel-runway inference from observed geometry."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from sadar.approach.configuration import DEFAULT_CONFIG, ApproachConfig
from sadar.approach.geometry import (
    GeometryCatalog,
    RunwayThreshold,
    circular_difference_deg,
    load_lemd_geometry,
    runway_relative,
)
from sadar.approach.observations import canonical_observations, observed, track_values


def _runway_score(
    frame: pd.DataFrame,
    runway: RunwayThreshold,
    config: ApproachConfig,
) -> tuple[float, int, dict[str, float]]:
    relative = runway_relative(frame["lat"], frame["lon"], runway)
    in_gate = (
        (relative.along_track_m >= 0)
        & (relative.along_track_m <= config.gate_along_m * 1.25)
        & (np.abs(relative.cross_track_m) <= config.gate_cross_m)
    )
    if "baroaltitude" in frame:
        altitude_valid = observed(frame, "baroaltitude").to_numpy()
        altitude = frame["baroaltitude"].to_numpy(dtype="float64")
        in_gate &= ~altitude_valid | (
            altitude <= runway.elevation_m + config.gate_max_height_proxy_m
        )
    indices = np.flatnonzero(in_gate)
    if len(indices) < config.inference_minimum_rows:
        return math.inf, len(indices), {}
    time = frame["time"].to_numpy(dtype="int64")
    window_start = time[indices[-1]] - config.inference_window_s
    indices = indices[time[indices] >= window_start]
    if time[indices[-1]] - time[indices[0]] < config.inference_minimum_duration_s:
        return math.inf, len(indices), {}
    along = relative.along_track_m[indices]
    cross = np.abs(relative.cross_track_m[indices])
    corridor = np.maximum(250.0, along * 0.12)
    lateral = float(np.median(cross / corridor))
    track, valid_track = track_values(frame, config)
    usable_track = indices[valid_track[indices]]
    track_error = (
        float(
            np.median(
                circular_difference_deg(
                    track[usable_track], runway.true_bearing_deg
                )
            )
        )
        if len(usable_track) >= 3
        else 90.0
    )
    terminal = float(np.min(relative.threshold_distance_m))
    score = (
        lateral
        + track_error / 30.0
        + min(terminal / config.terminal_distance_m, 2.0)
    )
    return score, len(indices), {
        "lateral_component": round(lateral, 4),
        "track_error_deg": round(track_error, 2),
        "minimum_threshold_distance_m": round(terminal, 1),
    }


def infer_runway(
    frame: pd.DataFrame,
    *,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    observations = canonical_observations(frame)
    geometry = geometry or load_lemd_geometry()
    candidates = []
    for runway in geometry.landing_thresholds:
        score, rows, evidence = _runway_score(observations, runway, config)
        candidates.append(
            {
                "runway": runway.designator,
                "direction": runway.direction,
                "score": score,
                "supporting_rows": rows,
                "evidence": evidence,
            }
        )
    candidates.sort(key=lambda item: item["score"])
    finite = [item for item in candidates if math.isfinite(item["score"])]
    if not finite:
        return {
            "runway": None,
            "direction": None,
            "specificity": "unknown",
            "confidence": 0.0,
            "score_margin": 0.0,
            "candidates": candidates,
            "reason": "no_supported_runway_candidate",
        }
    winner = finite[0]
    other_direction = next(
        (item for item in finite if item["direction"] != winner["direction"]),
        None,
    )
    direction_margin = (
        other_direction["score"] - winner["score"]
        if other_direction
        else math.inf
    )
    if (
        winner["score"] > config.direction_score_maximum
        or direction_margin < config.direction_margin_minimum
    ):
        return {
            "runway": None,
            "direction": None,
            "specificity": "unknown",
            "confidence": 0.0,
            "score_margin": round(float(direction_margin), 4),
            "candidates": candidates,
            "reason": "runway_direction_ambiguous",
        }
    parallel = next(
        (
            item
            for item in finite
            if item["direction"] == winner["direction"] and item is not winner
        ),
        None,
    )
    exact_margin = parallel["score"] - winner["score"] if parallel else math.inf
    exact = exact_margin >= config.exact_margin_minimum
    confidence = min(1.0, max(0.0, direction_margin / 2.0)) * (
        1.0 / (1.0 + winner["score"])
    )
    return {
        "runway": winner["runway"] if exact else f"{winner['direction']}_pair",
        "geometry_runway": winner["runway"],
        "direction": winner["direction"],
        "specificity": "exact" if exact else "direction",
        "confidence": round(float(confidence), 4),
        "score_margin": round(
            float(exact_margin if exact else direction_margin), 4
        ),
        "candidates": candidates,
        "reason": None,
    }
