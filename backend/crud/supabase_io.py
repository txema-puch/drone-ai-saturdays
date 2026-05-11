"""Supabase I/O helpers for LEMD trajectory data.

Used by Phase 2 data validation (`notebooks/05_phase2_data_validation.ipynb`)
and any future code that needs to discover, load, snapshot, or hash the
`lemd_YYYY_MM_DD` tables Monica's pipeline writes to Supabase.

Design context: `backend/docs/designs/12-task-phase2-data-validation.md`.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from datetime import date, timedelta
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


def load_table_paginated(
    client: Client,
    table_name: str,
    batch_size: int = 1_000,
    verbose: bool = True,
    max_retries: int = 5,
) -> pd.DataFrame:
    """Page through a Supabase `lemd_*` table using composite keyset
    pagination on `(time, icao24)` with boundary-row deduplication.

    Why keyset and not OFFSET. Cycle 2 (~1.15M rows) exposed that
    OFFSET-based pagination (`.range(start, end)`) does not scale: each
    subsequent page makes Postgres scan and discard `start` rows before
    returning the next batch, so query cost grows linearly with offset.
    Eventually a single page exceeds Supabase's `statement_timeout` and
    Postgres aborts the query (APIError code 57014). Smaller batch_size
    does not help — OFFSET still scales with offset value, not limit.

    Keyset fixes this: the WHERE clause becomes
    `(time, icao24) >= (last_time, last_icao24)`, which Postgres can
    resolve via an indexed range seek — O(log N) to find the start,
    O(1) per row after that. Page cost is constant regardless of depth.

    Why `(time, icao24)` and not just `time`. `time` (OpenSky epoch int)
    is not unique on its own — many aircraft broadcast within the same
    second. `icao24` (6-hex aircraft id) breaks most ties.

    Why `>=` on the cursor and not `>`. `(time, icao24)` can also be
    non-unique if the table contains full-row duplicates (cycle 1's
    issue #13: 37.5% dups from script re-runs without a unique
    constraint). Using strict-greater (`>`) would silently skip
    duplicates that span a page boundary. Using `>=` re-fetches the
    last page's boundary rows, then we deduplicate them in Python via
    a Counter keyed on the full-row frozenset. Net cost: a handful of
    redundant rows per page (~5-15% bandwidth at worst), but the
    snapshot preserves every row Postgres returned, including
    duplicates — so the audit's dup-detection cells see the true
    counts.

    Side effect: the returned DataFrame is sorted by `(time, icao24)`.
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
        table_name: Table to page through. Must have columns `time`
            (int) and `icao24` (str). Both should be indexed.
        batch_size: Rows per page. Default 1000 (PostgREST server cap).
        verbose: Print per-page progress to stdout.
        max_retries: Retry attempts per page on transient httpx errors.

    Returns:
        DataFrame with all rows from `table_name`, sorted by
        `(time, icao24)` ascending. Full-row duplicates are preserved.
    """
    rows: list[dict] = []
    cursor_time: int | None = None
    cursor_icao24: str | None = None
    # Multiset of row identities seen at exactly (cursor_time, cursor_icao24)
    # in the previous page — these are what `>=` will re-fetch and we need to
    # drop. Counter (not set) so we drop the right NUMBER of duplicates and
    # let any additional ones pass through.
    boundary_counter: Counter = Counter()
    page_num = 0

    while True:
        page_num += 1

        # Build query. First page: no cursor filter. Subsequent: composite
        # keyset condition `time > cursor_time OR (time = cursor_time AND
        # icao24 >= cursor_icao24)`, expressed in PostgREST or() syntax.
        query = (
            client.table(table_name)
            .select("*")
            .order("time", desc=False)
            .order("icao24", desc=False)
            .limit(batch_size)
        )
        if cursor_time is not None:
            query = query.or_(
                f"time.gt.{cursor_time},"
                f"and(time.eq.{cursor_time},icao24.gte.{cursor_icao24})"
            )

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = query.execute()
                break
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"{table_name}: page {page_num} (cursor "
                        f"time={cursor_time}, icao24={cursor_icao24}) "
                        f"failed after {max_retries} attempts "
                        f"({type(exc).__name__}). {len(rows):,} rows "
                        f"already fetched are discarded."
                    ) from exc
                wait_s = 2 ** attempt  # 1, 2, 4, 8, 16
                if verbose:
                    print(
                        f"  ⚠️  {table_name}: page {page_num} hit "
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

        # Dedupe rows at the cursor point. Rows further along (time/icao24
        # strictly greater than cursor) are always new.
        new_rows: list[dict] = []
        for row in chunk:
            if (
                row["time"] == cursor_time
                and row["icao24"] == cursor_icao24
            ):
                key = _row_key(row)
                if boundary_counter[key] > 0:
                    boundary_counter[key] -= 1
                    continue
            new_rows.append(row)

        # Safety: if a single (time, icao24) pair has so many full-row
        # duplicates that they fill an entire batch, the cursor can't
        # advance and we'd loop forever. Detect that and bail loudly.
        last_row = chunk[-1]
        new_cursor_time = last_row["time"]
        new_cursor_icao24 = last_row["icao24"]
        if (
            new_cursor_time == cursor_time
            and new_cursor_icao24 == cursor_icao24
            and not new_rows
        ):
            raise RuntimeError(
                f"{table_name}: page {page_num} stuck at "
                f"(time={cursor_time}, icao24={cursor_icao24}) — "
                f"{batch_size} consecutive identical rows. Manual "
                f"investigation needed (likely upstream duplication "
                f"larger than batch_size). {len(rows):,} rows fetched "
                f"before stall."
            )

        rows.extend(new_rows)
        if verbose:
            print(f"  {table_name}: fetched {len(rows):,} rows...")

        # Prepare boundary_counter for the next page: track every row in
        # this page at the new cursor position so the next `>=` query
        # can dedupe them.
        boundary_counter = Counter()
        for row in chunk:
            if (
                row["time"] == new_cursor_time
                and row["icao24"] == new_cursor_icao24
            ):
                boundary_counter[_row_key(row)] += 1

        cursor_time = new_cursor_time
        cursor_icao24 = new_cursor_icao24

        if len(chunk) < batch_size:
            break

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
