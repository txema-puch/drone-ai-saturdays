"""Bounded, ephemeral upload evaluation.

    multipart bytes -> bounded CSV/Parquet parse -> typed raw observations
      -> canonicalize/dedupe/hash -> core derivations -> core preprocessing
      -> vectorized frozen-model score -> upload-only evidence allowlist

No filename, raw row, or uploaded byte is logged or persisted by this module.
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

from sadar_research.trajectory_anomaly.data.derivations import apply_derivations
from sadar_research.trajectory_anomaly.pipeline.preprocessing import GAP_SPLIT_S, GRID_S, preprocess, to_sequences_loss_mask
from sadar_research.trajectory_anomaly.releases.schema import canonical_json_bytes
from sadar_research.trajectory_anomaly.evaluation.scoring import assemble_segment_evidence, score_segments

MAX_MULTIPART_BYTES = 10 * 1024 * 1024
MAX_RAW_ROWS = 50_000
MAX_ACCEPTED_SEGMENTS = 25
MAX_GRID_ROWS = 100_000
MAX_PREPROCESS_SEGMENTS = 100
MAX_PARQUET_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
INPUT_SCHEMA_VERSION = "opensky_raw_v1"
DERIVATION_CONTRACT_VERSION = "derivations_v1"
PREPROCESSING_CONTRACT_VERSION = "preprocessing_v1"
LEMD_CENTER = {"lat": 40.4936, "lon": -3.5668}

REQUIRED_COLUMNS = (
    "time", "icao24", "lat", "lon", "baroaltitude", "velocity", "heading",
    "vertrate", "onground",
)
OPTIONAL_COLUMNS = (
    "callsign", "squawk", "geoaltitude", "alert", "spi", "lastcontact",
)
DERIVED_COLUMNS = {
    "flight_id", "segment_id", "operation", "flight_phase", "dist_to_runway_m",
    "time_utc", "velocity_kmh", "is_emergency", "n_imputed_impossible",
    "n_imputed_missing",
}
ACCEPTED_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
_NULL_STRINGS = {"", "null", "none", "nan", "na"}
_MEDIA_TYPES = {
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream", ""},
    ".parquet": {"application/vnd.apache.parquet", "application/x-parquet", "application/octet-stream", ""},
}


@dataclass(frozen=True)
class EvaluationError(Exception):
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
        raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
            _field(field, "A value is required.", "required"),
        ))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
            _field(field, "Expected a numeric value.", "numeric"),
        )) from exc
    if not math.isfinite(result):
        raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
            _field(field, "Expected a finite value.", "finite"),
        ))
    return result


def _boolean(value: Any, *, field: str, default_false: bool) -> tuple[bool | None, bool]:
    if _is_null(value):
        return (False if default_false else None), default_false
    if isinstance(value, (bool, np.bool_)):
        return bool(value), False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True, False
        if normalized in ("false", "0"):
            return False, False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number) and number in (0.0, 1.0):
            return bool(number), False
    raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
        _field(field, "Expected true, false, 0, 1, or null.", "boolean"),
    ))


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
        raise EvaluationError(422, "invalid_schema", "The upload schema is not supported.", fields)
    return [name for name in names if name in ACCEPTED_COLUMNS]


def _parse_csv(data: bytes) -> pd.DataFrame:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationError(422, "invalid_encoding", "CSV files must be UTF-8.") from exc
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(rows)
    except (StopIteration, csv.Error) as exc:
        raise EvaluationError(422, "invalid_csv", "The CSV header is missing or malformed.") from exc
    header = [name.strip() for name in header]
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
    string_columns = {name: "string" for name in ("icao24", "callsign") if name in materialized}
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
        raise EvaluationError(413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows.")
    uncompressed = sum(
        metadata.row_group(group).column(column).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for column in range(metadata.row_group(group).num_columns)
    )
    if uncompressed > MAX_PARQUET_UNCOMPRESSED_BYTES:
        raise EvaluationError(413, "parquet_expansion_too_large", "The declared Parquet expansion is too large.")
    primitive = (
        pa.types.is_boolean, pa.types.is_integer, pa.types.is_floating,
        pa.types.is_string, pa.types.is_large_string, pa.types.is_null,
    )
    if any(not any(check(field.type) for check in primitive) for field in schema):
        raise EvaluationError(422, "nested_parquet", "Parquet columns must use flat primitive types.")
    try:
        return parquet.read(columns=materialized).to_pandas()
    except Exception as exc:
        raise EvaluationError(422, "invalid_parquet", "The Parquet data could not be read.") from exc


def _parse(data: bytes, *, suffix: str, media_type: str) -> pd.DataFrame:
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if suffix not in _MEDIA_TYPES or normalized_type not in _MEDIA_TYPES[suffix]:
        raise EvaluationError(415, "unsupported_file_type", "Upload a CSV or Parquet file.")
    return _parse_csv(data) if suffix == ".csv" else _parse_parquet(data)


def _normalize(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, int, str]:
    if len(frame) > MAX_RAW_ROWS:
        raise EvaluationError(413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows.")
    _validate_input_columns(list(frame.columns))
    if len(frame) == 0:
        raise EvaluationError(422, "empty_file", "The file contains no observations.")

    records: list[dict[str, Any]] = []
    onground_defaulted = 0
    for row_number, (_, source) in enumerate(frame.iterrows(), start=2):
        prefix = f"row[{row_number}]"
        time_value = _finite_number(source["time"], field=f"{prefix}.time", nullable=False)
        assert time_value is not None
        if not time_value.is_integer() or not 0 <= time_value <= 4_102_444_800:
            raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
                _field(f"{prefix}.time", "Expected Unix seconds from 1970 through 2100.", "range"),
            ))
        icao24 = "" if _is_null(source["icao24"]) else str(source["icao24"]).strip().lower()
        if not icao24:
            raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
                _field(f"{prefix}.icao24", "A value is required.", "required"),
            ))
        lat = _finite_number(source["lat"], field=f"{prefix}.lat", nullable=False)
        lon = _finite_number(source["lon"], field=f"{prefix}.lon", nullable=False)
        assert lat is not None and lon is not None
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
                _field(prefix, "Latitude or longitude is outside WGS84 bounds.", "range"),
            ))
        onground, defaulted = _boolean(
            source["onground"], field=f"{prefix}.onground", default_false=True
        )
        onground_defaulted += int(defaulted)
        record: dict[str, Any] = {
            "time": int(time_value), "icao24": icao24, "lat": lat, "lon": lon,
            "baroaltitude": _finite_number(source["baroaltitude"], field=f"{prefix}.baroaltitude", nullable=True),
            "velocity": _finite_number(source["velocity"], field=f"{prefix}.velocity", nullable=True),
            "heading": _finite_number(source["heading"], field=f"{prefix}.heading", nullable=True),
            "vertrate": _finite_number(source["vertrate"], field=f"{prefix}.vertrate", nullable=True),
            "onground": bool(onground),
            "callsign": None,
            "squawk": None,
            "geoaltitude": None,
            "alert": None,
            "spi": None,
            "lastcontact": None,
        }
        if "callsign" in source and not _is_null(source["callsign"]):
            record["callsign"] = str(source["callsign"]).strip()
        if "squawk" in source and not _is_null(source["squawk"]):
            squawk = _finite_number(source["squawk"], field=f"{prefix}.squawk", nullable=True)
            if squawk is None or not squawk.is_integer():
                raise EvaluationError(422, "invalid_schema", "One or more fields are invalid.", (
                    _field(f"{prefix}.squawk", "Expected an integer code.", "integer"),
                ))
            record["squawk"] = int(squawk)
        for name in ("geoaltitude", "lastcontact"):
            if name in source:
                record[name] = _finite_number(source[name], field=f"{prefix}.{name}", nullable=True)
        for name in ("alert", "spi"):
            if name in source:
                record[name], _ = _boolean(source[name], field=f"{prefix}.{name}", default_false=False)
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
            raise EvaluationError(422, "conflicting_observations", "Conflicting observations share the same aircraft and timestamp.")
        canonical.append(group[0])
        duplicate_rows += len(group) - 1
    digest = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    return pd.DataFrame(canonical, columns=ACCEPTED_COLUMNS), duplicate_rows, onground_defaulted, digest


def _preprocessing_projection(frame: pd.DataFrame) -> tuple[int, int]:
    """Conservatively bound 10-second resampling before any grid is allocated."""
    if frame.empty:
        return 0, 0
    ordered = frame[["flight_id", "time"]].sort_values(["flight_id", "time"]).copy()
    gaps = ordered.groupby("flight_id", sort=False)["time"].diff()
    starts = gaps.isna() | (gaps > GAP_SPLIT_S)
    ordered["_upload_segment"] = starts.groupby(ordered["flight_id"]).cumsum()
    spans = ordered.groupby(["flight_id", "_upload_segment"], sort=False)["time"].agg(["min", "max"])
    rows = int((((spans["max"] - spans["min"] + GRID_S - 1) // GRID_S) + 1).sum())
    return rows, int(len(spans))


def _reason(code: str, message: str, count: int) -> dict[str, Any] | None:
    return {"code": code, "message": message, "count": int(count)} if count else None


class UploadEvaluationService:
    def __init__(self, *, release_id: str, model_id: str) -> None:
        self.release_id = release_id
        self.model_id = model_id

    def evaluate(
        self,
        data: bytes,
        *,
        filename: str,
        media_type: str,
        loaded,
    ) -> dict[str, Any]:
        if not data:
            raise EvaluationError(422, "empty_file", "The file contains no observations.")
        if len(data) > MAX_MULTIPART_BYTES:
            raise EvaluationError(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
        suffix = PurePath(filename or "").suffix.lower()
        upload_sha256 = hashlib.sha256(data).hexdigest()
        raw = _parse(data, suffix=suffix, media_type=media_type)
        raw_rows = int(len(raw))
        normalized, duplicate_rows, onground_defaulted, dataset_digest = _normalize(raw)

        derivation_diagnostics: dict[str, int] = {}
        derived = apply_derivations(normalized, diagnostics=derivation_diagnostics)
        projected_grid_rows, projected_segments = _preprocessing_projection(derived)
        if projected_segments > MAX_PREPROCESS_SEGMENTS:
            raise EvaluationError(
                413,
                "too_many_segments",
                f"The upload creates more than {MAX_PREPROCESS_SEGMENTS} preprocessing segments.",
            )
        if projected_grid_rows > MAX_GRID_ROWS:
            raise EvaluationError(
                413,
                "derived_rows_too_large",
                f"The upload would create more than {MAX_GRID_ROWS} resampled rows.",
            )
        preprocessing_diagnostics: dict[str, int] = {}
        clean, _ = preprocess(derived, diagnostics=preprocessing_diagnostics)
        contract = loaded.model_contract["scoring_contract"]
        if not clean.empty:
            segment_ids = [
                str(segment_id) for segment_id, _ in clean.groupby("segment_id", sort=False)
            ]
            masks = to_sequences_loss_mask(clean, int(contract["T"]))
            unscorable = {
                segment_id
                for segment_id, mask in zip(segment_ids, masks, strict=True)
                if int(mask.sum()) == 0
            }
            preprocessing_diagnostics["unscorable_segments"] = len(unscorable)
            if unscorable:
                clean = clean.loc[~clean["segment_id"].astype(str).isin(unscorable)].copy()
        accepted_segments = int(clean["segment_id"].nunique()) if not clean.empty else 0
        if accepted_segments > MAX_ACCEPTED_SEGMENTS:
            raise EvaluationError(413, "too_many_segments", f"At most {MAX_ACCEPTED_SEGMENTS} assessable segments are accepted.")

        reasons = [
            _reason("outside_lemd_radius", "Observations outside the LEMD collection radius.", derivation_diagnostics.get("outside_radius_rows", 0)),
            _reason("filter_b_rejected", "Trajectories did not approach LEMD closely and low enough.", derivation_diagnostics.get("filter_b_trajectories", 0)),
            _reason("filter_d_rejected", "Segments did not engage the frozen LEMD operation gate.", preprocessing_diagnostics.get("filter_d_segments", 0)),
            _reason("idle_rejected", "Segments contained no assessable airborne movement.", preprocessing_diagnostics.get("idle_segments", 0)),
            _reason("short_rejected", "Segments were shorter than the frozen minimum window.", preprocessing_diagnostics.get("short_segments", 0)),
            _reason("unscorable_rejected", "Segments contained no observed model timesteps.", preprocessing_diagnostics.get("unscorable_segments", 0)),
            _reason("impossible_observations", "Measured values outside frozen physical bounds were imputed.", preprocessing_diagnostics.get("impossible_observations", 0)),
            _reason("missing_observations", "Missing measured values were imputed by the frozen pipeline.", preprocessing_diagnostics.get("missing_observations", 0)),
            _reason("onground_defaulted", "Null onground values were treated as false.", onground_defaulted),
        ]
        rejection_reasons = [item for item in reasons if item is not None]
        rejected_segments = sum(
            derivation_diagnostics.get(name, 0)
            for name in ("filter_b_trajectories",)
        ) + sum(
            preprocessing_diagnostics.get(name, 0)
            for name in ("filter_d_segments", "idle_segments", "short_segments", "unscorable_segments")
        )

        results: list[dict[str, Any]] = []
        if accepted_segments:
            T = int(contract["T"])
            scored = score_segments(
                clean, T=T, scaler=loaded.scaler, model=loaded.model,
            )
            frames = {
                str(segment_id): frame
                for segment_id, frame in clean.groupby("segment_id", sort=False)
            }
            for index, segment_id in enumerate(scored["segment_ids"]):
                reference = "e_" + hashlib.sha256(
                    f"{dataset_digest}|{segment_id}".encode("utf-8")
                ).hexdigest()[:20]
                results.append(assemble_segment_evidence(
                    frames[segment_id], scored, index,
                    evaluation_ref=reference,
                    T=T,
                    scaler=loaded.scaler,
                    threshold=float(contract["threshold"]),
                    step_threshold=float(contract["step_threshold"]),
                    cohort_scores=loaded.cohort_reference,
                    center=LEMD_CENTER,
                    step_seconds=GRID_S,
                ))

        response = {
            "release_id": self.release_id,
            "model_id": self.model_id,
            "dataset_digest": dataset_digest,
            "upload_sha256": upload_sha256,
            "raw_rows": raw_rows,
            "derived_rows": int(len(derived)),
            "accepted_rows": int(len(clean)),
            "accepted_segments": accepted_segments,
            "rejected_segments": int(rejected_segments),
            "duplicate_rows_collapsed": duplicate_rows,
            "rejection_reasons": rejection_reasons,
            "results": results,
        }
        if len(canonical_json_bytes(response)) > MAX_RESPONSE_BYTES:
            raise EvaluationError(
                413,
                "evaluation_response_too_large",
                "The bounded evaluation result exceeds the response limit.",
            )
        return response
