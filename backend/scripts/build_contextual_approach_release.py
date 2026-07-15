"""Build an explicitly unqualified contextual schema-v3 research release."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from backend.core.approach_context import (
    load_aircraft_metadata_parts,
    load_global_hourly_weather,
)
from backend.core.approach_geometry import GEOMETRY_PATH
from backend.core.approach_reference import load_approach_reference
from backend.scripts.audit_approach_context import (
    AIRCRAFT_PARTS_DIR,
    WEATHER_DIR,
    _logical_parts_sha256,
)
from backend.scripts.build_approach_release import (
    DEFAULT_INPUT,
    MAX_CASE_OBSERVATIONS,
    assert_not_sealed,
    build_payloads,
    file_sha256,
)
from backend.serve.approach_release import (
    ApproachReleaseError,
    validate_release_directory,
    write_release,
)


REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO / "backend/models/sadar_approach_context_v1"
DEFAULT_REFERENCE = (
    REPO / "backend/core/resources/lemd_approach_context_reference_v1.json"
)


def build_contextual_release(
    input_path: Path = DEFAULT_INPUT,
    *,
    output: Path = DEFAULT_OUTPUT,
    reference_path: Path = DEFAULT_REFERENCE,
    weather_dir: Path = WEATHER_DIR,
    aircraft_parts_dir: Path = AIRCRAFT_PARTS_DIR,
    max_case_observations: int = MAX_CASE_OBSERVATIONS,
) -> dict:
    input_path = Path(input_path)
    output = Path(output)
    input_digest = assert_not_sealed(input_path)
    frame = pd.read_parquet(input_path)
    years = sorted(
        set(pd.to_datetime(frame["time"], unit="s", utc=True).dt.year.astype(int))
    )
    weather_paths = [weather_dir / f"lemd_isd_{year}.csv" for year in years]
    weather = []
    for path in weather_paths:
        weather.extend(load_global_hourly_weather(path))
    weather.sort(key=lambda item: item.observed_at)
    requested = set(frame["icao24"].dropna().astype(str).str.lower().str.strip())
    aircraft = load_aircraft_metadata_parts(aircraft_parts_dir, requested)
    sources = {
        "qualification": "not_qualified_no_independent_labels_or_fresh_holdout",
        "weather_station": "08221099999",
        "weather_files_sha256": {
            path.name: file_sha256(path) for path in weather_paths
        },
        "aircraft_metadata_sha256": _logical_parts_sha256(aircraft_parts_dir),
        "aircraft_metadata_temporal_warning": (
            "Current OpenSky registry metadata may not represent historical identity."
        ),
        "unavailable": ["aircraft_configuration", "actual_mass", "atc_clearance"],
    }
    payloads, source, contracts = build_payloads(
        frame,
        input_sha256=input_digest,
        reference=load_approach_reference(reference_path),
        geometry_payload=json.loads(GEOMETRY_PATH.read_text()),
        contextual={"weather": weather, "aircraft": aircraft, "sources": sources},
        max_case_observations=max_case_observations,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    candidate = temporary_root / "release"
    try:
        manifest = write_release(candidate, payloads, source=source, contracts=contracts)
        if output.exists():
            existing = validate_release_directory(output)
            if existing != manifest:
                raise ApproachReleaseError(
                    f"output already contains a different release: {existing['release_id']}"
                )
            return existing
        os.replace(candidate, output)
        return validate_release_directory(output)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--weather-dir", type=Path, default=WEATHER_DIR)
    parser.add_argument("--aircraft-parts-dir", type=Path, default=AIRCRAFT_PARTS_DIR)
    parser.add_argument("--max-case-observations", type=int, default=MAX_CASE_OBSERVATIONS)
    args = parser.parse_args()
    manifest = build_contextual_release(
        args.input,
        output=args.output,
        reference_path=args.reference,
        weather_dir=args.weather_dir,
        aircraft_parts_dir=args.aircraft_parts_dir,
        max_case_observations=args.max_case_observations,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
