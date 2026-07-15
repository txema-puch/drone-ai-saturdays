from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from backend.core.approach_context import (
    WeatherObservation,
    join_nearest_weather,
    load_aircraft_metadata_parts,
    load_global_hourly_weather,
    qnh_pressure_altitude_correction_proxy,
    runway_relative_wind_components,
)


WEATHER_HEADER = (
    '"STATION","DATE","REPORT_TYPE","WND","TMP","DEW","MA1","REM"\n'
)


def test_global_hourly_prefers_fm15_and_decodes_canonical_units() -> None:
    source = io.StringIO(
        WEATHER_HEADER
        + '"08221099999","2025-01-01T00:00:00","FM-12",'
        '"320,1,N,0010,1","-0003,1","-0015,1",'
        '"99999,9,09624,1","SYNOP"\n'
        + '"08221099999","2025-01-01T00:00:00","FM-15",'
        '"330,1,N,0005,1","-0010,1","-0020,1",'
        '"10310,1,99999,9","MET053METAR LEMD 010000Z 33001KT Q1031="\n'
        + '"99999999999","2025-01-01T00:00:00","FM-15",'
        '"180,1,N,0010,1","+0100,1","+0050,1",'
        '"10130,1,99999,9","METAR Q1013="\n'
    )

    observations = load_global_hourly_weather(source)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.report_type == "FM-15"
    assert observation.observed_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert observation.wind_from_direction_deg == 330.0
    assert observation.wind_speed_mps == 0.5
    assert observation.temperature_c == -1.0
    assert observation.dew_point_c == -2.0
    assert observation.qnh_hpa == 1031.0
    assert observation.raw_metar_qnh_hpa == 1031.0
    assert observation.qnh_cross_check_matches is True
    assert observation.missing_reasons == ()


def test_global_hourly_exposes_variable_wind_and_qnh_mismatch() -> None:
    source = io.StringIO(
        WEATHER_HEADER
        + '"08221099999","2025-01-01T00:30:00","FM-15",'
        '"999,9,V,0010,1","+9999,9","+0000,1",'
        '"10300,1,99999,9","METAR LEMD Q1028="\n'
    )

    observation = load_global_hourly_weather(source)[0]

    assert observation.wind_from_direction_deg is None
    assert observation.wind_speed_mps == 1.0
    assert observation.qnh_hpa == 1030.0
    assert observation.qnh_cross_check_delta_hpa == 2.0
    assert observation.qnh_cross_check_matches is False
    assert set(observation.missing_reasons) == {
        "wind_direction_missing_or_variable",
        "ma1_raw_metar_qnh_mismatch",
        "temperature_missing",
    }


def _weather(at_minute: int) -> WeatherObservation:
    return WeatherObservation(
        station="08221099999",
        observed_at=datetime(2025, 1, 1, 12, at_minute, tzinfo=timezone.utc),
        report_type="FM-15",
        wind_from_direction_deg=180.0,
        wind_speed_mps=5.0,
        qnh_hpa=1013.0,
        raw_metar_qnh_hpa=1013.0,
        qnh_cross_check_delta_hpa=0.0,
        qnh_cross_check_matches=True,
        temperature_c=10.0,
        dew_point_c=5.0,
        missing_reasons=(),
    )


def test_nearest_weather_join_has_age_limit_and_prefers_past_on_tie() -> None:
    observations = [_weather(0), _weather(30)]

    joined = join_nearest_weather(
        "2025-01-01T12:15:00Z", observations, maximum_age_seconds=901
    )
    stale = join_nearest_weather(
        "2025-01-01T13:00:00Z", observations, maximum_age_seconds=1200
    )

    assert joined.observation == observations[0]
    assert joined.age_seconds == 900.0
    assert joined.missing_reasons == ()
    assert stale.observation is None
    assert stale.nearest_observation_at == observations[1].observed_at
    assert stale.age_seconds == 1800.0
    assert stale.missing_reasons == ("nearest_weather_observation_too_old",)


def test_nearest_weather_join_accepts_real_epoch_seconds_without_unit_drift() -> None:
    observation = _weather(0)
    epoch_seconds = int(observation.observed_at.timestamp()) + 60

    joined = join_nearest_weather(
        epoch_seconds, [observation], maximum_age_seconds=120
    )

    assert joined.attempt_midpoint.year == 2025
    assert joined.age_seconds == 60.0
    assert joined.observation == observation


def test_runway_wind_components_use_meteorological_from_direction() -> None:
    headwind = runway_relative_wind_components(
        wind_from_direction_deg=180.0,
        wind_speed_mps=10.0,
        runway_true_bearing_deg=180.0,
    )
    tailwind = runway_relative_wind_components(
        wind_from_direction_deg=0.0,
        wind_speed_mps=10.0,
        runway_true_bearing_deg=180.0,
    )
    from_right = runway_relative_wind_components(
        wind_from_direction_deg=270.0,
        wind_speed_mps=10.0,
        runway_true_bearing_deg=180.0,
    )

    assert headwind.headwind_mps == pytest.approx(10.0)
    assert tailwind.headwind_mps == pytest.approx(-10.0)
    assert from_right.headwind_mps == pytest.approx(0.0, abs=1e-12)
    assert from_right.crosswind_from_right_mps == pytest.approx(10.0)


def test_qnh_correction_is_an_explicit_pressure_altitude_proxy() -> None:
    low_qnh = qnh_pressure_altitude_correction_proxy(1003.25)
    high_qnh = qnh_pressure_altitude_correction_proxy(1023.25)

    assert low_qnh.pressure_altitude_minus_qnh_altitude_proxy_m == pytest.approx(91.44)
    assert low_qnh.qnh_altitude_from_pressure_altitude_addend_m == pytest.approx(-91.44)
    assert high_qnh.pressure_altitude_minus_qnh_altitude_proxy_m == pytest.approx(-91.44)
    assert high_qnh.qnh_altitude_from_pressure_altitude_addend_m == pytest.approx(91.44)


def test_aircraft_loader_streams_records_across_arbitrary_part_boundaries(tmp_path) -> None:
    csv_bytes = (
        '"icao24","registration","manufacturername","notes"\r\n'
        '"abc123","EC-ABC","Aérospatiale","quoted, field\nwith newline"\r\n'
        '"def456","EC-DEF","Boeing","not requested"\r\n'
        '"fedcba","EC-FED","Airbus","second requested"\r\n'
    ).encode("utf-8")
    # Split inside the UTF-8 encoding of "é", inside a quoted multiline record,
    # and inside the final requested ICAO24.
    accent = csv_bytes.index("é".encode("utf-8")) + 1
    newline_record = csv_bytes.index(b"with newline") + 4
    final_icao = csv_bytes.index(b"fedcba") + 3
    boundaries = [0, accent, newline_record, final_icao, len(csv_bytes)]
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        (tmp_path / f"aircraftDatabase.part{index:02d}").write_bytes(csv_bytes[start:end])

    result = load_aircraft_metadata_parts(tmp_path, ["ABC123", "fedcba", "000000"])

    assert set(result) == {"abc123", "fedcba"}
    assert result["abc123"]["manufacturername"] == "Aérospatiale"
    assert result["abc123"]["notes"] == "quoted, field\nwith newline"
    assert result["fedcba"]["registration"] == "EC-FED"


def test_aircraft_loader_does_not_require_parts_for_empty_request(tmp_path) -> None:
    assert load_aircraft_metadata_parts(tmp_path, []) == {}
