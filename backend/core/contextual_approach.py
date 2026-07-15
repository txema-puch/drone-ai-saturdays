"""Context-enriched approach assessment built on the frozen observed-row engine.

Weather and aircraft metadata are explicit inputs. QNH supplies a first-order
pressure-altitude bias proxy; airport wind is contextual evidence only and does
not create a criterion verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Mapping, Sequence

import pandas as pd

from backend.core.approach import (
    ASSESSMENT_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    ApproachConfig,
    assess_approach,
    extract_approach_attempts,
)
from backend.core.approach_context import (
    WeatherObservation,
    join_nearest_weather,
    qnh_pressure_altitude_correction_proxy,
    runway_relative_wind_components,
)
from backend.core.approach_geometry import GeometryCatalog, load_lemd_geometry


CONTEXT_ENGINE_VERSION = "approach_context_v1"
CONTEXT_SCHEMA_VERSION = "approach_context_v1"
MAXIMUM_WEATHER_AGE_S = 1_800


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assess_contextual_operation(
    frame: pd.DataFrame,
    *,
    operation_id: str,
    weather: Sequence[WeatherObservation],
    aircraft_metadata: Mapping[str, str] | None,
    reference: dict[str, Any],
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
    maximum_weather_age_s: float = MAXIMUM_WEATHER_AGE_S,
) -> dict[str, Any]:
    """Assess attempts with QNH/type context while preserving explicit fallback."""

    geometry = geometry or load_lemd_geometry()
    metadata = dict(aircraft_metadata or {})
    typecode = (metadata.get("typecode") or "").strip().upper()
    speed_class = typecode or "unknown"
    assessments = []
    for index, attempt in enumerate(
        extract_approach_attempts(frame, geometry=geometry, config=config), start=1
    ):
        midpoint = int((attempt["time"].min() + attempt["time"].max()) // 2)
        joined = join_nearest_weather(
            midpoint,
            weather,
            maximum_age_seconds=maximum_weather_age_s,
        )
        observation = joined.observation
        qnh_proxy = (
            qnh_pressure_altitude_correction_proxy(observation.qnh_hpa)
            if observation is not None and observation.qnh_hpa is not None
            else None
        )
        assessment = assess_approach(
            attempt,
            operation_id=f"{operation_id}:attempt-{index}",
            geometry=geometry,
            config=config,
            reference=reference,
            speed_class=speed_class,
            altitude_bias_override_m=(
                qnh_proxy.pressure_altitude_minus_qnh_altitude_proxy_m
                if qnh_proxy is not None else None
            ),
            altitude_bias_source=(
                "ncei_metar_qnh_pressure_altitude_proxy"
                if qnh_proxy is not None else None
            ),
        )
        inference = assessment["runway_inference"]
        runway = inference.get("geometry_runway")
        wind = None
        if (
            observation is not None
            and observation.wind_from_direction_deg is not None
            and observation.wind_speed_mps is not None
            and runway in geometry.thresholds
        ):
            wind = runway_relative_wind_components(
                wind_from_direction_deg=observation.wind_from_direction_deg,
                wind_speed_mps=observation.wind_speed_mps,
                runway_true_bearing_deg=geometry.thresholds[runway].true_bearing_deg,
            )
        context = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "weather": {
                "station": observation.station if observation is not None else None,
                "observed_at": (
                    observation.observed_at.isoformat() if observation is not None else None
                ),
                "age_seconds": joined.age_seconds,
                "maximum_age_seconds": maximum_weather_age_s,
                "qnh_hpa": observation.qnh_hpa if observation is not None else None,
                "temperature_c": (
                    observation.temperature_c if observation is not None else None
                ),
                "dew_point_c": observation.dew_point_c if observation is not None else None,
                "wind_from_direction_deg": (
                    observation.wind_from_direction_deg
                    if observation is not None else None
                ),
                "wind_speed_mps": (
                    observation.wind_speed_mps if observation is not None else None
                ),
                "headwind_mps": wind.headwind_mps if wind is not None else None,
                "crosswind_from_right_mps": (
                    wind.crosswind_from_right_mps if wind is not None else None
                ),
                "missing_reasons": list(joined.missing_reasons),
            },
            "aircraft": {
                "typecode": typecode or None,
                "manufacturer": metadata.get("manufacturername") or None,
                "model": metadata.get("model") or None,
                "category": metadata.get("categoryDescription") or None,
                "temporal_identity_warning": (
                    "OpenSky metadata is a current snapshot and may not represent the historical operation."
                    if metadata else None
                ),
            },
            "unavailable": ["aircraft_configuration", "actual_mass", "atc_clearance"],
        }
        assessment["engine_version"] = CONTEXT_ENGINE_VERSION
        assessment["context"] = context
        assessment["provenance"]["context_sha256"] = _digest(context)
        assessment["provenance"]["context_policy_sha256"] = _digest({
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "maximum_weather_age_s": maximum_weather_age_s,
            "qnh_proxy": "30_ft_per_hpa_relative_to_1013.25",
            "wind_role": "display_only",
            "aircraft_role": "reference_speed_class_with_unknown_fallback",
            "config": asdict(config),
        })
        assessments.append(assessment)
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": CONTEXT_ENGINE_VERSION,
        "operation_id": operation_id,
        "attempt_count": len(assessments),
        "attempts": assessments,
    }
