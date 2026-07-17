"""Public limits, schema, and API-safe failures for uploaded evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
CONTEXT_COLUMNS = (
    "qnh_hpa",
    "wind_from_direction_deg",
    "wind_speed_mps",
    "aircraft_typecode",
)
WEATHER_CONTEXT_COLUMNS = (
    "qnh_hpa",
    "wind_from_direction_deg",
    "wind_speed_mps",
)
REQUIRED_COLUMNS = (
    "time",
    "icao24",
    "lat",
    "lon",
    "baroaltitude",
    "velocity",
    "heading",
    "vertrate",
    "onground",
)
OPTIONAL_COLUMNS = (
    "callsign",
    "squawk",
    "geoaltitude",
    "alert",
    "spi",
    "lastcontact",
    "qnh_hpa",
    "wind_from_direction_deg",
    "wind_speed_mps",
    "aircraft_typecode",
)
ACCEPTED_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
DERIVED_COLUMNS = {
    "flight_id",
    "segment_id",
    "operation",
    "flight_phase",
    "dist_to_runway_m",
    "time_utc",
    "velocity_kmh",
    "is_emergency",
    "n_imputed_impossible",
    "n_imputed_missing",
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


def field_error(field: str, message: str, code: str) -> dict[str, str]:
    return {"field": field, "message": message, "code": code}
