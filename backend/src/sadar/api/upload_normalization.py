"""Canonical validation and normalization for uploaded observations."""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from sadar.api.upload_contract import (
    ACCEPTED_COLUMNS,
    MAX_RAW_ROWS,
    EvaluationError,
    field_error,
)
from sadar.api.upload_parsing import boolean, finite_number, is_null, validate_input_columns
from sadar.releases.approach import canonical_json_bytes


_CANONICAL_PRECISION = {
    "lat": 8,
    "lon": 8,
    "baroaltitude": 6,
    "geoaltitude": 6,
    "velocity": 6,
    "heading": 6,
    "vertrate": 6,
    "lastcontact": 6,
    "qnh_hpa": 2,
    "wind_from_direction_deg": 2,
    "wind_speed_mps": 3,
}


def normalize_upload(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, str]:
    if len(frame) > MAX_RAW_ROWS:
        raise EvaluationError(
            413, "too_many_rows", f"Files may contain at most {MAX_RAW_ROWS} rows."
        )
    validate_input_columns(list(frame.columns))
    if frame.empty:
        raise EvaluationError(422, "empty_file", "The file contains no observations.")

    records: list[dict[str, Any]] = []
    for row_number, (_, source) in enumerate(frame.iterrows(), start=2):
        prefix = f"row[{row_number}]"
        time_value = finite_number(source["time"], field=f"{prefix}.time", nullable=False)
        assert time_value is not None
        if not time_value.is_integer() or not 0 <= time_value <= 4_102_444_800:
            raise EvaluationError(
                422,
                "invalid_schema",
                "One or more fields are invalid.",
                (field_error(
                    f"{prefix}.time",
                    "Expected Unix seconds from 1970 through 2100.",
                    "range",
                ),),
            )
        icao24 = "" if is_null(source["icao24"]) else str(source["icao24"]).strip().lower()
        if not icao24:
            raise EvaluationError(
                422,
                "invalid_schema",
                "One or more fields are invalid.",
                (field_error(f"{prefix}.icao24", "A value is required.", "required"),),
            )
        lat = finite_number(source["lat"], field=f"{prefix}.lat", nullable=False)
        lon = finite_number(source["lon"], field=f"{prefix}.lon", nullable=False)
        assert lat is not None and lon is not None
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise EvaluationError(
                422,
                "invalid_schema",
                "One or more fields are invalid.",
                (field_error(
                    prefix,
                    "Latitude or longitude is outside WGS84 bounds.",
                    "range",
                ),),
            )
        onground, _ = boolean(
            source["onground"], field=f"{prefix}.onground", default_false=True
        )
        record: dict[str, Any] = {
            "time": int(time_value),
            "icao24": icao24,
            "lat": lat,
            "lon": lon,
            "baroaltitude": finite_number(
                source["baroaltitude"], field=f"{prefix}.baroaltitude", nullable=True
            ),
            "velocity": finite_number(
                source["velocity"], field=f"{prefix}.velocity", nullable=True
            ),
            "heading": finite_number(
                source["heading"], field=f"{prefix}.heading", nullable=True
            ),
            "vertrate": finite_number(
                source["vertrate"], field=f"{prefix}.vertrate", nullable=True
            ),
            "onground": bool(onground),
            "callsign": None,
            "squawk": None,
            "geoaltitude": None,
            "alert": None,
            "spi": None,
            "lastcontact": None,
            "qnh_hpa": None,
            "wind_from_direction_deg": None,
            "wind_speed_mps": None,
            "aircraft_typecode": None,
        }
        if "callsign" in source and not is_null(source["callsign"]):
            record["callsign"] = str(source["callsign"]).strip()
        if "squawk" in source and not is_null(source["squawk"]):
            squawk = finite_number(
                source["squawk"], field=f"{prefix}.squawk", nullable=True
            )
            if squawk is None or not squawk.is_integer():
                raise EvaluationError(
                    422,
                    "invalid_schema",
                    "One or more fields are invalid.",
                    (field_error(
                        f"{prefix}.squawk", "Expected an integer code.", "integer"
                    ),),
                )
            record["squawk"] = int(squawk)
        for name in ("geoaltitude", "lastcontact"):
            if name in source:
                record[name] = finite_number(
                    source[name], field=f"{prefix}.{name}", nullable=True
                )
        if "qnh_hpa" in source:
            record["qnh_hpa"] = finite_number(
                source["qnh_hpa"], field=f"{prefix}.qnh_hpa", nullable=True
            )
            if record["qnh_hpa"] is not None and not 850 <= record["qnh_hpa"] <= 1100:
                raise EvaluationError(
                    422,
                    "invalid_schema",
                    "One or more fields are invalid.",
                    (field_error(
                        f"{prefix}.qnh_hpa", "Expected 850 through 1100 hPa.", "range"
                    ),),
                )
        if "wind_from_direction_deg" in source:
            record["wind_from_direction_deg"] = finite_number(
                source["wind_from_direction_deg"],
                field=f"{prefix}.wind_from_direction_deg",
                nullable=True,
            )
            direction = record["wind_from_direction_deg"]
            if direction is not None and not 0 <= direction <= 360:
                raise EvaluationError(
                    422,
                    "invalid_schema",
                    "One or more fields are invalid.",
                    (field_error(
                        f"{prefix}.wind_from_direction_deg",
                        "Expected 0 through 360 degrees.",
                        "range",
                    ),),
                )
            if direction == 360:
                record["wind_from_direction_deg"] = 0.0
        if "wind_speed_mps" in source:
            record["wind_speed_mps"] = finite_number(
                source["wind_speed_mps"], field=f"{prefix}.wind_speed_mps", nullable=True
            )
            if record["wind_speed_mps"] is not None and record["wind_speed_mps"] < 0:
                raise EvaluationError(
                    422,
                    "invalid_schema",
                    "One or more fields are invalid.",
                    (field_error(
                        f"{prefix}.wind_speed_mps", "Expected zero or greater.", "range"
                    ),),
                )
        if "aircraft_typecode" in source and not is_null(source["aircraft_typecode"]):
            typecode = str(source["aircraft_typecode"]).strip().upper()
            if len(typecode) > 16:
                raise EvaluationError(
                    422,
                    "invalid_schema",
                    "One or more fields are invalid.",
                    (field_error(
                        f"{prefix}.aircraft_typecode",
                        "Expected at most 16 characters.",
                        "length",
                    ),),
                )
            record["aircraft_typecode"] = typecode or None
        for name in ("alert", "spi"):
            if name in source:
                record[name], _ = boolean(
                    source[name], field=f"{prefix}.{name}", default_false=False
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
                422,
                "conflicting_observations",
                "Conflicting observations share the same aircraft and timestamp.",
            )
        canonical.append(group[0])
        duplicate_rows += len(group) - 1
    digest = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    return pd.DataFrame(canonical, columns=ACCEPTED_COLUMNS), duplicate_rows, digest
