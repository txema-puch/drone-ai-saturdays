import numpy as np

from sadar_research.trajectory_anomaly.pipeline.precompute import (
    select_case_indices,
    valid_normal_step_scores,
)


def test_valid_normal_step_scores_uses_boolean_mask_not_prefix_length():
    steps = np.array([[1.0, 0.0, 3.0, 0.0], [9.0, 9.0, 9.0, 9.0]])
    masks = np.array([[1.0, 0.0, 1.0, 0.0], [1.0, 1.0, 1.0, 1.0]])
    segment_ids = np.array(["normal#1", "anomaly#1"])

    result = valid_normal_step_scores(steps, masks, segment_ids, {"anomaly#1"})

    assert result.tolist() == [1.0, 3.0]


def test_case_selection_counts_top_normal_cases_after_adding_all_anomalies():
    segment_ids = np.array(["anomaly#1", "normal-a#1", "normal-b#1", "normal-c#1"])
    scores = np.array([100.0, 30.0, 20.0, 10.0])

    result = select_case_indices(
        segment_ids,
        scores,
        {"anomaly#1"},
        n_top_normal=2,
        n_typical=0,
    )

    assert result == {0, 1, 2}
