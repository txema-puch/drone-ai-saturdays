"""Fit the immutable ADS-B-only approach reference from the historical train fold."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from sadar.approach.assessment import assess_approach, extract_approach_attempts
from sadar.approach.reference import dumps_reference, fit_reference


def build_reference(model_dir: Path) -> tuple[dict, dict]:
    split_path = model_dir / "split_ids.json"
    split_bytes = split_path.read_bytes()
    ids = json.loads(split_bytes)
    allowed_segments = set(ids["train"])
    clean = pd.read_parquet(model_dir / "clean_df.parquet")
    train = clean.loc[clean["segment_id"].isin(allowed_segments)].copy()

    attempts = []
    rejected: dict[str, int] = {}
    for operation_id, operation in train.groupby("flight_id", sort=True):
        for number, frame in enumerate(extract_approach_attempts(operation), start=1):
            assessment = assess_approach(frame, operation_id=f"{operation_id}:attempt-{number}")
            reason = None
            if assessment["status"] == "not_assessable":
                reason = "quality_or_coverage"
            elif assessment["attempt"]["outcome"] in {"go_around", "incomplete"}:
                reason = assessment["attempt"]["outcome"]
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            attempts.append({
                "attempt_id": assessment["operation_id"],
                "frame": frame,
                "direction": assessment["runway_inference"]["direction"],
                "geometry_runway": assessment["runway_inference"]["geometry_runway"],
                "speed_class": (
                    str(frame["speed_class"].dropna().iloc[0])
                    if "speed_class" in frame and frame["speed_class"].notna().any()
                    else "unknown"
                ),
            })

    cohort = {
        "source": "OpenSky scientific Monday historical clean observations",
        "years": [2017, 2018],
        "split_ids_sha256": hashlib.sha256(split_bytes).hexdigest(),
        "candidate_train_segments": len(allowed_segments),
        "selection": "terminal non-go-around attempts passing observed-row quality gates",
    }
    reference = fit_reference(attempts, fit_fold="train", cohort=cohort)
    report = {
        "candidate_operations": int(train["flight_id"].nunique()),
        "eligible_attempts": len(attempts),
        "accepted_attempts": reference["accepted_attempts"],
        "empty_reference_attempts": len(attempts) - reference["accepted_attempts"],
        "rejected_attempts": rejected,
        "reference_cells": len(reference["entries"]),
        "reference_sha256": reference["artifact_sha256"],
        "diagnostics": reference["diagnostics"],
    }
    return reference, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reference, report = build_reference(args.model_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps_reference(reference))
    encoded_report = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded_report)
    else:
        print(encoded_report, end="")


if __name__ == "__main__":
    main()
