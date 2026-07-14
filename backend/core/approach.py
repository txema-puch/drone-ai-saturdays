"""Rules-first, observed-row LEMD approach assessment prototype.

This module deliberately does not import the historical LSTM preprocessing or serving
stack. Criterion evidence is computed from observed values only; model-era interpolated
rows are filtered through their ``*_missing`` masks.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

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


@dataclass(frozen=True)
class ApproachConfig:
    gate_along_m: float = 20_000.0
    gate_cross_m: float = 6_000.0
    terminal_distance_m: float = 1_500.0
    minimum_samples: int = 20
    minimum_observed_fraction: float = 0.70
    maximum_gap_s: int = 60
    maximum_implied_ground_speed_mps: float = 400.0
    maximum_implied_vertical_rate_mps: float = 50.0
    minimum_track_speed_mps: float = 30.0
    inference_minimum_rows: int = 8
    direction_score_maximum: float = 4.0
    direction_margin_minimum: float = 0.35
    exact_margin_minimum: float = 0.20
    persistence_rows: int = 3
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


def _track_values(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    track = frame.get("heading", pd.Series(np.nan, index=frame.index)).to_numpy(dtype="float64")
    valid = _observed(frame, "heading").to_numpy(copy=True)
    if "velocity" in frame:
        speed = frame["velocity"].to_numpy(dtype="float64")
        valid &= _observed(frame, "velocity").to_numpy() & (speed >= DEFAULT_CONFIG.minimum_track_speed_mps)
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
    indices = np.flatnonzero(in_gate)
    if len(indices) < config.inference_minimum_rows:
        return math.inf, len(indices), {}
    indices = indices[-min(60, len(indices)):]
    along = relative.along_track_m[indices]
    cross = np.abs(relative.cross_track_m[indices])
    corridor = np.maximum(250.0, along * 0.12)
    lateral = float(np.median(cross / corridor))
    track, valid_track = _track_values(frame)
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
    reasons = []
    if len(frame) < config.minimum_samples:
        reasons.append("insufficient_observations")
    if max_gap > config.maximum_gap_s:
        reasons.append("approach_coverage_gap")
    if max_ground > config.maximum_implied_ground_speed_mps:
        reasons.append("position_rate_conflict")
    if max_vertical > config.maximum_implied_vertical_rate_mps:
        reasons.append("altitude_rate_conflict")
    return {
        "observed_samples": int(len(frame)),
        "maximum_gap_s": round(max_gap, 1),
        "maximum_implied_ground_speed_mps": round(max_ground, 1),
        "maximum_implied_vertical_rate_mps": round(max_vertical, 1),
        "reasons": reasons,
    }


def _persistent_spans(mask: np.ndarray, minimum_rows: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(mask.tolist() + [False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= minimum_rows:
                spans.append((start, index - 1))
            start = None
    return spans


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
    spans = _persistent_spans(valid & failure, config.persistence_rows)
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


def assess_approach(
    frame: pd.DataFrame,
    *,
    operation_id: str | None = None,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Assess the last supported LEMD approach attempt in one candidate record."""
    geometry = geometry or load_lemd_geometry()
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
        "runway_inference": inference,
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
    attempt = observations.iloc[indices[0]:indices[-1] + 1].reset_index(drop=True)
    relative = runway_relative(attempt["lat"], attempt["lon"], runway)
    quality = _quality(attempt, config)
    terminal = bool(np.min(relative.threshold_distance_m) <= config.terminal_distance_m)
    if not terminal:
        quality["reasons"].append("terminal_gate_not_reached")

    bias, bias_source = _vertical_bias(attempt, runway, relative)
    baro = attempt.get("baroaltitude", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    height = baro - runway.elevation_m - (bias or 0.0)
    track, track_valid = _track_values(attempt)

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

    vertical = attempt.get("vertrate", pd.Series(np.nan, index=attempt.index)).to_numpy(dtype="float64")
    descent_valid = _observed(attempt, "vertrate").to_numpy() & (bias is not None) & (height <= config.descent_gate_height_m)
    descent_limit = np.full(len(attempt), config.descent_rate_limit_mps)
    descent = _criterion(
        "observed_descent_rate", attempt, vertical, descent_limit, descent_valid,
        vertical < config.descent_rate_limit_mps, relative, unit="m/s", config=config,
    )

    correction = circular_difference_deg(track, runway.true_bearing_deg)
    correction_limit = np.full(len(attempt), config.correction_limit_deg)
    correction_valid = track_valid & (relative.along_track_m >= 0) & (relative.along_track_m <= config.correction_gate_m)
    late_correction = _criterion(
        "late_track_correction", attempt, correction, correction_limit, correction_valid,
        correction > config.correction_limit_deg, relative, unit="deg", config=config,
    )
    speed = {
        "name": "observed_ground_speed_envelope",
        "status": "not_observed",
        "severity": "high",
        "observed_samples": int(_observed(attempt, "velocity").sum()),
        "reason": "empirical_reference_not_fitted",
        "evidence": [],
    }
    criteria = [lateral, path, descent, speed, late_correction]
    failed = [item for item in criteria if item["status"] == "review_required" and item["severity"] == "high"]
    missing_required = [item for item in criteria if item["status"] == "not_observed"]
    if quality["reasons"]:
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
        "reasons": quality["reasons"],
        "attempt": {
            "start_time": int(attempt["time"].iloc[0]),
            "end_time": int(attempt["time"].iloc[-1]),
            "outcome": "closest_approach" if terminal else "incomplete",
            "observed_samples": len(attempt),
            "minimum_threshold_distance_m": round(float(np.min(relative.threshold_distance_m)), 1),
        },
        "quality": quality,
        "altitude_reference": {"bias_m": round(bias, 1) if bias is not None else None, "source": bias_source},
        "criteria": criteria,
        "failed_criteria": [item["name"] for item in failed],
        "maneuvers": [],
    }
