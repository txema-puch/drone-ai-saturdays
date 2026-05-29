"""Supabase I/O helpers for LEMD trajectory data.

Used by Phase 2 data validation (`notebooks/05_phase2_data_validation.ipynb`)
and any future code that needs to discover, load, snapshot, or hash the
`lemd_YYYY_MM_DD` tables Monica's pipeline writes to Supabase.

Design context: `backend/docs/designs/12-task-phase2-data-validation.md`.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from supabase import Client


def discover_lemd_tables(client: Client, start: date, end: date) -> list[str]:
    """Probe `lemd_YYYY_MM_DD` candidate tables for each day in `[start, end]`.

    Returns the list of names that exist, in chronological order. Tables
    the client cannot reach (404, auth error, network blip) are silently
    skipped — caller should sanity-check the returned list against
    expected coverage. If discovery returns an empty list when matches
    were expected, re-check credentials before assuming "no data."
    """
    candidates: list[str] = []
    day = start
    while day <= end:
        candidates.append(f"lemd_{day.strftime('%Y_%m_%d')}")
        day += timedelta(days=1)

    available: list[str] = []
    for name in candidates:
        try:
            client.table(name).select("*").limit(1).execute()
            available.append(name)
        except Exception:
            continue
    return available


def load_table_paginated(
    client: Client,
    table_name: str,
    batch_size: int = 1_000,
    verbose: bool = True,
) -> pd.DataFrame:
    """Page through a Supabase table and return all rows as a DataFrame.

    PostgREST silently caps responses at its server-side `max-rows` (default
    1000). Requesting larger pages does NOT lift the cap — the server just
    returns 1000 and the loop's "partial page → end of table" heuristic
    fires after the first request. Keep `batch_size` at the server cap so
    a partial page actually means we reached the end.
    """
    rows: list[dict] = []
    start = 0
    while True:
        result = (
            client.table(table_name)
            .select("*")
            .range(start, start + batch_size - 1)
            .execute()
        )
        chunk = result.data
        if not chunk:
            break
        rows.extend(chunk)
        if verbose:
            print(f"  {table_name}: fetched {len(rows):,} rows...")
        if len(chunk) < batch_size:
            break
        start += batch_size
    return pd.DataFrame(rows)


def save_snapshot_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Write `df` to a parquet file at `path`. Overwrites if exists.

    Engine: pyarrow. `index=False` so the row index is not encoded as a
    column on re-read. Default compression (snappy). Returns the path
    written so callers can chain into hashing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    return path


def compute_file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the sha256 hex digest of the bytes at `path`.

    Reads in `chunk_size` chunks (default 1 MiB) so very large files do
    not blow memory. The hash is stable as long as the writer is — for
    our setup, `uv.lock` pins pyarrow, so the same DataFrame written
    twice produces the same hash.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
