"""Bounded, ephemeral rules-first evaluation of uploaded approach observations.

This module intentionally does not import the historical upload evaluator: that
module imports the Torch scoring stack at import time.  The parser and canonical
normalizer below preserve its public error contract while keeping approach
screening independent from model preparation and resampling.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.approach import assess_approach, extract_approach_attempts
from backend.core.approach_reference import load_approach_reference, validate_reference
from backend.core.derivations import add_flight_id
from backend.serve.release import canonical_json_bytes


SCHEMA_VERSION = "approach_upload_evaluation_v1"
INPUT_SCHEMA_VERSION = "opensky_raw_v1"
DERIVATION_CONTRACT_VERSION = "flight_id_gap_30m_v1"

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_RAW_ROWS = 50_000
MAX_PARQUET_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_OPERATIONS = 250
MAX_ATTEMPTS = 500
MAX_TRAJECTORY_POINTS = 300
MAX_CRITERION_EVIDENCE = 25
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

REQUIRED_COLUMNS = (
    "time", "icao24", "lat", "lon", "baroaltitude", "velocity", "heading",
    "vertrate", "onground",
)
OPTIONAL_COLUMNS = (
    "callsign", "squawk", "geoaltitude", "alert", "spi", "lastcontact",
)
ACCEPTED_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
DERIVED_COLUMNS = {
    "flight_id", "segment_id", "operation", "flight_phase", "dist_to_runway_m",
    "time_utc", "velocity_kmh", "is_emergency", "n_imputed_impossible",
    "n_imputed_missing",
}
_NULL_STRINGS = {"", "null", "none", "nan", "na"}
_MEDIA_TYPES = {
    ".csv": {
        "text/csv", "application/csv", "application/vnd.ms-excel",
        "application/octet-stream", "",
    },
    ".parquet": {
        "application/vnd.apache.parquet", "application/x-parquet",
        "application/octet-stream", "",
    },
}
_CANONICAL_PRECISION = {
    "lat": 8,
    "lon": 8,
    "baroaltitude": 6,
    "geoaltitude": 6,
    "velocity": 6,
    "heading": 6,
    "vertrate": 6,
    "lastcontact": 6,
}


@dataclass(frozen=True)
class EvaluationError(Exception):
    """API-safe error with the same semantics as the legacy upload evaluator."""

    status_code: int
    code: str
    message: str
    fields: tuple[dict[str, str], ...] = ()

    def detail(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.fields:
            result["fields"] = list(self.fields[:20])
        return result


def _field(field: str, message: str, code: str) -> dict[str, str]:
    return {"field": field, "message": message, "code": code}


def _is_null(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NULL_STRINGS
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _finite_number(value: Any, *, field: str, nullable: bool) -> float | None:
    if _is_null(value):
        if nullable:
            return None
        raise EvaluationError(
            422, "invalid_schema", "One or more fields are invalid.",
            (_field(field, "A value is required.", "required"),),
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EvaluationError(
            422, "invalid_schema", "One or more fields are invalid.",
            (_field(field, "Expected a numeric value.", "numeric"),),
        ) from exc
    if not math.isfinite(result):
        raise EvaluationError(
            422, "invalid_schema", "One or more fields are invalid.",
            (_field(field, "Expected a finite value.", "finite"),),
        )
    return result


def _boolean(value: Any, *, field: str, default_false: bool) -> tuple[bool | None, bool]:
    if _is_null(value):
        return (False if default_false else None), default_false
    if isinstance(value, (bool, np.bool_)):
        return bool(value), False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True, False
        if normalized in {"false", "0"}:
            return False, False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number) and number in {0.0, 1.0}:
            return bool(number), False
    raise EvaluationError(
        422, "invalid_schema", "One or more fields are invalid.",
        (_field(field, "Expected true, false, 0, 1, or null.", "boolean"),),
    )


def _validate_input_columns(names: list[str]) -> list[str]:
    if len(names) != len(set(names)):
        raise EvaluationError(422, "duplicate_columns", "The file contains duplicate column names.")
    missing = [name for name in REQUIRED_COLUMNS if name not in names]
    unknown = sorted(set(names) - set(ACCEPTED_COLUMNS) - DERIVED_COLUMNS)
    if missing or unknown:
        fields = tuple(
            [_field(name, "Required column is missing.", "required") for name in missing]
            + [_field(name, "Column is not supported.", "unsupported") for name in unknown[:20]]
        )
        raise EvaluationError(
            422, "invalid_schema", "The upload schema is not supported.", fields,
        )
    return [name for name in names if name in ACCEPTED_COLUMNS]


def _parse_csv(data: bytes) -> pd.DataFrame:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationError(422, "invalid_encoding", "CSV files must be UTF-8.") from exc
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = [name.strip() for name in next(rows)]
    except (StopIteration, csv.Error) as exc:
        raise EvaluationError(422, "invalid_csv", "The CSV header is missing or malformed.") from exc
    if not header or any(not name for name in header):
        raise EvaluationError(422, "invalid_csv", "Every CSV column must have a name.")
    materialized = _validate_input_columns(header)
    row_count = 0
    try:
        for row in rows:
            if not row:
                continue
            if len(row) != len(header):
                raise EvaluationError(
                    422, "invalid_csv", "Every CSV row must match the header width."
                )
            row_count += 1
            if row_count > MAX_RAW_ROWS:
                raise EvaluationError(
                    413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows."
                )
    except csv.Error as exc:
        raise EvaluationError(422, "invalid_csv", "The CSV body is malformed.") from exc
    string_columns = {
        name: "string" for name in ("icao24", "callsign") if name in materialized
    }
    try:
        return pd.read_csv(
            io.StringIO(text), header=0, names=header, usecols=materialized,
            dtype=string_columns, keep_default_na=True,
        )
    except Exception as exc:
        raise EvaluationError(422, "invalid_csv", "The CSV body is malformed.") from exc


def _parse_parquet(data: bytes) -> pd.DataFrame:
    try:
        parquet = pq.ParquetFile(io.BytesIO(data))
        schema = parquet.schema_arrow
        metadata = parquet.metadata
    except Exception as exc:
        raise EvaluationError(422, "invalid_parquet", "The Parquet file is malformed.") from exc
    materialized = _validate_input_columns(schema.names)
    if metadata.num_rows > MAX_RAW_ROWS:
        raise EvaluationError(
            413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows."
        )
    uncompressed = sum(
        metadata.row_group(group).column(column).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for column in range(metadata.row_group(group).num_columns)
    )
    if uncompressed > MAX_PARQUET_UNCOMPRESSED_BYTES:
        raise EvaluationError(
            413, "parquet_expansion_too_large", "The declared Parquet expansion is too large."
        )
    primitive = (
        pa.types.is_boolean, pa.types.is_integer, pa.types.is_floating,
        pa.types.is_string, pa.types.is_large_string, pa.types.is_null,
    )
    if any(not any(check(field.type) for check in primitive) for field in schema):
        raise EvaluationError(
            422, "nested_parquet", "Parquet columns must use flat primitive types."
        )
    try:
        return parquet.read(columns=materialized).to_pandas()
    except Exception as exc:
        raise EvaluationError(
            422, "invalid_parquet", "The Parquet data could not be read."
        ) from exc


def _parse(data: bytes, *, suffix: str, media_type: str) -> pd.DataFrame:
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if suffix not in _MEDIA_TYPES or normalized_type not in _MEDIA_TYPES[suffix]:
        raise EvaluationError(415, "unsupported_file_type", "Upload a CSV or Parquet file.")
    return _parse_csv(data) if suffix == ".csv" else _parse_parquet(data)


def _normalize(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, str]:
    if len(frame) > MAX_RAW_ROWS:
        raise EvaluationError(
            413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows."
        )
    _validate_input_columns(list(frame.columns))
    if frame.empty:
        raise EvaluationError(422, "empty_file", "The file contains no observations.")

    records: list[dict[str, Any]] = []
    for row_number, (_, source) in enumerate(frame.iterrows(), start=2):
        prefix = f"row[{row_number}]"
        time_value = _finite_number(source["time"], field=f"{prefix}.time", nullable=False)
        assert time_value is not None
        if not time_value.is_integer() or not 0 <= time_value <= 4_102_444_800:
            raise EvaluationError(
                422, "invalid_schema", "One or more fields are invalid.",
                (_field(
                    f"{prefix}.time", "Expected Unix seconds from 1970 through 2100.", "range",
                ),),
            )
        icao24 = "" if _is_null(source["icao24"]) else str(source["icao24"]).strip().lower()
        if not icao24:
            raise EvaluationError(
                422, "invalid_schema", "One or more fields are invalid.",
                (_field(f"{prefix}.icao24", "A value is required.", "required"),),
            )
        lat = _finite_number(source["lat"], field=f"{prefix}.lat", nullable=False)
        lon = _finite_number(source["lon"], field=f"{prefix}.lon", nullable=False)
        assert lat is not None and lon is not None
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise EvaluationError(
                422, "invalid_schema", "One or more fields are invalid.",
                (_field(prefix, "Latitude or longitude is outside WGS84 bounds.", "range"),),
            )
        onground, _ = _boolean(
            source["onground"], field=f"{prefix}.onground", default_false=True,
        )
        record: dict[str, Any] = {
            "time": int(time_value), "icao24": icao24, "lat": lat, "lon": lon,
            "baroaltitude": _finite_number(
                source["baroaltitude"], field=f"{prefix}.baroaltitude", nullable=True,
            ),
            "velocity": _finite_number(
                source["velocity"], field=f"{prefix}.velocity", nullable=True,
            ),
            "heading": _finite_number(
                source["heading"], field=f"{prefix}.heading", nullable=True,
            ),
            "vertrate": _finite_number(
                source["vertrate"], field=f"{prefix}.vertrate", nullable=True,
            ),
            "onground": bool(onground),
            "callsign": None, "squawk": None, "geoaltitude": None,
            "alert": None, "spi": None, "lastcontact": None,
        }
        if "callsign" in source and not _is_null(source["callsign"]):
            record["callsign"] = str(source["callsign"]).strip()
        if "squawk" in source and not _is_null(source["squawk"]):
            squawk = _finite_number(source["squawk"], field=f"{prefix}.squawk", nullable=True)
            if squawk is None or not squawk.is_integer():
                raise EvaluationError(
                    422, "invalid_schema", "One or more fields are invalid.",
                    (_field(f"{prefix}.squawk", "Expected an integer code.", "integer"),),
                )
            record["squawk"] = int(squawk)
        for name in ("geoaltitude", "lastcontact"):
            if name in source:
                record[name] = _finite_number(
                    source[name], field=f"{prefix}.{name}", nullable=True,
                )
        for name in ("alert", "spi"):
            if name in source:
                record[name], _ = _boolean(
                    source[name], field=f"{prefix}.{name}", default_false=False,
                )
        for name, digits in _CANONICAL_PRECISION.items():
            if record[name] is not None:
                record[name] = round(float(record[name]), digits)
        records.append(record)

    records.sort(key=lambda item: (item["icao24"], item["time"], canonical_json_bytes(item)))
    canonical: list[dict[str, Any]] = []
    duplicate_rows = 0
    index = 0
    while index < len(records):
        key = (records[index]["icao24"], records[index]["time"])
        group: list[dict[str, Any]] = []
        while index < len(records) and (records[index]["icao24"], records[index]["time"]) == key:
            group.append(records[index])
            index += 1
        variants = {canonical_json_bytes(item) for item in group}
        if len(variants) > 1:
            raise EvaluationError(
                422, "conflicting_observations",
                "Conflicting observations share the same aircraft and timestamp.",
            )
        canonical.append(group[0])
        duplicate_rows += len(group) - 1
    digest = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    return pd.DataFrame(canonical, columns=ACCEPTED_COLUMNS), duplicate_rows, digest


def _sample_indices(length: int) -> np.ndarray:
    if length <= MAX_TRAJECTORY_POINTS:
        return np.arange(length, dtype="int64")
    return np.unique(
        np.linspace(0, length - 1, MAX_TRAJECTORY_POINTS, dtype="int64")
    )


def _nullable_number(value: Any, *, digits: int) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _observed_payload(frame: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered = frame.sort_values("time").reset_index(drop=True)
    indices = _sample_indices(len(ordered))
    sampled = ordered.iloc[indices]
    time = [int(value) for value in sampled["time"]]
    trajectory = {
        "observed_points": int(len(ordered)),
        "returned_points": int(len(sampled)),
        "sampling": "all_observed" if len(sampled) == len(ordered) else "evenly_spaced_v1",
        "points": [
            {
                "time": int(row.time),
                "lat": _nullable_number(row.lat, digits=6),
                "lon": _nullable_number(row.lon, digits=6),
            }
            for row in sampled.itertuples(index=False)
        ],
    }
    channels = {
        "time": time,
        "barometric_altitude_m": [
            _nullable_number(value, digits=1) for value in sampled["baroaltitude"]
        ],
        "geometric_altitude_m": [
            _nullable_number(value, digits=1) for value in sampled["geoaltitude"]
        ],
        "ground_speed_mps": [
            _nullable_number(value, digits=2) for value in sampled["velocity"]
        ],
        "vertical_rate_mps": [
            _nullable_number(value, digits=2) for value in sampled["vertrate"]
        ],
        "ground_track_deg": [
            _nullable_number(value, digits=2) for value in sampled["heading"]
        ],
        "onground": [bool(value) for value in sampled["onground"]],
    }
    return trajectory, channels


def _bounded_criteria(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bounded = []
    for criterion in criteria:
        evidence = list(criterion.get("evidence", []))
        item = {key: value for key, value in criterion.items() if key != "evidence"}
        item["evidence"] = evidence[:MAX_CRITERION_EVIDENCE]
        item["evidence_truncated"] = max(0, len(evidence) - MAX_CRITERION_EVIDENCE)
        bounded.append(item)
    return bounded


def _result(
    *,
    assessment: dict[str, Any],
    attempt_frame: pd.DataFrame,
    dataset_digest: str,
    operation_id: str,
    attempt_index: int,
) -> dict[str, Any]:
    attempt = dict(assessment.get("attempt", {}))
    reference_material = {
        "dataset_digest": dataset_digest,
        "operation_id": operation_id,
        "attempt_index": attempt_index,
        "start_time": attempt.get("start_time"),
        "end_time": attempt.get("end_time"),
    }
    evaluation_ref = "ae_" + hashlib.sha256(
        canonical_json_bytes(reference_material)
    ).hexdigest()[:20]
    inference = assessment["runway_inference"]
    trajectory, channels = _observed_payload(attempt_frame)
    return {
        "evaluation_ref": evaluation_ref,
        "operation_id": operation_id,
        "attempt_index": attempt_index,
        "attempt": attempt,
        "status": assessment["status"],
        "runway": {
            "designator": inference.get("runway"),
            "geometry_runway": inference.get("geometry_runway"),
            "direction": inference.get("direction"),
            "specificity": inference.get("specificity"),
            "confidence": inference.get("confidence"),
        },
        "failed_criteria": list(assessment.get("failed_criteria", [])),
        "reasons": list(assessment.get("reasons", [])),
        "quality": assessment.get("quality", {}),
        "criteria": _bounded_criteria(assessment.get("criteria", [])),
        "maneuvers": list(assessment.get("maneuvers", [])),
        "provenance": {
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "derivation_contract_version": DERIVATION_CONTRACT_VERSION,
            "engine_version": assessment["engine_version"],
            **assessment["provenance"],
            "geometry": assessment["geometry"],
            "reference": assessment["reference"],
        },
        "trajectory": trajectory,
        "channels": channels,
    }


class ApproachUploadEvaluationService:
    """Evaluate raw OpenSky observations with the published approach contract."""

    def __init__(
        self,
        *,
        release_id: str,
        reference: dict[str, Any] | None = None,
    ) -> None:
        if not release_id:
            raise ValueError("release_id is required")
        self.release_id = release_id
        self.reference = reference if reference is not None else load_approach_reference()
        validate_reference(self.reference)

    def evaluate(
        self,
        data: bytes,
        *,
        filename: str,
        media_type: str,
    ) -> dict[str, Any]:
        if not data:
            raise EvaluationError(422, "empty_file", "The file contains no observations.")
        if len(data) > MAX_INPUT_BYTES:
            raise EvaluationError(
                413, "request_too_large", "The upload exceeds the 10 MiB limit."
            )
        suffix = PurePath(filename or "").suffix.lower()
        upload_sha256 = hashlib.sha256(data).hexdigest()
        raw = _parse(data, suffix=suffix, media_type=media_type)
        raw_rows = int(len(raw))
        normalized, duplicate_rows, dataset_digest = _normalize(raw)
        operations_frame = add_flight_id(normalized)
        operation_groups = list(operations_frame.groupby("flight_id", sort=True))
        if len(operation_groups) > MAX_OPERATIONS:
            raise EvaluationError(
                413, "too_many_operations",
                f"At most {MAX_OPERATIONS} candidate operations are accepted.",
            )

        results: list[dict[str, Any]] = []
        for operation_id, operation in operation_groups:
            attempt_frames = extract_approach_attempts(operation)
            if len(results) + len(attempt_frames) > MAX_ATTEMPTS:
                raise EvaluationError(
                    413, "too_many_attempts",
                    f"At most {MAX_ATTEMPTS} approach attempts are accepted.",
                )
            for attempt_index, attempt_frame in enumerate(attempt_frames, start=1):
                assessment = assess_approach(
                    attempt_frame,
                    operation_id=f"{operation_id}:attempt-{attempt_index}",
                    reference=self.reference,
                )
                results.append(_result(
                    assessment=assessment,
                    attempt_frame=attempt_frame,
                    dataset_digest=dataset_digest,
                    operation_id=str(operation_id),
                    attempt_index=attempt_index,
                ))

        status_counts: dict[str, int] = {}
        for result in results:
            status = str(result["status"])
            status_counts[status] = status_counts.get(status, 0) + 1
        response = {
            "schema_version": SCHEMA_VERSION,
            "release_id": self.release_id,
            "reference_sha256": self.reference["artifact_sha256"],
            "dataset_digest": dataset_digest,
            "upload_sha256": upload_sha256,
            "raw_rows": raw_rows,
            "canonical_rows": int(len(normalized)),
            "duplicate_rows_collapsed": duplicate_rows,
            "operations": len(operation_groups),
            "attempts": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "results": results,
        }
        if len(canonical_json_bytes(response)) > MAX_RESPONSE_BYTES:
            raise EvaluationError(
                413, "evaluation_response_too_large",
                "The bounded evaluation result exceeds the response limit.",
            )
        return response
