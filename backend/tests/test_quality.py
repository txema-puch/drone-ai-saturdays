"""Deployment-only assessment guardrails; frozen model behavior is not touched."""

import pandas as pd

from sadar_research.trajectory_anomaly.evaluation.quality import assess_segment, assessment_copy


def _segment(altitudes, *, latitudes=None, longitudes=None):
    n = len(altitudes)
    return pd.DataFrame({
        "time": [i * 10 for i in range(n)],
        "lat": latitudes or [40.48] * n,
        "lon": longitudes or [-3.56] * n,
        "baroaltitude": altitudes,
    })


def test_altitude_jump_abstains_without_assigning_a_cause():
    assessment = assess_segment(
        _segment([648.0, 11_582.0, 700.0]),
        valid_steps=3, n_steps=3, truncated=False, terminal_op=True,
    )
    assert assessment["assessment_state"] == "insufficient_data"
    # With enough observed context, the same transition is a data-quality conflict.
    assessment = assess_segment(
        _segment([648.0] * 30 + [11_582.0]),
        valid_steps=31, n_steps=31, truncated=False, terminal_op=True,
    )
    assert assessment["assessment_state"] == "data_quality_conflict"
    assert "altitude_rate_conflict" in assessment["data_quality_flags"]
    assert assessment["behavioral_verdict"] == "not_assessable"
    assert "cause is unassigned" in assessment_copy(assessment)


def test_missing_heavy_segment_is_insufficient_not_normal():
    assessment = assess_segment(
        _segment([10_000.0] * 31),
        valid_steps=2, n_steps=31, truncated=False, terminal_op=False,
    )
    assert assessment["assessment_state"] == "insufficient_data"
    assert assessment["review_lane"] == "data_quality"
    assert assessment["observed_fraction"] == 0.0645


def test_truncated_nonterminal_segment_is_coverage_limited():
    assessment = assess_segment(
        _segment([7900.0 - i * 10 for i in range(260)]),
        valid_steps=259, n_steps=381, truncated=True, terminal_op=False,
    )
    assert assessment["assessment_state"] == "coverage_limited"
    assert assessment["data_quality_flags"] == ["terminal_phase_not_scored"]
    assert assessment["review_lane"] == "coverage"


def test_clean_terminal_segment_remains_reviewable():
    assessment = assess_segment(
        _segment([1000.0 - i * 5 for i in range(40)]),
        valid_steps=40, n_steps=40, truncated=False, terminal_op=True,
    )
    assert assessment["assessment_state"] == "reviewable"
    assert assessment["data_quality_flags"] == []
    assert assessment["behavioral_verdict"] == "reviewable"
