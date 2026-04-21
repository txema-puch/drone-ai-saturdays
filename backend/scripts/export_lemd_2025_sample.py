from pathlib import Path
from datetime import datetime

from backend.crud.opensky import OpenSkyService

START = datetime(2025, 1, 1)
END = datetime(2025, 1, 1, 23, 59, 59)
SAMPLE_SIZE = 10

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    service = OpenSkyService()

    print(f"Descargando vuelos de LEMD para el {START.date()}...")
    flights = service.get_flights(START, END, limit=SAMPLE_SIZE)
    
    if flights.empty:
        print("No se encontraron vuelos para ese rango.")
        return

    flights_path = RAW_DIR / "lemd_2025_flights_sample_10.csv"
    flights.to_csv(flights_path, index=False)
    print(f"Vuelos guardados en: {flights_path}")


    print("Descargando trayectorias de los 10 vuelos...")
    tracks_dir = RAW_DIR / "tracks_2025_sample_10"
    tracks_dir.mkdir(parents=True, exist_ok=True)

    for index, row in flights.head(SAMPLE_SIZE).iterrows():
        icao24 = str(row["icao24"])
        firstseen = datetime.fromtimestamp(row["firstseen"])
        lastseen = datetime.fromtimestamp(row["lastseen"])

        track = service.get_track(icao24, firstseen, lastseen)
        track_path = tracks_dir / f"track_{index + 1:02d}_{icao24}.csv"
        track.to_csv(track_path, index=False)
        print(f"Guardado: {track_path}")

    print("Proceso terminado")


if __name__ == "__main__":
    main()
