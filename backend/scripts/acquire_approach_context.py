"""Acquire or audit the external context inputs used by approach research.

The OpenSky aircraft URL is a mutable current snapshot. Reproducibility therefore
comes from the recorded retrieval time, byte length, per-part hashes, and logical
content hash—not from pretending the URL is immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import requests


REPO = Path(__file__).resolve().parents[2]
WEATHER_DIR = REPO / "data/raw/weather"
AIRCRAFT_DIR = REPO / "data/raw/aircraft_metadata"
DEFAULT_MANIFEST = (
    REPO / "backend/docs/ml/iterations/approach-context/source-manifest.json"
)
WEATHER_URL = (
    "https://www.ncei.noaa.gov/data/global-hourly/access/{year}/08221099999.csv"
)
AIRCRAFT_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
AIRCRAFT_PART_BYTES = 10_000_000
MAX_WEATHER_BYTES = 32 * 1024 * 1024
MAX_AIRCRAFT_BYTES = 256 * 1024 * 1024
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _observed_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _atomic_stream(
    response: requests.Response,
    destination: Path,
    *,
    maximum_bytes: int,
) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError(f"download exceeds byte limit: {destination.name}")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"bytes": size, "sha256": digest.hexdigest()}


def acquire_weather(years: list[int], directory: Path) -> None:
    for year in years:
        url = WEATHER_URL.format(year=year)
        with requests.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            _atomic_stream(
                response,
                directory / f"lemd_isd_{year}.csv",
                maximum_bytes=MAX_WEATHER_BYTES,
            )


def acquire_aircraft(directory: Path) -> None:
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".aircraft-metadata.", dir=directory.parent))
    try:
        offset = 0
        part = 0
        total = None
        while total is None or offset < total:
            end = offset + AIRCRAFT_PART_BYTES - 1
            with requests.get(
                AIRCRAFT_URL,
                headers={"Range": f"bytes={offset}-{end}"},
                stream=True,
                timeout=(15, 120),
            ) as response:
                if response.status_code != 206:
                    raise ValueError("aircraft source did not honor bounded byte ranges")
                matched = _CONTENT_RANGE.fullmatch(
                    response.headers.get("Content-Range", "")
                )
                if matched is None or int(matched.group(1)) != offset:
                    raise ValueError("aircraft source returned an invalid Content-Range")
                observed_end = int(matched.group(2))
                total = int(matched.group(3))
                if total > MAX_AIRCRAFT_BYTES or observed_end >= total:
                    raise ValueError("aircraft source declared an invalid byte range")
                record = _atomic_stream(
                    response,
                    staging / f"aircraftDatabase.part{part:02d}",
                    maximum_bytes=AIRCRAFT_PART_BYTES,
                )
                if record["bytes"] != observed_end - offset + 1:
                    raise ValueError("aircraft range byte length mismatch")
                offset = observed_end + 1
                part += 1
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("aircraftDatabase.part*"):
            stale.unlink()
        for completed in sorted(staging.glob("aircraftDatabase.part*")):
            os.replace(completed, directory / completed.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def audit_sources(
    *,
    years: list[int],
    weather_dir: Path,
    aircraft_dir: Path,
    repository_root: Path = REPO,
) -> dict[str, object]:
    weather = []
    for year in years:
        path = weather_dir / f"lemd_isd_{year}.csv"
        weather.append({
            "year": year,
            "url": WEATHER_URL.format(year=year),
            "path": path.relative_to(repository_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "local_file_mtime_utc": _observed_at(path),
        })
    parts = sorted(aircraft_dir.glob("aircraftDatabase.part*"))
    if not parts:
        raise FileNotFoundError("aircraft metadata parts are missing")
    logical = hashlib.sha256()
    part_records = []
    for path in parts:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                logical.update(chunk)
        part_records.append({
            "path": path.relative_to(repository_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "local_file_mtime_utc": _observed_at(path),
        })
    return {
        "schema_version": "approach_context_sources_v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "weather": {
            "provider": "NOAA NCEI Global Hourly",
            "station": "08221099999",
            "access": "public HTTPS",
            "license_note": "U.S. government data; review NOAA/NCEI terms and attribution guidance.",
            "files": weather,
        },
        "aircraft": {
            "provider": "OpenSky Network aircraft database",
            "url": AIRCRAFT_URL,
            "snapshot_semantics": "mutable current snapshot",
            "logical_bytes": sum(item["bytes"] for item in part_records),
            "logical_sha256": logical.hexdigest(),
            "parts": part_records,
            "terms_url": "https://opensky-network.org/about/terms-of-use",
            "license_scope": "non-profit research and non-profit education only unless separately licensed",
            "publication_obligation": "cite OpenSky and provide it a copy or link for public web pages/publications",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[2017, 2018, 2019, 2025])
    parser.add_argument("--weather-dir", type=Path, default=WEATHER_DIR)
    parser.add_argument("--aircraft-dir", type=Path, default=AIRCRAFT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Refresh mutable sources before auditing. Omit to audit existing local files.",
    )
    args = parser.parse_args()
    if args.download:
        acquire_weather(args.years, args.weather_dir)
        acquire_aircraft(args.aircraft_dir)
    manifest = audit_sources(
        years=args.years,
        weather_dir=args.weather_dir,
        aircraft_dir=args.aircraft_dir,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
