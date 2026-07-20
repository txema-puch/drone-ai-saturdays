"""Bounded, deterministic DTOs for one evaluated approach attempt."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from sadar.api.upload_contract import (
    DERIVATION_CONTRACT_VERSION,
    INPUT_SCHEMA_VERSION,
    MAX_CRITERION_EVIDENCE,
    MAX_TRAJECTORY_POINTS,
)
from sadar.releases.approach import canonical_json_bytes


def _sample_indices(length: int) -> np.ndarray:
    if length <= MAX_TRAJECTORY_POINTS:
        return np.arange(length, dtype="int64")
    return np.unique(
        np.linspace(0, length - 1, MAX_TRAJECTORY_POINTS, dtype="int64")
    )


def _nullable_number(value: Any, *, digits: int) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _observed_payload(
    frame: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered = frame.sort_values("time").reset_index(drop=True)
    indices = _sample_indices(len(ordered))
    sampled = ordered.iloc[indices]
    time = [int(value) for value in sampled["time"]]
    trajectory = {
        "observed_points": int(len(ordered)),
        "returned_points": int(len(sampled)),
        "sampling": (
            "all_observed"
            if len(sampled) == len(ordered)
            else "evenly_spaced_v1"
        ),
        "points": [
            {
                "time": int(row.time),
                "lat": _nullable_number(row.lat, digits=6),
                "lon": _nullable_number(row.lon, digits=6),
            }
            for row in sampled.itertuples(index=False)
        ],
    }
    channels = {
        "time": time,
        "barometric_altitude_m": [
            _nullable_number(value, digits=1) for value in sampled["baroaltitude"]
        ],
        "geometric_altitude_m": [
            _nullable_number(value, digits=1) for value in sampled["geoaltitude"]
        ],
        "ground_speed_mps": [
            _nullable_number(value, digits=2) for value in sampled["velocity"]
        ],
        "vertical_rate_mps": [
            _nullable_number(value, digits=2) for value in sampled["vertrate"]
        ],
        "ground_track_deg": [
            _nullable_number(value, digits=2) for value in sampled["heading"]
        ],
        "onground": [bool(value) for value in sampled["onground"]],
    }
    return trajectory, channels


def _bounded_criteria(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bounded = []
    for criterion in criteria:
        evidence = list(criterion.get("evidence", []))
        item = {key: value for key, value in criterion.items() if key != "evidence"}
        item["evidence"] = evidence[:MAX_CRITERION_EVIDENCE]
        item["evidence_truncated"] = max(
            0, len(evidence) - MAX_CRITERION_EVIDENCE
        )
        bounded.append(item)
    return bounded


def evaluation_result(
    *,
    assessment: dict[str, Any],
    attempt_frame: pd.DataFrame,
    dataset_digest: str,
    operation_id: str,
    attempt_index: int,
) -> dict[str, Any]:
    attempt = dict(assessment.get("attempt", {}))
    reference_material = {
        "dataset_digest": dataset_digest,
        "operation_id": operation_id,
        "attempt_index": attempt_index,
        "start_time": attempt.get("start_time"),
        "end_time": attempt.get("end_time"),
    }
    evaluation_ref = "ae_" + hashlib.sha256(
        canonical_json_bytes(reference_material)
    ).hexdigest()[:20]
    inference = assessment["runway_inference"]
    trajectory, channels = _observed_payload(attempt_frame)
    return {
        "evaluation_ref": evaluation_ref,
        "operation_id": operation_id,
        "attempt_index": attempt_index,
        "attempt": attempt,
        "status": assessment["status"],
        "runway": {
            "designator": inference.get("runway"),
            "geometry_runway": inference.get("geometry_runway"),
            "direction": inference.get("direction"),
            "specificity": inference.get("specificity"),
            "confidence": inference.get("confidence"),
        },
        "failed_criteria": list(assessment.get("failed_criteria", [])),
        "reasons": list(assessment.get("reasons", [])),
        "quality": assessment.get("quality", {}),
        "criteria": _bounded_criteria(assessment.get("criteria", [])),
        "maneuvers": list(assessment.get("maneuvers", [])),
        "provenance": {
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "derivation_contract_version": DERIVATION_CONTRACT_VERSION,
            "engine_version": assessment["engine_version"],
            **assessment["provenance"],
            "geometry": assessment["geometry"],
            "reference": assessment["reference"],
        },
        "trajectory": trajectory,
        "channels": channels,
        **(
            {"context": assessment["context"]}
            if assessment.get("context")
            else {}
        ),
    }
