
import time
import re
from datetime import datetime, timedelta

import pandas as pd
from supabase import create_client, Client

from sadar_research.trajectory_anomaly.data.config import settings
from sadar_research.trajectory_anomaly.data.opensky import OpenSkyService

# ── Configuración ──────────────────────────────────────────────────────────────
DIA = datetime(2025, 3, 11)
FRANJA_HORAS = 2
PAUSA_S = 5
BATCH_SIZE = 500  

FECHA_STR = DIA.strftime("%Y_%m_%d")
NOMBRE_TABLA = f"lemd_{FECHA_STR}"
COLUMNAS_OBJETIVO = [
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

# ── Cliente Supabase ───────────────────────────────────────────────────────────

def get_supabase() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def subir_a_supabase(client: Client, tabla: str, df: pd.DataFrame) -> bool:
    if df.empty:
        return False

    df_clean = df.where(pd.notna(df), other=None).copy()

    for col in ["time_utc", "firstseen", "lastseen", "day"]:
        if col in df_clean.columns:
            df_clean[col] = pd.to_datetime(df_clean[col], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
            df_clean[col] = df_clean[col].where(df_clean[col].notna(), None)

    registros = df_clean.to_dict(orient="records")
    total = len(registros)
    subidos = 0
    any_confirmed = False

    for i in range(0, total, BATCH_SIZE):
        lote = registros[i : i + BATCH_SIZE]
        try:
            res = client.table(tabla).upsert(lote).execute()
            status = getattr(res, "status_code", None) or (res.get("status") if isinstance(res, dict) else None)
            data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)

            if status is None or (200 <= int(status) < 300) or data is not None:
                subidos += len(lote)
                any_confirmed = True
                print(f"    Supabase {tabla}: {subidos}/{total} filas subidas")
            else:
                print(f"    Supabase retornó estado inesperado al subir a {tabla}: {res}")
        except Exception as e:
            msg = str(e)
            print(f"    ERROR subiendo lote a {tabla}: {e}")
            m = re.search(r"Perhaps you meant the table 'public\\.([^']+)'", msg)
            if m:
                suggested = m.group(1)
                print(f"    Intentando fallback a tabla sugerida: {suggested}")
                try:
                    res2 = client.table(suggested).upsert(lote).execute()
                    status2 = getattr(res2, "status_code", None) or (res2.get("status") if isinstance(res2, dict) else None)
                    data2 = getattr(res2, "data", None) or (res2.get("data") if isinstance(res2, dict) else None)
                    if status2 is None or (200 <= int(status2) < 300) or data2 is not None:
                        subidos += len(lote)
                        any_confirmed = True
                        print(f"    Supabase {suggested}: {subidos}/{total} filas subidas (fallback)")
                    else:
                        print(f"    Supabase retornó estado inesperado al subir a {suggested}: {res2}")
                except Exception as e2:
                    print(f"    ERROR fallback a {suggested}: {e2}")

    return any_confirmed


# ── Lógica del día ─────────────────────────────────────────────────────────────

def franjas_del_dia(dia: datetime, horas: int) -> list[tuple[datetime, datetime]]:
    result = []
    inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_dia = inicio + timedelta(days=1)

    while inicio < fin_dia:
        fin = min(inicio + timedelta(hours=horas), fin_dia)
        result.append((inicio, fin))
        inicio = fin

    return result


def main() -> None:
    service = OpenSkyService()
    supabase = get_supabase()

    print(f"Descargando vuelos LEMD {DIA.date()} en franjas de {FRANJA_HORAS}h...")

    todos_vuelos = []

    for f_ini, f_fin in franjas_del_dia(DIA, FRANJA_HORAS):
        print(f"  Franja {f_ini.strftime('%H:%M')} → {f_fin.strftime('%H:%M')} ...", end=" ")
        try:
            df = service.get_flights(f_ini, f_fin)
            if not df.empty:
                todos_vuelos.append(df)
                print(f"{len(df)} vuelos")
            else:
                print("sin vuelos")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(PAUSA_S)

    if not todos_vuelos:
        print("Sin vuelos para este día.")
        return

    flights = (
        pd.concat(todos_vuelos, ignore_index=True)
        .drop_duplicates(subset=["icao24", "firstseen"])
        .sort_values("firstseen")
        .reset_index(drop=True)
    )

    print(
        f"\nVuelos: {len(flights)} ("
        f"{len(flights[flights['operation'] == 'arrival'])} llegadas, "
        f"{len(flights[flights['operation'] == 'departure'])} salidas)"
    )

    print(f"\nConstruyendo tabla maestra ({len(flights)} vuelos)...")
    master = service.build_master_table(flights)

    if master.empty:
        print("Tabla maestra vacía.")
        return

    faltantes = [c for c in COLUMNAS_OBJETIVO if c not in master.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas en master: {faltantes}")

    tabla_unica = master[COLUMNAS_OBJETIVO].copy()

    print(f"  Subiendo tabla consolidada a Supabase ({NOMBRE_TABLA})...")
    subir_a_supabase(supabase, NOMBRE_TABLA, tabla_unica)

    print(f"\n{'=' * 50}")
    print("COMPLETADO")
    print(f"{'=' * 50}")
    print(f"Tabla en Supabase: {NOMBRE_TABLA}")
    print("Datos guardados  : En Supabase (sin locales)")
    print(f"Filas totales    : {len(tabla_unica)}")
    print(f"Vuelos únicos    : {tabla_unica['flight_id'].nunique()}")
    print("\nFases detectadas:")
    print(tabla_unica["flight_phase"].value_counts().to_string())
    print("\nOperaciones:")
    print(tabla_unica["operation"].value_counts().to_string())

    alt = tabla_unica["baroaltitude"].dropna()
    if not alt.empty:
        print(f"\nAltitud (m): max={alt.max():.0f} min={alt.min():.0f} media={alt.mean():.0f}")

    vel = tabla_unica["velocity_kmh"].dropna()
    if not vel.empty:
        print(f"Velocidad (km/h): max={vel.max():.0f} min={vel.min():.0f} media={vel.mean():.0f}")

    dist = tabla_unica["dist_to_runway_m"].dropna()
    if not dist.empty:
        print(f"Distancia pista (m): max={dist.max():.0f} min={dist.min():.0f}")

    print(f"{'=' * 50}")
    print(f"Datos disponibles en Supabase — tabla: {NOMBRE_TABLA}")


if __name__ == "__main__":
    main()
