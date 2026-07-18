"""Strict immutable contract for schema-v4 public approach evidence releases."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Mapping
from datetime import date as calendar_date
from itertools import product
from pathlib import Path, PurePosixPath
from typing import Any


APPROACH_RELEASE_SCHEMA_VERSION = 4
MANIFEST_NAME = "release-manifest.json"
REQUIRED_FILES = frozenset({
    "demo/catalog.json",
    "demo/attempts.json",
    "demo/cases.json",
    "demo/operations.json",
    "research/aggregate-results.json",
    "config/approach-config.json",
    "config/lemd-geometry.json",
    "reference/approach-reference.json",
})
OPTIONAL_FILES: frozenset[str] = frozenset()
ALLOWED_FILES = REQUIRED_FILES
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_RELEASE_ATTEMPTS = 5_000
FILE_LIMITS = {
    "demo/catalog.json": 1 * 1024 * 1024,
    "demo/attempts.json": 5 * 1024 * 1024,
    "demo/cases.json": 8 * 1024 * 1024,
    "demo/operations.json": 1 * 1024 * 1024,
    "research/aggregate-results.json": 2 * 1024 * 1024,
    "config/approach-config.json": 1 * 1024 * 1024,
    "config/lemd-geometry.json": 1 * 1024 * 1024,
    "reference/approach-reference.json": 8 * 1024 * 1024,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[0-9a-f]{20}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORBIDDEN_AGGREGATE_KEYS = {
    "lat", "lon", "latitude", "longitude", "icao24", "callsign", "flight_id",
    "source_operation_id", "observations", "trajectory", "path", "squawk", "alert",
}
_FORBIDDEN_DEMO_IDENTIFIER_KEYS = {
    "source_operation_id", "icao24", "callsign", "flight_id",
}
_OBSERVATION_KEYS = {
    "observation_index", "time", "lat", "lon", "baroaltitude", "geoaltitude",
    "velocity", "heading", "vertrate", "onground",
}
_STATUS_KEYS = {
    "criteria_observed", "not_assessable", "partial_observation", "review_required",
}
_CRITERIA = (
    "lateral_path_proxy", "barometric_path_proxy", "observed_descent_rate",
    "observed_ground_speed_envelope", "late_track_correction",
)
_CRITERION_STATUSES = {"within_limit", "review_required", "not_observed"}
_BLOCKED_USES = [
    "operational_monitoring", "emergency_detection", "stabilized_approach_certification",
    "atc_decision_support", "safety_performance_claims",
]
_CITATION = (
    "Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic, and "
    "Matthias Wilhelm. Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for "
    "Research. IPSN 2014."
)


class ApproachReleaseError(RuntimeError):
    """Base error for schema-v4 release failures."""


class ApproachReleaseFormatError(ApproachReleaseError):
    """The release has an unsafe or incompatible shape."""


class ApproachReleaseIntegrityError(ApproachReleaseError):
    """Declared identities or bytes do not match observed content."""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ApproachReleaseFormatError(f"value is not canonical JSON: {exc}") from exc


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ApproachReleaseFormatError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ApproachReleaseFormatError(f"JSON contains non-standard number {value}")


def parse_json_bytes(data: bytes, *, source: str = "JSON") -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApproachReleaseFormatError(f"{source} is not UTF-8") from exc
    try:
        return json.loads(text, object_pairs_hook=_object_without_duplicates, parse_constant=_reject_constant)
    except ApproachReleaseError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ApproachReleaseFormatError(f"{source} is malformed JSON") from exc


def _read_regular(path: Path, *, limit: int) -> bytes:
    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApproachReleaseFormatError(f"cannot open {path.name}") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ApproachReleaseFormatError(f"{path.name} must be a regular file")
        if info.st_size > limit:
            raise ApproachReleaseFormatError(f"{path.name} exceeds byte limit")
        return handle.read(limit + 1)


def read_canonical_json(path: Path | str, *, limit: int) -> Any:
    file_path = Path(path)
    data = _read_regular(file_path, limit=limit)
    if len(data) > limit:
        raise ApproachReleaseFormatError(f"{file_path.name} exceeds byte limit")
    value = parse_json_bytes(data, source=file_path.name)
    if canonical_json_bytes(value) != data:
        raise ApproachReleaseFormatError(f"{file_path.name} is not canonical JSON")
    return value


def _plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ApproachReleaseFormatError(f"{field} must be lowercase SHA-256")
    return value


def _exact_object(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ApproachReleaseFormatError(f"{field} keys mismatch")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 500:
        raise ApproachReleaseFormatError(f"{field} must be trimmed non-empty text")
    return value


def _scan_forbidden_keys(value: Any, field: str, forbidden: set[str]) -> None:
    pending: list[tuple[Any, str]] = [(value, field)]
    while pending:
        current, current_path = pending.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = f"{current_path}.{key}"
                if key.lower() in forbidden:
                    raise ApproachReleaseFormatError(f"{child_path} is forbidden")
                pending.append((child, child_path))
        elif isinstance(current, list):
            pending.extend(
                (child, f"{current_path}[{index}]")
                for index, child in enumerate(current)
            )


def _optional_number(value: Any, field: str) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ApproachReleaseFormatError(f"{field} must be a finite number or null")


def _total(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if not _plain_int(value) or value < 0:
        raise ApproachReleaseFormatError(f"{field} must be a non-negative integer")
    return value


def _rate(value: Any, field: str, *, nullable: bool = False) -> float | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApproachReleaseFormatError(f"{field} must be a finite rate")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ApproachReleaseFormatError(f"{field} must be a finite rate")
    return result


def _limits(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ApproachReleaseFormatError(f"{field} must contain 1-32 limits")
    items = [_text(item, f"{field}[]") for item in value]
    if len(items) != len(set(items)):
        raise ApproachReleaseFormatError(f"{field} must contain unique limits")
    return items


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ApproachReleaseFormatError(f"{field} must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ApproachReleaseFormatError(f"{field} is unsafe")
    return value


def release_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("release_id", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:20]


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate the exact schema-v4 manifest without reading artifacts."""
    manifest = _exact_object(manifest, {
        "schema_version", "release_id", "release_kind", "data_policy", "source",
        "contracts", "files",
    }, "release manifest")
    if not _plain_int(manifest["schema_version"]) or manifest["schema_version"] != 4:
        raise ApproachReleaseFormatError("approach release schema_version must equal integer 4")
    if manifest["release_kind"] != "sadar_approach_public_evidence":
        raise ApproachReleaseFormatError("unsupported approach release kind")
    _validate_data_policy(manifest["data_policy"])
    source = _exact_object(manifest["source"], {
        "aggregate_artifact_sha256", "synthetic_generator", "synthetic_seed",
    }, "source")
    _digest(source["aggregate_artifact_sha256"], "source.aggregate_artifact_sha256")
    if source["synthetic_generator"] != "sadar_synthetic_approach_v1":
        raise ApproachReleaseFormatError("source.synthetic_generator is unsupported")
    if not _plain_int(source["synthetic_seed"]) or not 0 <= source["synthetic_seed"] <= 4294967295:
        raise ApproachReleaseFormatError("source.synthetic_seed must be a uint32 integer")
    contracts = _exact_object(manifest["contracts"], {
        "assessment_schema_version", "engine_version", "reconstruction_policy_version",
        "demo_schema_version", "case_observation_limit", "approach_config_sha256",
        "geometry_source_sha256", "reference_sha256", "aggregate_results_sha256",
    }, "contracts")
    for key in ("assessment_schema_version", "engine_version", "reconstruction_policy_version", "demo_schema_version"):
        _text(contracts[key], f"contracts.{key}")
    if not _plain_int(contracts["case_observation_limit"]) or contracts["case_observation_limit"] != 600:
        raise ApproachReleaseFormatError("contracts.case_observation_limit must equal 600")
    for key in ("approach_config_sha256", "geometry_source_sha256", "reference_sha256", "aggregate_results_sha256"):
        _digest(contracts[key], f"contracts.{key}")
    release_id = manifest["release_id"]
    if not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id):
        raise ApproachReleaseFormatError("release_id must be 20 lowercase hex characters")
    if release_id != release_id_for_manifest(manifest):
        raise ApproachReleaseIntegrityError("release ID mismatch")
    records = manifest["files"]
    if not isinstance(records, list):
        raise ApproachReleaseFormatError("files must be an array")
    paths: list[str] = []
    total = 0
    for index, record in enumerate(records):
        record = _exact_object(record, {"path", "sha256", "bytes"}, f"files[{index}]")
        path = _relative_path(record["path"], field=f"files[{index}].path")
        if path not in ALLOWED_FILES:
            raise ApproachReleaseFormatError(f"release file is not allowlisted: {path}")
        _digest(record["sha256"], f"files[{index}].sha256")
        size = _total(record["bytes"], f"files[{index}].bytes")
        if size > FILE_LIMITS[path]:
            raise ApproachReleaseFormatError(f"release byte length is invalid for {path}")
        paths.append(path)
        total += size
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ApproachReleaseFormatError("release file records must be unique and sorted")
    if set(paths) != REQUIRED_FILES:
        raise ApproachReleaseFormatError("release file allowlist mismatch")
    if total > MAX_TOTAL_BYTES:
        raise ApproachReleaseFormatError("release exceeds total byte limit")
    return manifest


def _validate_data_policy(value: Any) -> None:
    expected = {
        "demo_records": "synthetic", "research_results": "aggregate_only",
        "source_records_included": False,
    }
    if value != expected or not isinstance(value, dict):
        raise ApproachReleaseFormatError("data_policy must declare the frozen public split")


def _cell(value: Any, field: str) -> None:
    if value in {"<10", "suppressed"}:
        return
    if not _plain_int(value) or value < 0 or 1 <= value <= 9:
        raise ApproachReleaseFormatError(f"{field} contains an unsuppressed small cell")


def _count_map(value: Any, keys: set[str], field: str, *, nonempty_subset: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or (not value and nonempty_subset):
        raise ApproachReleaseFormatError(f"{field} must be a count map")
    if (not nonempty_subset and set(value) != keys) or (nonempty_subset and not set(value) <= keys):
        raise ApproachReleaseFormatError(f"{field} count labels mismatch")
    for key, cell in value.items():
        _cell(cell, f"{field}.{key}")
    primary_count = list(value.values()).count("<10")
    companion_count = list(value.values()).count("suppressed")
    if primary_count and companion_count != 1:
        raise ApproachReleaseFormatError(f"{field} lacks complementary suppression")
    if not primary_count and companion_count:
        raise ApproachReleaseFormatError(f"{field} has complementary suppression without a primary cell")
    return value


def _criterion_map(value: Any, field: str) -> dict[str, Any]:
    value = _exact_object(value, set(_CRITERIA), field)
    for criterion in _CRITERIA:
        _count_map(value[criterion], _CRITERION_STATUSES, f"{field}.{criterion}", nonempty_subset=True)
    return value


def _recursive_aggregate_scan(value: Any, path: str = "aggregate_results") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _FORBIDDEN_AGGREGATE_KEYS:
                raise ApproachReleaseFormatError(f"{path}.{key} is forbidden")
            _recursive_aggregate_scan(item, f"{path}.{key}")
    elif isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            row_keys = set().union(*(item.keys() for item in value))
            if row_keys & _FORBIDDEN_AGGREGATE_KEYS:
                raise ApproachReleaseFormatError(f"{path} contains row-like mappings")
        for index, item in enumerate(value):
            _recursive_aggregate_scan(item, f"{path}[{index}]")
    elif _plain_int(value) and 315532800 <= value <= 4102444800:
        raise ApproachReleaseFormatError(f"{path} contains an epoch-like event timestamp")


def _check_published_rate(rate: Any, numerator: Any, denominator: Any, field: str) -> None:
    if _plain_int(numerator) and _plain_int(denominator) and denominator > 0:
        expected = round(numerator / denominator, 4)
        observed = _rate(rate, field)
        if round(float(observed), 4) != expected:
            raise ApproachReleaseFormatError(f"{field} does not match its disclosed operands")
    elif rate is not None:
        raise ApproachReleaseFormatError(f"{field} must be null when operands are suppressed")


_MAX_ASSIGNMENT_SEARCH = 100_000
_STATUS_ORDER = (
    "criteria_observed", "not_assessable", "partial_observation", "review_required",
)


def _is_deterministic_companion(
    counts: dict[str, Any], assignment: dict[str, int], companion: str
) -> bool:
    candidates = {
        key: assignment[key]
        for key, published in counts.items()
        if published != "<10" and assignment[key] > 0
    }
    largest = max(candidates.values())
    return companion == min(key for key, value in candidates.items() if value == largest)


def _count_assignments(
    counts: dict[str, Any],
    *,
    total: int,
    field: str,
    fixed: Mapping[str, int] | None = None,
) -> list[dict[str, int]]:
    """Enumerate the hidden cells of one published partition under its real total."""
    fixed = fixed or {}
    primary = [key for key, value in counts.items() if value == "<10"]
    companion = [key for key, value in counts.items() if value == "suppressed"]
    explicit = {
        key: value for key, value in counts.items() if _plain_int(value)
    }
    if not primary:
        assignment = dict(explicit)
        if sum(assignment.values()) != total or any(assignment.get(key) != value for key, value in fixed.items()):
            raise ApproachReleaseFormatError(f"{field} does not partition its published total")
        return [assignment]
    if len(companion) != 1:
        raise ApproachReleaseFormatError(f"{field} suppression shape is invalid")
    remaining = total - sum(explicit.values())
    assignments: list[dict[str, int]] = []
    examined = 0
    for values in product(range(1, 10), repeat=len(primary)):
        examined += 1
        if examined > _MAX_ASSIGNMENT_SEARCH:
            raise ApproachReleaseFormatError(f"{field} suppression is too complex to prove safe")
        companion_value = remaining - sum(values)
        if companion_value < 10:
            continue
        assignment = {
            **explicit,
            **dict(zip(primary, values, strict=True)),
            companion[0]: companion_value,
        }
        if any(assignment.get(key) != value for key, value in fixed.items()):
            continue
        assignments.append(assignment)
    if not assignments:
        raise ApproachReleaseFormatError(f"{field} has no feasible suppressed assignment")
    return assignments


def _require_primary_ambiguity(
    counts: dict[str, Any], assignments: list[dict[str, int]], field: str
) -> None:
    for key, value in counts.items():
        if value == "<10" and len({assignment[key] for assignment in assignments}) <= 1:
            raise ApproachReleaseFormatError(
                f"{field}.{key} is uniquely recoverable from published constraints"
            )


def _partition_assignments(
    counts: dict[str, Any],
    total: Any,
    field: str,
    *,
    fixed: Mapping[str, int] | None = None,
    require_ambiguity: bool = True,
) -> list[dict[str, int]]:
    if not _plain_int(total):
        if "<10" in counts.values():
            raise ApproachReleaseFormatError(f"{field} lacks a published total for suppression proof")
        return [dict(counts)]
    assignments = _count_assignments(counts, total=total, field=field, fixed=fixed)
    if require_ambiguity:
        _require_primary_ambiguity(counts, assignments, field)
    companion = next((key for key, value in counts.items() if value == "suppressed"), None)
    if companion is None:
        return assignments
    deterministic = [
        assignment for assignment in assignments
        if _is_deterministic_companion(counts, assignment, companion)
    ]
    if not deterministic:
        raise ApproachReleaseFormatError(f"{field} has no feasible deterministic companion")
    if require_ambiguity:
        _require_primary_ambiguity(counts, deterministic, field)
    return deterministic


def _overlap_assignments(
    counts: dict[str, Any],
    *,
    base_reviews: set[int],
    context_reviews: set[int],
    field: str,
) -> list[dict[str, int]]:
    primary = [key for key, value in counts.items() if value == "<10"]
    companion = [key for key, value in counts.items() if value == "suppressed"]
    explicit = {key: value for key, value in counts.items() if _plain_int(value)}
    if not primary:
        assignment = dict(explicit)
        if (
            assignment["base_only"] + assignment["both"] not in base_reviews
            or assignment["context_only"] + assignment["both"] not in context_reviews
        ):
            raise ApproachReleaseFormatError(f"{field} does not match published review counts")
        return [assignment]
    assignments: dict[tuple[int, int, int], dict[str, int]] = {}
    examined = 0
    for values in product(range(1, 10), repeat=len(primary)):
        partial = {**explicit, **dict(zip(primary, values, strict=True))}
        for base_review in base_reviews:
            for context_review in context_reviews:
                examined += 1
                if examined > _MAX_ASSIGNMENT_SEARCH:
                    raise ApproachReleaseFormatError(f"{field} suppression is too complex to prove safe")
                if companion == ["base_only"]:
                    companion_value = base_review - partial["both"]
                elif companion == ["both"]:
                    companion_value = base_review - partial["base_only"]
                    if companion_value != context_review - partial["context_only"]:
                        continue
                elif companion == ["context_only"]:
                    companion_value = context_review - partial["both"]
                else:
                    raise ApproachReleaseFormatError(f"{field} suppression shape is invalid")
                if companion_value < 10:
                    continue
                assignment = {**partial, companion[0]: companion_value}
                if (
                    assignment["base_only"] + assignment["both"] != base_review
                    or assignment["context_only"] + assignment["both"] != context_review
                ):
                    continue
                identity = tuple(assignment[key] for key in ("base_only", "both", "context_only"))
                assignments[identity] = assignment
    if not assignments:
        raise ApproachReleaseFormatError(f"{field} has no feasible suppressed assignment")
    deterministic = [
        assignment for assignment in assignments.values()
        if _is_deterministic_companion(counts, assignment, companion[0])
    ]
    if not deterministic:
        raise ApproachReleaseFormatError(f"{field} has no feasible deterministic companion")
    return deterministic


def _validate_reconstruction_safety(aggregate: dict[str, Any]) -> None:
    """Prove that published totals and related partitions cannot reveal a rare cell."""
    holdout, context_cohort = aggregate["cohorts"]
    context = aggregate["findings"]["context_validation"]

    for cohort_index, cohort in enumerate((holdout, context_cohort)):
        attempts = cohort["attempts"]
        fixed: dict[str, int] = {}
        if _plain_int(attempts) and _plain_int(cohort["assessable_attempts"]):
            not_assessable = attempts - cohort["assessable_attempts"]
            if not_assessable < 0:
                raise ApproachReleaseFormatError(f"cohorts[{cohort_index}].assessable_attempts exceeds attempts")
            fixed["not_assessable"] = not_assessable
        status_assignments = _partition_assignments(
            cohort["status_counts"], attempts, f"cohorts[{cohort_index}].status_counts",
            fixed=fixed, require_ambiguity=cohort_index == 0,
        )
        if cohort["outcome_counts"] is not None:
            _partition_assignments(cohort["outcome_counts"], attempts, f"cohorts[{cohort_index}].outcome_counts")
        for criterion, counts in cohort["criterion_status_counts"].items():
            _partition_assignments(counts, attempts, f"cohorts[{cohort_index}].criterion_status_counts.{criterion}")
        if cohort["runway_direction_counts"] is not None:
            _partition_assignments(cohort["runway_direction_counts"], attempts, f"cohorts[{cohort_index}].runway_direction_counts")
        if cohort_index == 1:
            context_status_assignments = status_assignments

    attempts = context_cohort["attempts"]
    base_status_assignments = _partition_assignments(
        context["base_status_counts"], attempts,
        "findings.context_validation.base_status_counts", require_ambiguity=False,
    )
    for family in ("base_criterion_status_counts", "context_criterion_status_counts"):
        for criterion, counts in context[family].items():
            _partition_assignments(
                counts, attempts, f"findings.context_validation.{family}.{criterion}"
            )
    transition_assignments = _partition_assignments(
        context["status_transition_counts"], attempts,
        "findings.context_validation.status_transition_counts", require_ambiguity=False,
    )

    base_by_counts = {
        tuple(assignment[key] for key in _STATUS_ORDER): assignment
        for assignment in base_status_assignments
    }
    context_by_counts = {
        tuple(assignment[key] for key in _STATUS_ORDER): assignment
        for assignment in context_status_assignments
    }
    linked: list[tuple[dict[str, int], tuple[int, ...], tuple[int, ...]]] = []
    for assignment in transition_assignments:
        rows = tuple(
            sum(
                assignment.get(f"{source}->{destination}", 0)
                for destination in _STATUS_ORDER
            )
            for source in _STATUS_ORDER
        )
        columns = tuple(
            sum(
                assignment.get(f"{source}->{destination}", 0)
                for source in _STATUS_ORDER
            )
            for destination in _STATUS_ORDER
        )
        if rows in base_by_counts and columns in context_by_counts:
            linked.append((assignment, rows, columns))
    if not linked:
        raise ApproachReleaseFormatError(
            "findings.context_validation.status_transition_counts does not match status margins"
        )

    base_reviews = {rows[_STATUS_ORDER.index("review_required")] for _, rows, _ in linked}
    context_reviews = {columns[_STATUS_ORDER.index("review_required")] for _, _, columns in linked}
    overlap_assignments = _overlap_assignments(
        context["review_overlap"], base_reviews=base_reviews,
        context_reviews=context_reviews, field="findings.context_validation.review_overlap",
    )
    review_pairs = {
        (assignment["base_only"] + assignment["both"], assignment["context_only"] + assignment["both"])
        for assignment in overlap_assignments
    }
    linked = [
        item for item in linked
        if (
            item[1][_STATUS_ORDER.index("review_required")],
            item[2][_STATUS_ORDER.index("review_required")],
        ) in review_pairs
    ]
    if not linked:
        raise ApproachReleaseFormatError(
            "findings.context_validation.review_overlap does not match transition margins"
        )
    matched_base = {rows for _, rows, _ in linked}
    matched_context = {columns for _, _, columns in linked}
    matched_pairs = {
        (
            rows[_STATUS_ORDER.index("review_required")],
            columns[_STATUS_ORDER.index("review_required")],
        )
        for _, rows, columns in linked
    }
    base_status_assignments = [
        assignment for counts, assignment in base_by_counts.items() if counts in matched_base
    ]
    context_status_assignments = [
        assignment for counts, assignment in context_by_counts.items() if counts in matched_context
    ]
    transition_assignments = [assignment for assignment, _, _ in linked]
    overlap_assignments = [
        assignment for assignment in overlap_assignments
        if (
            assignment["base_only"] + assignment["both"],
            assignment["context_only"] + assignment["both"],
        ) in matched_pairs
    ]
    for counts, assignments, field in (
        (context["base_status_counts"], base_status_assignments, "findings.context_validation.base_status_counts"),
        (context["context_status_counts"], context_status_assignments, "findings.context_validation.context_status_counts"),
        (context["status_transition_counts"], transition_assignments, "findings.context_validation.status_transition_counts"),
        (context["review_overlap"], overlap_assignments, "findings.context_validation.review_overlap"),
    ):
        _require_primary_ambiguity(counts, assignments, field)


def _validate_aggregate_results(value: Any) -> None:
    _recursive_aggregate_scan(value)
    top = _exact_object(value, {
        "schema_version", "basis", "generated_at", "cohorts", "findings", "qualification",
        "allowed_role", "blocked_uses", "limitations", "data_access",
    }, "aggregate_results")
    if top["schema_version"] != "approach_aggregate_results_v1" or top["basis"] != "real_opensky_research_data":
        raise ApproachReleaseFormatError("aggregate_results schema or basis is unsupported")
    if top["generated_at"] != "2026-07-18":
        raise ApproachReleaseFormatError("aggregate_results.generated_at must equal 2026-07-18")
    if top["qualification"] != "not_qualified_no_independent_labels_or_fresh_holdout":
        raise ApproachReleaseFormatError("aggregate_results.qualification is invalid")
    if top["allowed_role"] != "research_and_evidence_labeling_demonstrator":
        raise ApproachReleaseFormatError("aggregate_results.allowed_role is invalid")
    if top["blocked_uses"] != _BLOCKED_USES:
        raise ApproachReleaseFormatError("aggregate_results.blocked_uses is invalid")
    _limits(top["limitations"], "aggregate_results.limitations")
    access = _exact_object(top["data_access"], {
        "provider", "terms_url", "access_url", "citation", "publication_notice_status",
        "publication_notice_date",
    }, "aggregate_results.data_access")
    if access["provider"] != "OpenSky Network" or access["terms_url"] != "https://opensky-network.org/about/terms-of-use" or access["access_url"] != "https://opensky-network.org/data/data-access" or access["citation"] != _CITATION:
        raise ApproachReleaseFormatError("aggregate_results.data_access citation contract is invalid")
    status = access["publication_notice_status"]
    if status not in {"pending", "sent", "acknowledged"}:
        raise ApproachReleaseFormatError("aggregate_results publication_notice_status is invalid")
    date = access["publication_notice_date"]
    if date is not None and (not isinstance(date, str) or not _DATE_RE.fullmatch(date)):
        raise ApproachReleaseFormatError("aggregate_results publication_notice_date is invalid")
    if date is not None:
        try:
            parsed_notice_date = calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise ApproachReleaseFormatError(
                "aggregate_results publication_notice_date is invalid"
            ) from exc
        if parsed_notice_date > calendar_date.fromisoformat(top["generated_at"]):
            raise ApproachReleaseFormatError(
                "aggregate_results publication_notice_date is invalid"
            )
    if (status == "pending") != (date is None):
        raise ApproachReleaseFormatError(
            "aggregate_results publication_notice_date does not match "
            "publication_notice_status"
        )
    cohorts = top["cohorts"]
    if not isinstance(cohorts, list) or len(cohorts) != 2:
        raise ApproachReleaseFormatError("aggregate_results.cohorts must contain two ordered cohorts")
    expected_cohorts = (
        ("2026_holdout", "March 2026", "single_burn_holdout"),
        ("2019_context_validation", "2019 validation cohort", "val"),
    )
    cohort_keys = {
        "cohort_id", "period", "role", "source_sha256", "base_reference_sha256",
        "context_reference_sha256", "rows", "operations", "operations_with_attempts",
        "attempts", "assessable_attempts", "status_counts", "outcome_counts",
        "criterion_status_counts", "runway_direction_counts", "abstention_rate",
        "review_rate_among_assessable", "context_coverage", "decision",
        "interpretation_limits",
    }
    coverage_keys = {
        "aircraft_metadata_rate", "aircraft_typecode_rate", "barometric_path_current_rate",
        "barometric_path_qnh_context_upper_bound_rate", "qnh_rate", "weather_match_rate",
        "wind_components_rate", "wind_direction_rate", "wind_speed_rate",
    }
    for index, (cohort, expected) in enumerate(zip(cohorts, expected_cohorts, strict=True)):
        cohort = _exact_object(cohort, cohort_keys, f"cohorts[{index}]")
        if tuple(cohort[key] for key in ("cohort_id", "period", "role")) != expected:
            raise ApproachReleaseFormatError(f"cohorts[{index}] identity is invalid")
        _digest(cohort["source_sha256"], f"cohorts[{index}].source_sha256")
        _digest(cohort["base_reference_sha256"], f"cohorts[{index}].base_reference_sha256")
        if index == 0:
            if cohort["context_reference_sha256"] is not None or cohort["context_coverage"] is not None:
                raise ApproachReleaseFormatError("holdout context fields must be null")
        else:
            _digest(cohort["context_reference_sha256"], f"cohorts[{index}].context_reference_sha256")
            coverage = _exact_object(cohort["context_coverage"], coverage_keys, f"cohorts[{index}].context_coverage")
            for key, rate in coverage.items():
                _rate(rate, f"cohorts[{index}].context_coverage.{key}")
        for key in ("rows", "operations", "operations_with_attempts", "attempts", "assessable_attempts"):
            _total(cohort[key], f"cohorts[{index}].{key}", nullable=True)
        status = _count_map(cohort["status_counts"], _STATUS_KEYS, f"cohorts[{index}].status_counts")
        if cohort["outcome_counts"] is not None:
            _count_map(cohort["outcome_counts"], {"final_gate_observed", "go_around", "incomplete"}, f"cohorts[{index}].outcome_counts")
        _criterion_map(cohort["criterion_status_counts"], f"cohorts[{index}].criterion_status_counts")
        if cohort["runway_direction_counts"] is not None:
            _count_map(cohort["runway_direction_counts"], {"18", "32"}, f"cohorts[{index}].runway_direction_counts")
        _check_published_rate(cohort["abstention_rate"], status["not_assessable"], cohort["attempts"], f"cohorts[{index}].abstention_rate")
        _check_published_rate(cohort["review_rate_among_assessable"], status["review_required"], cohort["assessable_attempts"], f"cohorts[{index}].review_rate_among_assessable")
        expected_decision = "descriptive_holdout_burn_no_accuracy_claim" if index == 0 else "not_qualified_no_independent_labels_or_fresh_holdout"
        if cohort["decision"] != expected_decision:
            raise ApproachReleaseFormatError(f"cohorts[{index}].decision is invalid")
        _limits(cohort["interpretation_limits"], f"cohorts[{index}].interpretation_limits")
    findings = _exact_object(top["findings"], {"screening_holdout", "context_validation"}, "aggregate_results.findings")
    screening = _exact_object(findings["screening_holdout"], {
        "cohort_id", "policy", "criterion_status_counts", "reason_counts", "interpretation_limits",
    }, "findings.screening_holdout")
    if screening["cohort_id"] != "2026_holdout" or screening["policy"] != "single_precommitted_transform_no_threshold_tuning":
        raise ApproachReleaseFormatError("findings.screening_holdout identity is invalid")
    _criterion_map(screening["criterion_status_counts"], "findings.screening_holdout.criterion_status_counts")
    _count_map(screening["reason_counts"], {"insufficient_duration", "position_rate_conflict", "terminal_gate_not_reached"}, "findings.screening_holdout.reason_counts")
    _limits(screening["interpretation_limits"], "findings.screening_holdout.interpretation_limits")
    context = _exact_object(findings["context_validation"], {
        "cohort_id", "base_status_counts", "context_status_counts", "base_criterion_status_counts",
        "context_criterion_status_counts", "review_overlap", "status_transition_counts",
        "base_review_rate_among_assessable", "context_review_rate_among_assessable",
        "context_coverage", "decision", "interpretation_limits",
    }, "findings.context_validation")
    if context["cohort_id"] != "2019_context_validation" or context["decision"] != "not_qualified_no_independent_labels_or_fresh_holdout":
        raise ApproachReleaseFormatError("findings.context_validation identity is invalid")
    base_status = _count_map(context["base_status_counts"], _STATUS_KEYS, "findings.context_validation.base_status_counts")
    contextual_status = _count_map(context["context_status_counts"], _STATUS_KEYS, "findings.context_validation.context_status_counts")
    _criterion_map(context["base_criterion_status_counts"], "findings.context_validation.base_criterion_status_counts")
    _criterion_map(context["context_criterion_status_counts"], "findings.context_validation.context_criterion_status_counts")
    _count_map(context["review_overlap"], {"base_only", "both", "context_only"}, "findings.context_validation.review_overlap")
    transition_keys = {
        "criteria_observed->criteria_observed", "criteria_observed->review_required",
        "not_assessable->not_assessable", "partial_observation->criteria_observed",
        "partial_observation->partial_observation", "partial_observation->review_required",
        "review_required->criteria_observed", "review_required->partial_observation",
        "review_required->review_required",
    }
    _count_map(context["status_transition_counts"], transition_keys, "findings.context_validation.status_transition_counts")
    context_cov = _exact_object(context["context_coverage"], {
        "aircraft_type", "all_reference_cells_exact_type", "any_exact_type_reference", "qnh", "wind_components",
    }, "findings.context_validation.context_coverage")
    for key, rate in context_cov.items():
        _rate(rate, f"findings.context_validation.context_coverage.{key}")
    attempts = cohorts[1]["attempts"]
    base_denominator = attempts - base_status["not_assessable"] if _plain_int(attempts) and _plain_int(base_status["not_assessable"]) else None
    context_denominator = attempts - contextual_status["not_assessable"] if _plain_int(attempts) and _plain_int(contextual_status["not_assessable"]) else None
    _check_published_rate(context["base_review_rate_among_assessable"], base_status["review_required"], base_denominator, "findings.context_validation.base_review_rate_among_assessable")
    _check_published_rate(context["context_review_rate_among_assessable"], contextual_status["review_required"], context_denominator, "findings.context_validation.context_review_rate_among_assessable")
    _limits(context["interpretation_limits"], "findings.context_validation.interpretation_limits")
    if screening["criterion_status_counts"] != cohorts[0]["criterion_status_counts"] or screening["interpretation_limits"] != cohorts[0]["interpretation_limits"]:
        raise ApproachReleaseFormatError("screening_holdout duplicated projection mismatch")
    if context["context_status_counts"] != cohorts[1]["status_counts"] or context["context_criterion_status_counts"] != cohorts[1]["criterion_status_counts"]:
        raise ApproachReleaseFormatError("context_validation duplicated projection mismatch")
    stable_limits: list[str] = []
    for item in [*cohorts[0]["interpretation_limits"], *cohorts[1]["interpretation_limits"]]:
        if item not in stable_limits:
            stable_limits.append(item)
    if top["limitations"] != stable_limits:
        raise ApproachReleaseFormatError("aggregate_results.limitations projection mismatch")
    _validate_reconstruction_safety(top)


def _validate_reference(reference: Any) -> None:
    reference = _exact_object(reference, {
        "schema_version", "fit_fold", "source_reference_sha256", "cohort", "distance_bins_m",
        "quantiles", "minimum_samples", "minimum_attempts", "accepted_attempts", "entries",
        "artifact_sha256",
    }, "reference")
    if reference["schema_version"] != "approach_reference_v1" or reference["fit_fold"] != "train":
        raise ApproachReleaseFormatError("reference schema or fit_fold is invalid")
    _digest(reference["source_reference_sha256"], "reference.source_reference_sha256")
    _digest(reference["artifact_sha256"], "reference.artifact_sha256")
    cohort = _exact_object(reference["cohort"], {"candidate_train_segments", "selection", "source", "split_ids_sha256", "years"}, "reference.cohort")
    _total(cohort["candidate_train_segments"], "reference.cohort.candidate_train_segments")
    _text(cohort["selection"], "reference.cohort.selection")
    _text(cohort["source"], "reference.cohort.source")
    _digest(cohort["split_ids_sha256"], "reference.cohort.split_ids_sha256")
    if cohort["years"] != [2017, 2018]:
        raise ApproachReleaseFormatError("reference.cohort.years is invalid")
    if reference["distance_bins_m"] != [0.0, 1500.0, 3000.0, 6000.0, 10000.0, 20000.0] or reference["quantiles"] != [0.01, 0.99]:
        raise ApproachReleaseFormatError("reference bins or quantiles are invalid")
    for key in ("minimum_samples", "minimum_attempts", "accepted_attempts"):
        _total(reference[key], f"reference.{key}")
    entries = reference["entries"]
    if not isinstance(entries, list) or len(entries) != 10:
        raise ApproachReleaseFormatError("reference.entries must contain ten runtime cells")
    entry_keys = {
        "direction", "speed_class", "distance_bin_m", "attempt_count", "speed_sample_count",
        "vertical_rate_sample_count", "speed_lower_mps", "speed_upper_mps",
        "vertical_rate_lower_mps", "vertical_rate_upper_mps",
    }
    expected_order = [(direction, bin_name) for direction in ("18", "32") for bin_name in ("0-1500", "10000-20000", "1500-3000", "3000-6000", "6000-10000")]
    observed_order = []
    for index, entry in enumerate(entries):
        entry = _exact_object(entry, entry_keys, f"reference.entries[{index}]")
        observed_order.append((entry["direction"], entry["distance_bin_m"]))
        if entry["direction"] not in {"18", "32"} or entry["speed_class"] != "unknown":
            raise ApproachReleaseFormatError(f"reference.entries[{index}] identity is invalid")
        for key in ("attempt_count", "speed_sample_count", "vertical_rate_sample_count"):
            _total(entry[key], f"reference.entries[{index}].{key}")
        for key in ("speed_lower_mps", "speed_upper_mps", "vertical_rate_lower_mps", "vertical_rate_upper_mps"):
            if isinstance(entry[key], bool) or not isinstance(entry[key], (int, float)) or not math.isfinite(float(entry[key])):
                raise ApproachReleaseFormatError(f"reference.entries[{index}].{key} must be finite")
        if not 0 <= entry["speed_lower_mps"] <= entry["speed_upper_mps"] <= 150 or not -25 <= entry["vertical_rate_lower_mps"] <= entry["vertical_rate_upper_mps"] <= 25:
            raise ApproachReleaseFormatError(f"reference.entries[{index}] thresholds are invalid")
    if observed_order != expected_order:
        raise ApproachReleaseFormatError("reference.entries order is invalid")
    projection = dict(reference)
    projection.pop("artifact_sha256")
    if hashlib.sha256(canonical_json_bytes(projection)).hexdigest() != reference["artifact_sha256"]:
        raise ApproachReleaseIntegrityError("reference.artifact_sha256 mismatch")


def _validate_catalog(catalog: Any) -> dict[str, dict[str, Any]]:
    catalog = _exact_object(catalog, {
        "schema_version", "generator_version", "seed", "approach_config_sha256",
        "geometry_source_sha256", "reference_sha256", "scenarios",
    }, "demo.catalog")
    if catalog["schema_version"] != "approach_synthetic_demo_v1":
        raise ApproachReleaseFormatError("demo.catalog schema_version is invalid")
    if catalog["generator_version"] != "sadar_synthetic_approach_v1":
        raise ApproachReleaseFormatError("demo.catalog.generator_version is unsupported")
    if not _plain_int(catalog["seed"]) or not 0 <= catalog["seed"] <= 4294967295:
        raise ApproachReleaseFormatError("demo.catalog.seed must be uint32")
    for key in ("approach_config_sha256", "geometry_source_sha256", "reference_sha256"):
        _digest(catalog[key], f"demo.catalog.{key}")
    scenarios = catalog["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ApproachReleaseFormatError("demo.catalog.scenarios must be non-empty")
    result: dict[str, dict[str, Any]] = {}
    for index, scenario in enumerate(scenarios):
        scenario = _exact_object(scenario, {"scenario_id", "scenario_title", "teaching_goal"}, f"demo.catalog.scenarios[{index}]")
        for key in scenario:
            _text(scenario[key], f"demo.catalog.scenarios[{index}].{key}")
        if scenario["scenario_id"] in result:
            raise ApproachReleaseFormatError("demo.catalog scenario IDs must be unique")
        result[scenario["scenario_id"]] = scenario
    return result


def _synthetic_common(record: Any, field: str, scenarios: dict[str, dict[str, Any]]) -> None:
    if not isinstance(record, dict) or record.get("data_origin") != "synthetic":
        raise ApproachReleaseFormatError(f"{field}.data_origin must be synthetic")
    _scan_forbidden_keys(record, field, _FORBIDDEN_DEMO_IDENTIFIER_KEYS)
    scenario = scenarios.get(record.get("scenario_id"))
    if scenario is None:
        raise ApproachReleaseFormatError(f"{field}.scenario_id is unknown")
    for key in ("scenario_title", "teaching_goal"):
        if record.get(key) != scenario[key]:
            raise ApproachReleaseFormatError(f"{field}.{key} does not match catalog")


def _validate_synthetic_attempts(value: Any, scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    value = _exact_object(value, {"schema_version", "attempts"}, "demo.attempts")
    if value["schema_version"] != "approach_attempts_v1" or not isinstance(value["attempts"], list):
        raise ApproachReleaseFormatError("demo.attempts payload is invalid")
    if len(value["attempts"]) > MAX_RELEASE_ATTEMPTS:
        raise ApproachReleaseFormatError("demo.attempts exceeds record limit")
    for index, record in enumerate(value["attempts"]):
        _synthetic_common(record, f"demo.attempts[{index}]", scenarios)
        if not isinstance(record.get("attempt_id"), str) or not record["attempt_id"].startswith("syn-a-"):
            raise ApproachReleaseFormatError(f"demo.attempts[{index}].attempt_id prefix is invalid")
        if record.get("status") not in _STATUS_KEYS:
            raise ApproachReleaseFormatError(f"demo.attempts[{index}].status is invalid")
        assessment = record.get("assessment")
        if not isinstance(assessment, dict):
            raise ApproachReleaseFormatError(f"demo.attempts[{index}].assessment must be an object")
        for key in ("attempt", "quality", "runway_inference"):
            child = assessment.get(key)
            if child is not None and not isinstance(child, dict):
                raise ApproachReleaseFormatError(
                    f"demo.attempts[{index}].assessment.{key} must be an object or null"
                )
        for key in ("criteria", "reasons", "maneuvers"):
            child = assessment.get(key)
            if child is not None and not isinstance(child, list):
                raise ApproachReleaseFormatError(
                    f"demo.attempts[{index}].assessment.{key} must be an array or null"
                )
        if assessment.get("status") != record["status"]:
            raise ApproachReleaseFormatError(
                f"demo.attempts[{index}].assessment.status mismatch"
            )
        for criterion_index, criterion in enumerate(assessment.get("criteria") or []):
            if not isinstance(criterion, dict) or not isinstance(criterion.get("evidence"), list):
                raise ApproachReleaseFormatError(
                    f"demo.attempts[{index}].assessment.criteria[{criterion_index}] is invalid"
                )
    return value["attempts"]


def _validate_synthetic_cases(value: Any, scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    value = _exact_object(value, {"schema_version", "cases"}, "demo.cases")
    if value["schema_version"] != "approach_cases_v1" or not isinstance(value["cases"], list):
        raise ApproachReleaseFormatError("demo.cases payload is invalid")
    for index, record in enumerate(value["cases"]):
        _synthetic_common(record, f"demo.cases[{index}]", scenarios)
        if not isinstance(record.get("case_id"), str) or not record["case_id"].startswith("syn-c-"):
            raise ApproachReleaseFormatError(f"demo.cases[{index}].case_id prefix is invalid")
        if not isinstance(record.get("observations"), list):
            raise ApproachReleaseFormatError(f"demo.cases[{index}].observations must be an array")
        if len(record["observations"]) > 600:
            raise ApproachReleaseFormatError(f"demo.cases[{index}].observations exceeds limit")
        if record.get("observation_count") != len(record["observations"]):
            raise ApproachReleaseFormatError(f"demo.cases[{index}].observation_count mismatch")
        for observation_index, observation in enumerate(record["observations"]):
            field = f"demo.cases[{index}].observations[{observation_index}]"
            if not isinstance(observation, dict) or not {
                "observation_index", "time", "lat", "lon", "baroaltitude",
            }.issubset(observation) or not set(observation).issubset(_OBSERVATION_KEYS):
                raise ApproachReleaseFormatError(f"{field} shape is invalid")
            if observation["observation_index"] != observation_index:
                raise ApproachReleaseFormatError(f"{field}.observation_index mismatch")
            for key in _OBSERVATION_KEYS - {"observation_index", "onground"}:
                if key in observation:
                    _optional_number(observation[key], f"{field}.{key}")
            if "onground" in observation and not isinstance(observation["onground"], bool):
                raise ApproachReleaseFormatError(f"{field}.onground must be boolean")
    return value["cases"]


def _validate_synthetic_operations(value: Any, scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    value = _exact_object(value, {"schema_version", "operations"}, "demo.operations")
    if value["schema_version"] != "approach_operations_v1" or not isinstance(value["operations"], list):
        raise ApproachReleaseFormatError("demo.operations payload is invalid")
    for index, record in enumerate(value["operations"]):
        _synthetic_common(record, f"demo.operations[{index}]", scenarios)
        if not isinstance(record.get("operation_id"), str) or not record["operation_id"].startswith("syn-op-"):
            raise ApproachReleaseFormatError(f"demo.operations[{index}].operation_id prefix is invalid")
        for key in ("attempt_ids", "case_ids"):
            if not isinstance(record.get(key), list) or not all(
                isinstance(item, str) for item in record[key]
            ):
                raise ApproachReleaseFormatError(f"demo.operations[{index}].{key} is invalid")
        if not _plain_int(record.get("attempt_count")) or record["attempt_count"] < 0:
            raise ApproachReleaseFormatError(
                f"demo.operations[{index}].attempt_count is invalid"
            )
    return value["operations"]


def _validate_cross_references(attempts: list[dict[str, Any]], cases: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    identifiers = []
    for records, key, name in ((attempts, "attempt_id", "attempt"), (cases, "case_id", "case"), (operations, "operation_id", "operation")):
        values = [item.get(key) for item in records]
        if values != sorted(values) or len(values) != len(set(values)):
            raise ApproachReleaseFormatError(f"synthetic {name} IDs must be unique and sorted")
        identifiers.append(set(values))
    attempt_ids, case_ids, operation_ids = identifiers
    attempts_by_id = {item["attempt_id"]: item for item in attempts}
    cases_by_id = {item["case_id"]: item for item in cases}
    if len({item.get("case_id") for item in attempts}) != len(attempts):
        raise ApproachReleaseFormatError("synthetic attempt/case links must be one-to-one")
    if len({item.get("attempt_id") for item in cases}) != len(cases):
        raise ApproachReleaseFormatError("synthetic case/attempt links must be one-to-one")
    for attempt in attempts:
        if attempt.get("case_id") not in case_ids or attempt.get("operation_id") not in operation_ids:
            raise ApproachReleaseFormatError("synthetic attempt cross reference is invalid")
        case = cases_by_id[attempt["case_id"]]
        if (
            case.get("attempt_id") != attempt["attempt_id"]
            or case.get("operation_id") != attempt["operation_id"]
            or case.get("scenario_id") != attempt.get("scenario_id")
        ):
            raise ApproachReleaseFormatError("synthetic attempt/case links are not reciprocal")
    for case in cases:
        if case.get("attempt_id") not in attempt_ids or case.get("operation_id") not in operation_ids:
            raise ApproachReleaseFormatError("synthetic case cross reference is invalid")
        attempt = attempts_by_id[case["attempt_id"]]
        if attempt.get("case_id") != case["case_id"] or attempt.get("operation_id") != case["operation_id"]:
            raise ApproachReleaseFormatError("synthetic attempt/case links are not reciprocal")
    grouped_attempts = [item for operation in operations for item in operation.get("attempt_ids", [])]
    grouped_cases = [item for operation in operations for item in operation.get("case_ids", [])]
    if set(grouped_attempts) != attempt_ids or len(grouped_attempts) != len(set(grouped_attempts)):
        raise ApproachReleaseFormatError("synthetic operations do not cover attempts exactly")
    if set(grouped_cases) != case_ids or len(grouped_cases) != len(set(grouped_cases)):
        raise ApproachReleaseFormatError("synthetic operations do not cover cases exactly")
    for operation in operations:
        if operation.get("attempt_count") != len(operation.get("attempt_ids", [])):
            raise ApproachReleaseFormatError("synthetic operation attempt_count is inconsistent")
        for attempt_id in operation.get("attempt_ids", []):
            attempt = attempts_by_id[attempt_id]
            if (
                attempt.get("operation_id") != operation["operation_id"]
                or attempt.get("scenario_id") != operation.get("scenario_id")
            ):
                raise ApproachReleaseFormatError("synthetic grouped attempt owner is invalid")
        for case_id in operation.get("case_ids", []):
            case = cases_by_id[case_id]
            if (
                case.get("operation_id") != operation["operation_id"]
                or case.get("scenario_id") != operation.get("scenario_id")
            ):
                raise ApproachReleaseFormatError("synthetic grouped case owner is invalid")


def _validate_payloads(payloads: dict[str, Any], manifest: dict[str, Any] | None = None) -> None:
    catalog = payloads["demo/catalog.json"]
    scenarios = _validate_catalog(catalog)
    attempts = _validate_synthetic_attempts(payloads["demo/attempts.json"], scenarios)
    cases = _validate_synthetic_cases(payloads["demo/cases.json"], scenarios)
    operations = _validate_synthetic_operations(payloads["demo/operations.json"], scenarios)
    _validate_cross_references(attempts, cases, operations)
    aggregate = payloads["research/aggregate-results.json"]
    _validate_aggregate_results(aggregate)
    config = payloads["config/approach-config.json"]
    geometry = payloads["config/lemd-geometry.json"]
    if not isinstance(config, dict) or config.get("schema_version") != "approach_config_v1" or not isinstance(config.get("config"), dict):
        raise ApproachReleaseFormatError("approach config payload is invalid")
    if not isinstance(geometry, dict) or geometry.get("schema_version") != "lemd_geometry_v1" or not isinstance(geometry.get("thresholds"), dict):
        raise ApproachReleaseFormatError("geometry payload is invalid")
    reference = payloads["reference/approach-reference.json"]
    _validate_reference(reference)
    config_digest = hashlib.sha256(canonical_json_bytes(config)).hexdigest()
    geometry_digest = hashlib.sha256(canonical_json_bytes(geometry)).hexdigest()
    reference_digest = hashlib.sha256(canonical_json_bytes(reference)).hexdigest()
    aggregate_digest = hashlib.sha256(canonical_json_bytes(aggregate)).hexdigest()
    if catalog["approach_config_sha256"] != config_digest or catalog["geometry_source_sha256"] != geometry_digest or catalog["reference_sha256"] != reference_digest:
        raise ApproachReleaseIntegrityError("demo.catalog methodology hash mismatch")
    if manifest is not None:
        source, contracts = manifest["source"], manifest["contracts"]
        if source["synthetic_generator"] != catalog["generator_version"] or source["synthetic_seed"] != catalog["seed"]:
            raise ApproachReleaseIntegrityError("manifest synthetic generator/seed mismatch")
        expected_contracts = {
            "assessment_schema_version": config.get("assessment_schema_version"),
            "engine_version": config.get("engine_version"),
            "reconstruction_policy_version": config.get("reconstruction_policy_version"),
            "demo_schema_version": catalog["schema_version"],
            "approach_config_sha256": config_digest,
            "geometry_source_sha256": geometry_digest,
            "reference_sha256": reference_digest,
            "aggregate_results_sha256": aggregate_digest,
        }
        for key, expected in expected_contracts.items():
            if contracts[key] != expected:
                raise ApproachReleaseIntegrityError(f"manifest contracts.{key} mismatch")
        if source["aggregate_artifact_sha256"] != aggregate_digest:
            raise ApproachReleaseIntegrityError("manifest aggregate artifact hash mismatch")


def _load_validated_release(path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ApproachReleaseFormatError("release root must be a real directory")
    manifest = validate_manifest(read_canonical_json(root / MANIFEST_NAME, limit=MAX_MANIFEST_BYTES))
    expected = {MANIFEST_NAME, *(record["path"] for record in manifest["files"])}
    expected_directories = {parent.as_posix() for relative in expected for parent in PurePosixPath(relative).parents if parent.as_posix() != "."}
    observed: set[str] = set()
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise ApproachReleaseFormatError(f"release contains symlink: {relative}")
        if candidate.is_file():
            observed.add(relative)
        elif candidate.is_dir():
            if relative not in expected_directories:
                raise ApproachReleaseFormatError(f"release contains extra directory: {relative}")
        else:
            raise ApproachReleaseFormatError(f"release contains non-regular member: {relative}")
    if observed != expected:
        raise ApproachReleaseFormatError("release layout mismatch: missing or extra_files")
    payloads: dict[str, Any] = {}
    for record in manifest["files"]:
        relative = record["path"]
        data = _read_regular(root.joinpath(*PurePosixPath(relative).parts), limit=FILE_LIMITS[relative])
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ApproachReleaseIntegrityError(f"release artifact mismatch: {relative}")
        value = parse_json_bytes(data, source=relative)
        if canonical_json_bytes(value) != data:
            raise ApproachReleaseFormatError(f"{relative} is not canonical JSON")
        payloads[relative] = value
    _validate_payloads(payloads, manifest)
    return manifest, payloads


def validate_public_release_directory(path: Path | str) -> dict[str, Any]:
    """Run the full integrity, schema, cross-reference, and disclosure boundary."""
    manifest, _ = _load_validated_release(path)
    return manifest


validate_release_directory = validate_public_release_directory


def load_release_directory(path: Path | str) -> dict[str, Any]:
    """Validate first, then load the split schema-v4 lanes for serving."""
    manifest, payloads = _load_validated_release(path)
    aggregate = payloads["research/aggregate-results.json"]
    return {
        "manifest": manifest,
        "attempts": payloads["demo/attempts.json"]["attempts"],
        "cases": payloads["demo/cases.json"]["cases"],
        "operations": payloads["demo/operations.json"]["operations"],
        "metrics": aggregate,
        "aggregate_results": aggregate,
        "config": payloads["config/approach-config.json"],
        "geometry": payloads["config/lemd-geometry.json"],
        "reference": payloads["reference/approach-reference.json"],
        "research": None,
        "demo_data_origin": "synthetic",
    }


def write_release(root: Path | str, payloads: Mapping[str, Any], *, source: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any]:
    """Write canonical allowlisted schema-v4 artifacts and their manifest."""
    if set(payloads) != REQUIRED_FILES:
        raise ApproachReleaseFormatError("release payload allowlist mismatch")
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for relative in sorted(payloads):
        data = canonical_json_bytes(payloads[relative])
        if len(data) > FILE_LIMITS[relative]:
            raise ApproachReleaseFormatError(f"release payload exceeds byte limit: {relative}")
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    manifest: dict[str, Any] = {
        "schema_version": 4,
        "release_kind": "sadar_approach_public_evidence",
        "data_policy": {"demo_records": "synthetic", "research_results": "aggregate_only", "source_records_included": False},
        "source": source,
        "contracts": contracts,
        "files": records,
    }
    manifest["release_id"] = release_id_for_manifest(manifest)
    (destination / MANIFEST_NAME).write_bytes(canonical_json_bytes(manifest))
    validate_public_release_directory(destination)
    return manifest


def validation_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a schema-v4 public release directory.")
    parser.add_argument("--release-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest, payloads = _load_validated_release(args.release_dir)
    except ApproachReleaseError as exc:
        print(f"public release validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "release_id": manifest["release_id"],
        "schema_version": manifest["schema_version"],
        "demo_count": len(payloads["demo/attempts.json"]["attempts"]),
        "cohort_count": len(payloads["research/aggregate-results.json"]["cohorts"]),
    }, sort_keys=True))
    return 0
