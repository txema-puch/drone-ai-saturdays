"""Run the single precommitted schema-v3 assessment on the sealed 2026 holdout."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.approach_reference import REFERENCE_PATH, load_approach_reference
from backend.scripts.audit_approach_dataset import file_sha256, summarize_frame
from backend.serve.approach_release import load_release_directory


REPO = Path(__file__).resolve().parents[2]
SEALED_PATH = REPO / "data/raw/lemd_20260310_to_20260314__snapshot_2026-05-11.parquet"
SEALED_SHA256 = "16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899"
DEFAULT_RELEASE = REPO / "backend/models/sadar_approach_v3"
DEFAULT_OUTPUT = (
    REPO
    / "backend/docs/ml/iterations/approach-screening/artifacts/2026-holdout-burn.json"
)


def _commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def burn(
    *,
    input_path: Path = SEALED_PATH,
    release_dir: Path = DEFAULT_RELEASE,
    reference_path: Path = REFERENCE_PATH,
) -> dict[str, Any]:
    """Verify every frozen identity before the first parquet read, then assess once."""
    input_digest = file_sha256(input_path)
    if input_digest != SEALED_SHA256:
        raise ValueError("holdout path does not match the precommitted sealed digest")
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
        "source_commit": _commit(),
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
    parser.add_argument("--input", type=Path, default=SEALED_PATH)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--reference", type=Path, default=REFERENCE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = burn(
        input_path=args.input,
        release_dir=args.release,
        reference_path=args.reference,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
