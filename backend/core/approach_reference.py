"""Train-only empirical reference envelopes for observed LEMD approaches."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.core.approach_geometry import GeometryCatalog, load_lemd_geometry, runway_relative


REFERENCE_SCHEMA_VERSION = "approach_reference_v1"
REFERENCE_PATH = Path(__file__).with_name("resources") / "lemd_approach_reference_v1.json"
DISTANCE_BINS_M = (0.0, 1_500.0, 3_000.0, 6_000.0, 10_000.0, 20_000.0)
MINIMUM_ATTEMPTS = 20
MINIMUM_SAMPLES = 100


def _observed(frame: pd.DataFrame, channel: str) -> np.ndarray:
    valid = frame[channel].notna().to_numpy(copy=True) if channel in frame else np.zeros(len(frame), dtype=bool)
    mask = f"{channel}_missing"
    if mask in frame:
        valid &= ~frame[mask].fillna(True).astype(bool).to_numpy()
    return valid


def distance_bin(distance_m: float) -> str | None:
    for lower, upper in zip(DISTANCE_BINS_M[:-1], DISTANCE_BINS_M[1:]):
        if lower <= distance_m < upper:
            return f"{int(lower)}-{int(upper)}"
    return None


def _canonical_bytes(reference: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in reference.items() if key != "artifact_sha256"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def reference_digest(reference: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(reference)).hexdigest()


def validate_reference(reference: dict[str, Any]) -> None:
    if reference.get("schema_version") != REFERENCE_SCHEMA_VERSION:
        raise ValueError("unsupported approach reference schema")
    if reference.get("fit_fold") != "train":
        raise ValueError("approach reference must be fit on train only")
    if reference.get("artifact_sha256") != reference_digest(reference):
        raise ValueError("approach reference digest mismatch")
    for entry in reference.get("entries", []):
        if not entry["speed_lower_mps"] <= entry["speed_upper_mps"]:
            raise ValueError("invalid speed reference bounds")
        if not entry["vertical_rate_lower_mps"] <= entry["vertical_rate_upper_mps"]:
            raise ValueError("invalid vertical-rate reference bounds")


def fit_reference(
    attempts: Iterable[dict[str, Any]],
    *,
    fit_fold: str,
    cohort: dict[str, Any],
    geometry: GeometryCatalog | None = None,
    minimum_attempts: int = MINIMUM_ATTEMPTS,
    minimum_samples: int = MINIMUM_SAMPLES,
    include_unknown_fallback: bool = True,
) -> dict[str, Any]:
    """Fit robust per-distance envelopes; hard-fail on any non-train fold."""
    if fit_fold != "train":
        raise ValueError("empirical reference fitting is restricted to the train fold")
    geometry = geometry or load_lemd_geometry()
    rows: list[dict[str, Any]] = []
    diagnostics: dict[str, dict[str, int]] = {"year": {}, "direction": {}, "speed_class": {}}
    accepted_attempts = 0
    for item in attempts:
        frame = item["frame"]
        direction = str(item["direction"])
        runway_name = str(item["geometry_runway"])
        speed_class = str(item.get("speed_class") or "unknown")
        attempt_id = str(item["attempt_id"])
        relative = runway_relative(frame["lat"], frame["lon"], geometry.thresholds[runway_name])
        speed_valid = _observed(frame, "velocity")
        vertical_valid = _observed(frame, "vertrate")
        year = datetime.fromtimestamp(int(frame["time"].iloc[0]), tz=timezone.utc).year
        contributed = False
        for index in range(len(frame)):
            bin_name = distance_bin(float(max(relative.along_track_m[index], 0.0)))
            if bin_name is None or relative.along_track_m[index] < 0:
                continue
            speed = float(frame.iloc[index]["velocity"]) if speed_valid[index] else np.nan
            vertical = float(frame.iloc[index]["vertrate"]) if vertical_valid[index] else np.nan
            if not np.isfinite(speed) and not np.isfinite(vertical):
                continue
            classes = [speed_class]
            if include_unknown_fallback and speed_class != "unknown":
                classes.append("unknown")
            for reference_class in classes:
                rows.append({
                    "attempt_id": attempt_id,
                    "year": year,
                    "direction": direction,
                    "speed_class": reference_class,
                    "distance_bin_m": bin_name,
                    "speed_mps": speed,
                    "vertical_rate_mps": vertical,
                })
            contributed = True
        if contributed:
            accepted_attempts += 1
            for key, value in (("year", str(year)), ("direction", direction), ("speed_class", speed_class)):
                diagnostics[key][value] = diagnostics[key].get(value, 0) + 1

    table = pd.DataFrame(rows)
    entries: list[dict[str, Any]] = []
    year_cells: list[dict[str, Any]] = []
    if not table.empty:
        groups = table.groupby(["direction", "speed_class", "distance_bin_m"], sort=True)
        for (direction, speed_class, bin_name), group in groups:
            attempt_count = int(group["attempt_id"].nunique())
            speed = group["speed_mps"].dropna().to_numpy(dtype="float64")
            vertical = group["vertical_rate_mps"].dropna().to_numpy(dtype="float64")
            if attempt_count < minimum_attempts or len(speed) < minimum_samples or len(vertical) < minimum_samples:
                continue
            entries.append({
                "direction": direction,
                "speed_class": speed_class,
                "distance_bin_m": bin_name,
                "attempt_count": attempt_count,
                "speed_sample_count": int(len(speed)),
                "vertical_rate_sample_count": int(len(vertical)),
                "speed_lower_mps": round(float(np.quantile(speed, 0.01)), 4),
                "speed_upper_mps": round(float(np.quantile(speed, 0.99)), 4),
                "vertical_rate_lower_mps": round(float(np.quantile(vertical, 0.01)), 4),
                "vertical_rate_upper_mps": round(float(np.quantile(vertical, 0.99)), 4),
            })
        year_table = table.loc[table["speed_class"] == "unknown"]
        year_groups = year_table.groupby(["year", "direction", "distance_bin_m"], sort=True)
        for (year, direction, bin_name), group in year_groups:
            attempt_count = int(group["attempt_id"].nunique())
            speed = group["speed_mps"].dropna().to_numpy(dtype="float64")
            vertical = group["vertical_rate_mps"].dropna().to_numpy(dtype="float64")
            if attempt_count < minimum_attempts or not len(speed) or not len(vertical):
                continue
            year_cells.append({
                "year": int(year),
                "direction": direction,
                "distance_bin_m": bin_name,
                "attempt_count": attempt_count,
                "speed_median_mps": round(float(np.median(speed)), 4),
                "vertical_rate_median_mps": round(float(np.median(vertical)), 4),
            })

    comparisons = []
    for direction in sorted({item["direction"] for item in year_cells}):
        for bin_name in sorted({item["distance_bin_m"] for item in year_cells}):
            cells = [
                item for item in year_cells
                if item["direction"] == direction and item["distance_bin_m"] == bin_name
            ]
            envelope = next((
                item for item in entries
                if item["direction"] == direction
                and item["speed_class"] == "unknown"
                and item["distance_bin_m"] == bin_name
            ), None)
            if len(cells) < 2 or envelope is None:
                continue
            speed_width = envelope["speed_upper_mps"] - envelope["speed_lower_mps"]
            vertical_width = envelope["vertical_rate_upper_mps"] - envelope["vertical_rate_lower_mps"]
            comparisons.append({
                "direction": direction,
                "distance_bin_m": bin_name,
                "years": [item["year"] for item in cells],
                "speed_median_shift_fraction": round(
                    (max(item["speed_median_mps"] for item in cells) - min(item["speed_median_mps"] for item in cells))
                    / speed_width, 4,
                ) if speed_width else 0.0,
                "vertical_rate_median_shift_fraction": round(
                    (max(item["vertical_rate_median_mps"] for item in cells) - min(item["vertical_rate_median_mps"] for item in cells))
                    / vertical_width, 4,
                ) if vertical_width else 0.0,
            })
    maximum_shift = max(
        (max(item["speed_median_shift_fraction"], item["vertical_rate_median_shift_fraction"])
         for item in comparisons),
        default=None,
    )
    reference: dict[str, Any] = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "fit_fold": fit_fold,
        "cohort": cohort,
        "distance_bins_m": list(DISTANCE_BINS_M),
        "quantiles": [0.01, 0.99],
        "minimum_attempts": minimum_attempts,
        "minimum_samples": minimum_samples,
        "accepted_attempts": accepted_attempts,
        "diagnostics": diagnostics,
        "stratification": {
            "calendar_year": {
                "status": "pass" if maximum_shift is not None and maximum_shift <= 0.5 else "review",
                "maximum_median_shift_fraction_of_reference_width": maximum_shift,
                "acceptance_limit": 0.5,
                "cells": year_cells,
                "comparisons": comparisons,
            },
            "collection_source": {
                "status": "single_source_only",
                "note": "Historical fit contains one OpenSky collection product; 2025 is audited separately.",
            },
            "fleet": ({
                "status": "typecode_conditioned_with_unknown_fallback",
                "note": "Eligible exact typecode cells are retained; every attempt also contributes to an unknown-class fallback.",
            } if any(key != "unknown" for key in diagnostics["speed_class"]) else {
                "status": "unavailable",
                "note": "No aircraft type field exists in the historical fit artifact; speed_class is explicit unknown.",
            }),
        },
        "entries": entries,
    }
    reference["artifact_sha256"] = reference_digest(reference)
    validate_reference(reference)
    return reference


def lookup_reference(
    reference: dict[str, Any],
    *,
    direction: str,
    speed_class: str,
    along_track_m: float,
) -> dict[str, Any] | None:
    bin_name = distance_bin(along_track_m)
    if bin_name is None:
        return None
    candidates = [
        entry for entry in reference["entries"]
        if entry["direction"] == direction and entry["distance_bin_m"] == bin_name
    ]
    exact = next((entry for entry in candidates if entry["speed_class"] == speed_class), None)
    if exact:
        return {**exact, "fallback": "exact"}
    unknown = next((entry for entry in candidates if entry["speed_class"] == "unknown"), None)
    return {**unknown, "fallback": "unknown_speed_class"} if unknown else None


def dumps_reference(reference: dict[str, Any]) -> str:
    validate_reference(reference)
    return json.dumps(reference, indent=2, sort_keys=True) + "\n"


@lru_cache(maxsize=1)
def load_approach_reference(path: str | Path = REFERENCE_PATH) -> dict[str, Any]:
    reference = json.loads(Path(path).read_text())
    validate_reference(reference)
    return reference
