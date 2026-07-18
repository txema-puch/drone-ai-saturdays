from __future__ import annotations

import json
import re
import subprocess
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from sadar.approach.geometry import load_lemd_geometry
from sadar.demo.catalog import (
    DEFAULT_SEED,
    GENERATOR_VERSION,
    generate_demo_payloads,
    semantic_snapshot,
)
from sadar.demo.generator import round_trip_error_m
from sadar.demo.scenarios import SCENARIOS, SCENARIO_IDS, Scenario
from sadar.pipelines import build_release as release_builder
from sadar.pipelines.build_synthetic_demo import build_synthetic_demo
from sadar.releases.approach import (
    ApproachReleaseIntegrityError,
    canonical_json_bytes,
    validate_public_release_directory,
)


REPO = Path(__file__).resolve().parents[3]
SNAPSHOT = Path(__file__).parent / "fixtures/synthetic_demo_snapshot.json"
EXPECTED_IDS = {
    "stable-rwy-32l", "low-speed-rwy-32l", "high-speed-rwy-18r",
    "descent-rate-rwy-32r", "lateral-offset-rwy-18l",
    "late-track-correction-rwy-32l", "multi-criterion-rwy-18r",
    "evidence-ends-early-rwy-32l", "short-record-rwy-18l",
    "large-internal-gap-rwy-32r", "parallel-runway-ambiguity-32",
    "go-around-rwy-18r", "touch-and-go-rwy-32l",
    "altitude-rate-conflict-rwy-32l",
}
EXPECTED_OUTCOMES = {
    "landing_observed", "go_around", "touch_and_go", "final_gate_observed",
    "incomplete",
}


@pytest.fixture(scope="module")
def payloads() -> dict[str, object]:
    return generate_demo_payloads(
        seed=DEFAULT_SEED,
        methodology_payloads=release_builder._methodology_payloads(),
    )


def test_catalog_is_complete_declarative_and_covers_required_states(payloads) -> None:
    required_fields = {
        "scenario_id", "title", "teaching_goal", "runway", "start_along_track_m",
        "end_along_track_m", "duration_s", "sample_interval_s",
        "cross_track_profile_m", "barometric_altitude_profile_m",
        "ground_speed_profile_mps", "vertical_rate_profile_mps",
        "heading_offset_profile_deg", "coverage_gaps", "expected_status",
        "expected_failed_criteria", "expected_outcome", "expected_runway_specificity",
        "expected_quality_flags",
    }
    assert {item.name for item in fields(Scenario)} == required_fields
    assert len(SCENARIOS) == 14
    assert SCENARIO_IDS == EXPECTED_IDS
    assert len({item.scenario_id for item in SCENARIOS}) == 14
    assert all(
        re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item.scenario_id)
        for item in SCENARIOS
    )
    assert {item.expected_status for item in SCENARIOS} == {
        "criteria_observed", "review_required", "partial_observation", "not_assessable",
    }
    attempts = payloads["attempts.json"]["attempts"]
    assert {item["outcome"] for item in attempts} == EXPECTED_OUTCOMES
    assert {item["scenario_id"] for item in attempts} == EXPECTED_IDS


def test_geometry_round_trips_every_supported_landing_runway() -> None:
    geometry = load_lemd_geometry()
    along = np.array([-200.0, 0.0, 3_500.0, 12_000.0])
    for runway_name in ("18L", "18R", "32L", "32R"):
        runway = geometry.thresholds[runway_name]
        for cross in (-1_000.0, 0.0, 1_000.0):
            along_error, cross_error = round_trip_error_m(
                along, np.full(len(along), cross), runway
            )
            assert along_error <= 5.0
            assert cross_error <= 5.0


def test_all_scenarios_match_declared_assessments(payloads) -> None:
    attempts = {
        item["scenario_id"]: item for item in payloads["attempts.json"]["attempts"]
    }
    for scenario in SCENARIOS:
        attempt = attempts[scenario.scenario_id]
        assessment = attempt["assessment"]
        quality = assessment["quality"]
        flags = set(quality["fatal_reasons"])
        flags.update(
            flag
            for channel in quality["channel_advisories"].values()
            for flag in channel
        )
        assert attempt["status"] == scenario.expected_status
        assert set(attempt["failed_criteria"]) == set(scenario.expected_failed_criteria)
        assert attempt["outcome"] == scenario.expected_outcome
        assert assessment["runway_inference"]["specificity"] == scenario.expected_runway_specificity
        assert flags == set(scenario.expected_quality_flags)


def test_stable_case_is_an_observed_landing(payloads) -> None:
    attempt = next(
        item for item in payloads["attempts.json"]["attempts"]
        if item["scenario_id"] == "stable-rwy-32l"
    )
    case = next(
        item for item in payloads["cases.json"]["cases"]
        if item["scenario_id"] == "stable-rwy-32l"
    )
    assert attempt["status"] == "criteria_observed"
    assert attempt["failed_criteria"] == []
    assert attempt["outcome"] == "landing_observed"
    assert any(item["onground"] for item in case["observations"])
    assert attempt["landing_outcome"]["available"] is True


def test_early_ending_case_separates_gate_from_landing_availability(payloads) -> None:
    attempt = next(
        item for item in payloads["attempts.json"]["attempts"]
        if item["scenario_id"] == "evidence-ends-early-rwy-32l"
    )
    case = next(
        item for item in payloads["cases.json"]["cases"]
        if item["scenario_id"] == "evidence-ends-early-rwy-32l"
    )
    times = [item["time"] for item in case["observations"]]
    assert attempt["status"] == "partial_observation"
    assert attempt["outcome"] == "final_gate_observed"
    assert attempt["outcome"] != "landing_observed"
    assert max(np.diff(times)) == 2
    signal = attempt["landing_outcome"]
    assert signal == case["landing_outcome"]
    assert signal["available"] is False
    assert signal["reason"] == "evidence_ends_before_threshold"
    assert signal["evidence_end_along_track_m"] == pytest.approx(3_500.0, abs=100.0)


def test_speed_evidence_exposes_explanatory_operands(payloads) -> None:
    attempt = next(
        item for item in payloads["attempts.json"]["attempts"]
        if item["scenario_id"] == "low-speed-rwy-32l"
    )
    criterion = next(
        item for item in attempt["assessment"]["criteria"]
        if item["name"] == "observed_ground_speed_envelope"
    )
    evidence = criterion["evidence"][0]
    assert {"value", "limit", "start_time", "end_time", "along_track_m"} <= set(evidence)
    assert evidence["value"] < evidence["limit"]
    assert evidence["end_time"] - evidence["start_time"] >= 20


def test_payloads_are_explicitly_synthetic_and_one_to_one(payloads) -> None:
    for lane in ("attempts", "cases", "operations"):
        records = payloads[f"{lane}.json"][lane]
        assert len(records) == 14
        assert all(item["data_origin"] == "synthetic" for item in records)
    assert all(
        item["attempt_id"].startswith("syn-a-")
        for item in payloads["attempts.json"]["attempts"]
    )
    assert all(item["case_id"].startswith("syn-c-") for item in payloads["cases.json"]["cases"])
    assert all(
        item["operation_id"].startswith("syn-op-")
        for item in payloads["operations.json"]["operations"]
    )
    encoded = b"".join(canonical_json_bytes(payload) for payload in payloads.values())
    for forbidden in (b'"icao24"', b'"callsign"', b'"squawk"', b'"alert"', b'"flight_id"'):
        assert forbidden not in encoded


def test_two_independent_builds_are_byte_identical_and_match_snapshot(
    tmp_path: Path, payloads
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    build_synthetic_demo(output=left, seed=DEFAULT_SEED)
    build_synthetic_demo(output=right, seed=DEFAULT_SEED)
    for name in ("catalog.json", "attempts.json", "cases.json", "operations.json"):
        assert (left / "demo" / name).read_bytes() == (right / "demo" / name).read_bytes()
    assert semantic_snapshot(payloads) == json.loads(SNAPSHOT.read_text())


def test_cli_has_no_data_input_and_rejects_nonempty_output(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(REPO / "backend/.venv/bin/sadar-build-synthetic-demo"), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--output" in result.stdout
    assert "--seed" in result.stdout
    assert "--reference" in result.stdout
    assert set(re.findall(r"--[a-z-]+", result.stdout)) == {
        "--help", "--output", "--seed", "--reference",
    }
    for forbidden in ("--input", "parquet", "csv", "dataset"):
        assert forbidden not in result.stdout.lower()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="must not already contain"):
        build_synthetic_demo(output=occupied, seed=DEFAULT_SEED)


def test_public_builder_regenerates_and_rejects_relabelled_telemetry(tmp_path: Path) -> None:
    synthetic = tmp_path / "synthetic"
    build_synthetic_demo(output=synthetic, seed=DEFAULT_SEED)
    cases_path = synthetic / "demo/cases.json"
    cases = json.loads(cases_path.read_text())
    cases["cases"][0]["observations"][0]["lat"] += 0.0001
    cases_path.write_bytes(canonical_json_bytes(cases))
    with pytest.raises(ApproachReleaseIntegrityError, match="generator output"):
        release_builder.build_public_release(
            aggregate_results_path=release_builder.PUBLIC_AGGREGATE_RESOURCE,
            synthetic_payload_dir=synthetic,
            output=tmp_path / "release",
        )


def test_schema_v4_release_integration_validates(tmp_path: Path) -> None:
    synthetic = tmp_path / "synthetic"
    release = tmp_path / "release"
    build_synthetic_demo(output=synthetic, seed=DEFAULT_SEED)
    manifest = release_builder.build_public_release(
        aggregate_results_path=Path(__file__).parent / "fixtures/public_aggregate_results.json",
        synthetic_payload_dir=synthetic,
        output=release,
    )
    validated = validate_public_release_directory(release)
    assert validated == manifest
    assert validated["schema_version"] == 4
    assert validated["source"]["synthetic_seed"] == DEFAULT_SEED
    assert len(json.loads((release / "demo/catalog.json").read_text())["scenarios"]) == 14


def test_generator_source_has_no_row_level_reader() -> None:
    result = subprocess.run(
        [
            "rg", "-n", "read_parquet|read_csv|data/raw|models/",
            "backend/src/sadar/demo", "backend/src/sadar/pipelines/build_synthetic_demo.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    assert GENERATOR_VERSION == "sadar_synthetic_approach_v1"
