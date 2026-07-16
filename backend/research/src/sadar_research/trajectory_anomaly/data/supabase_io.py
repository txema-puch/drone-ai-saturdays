"""Supabase I/O helpers for LEMD trajectory data.

Used by Phase 2 data validation (`research/trajectory-anomaly/notebooks/lifecycle/05_phase2_data_validation.ipynb`)
and any future code that needs to discover, load, snapshot, or hash the
`lemd_YYYY_MM_DD` tables Monica's pipeline writes to Supabase.

Design context: `docs/research/trajectory-anomaly/data-workflow.md`.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
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


def _row_key(row: dict) -> frozenset:
    """Stable hashable identity for a row, used to dedupe full-row duplicates
    across page boundaries during keyset pagination. `frozenset(row.items())`
    is order-independent and ignores dict ordering quirks. Assumes all values
    are hashable (ADS-B rows are int/str/float/bool/None — true in practice).
    """
    return frozenset(row.items())


def _fetch_time_bounds(client: Client, table_name: str) -> tuple[int, int]:
    """Return (min_time, max_time) for `table_name`. Single-row queries that
    use the `(time, icao24)` index when present — fast even on ~1.5M-row
    tables. Without the index, falls back to a sequential scan to find
    the limit-1 result, which may also time out; if so, add the index
    via `CREATE INDEX ... ON <table> (time, icao24)`.
    """
    min_q = client.table(table_name).select("time").order("time", desc=False).limit(1).execute()
    max_q = client.table(table_name).select("time").order("time", desc=True).limit(1).execute()
    if not min_q.data or not max_q.data:
        raise RuntimeError(f"{table_name} appears empty (min/max time query returned no rows)")
    return min_q.data[0]["time"], max_q.data[0]["time"]


def load_table_paginated(
    client: Client,
    table_name: str,
    batch_size: int = 1_000,
    verbose: bool = True,
    max_retries: int = 5,
) -> pd.DataFrame:
    """Page through a Supabase `lemd_*` table using day-by-day
    bounded-OFFSET pagination.

    History of approaches tried for cycle 2 (~1.15M+ rows):

    1. Naive OFFSET-only (`.range(start, end)`): failed at deep offsets
       because each query had to scan and discard `start` rows before
       returning the next batch. Postgres killed pages where the scan
       exceeded `statement_timeout` (APIError code 57014).
    2. Composite keyset on `(time, icao24)` with OR cursor: works after
       adding a `(time, icao24)` index, but Postgres's planner converts
       the OR clause to a Bitmap Heap Scan + Sort at deep cursor
       positions. With ~1M+ matching rows after the cursor, the
       materialization + sort still exceeded `statement_timeout`.
    3. Day-by-day bounded OFFSET (this version): each query filters to a
       single calendar day's worth of rows
       (`WHERE time >= day_start AND time < day_end`). The day-bounded
       result set is at most a few hundred thousand rows, so OFFSET
       within a day stays small. No OR clause, no global sort, no
       bitmap union. Each query is a simple indexed range scan + small
       OFFSET, which Postgres handles in well under
       `statement_timeout`.

    Requires an index on `(time, ...)` for fast range scans. Without
    one, even the day-bounded query may scan the whole table. Add via:
    `CREATE INDEX ... ON <table> (time, icao24);`

    Note: this is a workaround for Supabase's relatively low
    `statement_timeout` (120s for service-role). On a longer-timeout
    Postgres, keyset would be simpler and roughly equivalent.

    Order: PostgREST's `range(start, end)` without ORDER BY returns
    rows in an undefined order within each page. Across pages within
    one day, OFFSET stability is the only guarantee — adjacent pages
    don't return the same row twice if the underlying scan is stable
    (it should be for a static table during a single audit run).
    Phase 3 trajectory reconstruction groups by `flight_id` and sorts
    by `time` within each group, so the parquet's physical row order
    does not affect downstream sequence model inputs.

    Resilience: each page fetch is retried up to `max_retries` times
    with exponential backoff (1s, 2s, 4s, 8s, 16s) on
    `httpx.RequestError`. Postgres-level errors (APIError, e.g.
    statement_timeout) are NOT retried because they indicate the
    query itself is the problem, not the connection.

    Args:
        client: Supabase client.
        table_name: Table to page through. Must have a `time` column
            (int epoch seconds, indexed) and be schema `public`.
        batch_size: Rows per page within a day. Default 1000
            (PostgREST server cap).
        verbose: Print per-day-and-page progress to stdout.
        max_retries: Retry attempts per page on transient httpx errors.

    Returns:
        DataFrame with all rows from `table_name`. Row order is
        per-day grouped and otherwise undefined; downstream code
        must sort if order matters.
    """
    if verbose:
        print(f"  {table_name}: probing time range...")
    min_time, max_time = _fetch_time_bounds(client, table_name)
    start_day = datetime.fromtimestamp(min_time, tz=timezone.utc).date()
    end_day = datetime.fromtimestamp(max_time, tz=timezone.utc).date()
    if verbose:
        print(
            f"  {table_name}: data spans {start_day} to {end_day} "
            f"({(end_day - start_day).days + 1} days)"
        )

    rows: list[dict] = []
    day = start_day
    while day <= end_day:
        day_start = int(
            datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        )
        day_end = int(
            datetime.combine(
                day + timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone.utc,
            ).timestamp()
        )

        offset = 0
        day_rows_before = len(rows)
        while True:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    result = (
                        client.table(table_name)
                        .select("*")
                        .gte("time", day_start)
                        .lt("time", day_end)
                        .range(offset, offset + batch_size - 1)
                        .execute()
                    )
                    break
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt == max_retries - 1:
                        raise RuntimeError(
                            f"{table_name}: day {day}, offset {offset:,} "
                            f"failed after {max_retries} attempts "
                            f"({type(exc).__name__}). {len(rows):,} rows "
                            f"already fetched are discarded."
                        ) from exc
                    wait_s = 2 ** attempt  # 1, 2, 4, 8, 16
                    if verbose:
                        print(
                            f"    ⚠️  {table_name} {day}: offset {offset:,} hit "
                            f"{type(exc).__name__} "
                            f"(attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_s}s..."
                        )
                    time.sleep(wait_s)
            else:
                raise RuntimeError(
                    f"unreachable: retry loop exited without break (last: {last_exc!r})"
                )

            chunk = result.data
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < batch_size:
                break
            offset += batch_size

        day_rows = len(rows) - day_rows_before
        if verbose and day_rows > 0:
            print(f"  {table_name} {day}: +{day_rows:,} rows (total {len(rows):,})")
        day += timedelta(days=1)

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
