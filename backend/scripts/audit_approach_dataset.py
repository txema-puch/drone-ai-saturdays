"""Audit an external approach dataset while enforcing the sealed-holdout firewall."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.approach import assess_operation
from backend.core.approach_reference import validate_reference


SEALED_HOLDOUT_SHA256 = {
    "16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899"
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def summarize_frame(
    frame: pd.DataFrame,
    *,
    input_sha256: str,
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Summarize an already-authorized frame without changing assessment thresholds."""
    validate_reference(reference)
    required = {"flight_id", "time", "lat", "lon"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"dataset missing required columns: {sorted(missing)}")
    operations = [
        assess_operation(group, operation_id=str(operation_id), reference=reference)
        for operation_id, group in frame.groupby("flight_id", sort=True)
    ]
    attempts = [attempt for operation in operations for attempt in operation["attempts"]]
    assessable = [item for item in attempts if item["status"] != "not_assessable"]
    criteria = [criterion for item in attempts for criterion in item.get("criteria", [])]
    return {
        "schema_version": "approach_dataset_audit_v1",
        "input_sha256": input_sha256,
        "reference_sha256": reference["artifact_sha256"],
        "rows": len(frame),
        "operations": int(frame["flight_id"].nunique()),
        "operations_with_attempts": sum(bool(item["attempts"]) for item in operations),
        "attempts": len(attempts),
        "assessable_attempts": len(assessable),
        "abstention_rate": round(
            (len(attempts) - len(assessable)) / len(attempts), 4
        ) if attempts else None,
        "review_rate_among_assessable": round(
            sum(item["status"] == "review_required" for item in assessable) / len(assessable), 4
        ) if assessable else None,
        "status_counts": _counts(item["status"] for item in attempts),
        "outcome_counts": _counts(item["attempt"]["outcome"] for item in attempts),
        "runway_direction_counts": _counts(
            item["runway_inference"].get("direction") or "unknown" for item in attempts
        ),
        "reason_counts": _counts(
            reason for item in attempts for reason in item.get("reasons", [])
        ),
        "channel_advisory_counts": _counts(
            advisory
            for item in attempts
            for advisories in item.get("quality", {}).get("channel_advisories", {}).values()
            for advisory in advisories
        ),
        "criterion_status_counts": {
            name: _counts(item["status"] for item in criteria if item["name"] == name)
            for name in sorted({item["name"] for item in criteria})
        },
    }


def audit_dataset(path: Path, *, reference: dict[str, Any]) -> dict[str, Any]:
    digest = file_sha256(path)
    if digest in SEALED_HOLDOUT_SHA256:
        raise ValueError("refusing to read sealed 2026 holdout before the final burn")
    return summarize_frame(
        pd.read_parquet(path),
        input_sha256=digest,
        reference=reference,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_dataset(args.input, reference=json.loads(args.reference.read_text()))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
