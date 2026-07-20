"""LEMD ADS-B extraction + per-row derivations from OpenSky Trino.

Dual-use module. Read this before changing any of the math.

1. Production pipeline (Monica's `backend/research/src/sadar_research/trajectory_anomaly/data/export_sample.py`)
   Pulls state-vectors via Trino, applies the 200km LEMD radius filter, and
   derives six columns (flight_id, operation, time_utc, velocity_kmh,
   dist_to_runway_m, flight_phase) before writing to Supabase `lemd_*` tables.

2. Audit reference implementation
   `research/trajectory-anomaly/notebooks/lifecycle/05_phase2_data_validation.ipynb` imports `calculate_flight_phase`
   and `distance_to_closest_runway` from this module and re-runs them on the
   Supabase rows to verify the upstream computations still produce the same
   values. Tolerances are documented in `docs/research/trajectory-anomaly/lifecycle/02-data.md` (D-205).

Implication: any change to the derivation functions silently changes the audit's
consistency check. If the function is updated and past data is rebackfilled,
the audit passes. If updated without rebackfill, the next cycle's audit flags
the deltas as inconsistencies. Both outcomes are by design — see
`docs/research/trajectory-anomaly/data-workflow.md > Why opensky.py is dual-use`.

See also:
- `backend/research/src/sadar_research/trajectory_anomaly/data/supabase_io.py` — Phase 2 audit's I/O helpers (paired with this)
- `docs/research/trajectory-anomaly/data-workflow.md` — full pipeline workflow
- `docs/research/trajectory-anomaly/lifecycle/02-data.md` — audit methodology and per-cycle log
- `docs/research/trajectory-anomaly/data-workflow.md` — Phase 2 design doc
"""

from datetime import datetime, timedelta
import time

import numpy as np
import pandas as pd
from pyopensky.trino import Trino
from tqdm import tqdm

from sadar_research.trajectory_anomaly.data.config import settings

# Geo + derivation helpers were extracted to leaf modules (refactor A1,
# 2026-06-01) so `backend/research/src/sadar_research/trajectory_anomaly/pipeline/preprocessing.py` and the test-suite can import
# them without triggering `Settings()` (which this module does at import time).
# Re-exported here so notebook 05 and `download_opensky_states.py` keep working
# unchanged: `from sadar_research.trajectory_anomaly.data.opensky import calculate_flight_phase, ...`.
from sadar_research.trajectory_anomaly.data.geometry import (  # noqa: F401  (re-export)
    LEMD_RUNWAYS,
    MAX_RADIUS_M,
    distance_to_closest_runway,
    haversine_dist,
)
from sadar_research.trajectory_anomaly.data.derivations import calculate_flight_phase  # noqa: F401  (re-export)


class OpenSkyService:
    def __init__(self):
        self.trino = Trino(username=settings.OPENSKY_USERNAME, password=settings.OPENSKY_PASSWORD)

    def get_flights(self, start: datetime, end: datetime, limit=None):
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        days = []
        current_day = start.date()
        while current_day <= end.date():
            day_start_ts = int(datetime(current_day.year, current_day.month, current_day.day).timestamp())
            days.append(str(day_start_ts))
            current_day += timedelta(days=1)

        days_filter = ", ".join(days)

        query = f"""
        SELECT
            icao24,
            callsign,
            firstseen,
            lastseen,
            CASE
                WHEN estarrivalairport = 'LEMD' THEN 'arrival'
                WHEN estdepartureairport = 'LEMD' THEN 'departure'
                ELSE 'unknown'
            END AS operation
        FROM flights_data4
        WHERE day IN ({days_filter})
          AND (estarrivalairport = 'LEMD' OR estdepartureairport = 'LEMD')
          AND firstseen >= {start_ts}
          AND lastseen <= {end_ts}
        ORDER BY firstseen
        """
        if limit is not None:
            query += f"\nLIMIT {int(limit)}"

        return self.trino.query(query)

    def get_track(self, icao24: str, start: datetime, end: datetime, retries=3):
        """Obtiene la trayectoria de un avión con reintentos."""
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        hours = []
        current_hour = start.replace(minute=0, second=0, microsecond=0)
        while current_hour <= end + timedelta(hours=1):
            hours.append(str(int(current_hour.timestamp())))
            current_hour += timedelta(hours=1)
        hours_filter = ", ".join(hours)

        query = f"""
        SELECT
            time, icao24, lat, lon,
            baroaltitude, geoaltitude,
            velocity, heading, vertrate,
            callsign, onground, squawk,
            alert, spi, lastcontact
        FROM state_vectors_data4
        WHERE hour IN ({hours_filter})
          AND icao24 = '{icao24}'
          AND time BETWEEN {start_ts} AND {end_ts}
          AND time - lastcontact <= 15
        ORDER BY time
        """

        for attempt in range(retries):
            try:
                time.sleep(0.5)
                return self.trino.query(query)
            except Exception:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def build_master_table(self, flights_df: pd.DataFrame) -> pd.DataFrame:
        master_list = []

        for i, flight in tqdm(flights_df.iterrows(), total=len(flights_df), desc="Descargando trayectorias"):
            start = datetime.utcfromtimestamp(flight["firstseen"])
            end = datetime.utcfromtimestamp(flight["lastseen"])

            track = self.get_track(flight["icao24"], start, end)

            if track is None or track.empty:
                print(f"  -> Sin trayectoria para {flight['icao24']}")
                continue

            track["flight_id"] = f"{flight['icao24']}_{int(flight['firstseen'])}"
            track["operation"] = flight.get("operation", "unknown")
            track["time_utc"] = pd.to_datetime(track["time"], unit="s", utc=True)
            track["velocity_kmh"] = pd.to_numeric(track.get("velocity", pd.Series()), errors="coerce") * 3.6
            track["callsign"] = track["callsign"].astype(str).str.strip()

            track["dist_to_runway_m"] = distance_to_closest_runway(track["lat"], track["lon"]) if ("lat" in track.columns and "lon" in track.columns) else pd.Series([np.nan] * len(track))

            track = track[track["dist_to_runway_m"] <= MAX_RADIUS_M].copy()

            track["flight_phase"] = calculate_flight_phase(track)

            master_list.append(track)

        if not master_list:
            return pd.DataFrame()

        master = pd.concat(master_list, ignore_index=True)

        # Normalizar columnas esperadas por la tabla Supabase
        required_cols = [
            "time",
            "icao24",
            "lat",
            "lon",
            "baroaltitude",
            "geoaltitude",
            "velocity",
            "heading",
            "vertrate",
            "callsign",
            "onground",
            "squawk",
            "alert",
            "spi",
            "lastcontact",
            "flight_id",
            "operation",
            "time_utc",
            "velocity_kmh",
            "dist_to_runway_m",
            "flight_phase",
        ]

        for c in required_cols:
            if c not in master.columns:
                master[c] = None

        # Asegurar que `time` es entero (epoch seconds)
        if "time" in master.columns:
            master["time"] = pd.to_numeric(master["time"], errors="coerce").fillna(0).astype(int)

        # Normalizar types: flight_id a str
        master["flight_id"] = master["flight_id"].astype(str)

        return master