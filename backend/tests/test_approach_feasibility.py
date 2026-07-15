import json

import pandas as pd
import pytest

from backend.scripts.approach_feasibility import run


def test_feasibility_refuses_burned_test_fold(tmp_path):
    with pytest.raises(ValueError, match="test is burned"):
        run(tmp_path, fold="test")


def test_feasibility_reports_only_requested_development_fold(tmp_path, monkeypatch):
    (tmp_path / "split_ids.json").write_text(json.dumps({
        "train": ["a_1#1"], "val": ["b_2#1"], "test": ["c_3#1"]
    }))
    rows = pd.DataFrame({
        "flight_id": ["a_1", "b_2", "c_3"],
        "segment_id": ["a_1#1", "b_2#1", "c_3#1"],
    })
    monkeypatch.setattr(pd, "read_parquet", lambda _path: rows)
    monkeypatch.setattr(
        "backend.scripts.approach_feasibility.assess_operation",
        lambda frame, operation_id, reference: {"attempts": [{
                "operation_id": f"{operation_id}:attempt-1",
                "status": "not_assessable",
                "reasons": ["fixture"],
                "runway_inference": {"direction": None, "specificity": "unknown", "runway": None},
                "criteria": [],
            }]},
    )
    report = run(tmp_path, fold="train")
    assert report["operations_considered"] == 1
    assert report["examples"][0]["operation_id"] == "a_1:attempt-1"
