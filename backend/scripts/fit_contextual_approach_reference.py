"""Fit the train-only, aircraft-type-conditioned contextual reference."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from backend.core.approach import assess_approach, extract_approach_attempts
from backend.core.approach_context import load_aircraft_metadata_parts
from backend.core.approach_reference import dumps_reference, fit_reference
from backend.scripts.audit_approach_context import _logical_parts_sha256


REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = REPO / "backend/models/phase6"
DEFAULT_AIRCRAFT_PARTS = REPO / "data/raw/aircraft_metadata"
DEFAULT_OUTPUT = (
    REPO / "backend/core/resources/lemd_approach_context_reference_v1.json"
)


def build_contextual_reference(
    *,
    model_dir: Path = DEFAULT_MODEL_DIR,
    aircraft_parts_dir: Path = DEFAULT_AIRCRAFT_PARTS,
) -> tuple[dict, dict]:
    split_path = model_dir / "split_ids.json"
    split_bytes = split_path.read_bytes()
    split_ids = json.loads(split_bytes)
    allowed_segments = set(split_ids["train"])
    clean_path = model_dir / "clean_df.parquet"
    clean = pd.read_parquet(clean_path)
    train = clean.loc[clean["segment_id"].isin(allowed_segments)].copy()
    icao24 = {
        str(operation_id): str(operation_id).split("_", 1)[0].lower()
        for operation_id in train["flight_id"].astype(str).unique()
    }
    metadata = load_aircraft_metadata_parts(aircraft_parts_dir, set(icao24.values()))

    attempts = []
    rejected: Counter[str] = Counter()
    typecodes: Counter[str] = Counter()
    for operation_id, operation in train.groupby("flight_id", sort=True):
        operation_id = str(operation_id)
        typecode = (
            metadata.get(icao24[operation_id], {}).get("typecode") or ""
        ).strip().upper() or "unknown"
        for number, frame in enumerate(extract_approach_attempts(operation), start=1):
            assessment = assess_approach(
                frame, operation_id=f"{operation_id}:attempt-{number}"
            )
            reason = None
            if assessment["status"] == "not_assessable":
                reason = "quality_or_coverage"
            elif assessment["attempt"]["outcome"] in {"go_around", "incomplete"}:
                reason = assessment["attempt"]["outcome"]
            if reason:
                rejected[reason] += 1
                continue
            attempts.append({
                "attempt_id": assessment["operation_id"],
                "frame": frame,
                "direction": assessment["runway_inference"]["direction"],
                "geometry_runway": assessment["runway_inference"]["geometry_runway"],
                "speed_class": typecode,
            })
            typecodes[typecode] += 1

    clean_digest = hashlib.sha256(clean_path.read_bytes()).hexdigest()
    metadata_digest = _logical_parts_sha256(aircraft_parts_dir)
    cohort = {
        "source": "OpenSky scientific Monday historical clean observations",
        "years": [2017, 2018],
        "split_ids_sha256": hashlib.sha256(split_bytes).hexdigest(),
        "clean_df_sha256": clean_digest,
        "aircraft_metadata_sha256": metadata_digest,
        "aircraft_metadata_temporal_warning": (
            "Current OpenSky registry metadata may not represent historical identity."
        ),
        "selection": "terminal non-go-around attempts passing observed-row quality gates",
    }
    reference = fit_reference(attempts, fit_fold="train", cohort=cohort)
    exact_entries = [
        item for item in reference["entries"] if item["speed_class"] != "unknown"
    ]
    report = {
        "schema_version": "approach_context_reference_fit_v1",
        "candidate_operations": int(train["flight_id"].nunique()),
        "eligible_attempts": len(attempts),
        "accepted_attempts": reference["accepted_attempts"],
        "rejected_attempts": dict(sorted(rejected.items())),
        "typed_attempt_rate": round(
            sum(value for key, value in typecodes.items() if key != "unknown")
            / len(attempts),
            4,
        ) if attempts else None,
        "top_typecodes": typecodes.most_common(20),
        "reference_cells": len(reference["entries"]),
        "exact_type_cells": len(exact_entries),
        "exact_typecodes": sorted({item["speed_class"] for item in exact_entries}),
        "unknown_fallback_cells": sum(
            item["speed_class"] == "unknown" for item in reference["entries"]
        ),
        "reference_sha256": reference["artifact_sha256"],
        "diagnostics": reference["diagnostics"],
    }
    return reference, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument(
        "--aircraft-parts-dir", type=Path, default=DEFAULT_AIRCRAFT_PARTS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reference, report = build_contextual_reference(
        model_dir=args.model_dir,
        aircraft_parts_dir=args.aircraft_parts_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps_reference(reference))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
