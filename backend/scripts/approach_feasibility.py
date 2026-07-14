"""Measure approach-screening feasibility without touching the burned test fold.

The report is descriptive. It does not tune thresholds and refuses the historical
``test`` fold by construction. Use the 2026 holdout only through the later burn script.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.approach import assess_approach


REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = REPO / "backend" / "models" / "phase6"
ALLOWED_FOLDS = {"train", "val"}


def _counter(items) -> dict[str, int]:
    return dict(sorted(Counter(items).items()))


def run(model_dir: Path, *, fold: str, limit: int | None = None) -> dict[str, Any]:
    if fold not in ALLOWED_FOLDS:
        raise ValueError(f"fold must be one of {sorted(ALLOWED_FOLDS)}; test is burned")
    ids = json.loads((model_dir / "split_ids.json").read_text())
    allowed_segments = set(ids[fold])
    clean = pd.read_parquet(model_dir / "clean_df.parquet")
    eligible_operations = sorted(
        clean.loc[clean["segment_id"].isin(allowed_segments), "flight_id"].astype(str).unique()
    )
    if limit is not None:
        eligible_operations = eligible_operations[:limit]
    selected = clean.loc[clean["flight_id"].astype(str).isin(eligible_operations)].copy()

    assessments = []
    for operation_id, frame in selected.groupby("flight_id", sort=True):
        assessments.append(assess_approach(frame, operation_id=str(operation_id)))

    criteria = [criterion for item in assessments for criterion in item.get("criteria", [])]
    report = {
        "schema_version": "approach_feasibility_v1",
        "fold": fold,
        "source": str(model_dir.relative_to(REPO) if model_dir.is_relative_to(REPO) else model_dir),
        "operations_considered": len(eligible_operations),
        "operations_assessed": len(assessments),
        "status_counts": _counter(item["status"] for item in assessments),
        "runway_direction_counts": _counter(
            item["runway_inference"].get("direction") or "unknown" for item in assessments
        ),
        "runway_specificity_counts": _counter(
            item["runway_inference"]["specificity"] for item in assessments
        ),
        "reason_counts": _counter(
            reason for item in assessments for reason in item.get("reasons", [])
        ),
        "altitude_reference_counts": _counter(
            item.get("altitude_reference", {}).get("source", "unavailable")
            for item in assessments
        ),
        "criterion_status_counts": {
            name: _counter(
                criterion["status"] for criterion in criteria if criterion["name"] == name
            )
            for name in sorted({criterion["name"] for criterion in criteria})
        },
        "examples": [
            {
                "operation_id": item["operation_id"],
                "status": item["status"],
                "runway": item["runway_inference"].get("runway"),
                "reasons": item.get("reasons", []),
                "failed_criteria": item.get("failed_criteria", []),
            }
            for item in assessments[:25]
        ],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--fold", choices=sorted(ALLOWED_FOLDS), default="train")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.model_dir, fold=args.fold, limit=args.limit)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
