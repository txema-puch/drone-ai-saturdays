"""Safe, frozen serve-time model artifact contracts.

Training may consume trusted local pickle-backed artifacts.  A release never does: it
contains a tensor-only state dict, a strict JSON scaler, a JSON architecture/contract,
and a sorted full-precision cohort-score reference.
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import io
import math
import os
import re
import uuid
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from backend.serve.release import (
    ReleaseCompatibilityError,
    ReleaseFormatError,
    ReleaseIntegrityError,
    canonical_json_bytes,
    parse_json_bytes,
    read_json_file,
)


MODEL_ARTIFACT_SCHEMA_VERSION = 1
SCALER_SCHEMA_VERSION = 1
COHORT_REFERENCE_SCHEMA_VERSION = 1
COHORT_FORMULA_ID = "weak_ecdf_le_v1"
COHORT_TIE_POLICY = "inclusive"
COHORT_ENCODING = "ieee754_float64_hex"
ONLINE_INPUT_UNITS = {
    "time": "unix_seconds",
    "lat": "degrees_wgs84",
    "lon": "degrees_wgs84",
    "baroaltitude": "metres",
    "velocity": "metres_per_second",
    "heading": "degrees_clockwise_from_true_north",
    "vertrate": "metres_per_second",
    "onground": "boolean",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_MODEL_JSON_BYTES = 4 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAX_MODEL_PARAMETERS = 25_000_000
MAX_STATE_DICT_BYTES = 200 * 1024 * 1024
MAX_SEQUENCE_LENGTH = 4096
_DTYPE_BYTES = {
    "bool": 1,
    "uint8": 1,
    "int8": 1,
    "int16": 2,
    "float16": 2,
    "bfloat16": 2,
    "int32": 4,
    "float32": 4,
    "int64": 8,
    "float64": 8,
}
_LSTM_ARCHITECTURE_LIMITS = {
    "n_features": 64,
    "hidden": 512,
    "latent": 512,
    "num_layers": 4,
}


def _is_plain_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_float(value: Any, *, field: str) -> float:
    if not _is_plain_number(value):
        raise ReleaseFormatError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ReleaseFormatError(f"{field} must be finite")
    return result


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReleaseFormatError(f"{field} must be a positive integer")
    return value


def _feature_names(value: Any, *, field: str = "features") -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ReleaseFormatError(f"{field} must be a non-empty array")
    if any(not isinstance(name, str) or not name for name in value):
        raise ReleaseFormatError(f"{field} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ReleaseFormatError(f"{field} contains duplicate names")
    return tuple(value)


def _numeric_vector(value: Any, *, field: str, width: int) -> np.ndarray:
    if not isinstance(value, list) or len(value) != width:
        raise ReleaseFormatError(f"{field} must contain exactly {width} values")
    return np.asarray([_finite_float(item, field=f"{field}[{index}]") for index, item in enumerate(value)])


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class FrozenStandardScaler:
    """The inference-only subset of sklearn's StandardScaler contract."""

    features: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    var: np.ndarray
    n_samples_seen: np.ndarray

    @classmethod
    def from_payload(cls, payload: Any) -> "FrozenStandardScaler":
        if not isinstance(payload, dict):
            raise ReleaseFormatError("scaler artifact must be a JSON object")
        expected_keys = {
            "schema_version", "features", "mean", "scale", "var", "n_samples_seen"
        }
        if set(payload) != expected_keys:
            raise ReleaseFormatError(
                f"scaler artifact keys mismatch: missing={sorted(expected_keys - set(payload))}, "
                f"extra={sorted(set(payload) - expected_keys)}"
            )
        if payload["schema_version"] != SCALER_SCHEMA_VERSION:
            raise ReleaseCompatibilityError(
                f"unsupported scaler schema: expected {SCALER_SCHEMA_VERSION}, "
                f"observed {payload['schema_version']}"
            )
        features = _feature_names(payload["features"], field="scaler.features")
        width = len(features)
        mean = _numeric_vector(payload["mean"], field="scaler.mean", width=width)
        scale = _numeric_vector(payload["scale"], field="scaler.scale", width=width)
        var = _numeric_vector(payload["var"], field="scaler.var", width=width)
        samples = _numeric_vector(
            payload["n_samples_seen"], field="scaler.n_samples_seen", width=width
        )
        if np.any(scale <= 0):
            raise ReleaseFormatError("scaler.scale values must be greater than zero")
        if np.any(var < 0):
            raise ReleaseFormatError("scaler.var values must be non-negative")
        if np.any(samples <= 0):
            raise ReleaseFormatError("scaler.n_samples_seen values must be greater than zero")
        for array in (mean, scale, var, samples):
            array.setflags(write=False)
        return cls(features, mean, scale, var, samples)

    @classmethod
    def from_json_bytes(cls, data: bytes) -> "FrozenStandardScaler":
        return cls.from_payload(parse_json_bytes(data, source="scaler.json"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCALER_SCHEMA_VERSION,
            "features": list(self.features),
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "var": self.var.tolist(),
            "n_samples_seen": self.n_samples_seen.tolist(),
        }

    def _array(self, values: Any) -> np.ndarray:
        try:
            array = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("scaler input must be numeric") from exc
        if array.ndim == 0 or array.shape[-1] != len(self.features):
            observed = 0 if array.ndim == 0 else array.shape[-1]
            raise ValueError(
                f"scaler feature width mismatch: expected {len(self.features)}, observed {observed}"
            )
        if not np.isfinite(array).all():
            raise ValueError("scaler input must contain only finite values")
        return array

    def transform(self, values: Any) -> np.ndarray:
        array = self._array(values)
        return (array - self.mean) / self.scale

    def inverse_transform(self, values: Any) -> np.ndarray:
        array = self._array(values)
        return array * self.scale + self.mean


def scaler_payload(training_scaler: Any, features: Sequence[str]) -> dict[str, Any]:
    """Export fitted sklearn-compatible attributes without serializing its object."""
    names = _feature_names(list(features), field="scaler.features")
    width = len(names)
    attributes: dict[str, np.ndarray] = {}
    for public_name, attribute_name in (("mean", "mean_"), ("scale", "scale_"), ("var", "var_")):
        if not hasattr(training_scaler, attribute_name):
            raise ReleaseFormatError(f"training scaler is missing fitted attribute {attribute_name}")
        values = np.asarray(getattr(training_scaler, attribute_name), dtype=np.float64).reshape(-1)
        if len(values) != width or not np.isfinite(values).all():
            raise ReleaseFormatError(f"training scaler {attribute_name} is invalid for {width} features")
        attributes[public_name] = values

    if not hasattr(training_scaler, "n_samples_seen_"):
        raise ReleaseFormatError("training scaler is missing fitted attribute n_samples_seen_")
    samples = np.asarray(training_scaler.n_samples_seen_, dtype=np.float64).reshape(-1)
    if len(samples) == 1:
        samples = np.repeat(samples, width)
    if len(samples) != width or not np.isfinite(samples).all():
        raise ReleaseFormatError("training scaler n_samples_seen_ is invalid")

    payload = {
        "schema_version": SCALER_SCHEMA_VERSION,
        "features": list(names),
        "mean": attributes["mean"].tolist(),
        "scale": attributes["scale"].tolist(),
        "var": attributes["var"].tolist(),
        "n_samples_seen": samples.tolist(),
    }
    FrozenStandardScaler.from_payload(payload)
    return payload


def export_json_scaler(training_scaler: Any, features: Sequence[str], destination: Path | str) -> FrozenStandardScaler:
    payload = scaler_payload(training_scaler, features)
    frozen = FrozenStandardScaler.from_payload(payload)
    _atomic_write(Path(destination), canonical_json_bytes(payload) + b"\n")
    return frozen


def assert_scaler_parity(
    training_scaler: Any,
    frozen_scaler: FrozenStandardScaler,
    vectors: Any,
    *,
    atol: float = 1e-12,
) -> None:
    expected = np.asarray(training_scaler.transform(vectors), dtype=np.float64)
    observed = frozen_scaler.transform(vectors)
    if not np.allclose(expected, observed, rtol=0.0, atol=atol, equal_nan=False):
        maximum = float(np.max(np.abs(expected - observed)))
        raise ReleaseIntegrityError(
            f"JSON scaler parity mismatch: expected max absolute error <= {atol}, observed {maximum}"
        )


def _dtype_name(dtype: torch.dtype) -> str:
    return str(dtype).removeprefix("torch.")


def tensor_metadata(state_dict: Mapping[str, torch.Tensor]) -> dict[str, dict[str, Any]]:
    if not isinstance(state_dict, Mapping) or not state_dict:
        raise ReleaseFormatError("state dict must be a non-empty mapping")
    if any(not isinstance(key, str) or not key for key in state_dict):
        raise ReleaseFormatError("state dict keys must be non-empty strings")
    metadata: dict[str, dict[str, Any]] = {}
    for key in sorted(state_dict):
        value = state_dict[key]
        if type(value) is not torch.Tensor:
            raise ReleaseFormatError(f"state dict value {key!r} must be a tensor only")
        if value.layout != torch.strided:
            raise ReleaseFormatError(f"state dict tensor {key!r} must use strided layout")
        if value.is_floating_point() and not torch.isfinite(value).all().item():
            raise ReleaseFormatError(f"state dict tensor {key!r} contains non-finite values")
        metadata[key] = {"shape": list(value.shape), "dtype": _dtype_name(value.dtype)}
    return metadata


def export_tensor_state_dict(state_dict_or_model: Any, destination: Path | str) -> dict[str, dict[str, Any]]:
    source = (
        state_dict_or_model.state_dict()
        if callable(getattr(state_dict_or_model, "state_dict", None))
        else state_dict_or_model
    )
    if not isinstance(source, Mapping):
        raise ReleaseFormatError("model export needs a state-dict mapping")
    tensor_metadata(source)
    tensors = OrderedDict(
        (key, value.detach().cpu().contiguous().clone())
        for key, value in sorted(source.items())
    )
    metadata = tensor_metadata(tensors)
    buffer = io.BytesIO()
    torch.save(tensors, buffer)
    _atomic_write(Path(destination), buffer.getvalue())
    return metadata


def _validate_tensor_metadata(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise ReleaseFormatError("model contract tensor_metadata must be a non-empty object")
    result: dict[str, dict[str, Any]] = {}
    total_elements = 0
    total_bytes = 0
    for key, record in value.items():
        if not isinstance(key, str) or not key or not isinstance(record, dict):
            raise ReleaseFormatError("model contract tensor metadata entry is malformed")
        if set(record) != {"shape", "dtype"}:
            raise ReleaseFormatError(f"tensor metadata {key!r} must contain exactly shape and dtype")
        shape = record["shape"]
        if not isinstance(shape, list) or any(
            not isinstance(size, int) or isinstance(size, bool) or size < 0 for size in shape
        ):
            raise ReleaseFormatError(f"tensor metadata {key!r} has invalid shape")
        dtype = record["dtype"]
        if not isinstance(dtype, str) or dtype not in _DTYPE_BYTES:
            raise ReleaseFormatError(f"tensor metadata {key!r} has invalid dtype")
        elements = math.prod(shape) if shape else 1
        total_elements += elements
        total_bytes += elements * _DTYPE_BYTES[dtype]
        if total_elements > MAX_MODEL_PARAMETERS or total_bytes > MAX_STATE_DICT_BYTES:
            raise ReleaseFormatError(
                "model tensor metadata exceeds parameter or decoded-byte limits"
            )
        result[key] = {"shape": shape, "dtype": dtype}
    return result


def load_tensor_state_dict(
    path: Path | str,
    expected_metadata: Mapping[str, Any],
) -> OrderedDict[str, torch.Tensor]:
    """Load with PyTorch's restricted unpickler, then enforce tensor-only exact metadata."""
    expected = _validate_tensor_metadata(dict(expected_metadata))
    checkpoint = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(checkpoint, flags)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if info.st_size > MAX_CHECKPOINT_BYTES:
                raise ReleaseFormatError(
                    f"checkpoint exceeds byte limit: expected <= {MAX_CHECKPOINT_BYTES}, "
                    f"observed {info.st_size}"
                )
            state = torch.load(handle, map_location="cpu", weights_only=True)
    except ReleaseFormatError:
        raise
    except Exception as exc:
        raise ReleaseFormatError(f"tensor-only checkpoint could not be loaded: {type(exc).__name__}") from exc
    if not isinstance(state, Mapping):
        raise ReleaseFormatError("tensor-only checkpoint must contain a state-dict mapping")
    normalized = OrderedDict((key, value) for key, value in state.items())
    observed = tensor_metadata(normalized)
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        mismatched = sorted(
            key for key in set(expected) & set(observed) if expected[key] != observed[key]
        )
        raise ReleaseCompatibilityError(
            f"state dict contract mismatch: missing={missing}, extra={extra}, mismatched={mismatched}"
        )
    return normalized


def instantiate_model_from_contract(
    contract: Mapping[str, Any],
    state_dict: Mapping[str, torch.Tensor],
    *,
    model_factories: Mapping[str, Any] | None = None,
) -> torch.nn.Module:
    """Construct the declared architecture and require a strict state-dict load."""
    validated = validate_model_contract(copy.deepcopy(dict(contract)))
    factories = dict(model_factories or {})
    if not factories:
        from backend.core.lstm_ae import LSTMAutoencoder

        factories["LSTMAutoencoder"] = LSTMAutoencoder
    model_class = validated["model_class"]
    factory = factories.get(model_class)
    if factory is None:
        raise ReleaseCompatibilityError(f"unsupported model class {model_class!r}")
    try:
        model = factory(**validated["architecture"])
    except Exception as exc:
        raise ReleaseCompatibilityError(
            f"model architecture for {model_class} could not be constructed: {type(exc).__name__}"
        ) from exc
    if not isinstance(model, torch.nn.Module):
        raise ReleaseCompatibilityError(f"model factory for {model_class} did not return a module")
    try:
        model.load_state_dict(state_dict, strict=True)
    except RuntimeError as exc:
        raise ReleaseCompatibilityError(
            f"state dict cannot load strictly into {model_class}: {exc}"
        ) from exc
    model.eval()
    scoring = validated["scoring_contract"]
    smoke_steps = min(int(scoring["T"]), 4)
    sample = torch.zeros((1, smoke_steps, len(validated["features"])), dtype=torch.float32)
    mask = torch.ones((1, smoke_steps), dtype=torch.float32)
    try:
        with torch.inference_mode():
            output = model(sample, mask)
    except Exception as exc:
        raise ReleaseCompatibilityError(
            f"model {model_class} failed bounded shape smoke test: {type(exc).__name__}"
        ) from exc
    if not isinstance(output, torch.Tensor) or tuple(output.shape) != tuple(sample.shape):
        raise ReleaseCompatibilityError(
            f"model {model_class} output shape mismatch: expected {tuple(sample.shape)}, "
            f"observed {getattr(output, 'shape', None)}"
        )
    return model


def build_model_contract(
    *,
    model_class: str,
    architecture: Mapping[str, Any],
    features: Sequence[str],
    scaler_features: Sequence[str],
    tensors: Mapping[str, Any],
    scoring_contract: Mapping[str, Any],
    cohort_reference: Mapping[str, Any],
    producing_versions: Mapping[str, str],
) -> dict[str, Any]:
    contract = {
        "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
        "model_class": model_class,
        "architecture": copy.deepcopy(dict(architecture)),
        "features": list(features),
        "scaler_features": list(scaler_features),
        "tensor_metadata": copy.deepcopy(dict(tensors)),
        "scoring_contract": copy.deepcopy(dict(scoring_contract)),
        "cohort_reference": copy.deepcopy(dict(cohort_reference)),
        "producing_versions": copy.deepcopy(dict(producing_versions)),
    }
    return validate_model_contract(contract)


def validate_model_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ReleaseFormatError("model contract must be a JSON object")
    required = {
        "schema_version", "model_class", "architecture", "features", "scaler_features",
        "tensor_metadata", "scoring_contract", "cohort_reference", "producing_versions",
    }
    if set(contract) != required:
        raise ReleaseFormatError(
            f"model contract keys mismatch: missing={sorted(required - set(contract))}, "
            f"extra={sorted(set(contract) - required)}"
        )
    if contract["schema_version"] != MODEL_ARTIFACT_SCHEMA_VERSION:
        raise ReleaseCompatibilityError(
            f"unsupported model contract schema: expected {MODEL_ARTIFACT_SCHEMA_VERSION}, "
            f"observed {contract['schema_version']}"
        )
    if not isinstance(contract["model_class"], str) or not contract["model_class"]:
        raise ReleaseFormatError("model contract model_class must be a non-empty string")
    if contract["model_class"] != "LSTMAutoencoder":
        raise ReleaseCompatibilityError(
            f"unsupported model class {contract['model_class']!r}"
        )
    architecture = contract["architecture"]
    if not isinstance(architecture, dict) or not architecture:
        raise ReleaseFormatError("model contract architecture must be a non-empty object")
    if set(architecture) != set(_LSTM_ARCHITECTURE_LIMITS):
        raise ReleaseFormatError(
            f"LSTMAutoencoder architecture keys mismatch: "
            f"expected {sorted(_LSTM_ARCHITECTURE_LIMITS)}, observed {sorted(architecture)}"
        )
    for key, maximum in _LSTM_ARCHITECTURE_LIMITS.items():
        value = _positive_int(architecture[key], field=f"model architecture {key}")
        if value > maximum:
            raise ReleaseFormatError(
                f"model architecture {key} exceeds limit: expected <= {maximum}, observed {value}"
            )
    features = _feature_names(contract["features"], field="model contract features")
    scaler_features = _feature_names(
        contract["scaler_features"], field="model contract scaler_features"
    )
    if tuple(features[: len(scaler_features)]) != scaler_features:
        raise ReleaseCompatibilityError(
            "model scaler_features must be an ordered prefix of model features"
        )
    if architecture.get("n_features") != len(features):
        raise ReleaseCompatibilityError(
            f"model n_features mismatch: expected {len(features)}, observed {architecture.get('n_features')}"
        )
    _validate_tensor_metadata(contract["tensor_metadata"])

    scoring = contract["scoring_contract"]
    if not isinstance(scoring, dict):
        raise ReleaseFormatError("model scoring_contract must be an object")
    for key in ("T", "threshold", "step_threshold", "feature_names"):
        if key not in scoring:
            raise ReleaseFormatError(f"model scoring_contract is missing {key!r}")
    sequence_length = _positive_int(scoring["T"], field="model scoring_contract.T")
    if sequence_length > MAX_SEQUENCE_LENGTH:
        raise ReleaseFormatError(
            f"model sequence length exceeds limit: expected <= {MAX_SEQUENCE_LENGTH}, "
            f"observed {sequence_length}"
        )
    threshold = _finite_float(scoring["threshold"], field="model scoring_contract.threshold")
    step_threshold = _finite_float(
        scoring["step_threshold"], field="model scoring_contract.step_threshold"
    )
    if threshold < 0 or step_threshold < 0:
        raise ReleaseFormatError("model scoring thresholds must be non-negative")
    scoring_features = _feature_names(
        scoring["feature_names"], field="model scoring_contract.feature_names"
    )
    if scoring_features != features:
        raise ReleaseCompatibilityError("model scoring feature order does not match model features")

    reference = contract["cohort_reference"]
    if not isinstance(reference, dict):
        raise ReleaseFormatError("model cohort_reference must be an object")
    for key in ("count", "digest", "formula_id", "tie_policy"):
        if key not in reference:
            raise ReleaseFormatError(f"model cohort_reference is missing {key!r}")
    _positive_int(reference["count"], field="model cohort_reference.count")
    digest = reference["digest"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ReleaseFormatError("model cohort_reference.digest must be SHA-256 hex")
    if reference["formula_id"] != COHORT_FORMULA_ID or reference["tie_policy"] != COHORT_TIE_POLICY:
        raise ReleaseCompatibilityError("model cohort percentile contract is unsupported")

    versions = contract["producing_versions"]
    if not isinstance(versions, dict) or not versions or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in versions.items()
    ):
        raise ReleaseFormatError("model producing_versions must be a non-empty string map")
    return contract


def write_model_contract(contract: Mapping[str, Any], destination: Path | str) -> None:
    validated = validate_model_contract(copy.deepcopy(dict(contract)))
    _atomic_write(Path(destination), canonical_json_bytes(validated) + b"\n")


def _cohort_digest(payload: Mapping[str, Any]) -> str:
    digest_payload = copy.deepcopy(dict(payload))
    digest_payload.pop("digest", None)
    return hashlib.sha256(canonical_json_bytes(digest_payload)).hexdigest()


def build_cohort_score_reference(scores: Sequence[float] | np.ndarray) -> dict[str, Any]:
    values = np.array(scores, dtype=np.float64, copy=True).reshape(-1)
    if values.size == 0:
        raise ReleaseFormatError("cohort score reference cannot be empty")
    if not np.isfinite(values).all():
        raise ReleaseFormatError("cohort score reference contains non-finite values")
    values.sort()
    payload: dict[str, Any] = {
        "schema_version": COHORT_REFERENCE_SCHEMA_VERSION,
        "encoding": COHORT_ENCODING,
        "formula_id": COHORT_FORMULA_ID,
        "tie_policy": COHORT_TIE_POLICY,
        "count": int(values.size),
        "scores": [float(value).hex() for value in values],
    }
    payload["digest"] = _cohort_digest(payload)
    return payload


def validate_cohort_score_reference(reference: Any) -> tuple[dict[str, Any], tuple[float, ...]]:
    if not isinstance(reference, dict):
        raise ReleaseFormatError("cohort score reference must be a JSON object")
    required = {
        "schema_version", "encoding", "formula_id", "tie_policy", "count", "scores", "digest"
    }
    if set(reference) != required:
        raise ReleaseFormatError(
            f"cohort reference keys mismatch: missing={sorted(required - set(reference))}, "
            f"extra={sorted(set(reference) - required)}"
        )
    if reference["schema_version"] != COHORT_REFERENCE_SCHEMA_VERSION:
        raise ReleaseCompatibilityError("unsupported cohort reference schema")
    if reference["encoding"] != COHORT_ENCODING:
        raise ReleaseCompatibilityError("unsupported cohort score encoding")
    if reference["formula_id"] != COHORT_FORMULA_ID or reference["tie_policy"] != COHORT_TIE_POLICY:
        raise ReleaseCompatibilityError("unsupported cohort percentile contract")
    count = _positive_int(reference["count"], field="cohort reference count")
    scores = reference["scores"]
    if not isinstance(scores, list) or len(scores) != count:
        raise ReleaseFormatError(
            f"cohort score count mismatch: expected {count}, observed "
            f"{len(scores) if isinstance(scores, list) else 'non-array'}"
        )
    values: list[float] = []
    for index, encoded in enumerate(scores):
        if not isinstance(encoded, str):
            raise ReleaseFormatError(f"cohort score {index} must be a float64 hex string")
        try:
            value = float.fromhex(encoded)
        except ValueError as exc:
            raise ReleaseFormatError(f"cohort score {index} has invalid float64 hex") from exc
        if not math.isfinite(value) or float(value).hex() != encoded:
            raise ReleaseFormatError(f"cohort score {index} is not canonical finite float64 hex")
        values.append(value)
    if values != sorted(values):
        raise ReleaseFormatError("cohort scores must be sorted in ascending order")
    digest = reference["digest"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ReleaseFormatError("cohort reference digest must be SHA-256 hex")
    expected_digest = _cohort_digest(reference)
    if digest != expected_digest:
        raise ReleaseIntegrityError(
            f"cohort reference digest mismatch: expected {expected_digest}, observed {digest}"
        )
    return reference, tuple(values)


def write_cohort_score_reference(scores: Sequence[float] | np.ndarray, destination: Path | str) -> dict[str, Any]:
    reference = build_cohort_score_reference(scores)
    _atomic_write(Path(destination), canonical_json_bytes(reference) + b"\n")
    return reference


def weak_ecdf_percentile(sorted_scores: Sequence[float], score: float) -> float:
    """Return ``100 * count(reference <= score) / N`` with inclusive ties."""
    candidate = _finite_float(score, field="candidate score")
    if len(sorted_scores) == 0:
        raise ValueError("cohort score reference cannot be empty")
    return 100.0 * bisect.bisect_right(sorted_scores, candidate) / len(sorted_scores)


def validate_online_contract(
    manifest: Mapping[str, Any],
    *,
    input_schema_version: str,
    derivation_contract_version: str,
    preprocessing_contract_version: str,
) -> None:
    expected = {
        "input_schema_version": input_schema_version,
        "derivation_contract_version": derivation_contract_version,
        "preprocessing_contract_version": preprocessing_contract_version,
    }
    observed = manifest.get("online_input_contract")
    if not isinstance(observed, dict):
        raise ReleaseFormatError("release online_input_contract must be an object")
    for key, expected_value in expected.items():
        if not isinstance(expected_value, str) or not expected_value:
            raise ReleaseFormatError(f"expected online input contract {key} must be non-empty")
        observed_value = observed.get(key)
        if observed_value != expected_value:
            raise ReleaseCompatibilityError(
                f"online input contract {key} mismatch: expected {expected_value!r}, "
                f"observed {observed_value!r}"
            )
    if observed.get("units") != ONLINE_INPUT_UNITS:
        raise ReleaseCompatibilityError(
            f"online input units mismatch: expected {ONLINE_INPUT_UNITS}, "
            f"observed {observed.get('units')!r}"
        )


def validate_manifest_model_contract(
    manifest: Mapping[str, Any],
    model_contract: Mapping[str, Any],
    cohort_reference: Mapping[str, Any],
) -> None:
    contract = validate_model_contract(copy.deepcopy(dict(model_contract)))
    reference, _ = validate_cohort_score_reference(copy.deepcopy(dict(cohort_reference)))
    if canonical_json_bytes(manifest.get("scoring_contract")) != canonical_json_bytes(
        contract["scoring_contract"]
    ):
        raise ReleaseCompatibilityError("manifest and model scoring contracts differ")
    declared = contract["cohort_reference"]
    observed = {
        "count": reference["count"],
        "digest": reference["digest"],
        "formula_id": reference["formula_id"],
        "tie_policy": reference["tie_policy"],
    }
    if declared != observed:
        raise ReleaseCompatibilityError(
            f"model cohort reference contract mismatch: expected {declared}, observed {observed}"
        )


@dataclass(frozen=True)
class LoadedModelArtifacts:
    model: torch.nn.Module
    state_dict: OrderedDict[str, torch.Tensor]
    scaler: FrozenStandardScaler
    model_contract: dict[str, Any]
    cohort_reference: tuple[float, ...]


def load_model_artifacts(
    release_dir: Path | str,
    manifest: Mapping[str, Any],
    *,
    input_schema_version: str,
    derivation_contract_version: str,
    preprocessing_contract_version: str,
) -> LoadedModelArtifacts:
    base = Path(release_dir) / "model"
    try:
        contract = validate_model_contract(
            read_json_file(base / "model-contract.json", max_bytes=MAX_MODEL_JSON_BYTES)
        )
        scaler = FrozenStandardScaler.from_payload(
            read_json_file(base / "scaler.json", max_bytes=MAX_MODEL_JSON_BYTES)
        )
        reference_payload = read_json_file(
            base / "cohort-score-reference.json",
            max_bytes=MAX_MODEL_JSON_BYTES,
        )
    except OSError as exc:
        raise ReleaseFormatError(f"cannot read model artifact: {exc}") from exc
    reference, values = validate_cohort_score_reference(reference_payload)
    validate_online_contract(
        manifest,
        input_schema_version=input_schema_version,
        derivation_contract_version=derivation_contract_version,
        preprocessing_contract_version=preprocessing_contract_version,
    )
    validate_manifest_model_contract(manifest, contract, reference)
    if tuple(contract["scaler_features"]) != scaler.features:
        raise ReleaseCompatibilityError("JSON scaler feature order does not match model features")
    state_dict = load_tensor_state_dict(base / "state_dict.pt", contract["tensor_metadata"])
    model = instantiate_model_from_contract(contract, state_dict)
    return LoadedModelArtifacts(model, state_dict, scaler, contract, values)
