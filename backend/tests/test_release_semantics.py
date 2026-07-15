from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import torch
from sklearn.preprocessing import StandardScaler

from backend.core.lstm_ae import LSTMAutoencoder
from backend.core.preprocessing import AE_FEATURES, SCALER_FEATURES
from backend.serve import model_artifacts, release, release_semantics
from backend.serve.operations import case_identity, operation_ref
from backend.serve.release import ReleaseCompatibilityError, ReleaseIntegrityError


ONLINE_CONTRACT = {
    "input_schema_version": "opensky_raw_v1",
    "derivation_contract_version": "derivations_v1",
    "preprocessing_contract_version": "preprocessing_v1",
    "units": copy.deepcopy(model_artifacts.ONLINE_INPUT_UNITS),
}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True))


def build_semantic_release(
    base: Path,
) -> tuple[dict, StandardScaler, list[list[float]], dict[str, float]]:
    case_id_a, case_ref_a = case_identity("flight#1")
    case_id_b, case_ref_b = case_identity("flight#2")
    row_a = {
        "case_id": case_id_a,
        "case_ref": case_ref_a,
        "segment_id": "flight#1",
        "operation_ref": operation_ref("flight#1"),
        "has_case": True,
        "score": 0.2,
        "pct": 50.0,
        "band": "upper-normal",
        "anomalous": False,
        "label": "normal",
        "assessment_state": "reviewable",
    }
    row_b = {
        "case_id": case_id_b,
        "case_ref": case_ref_b,
        "segment_id": "flight#2",
        "operation_ref": operation_ref("flight#2"),
        "has_case": False,
        "score": 0.8,
        "pct": 100.0,
        "band": "highly anomalous",
        "anomalous": True,
        "label": "normal",
        "assessment_state": "data_quality_conflict",
    }
    queue = [row_b, row_a]
    case_a = {key: value for key, value in row_a.items() if key != "has_case"}
    case_a.update({"report": None, "path": []})
    cases = {case_id_a: case_a}
    operation = {
        "operation_ref": operation_ref("flight#1"),
        "segment_count": 2,
        "worst_score": row_b["score"],
        "worst_pct": row_b["pct"],
        "worst_band": row_b["band"],
        "worst_case_id": row_b["case_id"],
        "worst_case_ref": row_b["case_ref"],
        "worst_segment_id": row_b["segment_id"],
        "behavioral_worst_score": row_a["score"],
        "behavioral_worst_pct": row_a["pct"],
        "behavioral_worst_band": row_a["band"],
        "behavioral_worst_case_id": row_a["case_id"],
        "behavioral_worst_case_ref": row_a["case_ref"],
        "segments": [row_a, row_b],
    }
    _write_json(base / "queue.json", queue)
    _write_json(base / "cases.json", cases)
    _write_json(base / "operations.json", [operation])
    _write_json(
        base / "metrics.json",
        {
            "selected_model": "AE",
            "results": [
                {
                    "model": "AE",
                    "real_roc_auc": 0.667,
                    "real_pr_auc": 0.088,
                    "synthetic_mean_roc_auc": 0.731,
                    "synthetic_per_type": {"speed_spike": 0.58},
                }
            ],
            "notes": {"source": "synthetic fixture"},
        },
    )

    raw = pd.DataFrame(
        {
            "segment_id": ["flight#1"],
            "time": [1],
            "lat": [40.0],
            "lon": [-3.0],
            "baroaltitude": [100.0],
            "velocity": [20.0],
            "vertrate": [0.0],
            "heading": [180.0],
            "onground": [False],
        }
    )
    raw.to_parquet(base / "cases_raw.parquet", index=False)

    model_dir = base / "model"
    model_dir.mkdir()
    vectors = [
        [1.0, 10.0, 100.0, 20.0, -1.0, 500.0],
        [2.0, 20.0, 200.0, 30.0, 0.0, 600.0],
        [4.0, 40.0, 400.0, 40.0, 1.0, 700.0],
    ]
    training_scaler = StandardScaler().fit(vectors)
    model_artifacts.export_json_scaler(
        training_scaler, SCALER_FEATURES, model_dir / "scaler.json"
    )
    model = LSTMAutoencoder(n_features=len(AE_FEATURES), hidden=4, latent=2, num_layers=1)
    metadata = model_artifacts.export_tensor_state_dict(model, model_dir / "state_dict.pt")
    cohort = model_artifacts.write_cohort_score_reference(
        [0.2, 0.8], model_dir / "cohort-score-reference.json"
    )
    scoring_contract = {
        "T": 8,
        "threshold": 0.222,
        "step_threshold": 0.5,
        "feature_names": list(AE_FEATURES),
    }
    contract = model_artifacts.build_model_contract(
        model_class="LSTMAutoencoder",
        architecture={
            "n_features": len(AE_FEATURES),
            "hidden": 4,
            "latent": 2,
            "num_layers": 1,
        },
        features=AE_FEATURES,
        scaler_features=SCALER_FEATURES,
        tensors=metadata,
        scoring_contract=scoring_contract,
        cohort_reference={
            key: cohort[key] for key in ("count", "digest", "formula_id", "tie_policy")
        },
        producing_versions={"python": "3.11", "torch": torch.__version__},
    )
    model_artifacts.write_model_contract(contract, model_dir / "model-contract.json")

    payload = {
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "source": {"commit": "abc123"},
        "scoring_contract": scoring_contract,
        "online_input_contract": copy.deepcopy(ONLINE_CONTRACT),
    }
    manifest = release.write_release_manifest(base, payload)
    return manifest, training_scaler, vectors, {case_id_a: 0.2, case_id_b: 0.8}


def validate_semantics(
    base: Path,
    manifest: dict,
    training_scaler: StandardScaler,
    vectors: list[list[float]],
    scores: dict[str, float],
    *,
    expected_online_contract: dict = ONLINE_CONTRACT,
    report_validator=lambda case: True,
):
    return release_semantics.validate_release_semantics(
        base,
        manifest,
        expected_online_contract=expected_online_contract,
        training_scaler=training_scaler,
        scaler_parity_vectors=vectors,
        recomputed_scores_by_case_id=scores,
        report_validator=report_validator,
    )


def test_semantic_validator_accepts_consistent_release_and_parity_inputs(tmp_path: Path):
    manifest, training_scaler, vectors, scores = build_semantic_release(tmp_path)
    release.validate_release_directory(tmp_path)

    loaded = validate_semantics(
        tmp_path, manifest, training_scaler, vectors, scores
    )
    assert loaded.cohort_reference == (0.2, 0.8)


def test_semantic_validator_rejects_case_subset_and_operation_maximum_drift(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    cases_path = tmp_path / "cases.json"
    cases = json.loads(cases_path.read_text())
    cases.clear()
    _write_json(cases_path, cases)
    with pytest.raises(ReleaseIntegrityError, match="curated case subset mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)


def test_semantic_validator_recomputes_stable_case_and_operation_identities(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    queue_path = tmp_path / "queue.json"
    queue = json.loads(queue_path.read_text())
    queue[0]["case_id"] = "c_position_0"
    _write_json(queue_path, queue)
    with pytest.raises(ReleaseIntegrityError, match="queue identity mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)

    # Restore, then prove arbitrary operation grouping is rejected independently.
    for child in tmp_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    queue = json.loads((tmp_path / "queue.json").read_text())
    queue[0]["operation_ref"] = "OP-FAKE"
    _write_json(tmp_path / "queue.json", queue)
    with pytest.raises(ReleaseIntegrityError, match="operation identity mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)

    # Restore the release and mutate only the operation summary.
    for child in tmp_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    operations_path = tmp_path / "operations.json"
    operations = json.loads(operations_path.read_text())
    operations[0]["worst_case_id"] = next(
        case_id for case_id, score in scores.items() if score == 0.2
    )
    _write_json(operations_path, operations)
    with pytest.raises(ReleaseIntegrityError, match="worst_case_id mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)


def test_semantic_validator_rejects_parquet_membership_and_online_version_drift(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    raw_path = tmp_path / "cases_raw.parquet"
    raw = pd.read_parquet(raw_path)
    extra = raw.copy()
    extra["segment_id"] = "unknown#1"
    pd.concat([raw, extra]).to_parquet(raw_path, index=False)
    with pytest.raises(ReleaseIntegrityError, match="segment set mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)

    # A code-generation contract mismatch fails even if all shipped artifacts agree.
    for child in tmp_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    expected = {**ONLINE_CONTRACT, "preprocessing_contract_version": "preprocessing_v2"}
    with pytest.raises(ReleaseCompatibilityError, match="preprocessing_contract_version"):
        validate_semantics(
            tmp_path,
            manifest,
            scaler,
            vectors,
            scores,
            expected_online_contract=expected,
        )


def test_semantic_validator_rejects_recomputed_queue_score_drift(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    drifted_scores = dict(scores)
    drifted_scores[next(iter(drifted_scores))] = 0.9
    with pytest.raises(ReleaseIntegrityError, match="queue model evidence mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, drifted_scores)


def test_semantic_validator_bounds_json_and_parquet_before_decoding(tmp_path: Path, monkeypatch):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    monkeypatch.setitem(release_semantics.JSON_ARTIFACT_LIMITS, "queue.json", 1)
    with pytest.raises(release.ReleaseFormatError, match="exceeds byte limit"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)

    monkeypatch.setitem(release_semantics.JSON_ARTIFACT_LIMITS, "queue.json", 8 * 1024 * 1024)
    monkeypatch.setattr(release_semantics, "MAX_CASE_RAW_ROWS", 0)
    with pytest.raises(release.ReleaseFormatError, match="cases_raw.parquet exceeds row limit"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)


def test_non_null_report_requires_positive_deterministic_binding_validation(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    cases_path = tmp_path / "cases.json"
    cases = json.loads(cases_path.read_text())
    next(iter(cases.values()))["report"] = ""
    _write_json(cases_path, cases)
    with pytest.raises(ReleaseIntegrityError, match="report failed deterministic binding"):
        validate_semantics(
            tmp_path,
            manifest,
            scaler,
            vectors,
            scores,
            report_validator=lambda case: False,
        )


def test_metrics_and_executable_feature_contracts_are_mandatory(tmp_path: Path):
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    metrics_path = tmp_path / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    metrics["selected_model"] = "IF"
    _write_json(metrics_path, metrics)
    with pytest.raises(ReleaseCompatibilityError, match="selected_model mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)

    for child in tmp_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    manifest, scaler, vectors, scores = build_semantic_release(tmp_path)
    contract_path = tmp_path / "model/model-contract.json"
    contract = json.loads(contract_path.read_text())
    contract["features"][-1] = "ongrounX"
    contract["scoring_contract"]["feature_names"][-1] = "ongrounX"
    manifest["scoring_contract"]["feature_names"][-1] = "ongrounX"
    _write_json(contract_path, contract)
    with pytest.raises(ReleaseCompatibilityError, match="model feature contract mismatch"):
        validate_semantics(tmp_path, manifest, scaler, vectors, scores)
