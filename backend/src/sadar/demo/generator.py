"""Independent runway-relative generation for synthetic approach scenarios."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from sadar.approach.geometry import (
    EARTH_RADIUS_M,
    GeometryCatalog,
    RunwayThreshold,
    runway_relative,
)
from sadar.demo.scenarios import Profile, Scenario
from sadar.releases.approach import canonical_json_bytes


SYNTHETIC_CLOCK = 946_684_800


def geometry_from_payload(payload: dict[str, Any]) -> GeometryCatalog:
    """Construct production geometry from the exact canonical bundled payload."""
    thresholds = {
        designator: RunwayThreshold(
            designator=designator,
            pair=str(raw["pair"]),
            lat=float(raw["lat"]),
            lon=float(raw["lon"]),
            true_bearing_deg=float(raw["true_bearing_deg"]) % 360.0,
            elevation_m=float(raw["elevation_m"]),
            displaced_m=float(raw["displaced_m"]),
            landing_available=bool(raw["landing_available"]),
        )
        for designator, raw in payload["thresholds"].items()
    }
    return GeometryCatalog(
        schema_version=str(payload["schema_version"]),
        effective_date=str(payload["effective_date"]),
        source=dict(payload["source"]),
        artifact_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        historical_applicability=str(payload["historical_applicability"]),
        thresholds=thresholds,
        runway_pairs=dict(payload["runway_pairs"]),
    )


def _profile(profile: Profile, progress: np.ndarray) -> np.ndarray:
    points = np.asarray(profile, dtype="float64")
    return np.interp(progress, points[:, 0], points[:, 1])


def runway_relative_to_latlon(
    along_track_m: np.ndarray,
    cross_track_m: np.ndarray,
    runway: RunwayThreshold,
) -> tuple[np.ndarray, np.ndarray]:
    """Invert the engine's local equirectangular projection deterministically."""
    bearing = math.radians(runway.true_bearing_deg)
    east = -along_track_m * math.sin(bearing) + cross_track_m * math.cos(bearing)
    north = -along_track_m * math.cos(bearing) - cross_track_m * math.sin(bearing)
    lat = runway.lat + np.degrees(north / EARTH_RADIUS_M)
    mean_lat = np.radians((lat + runway.lat) / 2.0)
    lon = runway.lon + np.degrees(east / (EARTH_RADIUS_M * np.cos(mean_lat)))
    return lat, lon


def generate_frame(
    scenario: Scenario,
    *,
    geometry: GeometryCatalog,
    clock_offset_s: int,
) -> pd.DataFrame:
    """Generate one mathematical track without consulting files or external state."""
    runway = geometry.thresholds[scenario.runway]
    offsets = np.arange(0, scenario.duration_s + 1, scenario.sample_interval_s, dtype="int64")
    progress = offsets.astype("float64") / scenario.duration_s
    speed = _profile(scenario.ground_speed_profile_mps, progress)
    cross = _profile(scenario.cross_track_profile_m, progress)
    along = np.empty(len(offsets), dtype="float64")
    along[-1] = scenario.end_along_track_m
    for index in range(len(offsets) - 2, -1, -1):
        delta_time = float(offsets[index + 1] - offsets[index])
        distance = (speed[index] + speed[index + 1]) * 0.5 * delta_time
        delta_cross = cross[index + 1] - cross[index]
        if abs(delta_cross) >= distance:
            raise ValueError(
                f"synthetic scenario {scenario.scenario_id} cross-track motion "
                "exceeds its declared ground speed"
            )
        along[index] = along[index + 1] + math.sqrt(
            distance * distance - delta_cross * delta_cross
        )
    lat, lon = runway_relative_to_latlon(along, cross, runway)

    if scenario.barometric_altitude_profile_m == "three_degree":
        height = np.tan(math.radians(3.0)) * np.maximum(along, 0.0)
    elif scenario.barometric_altitude_profile_m == "steep_final":
        # A continuous steep-final teaching case: a modestly high intercept,
        # a sustained correction from 2.5 km to 0.5 km, then a normal finish.
        height_at_6000 = math.tan(math.radians(3.0)) * 6_000.0
        height_at_2500 = 200.0
        height_at_500 = 20.0
        height = np.where(
            along >= 6_000.0,
            np.tan(math.radians(3.0)) * along,
            np.where(
                along >= 2_500.0,
                height_at_2500
                + (along - 2_500.0) * (height_at_6000 - height_at_2500) / 3_500.0,
                np.where(
                    along >= 500.0,
                    height_at_500
                    + (along - 500.0) * (height_at_2500 - height_at_500) / 2_000.0,
                    np.maximum(along, 0.0) * height_at_500 / 500.0,
                ),
            ),
        )
    elif scenario.barometric_altitude_profile_m == "touch_and_go":
        height = np.where(
            along >= 0.0,
            np.tan(math.radians(3.0)) * along,
            -0.10 * along,
        )
    else:
        height = _profile(scenario.barometric_altitude_profile_m, progress)
    barometric = runway.elevation_m + height
    vertical_rate = np.gradient(barometric, offsets.astype("float64"))
    if scenario.vertical_rate_override_profile_mps is not None:
        vertical_rate = _profile(
            scenario.vertical_rate_override_profile_mps,
            progress,
        )

    along_rate = np.gradient(along, offsets.astype("float64"))
    cross_rate = np.gradient(cross, offsets.astype("float64"))
    track_offset = np.degrees(np.arctan2(cross_rate, -along_rate))
    onground = np.zeros(len(offsets), dtype=bool)
    for start_along_m, end_along_m in scenario.ground_contact_along_windows_m:
        onground |= (along <= start_along_m) & (along >= end_along_m)

    frame = pd.DataFrame({
        "flight_id": f"synthetic-{scenario.scenario_id}",
        "time": SYNTHETIC_CLOCK + clock_offset_s + offsets,
        "lat": lat,
        "lon": lon,
        "baroaltitude": barometric,
        "geoaltitude": barometric,
        "velocity": speed,
        "heading": (runway.true_bearing_deg + track_offset) % 360.0,
        "vertrate": vertical_rate,
        "onground": onground,
    })
    if scenario.coverage_gaps:
        keep = np.ones(len(frame), dtype=bool)
        for start_s, end_s in scenario.coverage_gaps:
            keep &= ~((offsets >= start_s) & (offsets <= end_s))
        frame = frame.loc[keep].reset_index(drop=True)
    return frame


def round_trip_error_m(
    along_track_m: np.ndarray,
    cross_track_m: np.ndarray,
    runway: RunwayThreshold,
) -> tuple[float, float]:
    lat, lon = runway_relative_to_latlon(along_track_m, cross_track_m, runway)
    observed = runway_relative(lat, lon, runway)
    return (
        float(np.max(np.abs(observed.along_track_m - along_track_m))),
        float(np.max(np.abs(observed.cross_track_m - cross_track_m))),
    )
