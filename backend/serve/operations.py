"""Pure operation-grouping helpers shared by bundle generation and serving."""

from __future__ import annotations

from collections import defaultdict


def operation_key(segment_id: str) -> str:
    """Return the stable trajectory key shared by sibling scored segments."""
    return segment_id.rsplit("#", 1)[0]


def operation_ref(segment_id: str) -> str:
    return f"OP-{operation_key(segment_id).upper().replace('_', '-')}"


def annotate_segment_refs(rows: list[dict]) -> list[dict]:
    """Bake stable analyst references without depending on queue position."""
    return [
        {
            **row,
            "band": row.get("band", severity_band(float(row["pct"]))),
            "case_ref": f"CASE-{int(row['id']):04d}",
            "operation_ref": operation_ref(row["segment_id"]),
        }
        for row in rows
    ]


def severity_band(pct: float) -> str:
    return ("highly anomalous" if pct >= 95 else "elevated" if pct >= 80
            else "upper-normal" if pct >= 50 else "normal range")


def build_operation_summaries(rows: list[dict]) -> list[dict]:
    """Aggregate segment evidence without compounding scores across long operations."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["operation_ref"]].append(row)

    operations = []
    for ref, segments in grouped.items():
        segments = sorted(
            segments,
            key=lambda row: int(row["segment_id"].rsplit("#", 1)[1])
            if "#" in row["segment_id"] else 0,
        )
        worst = max(segments, key=lambda row: row["score"])
        reviewable = [
            row for row in segments if row.get("assessment_state", "reviewable") == "reviewable"
        ]
        behavioral_worst = max(reviewable, key=lambda row: row["score"]) if reviewable else None
        terminal_count = sum(bool(row.get("terminal_op", True)) for row in segments)
        truncated_count = sum(bool(row.get("truncated", False)) for row in segments)
        if terminal_count == 0:
            quality = "likely artifact"
        elif terminal_count == len(segments):
            quality = "mostly terminal"
        else:
            quality = "mixed"
        operations.append({
            "operation_ref": ref,
            "segment_count": len(segments),
            "flagged_segment_count": sum(bool(row["anomalous"]) for row in segments),
            "worst_score": worst["score"],
            "worst_pct": worst["pct"],
            "worst_band": severity_band(worst["pct"]),
            "worst_case_ref": worst["case_ref"],
            "worst_segment_id": worst["segment_id"],
            "worst_segment_id_num": worst["id"],
            "labels_seen": sorted({row["label"] for row in segments}),
            "has_confirmed_event": any(row["label"] != "normal" for row in segments),
            "has_model_flag_unlabeled": any(
                row["anomalous"] and row["label"] == "normal" for row in segments
            ),
            "behavioral_flagged_segment_count": sum(
                bool(row["anomalous"]) for row in reviewable
            ),
            "reviewable_segment_count": len(reviewable),
            "not_assessable_segment_count": len(segments) - len(reviewable),
            "data_quality_segment_count": sum(
                row.get("review_lane") == "data_quality" for row in segments
            ),
            "coverage_limited_segment_count": sum(
                row.get("review_lane") == "coverage" for row in segments
            ),
            "behavioral_assessment": "reviewable" if behavioral_worst else "not_assessable",
            "behavioral_worst_score": behavioral_worst["score"] if behavioral_worst else None,
            "behavioral_worst_pct": behavioral_worst["pct"] if behavioral_worst else None,
            "behavioral_worst_band": (
                severity_band(behavioral_worst["pct"]) if behavioral_worst else None
            ),
            "behavioral_worst_case_ref": (
                behavioral_worst["case_ref"] if behavioral_worst else None
            ),
            "behavioral_worst_segment_id_num": (
                behavioral_worst["id"] if behavioral_worst else None
            ),
            "terminal_segment_count": terminal_count,
            "truncated_segment_count": truncated_count,
            "data_quality_summary": quality,
            "assessment_summary": (
                "reviewable" if len(reviewable) == len(segments)
                else "not assessable" if not reviewable
                else "mixed evidence"
            ),
            "segments": segments,
        })
    return sorted(
        operations,
        key=lambda operation: (
            operation["behavioral_worst_score"] is not None,
            operation["behavioral_worst_score"] or float("-inf"),
        ),
        reverse=True,
    )
