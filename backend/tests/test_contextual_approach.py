from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from backend.core.approach import assess_approach
from backend.core.approach_context import WeatherObservation
from backend.core.contextual_approach import assess_contextual_operation
from backend.tests.test_approach import _fixture
from backend.tests.test_approach_reference import _reference


def _weather(qnh: float = 1003.25) -> list[WeatherObservation]:
    return [WeatherObservation(
        station="08221099999",
        observed_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
        report_type="FM-15",
        wind_from_direction_deg=180.0,
        wind_speed_mps=5.0,
        qnh_hpa=qnh,
        raw_metar_qnh_hpa=qnh,
        qnh_cross_check_delta_hpa=0.0,
        qnh_cross_check_matches=True,
        temperature_c=10.0,
        dew_point_c=4.0,
        missing_reasons=(),
    )]


def test_altitude_override_requires_explicit_plausible_source() -> None:
    frame = _fixture()
    with pytest.raises(ValueError, match="explicit source"):
        assess_approach(frame, altitude_bias_override_m=10.0)
    with pytest.raises(ValueError, match="within 500 m"):
        assess_approach(
            frame,
            altitude_bias_override_m=501.0,
            altitude_bias_source="fixture",
        )


def test_contextual_assessment_uses_qnh_and_type_without_hiding_missing_private_data() -> None:
    frame = _fixture()
    midpoint = int((frame.time.min() + frame.time.max()) // 2)
    weather = _weather()
    weather[0] = replace(
        weather[0], observed_at=datetime.fromtimestamp(midpoint, tz=timezone.utc)
    )

    result = assess_contextual_operation(
        frame,
        operation_id="fixture",
        weather=weather,
        aircraft_metadata={"typecode": "A320", "manufacturername": "Airbus"},
        reference=_reference(),
    )["attempts"][0]

    assert result["engine_version"] == "approach_context_v1"
    assert result["altitude_reference"]["source"] == (
        "ncei_global_hourly_qnh_pressure_altitude_proxy"
    )
    assert result["context"]["aircraft"]["typecode"] == "A320"
    assert result["context"]["unavailable"] == [
        "aircraft_configuration", "actual_mass", "atc_clearance"
    ]
    assert result["reference"]["speed_class"] == "A320"
    assert result["provenance"]["context_sha256"]


def test_extreme_but_parseable_qnh_abstains_instead_of_crashing() -> None:
    frame = _fixture()
    midpoint = int((frame.time.min() + frame.time.max()) // 2)
    weather = _weather(qnh=850.0)
    weather[0] = replace(
        weather[0], observed_at=datetime.fromtimestamp(midpoint, tz=timezone.utc)
    )

    result = assess_contextual_operation(
        frame,
        operation_id="fixture",
        weather=weather,
        aircraft_metadata=None,
        reference=_reference(),
    )["attempts"][0]

    assert result["altitude_reference"]["source"] != (
        "ncei_global_hourly_qnh_pressure_altitude_proxy"
    )
    assert "qnh_pressure_altitude_proxy_outside_supported_bias" in (
        result["context"]["weather"]["missing_reasons"]
    )
