"""Versioned LEMD runway geometry and runway-relative coordinate helpers.

The old ``LEMD_RUNWAYS`` mapping is retained for the historical model contract.
New approach screening must use this module and its AIP-sourced geometry artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sadar.trajectory.geo import EARTH_RADIUS_M, haversine_dist


GEOMETRY_RESOURCE = files("sadar.approach.resources").joinpath(
    "lemd_runways_2026-07-09.json"
)
# Compatibility for repository pipeline commands during the staged migration.
# Runtime loading uses the Traversable above and does not discover a repository root.
GEOMETRY_PATH = Path(str(GEOMETRY_RESOURCE))


@dataclass(frozen=True)
class RunwayThreshold:
    designator: str
    pair: str
    lat: float
    lon: float
    true_bearing_deg: float
    elevation_m: float
    displaced_m: float
    landing_available: bool

    @property
    def direction(self) -> str:
        return self.designator[:2]


@dataclass(frozen=True)
class RunwayRelative:
    along_track_m: np.ndarray
    cross_track_m: np.ndarray
    threshold_distance_m: np.ndarray


@dataclass(frozen=True)
class GeometryCatalog:
    schema_version: str
    effective_date: str
    source: dict[str, Any]
    artifact_sha256: str
    historical_applicability: str
    thresholds: dict[str, RunwayThreshold]
    runway_pairs: dict[str, Any]

    @property
    def landing_thresholds(self) -> tuple[RunwayThreshold, ...]:
        return tuple(item for item in self.thresholds.values() if item.landing_available)


def _finite_number(value: Any, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


@lru_cache(maxsize=1)
def load_lemd_geometry(path: str | Path | None = None) -> GeometryCatalog:
    data = GEOMETRY_RESOURCE.read_bytes() if path is None else Path(path).read_bytes()
    payload = json.loads(data)
    if payload.get("schema_version") != "lemd_geometry_v1":
        raise ValueError("unsupported LEMD geometry schema")
    thresholds: dict[str, RunwayThreshold] = {}
    for designator, raw in payload["thresholds"].items():
        thresholds[designator] = RunwayThreshold(
            designator=designator,
            pair=str(raw["pair"]),
            lat=_finite_number(raw["lat"], f"{designator}.lat"),
            lon=_finite_number(raw["lon"], f"{designator}.lon"),
            true_bearing_deg=_finite_number(
                raw["true_bearing_deg"], f"{designator}.true_bearing_deg"
            ) % 360.0,
            elevation_m=_finite_number(raw["elevation_m"], f"{designator}.elevation_m"),
            displaced_m=_finite_number(raw["displaced_m"], f"{designator}.displaced_m"),
            landing_available=bool(raw["landing_available"]),
        )
    if set(thresholds) != {"14L", "14R", "18L", "18R", "32L", "32R", "36L", "36R"}:
        raise ValueError("LEMD geometry must define all eight thresholds")
    return GeometryCatalog(
        schema_version=str(payload["schema_version"]),
        effective_date=str(payload["effective_date"]),
        source=dict(payload["source"]),
        artifact_sha256=hashlib.sha256(data).hexdigest(),
        historical_applicability=str(payload["historical_applicability"]),
        thresholds=thresholds,
        runway_pairs=dict(payload["runway_pairs"]),
    )


def circular_difference_deg(left: np.ndarray | float, right: float) -> np.ndarray:
    """Smallest absolute angular difference in degrees."""
    values = np.asarray(left, dtype="float64")
    return np.abs((values - right + 180.0) % 360.0 - 180.0)


def runway_relative(
    lat: pd.Series | np.ndarray,
    lon: pd.Series | np.ndarray,
    runway: RunwayThreshold,
) -> RunwayRelative:
    """Project WGS84 observations into a local threshold-centered runway frame.

    ``along_track_m`` is positive on final before the landing threshold and negative
    after crossing it. ``cross_track_m`` is signed perpendicular displacement.
    The local equirectangular projection is appropriate for the <= 25 km gate.
    """
    lat_values = np.asarray(lat, dtype="float64")
    lon_values = np.asarray(lon, dtype="float64")
    mean_lat = np.radians((lat_values + runway.lat) / 2.0)
    east = np.radians(lon_values - runway.lon) * EARTH_RADIUS_M * np.cos(mean_lat)
    north = np.radians(lat_values - runway.lat) * EARTH_RADIUS_M
    bearing = math.radians(runway.true_bearing_deg)
    toward_runway_east = math.sin(bearing)
    toward_runway_north = math.cos(bearing)
    along = -(east * toward_runway_east + north * toward_runway_north)
    cross = east * toward_runway_north - north * toward_runway_east
    distance = np.asarray(
        haversine_dist(lat_values, lon_values, runway.lat, runway.lon), dtype="float64"
    )
    return RunwayRelative(along, cross, distance)
