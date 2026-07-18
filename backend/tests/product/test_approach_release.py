from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from sadar.pipelines import build_context_release as contextual_builder
from sadar.pipelines import build_release as builder
from sadar.pipelines.build_synthetic_demo import build_synthetic_demo
from sadar.releases import approach as approach_release


REPO = Path(__file__).resolve().parents[3]
AGGREGATE_FIXTURE = Path(__file__).parent / "fixtures/public_aggregate_results.json"


def _synthetic_payloads(root: Path) -> Path:
    build_synthetic_demo(output=root, seed=20_260_718)
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


def _replace_payload_without_validation(
    release: Path, relative: str, payload: object
) -> None:
    manifest = json.loads((release / approach_release.MANIFEST_NAME).read_text())
    data = approach_release.canonical_json_bytes(payload)
    (release / relative).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    record = next(item for item in manifest["files"] if item["path"] == relative)
    record["bytes"] = len(data)
    record["sha256"] = digest
    if relative == "research/aggregate-results.json":
        manifest["source"]["aggregate_artifact_sha256"] = digest
        manifest["contracts"]["aggregate_results_sha256"] = digest
    manifest["release_id"] = approach_release.release_id_for_manifest(manifest)
    (release / approach_release.MANIFEST_NAME).write_bytes(
        approach_release.canonical_json_bytes(manifest)
    )


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
        ("attempts", lambda record: record["assessment"].update(icao24="secret"), "icao24"),
        ("cases", lambda record: record.update(case_id="c-real"), "prefix"),
        ("cases", lambda record: record["observations"][0].update(callsign="secret"), "callsign"),
        ("operations", lambda record: record.update(operation_id="op-real"), "prefix"),
        ("operations", lambda record: record.update(icao24="secret"), "icao24"),
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


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payloads: payloads["demo/attempts.json"]["attempts"][0].pop("assessment"), "assessment"),
        (
            lambda payloads: payloads["demo/cases.json"]["cases"][0]["observations"][0].update(lat="invalid"),
            "lat",
        ),
        (
            lambda payloads: payloads["demo/cases.json"]["cases"][0].update(observation_count=99),
            "observation_count",
        ),
    ],
)
def test_synthetic_validators_reject_runtime_unsafe_shapes(
    tmp_path: Path, mutation, match: str
) -> None:
    release = build_valid_release(tmp_path)
    payloads = _payloads(release)
    mutation(payloads)
    with pytest.raises(approach_release.ApproachReleaseError, match=match):
        approach_release._validate_payloads(payloads)


@pytest.mark.parametrize("bad_date", ["2026-99-99", "2026-02-30", "2026-07-19"])
def test_publication_notice_rejects_impossible_or_future_dates(bad_date: str) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["data_access"]["publication_notice_status"] = "sent"
    aggregate["data_access"]["publication_notice_date"] = bad_date
    with pytest.raises(
        approach_release.ApproachReleaseFormatError,
        match="publication_notice_date",
    ):
        approach_release._validate_aggregate_results(aggregate)


@pytest.mark.parametrize("forbidden", sorted(approach_release._FORBIDDEN_AGGREGATE_KEYS))
def test_aggregate_rejects_forbidden_keys_at_nested_levels(forbidden: str) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["findings"]["screening_holdout"][forbidden] = "private-value"
    with pytest.raises(approach_release.ApproachReleaseFormatError, match=forbidden):
        approach_release._validate_aggregate_results(aggregate)


@pytest.mark.parametrize(
    ("status", "date", "accepted"),
    [
        ("pending", None, True),
        ("pending", "2026-07-18", False),
        ("sent", "2026-07-18", True),
        ("sent", None, False),
        ("acknowledged", "2026-07-18", True),
        ("acknowledged", None, False),
    ],
)
def test_publication_notice_status_date_matrix(
    status: str, date: str | None, accepted: bool
) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["data_access"]["publication_notice_status"] = status
    aggregate["data_access"]["publication_notice_date"] = date

    if accepted:
        approach_release._validate_aggregate_results(aggregate)
        return

    with pytest.raises(
        approach_release.ApproachReleaseFormatError,
        match="publication_notice_date",
    ) as exc_info:
        approach_release._validate_aggregate_results(aggregate)
    message = str(exc_info.value)
    assert status not in message
    if date is not None:
        assert date not in message


def test_aggregate_rejects_epoch_small_cell_and_missing_complement(tmp_path: Path) -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["rows"] = 1_700_000_000
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="epoch-like"):
        approach_release._validate_aggregate_results(aggregate)


def test_reconstruction_safety_rejects_uniquely_recoverable_primary() -> None:
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    holdout = aggregate["cohorts"][0]
    holdout["attempts"] = 525
    holdout["assessable_attempts"] = 299
    holdout["status_counts"] = {
        "criteria_observed": "<10",
        "not_assessable": 226,
        "partial_observation": 288,
        "review_required": "suppressed",
    }
    holdout["abstention_rate"] = round(226 / 525, 4)
    holdout["review_rate_among_assessable"] = None
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="uniquely recoverable"):
        approach_release._validate_aggregate_results(aggregate)


def test_reconstruction_safety_binds_actual_partitions_margins_and_rates() -> None:
    mutations = []

    def holdout_status(value):
        value["cohorts"][0]["status_counts"]["criteria_observed"] += 1

    mutations.append(holdout_status)

    def holdout_criterion(value):
        for target in (
            value["cohorts"][0]["criterion_status_counts"],
            value["findings"]["screening_holdout"]["criterion_status_counts"],
        ):
            target["barometric_path_proxy"]["within_limit"] += 1

    mutations.append(holdout_criterion)

    def holdout_runway(value):
        value["cohorts"][0]["runway_direction_counts"]["32"] += 1

    mutations.append(holdout_runway)

    def context_base_criterion(value):
        value["findings"]["context_validation"]["base_criterion_status_counts"]["late_track_correction"]["within_limit"] += 1

    mutations.append(context_base_criterion)

    def transition_margin(value):
        value["findings"]["context_validation"]["status_transition_counts"]["criteria_observed->criteria_observed"] += 1

    mutations.append(transition_margin)

    def review_overlap(value):
        value["findings"]["context_validation"]["review_overlap"]["base_only"] += 1

    mutations.append(review_overlap)

    for mutate in mutations:
        aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
        mutate(aggregate)
        with pytest.raises(approach_release.ApproachReleaseFormatError):
            approach_release._validate_aggregate_results(aggregate)

    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["abstention_rate"] = 0.1
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="disclosed operands"):
        approach_release._validate_aggregate_results(aggregate)


def test_suppression_shape_rejects_small_cells_and_orphan_companions() -> None:
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
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["outcome_counts"]["go_around"] = 0
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="without a primary"):
        approach_release._validate_aggregate_results(aggregate)
    aggregate = json.loads(builder.PUBLIC_AGGREGATE_RESOURCE.read_text())
    aggregate["cohorts"][0]["outcome_counts"] = {
        "final_gate_observed": 578,
        "go_around": "<10",
        "incomplete": "suppressed",
    }
    with pytest.raises(approach_release.ApproachReleaseFormatError, match="no feasible"):
        approach_release._validate_aggregate_results(aggregate)


@pytest.mark.parametrize(
    ("location", "match"),
    [("top", "reference keys"), ("cohort", "reference.cohort"), ("entry", r"reference.entries\[0\]")],
)
def test_reference_is_closed_at_every_nesting_level(location: str, match: str) -> None:
    reference = builder._public_reference()
    approach_release._validate_reference(reference)
    assert "diagnostics" not in reference and "stratification" not in reference
    hostile = copy.deepcopy(reference)
    if location == "top":
        hostile["renamed_rows"] = [{"x": 40.4, "y": -3.5, "event": 100}]
    elif location == "cohort":
        hostile["cohort"]["renamed_rows"] = [{"x": 40.4, "y": -3.5, "event": 100}]
    else:
        hostile["entries"][0]["diagnostics"] = {"sample": "private"}
    with pytest.raises(approach_release.ApproachReleaseFormatError, match=match):
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


def test_projection_cli_accepts_canonical_tmp_and_rejects_other_outputs(
    tmp_path: Path,
) -> None:
    output = Path("/tmp") / f"sadar-plan002-{uuid.uuid4().hex}.json"
    command = [
        str(REPO / "backend/.venv/bin/sadar-project-public-aggregates"),
        "--holdout", str(builder.HOLDOUT_ARTIFACT),
        "--comparison", str(builder.COMPARISON_ARTIFACT),
        "--coverage", str(builder.COVERAGE_ARTIFACT),
        "--generated-at", "2026-07-18",
        "--output", str(output),
    ]
    try:
        accepted = subprocess.run(command, capture_output=True, text=True, check=False)
        assert accepted.returncode == 0, accepted.stderr
        assert output.read_bytes() == builder.PUBLIC_AGGREGATE_RESOURCE.read_bytes()
    finally:
        output.unlink(missing_ok=True)
    blocked = tmp_path / "not-allowed.json"
    rejected = subprocess.run(
        [*command[:-1], str(blocked)], capture_output=True, text=True, check=False
    )
    assert rejected.returncode != 0
    assert "tracked resource or under /tmp" in rejected.stderr
    assert not blocked.exists()


def test_catalog_hash_binding_fails_closed(tmp_path: Path) -> None:
    synthetic = _synthetic_payloads(tmp_path / "synthetic")
    catalog_path = synthetic / "demo/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["reference_sha256"] = "0" * 64
    catalog_path.write_bytes(approach_release.canonical_json_bytes(catalog))
    with pytest.raises(approach_release.ApproachReleaseIntegrityError, match="generator output"):
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


def test_validation_cli_reports_rejected_path_without_forbidden_value(tmp_path: Path) -> None:
    release = build_valid_release(tmp_path)
    command = [
        str(REPO / "backend/.venv/bin/sadar-validate-public-release"),
        "--release-dir", str(release),
    ]
    accepted = subprocess.run(command, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr
    output = json.loads(accepted.stdout)
    assert set(output) == {"release_id", "schema_version", "demo_count", "cohort_count"}
    payloads = _payloads(release)
    payloads["demo/operations.json"]["operations"][0]["callsign"] = "SECRET-CALLSIGN"
    _replace_payload_without_validation(
        release, "demo/operations.json", payloads["demo/operations.json"]
    )
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0
    assert "demo.operations[0].callsign" in rejected.stderr
    assert "SECRET-CALLSIGN" not in rejected.stderr


@pytest.mark.parametrize("status", ["sent", "acknowledged"])
def test_validation_cli_rejects_publication_notice_without_date(
    tmp_path: Path, status: str
) -> None:
    release = build_valid_release(tmp_path)
    payloads = _payloads(release)
    aggregate = payloads["research/aggregate-results.json"]
    aggregate["data_access"]["publication_notice_status"] = status
    aggregate["data_access"]["publication_notice_date"] = None
    _replace_payload_without_validation(
        release, "research/aggregate-results.json", aggregate
    )

    rejected = subprocess.run(
        [
            str(REPO / "backend/.venv/bin/sadar-validate-public-release"),
            "--release-dir", str(release),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "publication_notice_date" in rejected.stderr
    assert status not in rejected.stderr
