"""Audit contextual source coverage on development cohorts only.

This script never changes assessment criteria and refuses the burned 2026 holdout.
It measures whether time-aligned NOAA weather and OpenSky aircraft metadata are
available for each reconstructed approach attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from sadar.approach.assessment import assess_operation
from sadar.approach.context import (
    DEFAULT_MAXIMUM_WEATHER_AGE_S,
    join_latest_prior_weather,
    load_aircraft_metadata_parts,
    load_global_hourly_weather,
    runway_relative_wind_components,
)
from sadar.approach.geometry import load_lemd_geometry
from sadar.approach.reference import load_approach_reference
from sadar.pipelines.audit_dataset import SEALED_HOLDOUT_SHA256, file_sha256


SOURCE_2025_SHA256 = "8256c65f95135597f3db07413941380fc2a0c6bbfc429b07b12b10478f7e2c10"
MAXIMUM_WEATHER_AGE_S = DEFAULT_MAXIMUM_WEATHER_AGE_S


def _logical_parts_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(directory.glob("aircraftDatabase.part*"))
    if not paths:
        raise FileNotFoundError("OpenSky aircraft metadata parts are unavailable")
    for path in paths:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _count(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _load_frame(cohort: str, model_dir: Path, source_2025: Path) -> tuple[pd.DataFrame, str]:
    if cohort in {"train", "val"}:
        split_ids = json.loads((model_dir / "split_ids.json").read_text())
        allowed_segments = set(split_ids[cohort])
        clean = pd.read_parquet(model_dir / "clean_df.parquet")
        operations = set(
            clean.loc[clean["segment_id"].isin(allowed_segments), "flight_id"].astype(str)
        )
        selected = clean.loc[clean["flight_id"].astype(str).isin(operations)].copy()
        source_digest = file_sha256(model_dir / "clean_df.parquet")
        return selected, source_digest
    digest = file_sha256(source_2025)
    if digest in SEALED_HOLDOUT_SHA256:
        raise ValueError("refusing contextual access to the burned 2026 holdout")
    if digest != SOURCE_2025_SHA256:
        raise ValueError("2025 contextual source does not match its audited digest")
    return pd.read_parquet(source_2025), digest


def audit_context(
    *,
    cohort: str,
    model_dir: Path | None = None,
    source_2025: Path | None = None,
    weather_dir: Path | None = None,
    aircraft_parts_dir: Path | None = None,
) -> dict[str, Any]:
    if cohort not in {"train", "val", "2025"}:
        raise ValueError("cohort must be train, val, or 2025")
    if None in (model_dir, source_2025, weather_dir, aircraft_parts_dir):
        raise ValueError("model, source, weather, and aircraft paths are required")
    assert model_dir is not None and source_2025 is not None
    assert weather_dir is not None and aircraft_parts_dir is not None
    frame, source_digest = _load_frame(cohort, model_dir, source_2025)
    reference = load_approach_reference()
    geometry = load_lemd_geometry()

    years = sorted(
        set(pd.to_datetime(frame["time"], unit="s", utc=True).dt.year.astype(int))
    )
    weather_paths = [weather_dir / f"lemd_isd_{year}.csv" for year in years]
    missing_weather = [str(path) for path in weather_paths if not path.exists()]
    if missing_weather:
        raise FileNotFoundError(f"weather source files unavailable: {missing_weather}")
    weather = []
    for path in weather_paths:
        weather.extend(load_global_hourly_weather(path))
    weather.sort(key=lambda item: item.observed_at)

    operation_ids = frame["flight_id"].astype(str).unique()
    icao24_by_operation = {
        operation_id: operation_id.split("_", 1)[0].lower()
        for operation_id in operation_ids
    }
    aircraft = load_aircraft_metadata_parts(
        aircraft_parts_dir, set(icao24_by_operation.values())
    )

    attempts: list[dict[str, Any]] = []
    for operation_id, operation_frame in frame.groupby("flight_id", sort=True):
        operation_id = str(operation_id)
        for assessment in assess_operation(
            operation_frame,
            operation_id=operation_id,
            reference=reference,
        )["attempts"]:
            interval = assessment["attempt"]
            midpoint = (interval["start_time"] + interval["end_time"]) // 2
            joined = join_latest_prior_weather(
                midpoint, weather, maximum_age_seconds=MAXIMUM_WEATHER_AGE_S
            )
            observation = joined.observation
            runway = assessment["runway_inference"].get("geometry_runway")
            wind = None
            if (
                observation is not None
                and observation.wind_from_direction_deg is not None
                and observation.wind_speed_mps is not None
                and runway in geometry.thresholds
            ):
                wind = runway_relative_wind_components(
                    wind_from_direction_deg=observation.wind_from_direction_deg,
                    wind_speed_mps=observation.wind_speed_mps,
                    runway_true_bearing_deg=geometry.thresholds[runway].true_bearing_deg,
                )
            metadata = aircraft.get(icao24_by_operation[operation_id], {})
            path = next(
                (
                    criterion
                    for criterion in assessment.get("criteria", [])
                    if criterion["name"] == "barometric_path_proxy"
                ),
                None,
            )
            attempts.append({
                "status": assessment["status"],
                "weather_matched": observation is not None,
                "weather_age_s": joined.age_seconds,
                "weather_missing_reasons": joined.missing_reasons,
                "qnh_available": observation is not None and observation.qnh_hpa is not None,
                "qnh_cross_check_matches": (
                    observation.qnh_cross_check_matches if observation is not None else None
                ),
                "wind_speed_available": (
                    observation is not None and observation.wind_speed_mps is not None
                ),
                "wind_direction_available": (
                    observation is not None
                    and observation.wind_from_direction_deg is not None
                ),
                "wind_components_available": wind is not None,
                "headwind_mps": wind.headwind_mps if wind is not None else None,
                "crosswind_mps": (
                    abs(wind.crosswind_from_right_mps) if wind is not None else None
                ),
                "aircraft_metadata_available": bool(metadata),
                "typecode": (metadata.get("typecode") or "").strip().upper() or None,
                "category": (metadata.get("categoryDescription") or "").strip() or None,
                "barometric_path_currently_observed": (
                    path is not None and path["status"] != "not_observed"
                ),
            })

    total = len(attempts)
    qnh = sum(item["qnh_available"] for item in attempts)
    weather_matches = sum(item["weather_matched"] for item in attempts)
    wind_direction = sum(item["wind_direction_available"] for item in attempts)
    typecodes = sum(item["typecode"] is not None for item in attempts)
    current_path = sum(item["barometric_path_currently_observed"] for item in attempts)
    return {
        "schema_version": "approach_context_audit_v1",
        "cohort": cohort,
        "source_sha256": source_digest,
        "reference_sha256": reference["artifact_sha256"],
        "weather_source_sha256": {
            path.name: file_sha256(path) for path in weather_paths
        },
        "aircraft_metadata_sha256": _logical_parts_sha256(aircraft_parts_dir),
        "maximum_weather_age_s": MAXIMUM_WEATHER_AGE_S,
        "operations": int(frame["flight_id"].nunique()),
        "attempts": total,
        "status_counts": _count(item["status"] for item in attempts),
        "coverage": {
            "weather_match_rate": _rate(weather_matches, total),
            "qnh_rate": _rate(qnh, total),
            "wind_speed_rate": _rate(
                sum(item["wind_speed_available"] for item in attempts), total
            ),
            "wind_direction_rate": _rate(wind_direction, total),
            "wind_components_rate": _rate(
                sum(item["wind_components_available"] for item in attempts), total
            ),
            "aircraft_metadata_rate": _rate(
                sum(item["aircraft_metadata_available"] for item in attempts), total
            ),
            "aircraft_typecode_rate": _rate(typecodes, total),
            "barometric_path_current_rate": _rate(current_path, total),
            "barometric_path_qnh_context_upper_bound_rate": _rate(qnh, total),
        },
        "weather_missing_reason_counts": _count(
            reason for item in attempts for reason in item["weather_missing_reasons"]
        ),
        "top_typecodes": Counter(
            item["typecode"] for item in attempts if item["typecode"]
        ).most_common(20),
        "availability_gates": {
            "weather_qnh": "passed" if _rate(qnh, total) is not None and qnh / total >= 0.95 else "failed",
            "wind_direction": "passed" if _rate(wind_direction, total) is not None and wind_direction / total >= 0.80 else "failed",
            "aircraft_type": "passed" if _rate(typecodes, total) is not None and typecodes / total >= 0.80 else "failed",
            "aircraft_configuration": "failed_no_observed_source",
            "actual_mass": "failed_no_observed_source",
            "atc_clearance": "failed_no_observed_source",
        },
        "interpretation_limits": [
            "QNH correction is a first-order pressure-altitude proxy, not geometric or radio altitude.",
            "OpenSky metadata is a current registry snapshot and can mismatch historical aircraft identity.",
            "Wind and type coverage do not establish that either feature improves review precision.",
            "Configuration, actual mass, and ATC clearance are not present in these public observations.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=["train", "val", "2025"], required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source-2025", type=Path, required=True)
    parser.add_argument("--weather-dir", type=Path, required=True)
    parser.add_argument("--aircraft-parts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_context(
        cohort=args.cohort,
        model_dir=args.model_dir,
        source_2025=args.source_2025,
        weather_dir=args.weather_dir,
        aircraft_parts_dir=args.aircraft_parts_dir,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
