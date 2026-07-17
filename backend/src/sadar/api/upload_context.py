"""Validation and construction of analyst-supplied approach context."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from sadar.api.upload_contract import (
    WEATHER_CONTEXT_COLUMNS,
    EvaluationError,
    field_error,
)
from sadar.approach.context import WeatherObservation


def supplied_context(
    operation: pd.DataFrame,
) -> tuple[list[WeatherObservation], dict[str, str] | None]:
    supplied_weather_fields = [
        field for field in WEATHER_CONTEXT_COLUMNS if operation[field].notna().any()
    ]
    if supplied_weather_fields:
        context_rows = operation[supplied_weather_fields].notna().any(axis=1)
        if operation.loc[context_rows, supplied_weather_fields].isna().any().any():
            raise EvaluationError(
                422,
                "sparse_weather_context",
                "Weather fields supplied for an operation must be co-located on the same rows.",
                tuple(
                    field_error(
                        field,
                        "Repeat all supplied weather fields on each weather-report row.",
                        "incomplete_context",
                    )
                    for field in supplied_weather_fields
                ),
            )

    weather: list[WeatherObservation] = []
    for row in operation.itertuples(index=False):
        qnh = getattr(row, "qnh_hpa", None)
        wind_direction = getattr(row, "wind_from_direction_deg", None)
        wind_speed = getattr(row, "wind_speed_mps", None)
        if all(value is None or pd.isna(value) for value in (qnh, wind_direction, wind_speed)):
            continue
        missing = []
        if qnh is None or pd.isna(qnh):
            missing.append("analyst_supplied_qnh_missing")
        if wind_direction is None or pd.isna(wind_direction):
            missing.append("analyst_supplied_wind_direction_missing")
        if wind_speed is None or pd.isna(wind_speed):
            missing.append("analyst_supplied_wind_speed_missing")
        weather.append(WeatherObservation(
            station="analyst_supplied",
            observed_at=datetime.fromtimestamp(int(row.time), tz=timezone.utc),
            report_type="analyst_supplied",
            wind_from_direction_deg=(
                None if wind_direction is None or pd.isna(wind_direction)
                else float(wind_direction)
            ),
            wind_speed_mps=(
                None if wind_speed is None or pd.isna(wind_speed) else float(wind_speed)
            ),
            qnh_hpa=None if qnh is None or pd.isna(qnh) else float(qnh),
            raw_metar_qnh_hpa=None,
            qnh_cross_check_delta_hpa=None,
            qnh_cross_check_matches=None,
            temperature_c=None,
            dew_point_c=None,
            missing_reasons=tuple(missing),
        ))

    typecodes = sorted({
        str(value).strip().upper()
        for value in operation["aircraft_typecode"].dropna()
        if str(value).strip()
    })
    if len(typecodes) > 1:
        raise EvaluationError(
            422,
            "conflicting_aircraft_context",
            "An operation may contain only one aircraft type code.",
            (field_error(
                "aircraft_typecode",
                "Use one ICAO aircraft type code for every row in an operation.",
                "conflict",
            ),),
        )
    metadata = (
        {"typecode": typecodes[0], "_source": "analyst_supplied"}
        if typecodes else None
    )
    return weather, metadata
