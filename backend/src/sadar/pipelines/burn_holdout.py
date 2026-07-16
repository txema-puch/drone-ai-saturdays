"""Run the single precommitted schema-v3 assessment on the sealed 2026 holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from sadar.approach.reference import load_approach_reference
from sadar.pipelines.audit_dataset import file_sha256, summarize_frame
from sadar.releases.approach import load_release_directory


SEALED_SHA256 = "16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899"


def burn(
    *,
    input_path: Path,
    release_dir: Path | None = None,
    reference_path: Path | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Verify every frozen identity before the first parquet read, then assess once."""
    input_digest = file_sha256(input_path)
    if input_digest != SEALED_SHA256:
        raise ValueError("holdout path does not match the precommitted sealed digest")
    if release_dir is None or source_commit is None:
        raise ValueError("release_dir and source_commit are required")
    release = load_release_directory(release_dir)
    reference = load_approach_reference(reference_path)
    contracts = release["manifest"]["contracts"]
    if contracts["reference_sha256"] != reference["artifact_sha256"]:
        raise ValueError("release and holdout evaluator reference identities differ")
    if release["manifest"]["schema_version"] != 3:
        raise ValueError("holdout burn requires the frozen schema-v3 release")

    report = summarize_frame(
        pd.read_parquet(input_path),
        input_sha256=input_digest,
        reference=reference,
    )
    return {
        "schema_version": "approach_holdout_burn_v1",
        "policy": "single_precommitted_transform_no_threshold_tuning",
        "source_commit": source_commit,
        "release_id": release["manifest"]["release_id"],
        "release_source_sha256": release["manifest"]["source"]["input_sha256"],
        "reference_sha256": reference["artifact_sha256"],
        "holdout": report,
        "interpretation_limits": [
            "No independent human review labels are present, so this burn does not estimate precision, recall, AUROC, or safety performance.",
            "Status and workload drift are descriptive checks; holdout results cannot tune the frozen criteria or empirical reference.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = burn(
        input_path=args.input,
        release_dir=args.release,
        reference_path=args.reference,
        source_commit=args.source_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
