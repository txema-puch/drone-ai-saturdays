"""Project reviewed aggregates and assemble schema-v4 public releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sadar.approach.assessment import (
    ASSESSMENT_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    RECONSTRUCTION_POLICY,
    RECONSTRUCTION_POLICY_VERSION,
)
from sadar.approach.contextual import CONTEXT_ENGINE_VERSION
from sadar.approach.geometry import GEOMETRY_RESOURCE
from sadar.approach.reference import REFERENCE_RESOURCE, validate_reference
from sadar.releases.approach import (
    ApproachReleaseError,
    ApproachReleaseFormatError,
    ApproachReleaseIntegrityError,
    FILE_LIMITS,
    canonical_json_bytes,
    read_canonical_json,
    validate_public_release_directory,
    write_release,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
HOLDOUT_ARTIFACT = REPO_ROOT / "docs/research/approach-screening/lifecycle/artifacts/2026-holdout-burn.json"
COMPARISON_ARTIFACT = REPO_ROOT / "docs/research/approach-context/lifecycle/artifacts/val-comparison.json"
COVERAGE_ARTIFACT = REPO_ROOT / "docs/research/approach-context/lifecycle/artifacts/val-coverage.json"
PUBLIC_AGGREGATE_RESOURCE = Path(__file__).resolve().parents[1] / "approach/resources/lemd_public_aggregate_results_v1.json"
PRODUCTION_GENERATED_AT = "2026-07-18"
MAX_CASE_OBSERVATIONS = 600


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid reviewed aggregate artifact: {path.name}") from exc


def _exact(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{field} schema mismatch")
    return value


def _assert_reviewed_paths(holdout_path: Path, comparison_path: Path, coverage_path: Path) -> None:
    observed = tuple(path.resolve() for path in (holdout_path, comparison_path, coverage_path))
    expected = tuple(path.resolve() for path in (HOLDOUT_ARTIFACT, COMPARISON_ARTIFACT, COVERAGE_ARTIFACT))
    if observed != expected:
        raise ValueError("projection inputs must be the three exact tracked reviewed artifacts")


def _suppress_count_map(raw: dict[str, int]) -> dict[str, int | str]:
    if not isinstance(raw, dict) or not raw or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in raw.values()):
        raise ValueError("reviewed count map must contain non-negative integers")
    projected: dict[str, int | str] = {
        key: "<10" if 1 <= value <= 9 else value for key, value in raw.items()
    }
    if "<10" in projected.values():
        candidates = [(value, key) for key, value in projected.items() if isinstance(value, int) and value > 0]
        if not candidates:
            raise ValueError("small-cell map has no companion cell to suppress")
        largest = max(value for value, _ in candidates)
        key = min(key for value, key in candidates if value == largest)
        projected[key] = "suppressed"
    return projected


def _suppress_criterion_map(raw: dict[str, dict[str, int]]) -> dict[str, dict[str, int | str]]:
    return {criterion: _suppress_count_map(counts) for criterion, counts in raw.items()}


def _published_rate(numerator: int | str, denominator: int | None) -> float | None:
    if not isinstance(numerator, int) or isinstance(numerator, bool) or not isinstance(denominator, int) or isinstance(denominator, bool) or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _deduplicate_limits(*groups: list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item not in result:
                result.append(item)
    return result


def project_reviewed_aggregate_results(
    *,
    holdout_path: Path,
    comparison_path: Path,
    coverage_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    """Project only the three reviewed aggregate artifacts into the public contract."""
    holdout_path, comparison_path, coverage_path = map(Path, (holdout_path, comparison_path, coverage_path))
    _assert_reviewed_paths(holdout_path, comparison_path, coverage_path)
    if generated_at != PRODUCTION_GENERATED_AT:
        raise ValueError("generated_at must equal the reviewed 2026-07-18 decision")
    holdout = _exact(_read_json(holdout_path), {
        "holdout", "interpretation_limits", "policy", "reference_sha256", "release_id",
        "release_source_sha256", "schema_version", "source_commit",
    }, "holdout")
    comparison = _exact(_read_json(comparison_path), {
        "attempts", "base_criterion_status_counts", "base_reference_sha256",
        "base_review_rate_among_assessable", "base_status_counts", "cohort",
        "context_coverage", "context_criterion_status_counts", "context_reference_sha256",
        "context_review_rate_among_assessable", "context_status_counts", "decision",
        "interpretation_limits", "review_overlap", "schema_version", "source_commit",
        "source_sha256", "status_transition_counts",
    }, "comparison")
    coverage = _exact(_read_json(coverage_path), {
        "aircraft_metadata_sha256", "attempts", "availability_gates", "cohort", "coverage",
        "interpretation_limits", "maximum_weather_age_s", "operations", "reference_sha256",
        "schema_version", "source_sha256", "status_counts", "top_typecodes",
        "weather_missing_reason_counts", "weather_source_sha256",
    }, "coverage")
    if holdout["schema_version"] != "approach_holdout_burn_v1" or holdout["holdout"].get("schema_version") != "approach_dataset_audit_v1":
        raise ValueError("holdout schema mismatch")
    if comparison["schema_version"] != "approach_context_comparison_v1" or coverage["schema_version"] != "approach_context_audit_v1":
        raise ValueError("context artifact schema mismatch")
    if comparison["cohort"] != "val" or coverage["cohort"] != "val" or comparison["source_sha256"] != coverage["source_sha256"] or comparison["attempts"] != coverage["attempts"]:
        raise ValueError("context artifact provenance mismatch")
    if comparison["base_reference_sha256"] != coverage["reference_sha256"]:
        raise ValueError("context base reference provenance mismatch")

    burn = holdout["holdout"]
    holdout_status = _suppress_count_map(burn["status_counts"])
    context_status = _suppress_count_map(comparison["context_status_counts"])
    base_status = _suppress_count_map(comparison["base_status_counts"])
    context_assessable = comparison["attempts"] - comparison["context_status_counts"]["not_assessable"]
    holdout_cohort = {
        "cohort_id": "2026_holdout",
        "period": "March 2026",
        "role": "single_burn_holdout",
        "source_sha256": burn["input_sha256"],
        "base_reference_sha256": burn["reference_sha256"],
        "context_reference_sha256": None,
        "rows": burn["rows"],
        "operations": burn["operations"],
        "operations_with_attempts": burn["operations_with_attempts"],
        "attempts": burn["attempts"],
        "assessable_attempts": burn["assessable_attempts"],
        "status_counts": holdout_status,
        "outcome_counts": _suppress_count_map(burn["outcome_counts"]),
        "criterion_status_counts": _suppress_criterion_map(burn["criterion_status_counts"]),
        "runway_direction_counts": _suppress_count_map(burn["runway_direction_counts"]),
        "abstention_rate": _published_rate(holdout_status["not_assessable"], burn["attempts"]),
        "review_rate_among_assessable": _published_rate(holdout_status["review_required"], burn["assessable_attempts"]),
        "context_coverage": None,
        "decision": "descriptive_holdout_burn_no_accuracy_claim",
        "interpretation_limits": holdout["interpretation_limits"],
    }
    context_cohort = {
        "cohort_id": "2019_context_validation",
        "period": "2019 validation cohort",
        "role": "val",
        "source_sha256": comparison["source_sha256"],
        "base_reference_sha256": comparison["base_reference_sha256"],
        "context_reference_sha256": comparison["context_reference_sha256"],
        "rows": None,
        "operations": coverage["operations"],
        "operations_with_attempts": None,
        "attempts": comparison["attempts"],
        "assessable_attempts": context_assessable,
        "status_counts": context_status,
        "outcome_counts": None,
        "criterion_status_counts": _suppress_criterion_map(comparison["context_criterion_status_counts"]),
        "runway_direction_counts": None,
        "abstention_rate": _published_rate(context_status["not_assessable"], comparison["attempts"]),
        "review_rate_among_assessable": _published_rate(context_status["review_required"], context_assessable),
        "context_coverage": coverage["coverage"],
        "decision": comparison["decision"],
        "interpretation_limits": _deduplicate_limits(comparison["interpretation_limits"], coverage["interpretation_limits"]),
    }
    return {
        "schema_version": "approach_aggregate_results_v1",
        "basis": "real_opensky_research_data",
        "generated_at": generated_at,
        "cohorts": [holdout_cohort, context_cohort],
        "findings": {
            "screening_holdout": {
                "cohort_id": "2026_holdout",
                "policy": holdout["policy"],
                "criterion_status_counts": _suppress_criterion_map(burn["criterion_status_counts"]),
                "reason_counts": _suppress_count_map(burn["reason_counts"]),
                "interpretation_limits": holdout["interpretation_limits"],
            },
            "context_validation": {
                "cohort_id": "2019_context_validation",
                "base_status_counts": base_status,
                "context_status_counts": context_status,
                "base_criterion_status_counts": _suppress_criterion_map(comparison["base_criterion_status_counts"]),
                "context_criterion_status_counts": _suppress_criterion_map(comparison["context_criterion_status_counts"]),
                "review_overlap": _suppress_count_map(comparison["review_overlap"]),
                "status_transition_counts": _suppress_count_map(comparison["status_transition_counts"]),
                "base_review_rate_among_assessable": _published_rate(base_status["review_required"], comparison["attempts"] - comparison["base_status_counts"]["not_assessable"]),
                "context_review_rate_among_assessable": _published_rate(context_status["review_required"], context_assessable),
                "context_coverage": comparison["context_coverage"],
                "decision": comparison["decision"],
                "interpretation_limits": comparison["interpretation_limits"],
            },
        },
        "qualification": "not_qualified_no_independent_labels_or_fresh_holdout",
        "allowed_role": "research_and_evidence_labeling_demonstrator",
        "blocked_uses": [
            "operational_monitoring", "emergency_detection", "stabilized_approach_certification",
            "atc_decision_support", "safety_performance_claims",
        ],
        "limitations": _deduplicate_limits(
            holdout["interpretation_limits"], comparison["interpretation_limits"], coverage["interpretation_limits"]
        ),
        "data_access": {
            "provider": "OpenSky Network",
            "terms_url": "https://opensky-network.org/about/terms-of-use",
            "access_url": "https://opensky-network.org/data/data-access",
            "citation": "Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic, and Matthias Wilhelm. Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research. IPSN 2014.",
            "publication_notice_status": "pending",
            "publication_notice_date": None,
        },
    }


def _public_reference(reference_path: Path | None = None) -> dict[str, Any]:
    source = Path(reference_path) if reference_path is not None else REFERENCE_RESOURCE
    private = (
        read_canonical_json(
            source, limit=FILE_LIMITS["reference/approach-reference.json"]
        )
        if reference_path is not None
        else _read_json(source)
    )
    if not isinstance(private, dict):
        raise ApproachReleaseFormatError("approach reference must be an object")
    try:
        validate_reference(private)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApproachReleaseFormatError(f"invalid approach reference: {exc}") from exc
    public_keys = {
        "schema_version", "fit_fold", "source_reference_sha256", "cohort",
        "distance_bins_m", "quantiles", "minimum_samples", "minimum_attempts",
        "accepted_attempts", "entries", "artifact_sha256",
    }
    if set(private) == public_keys:
        return private
    projection = {
        "schema_version": private["schema_version"],
        "fit_fold": private["fit_fold"],
        "source_reference_sha256": private["artifact_sha256"],
        "cohort": private["cohort"],
        "distance_bins_m": private["distance_bins_m"],
        "quantiles": private["quantiles"],
        "minimum_samples": private["minimum_samples"],
        "minimum_attempts": private["minimum_attempts"],
        "accepted_attempts": private["accepted_attempts"],
        "entries": private["entries"],
    }
    projection["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    try:
        validate_reference(projection)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApproachReleaseFormatError(f"invalid public approach reference: {exc}") from exc
    return projection


def methodology_payloads(reference_path: Path | None = None) -> dict[str, Any]:
    config = {
        "schema_version": "approach_config_v1",
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": CONTEXT_ENGINE_VERSION,
        "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
        "reconstruction_policy": RECONSTRUCTION_POLICY,
        "config": asdict(DEFAULT_CONFIG),
    }
    return {
        "config/approach-config.json": config,
        "config/lemd-geometry.json": _read_json(GEOMETRY_RESOURCE),
        "reference/approach-reference.json": _public_reference(reference_path),
    }


def _verified_synthetic_payloads(
    synthetic_payload_dir: Path,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    """Regenerate from the untrusted catalog seed and require exact canonical bytes."""
    from sadar.demo.catalog import generate_demo_payloads

    demo_root = synthetic_payload_dir / "demo"
    catalog = read_canonical_json(
        demo_root / "catalog.json", limit=FILE_LIMITS["demo/catalog.json"]
    )
    if not isinstance(catalog, dict):
        raise ApproachReleaseFormatError("synthetic catalog must be an object")
    try:
        expected = generate_demo_payloads(
            seed=catalog.get("seed"), methodology_payloads=methodology
        )
    except (TypeError, ValueError) as exc:
        raise ApproachReleaseFormatError(
            f"synthetic payload regeneration failed: {exc}"
        ) from exc
    for name, payload in expected.items():
        path = demo_root / name
        observed_payload = read_canonical_json(
            path, limit=FILE_LIMITS[f"demo/{name}"]
        )
        observed = canonical_json_bytes(observed_payload)
        canonical = canonical_json_bytes(payload)
        if observed != canonical:
            raise ApproachReleaseIntegrityError(
                f"synthetic payload does not match generator output: demo/{name}"
            )
    return expected


def build_public_release(
    *,
    aggregate_results_path: Path,
    synthetic_payload_dir: Path,
    output: Path,
    reference_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble a public release exclusively from aggregate and synthetic JSON."""
    aggregate_results_path = Path(aggregate_results_path)
    synthetic_payload_dir = Path(synthetic_payload_dir)
    output = Path(output)
    aggregate = _read_json(aggregate_results_path)
    methodology = methodology_payloads(reference_path=reference_path)
    demo_paths = {
        "demo/catalog.json": "catalog.json",
        "demo/attempts.json": "attempts.json",
        "demo/cases.json": "cases.json",
        "demo/operations.json": "operations.json",
    }
    verified_demo = _verified_synthetic_payloads(synthetic_payload_dir, methodology)
    payloads: dict[str, Any] = {
        destination: verified_demo[source] for destination, source in demo_paths.items()
    }
    payloads.update(methodology)
    payloads["research/aggregate-results.json"] = aggregate
    catalog = payloads["demo/catalog.json"]
    aggregate_digest = hashlib.sha256(canonical_json_bytes(aggregate)).hexdigest()
    config_digest = hashlib.sha256(canonical_json_bytes(methodology["config/approach-config.json"])).hexdigest()
    geometry_digest = hashlib.sha256(canonical_json_bytes(methodology["config/lemd-geometry.json"])).hexdigest()
    reference_digest = hashlib.sha256(canonical_json_bytes(methodology["reference/approach-reference.json"])).hexdigest()
    if catalog.get("approach_config_sha256") != config_digest or catalog.get("geometry_source_sha256") != geometry_digest or catalog.get("reference_sha256") != reference_digest:
        raise ApproachReleaseFormatError("synthetic catalog does not bind the bundled methodology")
    source = {
        "aggregate_artifact_sha256": aggregate_digest,
        "synthetic_generator": catalog.get("generator_version"),
        "synthetic_seed": catalog.get("seed"),
    }
    contracts = {
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "engine_version": CONTEXT_ENGINE_VERSION,
        "reconstruction_policy_version": RECONSTRUCTION_POLICY_VERSION,
        "demo_schema_version": catalog.get("schema_version"),
        "case_observation_limit": MAX_CASE_OBSERVATIONS,
        "approach_config_sha256": config_digest,
        "geometry_source_sha256": geometry_digest,
        "reference_sha256": reference_digest,
        "aggregate_results_sha256": aggregate_digest,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    candidate = temporary_root / "release"
    try:
        manifest = write_release(candidate, payloads, source=source, contracts=contracts)
        if output.exists():
            existing = validate_public_release_directory(output)
            if existing != manifest:
                raise ApproachReleaseError("output already contains a different release")
            return existing
        os.replace(candidate, output)
        return validate_public_release_directory(output)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a schema-v4 public evidence release.")
    parser.add_argument("--aggregate-results", type=Path, required=True)
    parser.add_argument("--synthetic-payload-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_public_release(
        aggregate_results_path=args.aggregate_results,
        synthetic_payload_dir=args.synthetic_payload_dir,
        output=args.output,
        reference_path=args.reference,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def projection_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project the three reviewed aggregate artifacts.")
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--generated-at", choices=[PRODUCTION_GENERATED_AT], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    temporary_root = Path("/tmp").resolve()
    if output != PUBLIC_AGGREGATE_RESOURCE.resolve() and output != temporary_root and temporary_root not in output.parents:
        print("aggregate projection output must be the tracked resource or under /tmp", file=sys.stderr)
        return 1
    try:
        projected = project_reviewed_aggregate_results(
            holdout_path=args.holdout,
            comparison_path=args.comparison,
            coverage_path=args.coverage,
            generated_at=args.generated_at,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(projected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
