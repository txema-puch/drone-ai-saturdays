"""Deployment-only segment diagnostics and behavioral-assessment guardrails.

These annotations never modify model inputs, scores, thresholds, or evaluation artifacts.
They expose when the frozen score is not reliable evidence of behavioral conformance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.core.geo import haversine_dist

MIN_OBSERVED_STEPS = 30
MAX_IMPLIED_VERTICAL_RATE_MPS = 50.0
MAX_IMPLIED_GROUND_SPEED_MPS = 400.0


def assess_segment(
    segment: pd.DataFrame,
    *,
    valid_steps: int,
    n_steps: int,
    truncated: bool,
    terminal_op: bool,
) -> dict:
    """Return factual continuity diagnostics plus an explicit abstention state."""
    ordered = segment.sort_values("time").copy()
    window_steps = min(int(n_steps), len(ordered))
    observed_fraction = valid_steps / max(window_steps, 1)

    max_altitude_jump_m = 0.0
    max_implied_vertical_rate_mps = 0.0
    max_implied_ground_speed_mps = 0.0
    if len(ordered) > 1:
        time = ordered["time"].to_numpy(dtype="float64")
        dt = np.diff(time)
        usable = dt > 0
        if usable.any():
            altitude = ordered["baroaltitude"].to_numpy(dtype="float64")
            altitude_jump = np.abs(np.diff(altitude))
            max_altitude_jump_m = float(np.nanmax(altitude_jump[usable]))
            max_implied_vertical_rate_mps = float(
                np.nanmax(altitude_jump[usable] / dt[usable])
            )
            lat = ordered["lat"].to_numpy(dtype="float64")
            lon = ordered["lon"].to_numpy(dtype="float64")
            distance = haversine_dist(lat[:-1], lon[:-1], lat[1:], lon[1:])
            max_implied_ground_speed_mps = float(np.nanmax(distance[usable] / dt[usable]))

    flags = []
    if valid_steps < MIN_OBSERVED_STEPS:
        flags.append("insufficient_observations")
    if max_implied_vertical_rate_mps > MAX_IMPLIED_VERTICAL_RATE_MPS:
        flags.append("altitude_rate_conflict")
    if max_implied_ground_speed_mps > MAX_IMPLIED_GROUND_SPEED_MPS:
        flags.append("position_rate_conflict")
    if truncated and not terminal_op:
        flags.append("terminal_phase_not_scored")
    elif not terminal_op:
        flags.append("nonterminal_window")

    if "insufficient_observations" in flags:
        assessment_state = "insufficient_data"
        review_lane = "data_quality"
    elif any(flag.endswith("_rate_conflict") for flag in flags):
        assessment_state = "data_quality_conflict"
        review_lane = "data_quality"
    elif not terminal_op:
        assessment_state = "coverage_limited"
        review_lane = "coverage"
    else:
        assessment_state = "reviewable"
        review_lane = "behavioral"

    return {
        "assessment_state": assessment_state,
        "behavioral_verdict": (
            "reviewable" if assessment_state == "reviewable" else "not_assessable"
        ),
        "review_lane": review_lane,
        "data_quality_flags": flags,
        "valid_steps": int(valid_steps),
        "observed_fraction": round(float(observed_fraction), 4),
        "max_altitude_jump_m": round(max_altitude_jump_m, 1),
        "max_implied_vertical_rate_mps": round(max_implied_vertical_rate_mps, 1),
        "max_implied_ground_speed_mps": round(max_implied_ground_speed_mps, 1),
    }


def assessment_copy(assessment: dict) -> str:
    state = assessment["assessment_state"]
    if state == "insufficient_data":
        return "Insufficient observed timesteps; behavioral conformance is not assessable."
    if state == "data_quality_conflict":
        conflicts = []
        if "altitude_rate_conflict" in assessment["data_quality_flags"]:
            conflicts.append(
                f"implied vertical rate {assessment['max_implied_vertical_rate_mps']:.1f} m/s"
            )
        if "position_rate_conflict" in assessment["data_quality_flags"]:
            conflicts.append(
                f"implied ground speed {assessment['max_implied_ground_speed_mps']:.1f} m/s"
            )
        return (
            "Physically inconsistent telemetry transition detected ("
            + ", ".join(conflicts)
            + "); cause is unassigned and behavioral conformance is not assessable."
        )
    if state == "coverage_limited":
        if "terminal_phase_not_scored" in assessment["data_quality_flags"]:
            return "The terminal phase falls outside the scored window; behavioral conformance is not assessable."
        return "The scored window lacks a low-and-close LEMD terminal phase; behavioral conformance is not assessable."
    return "No deployment data-quality conflict detected; model evidence is available for analyst review."
