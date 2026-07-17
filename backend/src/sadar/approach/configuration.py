"""Versioned configuration and provenance for approach screening."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


ASSESSMENT_SCHEMA_VERSION = "approach_assessment_v1"
ENGINE_VERSION = "prototype_v1"
RECONSTRUCTION_POLICY_VERSION = "observed_attempts_v1"


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


def reconstruction_policy(config: ApproachConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    """Return the provenance record for the reconstruction behavior in use."""
    return {
        "position_evidence": "observed_rows_only",
        "time_order": "sort_drop_duplicate_epoch_second",
        "parallel_candidates": "temporal_cluster_then_infer",
        "reentry_split_s": config.attempt_reentry_gap_s,
    }


RECONSTRUCTION_POLICY = reconstruction_policy()


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
