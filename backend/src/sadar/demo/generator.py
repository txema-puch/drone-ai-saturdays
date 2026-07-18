"""Independent runway-relative generation for synthetic approach scenarios."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from sadar.approach.configuration import ApproachConfig
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
    config: ApproachConfig,
    clock_offset_s: int,
) -> pd.DataFrame:
    """Generate one mathematical track without consulting files or external state."""
    del config  # The frozen config is an explicit input even where no branch needs it.
    runway = geometry.thresholds[scenario.runway]
    offsets = np.arange(0, scenario.duration_s + 1, scenario.sample_interval_s, dtype="int64")
    progress = offsets.astype("float64") / scenario.duration_s
    along = np.linspace(scenario.start_along_track_m, scenario.end_along_track_m, len(offsets))
    cross = _profile(scenario.cross_track_profile_m, progress)
    lat, lon = runway_relative_to_latlon(along, cross, runway)

    if scenario.barometric_altitude_profile_m == "three_degree":
        height = np.tan(math.radians(3.0)) * np.maximum(along, 0.0)
    else:
        height = _profile(scenario.barometric_altitude_profile_m, progress)
    barometric = runway.elevation_m + height
    onground = np.zeros(len(offsets), dtype=bool)
    if scenario.expected_outcome == "touch_and_go":
        contact = int(np.argmin(np.abs(progress - 0.85)))
        onground[contact] = True
    elif scenario.expected_outcome == "landing_observed":
        onground[-3:] = True

    frame = pd.DataFrame({
        "flight_id": f"synthetic-{scenario.scenario_id}",
        "time": SYNTHETIC_CLOCK + clock_offset_s + offsets,
        "lat": lat,
        "lon": lon,
        "baroaltitude": barometric,
        "geoaltitude": barometric,
        "velocity": _profile(scenario.ground_speed_profile_mps, progress),
        "heading": (
            runway.true_bearing_deg
            + _profile(scenario.heading_offset_profile_deg, progress)
        ) % 360.0,
        "vertrate": _profile(scenario.vertical_rate_profile_mps, progress),
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
