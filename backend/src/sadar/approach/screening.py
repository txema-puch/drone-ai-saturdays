"""Rules-first, observed-row LEMD approach assessment prototype.

This module deliberately does not import the historical LSTM preprocessing or serving
stack. Criterion evidence is computed from observed values only; model-era interpolated
rows are filtered through their ``*_missing`` masks.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Literal

import numpy as np
import pandas as pd

from sadar.approach.reference import lookup_reference, validate_reference
from sadar.approach.configuration import (
    ASSESSMENT_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    ENGINE_VERSION,
    RECONSTRUCTION_POLICY,
    RECONSTRUCTION_POLICY_VERSION,
    ApproachConfig,
    digest,
)
from sadar.approach.geometry import (
    GeometryCatalog,
    RunwayThreshold,
    circular_difference_deg,
    load_lemd_geometry,
    runway_relative,
)
from sadar.approach.observations import (
    canonical_observations,
    observed,
    persistent_spans,
    quality as assess_quality,
    track_values,
)
from sadar.approach.inference import infer_runway
from sadar.approach.reconstruction import extract_approach_attempts


def _criterion(
    name: str,
    frame: pd.DataFrame,
    values: np.ndarray,
    limits: np.ndarray,
    valid: np.ndarray,
    failure: np.ndarray,
    relative,
    *,
    unit: str,
    config: ApproachConfig,
    severity: Literal["low", "medium", "high"] = "high",
) -> dict[str, Any]:
    spans = persistent_spans(
        valid & failure,
        frame["time"].to_numpy(dtype="int64"),
        config.persistence_rows,
        config.persistence_s,
    )
    evidence = []
    for start, end in spans:
        local = np.arange(start, end + 1)
        excess = np.abs(values[local] - limits[local])
        worst = int(local[int(np.nanargmax(excess))])
        evidence.append({
            "start_index": start,
            "end_index": end,
            "start_time": int(frame.iloc[start]["time"]),
            "end_time": int(frame.iloc[end]["time"]),
            "worst_index": worst,
            "worst_time": int(frame.iloc[worst]["time"]),
            "value": round(float(values[worst]), 3),
            "limit": round(float(limits[worst]), 3),
            "unit": unit,
            "along_track_m": round(float(relative.along_track_m[worst]), 1),
        })
    observed = int(valid.sum())
    return {
        "name": name,
        "status": "review_required" if evidence else "within_limit" if observed else "not_observed",
        "severity": severity,
        "observed_samples": observed,
        "evidence": evidence,
    }


def _vertical_bias(frame: pd.DataFrame, runway: RunwayThreshold, relative) -> tuple[float | None, str]:
    baro_valid = observed(frame, "baroaltitude").to_numpy()
    onground = frame.get("onground", pd.Series(False, index=frame.index)).fillna(False).astype(bool).to_numpy()
    near = relative.threshold_distance_m <= 1_500.0
    support = baro_valid & near & onground
    source = "observed_onground"
    if support.sum() < 2:
        support = baro_valid & (relative.threshold_distance_m <= 750.0)
        source = "threshold_adjacent_proxy"
    if support.sum() < 2:
        return None, "unavailable"
    bias = float(np.nanmedian(frame["baroaltitude"].to_numpy(dtype="float64")[support]) - runway.elevation_m)
    if abs(bias) > 500.0:
        return None, "inconsistent"
    return bias, source


def _attempt_outcome(
    frame: pd.DataFrame,
    relative,
    *,
    altitude_usable: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """Classify observed attempt outcome without treating a go-around as failure."""
    onground = frame.get("onground", pd.Series(False, index=frame.index)).fillna(False).astype(bool).to_numpy()
    near_ground = onground & (relative.threshold_distance_m <= 2_000.0)
    if near_ground.any():
        index = int(np.flatnonzero(near_ground)[0])
        altitude_valid = observed(frame, "baroaltitude").to_numpy() & altitude_usable
        later_airborne = np.flatnonzero(
            altitude_valid[index + 1:] & ~onground[index + 1:]
        ) + index + 1
        if len(later_airborne) >= 3:
            altitude = frame["baroaltitude"].to_numpy(dtype="float64")
            climb = float(np.nanmax(altitude[later_airborne]) - altitude[index])
            airborne_span = int(
                frame.iloc[later_airborne[-1]]["time"]
                - frame.iloc[later_airborne[0]]["time"]
            )
            if climb >= 150.0 and airborne_span >= 20:
                return "touch_and_go", [{
                    "name": "touch_and_go",
                    "index": index,
                    "time": int(frame.iloc[index]["time"]),
                    "observed_climb_after_contact_m": round(climb, 1),
                }]
        return "landing_observed", [{
            "name": "landing_observed",
            "index": index,
            "time": int(frame.iloc[index]["time"]),
        }]

    altitude_valid = observed(frame, "baroaltitude").to_numpy() & altitude_usable
    near = np.flatnonzero((relative.threshold_distance_m <= 5_000.0) & altitude_valid)
    if len(near):
        altitude = frame["baroaltitude"].to_numpy(dtype="float64")
        low_index = int(near[np.nanargmin(altitude[near])])
        before = altitude_valid[:low_index] & ~onground[:low_index]
        after = altitude_valid[low_index + 1:] & ~onground[low_index + 1:]
        descent = (
            float(np.nanmax(altitude[:low_index][before]) - altitude[low_index])
            if before.any() else 0.0
        )
        climb = (
            float(np.nanmax(altitude[low_index + 1:][after]) - altitude[low_index])
            if after.any() else 0.0
        )
        if descent >= 150.0 and climb >= 150.0:
            return "go_around", [{
                "name": "go_around",
                "index": low_index,
                "time": int(frame.iloc[low_index]["time"]),
                "descent_into_low_point_m": round(descent, 1),
                "climb_after_low_point_m": round(climb, 1),
            }]
    return "closest_approach", []


def assess_approach(
    frame: pd.DataFrame,
    *,
    operation_id: str | None = None,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
    reference: dict[str, Any] | None = None,
    speed_class: str = "unknown",
    altitude_bias_override_m: float | None = None,
    altitude_bias_source: str | None = None,
) -> dict[str, Any]:
    """Assess the last supported LEMD approach attempt in one candidate record."""
    geometry = geometry or load_lemd_geometry()
    if reference is not None:
        validate_reference(reference)
    observations = canonical_observations(frame)
    inference = infer_runway(observations, geometry=geometry, config=config)
    base = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "operation_id": operation_id,
        "geometry": {
            "schema_version": geometry.schema_version,
            "effective_date": geometry.effective_date,
            "artifact_sha256": geometry.artifact_sha256,
            "source_sha256": geometry.source["sha256"],
        },
        "config": asdict(config),
        "provenance": {
            "config_sha256": digest(asdict(config)),
            "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
            "reconstruction_policy_sha256": digest(RECONSTRUCTION_POLICY),
        },
        "runway_inference": inference,
        "reference": {
            "schema_version": reference["schema_version"],
            "artifact_sha256": reference["artifact_sha256"],
            "speed_class": speed_class,
        } if reference is not None else None,
    }
    if not inference.get("geometry_runway"):
        return {**base, "status": "not_assessable", "reasons": [inference["reason"]], "criteria": [], "maneuvers": []}
    runway = geometry.thresholds[inference["geometry_runway"]]
    relative_all = runway_relative(observations["lat"], observations["lon"], runway)
    gate = (
        (relative_all.along_track_m >= -500.0)
        & (relative_all.along_track_m <= config.gate_along_m)
        & (np.abs(relative_all.cross_track_m) <= config.gate_cross_m)
    )
    indices = np.flatnonzero(gate)
    if not len(indices):
        return {**base, "status": "not_assessable", "reasons": ["no_approach_attempt"], "criteria": [], "maneuvers": []}
    extension_limit = int(observations.iloc[indices[-1]]["time"]) + config.outcome_extension_s
    extended_end = int(
        np.searchsorted(observations["time"].to_numpy(), extension_limit, side="right") - 1
    )
    full_attempt = observations.iloc[indices[0]:extended_end + 1].reset_index(drop=True)
    full_relative = runway_relative(full_attempt["lat"], full_attempt["lon"], runway)
    initial_quality = assess_quality(full_attempt, config)
    initial_altitude_usable = (
        "barometric_altitude" not in initial_quality["channel_advisories"]
    )
    outcome, maneuvers = _attempt_outcome(
        full_attempt, full_relative, altitude_usable=initial_altitude_usable,
    )
    criterion_end_index = (
        int(maneuvers[0]["index"])
        if maneuvers and outcome in {"go_around", "touch_and_go"}
        else len(full_attempt) - 1
    )
    attempt = full_attempt.iloc[:criterion_end_index + 1].reset_index(drop=True)
    relative = runway_relative(attempt["lat"], attempt["lon"], runway)
    quality = assess_quality(attempt, config)
    altitude_usable = "barometric_altitude" not in quality["channel_advisories"]
    terminal_position = relative.threshold_distance_m <= config.terminal_distance_m
    terminal_altitude_observed = observed(attempt, "baroaltitude").to_numpy()
    terminal_height_ok = (
        ~terminal_altitude_observed
        | (not altitude_usable)
        | (
            attempt.get("baroaltitude", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
            <= runway.elevation_m + config.terminal_max_height_proxy_m
        )
    )
    terminal = bool(
        np.any(terminal_position & terminal_height_ok)
        or outcome in {"landing_observed", "go_around", "touch_and_go"}
    )
    if not terminal:
        quality["fatal_reasons"].append("terminal_gate_not_reached")

    if altitude_bias_override_m is not None:
        if not math.isfinite(altitude_bias_override_m) or abs(altitude_bias_override_m) > 500:
            raise ValueError("altitude bias override must be finite and within 500 m")
        if not altitude_bias_source:
            raise ValueError("altitude bias override requires an explicit source")
    if not altitude_usable:
        bias, bias_source = None, "rate_conflict"
    elif altitude_bias_override_m is not None:
        bias, bias_source = float(altitude_bias_override_m), altitude_bias_source
    else:
        bias, bias_source = _vertical_bias(attempt, runway, relative)
    baro = attempt.get("baroaltitude", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    height = baro - runway.elevation_m - (bias or 0.0)
    track, track_valid = track_values(attempt, config)

    lateral_limit = np.maximum(config.lateral_floor_m, relative.along_track_m * config.lateral_slope)
    lateral_valid = (relative.along_track_m >= 0) & (relative.along_track_m <= config.lateral_gate_m)
    lateral = _criterion(
        "lateral_path_proxy", attempt, np.abs(relative.cross_track_m), lateral_limit,
        lateral_valid, np.abs(relative.cross_track_m) > lateral_limit, relative,
        unit="m", config=config,
    )

    nominal_height = np.tan(math.radians(config.path_angle_deg)) * np.maximum(relative.along_track_m, 0)
    path_valid = (
        (bias is not None) & observed(attempt, "baroaltitude").to_numpy()
        & (relative.along_track_m >= 0) & (relative.along_track_m <= config.path_gate_m)
    )
    path_delta = height - nominal_height
    path_limit = np.where(path_delta >= 0, config.path_high_tolerance_m, -config.path_low_tolerance_m)
    path = _criterion(
        "barometric_path_proxy", attempt, path_delta, path_limit, path_valid,
        (path_delta > config.path_high_tolerance_m) | (path_delta < -config.path_low_tolerance_m),
        relative, unit="m from 3deg proxy", config=config,
    )
    path["altitude_bias_source"] = bias_source

    reference_rows = [
        lookup_reference(
            reference,
            direction=inference["direction"],
            speed_class=speed_class,
            along_track_m=float(along),
        ) if reference is not None and along >= 0 else None
        for along in relative.along_track_m
    ]
    if base["reference"] is not None:
        base["reference"].update({
            "requested_speed_class": speed_class,
            "effective_speed_classes": sorted({
                row["speed_class"] for row in reference_rows if row is not None
            }),
            "fallbacks": sorted({
                row["fallback"] for row in reference_rows if row is not None
            }),
        })
    vertical = attempt.get("vertrate", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    empirical_vertical = np.array([
        row["vertical_rate_lower_mps"] if row else np.nan for row in reference_rows
    ])
    if reference is not None:
        descent_valid = observed(attempt, "vertrate").to_numpy() & np.isfinite(empirical_vertical)
        descent_limit = empirical_vertical
    else:
        descent_valid = observed(attempt, "vertrate").to_numpy() & (bias is not None) & (height <= config.descent_gate_height_m)
        descent_limit = np.full(len(attempt), config.descent_rate_limit_mps)
    descent = _criterion(
        "observed_descent_rate", attempt, vertical, descent_limit, descent_valid,
        vertical < descent_limit, relative, unit="m/s", config=config,
    )
    descent["reference_source"] = "empirical_train_envelope" if reference is not None else "provisional_fixed_limit"

    correction = circular_difference_deg(track, runway.true_bearing_deg)
    correction_limit = np.full(len(attempt), config.correction_limit_deg)
    correction_valid = track_valid & (relative.along_track_m >= 0) & (relative.along_track_m <= config.correction_gate_m)
    late_correction = _criterion(
        "late_track_correction", attempt, correction, correction_limit, correction_valid,
        correction > config.correction_limit_deg, relative, unit="deg", config=config,
    )
    observed_speed = attempt.get("velocity", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    speed_lower = np.array([row["speed_lower_mps"] if row else np.nan for row in reference_rows])
    speed_upper = np.array([row["speed_upper_mps"] if row else np.nan for row in reference_rows])
    speed_valid = observed(attempt, "velocity").to_numpy() & np.isfinite(speed_lower) & np.isfinite(speed_upper)
    selected_speed_limit = np.where(observed_speed < speed_lower, speed_lower, speed_upper)
    speed = _criterion(
        "observed_ground_speed_envelope", attempt, observed_speed, selected_speed_limit,
        speed_valid, (observed_speed < speed_lower) | (observed_speed > speed_upper),
        relative, unit="m/s", config=config,
    )
    if reference is None:
        speed["reason"] = "empirical_reference_not_fitted"
    elif not speed_valid.any():
        speed["reason"] = "no_supported_reference_cell"
    criteria = [lateral, path, descent, speed, late_correction]
    failed = [item for item in criteria if item["status"] == "review_required" and item["severity"] == "high"]
    missing_required = [item for item in criteria if item["status"] == "not_observed"]
    if quality["fatal_reasons"]:
        status = "not_assessable"
    elif failed:
        status = "review_required"
    elif missing_required:
        status = "partial_observation"
    else:
        status = "criteria_observed"
    return {
        **base,
        "status": status,
        "reasons": quality["fatal_reasons"],
        "attempt": {
            "start_time": int(attempt["time"].iloc[0]),
            "end_time": int(full_attempt["time"].iloc[-1]),
            "criterion_end_time": int(attempt["time"].iloc[-1]),
            "outcome": (
                "final_gate_observed" if terminal and outcome == "closest_approach"
                else outcome if terminal else "incomplete"
            ),
            "observed_samples": len(full_attempt),
            "criterion_observed_samples": len(attempt),
            "minimum_threshold_distance_m": round(
                float(np.min(full_relative.threshold_distance_m)), 1
            ),
        },
        "quality": quality,
        "altitude_reference": {"bias_m": round(bias, 1) if bias is not None else None, "source": bias_source},
        "criteria": criteria,
        "failed_criteria": [item["name"] for item in failed],
        "maneuvers": maneuvers,
    }


def assess_operation(
    frame: pd.DataFrame,
    *,
    operation_id: str | None = None,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
    reference: dict[str, Any] | None = None,
    speed_class: str = "unknown",
) -> dict[str, Any]:
    """Assess every distinct approach attempt observed in a candidate record."""
    geometry = geometry or load_lemd_geometry()
    attempts = extract_approach_attempts(frame, geometry=geometry, config=config)
    assessments = [
        assess_approach(
            attempt,
            operation_id=f"{operation_id or 'operation'}:attempt-{index + 1}",
            geometry=geometry,
            config=config,
            reference=reference,
            speed_class=speed_class,
        )
        for index, attempt in enumerate(attempts)
    ]
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "operation_id": operation_id,
        "attempt_count": len(assessments),
        "attempts": assessments,
    }
