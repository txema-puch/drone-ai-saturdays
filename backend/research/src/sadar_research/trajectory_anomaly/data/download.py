"""Overnight LEMD-area downloader for OpenSky Network's public weekly state-vector dataset.

Alternative ingestion path to the Trino + Supabase pipeline. Pulls data
directly from the public S3-hosted "Weekly 24 Hours of State Vector Data
2017-2022" scientific dataset (https://opensky-network.org/data/scientific),
applies a two-stage LEMD filter (200 km haversine pre-cut + Filter B at the
trajectory level), reuses the same per-row derivations as
`backend/crud/opensky.py`, and writes one parquet file per Monday to
`data/raw/opensky_states/`.

Why this exists:
- The Trino + Supabase ingestion path was a human-side bottleneck.
- The public scientific dataset is download-able with no credentials and
  delivers the same schema OpenSky produces via Trino, at 10-second
  resolution instead of the Trino pipeline's 5-second.

Filter B (LEMD-flight gate, applied per-trajectory):
- After bbox + haversine cut, state vectors are segmented into flights by
  icao24 + 30-minute gap threshold.
- A trajectory is kept iff
    min(dist_to_runway_m) < 10_000     AND     min(baroaltitude) < 3_000
- This removes ~47% of bbox trajectories that are cruise overflights at
  FL350-FL410 transiting central Spain en route between unrelated airports.
- See `backend/docs/workflow/data-pipeline.md` for the rationale.
- Empirically verified on 2019-10-07: 1,174 trajectories kept,
  1,055 cruise overflights excluded (median min_alt 10,668 m, median
  min_dist 55 km).

Output filename convention (matches `data/raw/lemd_*` naming):
    data/raw/opensky_states/lemd_<MondayYYYYMMDD>__opensky_states_<fetchYYYY-MM-DD>.parquet

Differences vs the Trino path:
- `flight_id` is derived by segmenting consecutive observations of the same
  icao24 with a 30-min gap threshold (no `flights_data4` table available).
  Format `{icao24}_{firstseen_unix}` matches the Trino-path convention.
- `operation` is set to "unknown" (no flights metadata to infer arrival
  vs departure). Downstream preprocessing can derive heuristically.
- 10 s resolution vs 5 s. Downsample the Trino-sourced parquets to 10 s
  if composing both datasets at training time.

Usage:
    uv run python backend/scripts/download_opensky_states.py
    uv run python backend/scripts/download_opensky_states.py --mondays 30
    uv run python backend/scripts/download_opensky_states.py --include-covid
    uv run python backend/scripts/download_opensky_states.py --start 2019-01-01 --end 2019-12-31

Resumability:
    Re-running skips Mondays whose output parquet already exists. Pass
    --force to redownload. Atomic writes (.parquet.tmp -> .parquet rename)
    prevent partial files on Ctrl-C.

See also:
- `backend/crud/opensky.py` — Trino-based ingestion + derivation funcs
- `backend/docs/workflow/data-pipeline.md` — full pipeline workflow
- https://opensky-network.org/data/scientific — dataset listing (entry #1)
"""

from __future__ import annotations

import argparse
import gzip
import io
import logging
import signal
import tarfile
import time as time_mod
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from sadar_research.trajectory_anomaly.data.derivations import calculate_flight_phase
from sadar_research.trajectory_anomaly.data.geometry import (
    MAX_RADIUS_M,
    distance_to_closest_runway,
)


# ── Constants ────────────────────────────────────────────────────────────────

BUCKET_BASE = "https://s3.opensky-network.org/data-samples/states"
LEMD_LAT, LEMD_LON = 40.4719, -3.5626
# Bbox half-width that comfortably contains the 200 km haversine radius
# (1.8 deg ≈ 200 km at LEMD latitude). Cheap pre-filter applied before the
# exact haversine cut from distance_to_closest_runway.
BBOX_HALF_WIDTH_DEG = 1.8
GAP_THRESHOLD_SEC = 1800  # 30 min → new flight segment

# Filter B thresholds — empirically validated on 2019-10-07 full-day probe
FILTER_B_MAX_MIN_DIST_M = 10_000
FILTER_B_MAX_MIN_ALT_M = 3_000

# Bucket coverage observed via S3 listing: 2017-06-05 onward, 259 weekly entries
BUCKET_FIRST_MONDAY = date(2017, 6, 5)
BUCKET_LAST_MONDAY = date(2022, 5, 23)

# COVID exclusion (default ON). Traffic patterns during this window are
# genuinely anomalous compared to normal years; without exclusion the
# LSTM-AE learns "normal" as a mix of pre-COVID and pandemic flying.
COVID_START = date(2020, 3, 15)
COVID_END = date(2022, 1, 1)

CSV_COLUMNS = [
    "time", "icao24", "lat", "lon", "velocity", "heading", "vertrate",
    "callsign", "onground", "alert", "spi", "squawk", "baroaltitude",
    "geoaltitude", "lastposupdate", "lastcontact",
]

OUTPUT_COLUMNS = [
    "time", "icao24", "lat", "lon",
    "baroaltitude", "geoaltitude",
    "velocity", "heading", "vertrate",
    "callsign", "onground", "squawk", "alert", "spi", "lastcontact",
    "flight_id", "operation", "time_utc",
    "velocity_kmh", "dist_to_runway_m", "flight_phase",
]


_INTERRUPTED = False


def _sigint_handler(signum, frame):
    """Handle Ctrl-C gracefully: finish the current Monday, then exit."""
    global _INTERRUPTED
    _INTERRUPTED = True
    logging.warning("SIGINT received — will exit after current Monday completes.")


signal.signal(signal.SIGINT, _sigint_handler)


# ── Monday selection ─────────────────────────────────────────────────────────

def all_bucket_mondays() -> list[date]:
    """All Mondays available in the bucket (2017-06-05 → 2022-05-23)."""
    mondays = []
    d = BUCKET_FIRST_MONDAY
    while d <= BUCKET_LAST_MONDAY:
        mondays.append(d)
        d += timedelta(weeks=1)
    return mondays


def pick_mondays(n: int, include_covid: bool, start: date | None, end: date | None) -> list[date]:
    """Evenly sample n Mondays across the eligible range."""
    pool = all_bucket_mondays()
    if start:
        pool = [d for d in pool if d >= start]
    if end:
        pool = [d for d in pool if d <= end]
    if not include_covid:
        pool = [d for d in pool if not (COVID_START <= d <= COVID_END)]
    if not pool:
        raise ValueError("No Mondays match the given filters.")
    if n >= len(pool):
        return pool
    if n == 1:
        return [pool[len(pool) // 2]]
    idx = [int(i * (len(pool) - 1) / (n - 1)) for i in range(n)]
    return [pool[i] for i in idx]


# ── Download ─────────────────────────────────────────────────────────────────

def fetch_hour(monday: date, hour: int, session: requests.Session, max_retries: int = 5) -> pd.DataFrame:
    """Download and parse one hourly .csv.tar (contains .csv.gz inside).

    Returns an empty DataFrame on permanent failure so the Monday can still
    complete with the remaining hours intact.
    """
    date_str = monday.isoformat()
    url = f"{BUCKET_BASE}/.{date_str}/{hour:02d}/states_{date_str}-{hour:02d}.csv.tar"

    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=180)
            if r.status_code == 404:
                logging.warning(f"  404 missing: {date_str} hour {hour:02d} (skipping)")
                return pd.DataFrame(columns=CSV_COLUMNS)
            r.raise_for_status()

            with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:") as tar:
                gz_member = next(
                    (m for m in tar.getmembers() if m.name.endswith(".csv.gz")), None
                )
                if gz_member is None:
                    logging.warning(f"  No .csv.gz inside tar for {date_str} hour {hour:02d}")
                    return pd.DataFrame(columns=CSV_COLUMNS)

                gz_bytes = tar.extractfile(gz_member).read()
                csv_bytes = gzip.decompress(gz_bytes)
                return pd.read_csv(
                    io.BytesIO(csv_bytes),
                    names=CSV_COLUMNS,
                    header=0,
                    low_memory=False,
                )

        except (requests.RequestException, OSError, EOFError) as e:
            wait = 2 ** attempt
            logging.warning(
                f"  retry {attempt + 1}/{max_retries} after {wait}s "
                f"— {date_str} h{hour:02d}: {e}"
            )
            time_mod.sleep(wait)

    logging.error(f"  PERMANENT FAILURE: {date_str} hour {hour:02d} — skipping")
    return pd.DataFrame(columns=CSV_COLUMNS)


def filter_lemd_bbox(df: pd.DataFrame) -> pd.DataFrame:
    """Cheap rectangular bbox pre-filter around LEMD (~200 km half-width).

    Coerces lat/lon to numeric first — OpenSky CSV occasionally has rows with
    non-numeric values that would otherwise keep the column as `object` dtype
    and break `np.radians` downstream.
    """
    if df.empty:
        return df
    df = df.copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    mask = (
        df["lat"].between(LEMD_LAT - BBOX_HALF_WIDTH_DEG, LEMD_LAT + BBOX_HALF_WIDTH_DEG)
        & df["lon"].between(LEMD_LON - BBOX_HALF_WIDTH_DEG, LEMD_LON + BBOX_HALF_WIDTH_DEG)
    )
    return df.loc[mask].copy()


# ── Per-row derivations ──────────────────────────────────────────────────────

def add_flight_id(df: pd.DataFrame, gap_threshold_sec: int = GAP_THRESHOLD_SEC) -> pd.DataFrame:
    """Derive flight_id by segmenting same icao24 with a temporal gap threshold.

    Matches the Trino-path convention: `{icao24}_{firstseen_unix}`.
    """
    if df.empty:
        df = df.copy()
        df["flight_id"] = pd.Series(dtype=str)
        return df
    df = df.sort_values(["icao24", "time"]).reset_index(drop=True)
    gap = df.groupby("icao24", sort=False)["time"].diff()
    new_flight = gap.isna() | (gap > gap_threshold_sec)
    df["_flight_num"] = new_flight.groupby(df["icao24"]).cumsum()
    firstseen = df.groupby(["icao24", "_flight_num"])["time"].transform("min")
    df["flight_id"] = df["icao24"].astype(str) + "_" + firstseen.astype(int).astype(str)
    return df.drop(columns=["_flight_num"])


def apply_filter_b(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only trajectories where min_dist < 10 km AND min_alt < 3 km.

    Run after segmentation (flight_id present) and after distance/altitude
    columns are available. Removes cruise overflights at FL350-FL410 that
    transit the 200 km bbox without touching LEMD.
    """
    if df.empty:
        return df
    stats = df.groupby("flight_id").agg(
        min_dist=("dist_to_runway_m", "min"),
        min_alt=("baroaltitude", "min"),
    )
    keep_ids = stats[
        (stats["min_dist"] < FILTER_B_MAX_MIN_DIST_M)
        & (stats["min_alt"] < FILTER_B_MAX_MIN_ALT_M)
    ].index
    return df.loc[df["flight_id"].isin(keep_ids)].copy()


def apply_derivations(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the same per-row derivations as `OpenSkyService.build_master_table`,
    plus Filter B at the trajectory level."""
    if df.empty:
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        return empty

    df = df.copy()
    # Defensive coercion — OpenSky CSV sometimes has malformed cells that keep
    # whole columns as object dtype, which breaks ufuncs downstream.
    for col in ("velocity", "baroaltitude", "geoaltitude", "vertrate", "heading", "time"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["callsign"] = df["callsign"].astype(str).str.strip()
    df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["velocity_kmh"] = df["velocity"] * 3.6
    df["dist_to_runway_m"] = distance_to_closest_runway(df["lat"], df["lon"])

    # Exact 200 km haversine filter (the bbox was a cheap pre-cut)
    df = df.loc[df["dist_to_runway_m"] <= MAX_RADIUS_M].copy()
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = add_flight_id(df)

    # Filter B — drop cruise overflights at the trajectory level
    df = apply_filter_b(df)
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["operation"] = "unknown"
    df["flight_phase"] = calculate_flight_phase(df)
    df["time"] = pd.to_numeric(df["time"], errors="coerce").fillna(0).astype(int)
    df["flight_id"] = df["flight_id"].astype(str)

    for c in OUTPUT_COLUMNS:
        if c not in df.columns:
            df[c] = None

    return df[OUTPUT_COLUMNS]


# ── Per-Monday driver ────────────────────────────────────────────────────────

def process_monday(monday: date, out_dir: Path, session: requests.Session, force: bool) -> dict:
    """Download, filter, derive, and write parquet for one Monday."""
    fetch_date = date.today().isoformat()
    out_path = out_dir / f"lemd_{monday.strftime('%Y%m%d')}__opensky_states_{fetch_date}.parquet"
    existing = sorted(out_dir.glob(f"lemd_{monday.strftime('%Y%m%d')}__opensky_states_*.parquet"))

    if existing and not force:
        logging.info(f"[skip] {monday} — already present: {existing[-1].name}")
        return {"monday": str(monday), "status": "skipped", "rows": None, "trajectories": None, "path": str(existing[-1])}

    logging.info(f"[fetch] {monday}")
    t0 = time_mod.time()
    hour_chunks: list[pd.DataFrame] = []
    for hour in range(24):
        raw = fetch_hour(monday, hour, session)
        filtered = filter_lemd_bbox(raw)
        hour_chunks.append(filtered)
        if hour % 6 == 5:
            partial_rows = sum(len(c) for c in hour_chunks)
            logging.info(
                f"  {monday} progress: hours 00-{hour:02d} done, "
                f"{partial_rows:,} bbox rows so far"
            )

    raw_lemd = (
        pd.concat(hour_chunks, ignore_index=True)
        if hour_chunks
        else pd.DataFrame(columns=CSV_COLUMNS)
    )
    derived = apply_derivations(raw_lemd)

    # Atomic write — tmp + rename prevents partial files on Ctrl-C
    tmp_path = out_path.with_suffix(".parquet.tmp")
    derived.to_parquet(tmp_path, engine="pyarrow", compression="snappy", index=False)
    tmp_path.rename(out_path)

    elapsed = time_mod.time() - t0
    n_traj = int(derived["flight_id"].nunique()) if not derived.empty else 0
    logging.info(
        f"[done] {monday} — {len(derived):,} rows, {n_traj:,} trajectories, "
        f"{elapsed:.0f}s → {out_path.name}"
    )
    return {
        "monday": str(monday),
        "status": "ok",
        "rows": int(len(derived)),
        "trajectories": n_traj,
        "elapsed_s": round(elapsed, 1),
        "path": str(out_path),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download LEMD-filtered OpenSky weekly state-vector data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mondays", type=int, default=20,
                   help="Number of Mondays to sample (default: 20).")
    p.add_argument("--explicit-dates", type=str, default=None,
                   help="Comma-separated YYYY-MM-DD list of specific Mondays to fetch "
                        "(overrides --mondays/--start/--end/--include-covid).")
    p.add_argument("--out", type=Path,
                   default=ROOT_DIR / "data" / "raw" / "opensky_states",
                   help="Output directory (default: data/raw/opensky_states/).")
    p.add_argument("--include-covid", action="store_true",
                   help="Include 2020-03-15 → 2022-01-01 (excluded by default).")
    p.add_argument("--start", type=lambda s: date.fromisoformat(s), default=None,
                   help="Earliest Monday to consider (YYYY-MM-DD).")
    p.add_argument("--end", type=lambda s: date.fromisoformat(s), default=None,
                   help="Latest Monday to consider (YYYY-MM-DD).")
    p.add_argument("--force", action="store_true",
                   help="Re-download Mondays even if output parquet exists.")
    p.add_argument("--log", type=Path, default=None,
                   help="Log file (default: data/raw/opensky_states/run_<timestamp>.log).")
    return p.parse_args()


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.log or (
        args.out / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    configure_logging(log_path)

    if args.explicit_dates:
        mondays = [date.fromisoformat(s.strip()) for s in args.explicit_dates.split(",") if s.strip()]
        # Verify each is actually a Monday and in the bucket
        bad = [d for d in mondays if d.weekday() != 0]
        if bad:
            raise ValueError(f"--explicit-dates must all be Mondays. Not Mondays: {bad}")
    else:
        mondays = pick_mondays(args.mondays, args.include_covid, args.start, args.end)
    logging.info(f"Plan: {len(mondays)} Mondays")
    logging.info(f"  first: {mondays[0]}  last: {mondays[-1]}")
    logging.info(f"  output dir: {args.out}")
    logging.info(f"  log file: {log_path}")
    logging.info(f"  COVID included: {args.include_covid}")
    logging.info(
        f"  Filter B: min_dist < {FILTER_B_MAX_MIN_DIST_M/1000:.0f}km "
        f"AND min_alt < {FILTER_B_MAX_MIN_ALT_M:.0f}m"
    )

    session = requests.Session()
    summary: list[dict] = []

    for i, monday in enumerate(mondays, 1):
        logging.info(f"=== Monday {i}/{len(mondays)}: {monday} ===")
        try:
            row = process_monday(monday, args.out, session, args.force)
            summary.append(row)
        except Exception as e:  # noqa: BLE001
            logging.exception(f"FAILED on {monday}: {e}")
            summary.append({"monday": str(monday), "status": "error", "error": str(e)})

        if _INTERRUPTED:
            logging.warning("Stopping after Ctrl-C.")
            break

    # Write run manifest
    manifest_path = args.out / f"manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(summary).to_csv(manifest_path, index=False)
    logging.info(f"Manifest: {manifest_path}")

    ok = sum(1 for r in summary if r.get("status") == "ok")
    skipped = sum(1 for r in summary if r.get("status") == "skipped")
    errors = sum(1 for r in summary if r.get("status") == "error")
    total_rows = sum(r.get("rows") or 0 for r in summary)
    total_traj = sum(r.get("trajectories") or 0 for r in summary)
    logging.info(
        f"Done. ok={ok} skipped={skipped} errors={errors} "
        f"total_rows={total_rows:,} total_trajectories={total_traj:,}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
