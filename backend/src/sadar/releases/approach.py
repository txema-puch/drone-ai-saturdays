"""Strict immutable release contract for the rules-first approach product.

Schema v3 is intentionally independent from the historical model/schema-v2 bundle.
Every shipped artifact is canonical JSON, content addressed, and allowlisted.  The
manifest is not self-hashed; its release ID is derived from the manifest without the
``release_id`` field.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any


APPROACH_RELEASE_SCHEMA_VERSION = 3
MANIFEST_NAME = "release-manifest.json"
REQUIRED_FILES = frozenset({
    "attempts.json",
    "cases.json",
    "operations.json",
    "metrics.json",
    "config/approach-config.json",
    "config/lemd-geometry.json",
    "reference/approach-reference.json",
})
OPTIONAL_FILES = frozenset({"research/benchmark.json"})
ALLOWED_FILES = REQUIRED_FILES | OPTIONAL_FILES

MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_RELEASE_ATTEMPTS = 5_000
FILE_LIMITS = {
    "attempts.json": 64 * 1024 * 1024,
    "cases.json": 160 * 1024 * 1024,
    "operations.json": 16 * 1024 * 1024,
    "metrics.json": 2 * 1024 * 1024,
    "config/approach-config.json": 1 * 1024 * 1024,
    "config/lemd-geometry.json": 1 * 1024 * 1024,
    "reference/approach-reference.json": 8 * 1024 * 1024,
    "research/benchmark.json": 8 * 1024 * 1024,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


class ApproachReleaseError(RuntimeError):
    """Base error for schema-v3 release failures."""


class ApproachReleaseFormatError(ApproachReleaseError):
    """The release has an unsafe or incompatible shape."""


class ApproachReleaseIntegrityError(ApproachReleaseError):
    """Declared identities or bytes do not match observed content."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON and reject non-finite numbers."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
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
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ApproachReleaseError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ApproachReleaseFormatError(f"{source} is malformed JSON") from exc


def _read_regular(path: Path, *, limit: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApproachReleaseFormatError(f"cannot open {path.name}: {exc}") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ApproachReleaseFormatError(f"{path.name} must be a regular file")
        if info.st_size > limit:
            raise ApproachReleaseFormatError(
                f"{path.name} exceeds byte limit: expected <= {limit}, observed {info.st_size}"
            )
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ApproachReleaseFormatError(f"{path.name} exceeds byte limit")
    return data


def read_canonical_json(path: Path | str, *, limit: int) -> Any:
    file_path = Path(path)
    data = _read_regular(file_path, limit=limit)
    value = parse_json_bytes(data, source=file_path.name)
    if canonical_json_bytes(value) != data:
        raise ApproachReleaseFormatError(f"{file_path.name} is not canonical JSON")
    return value


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ApproachReleaseFormatError(f"{field} must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ApproachReleaseFormatError(f"{field} is unsafe: {value!r}")
    if path.as_posix() != value:
        raise ApproachReleaseFormatError(f"{field} is not canonical: {value!r}")
    return value


def _plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def release_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("release_id", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:20]


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate a schema-v3 manifest without reading its artifacts."""
    if not isinstance(manifest, dict):
        raise ApproachReleaseFormatError("release manifest must be an object")
    expected_keys = {
        "schema_version", "release_id", "release_kind", "source", "contracts", "files"
    }
    if set(manifest) != expected_keys:
        raise ApproachReleaseFormatError(
            f"release manifest keys mismatch: missing={sorted(expected_keys - set(manifest))}, "
            f"extra={sorted(set(manifest) - expected_keys)}"
        )
    if manifest["schema_version"] != APPROACH_RELEASE_SCHEMA_VERSION or not _plain_int(
        manifest["schema_version"]
    ):
        raise ApproachReleaseFormatError("approach release schema_version must equal integer 3")
    if manifest["release_kind"] != "sadar_approach_screening":
        raise ApproachReleaseFormatError("unsupported approach release kind")
    release_id = manifest["release_id"]
    if not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id):
        raise ApproachReleaseFormatError("release_id must be 20 lowercase hex characters")
    expected_id = release_id_for_manifest(manifest)
    if release_id != expected_id:
        raise ApproachReleaseIntegrityError(
            f"release ID mismatch: expected {expected_id}, observed {release_id}"
        )
    source = manifest["source"]
    if not isinstance(source, dict) or set(source) != {
        "input_sha256", "rows", "operations"
    }:
        raise ApproachReleaseFormatError("source must contain input_sha256, rows, and operations")
    if not isinstance(source["input_sha256"], str) or not _SHA256_RE.fullmatch(
        source["input_sha256"]
    ):
        raise ApproachReleaseFormatError("source input_sha256 is invalid")
    for key in ("rows", "operations"):
        if not _plain_int(source[key]) or source[key] < 0:
            raise ApproachReleaseFormatError(f"source {key} must be a non-negative integer")
    if not isinstance(manifest["contracts"], dict) or not manifest["contracts"]:
        raise ApproachReleaseFormatError("contracts must be a non-empty object")

    records = manifest["files"]
    if not isinstance(records, list):
        raise ApproachReleaseFormatError("files must be an array")
    paths: list[str] = []
    total = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
            raise ApproachReleaseFormatError(
                f"files[{index}] must contain exactly path, sha256, and bytes"
            )
        path = _relative_path(record["path"], field=f"files[{index}].path")
        if path not in ALLOWED_FILES:
            raise ApproachReleaseFormatError(f"release file is not allowlisted: {path}")
        if not isinstance(record["sha256"], str) or not _SHA256_RE.fullmatch(record["sha256"]):
            raise ApproachReleaseFormatError(f"release digest is invalid for {path}")
        size = record["bytes"]
        if not _plain_int(size) or size < 0 or size > FILE_LIMITS[path]:
            raise ApproachReleaseFormatError(f"release byte length is invalid for {path}")
        paths.append(path)
        total += size
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ApproachReleaseFormatError("release file records must be unique and sorted")
    missing = REQUIRED_FILES - set(paths)
    extra = set(paths) - ALLOWED_FILES
    if missing or extra:
        raise ApproachReleaseFormatError(
            f"release file allowlist mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    if total > MAX_TOTAL_BYTES:
        raise ApproachReleaseFormatError("release exceeds total byte limit")
    return manifest


def _validate_payloads(payloads: dict[str, Any]) -> None:
    attempts = payloads["attempts.json"]
    cases = payloads["cases.json"]
    operations = payloads["operations.json"]
    metrics = payloads["metrics.json"]
    config = payloads["config/approach-config.json"]
    geometry = payloads["config/lemd-geometry.json"]
    reference = payloads["reference/approach-reference.json"]
    schemas = {
        "attempts.json": "approach_attempts_v1",
        "cases.json": "approach_cases_v1",
        "operations.json": "approach_operations_v1",
        "metrics.json": "approach_release_metrics_v1",
        "config/approach-config.json": "approach_config_v1",
        "config/lemd-geometry.json": "lemd_geometry_v1",
        "reference/approach-reference.json": "approach_reference_v1",
    }
    for path, schema in schemas.items():
        value = payloads[path]
        if not isinstance(value, dict) or value.get("schema_version") != schema:
            raise ApproachReleaseFormatError(f"{path} has an unsupported schema_version")
    if not isinstance(attempts.get("attempts"), list):
        raise ApproachReleaseFormatError("attempts.json attempts must be an array")
    if len(attempts["attempts"]) > MAX_RELEASE_ATTEMPTS:
        raise ApproachReleaseFormatError(
            f"release may contain at most {MAX_RELEASE_ATTEMPTS} attempts"
        )
    if not isinstance(cases.get("cases"), list):
        raise ApproachReleaseFormatError("cases.json cases must be an array")
    if not isinstance(operations.get("operations"), list):
        raise ApproachReleaseFormatError("operations.json operations must be an array")
    if not isinstance(metrics.get("limitations"), list):
        raise ApproachReleaseFormatError("metrics.json limitations must be an array")
    if "qualification" in metrics and not isinstance(metrics["qualification"], str):
        raise ApproachReleaseFormatError("metrics.json qualification must be a string")
    if "allowed_role" in metrics and not isinstance(metrics["allowed_role"], str):
        raise ApproachReleaseFormatError("metrics.json allowed_role must be a string")
    if "blocked_uses" in metrics and not isinstance(metrics["blocked_uses"], list):
        raise ApproachReleaseFormatError("metrics.json blocked_uses must be an array")
    if not isinstance(config.get("config"), dict):
        raise ApproachReleaseFormatError("approach config payload is invalid")
    if not isinstance(geometry.get("thresholds"), dict):
        raise ApproachReleaseFormatError("geometry payload is invalid")
    if reference.get("fit_fold") != "train":
        raise ApproachReleaseFormatError("approach reference must be fit on train")

    attempt_ids = [item.get("attempt_id") for item in attempts["attempts"]]
    case_ids = [item.get("case_id") for item in cases["cases"]]
    operation_ids = [item.get("operation_id") for item in operations["operations"]]
    for name, values in (
        ("attempt", attempt_ids), ("case", case_ids), ("operation", operation_ids)
    ):
        if any(not isinstance(value, str) or not value for value in values):
            raise ApproachReleaseFormatError(f"{name} IDs must be non-empty strings")
        if values != sorted(values) or len(values) != len(set(values)):
            raise ApproachReleaseFormatError(f"{name} IDs must be unique and sorted")
    attempt_set, case_set, operation_set = set(attempt_ids), set(case_ids), set(operation_ids)
    allowed_statuses = {
        "review_required", "partial_observation", "criteria_observed", "not_assessable",
    }
    attempts_by_id = {item["attempt_id"]: item for item in attempts["attempts"]}
    cases_by_id = {item["case_id"]: item for item in cases["cases"]}
    operations_by_id = {
        item["operation_id"]: item for item in operations["operations"]
    }
    case_attempts = [item.get("attempt_id") for item in cases["cases"]]
    if set(case_attempts) != attempt_set or len(case_attempts) != len(set(case_attempts)):
        raise ApproachReleaseFormatError("cases must cover attempts exactly once")
    for attempt in attempts["attempts"]:
        if attempt.get("case_id") not in case_set:
            raise ApproachReleaseFormatError("attempt references an unknown case")
        if attempt.get("operation_id") not in operation_set:
            raise ApproachReleaseFormatError("attempt references an unknown operation")
        if attempt.get("status") not in allowed_statuses:
            raise ApproachReleaseFormatError("attempt has an unsupported status")
        assessment = attempt.get("assessment")
        if not isinstance(assessment, dict):
            raise ApproachReleaseFormatError("attempt assessment must be an object")
        if assessment.get("status") != attempt["status"]:
            raise ApproachReleaseFormatError("attempt and assessment status disagree")
        if not isinstance(attempt.get("failed_criteria"), list):
            raise ApproachReleaseFormatError("attempt failed_criteria must be an array")
    for case in cases["cases"]:
        if case.get("attempt_id") not in attempt_set:
            raise ApproachReleaseFormatError("case references an unknown attempt")
        if not isinstance(case.get("observations"), list):
            raise ApproachReleaseFormatError("case observations must be an array")
        attempt = attempts_by_id[case["attempt_id"]]
        if attempt.get("case_id") != case["case_id"]:
            raise ApproachReleaseFormatError("attempt and case links are not reciprocal")
        if attempt.get("operation_id") != case.get("operation_id"):
            raise ApproachReleaseFormatError("attempt and case operation ownership disagree")
    grouped = [
        attempt_id
        for operation in operations["operations"]
        for attempt_id in operation.get("attempt_ids", [])
    ]
    if set(grouped) != attempt_set or len(grouped) != len(set(grouped)):
        raise ApproachReleaseFormatError("operation attempt grouping does not cover attempts exactly")
    grouped_cases = [
        case_id
        for operation in operations["operations"]
        for case_id in operation.get("case_ids", [])
    ]
    if set(grouped_cases) != case_set or len(grouped_cases) != len(set(grouped_cases)):
        raise ApproachReleaseFormatError("operation case grouping does not cover cases exactly")
    for operation_id, operation in operations_by_id.items():
        if not isinstance(operation.get("attempt_ids"), list) or not isinstance(
            operation.get("case_ids"), list
        ):
            raise ApproachReleaseFormatError("operation group IDs must be arrays")
        if operation.get("attempt_count") != len(operation["attempt_ids"]):
            raise ApproachReleaseFormatError("operation attempt_count is inconsistent")
        for attempt_id in operation["attempt_ids"]:
            if attempts_by_id[attempt_id].get("operation_id") != operation_id:
                raise ApproachReleaseFormatError("grouped attempt has the wrong operation owner")
        for case_id in operation["case_ids"]:
            if cases_by_id[case_id].get("operation_id") != operation_id:
                raise ApproachReleaseFormatError("grouped case has the wrong operation owner")


def _load_validated_release(path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate the release once, returning its canonical payloads."""
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ApproachReleaseFormatError("release root must be a real directory")
    manifest = validate_manifest(
        read_canonical_json(root / MANIFEST_NAME, limit=MAX_MANIFEST_BYTES)
    )
    expected = {MANIFEST_NAME, *(record["path"] for record in manifest["files"])}
    expected_directories = {
        parent.as_posix()
        for relative in expected
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    observed: set[str] = set()
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise ApproachReleaseFormatError(f"release contains symlink: {relative}")
        if candidate.is_file():
            observed.add(relative)
        elif candidate.is_dir():
            if relative not in expected_directories:
                raise ApproachReleaseFormatError(
                    f"release contains extra directory: {relative}"
                )
        else:
            raise ApproachReleaseFormatError(f"release contains non-regular member: {relative}")
    if observed != expected:
        raise ApproachReleaseFormatError(
            f"release layout mismatch: missing={sorted(expected - observed)}, "
            f"extra_files={sorted(observed - expected)}"
        )
    payloads: dict[str, Any] = {}
    for record in manifest["files"]:
        relative = record["path"]
        file_path = root.joinpath(*PurePosixPath(relative).parts)
        data = _read_regular(file_path, limit=FILE_LIMITS[relative])
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != record["bytes"] or digest != record["sha256"]:
            raise ApproachReleaseIntegrityError(f"release artifact mismatch: {relative}")
        value = parse_json_bytes(data, source=relative)
        if canonical_json_bytes(value) != data:
            raise ApproachReleaseFormatError(f"{relative} is not canonical JSON")
        payloads[relative] = value
    _validate_payloads(payloads)
    return manifest, payloads


def validate_release_directory(path: Path | str) -> dict[str, Any]:
    """Validate exact layout, canonical JSON, byte integrity, and cross references."""
    manifest, _payloads = _load_validated_release(path)
    return manifest


def load_release_directory(path: Path | str) -> dict[str, Any]:
    """Validate first, then load the bounded schema-v3 payload for serving."""
    manifest, payloads = _load_validated_release(path)
    return {
        "manifest": manifest,
        "attempts": payloads["attempts.json"]["attempts"],
        "cases": payloads["cases.json"]["cases"],
        "operations": payloads["operations.json"]["operations"],
        "metrics": payloads["metrics.json"],
        "config": payloads["config/approach-config.json"],
        "geometry": payloads["config/lemd-geometry.json"],
        "reference": payloads["reference/approach-reference.json"],
        "research": payloads.get("research/benchmark.json"),
    }


def write_release(root: Path | str, payloads: Mapping[str, Any], *, source: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any]:
    """Write canonical allowlisted artifacts and their content-derived manifest."""
    destination = Path(root)
    selected = set(payloads)
    missing = REQUIRED_FILES - selected
    extra = selected - ALLOWED_FILES
    if missing or extra:
        raise ApproachReleaseFormatError(
            f"release payload allowlist mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for relative in sorted(payloads):
        data = canonical_json_bytes(payloads[relative])
        if len(data) > FILE_LIMITS[relative]:
            raise ApproachReleaseFormatError(f"release payload exceeds byte limit: {relative}")
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    manifest: dict[str, Any] = {
        "schema_version": APPROACH_RELEASE_SCHEMA_VERSION,
        "release_kind": "sadar_approach_screening",
        "source": source,
        "contracts": contracts,
        "files": records,
    }
    manifest["release_id"] = release_id_for_manifest(manifest)
    (destination / MANIFEST_NAME).write_bytes(canonical_json_bytes(manifest))
    validate_release_directory(destination)
    return manifest
