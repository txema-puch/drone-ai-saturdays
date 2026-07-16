"""Bounded CSV/Parquet parsing and scalar validation."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from sadar.api.upload_contract import (
    ACCEPTED_COLUMNS,
    DERIVED_COLUMNS,
    MAX_PARQUET_UNCOMPRESSED_BYTES,
    MAX_RAW_ROWS,
    REQUIRED_COLUMNS,
    EvaluationError,
    field_error,
)

NULL_STRINGS = {"", "null", "none", "nan", "na"}
MEDIA_TYPES = {
    ".csv": {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "",
    },
    ".parquet": {
        "application/vnd.apache.parquet",
        "application/x-parquet",
        "application/octet-stream",
        "",
    },
}


def is_null(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, str):
        return value.strip().lower() in NULL_STRINGS
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def finite_number(value: Any, *, field: str, nullable: bool) -> float | None:
    if is_null(value):
        if nullable:
            return None
        raise EvaluationError(
            422,
            "invalid_schema",
            "One or more fields are invalid.",
            (field_error(field, "A value is required.", "required"),),
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EvaluationError(
            422,
            "invalid_schema",
            "One or more fields are invalid.",
            (field_error(field, "Expected a numeric value.", "numeric"),),
        ) from exc
    if not math.isfinite(result):
        raise EvaluationError(
            422,
            "invalid_schema",
            "One or more fields are invalid.",
            (field_error(field, "Expected a finite value.", "finite"),),
        )
    return result


def boolean(
    value: Any, *, field: str, default_false: bool
) -> tuple[bool | None, bool]:
    if is_null(value):
        return (False if default_false else None), default_false
    if isinstance(value, (bool, np.bool_)):
        return bool(value), False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True, False
        if normalized in {"false", "0"}:
            return False, False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, bool
    ):
        number = float(value)
        if math.isfinite(number) and number in {0.0, 1.0}:
            return bool(number), False
    raise EvaluationError(
        422,
        "invalid_schema",
        "One or more fields are invalid.",
        (field_error(field, "Expected true, false, 0, 1, or null.", "boolean"),),
    )


def validate_input_columns(names: list[str]) -> list[str]:
    if len(names) != len(set(names)):
        raise EvaluationError(
            422, "duplicate_columns", "The file contains duplicate column names."
        )
    missing = [name for name in REQUIRED_COLUMNS if name not in names]
    unknown = sorted(set(names) - set(ACCEPTED_COLUMNS) - DERIVED_COLUMNS)
    if missing or unknown:
        fields = tuple(
            [
                field_error(name, "Required column is missing.", "required")
                for name in missing
            ]
            + [
                field_error(name, "Column is not supported.", "unsupported")
                for name in unknown[:20]
            ]
        )
        raise EvaluationError(
            422,
            "invalid_schema",
            "The upload schema is not supported.",
            fields,
        )
    return [name for name in names if name in ACCEPTED_COLUMNS]


def parse_csv(data: bytes) -> pd.DataFrame:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationError(
            422, "invalid_encoding", "CSV files must be UTF-8."
        ) from exc
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = [name.strip() for name in next(rows)]
    except (StopIteration, csv.Error) as exc:
        raise EvaluationError(
            422, "invalid_csv", "The CSV header is missing or malformed."
        ) from exc
    if not header or any(not name for name in header):
        raise EvaluationError(
            422, "invalid_csv", "Every CSV column must have a name."
        )
    materialized = validate_input_columns(header)
    row_count = 0
    try:
        for row in rows:
            if not row:
                continue
            if len(row) != len(header):
                raise EvaluationError(
                    422,
                    "invalid_csv",
                    "Every CSV row must match the header width.",
                )
            row_count += 1
            if row_count > MAX_RAW_ROWS:
                raise EvaluationError(
                    413,
                    "too_many_rows",
                    f"Files may contain at most {MAX_RAW_ROWS} rows.",
                )
    except csv.Error as exc:
        raise EvaluationError(
            422, "invalid_csv", "The CSV body is malformed."
        ) from exc
    string_columns = {
        name: "string"
        for name in ("icao24", "callsign", "aircraft_typecode")
        if name in materialized
    }
    try:
        return pd.read_csv(
            io.StringIO(text),
            header=0,
            names=header,
            usecols=materialized,
            dtype=string_columns,
            keep_default_na=True,
        )
    except Exception as exc:
        raise EvaluationError(
            422, "invalid_csv", "The CSV body is malformed."
        ) from exc


def parse_parquet(data: bytes) -> pd.DataFrame:
    try:
        parquet = pq.ParquetFile(io.BytesIO(data))
        schema = parquet.schema_arrow
        metadata = parquet.metadata
    except Exception as exc:
        raise EvaluationError(
            422, "invalid_parquet", "The Parquet file is malformed."
        ) from exc
    materialized = validate_input_columns(schema.names)
    if metadata.num_rows > MAX_RAW_ROWS:
        raise EvaluationError(
            413,
            "too_many_rows",
            f"Files may contain at most {MAX_RAW_ROWS} rows.",
        )
    uncompressed = sum(
        metadata.row_group(group).column(column).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for column in range(metadata.row_group(group).num_columns)
    )
    if uncompressed > MAX_PARQUET_UNCOMPRESSED_BYTES:
        raise EvaluationError(
            413,
            "parquet_expansion_too_large",
            "The declared Parquet expansion is too large.",
        )
    primitive = (
        pa.types.is_boolean,
        pa.types.is_integer,
        pa.types.is_floating,
        pa.types.is_string,
        pa.types.is_large_string,
        pa.types.is_null,
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


def parse_upload(data: bytes, *, suffix: str, media_type: str) -> pd.DataFrame:
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if suffix not in MEDIA_TYPES or normalized_type not in MEDIA_TYPES[suffix]:
        raise EvaluationError(
            415, "unsupported_file_type", "Upload a CSV or Parquet file."
        )
    return parse_csv(data) if suffix == ".csv" else parse_parquet(data)
