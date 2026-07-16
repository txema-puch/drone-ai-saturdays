"""Geographic primitives for the LEMD pipeline — haversine + runway distance.

Leaf module: depends only on numpy/pandas. **Do not import `settings`, Trino,
Supabase, or anything that touches credentials here** — `backend/core/preprocessing.py`
and the test-suite import this module, and they must run with no `.env` present
(`backend/crud/opensky.py` evaluates `Settings()` at import, which raises without
credentials; that is exactly the coupling this extraction breaks — see A1 in
`~/.claude/plans/phase3-preprocessing-impl.md`).

Canonical home (refactor A1, 2026-06-01). `backend/crud/opensky.py` re-exports these
names for backward compatibility (notebook 05 + the OpenSkyService class).
`backend/scripts/download_opensky_states.py` still imports them via `crud.opensky`
(re-export) — its migration is deferred until it has test coverage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sadar.trajectory.geo import EARTH_RADIUS_M, haversine_dist

# ── LEMD geography ────────────────────────────────────────────────────────────

LEMD_LAT, LEMD_LON = 40.4719, -3.5626

# Runway thresholds (lat, lon). Used by distance_to_closest_runway.
LEMD_RUNWAYS = {
    "14L": (40.5205, -3.5959),
    "14R": (40.5157, -3.5791),
    "32L": (40.4651, -3.5450),
    "32R": (40.4700, -3.5615),
    "18L": (40.5072, -3.5339),
    "18R": (40.5072, -3.5191),
    "36L": (40.4450, -3.5191),
    "36R": (40.4450, -3.5339),
}

# Only points within this radius of LEMD are relevant for Barajas.
MAX_RADIUS_M = 200_000

def distance_to_closest_runway(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Per-point distance (m) to the nearest LEMD runway threshold."""
    distances = pd.DataFrame({
        runway: haversine_dist(lat, lon, rlat, rlon)
        for runway, (rlat, rlon) in LEMD_RUNWAYS.items()
    })
    return distances.min(axis=1)
