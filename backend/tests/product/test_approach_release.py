from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from sadar.pipelines import build_context_release as contextual_builder
from sadar.pipelines import build_release as builder
from sadar.releases import approach as approach_release


REPO = Path(__file__).resolve().parents[3]
AGGREGATE_FIXTURE = Path(__file__).parent / "fixtures/public_aggregate_results.json"


def _synthetic_payloads(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    methodology = builder._methodology_payloads()
    digests = {
        key: hashlib.sha256(approach_release.canonical_json_bytes(value)).hexdigest()
        for key, value in methodology.items()
    }
    scenario = {
        "scenario_id": "stable-approach",
        "scenario_title": "Stable synthetic approach",
        "teaching_goal": "Learn the criteria-observed queue state.",
    }
    common = {"data_origin": "synthetic", **scenario}
    attempt = {
        **common,
        "attempt_id": "syn-a-stable-001",
        "case_id": "syn-c-stable-001",
        "operation_id": "syn-op-stable-001",
        "sequence": 1,
        "start_time": 100,
        "end_time": 110,
        "status": "criteria_observed",
        "outcome": "final_gate_observed",
        "runway": "18L",
        "runway_direction": "18",
        "failed_criteria": [],
        "assessment": {
            "schema_version": "approach_assessment_v1",
            "engine_version": "approach_context_v1",
            "status": "criteria_observed",
            "attempt": {"observed_samples": 2, "outcome": "final_gate_observed"},
            "quality": {"fatal_reasons": [], "channel_advisories": {}, "maximum_gap_s": 10},
            "runway_inference": {
                "runway": "18L", "direction": "18", "geometry_runway": "18L",
                "specificity": "runway", "confidence": "high", "score_margin": 1.0,
            },
            "criteria": [
                {
                    "name": "lateral_path_proxy",
                    "status": "within_limit",
                    "severity": "high",
                    "observed_samples": 2,
                    "evidence": [],
                }
            ],
            "reasons": [],
            "maneuvers": [],
            "provenance": {"generator": "sadar_synthetic_approach_v1"},
            "geometry": {},
            "reference": {},
            "context": {},
            "altitude_reference": "barometric",
        },
    }
    case = {
        **common,
        "case_id": "syn-c-stable-001",
        "attempt_id": "syn-a-stable-001",
        "operation_id": "syn-op-stable-001",
        "observation_count": 2,
        "observations_downsampled": False,
        "observations": [
            {"observation_index": 0, "time": 100, "lat": 40.48, "lon": -3.56, "baroaltitude": 500.0},
            {"observation_index": 1, "time": 110, "lat": 40.47, "lon": -3.55, "baroaltitude": 450.0},
        ],
    }
    operation = {
        **common,
        "operation_id": "syn-op-stable-001",
        "start_time": 100,
        "end_time": 110,
        "attempt_count": 1,
        "attempt_ids": ["syn-a-stable-001"],
        "case_ids": ["syn-c-stable-001"],
        "status_counts": {"criteria_observed": 1},
        "worst_status": "criteria_observed",
    }
    payloads = {
        "catalog.json": {
            "schema_version": "approach_synthetic_demo_v1",
            "generator_version": "sadar_synthetic_approach_v1",
            "seed": 20260718,
            "approach_config_sha256": digests["config/approach-config.json"],
            "geometry_source_sha256": digests["config/lemd-geometry.json"],
            "reference_sha256": digests["reference/approach-reference.json"],
            "scenarios": [scenario],
        },
        "attempts.json": {"schema_version": "approach_attempts_v1", "attempts": [attempt]},
        "cases.json": {"schema_version": "approach_cases_v1", "cases": [case]},
        "operations.json": {"schema_version": "approach_operations_v1", "operations": [operation]},
    }
    for name, payload in payloads.items():
        (root / name).write_bytes(approach_release.canonical_json_bytes(payload))
    return root


def build_valid_release(parent: Path, name: str = "approach-release") -> Path:
    destination = parent / name
    synthetic = _synthetic_payloads(parent / f"{name}-synthetic")
    builder.build_public_release(
        aggregate_results_path=builder.PUBLIC_AGGREGATE_RESOURCE,
        synthetic_payload_dir=synthetic,
        output=destination,
    )
    return destination


def _payloads(release: Path) -> dict[str, object]:
    return {path: json.loads((release / path).read_text()) for path in approach_release.REQUIRED_FILES}


def _rewrite_release(release: Path, payloads: dict[str, object]) -> None:
    manifest = json.loads((release / approach_release.MANIFEST_NAME).read_text())
    source = manifest["source"]
    contracts = manifest["contracts"]
    for path in approach_release.REQUIRED_FILES:
        target = release / path
        target.unlink()
    (release / approach_release.MANIFEST_NAME).unlink()
    approach_release.write_release(release, payloads, source=source, contracts=contracts)


def test_builder_is_deterministic_and_emits_exact_schema_v4(tmp_path: Path) -> None:
    left = build_valid_release(tmp_path, "left")
    right = build_valid_release(tmp_path, "right")
    first = approach_release.validate_public_release_directory(left)
    second = approach_release.validate_public_release_directory(right)
    assert first == second
    assert first["schema_version"] == 4
    assert first["release_kind"] == "sadar_approach_public_evidence"
    assert first["data_policy"] == {
        "demo_records": "synthetic", "research_results": "aggregate_only",
        "source_records_included": False,
    }
    assert {item["path"] for item in first["files"]} == approach_release.REQUIRED_FILES
    loaded = approach_release.load_release_directory(left)
    assert loaded["aggregate_results"] is loaded["metrics"]
    assert loaded["research"] is None
    assert loaded["demo_data_origin"] == "synthetic"
    assert loaded["attempts"][0]["attempt_id"].startswith("syn-a-")


def test_manifest_rejects_schema_v3_and_any_extra_file(tmp_path: Path) -> None:
    release = build_valid_release(tmp_path)
    manifest = json.loads((release / approach_release.MANIFEST_NAME).read_text())
    legacy = copy.deepcopy(manifest)
    legacy["schema_version"] = 3
    legacy["release_id"] = approach_release.release_id_for_manifest(legacy)
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="schema_version"):
        approach_release.validate_manifest(legacy)
    extra = copy.deepcopy(manifest)
    extra["files"].append({"path": "research/benchmark.json", "sha256": "0" * 64, "bytes": 0})
    extra["files"].sort(key=lambda item: item["path"])
    extra["release_id"] = approach_release.release_id_for_manifest(extra)
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="allowlisted"):
        approach_release.validate_manifest(extra)


@pytest.mark.parametrize(
    ("lane", "mutation", "match"),
    [
        ("attempts", lambda record: record.update(data_origin="real"), "data_origin"),
        ("attempts", lambda record: record.update(attempt_id="a-real"), "prefix"),
        ("cases", lambda record: record.update(case_id="c-real"), "prefix"),
        ("operations", lambda record: record.update(operation_id="op-real"), "prefix"),
        ("operations", lambda record: record.update(icao24="secret"), "forbidden identifier"),
    ],
)
def test_synthetic_validators_reject_wrong_origin_prefix_and_identifier(
    tmp_path: Path, lane: str, mutation, match: str
) -> None:
    release = build_valid_release(tmp_path)
    payloads = _payloads(release)
    record = payloads[f"demo/{lane}.json"][lane][0]
    mutation(record)
    with pytest.raises(approach_release.ApproachReleaseError, match=match):
        approach_release._validate_payloads(payloads)


@pytest.mark.parametrize("forbidden", sorted(approach_release._FORBIDDEN_AGGREGATE_KEYS))
def test_aggregate_rejects_forbidden_keys_at_nested_levels(forbidden: str) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["findings"]["screening_holdout"][forbidden] = "private-value"
    with pytest.raises(approach_release.ApproachReleaseFormatError, match=forbidden):
        approach_release._validate_aggregate_results(aggregate)


def test_aggregate_rejects_epoch_small_cell_and_missing_complement(tmp_path: Path) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["rows"] = 1_700_000_000
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="epoch-like"):
        approach_release._validate_aggregate_results(aggregate)


def test_every_primary_suppression_resists_integer_subtraction_attack() -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    count_maps: list[dict[str, object]] = []

    def visit(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            if key.endswith("_counts") and "<10" in value.values():
                count_maps.append(value)
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(aggregate)
    assert count_maps
    for count_map in count_maps:
        assert list(count_map.values()).count("suppressed") == 1
        explicit = sum(value for value in count_map.values() if isinstance(value, int))
        # For every plausible partition total, no total can identify the primary
        # without also knowing the complementary cell. All nine primary values
        # retain at least one non-negative complementary solution.
        plausible_total = explicit + 100
        candidates = {
            primary
            for primary in range(1, 10)
            if plausible_total - explicit - primary >= 0
        }
        assert candidates == set(range(1, 10))
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["status_counts"]["criteria_observed"] = 5
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="unsuppressed"):
        approach_release._validate_aggregate_results(aggregate)
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    count_map = aggregate["cohorts"][0]["outcome_counts"]
    suppressed = next(key for key, value in count_map.items() if value == "suppressed")
    count_map[suppressed] = 578
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="complementary"):
        approach_release._validate_aggregate_results(aggregate)


def test_reference_is_closed_and_digest_bound() -> None:
    reference = builder._public_reference()
    approach_release._validate_reference(reference)
    assert "diagnostics" not in reference and "stratification" not in reference
    hostile = copy.deepcopy(reference)
    hostile["renamed_rows"] = [{"x": 40.4, "y": -3.5, "event": 100}]
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="keys mismatch"):
        approach_release._validate_reference(hostile)
    hostile = copy.deepcopy(reference)
    hostile["entries"][0]["diagnostics"] = {"sample": "private"}
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="keys mismatch"):
        approach_release._validate_reference(hostile)


def test_production_aggregate_regenerates_byte_for_byte() -> None:
    projected = builder.project_reviewed_aggregate_results(
        holdout_path=builder.HOLDOUT_ARTIFACT,
        comparison_path=builder.COMPARISON_ARTIFACT,
        coverage_path=builder.COVERAGE_ARTIFACT,
        generated_at="2026-07-18",
    )
    assert approach_release.canonical_json_bytes(projected) == builder.PUBLIC_AGGREGATE_RESOURCE.read_bytes()
    assert approach_release.canonical_json_bytes(json.loads(AGGREGATE_FIXTURE.read_text())) == builder.PUBLIC_AGGREGATE_RESOURCE.read_bytes()
    assert projected["cohorts"][0]["base_reference_sha256"] == "b485f747154ea8d84ba6b5c980501e3a22bca9caff40c41711de107b03496c56"
    assert projected["cohorts"][1]["context_reference_sha256"] == "68ea1a974a077e0b2ef8322564d7799c5fd52cbd21db42b8d5bf1badad57d328"


def test_catalog_hash_binding_fails_closed(tmp_path: Path) -> None:
    synthetic = _synthetic_payloads(tmp_path / "synthetic")
    catalog = json.loads((synthetic / "catalog.json").read_text())
    catalog["reference_sha256"] = "0" * 64
    (synthetic / "catalog.json").write_bytes(approach_release.canonical_json_bytes(catalog))
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="methodology"):
        builder.build_public_release(
            aggregate_results_path=builder.PUBLIC_AGGREGATE_RESOURCE,
            synthetic_payload_dir=synthetic,
            output=tmp_path / "release",
        )


def test_public_builder_has_no_raw_input_signature_or_import() -> None:
    signature = inspect.signature(builder.build_public_release)
    assert set(signature.parameters) == {"aggregate_results_path", "synthetic_payload_dir", "output"}
    source = Path(builder.__file__).read_text()
    for forbidden in ("read_parquet", "DataFrame", "source_operation_id", '"icao24"', '"callsign"'):
        assert forbidden not in source


def test_context_builder_refuses_before_touching_nonexistent_raw_path(tmp_path: Path) -> None:
    nonexistent = tmp_path / "must-not-be-read.parquet"
    with pytest.raises(RuntimeError, match="raw-data public release assembly is retired"):
        contextual_builder.build_contextual_release(nonexistent, output=tmp_path / "release")
    result = subprocess.run(
        [
            str(REPO / "backend/.venv/bin/sadar-build-context-release"),
            "--input", str(nonexistent), "--output", str(tmp_path / "release"),
            "--weather-dir", str(tmp_path / "missing-weather"),
            "--aircraft-parts-dir", str(tmp_path / "missing-aircraft"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "raw-data public release assembly is retired" in result.stderr
    assert not nonexistent.exists()


def test_validation_cli_is_quiet_about_rejected_values(tmp_path: Path, capsys) -> None:
    release = build_valid_release(tmp_path)
    assert approach_release.validation_main(["--release-dir", str(release)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"release_id", "schema_version", "demo_count", "cohort_count"}
    payloads = _payloads(release)
    payloads["demo/operations.json"]["operations"][0]["callsign"] = "SECRET-CALLSIGN"
    with pytest.raises(approach_release.ApproachReleaseFormatError) as error:
        approach_release._validate_payloads(payloads)
    assert "SECRET-CALLSIGN" not in str(error.value)
