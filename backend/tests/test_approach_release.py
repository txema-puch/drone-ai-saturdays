from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.core.approach_geometry import EARTH_RADIUS_M, load_lemd_geometry
from backend.scripts import build_approach_release as builder
from backend.scripts import build_contextual_approach_release as contextual_builder
from backend.serve import approach_release


def _approach_frame(runway_name: str = "18L") -> pd.DataFrame:
    runway = load_lemd_geometry().thresholds[runway_name]
    along = np.linspace(12_000, 100, 80)
    bearing = math.radians(runway.true_bearing_deg)
    east = -along * math.sin(bearing)
    north = -along * math.cos(bearing)
    lat = runway.lat + np.degrees(north / EARTH_RADIUS_M)
    lon = runway.lon + np.degrees(
        east / (EARTH_RADIUS_M * np.cos(np.radians(runway.lat)))
    )
    height = np.tan(np.radians(3.0)) * along
    return pd.DataFrame({
        "flight_id": "fixture-operation",
        "icao24": "abc123",
        "callsign": "TEST1",
        "time": 1_700_000_000 + np.arange(80) * 10,
        "lat": lat,
        "lon": lon,
        "baroaltitude": runway.elevation_m + height,
        "geoaltitude": runway.elevation_m + height,
        "velocity": np.linspace(90, 65, 80),
        "heading": runway.true_bearing_deg,
        "vertrate": -3.0,
        "onground": False,
        "alert": False,
        "squawk": "1234",
    })


def _release_payloads(release_dir: Path) -> dict[str, object]:
    return {
        relative: json.loads((release_dir / relative).read_text())
        for relative in approach_release.REQUIRED_FILES
    }


def test_builder_is_deterministic_and_emits_bounded_schema_v3(tmp_path: Path) -> None:
    input_path = tmp_path / "audited-2025.parquet"
    _approach_frame().to_parquet(input_path, index=False)
    left = tmp_path / "left"
    right = tmp_path / "right"

    first = builder.build_approach_release(
        input_path, output=left, max_case_observations=12
    )
    second = builder.build_approach_release(
        input_path, output=right, max_case_observations=12
    )

    assert first == second
    assert first["schema_version"] == 3
    assert len(first["release_id"]) == 20
    assert {item["path"] for item in first["files"]} == approach_release.REQUIRED_FILES
    assert approach_release.validate_release_directory(left) == first
    assert approach_release.validate_release_directory(right) == second
    loaded = approach_release.load_release_directory(left)
    assert loaded["manifest"] == first
    assert len(loaded["attempts"]) == len(loaded["cases"]) == 1
    assert loaded["research"] is None
    cases = json.loads((left / "cases.json").read_text())
    assert len(cases["cases"]) == 1
    assert cases["cases"][0]["observation_count"] == 80
    assert cases["cases"][0]["observations_downsampled"] is True
    assert len(cases["cases"][0]["observations"]) <= 12
    assert (left / "attempts.json").read_bytes() == approach_release.canonical_json_bytes(
        json.loads((left / "attempts.json").read_text())
    )


def test_contextual_builder_embeds_explicit_weather_type_and_qualification(tmp_path: Path) -> None:
    input_path = tmp_path / "audited-2025.parquet"
    frame = _approach_frame()
    frame.to_parquet(input_path, index=False)
    weather_dir = tmp_path / "weather"
    weather_dir.mkdir()
    (weather_dir / "lemd_isd_2023.csv").write_text(
        '"STATION","DATE","REPORT_TYPE","WND","TMP","DEW","MA1","REM"\n'
        '"08221099999","2023-11-14T22:13:20","FM-15",'
        '"180,1,N,0050,1","+0100,1","+0050,1",'
        '"10030,1,99999,9","METAR LEMD Q1003="\n'
    )
    aircraft_dir = tmp_path / "aircraft"
    aircraft_dir.mkdir()
    (aircraft_dir / "aircraftDatabase.part00").write_text(
        '"icao24","typecode","manufacturername","model","categoryDescription"\n'
        '"abc123","A320","Airbus","A320","Large"\n'
    )
    release_dir = tmp_path / "context-release"

    manifest = contextual_builder.build_contextual_release(
        input_path,
        output=release_dir,
        weather_dir=weather_dir,
        aircraft_parts_dir=aircraft_dir,
    )

    assert approach_release.validate_release_directory(release_dir) == manifest
    attempts = json.loads((release_dir / "attempts.json").read_text())["attempts"]
    assert attempts[0]["assessment"]["engine_version"] == "approach_context_v1"
    assert attempts[0]["assessment"]["context"]["weather"]["qnh_hpa"] == 1003.0
    assert attempts[0]["assessment"]["context"]["aircraft"]["typecode"] == "A320"
    config = json.loads((release_dir / "config/approach-config.json").read_text())
    metrics = json.loads((release_dir / "metrics.json").read_text())
    assert config["context_sources"]["qualification"].startswith("not_qualified")
    assert metrics["qualification"].startswith("not_qualified")
    assert metrics["allowed_role"] == (
        "research_and_evidence_labeling_demonstrator"
    )
    assert "operational_monitoring" in metrics["blocked_uses"]
    assert manifest["contracts"]["qualification"].startswith("not_qualified")


def test_validator_rejects_corruption_extras_and_symlinks(tmp_path: Path) -> None:
    input_path = tmp_path / "audited-2025.parquet"
    _approach_frame().to_parquet(input_path, index=False)
    release_dir = tmp_path / "release"
    builder.build_approach_release(input_path, output=release_dir)

    attempts = release_dir / "attempts.json"
    original = attempts.read_bytes()
    attempts.write_bytes(original + b" ")
    with pytest.raises(approach_release.ApproachReleaseIntegrityError, match="attempts.json"):
        approach_release.validate_release_directory(release_dir)
    attempts.write_bytes(original)

    (release_dir / "unexpected.txt").write_text("unexpected")
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="extra_files"):
        approach_release.validate_release_directory(release_dir)
    (release_dir / "unexpected.txt").unlink()

    (release_dir / "alias.json").symlink_to("metrics.json")
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="symlink"):
        approach_release.validate_release_directory(release_dir)


def test_payload_validator_rejects_missing_attempt_contract(tmp_path: Path) -> None:
    input_path = tmp_path / "audited-2025.parquet"
    _approach_frame().to_parquet(input_path, index=False)
    release_dir = tmp_path / "release"
    builder.build_approach_release(input_path, output=release_dir)
    payloads = _release_payloads(release_dir)
    payloads["attempts.json"]["attempts"][0].pop("status")

    with pytest.raises(
        approach_release.ApproachReleaseFormatError, match="unsupported status"
    ):
        approach_release._validate_payloads(payloads)


def test_payload_validator_rejects_permuted_and_duplicate_links(tmp_path: Path) -> None:
    first = _approach_frame()
    second = _approach_frame("32L")
    second["flight_id"] = "fixture-operation-2"
    second["icao24"] = "def456"
    second["time"] += 10_000
    input_path = tmp_path / "audited-2025.parquet"
    pd.concat([first, second], ignore_index=True).to_parquet(input_path, index=False)
    release_dir = tmp_path / "release"
    builder.build_approach_release(input_path, output=release_dir)

    payloads = _release_payloads(release_dir)
    records = payloads["attempts.json"]["attempts"]
    records[0]["case_id"], records[1]["case_id"] = (
        records[1]["case_id"], records[0]["case_id"],
    )
    with pytest.raises(
        approach_release.ApproachReleaseFormatError, match="not reciprocal"
    ):
        approach_release._validate_payloads(payloads)

    payloads = _release_payloads(release_dir)
    operations = payloads["operations.json"]["operations"]
    duplicate_attempt = operations[0]["attempt_ids"][0]
    operations[1]["attempt_ids"].append(duplicate_attempt)
    operations[1]["attempt_count"] += 1
    with pytest.raises(
        approach_release.ApproachReleaseFormatError, match="cover attempts exactly"
    ):
        approach_release._validate_payloads(payloads)


def test_manifest_requires_v3_required_subset_and_optional_allowlist(tmp_path: Path) -> None:
    input_path = tmp_path / "audited-2025.parquet"
    _approach_frame().to_parquet(input_path, index=False)
    release_dir = tmp_path / "release"
    manifest = builder.build_approach_release(input_path, output=release_dir)

    invalid = dict(manifest)
    invalid["schema_version"] = 2
    invalid["release_id"] = approach_release.release_id_for_manifest(invalid)
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="schema_version"):
        approach_release.validate_manifest(invalid)

    missing = dict(manifest)
    missing["files"] = [
        item for item in missing["files"] if item["path"] != "metrics.json"
    ]
    missing["release_id"] = approach_release.release_id_for_manifest(missing)
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="missing"):
        approach_release.validate_manifest(missing)

    extra = dict(manifest)
    extra["files"] = [
        *extra["files"],
        {"path": "not-allowed.json", "sha256": "0" * 64, "bytes": 0},
    ]
    extra["files"] = sorted(extra["files"], key=lambda item: item["path"])
    extra["release_id"] = approach_release.release_id_for_manifest(extra)
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="allowlisted"):
        approach_release.validate_manifest(extra)


def test_builder_refuses_sealed_2026_before_parquet_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = tmp_path / "sealed.parquet"
    sealed.write_bytes(b"not parsed")
    read = False

    def fail_if_read(*args, **kwargs):
        nonlocal read
        read = True
        raise AssertionError("sealed parquet was read")

    monkeypatch.setattr(
        builder, "file_sha256", lambda path: next(iter(builder.SEALED_HOLDOUT_SHA256))
    )
    monkeypatch.setattr(builder.pd, "read_parquet", fail_if_read)
    with pytest.raises(ValueError, match="sealed 2026 holdout"):
        builder.build_approach_release(sealed, output=tmp_path / "release")
    assert read is False
