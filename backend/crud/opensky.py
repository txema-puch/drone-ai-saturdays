from datetime import datetime, timedelta
import time

import numpy as np
import pandas as pd
from pyopensky.trino import Trino
from tqdm import tqdm

from ..core.config import settings


# ── Umbrales de pista LEMD ────────────────────────────────────────────────────
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

# Solo puntos dentro de este radio son relevantes para Barajas
MAX_RADIUS_M = 200_000  


def haversine_dist(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos GPS."""
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def distance_to_closest_runway(lat: pd.Series, lon: pd.Series) -> pd.Series:
    distances = pd.DataFrame({
        runway: haversine_dist(lat, lon, rlat, rlon)
        for runway, (rlat, rlon) in LEMD_RUNWAYS.items()
    })
    return distances.min(axis=1)


def calculate_flight_phase(track: pd.DataFrame) -> pd.Series:
    conditions = [
        track["onground"].fillna(False).astype(bool),
        track["baroaltitude"].notna() & (track["baroaltitude"] < 50),
        track["vertrate"].notna() & (track["vertrate"] > 3) & track["baroaltitude"].notna() & (track["baroaltitude"] < 3000),
        track["vertrate"].notna() & (track["vertrate"] > 1),
        track["vertrate"].notna() & (track["vertrate"] <= -1) & track["baroaltitude"].notna() & (track["baroaltitude"] < 3000) & track["dist_to_runway_m"].notna() & (track["dist_to_runway_m"] < 20000),
        track["vertrate"].notna() & (track["vertrate"] < -1),
    ]
    values = ["on_ground", "on_ground", "takeoff", "climb", "approach", "descent"]
    return np.select(conditions, values, default="cruise")


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