"""Pure assessment and schema-v4 payload generation for synthetic scenarios."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import fields
from typing import Any

import numpy as np
import pandas as pd

from sadar.approach.assessment import (
    ASSESSMENT_SCHEMA_VERSION,
    RECONSTRUCTION_POLICY,
    RECONSTRUCTION_POLICY_VERSION,
    assess_approach,
    extract_approach_attempts,
)
from sadar.approach.configuration import ApproachConfig
from sadar.approach.contextual import CONTEXT_ENGINE_VERSION
from sadar.approach.geometry import runway_relative
from sadar.approach.reference import validate_reference
from sadar.demo.generator import generate_frame, geometry_from_payload
from sadar.demo.scenarios import SCENARIOS, Scenario
from sadar.releases.approach import canonical_json_bytes


GENERATOR_VERSION = "sadar_synthetic_approach_v1"
DEFAULT_SEED = 20_260_718
OBSERVATION_FIELDS = (
    "time", "lat", "lon", "baroaltitude", "geoaltitude", "velocity",
    "heading", "vertrate", "onground",
)
CONFIG_PAYLOAD_FIELDS = {
    "schema_version", "assessment_schema_version", "engine_version",
    "reconstruction_policy_version", "reconstruction_policy", "config",
}
GEOMETRY_PAYLOAD_FIELDS = {
    "schema_version", "airport", "coordinate_reference", "effective_date",
    "retrieved_at", "source", "historical_applicability", "thresholds",
    "runway_pairs",
}
GEOMETRY_THRESHOLD_FIELDS = {
    "pair", "lat", "lon", "true_bearing_deg", "elevation_m", "displaced_m",
    "landing_available",
}
GEOMETRY_THRESHOLD_OPTIONAL_FIELDS = {"tdz_elevation_m"}
PUBLIC_REFERENCE_FIELDS = {
    "schema_version", "fit_fold", "source_reference_sha256", "cohort",
    "distance_bins_m", "quantiles", "minimum_samples", "minimum_attempts",
    "accepted_attempts", "entries", "artifact_sha256",
}


def _digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _identifier(prefix: str, scenario_id: str, seed: int) -> str:
    digest = hashlib.sha256(
        f"{GENERATOR_VERSION}:{seed}:{scenario_id}:{prefix}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if isinstance(value, np.ndarray):
        return [_json_value(child) for child in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return round(number, 9) if math.isfinite(number) else None
    return value


def _quality_flags(assessment: dict[str, Any]) -> tuple[str, ...]:
    quality = assessment.get("quality", {})
    advisories = [
        flag
        for channel_flags in quality.get("channel_advisories", {}).values()
        for flag in channel_flags
    ]
    return tuple(sorted(set(quality.get("fatal_reasons", [])) | set(advisories)))


def _landing_outcome(assessment: dict[str, Any], end_along_m: float) -> dict[str, Any]:
    outcome = assessment.get("attempt", {}).get("outcome", "unavailable")
    available = outcome in {"landing_observed", "touch_and_go"}
    if available:
        reason = None
    elif outcome == "go_around":
        reason = "go_around_observed"
    elif end_along_m > 0:
        reason = "evidence_ends_before_threshold"
    else:
        reason = "landing_not_observed"
    return {
        "available": available,
        "reason": reason,
        "evidence_end_along_track_m": round(end_along_m, 1),
    }


def _assert_expected(scenario: Scenario, assessment: dict[str, Any]) -> None:
    observed = {
        "status": assessment["status"],
        "failed": tuple(sorted(assessment.get("failed_criteria", []))),
        "outcome": assessment.get("attempt", {}).get("outcome"),
        "specificity": assessment["runway_inference"].get("specificity"),
        "quality": _quality_flags(assessment),
    }
    expected = {
        "status": scenario.expected_status,
        "failed": tuple(sorted(scenario.expected_failed_criteria)),
        "outcome": scenario.expected_outcome,
        "specificity": scenario.expected_runway_specificity,
        "quality": tuple(sorted(scenario.expected_quality_flags)),
    }
    if observed != expected:
        raise ValueError(
            f"synthetic scenario {scenario.scenario_id} assessment mismatch: "
            f"expected={expected!r}, observed={observed!r}"
        )


def _validate_methodology_payloads(methodology_payloads: dict[str, Any]) -> None:
    required = {
        "config/approach-config.json", "config/lemd-geometry.json",
        "reference/approach-reference.json",
    }
    if not isinstance(methodology_payloads, dict) or set(methodology_payloads) != required:
        raise ValueError("methodology payload set mismatch")

    config_payload = methodology_payloads["config/approach-config.json"]
    if not isinstance(config_payload, dict) or set(config_payload) != CONFIG_PAYLOAD_FIELDS:
        raise ValueError("approach config payload schema mismatch")
    expected_metadata = {
        "schema_version": "approach_config_v1",
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": CONTEXT_ENGINE_VERSION,
        "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
        "reconstruction_policy": RECONSTRUCTION_POLICY,
    }
    if any(config_payload.get(key) != value for key, value in expected_metadata.items()):
        raise ValueError("approach config metadata mismatch")
    config_keys = {item.name for item in fields(ApproachConfig)}
    if not isinstance(config_payload["config"], dict) or set(config_payload["config"]) != config_keys:
        raise ValueError("approach config fields mismatch")

    geometry_payload = methodology_payloads["config/lemd-geometry.json"]
    if not isinstance(geometry_payload, dict) or set(geometry_payload) != GEOMETRY_PAYLOAD_FIELDS:
        raise ValueError("LEMD geometry payload schema mismatch")
    if geometry_payload.get("schema_version") != "lemd_geometry_v1":
        raise ValueError("unsupported LEMD geometry schema")
    thresholds = geometry_payload.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {
        "14L", "14R", "18L", "18R", "32L", "32R", "36L", "36R",
    }:
        raise ValueError("LEMD geometry must define all eight thresholds")
    if any(
        not isinstance(raw, dict)
        or set(raw) not in {
            frozenset(GEOMETRY_THRESHOLD_FIELDS),
            frozenset(GEOMETRY_THRESHOLD_FIELDS | GEOMETRY_THRESHOLD_OPTIONAL_FIELDS),
        }
        for raw in thresholds.values()
    ):
        raise ValueError("LEMD geometry threshold schema mismatch")

    reference = methodology_payloads["reference/approach-reference.json"]
    if not isinstance(reference, dict) or set(reference) != PUBLIC_REFERENCE_FIELDS:
        raise ValueError("public approach reference schema mismatch")
    validate_reference(reference)


def generate_demo_payloads(
    *,
    seed: int,
    methodology_payloads: dict[str, Any],
) -> dict[str, Any]:
    """Return all four canonical payload objects without file or network reads."""
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 4_294_967_295
    ):
        raise ValueError("seed must be a uint32 integer")
    _validate_methodology_payloads(methodology_payloads)
    config_payload = methodology_payloads["config/approach-config.json"]
    geometry_payload = methodology_payloads["config/lemd-geometry.json"]
    reference = methodology_payloads["reference/approach-reference.json"]
    config = ApproachConfig(**config_payload["config"])
    geometry = geometry_from_payload(geometry_payload)

    attempts: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    catalog_scenarios: list[dict[str, str]] = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        frame = generate_frame(
            scenario,
            geometry=geometry,
            clock_offset_s=scenario_index * 3_600,
        )
        extracted = extract_approach_attempts(frame, geometry=geometry, config=config)
        if len(extracted) != 1:
            raise ValueError(
                f"synthetic scenario {scenario.scenario_id} produced {len(extracted)} attempts"
            )
        attempt_frame = extracted[0]
        operation_id = _identifier("syn-op", scenario.scenario_id, seed)
        attempt_id = _identifier("syn-a", scenario.scenario_id, seed)
        case_id = _identifier("syn-c", scenario.scenario_id, seed)
        assessment = _json_value(assess_approach(
            attempt_frame,
            operation_id=attempt_id,
            geometry=geometry,
            config=config,
            reference=reference,
        ))
        _assert_expected(scenario, assessment)
        runway = geometry.thresholds[assessment["runway_inference"]["geometry_runway"]]
        relative = runway_relative(attempt_frame["lat"], attempt_frame["lon"], runway)
        end_along = float(relative.along_track_m[-1])
        landing_outcome = _landing_outcome(assessment, end_along)
        common = {
            "data_origin": "synthetic",
            "scenario_id": scenario.scenario_id,
            "scenario_title": scenario.title,
            "teaching_goal": scenario.teaching_goal,
        }
        observations = []
        for observation_index, (_, row) in enumerate(attempt_frame.iterrows()):
            observation = {"observation_index": observation_index}
            for field in OBSERVATION_FIELDS:
                if field in row:
                    value = _json_value(row[field])
                    if isinstance(value, float):
                        value = round(value, 8 if field in {"lat", "lon"} else 6)
                    observation[field] = value
            observations.append(observation)
        attempts.append({
            **common,
            "attempt_id": attempt_id,
            "case_id": case_id,
            "operation_id": operation_id,
            "sequence": 1,
            "start_time": int(attempt_frame["time"].iloc[0]),
            "end_time": int(attempt_frame["time"].iloc[-1]),
            "status": assessment["status"],
            "outcome": assessment["attempt"]["outcome"],
            "landing_outcome": landing_outcome,
            "runway": assessment["runway_inference"].get("runway"),
            "runway_direction": assessment["runway_inference"].get("direction"),
            "failed_criteria": assessment.get("failed_criteria", []),
            "assessment": assessment,
        })
        cases.append({
            **common,
            "case_id": case_id,
            "attempt_id": attempt_id,
            "operation_id": operation_id,
            "observation_count": len(observations),
            "observations_downsampled": False,
            "landing_outcome": landing_outcome,
            "observations": observations,
        })
        operations.append({
            **common,
            "operation_id": operation_id,
            "attempt_count": 1,
            "attempt_ids": [attempt_id],
            "case_ids": [case_id],
            "status_counts": {assessment["status"]: 1},
            "worst_status": assessment["status"],
        })
        catalog_scenarios.append({
            "scenario_id": scenario.scenario_id,
            "scenario_title": scenario.title,
            "teaching_goal": scenario.teaching_goal,
        })

    attempts.sort(key=lambda item: item["attempt_id"])
    cases.sort(key=lambda item: item["case_id"])
    operations.sort(key=lambda item: item["operation_id"])
    catalog_scenarios.sort(key=lambda item: item["scenario_id"])
    return {
        "catalog.json": {
            "schema_version": "approach_synthetic_demo_v1",
            "generator_version": GENERATOR_VERSION,
            "seed": seed,
            "approach_config_sha256": _digest(config_payload),
            "geometry_source_sha256": _digest(geometry_payload),
            "reference_sha256": _digest(reference),
            "scenarios": catalog_scenarios,
        },
        "attempts.json": {"schema_version": "approach_attempts_v1", "attempts": attempts},
        "cases.json": {"schema_version": "approach_cases_v1", "cases": cases},
        "operations.json": {"schema_version": "approach_operations_v1", "operations": operations},
    }


def semantic_snapshot(payloads: dict[str, Any]) -> dict[str, Any]:
    attempts = {
        item["scenario_id"]: item
        for item in payloads["attempts.json"]["attempts"]
    }
    cases = {item["scenario_id"]: item for item in payloads["cases.json"]["cases"]}
    catalog = payloads["catalog.json"]
    scenarios = []
    criterion_counts: Counter[str] = Counter()
    for scenario_id in sorted(attempts):
        attempt = attempts[scenario_id]
        assessment = attempt["assessment"]
        case = cases[scenario_id]
        for criterion in assessment.get("failed_criteria", []):
            criterion_counts[criterion] += 1
        scenarios.append({
            "scenario_id": scenario_id,
            "status": attempt["status"],
            "failed_criteria": sorted(attempt["failed_criteria"]),
            "outcome": attempt["outcome"],
            "runway_direction": attempt["runway_direction"],
            "runway_specificity": assessment["runway_inference"]["specificity"],
            "quality_flags": list(_quality_flags(assessment)),
            "observation_count": case["observation_count"],
            "end_along_track_m": case["landing_outcome"]["evidence_end_along_track_m"],
        })
    return {
        "generator_version": catalog["generator_version"],
        "seed": catalog["seed"],
        "approach_config_sha256": catalog["approach_config_sha256"],
        "geometry_source_sha256": catalog["geometry_source_sha256"],
        "reference_sha256": catalog["reference_sha256"],
        "scenario_ids": sorted(attempts),
        "scenarios": scenarios,
        "status_counts": dict(sorted(
            Counter(item["status"] for item in attempts.values()).items()
        )),
        "outcome_counts": dict(sorted(
            Counter(item["outcome"] for item in attempts.values()).items()
        )),
        "criterion_counts": dict(sorted(criterion_counts.items())),
        "payload_sha256": {
            name: _digest(payloads[name]) for name in sorted(payloads)
        },
    }
