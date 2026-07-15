"""Compare contextual and ADS-B-only assessment on development cohorts."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.approach import assess_operation
from backend.core.approach_context import (
    load_aircraft_metadata_parts,
    load_global_hourly_weather,
)
from backend.core.approach_reference import load_approach_reference
from backend.core.contextual_approach import assess_contextual_operation
from backend.scripts.audit_approach_context import (
    AIRCRAFT_PARTS_DIR,
    MODEL_DIR,
    SOURCE_2025,
    WEATHER_DIR,
    _load_frame,
)


REPO = Path(__file__).resolve().parents[2]
CONTEXT_REFERENCE = (
    REPO / "backend/core/resources/lemd_approach_context_reference_v1.json"
)


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _review_rate(items: list[dict[str, Any]]) -> float | None:
    assessable = [item for item in items if item["status"] != "not_assessable"]
    return round(
        sum(item["status"] == "review_required" for item in assessable)
        / len(assessable),
        4,
    ) if assessable else None


def _criterion_counts(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    criteria = [criterion for item in items for criterion in item.get("criteria", [])]
    return {
        name: _counts(
            item["status"] for item in criteria if item["name"] == name
        )
        for name in sorted({item["name"] for item in criteria})
    }


def evaluate(
    *,
    cohort: str,
    model_dir: Path = MODEL_DIR,
    source_2025: Path = SOURCE_2025,
    weather_dir: Path = WEATHER_DIR,
    aircraft_parts_dir: Path = AIRCRAFT_PARTS_DIR,
    context_reference_path: Path = CONTEXT_REFERENCE,
) -> dict[str, Any]:
    if cohort not in {"val", "2025"}:
        raise ValueError("contextual comparison is restricted to val or 2025 development data")
    frame, source_digest = _load_frame(cohort, model_dir, source_2025)
    years = sorted(
        set(pd.to_datetime(frame["time"], unit="s", utc=True).dt.year.astype(int))
    )
    weather = []
    for year in years:
        weather.extend(
            load_global_hourly_weather(weather_dir / f"lemd_isd_{year}.csv")
        )
    weather.sort(key=lambda item: item.observed_at)
    icao24 = {
        str(operation_id): str(operation_id).split("_", 1)[0].lower()
        for operation_id in frame["flight_id"].astype(str).unique()
    }
    metadata = load_aircraft_metadata_parts(aircraft_parts_dir, set(icao24.values()))
    base_reference = load_approach_reference()
    contextual_reference = load_approach_reference(context_reference_path)

    base_attempts: list[dict[str, Any]] = []
    contextual_attempts: list[dict[str, Any]] = []
    transitions: list[str] = []
    for operation_id, operation in frame.groupby("flight_id", sort=True):
        operation_id = str(operation_id)
        base = assess_operation(
            operation,
            operation_id=operation_id,
            reference=base_reference,
        )["attempts"]
        contextual = assess_contextual_operation(
            operation,
            operation_id=operation_id,
            weather=weather,
            aircraft_metadata=metadata.get(icao24[operation_id]),
            reference=contextual_reference,
        )["attempts"]
        if len(base) != len(contextual):
            raise ValueError("context changed attempt reconstruction")
        base_attempts.extend(base)
        contextual_attempts.extend(contextual)
        transitions.extend(
            f"{left['status']}->{right['status']}"
            for left, right in zip(base, contextual)
        )

    paired = list(zip(base_attempts, contextual_attempts))
    exact_reference = 0
    for item in contextual_attempts:
        speed_class = item.get("reference", {}).get("speed_class", "unknown")
        direction = item.get("runway_inference", {}).get("direction")
        if speed_class != "unknown" and any(
            entry["speed_class"] == speed_class and entry["direction"] == direction
            for entry in contextual_reference["entries"]
        ):
            exact_reference += 1
    return {
        "schema_version": "approach_context_comparison_v1",
        "source_commit": _commit(),
        "cohort": cohort,
        "source_sha256": source_digest,
        "base_reference_sha256": base_reference["artifact_sha256"],
        "context_reference_sha256": contextual_reference["artifact_sha256"],
        "attempts": len(paired),
        "base_status_counts": _counts(item["status"] for item in base_attempts),
        "context_status_counts": _counts(
            item["status"] for item in contextual_attempts
        ),
        "status_transition_counts": _counts(transitions),
        "base_review_rate_among_assessable": _review_rate(base_attempts),
        "context_review_rate_among_assessable": _review_rate(contextual_attempts),
        "review_overlap": {
            "both": sum(
                left["status"] == right["status"] == "review_required"
                for left, right in paired
            ),
            "context_only": sum(
                left["status"] != "review_required"
                and right["status"] == "review_required"
                for left, right in paired
            ),
            "base_only": sum(
                left["status"] == "review_required"
                and right["status"] != "review_required"
                for left, right in paired
            ),
        },
        "base_criterion_status_counts": _criterion_counts(base_attempts),
        "context_criterion_status_counts": _criterion_counts(contextual_attempts),
        "context_coverage": {
            "qnh": round(sum(
                item.get("context", {}).get("weather", {}).get("qnh_hpa") is not None
                for item in contextual_attempts
            ) / len(contextual_attempts), 4) if contextual_attempts else None,
            "wind_components": round(sum(
                item.get("context", {}).get("weather", {}).get("headwind_mps") is not None
                for item in contextual_attempts
            ) / len(contextual_attempts), 4) if contextual_attempts else None,
            "aircraft_type": round(sum(
                item.get("context", {}).get("aircraft", {}).get("typecode") is not None
                for item in contextual_attempts
            ) / len(contextual_attempts), 4) if contextual_attempts else None,
            "exact_type_reference": round(
                exact_reference / len(contextual_attempts), 4
            ) if contextual_attempts else None,
        },
        "decision": "not_qualified_no_independent_labels_or_fresh_holdout",
        "interpretation_limits": [
            "Status transitions measure rule/reference behavior, not correctness.",
            "No independent labels exist to estimate precision or incremental analyst value.",
            "The 2026 cohort is already burned and is not accessed by this comparison.",
            "A successor requires another untouched release cohort before qualification.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=["val", "2025"], required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(cohort=args.cohort)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
