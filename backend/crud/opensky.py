from datetime import datetime, timedelta
from pyopensky.trino import Trino
from ..core.config import settings


class OpenSkyService:
    def __init__(self):
        self.trino = Trino(
            username=settings.OPENSKY_USERNAME, password=settings.OPENSKY_PASSWORD
        )

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
        SELECT icao24, callsign, firstseen, lastseen
        FROM flights_data4
        WHERE day IN ({days_filter})
        AND estarrivalairport = 'LEMD'
        AND firstseen >= {start_ts}
        AND lastseen <= {end_ts}
        ORDER BY firstseen
        """
        if limit is not None:
            query += f"\nLIMIT {int(limit)}"

        return self.trino.query(query)

    def get_track(self, icao24: str, start: datetime, end: datetime):
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        hours = []
        current_hour = start.replace(minute=0, second=0, microsecond=0)
        while current_hour <= end:
            hour_start_ts = int(current_hour.timestamp())
            hours.append(str(hour_start_ts))
            current_hour += timedelta(hours=1)

        hours_filter = ", ".join(hours)

        query = f"""
        SELECT time, lat, lon, baroaltitude, velocity
        FROM state_vectors_data4
        WHERE hour IN ({hours_filter})
        AND icao24 = '{icao24}'
        AND time BETWEEN {start_ts} AND {end_ts}
        ORDER BY time
        """
        return self.trino.query(query)