"""Focused tests for stable references and operation-level aggregation."""

from backend.serve.operations import annotate_segment_refs, build_operation_summaries


def _segment(id_: int, segment_id: str, **overrides) -> dict:
    row = {
        "id": id_,
        "segment_id": segment_id,
        "score": 0.1,
        "pct": 25.0,
        "anomalous": False,
        "label": "normal",
        "terminal_op": True,
        "truncated": False,
    }
    row.update(overrides)
    return row


def test_segment_and_operation_refs_do_not_depend_on_visible_order():
    rows = annotate_segment_refs([
        _segment(4238, "502ce6_1543855510#1"),
        _segment(99, "abcdef_1580731000#1"),
    ])
    assert rows[0]["case_ref"] == "CASE-4238"
    assert rows[0]["operation_ref"] == "OP-502CE6-1543855510"
    assert annotate_segment_refs(list(reversed(rows)))[1]["case_ref"] == "CASE-4238"


def test_operation_uses_worst_segment_and_never_sums_scores():
    rows = annotate_segment_refs([
        _segment(
            4238, "502ce6_1543855510#1", score=0.8, pct=99.0, anomalous=True,
            label="go_around",
        ),
        _segment(
            4239, "502ce6_1543855510#2", score=0.7, pct=97.0, anomalous=True,
            terminal_op=False, truncated=True,
        ),
    ])
    operation = build_operation_summaries(rows)[0]
    assert operation["segment_count"] == 2
    assert operation["flagged_segment_count"] == 2
    assert operation["worst_score"] == 0.8
    assert operation["worst_score"] != sum(row["score"] for row in rows)
    assert operation["worst_case_ref"] == "CASE-4238"
    assert operation["labels_seen"] == ["go_around", "normal"]
    assert operation["has_confirmed_event"] is True
    assert operation["has_model_flag_unlabeled"] is True
    assert operation["terminal_segment_count"] == 1
    assert operation["truncated_segment_count"] == 1
    assert operation["data_quality_summary"] == "mixed"


def test_operation_quality_marks_nonterminal_groups_as_likely_artifacts():
    rows = annotate_segment_refs([
        _segment(1, "abc123_1#1", terminal_op=False),
        _segment(2, "abc123_1#2", terminal_op=False, truncated=True),
    ])
    assert build_operation_summaries(rows)[0]["data_quality_summary"] == "likely artifact"


def test_behavioral_worst_excludes_non_assessable_raw_worst():
    rows = annotate_segment_refs([
        _segment(
            10, "abc123_1#1", score=1.2, pct=99.0, anomalous=True,
            assessment_state="data_quality_conflict", review_lane="data_quality",
        ),
        _segment(
            11, "abc123_1#2", score=0.3, pct=85.0, anomalous=True,
            assessment_state="reviewable", review_lane="behavioral",
        ),
    ])
    operation = build_operation_summaries(rows)[0]
    assert operation["worst_case_ref"] == "CASE-0010"
    assert operation["behavioral_worst_case_ref"] == "CASE-0011"
    assert operation["behavioral_worst_score"] == 0.3
    assert operation["data_quality_segment_count"] == 1
    assert operation["assessment_summary"] == "mixed evidence"
