"""Credential-free geographic primitives shared by product and research."""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_000


def haversine_dist(lat1, lon1, lat2, lon2):
    """Return vectorized great-circle distance in metres for degree inputs."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    value = (
        np.sin(dphi / 2) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * np.arctan2(np.sqrt(value), np.sqrt(1 - value))
