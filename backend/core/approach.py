"""Rules-first, observed-row LEMD approach assessment prototype.

This module deliberately does not import the historical LSTM preprocessing or serving
stack. Criterion evidence is computed from observed values only; model-era interpolated
rows are filtered through their ``*_missing`` masks.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from backend.core.approach_reference import lookup_reference, validate_reference
from backend.core.approach_geometry import (
    GeometryCatalog,
    RunwayThreshold,
    circular_difference_deg,
    load_lemd_geometry,
    runway_relative,
)
from backend.core.geo import haversine_dist


ASSESSMENT_SCHEMA_VERSION = "approach_assessment_v1"
ENGINE_VERSION = "prototype_v1"
RECONSTRUCTION_POLICY_VERSION = "observed_attempts_v1"
RECONSTRUCTION_POLICY = {
    "position_evidence": "observed_rows_only",
    "time_order": "sort_drop_duplicate_epoch_second",
    "parallel_candidates": "temporal_cluster_then_infer",
    "reentry_split_s": 180,
}


@dataclass(frozen=True)
class ApproachConfig:
    gate_along_m: float = 20_000.0
    gate_cross_m: float = 6_000.0
    terminal_distance_m: float = 6_000.0
    terminal_max_height_proxy_m: float = 800.0
    gate_max_height_proxy_m: float = 3_000.0
    minimum_samples: int = 20
    minimum_duration_s: int = 90
    maximum_gap_s: int = 60
    maximum_implied_ground_speed_mps: float = 400.0
    maximum_implied_vertical_rate_mps: float = 50.0
    minimum_track_speed_mps: float = 30.0
    inference_minimum_rows: int = 8
    inference_minimum_duration_s: int = 60
    inference_window_s: int = 600
    direction_score_maximum: float = 4.0
    direction_margin_minimum: float = 0.35
    exact_margin_minimum: float = 0.20
    persistence_rows: int = 3
    persistence_s: int = 20
    attempt_reentry_gap_s: int = 180
    outcome_extension_s: int = 180
    lateral_gate_m: float = 6_000.0
    lateral_floor_m: float = 150.0
    lateral_slope: float = 0.10
    path_gate_m: float = 10_000.0
    path_angle_deg: float = 3.0
    path_low_tolerance_m: float = 120.0
    path_high_tolerance_m: float = 200.0
    descent_gate_height_m: float = 1_000.0
    descent_rate_limit_mps: float = -7.6
    correction_gate_m: float = 3_000.0
    correction_limit_deg: float = 15.0


DEFAULT_CONFIG = ApproachConfig()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _observed(frame: pd.DataFrame, channel: str) -> pd.Series:
    mask_name = f"{channel}_missing"
    valid = frame[channel].notna() if channel in frame else pd.Series(False, index=frame.index)
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
        ordered["time"].notna() & _observed(ordered, "lat") & _observed(ordered, "lon")
    ].copy()
    ordered["time"] = ordered["time"].astype("int64")
    return (
        ordered.sort_values("time")
        .drop_duplicates("time", keep="first")
        .reset_index(drop=True)
    )


def _track_values(
    frame: pd.DataFrame,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> tuple[np.ndarray, np.ndarray]:
    track = frame.get("heading", pd.Series(np.nan, index=frame.index)).to_numpy(dtype="float64")
    valid = _observed(frame, "heading").to_numpy(copy=True)
    if "velocity" in frame:
        speed = frame["velocity"].to_numpy(dtype="float64")
        valid &= _observed(frame, "velocity").to_numpy() & (speed >= config.minimum_track_speed_mps)
    return track, valid


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
        altitude_valid = _observed(frame, "baroaltitude").to_numpy()
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
    track, valid_track = _track_values(frame, config)
    usable_track = indices[valid_track[indices]]
    track_error = (
        float(np.median(circular_difference_deg(track[usable_track], runway.true_bearing_deg)))
        if len(usable_track) >= 3 else 90.0
    )
    terminal = float(np.min(relative.threshold_distance_m))
    score = lateral + track_error / 30.0 + min(terminal / config.terminal_distance_m, 2.0)
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
        candidates.append({
            "runway": runway.designator,
            "direction": runway.direction,
            "score": score,
            "supporting_rows": rows,
            "evidence": evidence,
        })
    candidates.sort(key=lambda item: item["score"])
    finite = [item for item in candidates if math.isfinite(item["score"])]
    if not finite:
        return {
            "runway": None, "direction": None, "specificity": "unknown",
            "confidence": 0.0, "score_margin": 0.0, "candidates": candidates,
            "reason": "no_supported_runway_candidate",
        }
    winner = finite[0]
    other_direction = next(
        (item for item in finite if item["direction"] != winner["direction"]), None
    )
    direction_margin = (
        other_direction["score"] - winner["score"] if other_direction else math.inf
    )
    if winner["score"] > config.direction_score_maximum or direction_margin < config.direction_margin_minimum:
        return {
            "runway": None, "direction": None, "specificity": "unknown",
            "confidence": 0.0, "score_margin": round(float(direction_margin), 4),
            "candidates": candidates, "reason": "runway_direction_ambiguous",
        }
    parallel = next(
        (item for item in finite if item["direction"] == winner["direction"] and item is not winner),
        None,
    )
    exact_margin = parallel["score"] - winner["score"] if parallel else math.inf
    exact = exact_margin >= config.exact_margin_minimum
    confidence = min(1.0, max(0.0, direction_margin / 2.0)) * (1.0 / (1.0 + winner["score"]))
    return {
        "runway": winner["runway"] if exact else f"{winner['direction']}_pair",
        "geometry_runway": winner["runway"],
        "direction": winner["direction"],
        "specificity": "exact" if exact else "direction",
        "confidence": round(float(confidence), 4),
        "score_margin": round(float(exact_margin if exact else direction_margin), 4),
        "candidates": candidates,
        "reason": None,
    }


def _quality(frame: pd.DataFrame, config: ApproachConfig) -> dict[str, Any]:
    time = frame["time"].to_numpy(dtype="float64")
    gaps = np.diff(time) if len(time) > 1 else np.array([], dtype="float64")
    max_gap = float(gaps.max()) if len(gaps) else 0.0
    max_ground = 0.0
    max_vertical = 0.0
    if len(frame) > 1:
        usable = gaps > 0
        distance = haversine_dist(
            frame["lat"].to_numpy()[:-1], frame["lon"].to_numpy()[:-1],
            frame["lat"].to_numpy()[1:], frame["lon"].to_numpy()[1:],
        )
        if usable.any():
            max_ground = float(np.nanmax(np.asarray(distance)[usable] / gaps[usable]))
        alt_valid = _observed(frame, "baroaltitude").to_numpy()
        pair_valid = usable & alt_valid[:-1] & alt_valid[1:]
        if pair_valid.any():
            altitude = frame["baroaltitude"].to_numpy(dtype="float64")
            max_vertical = float(np.nanmax(np.abs(np.diff(altitude)[pair_valid] / gaps[pair_valid])))
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


def _persistent_spans(
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


def _supported_gate_runs(
    frame: pd.DataFrame,
    runway: RunwayThreshold,
    config: ApproachConfig,
) -> list[tuple[int, int]]:
    """Return supported final-corridor visits, separating later re-approaches."""
    relative = runway_relative(frame["lat"], frame["lon"], runway)
    inside = (
        (relative.along_track_m >= -500.0)
        & (relative.along_track_m <= config.gate_along_m)
        & (np.abs(relative.cross_track_m) <= config.gate_cross_m)
    )
    indices = np.flatnonzero(inside)
    if not len(indices):
        return []
    time = frame["time"].to_numpy(dtype="int64")
    groups: list[list[int]] = [[int(indices[0])]]
    for index in indices[1:]:
        index = int(index)
        if time[index] - time[groups[-1][-1]] > config.attempt_reentry_gap_s:
            groups.append([index])
        else:
            groups[-1].append(index)
    return [
        (group[0], group[-1])
        for group in groups
        if len(group) >= config.inference_minimum_rows
    ]


def extract_approach_attempts(
    frame: pd.DataFrame,
    *,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> list[pd.DataFrame]:
    """Extract distinct observed final-corridor visits from one candidate record.

    Parallel-runway candidates overlap almost perfectly, so temporal candidates are
    clustered before assessment. A later re-entry after the configured gap becomes a
    new attempt, which preserves a go-around followed by another approach.
    """
    geometry = geometry or load_lemd_geometry()
    observations = canonical_observations(frame)
    if observations.empty:
        return []
    time = observations["time"].to_numpy(dtype="int64")
    candidates: list[tuple[int, int]] = []
    for runway in geometry.landing_thresholds:
        for start, supported_end in _supported_gate_runs(observations, runway, config):
            extension_limit = time[supported_end] + config.outcome_extension_s
            end = int(np.searchsorted(time, extension_limit, side="right") - 1)
            candidates.append((start, max(supported_end, end)))
    if not candidates:
        return []

    candidates.sort()
    clusters: list[list[tuple[int, int]]] = []
    for candidate in candidates:
        if not clusters or candidate[0] > max(end for _, end in clusters[-1]):
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    attempts = []
    for cluster in clusters:
        start = min(item[0] for item in cluster)
        end = max(item[1] for item in cluster)
        candidate = observations.iloc[start:end + 1].reset_index(drop=True)
        if infer_runway(candidate, geometry=geometry, config=config).get("geometry_runway"):
            attempts.append(candidate)
    return attempts


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
    spans = _persistent_spans(
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
    baro_valid = _observed(frame, "baroaltitude").to_numpy()
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
        return "landing_observed", [{"name": "landing_observed", "index": index, "time": int(frame.iloc[index]["time"])}]

    altitude_valid = _observed(frame, "baroaltitude").to_numpy() & altitude_usable
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
            "config_sha256": _digest(asdict(config)),
            "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
            "reconstruction_policy_sha256": _digest(RECONSTRUCTION_POLICY),
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
    attempt = observations.iloc[indices[0]:extended_end + 1].reset_index(drop=True)
    relative = runway_relative(attempt["lat"], attempt["lon"], runway)
    quality = _quality(attempt, config)
    altitude_usable = "barometric_altitude" not in quality["channel_advisories"]
    outcome, maneuvers = _attempt_outcome(attempt, relative, altitude_usable=altitude_usable)
    terminal_position = relative.threshold_distance_m <= config.terminal_distance_m
    terminal_altitude_observed = _observed(attempt, "baroaltitude").to_numpy()
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
        or outcome in {"landing_observed", "go_around"}
    )
    if not terminal:
        quality["fatal_reasons"].append("terminal_gate_not_reached")

    bias, bias_source = (
        _vertical_bias(attempt, runway, relative)
        if altitude_usable else (None, "rate_conflict")
    )
    baro = attempt.get("baroaltitude", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    height = baro - runway.elevation_m - (bias or 0.0)
    track, track_valid = _track_values(attempt, config)

    lateral_limit = np.maximum(config.lateral_floor_m, relative.along_track_m * config.lateral_slope)
    lateral_valid = (relative.along_track_m >= 0) & (relative.along_track_m <= config.lateral_gate_m)
    lateral = _criterion(
        "lateral_path_proxy", attempt, np.abs(relative.cross_track_m), lateral_limit,
        lateral_valid, np.abs(relative.cross_track_m) > lateral_limit, relative,
        unit="m", config=config,
    )

    nominal_height = np.tan(math.radians(config.path_angle_deg)) * np.maximum(relative.along_track_m, 0)
    path_valid = (
        (bias is not None) & _observed(attempt, "baroaltitude").to_numpy()
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
    vertical = attempt.get("vertrate", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    empirical_vertical = np.array([
        row["vertical_rate_lower_mps"] if row else np.nan for row in reference_rows
    ])
    if reference is not None:
        descent_valid = _observed(attempt, "vertrate").to_numpy() & np.isfinite(empirical_vertical)
        descent_limit = empirical_vertical
    else:
        descent_valid = _observed(attempt, "vertrate").to_numpy() & (bias is not None) & (height <= config.descent_gate_height_m)
        descent_limit = np.full(len(attempt), config.descent_rate_limit_mps)
    descent = _criterion(
        "observed_descent_rate", attempt, vertical, descent_limit, descent_valid,
        vertical < config.descent_rate_limit_mps, relative, unit="m/s", config=config,
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
    speed_valid = _observed(attempt, "velocity").to_numpy() & np.isfinite(speed_lower) & np.isfinite(speed_upper)
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
            "end_time": int(attempt["time"].iloc[-1]),
            "outcome": (
                "final_gate_observed" if terminal and outcome == "closest_approach"
                else outcome if terminal else "incomplete"
            ),
            "observed_samples": len(attempt),
            "minimum_threshold_distance_m": round(float(np.min(relative.threshold_distance_m)), 1),
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
