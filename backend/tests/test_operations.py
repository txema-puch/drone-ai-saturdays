"""Focused tests for stable identities and operation-level aggregation."""

import pytest

from backend.serve.operations import (
    annotate_segment_refs,
    build_operation_summaries,
    case_identity,
)


def _segment(segment_id: str, **overrides) -> dict:
    row = {
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


def test_case_identity_known_vector():
    assert case_identity("502ce6_1543855510#1") == (
        "c_c2bwwjgaxbqg43kb",
        "CASE-C2BWWJGAXBQG4",
    )


def test_segment_identities_do_not_depend_on_order_or_cohort_extension():
    source = [
        _segment("502ce6_1543855510#1"),
        _segment("abcdef_1580731000#1"),
    ]
    rows = annotate_segment_refs(source)
    original = {row["segment_id"]: (row["case_id"], row["case_ref"]) for row in rows}
    reordered_and_extended = annotate_segment_refs([
        _segment("new123_1700000000#1"),
        *reversed(source),
    ])
    regenerated = {
        row["segment_id"]: (row["case_id"], row["case_ref"])
        for row in reordered_and_extended
    }

    assert regenerated["502ce6_1543855510#1"] == original["502ce6_1543855510#1"]
    assert regenerated["abcdef_1580731000#1"] == original["abcdef_1580731000#1"]
    assert rows[0]["case_id"] == "c_c2bwwjgaxbqg43kb"
    assert rows[0]["case_ref"] == "CASE-C2BWWJGAXBQG4"
    assert rows[0]["operation_ref"] == "OP-502CE6-1543855510"


def test_corrected_or_resegmented_telemetry_gets_a_new_identity():
    original = case_identity("502ce6_1543855510#1")
    corrected_first_seen = case_identity("502ce6_1543855520#1")
    resegmented = case_identity("502ce6_1543855510#2")

    assert corrected_first_seen != original
    assert resegmented != original


@pytest.mark.parametrize(
    ("digest_fn", "identifier_prefix"),
    [
        (lambda _data: b"\x00" * 32, "c_"),
        (
            lambda data: b"\x00" * 8 + bytes([1 if data.startswith(b"a") else 2]) + b"\x00" * 23,
            "CASE-",
        ),
    ],
)
def test_identity_collision_aborts_bake(digest_fn, identifier_prefix):
    with pytest.raises(ValueError, match=f"collision for {identifier_prefix}"):
        annotate_segment_refs(
            [_segment("alpha_1#1"), _segment("bravo_1#1")],
            digest_fn=digest_fn,
        )


def test_duplicate_segment_identity_aborts_bake():
    with pytest.raises(ValueError, match="case identity collision"):
        annotate_segment_refs([_segment("alpha_1#1"), _segment("alpha_1#1")])


def test_operation_uses_worst_segment_and_never_sums_scores():
    rows = annotate_segment_refs([
        _segment(
            "502ce6_1543855510#1", score=0.8, pct=99.0, anomalous=True,
            label="go_around",
        ),
        _segment(
            "502ce6_1543855510#2", score=0.7, pct=97.0, anomalous=True,
            terminal_op=False, truncated=True,
        ),
    ])
    operation = build_operation_summaries(rows)[0]
    assert operation["segment_count"] == 2
    assert operation["flagged_segment_count"] == 2
    assert operation["worst_score"] == 0.8
    assert operation["worst_score"] != sum(row["score"] for row in rows)
    assert operation["worst_case_id"] == rows[0]["case_id"]
    assert operation["worst_case_ref"] == rows[0]["case_ref"]
    assert operation["labels_seen"] == ["go_around", "normal"]
    assert operation["has_confirmed_event"] is True
    assert operation["has_model_flag_unlabeled"] is True
    assert operation["terminal_segment_count"] == 1
    assert operation["truncated_segment_count"] == 1
    assert operation["data_quality_summary"] == "mixed"


def test_operation_quality_marks_nonterminal_groups_as_likely_artifacts():
    rows = annotate_segment_refs([
        _segment("abc123_1#1", terminal_op=False),
        _segment("abc123_1#2", terminal_op=False, truncated=True),
    ])
    assert build_operation_summaries(rows)[0]["data_quality_summary"] == "likely artifact"


def test_behavioral_worst_excludes_non_assessable_raw_worst():
    rows = annotate_segment_refs([
        _segment(
            "abc123_1#1", score=1.2, pct=99.0, anomalous=True,
            assessment_state="data_quality_conflict", review_lane="data_quality",
        ),
        _segment(
            "abc123_1#2", score=0.3, pct=85.0, anomalous=True,
            assessment_state="reviewable", review_lane="behavioral",
        ),
    ])
    operation = build_operation_summaries(rows)[0]
    assert operation["worst_case_id"] == rows[0]["case_id"]
    assert operation["behavioral_worst_case_id"] == rows[1]["case_id"]
    assert operation["worst_case_ref"] == rows[0]["case_ref"]
    assert operation["behavioral_worst_case_ref"] == rows[1]["case_ref"]
    assert operation["behavioral_worst_score"] == 0.3
    assert operation["data_quality_segment_count"] == 1
    assert operation["assessment_summary"] == "mixed evidence"
