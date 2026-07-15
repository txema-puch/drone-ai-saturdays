from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
import torch
from sklearn.preprocessing import StandardScaler

from backend.core.lstm_ae import LSTMAutoencoder

from backend.serve import model_artifacts as artifacts
from backend.serve.release import (
    ReleaseCompatibilityError,
    ReleaseFormatError,
    ReleaseIntegrityError,
)


def fitted_scaler() -> tuple[StandardScaler, np.ndarray]:
    vectors = np.array(
        [[1.0, 10.0], [2.0, 20.0], [4.0, 40.0], [8.0, 80.0]], dtype=np.float64
    )
    return StandardScaler().fit(vectors), vectors


def test_json_scaler_round_trip_and_sklearn_parity(tmp_path: Path):
    training, vectors = fitted_scaler()
    path = tmp_path / "scaler.json"
    frozen = artifacts.export_json_scaler(training, ["x", "y"], path)
    loaded = artifacts.FrozenStandardScaler.from_json_bytes(path.read_bytes())

    artifacts.assert_scaler_parity(training, loaded, vectors)
    np.testing.assert_allclose(loaded.transform(vectors), training.transform(vectors), atol=1e-12)
    np.testing.assert_allclose(loaded.inverse_transform(loaded.transform(vectors)), vectors)
    assert frozen.features == ("x", "y")
    assert "StandardScaler" not in path.read_text()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("scale", [1.0, 0.0], "greater than zero"),
        ("scale", [1.0, float("inf")], "finite"),
        ("mean", [1.0, float("nan")], "finite"),
        ("var", [1.0, -1.0], "non-negative"),
        ("n_samples_seen", [2.0, 0.0], "greater than zero"),
    ],
)
def test_json_scaler_rejects_invalid_numbers(field: str, value: list[float], message: str):
    payload = {
        "schema_version": 1,
        "features": ["x", "y"],
        "mean": [0.0, 0.0],
        "scale": [1.0, 1.0],
        "var": [1.0, 1.0],
        "n_samples_seen": [2.0, 2.0],
    }
    payload[field] = value
    with pytest.raises(ReleaseFormatError, match=message):
        artifacts.FrozenStandardScaler.from_payload(payload)


def test_json_scaler_rejects_wrong_input_width_and_nonfinite_input():
    training, _ = fitted_scaler()
    frozen = artifacts.FrozenStandardScaler.from_payload(
        artifacts.scaler_payload(training, ["x", "y"])
    )
    with pytest.raises(ValueError, match="width mismatch"):
        frozen.transform([[1.0]])
    with pytest.raises(ValueError, match="finite"):
        frozen.transform([[1.0, np.inf]])


def test_tensor_only_state_dict_round_trip_and_exact_metadata(tmp_path: Path):
    model = torch.nn.Sequential(torch.nn.Linear(3, 2), torch.nn.Linear(2, 1))
    path = tmp_path / "state_dict.pt"
    metadata = artifacts.export_tensor_state_dict(model, path)
    state = artifacts.load_tensor_state_dict(path, metadata)

    assert list(state) == sorted(model.state_dict())
    assert artifacts.tensor_metadata(state) == metadata
    assert all(type(value) is torch.Tensor for value in state.values())


def test_tensor_only_export_bytes_are_deterministic(tmp_path: Path):
    state = {"weight": torch.ones(2, 3), "bias": torch.zeros(2)}
    first = tmp_path / "first.pt"
    second = tmp_path / "second.pt"
    artifacts.export_tensor_state_dict(state, first)
    artifacts.export_tensor_state_dict(state, second)
    assert first.read_bytes() == second.read_bytes()


def test_object_bearing_checkpoint_is_rejected(tmp_path: Path):
    path = tmp_path / "object-bearing.pt"
    torch.save({"weight": torch.ones(1), "metadata": "not a tensor"}, path)
    with pytest.raises(ReleaseFormatError, match="tensor only"):
        artifacts.load_tensor_state_dict(
            path,
            {
                "weight": {"shape": [1], "dtype": "float32"},
                "metadata": {"shape": [], "dtype": "float32"},
            },
        )

    with pytest.raises(ReleaseFormatError, match="tensor only"):
        artifacts.export_tensor_state_dict(
            {"weight": torch.ones(1), "metadata": "not a tensor"},
            tmp_path / "rejected-export.pt",
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "shape", "dtype"])
def test_tensor_contract_rejects_key_shape_and_dtype_drift(tmp_path: Path, mutation: str):
    path = tmp_path / "state_dict.pt"
    metadata = artifacts.export_tensor_state_dict(
        {"weight": torch.ones(2, 3), "bias": torch.zeros(2)}, path
    )
    expected = copy.deepcopy(metadata)
    if mutation == "missing":
        expected["other"] = {"shape": [2], "dtype": "float32"}
    elif mutation == "extra":
        expected.pop("weight")
    elif mutation == "shape":
        expected["weight"]["shape"] = [3, 2]
    else:
        expected["weight"]["dtype"] = "float64"
    with pytest.raises(ReleaseCompatibilityError, match="state dict contract mismatch"):
        artifacts.load_tensor_state_dict(path, expected)


def test_tensor_metadata_and_checkpoint_bounds_apply_before_deserialization(tmp_path: Path, monkeypatch):
    with pytest.raises(ReleaseFormatError, match="parameter or decoded-byte limits"):
        artifacts.load_tensor_state_dict(
            tmp_path / "does-not-need-to-exist.pt",
            {"weight": {"shape": [artifacts.MAX_MODEL_PARAMETERS + 1], "dtype": "float32"}},
        )

    path = tmp_path / "state.pt"
    metadata = artifacts.export_tensor_state_dict({"weight": torch.ones(1)}, path)
    monkeypatch.setattr(artifacts, "MAX_CHECKPOINT_BYTES", 1)
    with pytest.raises(ReleaseFormatError, match="checkpoint exceeds byte limit"):
        artifacts.load_tensor_state_dict(path, metadata)


def test_cohort_reference_is_sorted_full_precision_and_weak_ecdf_uses_inclusive_ties():
    original = np.array([3.0, 2.0, 1.0, 2.0])
    reference = artifacts.build_cohort_score_reference(original)
    validated, scores = artifacts.validate_cohort_score_reference(reference)

    assert validated["scores"] == [float(value).hex() for value in (1.0, 2.0, 2.0, 3.0)]
    assert artifacts.weak_ecdf_percentile(scores, 0.5) == 0.0
    assert artifacts.weak_ecdf_percentile(scores, 1.0) == 25.0
    assert artifacts.weak_ecdf_percentile(scores, 2.0) == 75.0
    assert artifacts.weak_ecdf_percentile(scores, 3.0) == 100.0
    assert artifacts.weak_ecdf_percentile(scores, 4.0) == 100.0
    np.testing.assert_array_equal(original, [3.0, 2.0, 1.0, 2.0])


def test_cohort_reference_rejects_digest_count_order_and_nonfinite_drift():
    reference = artifacts.build_cohort_score_reference([1.0, 2.0, 3.0])
    corrupt = copy.deepcopy(reference)
    corrupt["digest"] = "0" * 64
    with pytest.raises(ReleaseIntegrityError, match="digest mismatch"):
        artifacts.validate_cohort_score_reference(corrupt)

    non_hex = copy.deepcopy(reference)
    non_hex["digest"] = "G" * 64
    with pytest.raises(ReleaseFormatError, match="SHA-256 hex"):
        artifacts.validate_cohort_score_reference(non_hex)

    wrong_count = copy.deepcopy(reference)
    wrong_count["count"] = 2
    with pytest.raises(ReleaseFormatError, match="count mismatch"):
        artifacts.validate_cohort_score_reference(wrong_count)

    unsorted = copy.deepcopy(reference)
    unsorted["scores"] = list(reversed(unsorted["scores"]))
    unsorted["digest"] = artifacts._cohort_digest(unsorted)
    with pytest.raises(ReleaseFormatError, match="sorted"):
        artifacts.validate_cohort_score_reference(unsorted)

    with pytest.raises(ReleaseFormatError, match="non-finite"):
        artifacts.build_cohort_score_reference([1.0, np.nan])


def model_contract(metadata: dict, cohort: dict) -> dict:
    return artifacts.build_model_contract(
        model_class="LSTMAutoencoder",
        architecture={"n_features": 2, "hidden": 4, "latent": 2, "num_layers": 1},
        features=["x", "y"],
        scaler_features=["x", "y"],
        tensors=metadata,
        scoring_contract={
            "T": 8,
            "threshold": 0.222,
            "step_threshold": 0.5,
            "feature_names": ["x", "y"],
        },
        cohort_reference={
            key: cohort[key] for key in ("count", "digest", "formula_id", "tie_policy")
        },
        producing_versions={"python": "3.11", "torch": torch.__version__},
    )


def test_manifest_model_and_online_contracts_are_enforced(tmp_path: Path):
    state_path = tmp_path / "state.pt"
    metadata = artifacts.export_tensor_state_dict({"weight": torch.ones(2, 2)}, state_path)
    cohort = artifacts.build_cohort_score_reference([0.1, 0.2])
    contract = model_contract(metadata, cohort)
    manifest = {
        "scoring_contract": copy.deepcopy(contract["scoring_contract"]),
        "online_input_contract": {
            "input_schema_version": "input-v1",
            "derivation_contract_version": "derive-v1",
            "preprocessing_contract_version": "preprocess-v1",
            "units": copy.deepcopy(artifacts.ONLINE_INPUT_UNITS),
        },
    }

    artifacts.validate_manifest_model_contract(manifest, contract, cohort)
    artifacts.validate_online_contract(
        manifest,
        input_schema_version="input-v1",
        derivation_contract_version="derive-v1",
        preprocessing_contract_version="preprocess-v1",
    )

    drifted = copy.deepcopy(manifest)
    drifted["online_input_contract"]["derivation_contract_version"] = "derive-v2"
    with pytest.raises(ReleaseCompatibilityError, match="derivation_contract_version"):
        artifacts.validate_online_contract(
            drifted,
            input_schema_version="input-v1",
            derivation_contract_version="derive-v1",
            preprocessing_contract_version="preprocess-v1",
        )

    unit_drift = copy.deepcopy(manifest)
    unit_drift["online_input_contract"]["units"]["time"] = "milliseconds"
    with pytest.raises(ReleaseCompatibilityError, match="units mismatch"):
        artifacts.validate_online_contract(
            unit_drift,
            input_schema_version="input-v1",
            derivation_contract_version="derive-v1",
            preprocessing_contract_version="preprocess-v1",
        )

    manifest["scoring_contract"]["threshold"] = 9.0
    with pytest.raises(ReleaseCompatibilityError, match="scoring contracts differ"):
        artifacts.validate_manifest_model_contract(manifest, contract, cohort)

    invalid_digest = copy.deepcopy(contract)
    invalid_digest["cohort_reference"]["digest"] = "A" * 64
    with pytest.raises(ReleaseFormatError, match="SHA-256 hex"):
        artifacts.validate_model_contract(invalid_digest)

    invalid_scaler_order = copy.deepcopy(contract)
    invalid_scaler_order["scaler_features"] = ["y"]
    with pytest.raises(ReleaseCompatibilityError, match="ordered prefix"):
        artifacts.validate_model_contract(invalid_scaler_order)

    oversized = copy.deepcopy(contract)
    oversized["architecture"]["hidden"] = 513
    with pytest.raises(ReleaseFormatError, match="hidden exceeds limit"):
        artifacts.validate_model_contract(oversized)

    negative_threshold = copy.deepcopy(contract)
    negative_threshold["scoring_contract"]["threshold"] = -0.1
    with pytest.raises(ReleaseFormatError, match="non-negative"):
        artifacts.validate_model_contract(negative_threshold)


def test_full_artifact_loader_rejects_object_checkpoint_and_contract_drift(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    training, _ = fitted_scaler()
    artifacts.export_json_scaler(training, ["x", "y"], model_dir / "scaler.json")
    model = LSTMAutoencoder(n_features=2, hidden=4, latent=2, num_layers=1)
    metadata = artifacts.export_tensor_state_dict(model, model_dir / "state_dict.pt")
    cohort = artifacts.write_cohort_score_reference([0.1, 0.2], model_dir / "cohort-score-reference.json")
    contract = model_contract(metadata, cohort)
    artifacts.write_model_contract(contract, model_dir / "model-contract.json")
    manifest = {
        "scoring_contract": copy.deepcopy(contract["scoring_contract"]),
        "online_input_contract": {
            "input_schema_version": "input-v1",
            "derivation_contract_version": "derive-v1",
            "preprocessing_contract_version": "preprocess-v1",
            "units": copy.deepcopy(artifacts.ONLINE_INPUT_UNITS),
        },
    }

    loaded = artifacts.load_model_artifacts(
        tmp_path,
        manifest,
        input_schema_version="input-v1",
        derivation_contract_version="derive-v1",
        preprocessing_contract_version="preprocess-v1",
    )
    assert loaded.cohort_reference == (0.1, 0.2)
    assert loaded.scaler.features == ("x", "y")
    assert isinstance(loaded.model, LSTMAutoencoder)
    assert not loaded.model.training

    torch.save({**model.state_dict(), "object": {"bad": True}}, model_dir / "state_dict.pt")
    with pytest.raises(ReleaseFormatError, match="tensor only"):
        artifacts.load_model_artifacts(
            tmp_path,
            manifest,
            input_schema_version="input-v1",
            derivation_contract_version="derive-v1",
            preprocessing_contract_version="preprocess-v1",
        )


def test_full_artifact_loader_rejects_self_consistent_but_wrong_state_dict(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    training, _ = fitted_scaler()
    artifacts.export_json_scaler(training, ["x", "y"], model_dir / "scaler.json")
    metadata = artifacts.export_tensor_state_dict(
        {"weight": torch.ones(2, 2)}, model_dir / "state_dict.pt"
    )
    cohort = artifacts.write_cohort_score_reference(
        [0.1, 0.2], model_dir / "cohort-score-reference.json"
    )
    contract = model_contract(metadata, cohort)
    artifacts.write_model_contract(contract, model_dir / "model-contract.json")
    manifest = {
        "scoring_contract": copy.deepcopy(contract["scoring_contract"]),
        "online_input_contract": {
            "input_schema_version": "input-v1",
            "derivation_contract_version": "derive-v1",
            "preprocessing_contract_version": "preprocess-v1",
            "units": copy.deepcopy(artifacts.ONLINE_INPUT_UNITS),
        },
    }
    with pytest.raises(ReleaseCompatibilityError, match="strictly"):
        artifacts.load_model_artifacts(
            tmp_path,
            manifest,
            input_schema_version="input-v1",
            derivation_contract_version="derive-v1",
            preprocessing_contract_version="preprocess-v1",
        )


def test_full_artifact_loader_bounds_json_before_parsing(tmp_path: Path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model-contract.json").write_text('{"padding":"' + "x" * 100 + '"}')
    monkeypatch.setattr(artifacts, "MAX_MODEL_JSON_BYTES", 32)
    with pytest.raises(ReleaseFormatError, match="exceeds byte limit"):
        artifacts.load_model_artifacts(
            tmp_path,
            {"scoring_contract": {}, "online_input_contract": {}},
            input_schema_version="input-v1",
            derivation_contract_version="derive-v1",
            preprocessing_contract_version="preprocess-v1",
        )
