"""Tests for the offline analysis-report helpers (`backend/research/src/sadar_research/trajectory_anomaly/evaluation/report.py`).

Pure / deterministic only — no live LLM call (the live prompt-quality check lives in the
opt-in `serve.report_eval`). Covers the data-quality classifier and the bounded context
builder, the two pieces that decide what the model is told.

  ★★ classify maps the flags to the D-014 taxonomy (terminal / truncated / overflight /
     neighbour / real-anomaly).
  ★★ build_context is bounded (channel summaries, not full arrays) and ranks attribution.
"""

from __future__ import annotations

from sadar_research.trajectory_anomaly.evaluation import report as rpt


def _case(**kw) -> dict:
    base = dict(
        segment_id="abc123_1580000000#1", label="normal", score=0.5, pct=90.0,
        band="elevated", anomalous=True, valid_steps=50, n_steps=50, truncated=False,
        terminal_op=True, n_siblings=1, assessment_state="reviewable",
        behavioral_verdict="reviewable", review_lane="behavioral", data_quality_flags=[],
        observed_fraction=1.0, max_altitude_jump_m=100.0,
        max_implied_vertical_rate_mps=10.0, max_implied_ground_speed_mps=80.0,
        feature_attribution={"lat": 0.1, "velocity": 0.9, "baroaltitude": 0.4},
        step_scores=[0.1, 0.9, 0.5],
        channels={"baroaltitude": [600.0, 500.0, 400.0], "velocity": [70.0, 66.0, 66.0],
                  "vertrate": [-3.0, 0.0, 0.0], "dist_to_runway_m": [4000.0, 1000.0, 200.0]},
    )
    base.update(kw)
    return base


def test_classify_terminal_op():
    assert "analyst review" in rpt.classify(_case())


def test_classify_truncated():
    case = _case(
        truncated=True, terminal_op=False, assessment_state="coverage_limited",
        behavioral_verdict="not_assessable", review_lane="coverage",
        data_quality_flags=["terminal_phase_not_scored"],
    )
    assert "terminal phase" in rpt.classify(case)


def test_classify_overflight_vs_neighbour():
    case = _case(
        assessment_state="data_quality_conflict", behavioral_verdict="not_assessable",
        review_lane="data_quality", data_quality_flags=["altitude_rate_conflict"],
        max_implied_vertical_rate_mps=1093.4,
    )
    text = rpt.classify(case)
    assert "Physically inconsistent" in text
    assert "cause is unassigned" in text


def test_classify_real_anomaly():
    assert "analyst review" in rpt.classify(_case(label="go_around"))
    assert "analyst review" in rpt.classify(_case(label="emergency"))


def test_guard_cached_report_abstains_and_removes_unsupported_verdict():
    legacy = "Genuine LEMD anomaly, not a data artifact.\nReading\nSomething unusual."
    conflict = _case(
        assessment_state="data_quality_conflict", behavioral_verdict="not_assessable",
        review_lane="data_quality", data_quality_flags=["altitude_rate_conflict"],
        max_implied_vertical_rate_mps=1093.4,
    )
    guarded = rpt.guard_cached_report(legacy, conflict, 0.222)
    assert "behavioral conformance is not assessable" in guarded
    assert "cause is unassigned" in guarded
    assert "Genuine LEMD anomaly" not in guarded

    reviewable = rpt.guard_cached_report(legacy, _case(), 0.222)
    assert "behavioral interpretation requires analyst review" in reviewable
    assert "Genuine LEMD anomaly" not in reviewable


def test_guard_cached_report_rejects_prohibited_claims():
    for claim in rpt.PROHIBITED_CLAIMS:
        report = f"Reviewable evidence. Possible {claim} activity."
        assert rpt.guard_cached_report(report, _case(), 0.222) is None


def test_build_context_ranks_and_bounds():
    ctx = rpt.build_context(_case(), threshold=0.222, step_threshold=0.9)
    # attribution ranked descending
    keys = list(ctx["feature_attribution_ranked"].keys())
    assert keys[0] == "velocity"
    # channels are SUMMARIES (start/end/min/max), never the raw arrays
    alt = ctx["channel_summaries"]["baroaltitude"]
    assert set(alt) == {"start", "end", "min", "max"}
    assert alt["min"] == 400.0 and alt["max"] == 600.0
    # the authoritative data-quality label is carried through
    assert "data_quality" in ctx and ctx["threshold"] == 0.222
    assert ctx["per_step_RE_peak"] == 0.9


def test_prompt_fingerprint_changes_with_model():
    assert rpt.prompt_fingerprint("a") != rpt.prompt_fingerprint("b")
    assert len(rpt.prompt_fingerprint("claude-sonnet-4-6")) == 8
