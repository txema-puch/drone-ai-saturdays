"""Stable HTTP representations derived from validated release records."""

from __future__ import annotations

import pandas as pd

from sadar.api.state import ReleaseState
from sadar.approach.geometry import load_lemd_geometry, runway_relative


def quality_flags(assessment: dict) -> list[str]:
    quality = assessment.get("quality") or {}
    flags = list(quality.get("fatal_reasons") or [])
    for advisories in (quality.get("channel_advisories") or {}).values():
        flags.extend(advisories)
    return sorted(set(str(flag) for flag in flags))


def summary(record: dict) -> dict:
    assessment = record["assessment"]
    attempt = assessment.get("attempt") or {}
    quality = assessment.get("quality") or {}
    inference = assessment.get("runway_inference") or {}
    return {
        "attempt_id": record["attempt_id"],
        "operation_ref": record["operation_id"],
        "status": record["status"],
        "direction": record.get("runway_direction"),
        "runway": record.get("runway"),
        "geometry_runway": inference.get("geometry_runway"),
        "runway_specificity": inference.get("specificity"),
        "runway_confidence": inference.get("confidence"),
        "runway_score_margin": inference.get("score_margin"),
        "failed_criteria": list(record.get("failed_criteria") or []),
        "outcome": record.get("outcome"),
        "observed_samples": attempt.get("observed_samples"),
        "coverage": {
            "observed_samples": attempt.get("observed_samples"),
            "maximum_gap_s": quality.get("maximum_gap_s"),
        },
        "start_time": record.get("start_time"),
        "end_time": record.get("end_time"),
        "reasons": list(assessment.get("reasons") or []),
        "quality_flags": quality_flags(assessment),
    }


def case_path(record: dict, case: dict) -> list[dict]:
    observations = case.get("observations") or []
    if not observations:
        return []
    runway_name = record["assessment"].get("runway_inference", {}).get(
        "geometry_runway"
    )
    relative = None
    if runway_name:
        runway = load_lemd_geometry().thresholds.get(runway_name)
        valid = all(
            item.get("lat") is not None and item.get("lon") is not None
            for item in observations
        )
        if runway is not None and valid:
            frame = pd.DataFrame(observations)
            relative = runway_relative(frame["lat"], frame["lon"], runway)
    path = []
    for index, item in enumerate(observations):
        point = {
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "alt": item.get("baroaltitude"),
            "time": item.get("time"),
            "t": item.get("time"),
            "observed": True,
        }
        if relative is not None:
            point["along_track_m"] = round(float(relative.along_track_m[index]), 1)
            point["cross_track_m"] = round(float(relative.cross_track_m[index]), 1)
        path.append(point)
    return path


def detail(record: dict, state: ReleaseState) -> dict:
    assessment = record["assessment"]
    case = state.cases_by_id[record["case_id"]]
    return {
        **summary(record),
        "path": case_path(record, case),
        "criteria": assessment.get("criteria") or [],
        "quality": assessment.get("quality"),
        "altitude_reference": assessment.get("altitude_reference"),
        "maneuvers": assessment.get("maneuvers") or [],
        "provenance": assessment.get("provenance"),
        "geometry": assessment.get("geometry"),
        "reference": assessment.get("reference"),
        "context": assessment.get("context"),
        "schema_version": assessment.get("schema_version"),
        "engine_version": assessment.get("engine_version"),
        "observations_downsampled": case.get("observations_downsampled", False),
        "research_benchmark": state.research,
    }
