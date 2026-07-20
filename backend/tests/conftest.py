"""Explicit synthetic fixtures for product and historical-research tests."""

import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests/ -> backend/ -> repo root

# The archived research application historically read a real-data-derived Hub
# bundle at import time. Mandatory public CI must not need credentials for that
# private audit record, so tests assemble the smallest deterministic synthetic
# bundle that exercises the same API contracts.
_RESEARCH_FIXTURE_TEMP = tempfile.TemporaryDirectory(prefix="sadar-research-test-")
_RESEARCH_FIXTURE_ROOT = Path(_RESEARCH_FIXTURE_TEMP.name)
_RESEARCH_BUNDLE = _RESEARCH_FIXTURE_ROOT / "trajectory-demo"
_RESEARCH_MODELS = _RESEARCH_FIXTURE_ROOT / "trajectory-training"
_RESEARCH_BUNDLE.mkdir()
_RESEARCH_MODELS.mkdir()


def _write_fixture(name: str, value: object) -> None:
    (_RESEARCH_BUNDLE / name).write_text(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    )


_case_id = "c_syntheticfixture"
_case_ref = "CASE-SYNTHETIC"
_operation_ref = "OP-SYNTHETIC-FIXTURE"
_segment_id = "synthetic_fixture#1"
_queue_row = {
    "case_id": _case_id,
    "case_ref": _case_ref,
    "segment_id": _segment_id,
    "operation_ref": _operation_ref,
    "score": 0.2,
    "pct": 50.0,
    "band": "upper-normal",
    "label": "normal",
    "anomalous": False,
    "assessment_state": "reviewable",
    "behavioral_verdict": "reviewable",
    "review_lane": "behavioral",
    "data_quality_flags": [],
}
_write_fixture(
    "manifest.json",
    {
        "schema_version": 2,
        "release_id": "synthetic-test-fixture",
        "threshold": 0.5,
        "step_threshold": 0.4,
        "T": 1,
        "center": {"lat": 40.4936, "lon": -3.5668},
        "step_seconds": 10,
        "n_segments": 1,
        "n_operations": 1,
    },
)
_write_fixture("queue.json", [_queue_row])
_write_fixture(
    "cases.json",
    {
        _case_id: {
            **_queue_row,
            "path": [],
            "reconstructed": [],
            "step_scores": [0.2],
            "valid_steps": 1,
            "n_steps": 1,
            "feature_attribution": [],
            "channels": {},
            "report": None,
        }
    },
)
_write_fixture(
    "metrics.json",
    {"selected_model": "synthetic-test-double", "results": [], "notes": {}},
)

if os.environ.get("SADAR_TEST_USE_EXTERNAL_RESEARCH_ARTIFACTS") != "true":
    os.environ["SADAR_RESEARCH_BUNDLE_DIR"] = str(_RESEARCH_BUNDLE)
    os.environ["SADAR_RESEARCH_MODELS_DIR"] = str(_RESEARCH_MODELS)
os.environ.setdefault("SADAR_FRONTEND_DIR", str(REPO_ROOT / "frontend/dist"))
