"""Build-time cross-file validation for a structurally valid SADAR release.

Unlike :mod:`backend.serve.release`, this boundary may use dataframe/parquet and ML
dependencies.  It validates the meaning of the already hashed files immediately before
promotion; the fetch stage intentionally does not import this module.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from backend.core.preprocessing import AE_FEATURES, SCALER_FEATURES
from backend.serve.model_artifacts import (
    LoadedModelArtifacts,
    assert_scaler_parity,
    build_cohort_score_reference,
    load_model_artifacts,
    weak_ecdf_percentile,
)
from backend.serve.operations import case_identity, operation_ref, severity_band
from backend.serve.release import (
    ReleaseCompatibilityError,
    ReleaseFormatError,
    ReleaseIntegrityError,
    canonical_json_bytes,
    read_json_file,
)


REQUIRED_CASE_RAW_COLUMNS = (
    "segment_id",
    "time",
    "lat",
    "lon",
    "baroaltitude",
    "velocity",
    "vertrate",
    "heading",
    "onground",
)
JSON_ARTIFACT_LIMITS = {
    "queue.json": 8 * 1024 * 1024,
    "cases.json": 64 * 1024 * 1024,
    "operations.json": 32 * 1024 * 1024,
    "metrics.json": 1 * 1024 * 1024,
}
MAX_QUEUE_ROWS = 100_000
MAX_CASES = 10_000
MAX_OPERATIONS = 100_000
MAX_CASE_RAW_ROWS = 1_000_000
MAX_CASE_RAW_ROW_GROUPS = 10_000
MAX_CASE_RAW_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
DISPLAY_SCORE_DECIMALS = 6
DISPLAY_PERCENTILE_DECIMALS = 1
SELECTED_MODEL_ID = "AE"


def _declared_size(manifest: Mapping[str, Any], relative: str) -> int:
    for record in manifest["files"]:
        if record["path"] == relative:
            return int(record["bytes"])
    raise ReleaseFormatError(f"release manifest does not declare {relative}")


def _read_release_json(base: Path, manifest: Mapping[str, Any], relative: str) -> Any:
    limit = JSON_ARTIFACT_LIMITS.get(relative)
    if limit is None:
        raise ReleaseFormatError(f"no semantic JSON limit is configured for {relative}")
    return read_json_file(
        base / relative,
        max_bytes=min(_declared_size(manifest, relative), limit),
    )


def _require_rows(value: Any, *, name: str, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ReleaseFormatError(f"{name} must be an array of objects")
    if len(value) > maximum:
        raise ReleaseFormatError(
            f"{name} exceeds row limit: expected <= {maximum}, observed {len(value)}"
        )
    return value


def _identity_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    case_refs: dict[str, str] = {}
    segment_ids: dict[str, str] = {}
    for index, row in enumerate(rows):
        for key in ("case_id", "case_ref", "segment_id", "operation_ref"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ReleaseFormatError(f"queue[{index}].{key} must be a non-empty string")
        case_id = row["case_id"]
        case_ref = row["case_ref"]
        segment_id = row["segment_id"]
        expected_case_id, expected_case_ref = case_identity(segment_id)
        expected_operation_ref = operation_ref(segment_id)
        if case_id != expected_case_id or case_ref != expected_case_ref:
            raise ReleaseIntegrityError(
                f"queue identity mismatch for {segment_id}: expected "
                f"{expected_case_id}/{expected_case_ref}, observed {case_id}/{case_ref}"
            )
        if row["operation_ref"] != expected_operation_ref:
            raise ReleaseIntegrityError(
                f"queue operation identity mismatch for {segment_id}: expected "
                f"{expected_operation_ref}, observed {row['operation_ref']}"
            )
        if case_id in result:
            raise ReleaseIntegrityError(f"queue contains duplicate case_id {case_id}")
        if case_ref in case_refs:
            raise ReleaseIntegrityError(
                f"queue contains duplicate case_ref {case_ref} for {case_refs[case_ref]} and {case_id}"
            )
        if segment_id in segment_ids:
            raise ReleaseIntegrityError(
                f"queue contains duplicate segment_id {segment_id} for {segment_ids[segment_id]} and {case_id}"
            )
        if not isinstance(row.get("has_case"), bool):
            raise ReleaseFormatError(f"queue[{index}].has_case must be boolean")
        result[case_id] = row
        case_refs[case_ref] = case_id
        segment_ids[segment_id] = case_id
    return result


def _cases_index(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or any(
        not isinstance(case_id, str) or not isinstance(case, dict)
        for case_id, case in value.items()
    ):
        raise ReleaseFormatError("cases.json must be an object keyed by case_id")
    if len(value) > MAX_CASES:
        raise ReleaseFormatError(
            f"cases.json exceeds row limit: expected <= {MAX_CASES}, observed {len(value)}"
        )
    for key, case in value.items():
        if case.get("case_id") != key:
            raise ReleaseIntegrityError(
                f"case map key mismatch: expected embedded case_id {key}, observed {case.get('case_id')!r}"
            )
    return value


def _validate_metrics(value: Any) -> None:
    if not isinstance(value, dict):
        raise ReleaseFormatError("metrics.json must be an object")
    selected = value.get("selected_model")
    if selected != SELECTED_MODEL_ID:
        raise ReleaseCompatibilityError(
            f"metrics selected_model mismatch: expected {SELECTED_MODEL_ID!r}, observed {selected!r}"
        )
    results = value.get("results")
    if not isinstance(results, list) or not results or len(results) > 100:
        raise ReleaseFormatError("metrics.results must be a non-empty bounded array")
    model_names: set[str] = set()
    for index, row in enumerate(results):
        if not isinstance(row, dict) or not isinstance(row.get("model"), str) or not row["model"]:
            raise ReleaseFormatError(f"metrics.results[{index}] must name a model")
        if row["model"] in model_names:
            raise ReleaseIntegrityError(f"metrics.results contains duplicate model {row['model']!r}")
        model_names.add(row["model"])
        for field in ("real_roc_auc", "real_pr_auc", "synthetic_mean_roc_auc"):
            metric = row.get(field)
            if metric is not None and (
                not isinstance(metric, (int, float))
                or isinstance(metric, bool)
                or not np.isfinite(metric)
            ):
                raise ReleaseFormatError(f"metrics.results[{index}].{field} must be finite or null")
        per_type = row.get("synthetic_per_type")
        if not isinstance(per_type, dict) or any(
            not isinstance(name, str)
            or not name
            or not isinstance(metric, (int, float))
            or isinstance(metric, bool)
            or not np.isfinite(metric)
            for name, metric in per_type.items()
        ):
            raise ReleaseFormatError(
                f"metrics.results[{index}].synthetic_per_type must be a finite metric map"
            )
    if selected not in model_names:
        raise ReleaseIntegrityError(f"metrics selected model {selected!r} has no result row")
    notes = value.get("notes")
    if not isinstance(notes, dict) or any(
        not isinstance(key, str) or not isinstance(note, str) for key, note in notes.items()
    ):
        raise ReleaseFormatError("metrics.notes must be a string map")


def _assert_duplicate_fields(queue_row: Mapping[str, Any], duplicate: Mapping[str, Any], *, source: str) -> None:
    missing = sorted(set(queue_row) - {"has_case"} - set(duplicate))
    if missing:
        raise ReleaseIntegrityError(
            f"{source} for {queue_row['case_id']} is missing duplicated queue fields {missing}"
        )
    for key in set(queue_row) & set(duplicate):
        if key == "has_case":
            continue
        if canonical_json_bytes(queue_row[key]) != canonical_json_bytes(duplicate[key]):
            raise ReleaseIntegrityError(
                f"{source} field mismatch for {queue_row['case_id']}.{key}: "
                f"expected {queue_row[key]!r}, observed {duplicate[key]!r}"
            )


def _validate_cases(
    queue_by_id: Mapping[str, dict[str, Any]],
    cases_by_id: Mapping[str, dict[str, Any]],
) -> None:
    expected_ids = {case_id for case_id, row in queue_by_id.items() if row["has_case"]}
    observed_ids = set(cases_by_id)
    if observed_ids != expected_ids:
        raise ReleaseIntegrityError(
            f"curated case subset mismatch: missing={sorted(expected_ids - observed_ids)}, "
            f"extra={sorted(observed_ids - expected_ids)}"
        )
    for case_id in sorted(expected_ids):
        _assert_duplicate_fields(queue_by_id[case_id], cases_by_id[case_id], source="case")


def _score(row: Mapping[str, Any], *, source: str) -> float:
    value = row.get("score")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not np.isfinite(value):
        raise ReleaseFormatError(f"{source}.score must be finite")
    return float(value)


def _segment_order(row: Mapping[str, Any]) -> tuple[str, int]:
    segment_id = str(row["segment_id"])
    trajectory, separator, suffix = segment_id.rpartition("#")
    if separator and suffix.isdigit():
        return trajectory, int(suffix)
    return segment_id, 0


def _assert_summary_identity(
    operation: Mapping[str, Any],
    prefix: str,
    expected: Mapping[str, Any] | None,
) -> None:
    field_map = {
        "score": f"{prefix}_score",
        "pct": f"{prefix}_pct",
        "band": f"{prefix}_band",
        "case_id": f"{prefix}_case_id",
        "case_ref": f"{prefix}_case_ref",
    }
    if prefix == "worst":
        field_map["segment_id"] = "worst_segment_id"
    for source_key, summary_key in field_map.items():
        observed = operation.get(summary_key)
        wanted = expected.get(source_key) if expected is not None else None
        if canonical_json_bytes(observed) != canonical_json_bytes(wanted):
            raise ReleaseIntegrityError(
                f"operation {operation.get('operation_ref')} {summary_key} mismatch: "
                f"expected {wanted!r}, observed {observed!r}"
            )


def _validate_operations(
    queue_by_id: Mapping[str, dict[str, Any]],
    operations: list[dict[str, Any]],
) -> set[str]:
    expected_groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for case_id, row in queue_by_id.items():
        expected_groups[row["operation_ref"]][case_id] = row

    observed_refs: set[str] = set()
    observed_case_ids: set[str] = set()
    for index, operation in enumerate(operations):
        ref = operation.get("operation_ref")
        if not isinstance(ref, str) or not ref:
            raise ReleaseFormatError(f"operations[{index}].operation_ref must be a non-empty string")
        if ref in observed_refs:
            raise ReleaseIntegrityError(f"operations contains duplicate operation_ref {ref}")
        observed_refs.add(ref)
        segments = _require_rows(
            operation.get("segments"),
            name=f"operation {ref}.segments",
            maximum=MAX_QUEUE_ROWS,
        )
        segment_map: dict[str, dict[str, Any]] = {}
        for segment in segments:
            case_id = segment.get("case_id")
            if not isinstance(case_id, str) or case_id not in queue_by_id:
                raise ReleaseIntegrityError(f"operation {ref} contains unknown case_id {case_id!r}")
            if case_id in observed_case_ids:
                raise ReleaseIntegrityError(f"case_id {case_id} appears in multiple operation memberships")
            observed_case_ids.add(case_id)
            segment_map[case_id] = segment
            if canonical_json_bytes(queue_by_id[case_id]) != canonical_json_bytes(segment):
                raise ReleaseIntegrityError(
                    f"operation {ref} segment {case_id} does not byte-match its queue row"
                )

        expected = expected_groups.get(ref, {})
        if set(segment_map) != set(expected):
            raise ReleaseIntegrityError(
                f"operation {ref} membership mismatch: missing={sorted(set(expected) - set(segment_map))}, "
                f"extra={sorted(set(segment_map) - set(expected))}"
            )
        if operation.get("segment_count") != len(expected):
            raise ReleaseIntegrityError(
                f"operation {ref} segment_count mismatch: expected {len(expected)}, "
                f"observed {operation.get('segment_count')!r}"
            )
        if expected:
            ordered = sorted(expected.values(), key=_segment_order)
            worst = max(ordered, key=lambda row: _score(row, source=f"queue {row['case_id']}"))
            _assert_summary_identity(operation, "worst", worst)
            reviewable = [
                row for row in ordered
                if row.get("assessment_state", "reviewable") == "reviewable"
            ]
            behavioral_worst = (
                max(reviewable, key=lambda row: _score(row, source=f"queue {row['case_id']}"))
                if reviewable else None
            )
            _assert_summary_identity(operation, "behavioral_worst", behavioral_worst)

    if observed_refs != set(expected_groups):
        raise ReleaseIntegrityError(
            f"operation set mismatch: missing={sorted(set(expected_groups) - observed_refs)}, "
            f"extra={sorted(observed_refs - set(expected_groups))}"
        )
    if observed_case_ids != set(queue_by_id):
        raise ReleaseIntegrityError(
            f"operation membership does not cover queue: missing={sorted(set(queue_by_id) - observed_case_ids)}"
        )
    return observed_refs


def _validate_case_operation_refs(cases: Mapping[str, Mapping[str, Any]], operation_refs: set[str]) -> None:
    for case_id, case in cases.items():
        if case.get("operation_ref") not in operation_refs:
            raise ReleaseIntegrityError(
                f"case {case_id} refers to unknown operation {case.get('operation_ref')!r}"
            )


def _validate_cases_raw(
    path: Path,
    cases: Mapping[str, Mapping[str, Any]],
    *,
    required_columns: Sequence[str],
) -> None:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - build image always carries pyarrow
        raise ReleaseCompatibilityError("pyarrow is required for build-time release validation") from exc
    try:
        parquet_file = parquet.ParquetFile(path)
    except Exception as exc:
        raise ReleaseFormatError(f"cases_raw.parquet is malformed: {type(exc).__name__}") from exc
    metadata = parquet_file.metadata
    if metadata.num_rows > MAX_CASE_RAW_ROWS:
        raise ReleaseFormatError(
            f"cases_raw.parquet exceeds row limit: expected <= {MAX_CASE_RAW_ROWS}, "
            f"observed {metadata.num_rows}"
        )
    if metadata.num_row_groups > MAX_CASE_RAW_ROW_GROUPS:
        raise ReleaseFormatError(
            f"cases_raw.parquet exceeds row-group limit: expected <= {MAX_CASE_RAW_ROW_GROUPS}, "
            f"observed {metadata.num_row_groups}"
        )
    uncompressed_bytes = sum(
        metadata.row_group(group_index).column(column_index).total_uncompressed_size
        for group_index in range(metadata.num_row_groups)
        for column_index in range(metadata.num_columns)
    )
    if uncompressed_bytes > MAX_CASE_RAW_UNCOMPRESSED_BYTES:
        raise ReleaseFormatError(
            f"cases_raw.parquet exceeds decoded-byte limit: expected <= "
            f"{MAX_CASE_RAW_UNCOMPRESSED_BYTES}, observed {uncompressed_bytes}"
        )
    columns = set(parquet_file.schema_arrow.names)
    missing_columns = sorted(set(required_columns) - columns)
    if missing_columns:
        raise ReleaseIntegrityError(
            f"cases_raw.parquet required columns mismatch: missing={missing_columns}"
        )
    try:
        segment_column = parquet_file.read(columns=["segment_id"])["segment_id"]
        observed_segments = {value.as_py() for value in segment_column if value.as_py() is not None}
    except Exception as exc:
        raise ReleaseFormatError(f"cannot read cases_raw.parquet segment IDs: {type(exc).__name__}") from exc
    expected_segments = {case["segment_id"] for case in cases.values()}
    if observed_segments != expected_segments:
        raise ReleaseIntegrityError(
            f"cases_raw.parquet segment set mismatch: "
            f"missing={sorted(expected_segments - observed_segments)}, "
            f"extra={sorted(observed_segments - expected_segments)}"
        )


def _validate_report_bindings(
    cases: Mapping[str, Mapping[str, Any]],
    report_validator: Callable[[Mapping[str, Any]], bool],
) -> None:
    for case_id, case in cases.items():
        if case.get("report") is None:
            continue
        if report_validator(case) is not True:
            raise ReleaseIntegrityError(
                f"case {case_id} report failed deterministic binding validation"
            )


def _validate_recomputed_scores(
    queue_by_id: Mapping[str, Mapping[str, Any]],
    artifacts: LoadedModelArtifacts,
    scores_by_case_id: Mapping[str, float],
) -> None:
    if not isinstance(scores_by_case_id, Mapping):
        raise ReleaseFormatError("recomputed_scores_by_case_id must be a mapping")
    if set(scores_by_case_id) != set(queue_by_id):
        raise ReleaseIntegrityError(
            f"recomputed score identity mismatch: "
            f"missing={sorted(set(queue_by_id) - set(scores_by_case_id))}, "
            f"extra={sorted(set(scores_by_case_id) - set(queue_by_id))}"
        )
    threshold = float(artifacts.model_contract["scoring_contract"]["threshold"])
    for case_id, row in queue_by_id.items():
        full_score = _score(
            {"score": scores_by_case_id[case_id]}, source=f"recomputed score {case_id}"
        )
        percentile = weak_ecdf_percentile(artifacts.cohort_reference, full_score)
        expected = {
            "score": round(full_score, DISPLAY_SCORE_DECIMALS),
            "pct": round(percentile, DISPLAY_PERCENTILE_DECIMALS),
            "anomalous": full_score >= threshold,
            "band": severity_band(percentile),
        }
        for key, expected_value in expected.items():
            if canonical_json_bytes(row.get(key)) != canonical_json_bytes(expected_value):
                raise ReleaseIntegrityError(
                    f"queue model evidence mismatch for {case_id}.{key}: "
                    f"expected {expected_value!r}, observed {row.get(key)!r}"
                )


def validate_release_semantics(
    release_dir: Path | str,
    manifest: Mapping[str, Any],
    *,
    expected_online_contract: Mapping[str, str],
    training_scaler: Any,
    scaler_parity_vectors: Any,
    recomputed_scores_by_case_id: Mapping[str, float],
    report_validator: Callable[[Mapping[str, Any]], bool],
    required_raw_columns: Sequence[str] = REQUIRED_CASE_RAW_COLUMNS,
) -> LoadedModelArtifacts:
    """Validate all cross-file release relationships before atomic promotion."""
    base = Path(release_dir)
    queue = _require_rows(
        _read_release_json(base, manifest, "queue.json"),
        name="queue.json",
        maximum=MAX_QUEUE_ROWS,
    )
    if not queue:
        raise ReleaseFormatError("queue.json cannot be empty")
    cases = _cases_index(_read_release_json(base, manifest, "cases.json"))
    operations = _require_rows(
        _read_release_json(base, manifest, "operations.json"),
        name="operations.json",
        maximum=MAX_OPERATIONS,
    )
    _validate_metrics(_read_release_json(base, manifest, "metrics.json"))

    queue_by_id = _identity_index(queue)
    _validate_cases(queue_by_id, cases)
    operation_refs = _validate_operations(queue_by_id, operations)
    _validate_case_operation_refs(cases, operation_refs)
    _validate_cases_raw(base / "cases_raw.parquet", cases, required_columns=required_raw_columns)
    _validate_report_bindings(cases, report_validator)

    observed_contract = manifest.get("online_input_contract")
    if not isinstance(observed_contract, dict):
        raise ReleaseFormatError("release online_input_contract must be an object")
    contract = dict(expected_online_contract)
    for key in (
        "input_schema_version",
        "derivation_contract_version",
        "preprocessing_contract_version",
    ):
        if not isinstance(contract.get(key), str) or not contract[key]:
            raise ReleaseFormatError(f"expected online contract {key} must be a non-empty string")

    artifacts = load_model_artifacts(
        base,
        manifest,
        input_schema_version=contract["input_schema_version"],
        derivation_contract_version=contract["derivation_contract_version"],
        preprocessing_contract_version=contract["preprocessing_contract_version"],
    )
    if tuple(artifacts.model_contract["features"]) != tuple(AE_FEATURES):
        raise ReleaseCompatibilityError(
            f"model feature contract mismatch: expected {AE_FEATURES}, "
            f"observed {artifacts.model_contract['features']}"
        )
    if artifacts.scaler.features != tuple(SCALER_FEATURES):
        raise ReleaseCompatibilityError(
            f"scaler feature contract mismatch: expected {SCALER_FEATURES}, "
            f"observed {list(artifacts.scaler.features)}"
        )
    assert_scaler_parity(training_scaler, artifacts.scaler, scaler_parity_vectors)
    _validate_recomputed_scores(queue_by_id, artifacts, recomputed_scores_by_case_id)
    expected_reference = build_cohort_score_reference(list(recomputed_scores_by_case_id.values()))
    declared = artifacts.model_contract["cohort_reference"]
    expected_contract = {
        key: expected_reference[key]
        for key in ("count", "digest", "formula_id", "tie_policy")
    }
    if canonical_json_bytes(declared) != canonical_json_bytes(expected_contract):
        raise ReleaseIntegrityError(
            f"recomputed cohort reference mismatch: expected {expected_contract}, observed {declared}"
        )
    return artifacts
