"""Build the independent SADAR approach-screening schema-v3 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.core.approach import (
    ASSESSMENT_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    ENGINE_VERSION,
    RECONSTRUCTION_POLICY,
    RECONSTRUCTION_POLICY_VERSION,
    assess_approach,
    extract_approach_attempts,
)
from backend.core.approach_geometry import GEOMETRY_PATH, load_lemd_geometry
from backend.core.approach_reference import REFERENCE_PATH, load_approach_reference
from backend.core.contextual_approach import (
    CONTEXT_ENGINE_VERSION,
    CONTEXT_SCHEMA_VERSION,
    assess_contextual_operation,
)
from backend.serve.approach_release import (
    ApproachReleaseError,
    canonical_json_bytes,
    validate_release_directory,
    write_release,
)


REPO = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO / "data/raw/lemd_20250310_to_20250314__deduped_2026-05-10.parquet"
DEFAULT_OUTPUT = REPO / "backend/models/sadar_approach_v3"
SEALED_HOLDOUT_SHA256 = frozenset({
    "16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899"
})
MAX_CASE_OBSERVATIONS = 1_200
OBSERVATION_FIELDS = (
    "time", "lat", "lon", "baroaltitude", "geoaltitude", "velocity",
    "heading", "vertrate", "onground", "squawk", "alert", "callsign",
)
STATUS_PRIORITY = {
    "review_required": 0,
    "partial_observation": 1,
    "criteria_observed": 2,
    "not_assessable": 3,
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_not_sealed(path: Path) -> str:
    """Hash and reject the final 2026 holdout before parquet parsing occurs."""
    digest = file_sha256(path)
    if digest in SEALED_HOLDOUT_SHA256:
        raise ValueError("refusing to read sealed 2026 holdout before the final burn")
    return digest


def _json_value(value: Any) -> Any:
    """Normalize pandas/numpy values and replace unavailable/non-finite data with null."""
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
        return number if math.isfinite(number) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value) if not isinstance(value, str) else value


def _first_text(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = frame[column].dropna().astype(str).str.strip()
    values = values[values != ""]
    return values.iloc[0] if len(values) else None


def _identity(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _evidence_indices(assessment: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    for criterion in assessment.get("criteria", []):
        for evidence in criterion.get("evidence", []):
            for key in ("start_index", "end_index", "worst_index"):
                value = evidence.get(key)
                if isinstance(value, int) and value >= 0:
                    indices.add(value)
    for maneuver in assessment.get("maneuvers", []):
        value = maneuver.get("index")
        if isinstance(value, int) and value >= 0:
            indices.add(value)
    return indices


def _bounded_indices(length: int, *, required: set[int], limit: int) -> list[int]:
    if limit < 2:
        raise ValueError("case observation limit must be at least 2")
    required = {index for index in required if 0 <= index < length} | ({0, length - 1} if length else set())
    if length <= limit:
        return list(range(length))
    if len(required) >= limit:
        # Evidence anchors take priority, with deterministic even thinning if pathological.
        ordered = sorted(required)
        positions = np.linspace(0, len(ordered) - 1, limit, dtype=int)
        return sorted({ordered[int(position)] for position in positions})
    remaining = limit - len(required)
    candidates = [index for index in range(length) if index not in required]
    positions = np.linspace(0, len(candidates) - 1, remaining, dtype=int)
    return sorted(required | {candidates[int(position)] for position in positions})


def _case_observations(
    frame: pd.DataFrame,
    assessment: dict[str, Any],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    indices = _bounded_indices(len(frame), required=_evidence_indices(assessment), limit=limit)
    observations = []
    for index in indices:
        row = frame.iloc[index]
        record: dict[str, Any] = {"observation_index": index}
        for field in OBSERVATION_FIELDS:
            if field in frame.columns:
                record[field] = _json_value(row[field])
        observations.append(record)
    return observations, len(indices) < len(frame)


def _counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_payloads(
    frame: pd.DataFrame,
    *,
    input_sha256: str,
    reference: dict[str, Any],
    geometry_payload: dict[str, Any],
    benchmark: dict[str, Any] | None = None,
    contextual: dict[str, Any] | None = None,
    max_case_observations: int = MAX_CASE_OBSERVATIONS,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Assess every candidate operation and return payloads, source, and contracts."""
    required = {"flight_id", "time", "lat", "lon"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"dataset missing required columns: {sorted(missing)}")
    geometry = load_lemd_geometry()
    engine_version = CONTEXT_ENGINE_VERSION if contextual is not None else ENGINE_VERSION
    config_payload = {
        "schema_version": "approach_config_v1",
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": engine_version,
        "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
        "reconstruction_policy": RECONSTRUCTION_POLICY,
        "config": asdict(DEFAULT_CONFIG),
    }
    if contextual is not None:
        config_payload["context_schema_version"] = CONTEXT_SCHEMA_VERSION
        config_payload["context_sources"] = contextual["sources"]

    attempt_records: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    operation_records: list[dict[str, Any]] = []
    for raw_operation_id, operation_frame in frame.groupby("flight_id", sort=True):
        raw_id = str(raw_operation_id)
        operation_id = _identity("op", {"source": input_sha256, "flight_id": raw_id})
        extracted = extract_approach_attempts(operation_frame, geometry=geometry, config=DEFAULT_CONFIG)
        operation_attempt_ids: list[str] = []
        operation_case_ids: list[str] = []
        operation_statuses: list[str] = []
        contextual_assessments = None
        if contextual is not None:
            raw_icao24 = (_first_text(operation_frame, "icao24") or raw_id.split("_", 1)[0]).lower()
            contextual_assessments = assess_contextual_operation(
                operation_frame,
                operation_id=operation_id,
                weather=contextual["weather"],
                aircraft_metadata=contextual["aircraft"].get(raw_icao24),
                reference=reference,
                geometry=geometry,
                config=DEFAULT_CONFIG,
            )["attempts"]
            if len(contextual_assessments) != len(extracted):
                raise ValueError("context changed release attempt reconstruction")
        for sequence, attempt_frame in enumerate(extracted, start=1):
            start_time = int(attempt_frame["time"].iloc[0])
            end_time = int(attempt_frame["time"].iloc[-1])
            identity = {
                "operation_id": operation_id,
                "sequence": sequence,
                "start_time": start_time,
                "end_time": end_time,
            }
            attempt_id = _identity("a", identity)
            case_id = _identity("c", identity)
            if contextual_assessments is None:
                raw_assessment = assess_approach(
                    attempt_frame,
                    operation_id=attempt_id,
                    geometry=geometry,
                    config=DEFAULT_CONFIG,
                    reference=reference,
                )
            else:
                raw_assessment = contextual_assessments[sequence - 1]
                raw_assessment["operation_id"] = attempt_id
                raw_assessment["provenance"]["context_sources_sha256"] = hashlib.sha256(
                    canonical_json_bytes(contextual["sources"])
                ).hexdigest()
            assessment = _json_value(raw_assessment)
            observations, downsampled = _case_observations(
                attempt_frame, assessment, limit=max_case_observations
            )
            attempt_record = {
                "attempt_id": attempt_id,
                "case_id": case_id,
                "operation_id": operation_id,
                "sequence": sequence,
                "start_time": start_time,
                "end_time": end_time,
                "status": assessment["status"],
                "outcome": assessment.get("attempt", {}).get("outcome", "unavailable"),
                "runway": assessment.get("runway_inference", {}).get("runway"),
                "runway_direction": assessment.get("runway_inference", {}).get("direction"),
                "failed_criteria": assessment.get("failed_criteria", []),
                "assessment": assessment,
            }
            case_record = {
                "case_id": case_id,
                "attempt_id": attempt_id,
                "operation_id": operation_id,
                "observation_count": len(attempt_frame),
                "observations_downsampled": downsampled,
                "observations": observations,
            }
            attempt_records.append(attempt_record)
            case_records.append(case_record)
            operation_attempt_ids.append(attempt_id)
            operation_case_ids.append(case_id)
            operation_statuses.append(assessment["status"])

        time_values = pd.to_numeric(operation_frame["time"], errors="coerce").dropna()
        worst_status = min(
            operation_statuses,
            key=lambda value: STATUS_PRIORITY.get(value, 99),
            default="no_approach_attempt",
        )
        operation_records.append({
            "operation_id": operation_id,
            "source_operation_id": raw_id,
            "icao24": _first_text(operation_frame, "icao24"),
            "callsign": _first_text(operation_frame, "callsign"),
            "start_time": int(time_values.min()) if len(time_values) else None,
            "end_time": int(time_values.max()) if len(time_values) else None,
            "attempt_count": len(operation_attempt_ids),
            "attempt_ids": operation_attempt_ids,
            "case_ids": operation_case_ids,
            "status_counts": _counts(operation_statuses),
            "worst_status": worst_status,
        })

    attempt_records.sort(key=lambda item: item["attempt_id"])
    case_records.sort(key=lambda item: item["case_id"])
    operation_records.sort(key=lambda item: item["operation_id"])
    statuses = [item["status"] for item in attempt_records]
    outcomes = [item["outcome"] for item in attempt_records]
    assessable = [status for status in statuses if status != "not_assessable"]
    metrics = {
        "schema_version": "approach_release_metrics_v1",
        "input_sha256": input_sha256,
        "rows": len(frame),
        "operations": len(operation_records),
        "operations_with_attempts": sum(item["attempt_count"] > 0 for item in operation_records),
        "attempts": len(attempt_records),
        "status_counts": _counts(statuses),
        "outcome_counts": _counts(outcomes),
        "abstention_rate": (
            round(statuses.count("not_assessable") / len(statuses), 6) if statuses else None
        ),
        "review_rate_among_assessable": (
            round(assessable.count("review_required") / len(assessable), 6)
            if assessable else None
        ),
        "limitations": [
            "Retrospective ADS-B-observable screening; not live monitoring or ATC decision support.",
            "Review-required means an observable proxy crossed a provisional criterion; it is not a certified unstable-approach finding.",
            (
                "QNH, airport wind and current-registry aircraft type are contextual proxies; actual mass, configuration, clearance and intent remain unavailable."
                if contextual is not None
                else "Weather, QNH, wind, mass, configuration, clearance and intent are absent from this ADS-B-only release."
            ),
            "Parallel runway assignment may remain direction-level where observed geometry is ambiguous.",
            "The historical LSTM is optional research evidence and never changes the approach verdict or queue priority.",
        ],
    }
    if contextual is not None:
        metrics.update({
            "qualification": contextual["sources"]["qualification"],
            "allowed_role": "research_and_evidence_labeling_demonstrator",
            "blocked_uses": [
                "operational_monitoring",
                "emergency_detection",
                "stabilized_approach_certification",
                "atc_decision_support",
                "safety_performance_claims",
                "context_accuracy_improvement_claims",
            ],
        })
        metrics["limitations"].append(
            "This contextual candidate is not qualified: independent labels and a fresh holdout are unavailable."
        )
    payloads: dict[str, Any] = {
        "attempts.json": {"schema_version": "approach_attempts_v1", "attempts": attempt_records},
        "cases.json": {"schema_version": "approach_cases_v1", "cases": case_records},
        "operations.json": {
            "schema_version": "approach_operations_v1", "operations": operation_records
        },
        "metrics.json": metrics,
        "config/approach-config.json": config_payload,
        "config/lemd-geometry.json": geometry_payload,
        "reference/approach-reference.json": reference,
    }
    if benchmark is not None:
        payloads["research/benchmark.json"] = benchmark
    contracts = {
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": engine_version,
        "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
        "case_observation_limit": max_case_observations,
        "approach_config_sha256": hashlib.sha256(canonical_json_bytes(config_payload)).hexdigest(),
        "geometry_source_sha256": geometry.artifact_sha256,
        "reference_sha256": reference["artifact_sha256"],
    }
    if contextual is not None:
        contracts["context_sources_sha256"] = hashlib.sha256(
            canonical_json_bytes(contextual["sources"])
        ).hexdigest()
        contracts["qualification"] = contextual["sources"]["qualification"]
        contracts["allowed_role"] = "research_and_evidence_labeling_demonstrator"
    source = {
        "input_sha256": input_sha256,
        "rows": len(frame),
        "operations": len(operation_records),
    }
    return payloads, source, contracts


def build_approach_release(
    input_path: Path = DEFAULT_INPUT,
    *,
    output: Path = DEFAULT_OUTPUT,
    reference_path: Path = REFERENCE_PATH,
    benchmark_path: Path | None = None,
    max_case_observations: int = MAX_CASE_OBSERVATIONS,
) -> dict[str, Any]:
    """Build atomically; an existing identical release is accepted idempotently."""
    input_path = Path(input_path)
    output = Path(output)
    input_digest = assert_not_sealed(input_path)
    reference = load_approach_reference(reference_path)
    geometry_payload = json.loads(GEOMETRY_PATH.read_text())
    benchmark = json.loads(benchmark_path.read_text()) if benchmark_path else None
    frame = pd.read_parquet(input_path)
    payloads, source, contracts = build_payloads(
        frame,
        input_sha256=input_digest,
        reference=reference,
        geometry_payload=geometry_payload,
        benchmark=benchmark,
        max_case_observations=max_case_observations,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    candidate = temporary_root / "release"
    try:
        manifest = write_release(candidate, payloads, source=source, contracts=contracts)
        if output.exists():
            existing = validate_release_directory(output)
            if existing != manifest:
                raise ApproachReleaseError(
                    f"output already contains a different release: {existing['release_id']}"
                )
            return existing
        os.replace(candidate, output)
        return validate_release_directory(output)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference", type=Path, default=REFERENCE_PATH)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--max-case-observations", type=int, default=MAX_CASE_OBSERVATIONS)
    args = parser.parse_args()
    manifest = build_approach_release(
        args.input,
        output=args.output,
        reference_path=args.reference,
        benchmark_path=args.benchmark,
        max_case_observations=args.max_case_observations,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
