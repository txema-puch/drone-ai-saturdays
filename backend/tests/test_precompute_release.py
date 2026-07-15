from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from sklearn.preprocessing import StandardScaler

from backend.core.lstm_ae import LSTMAutoencoder
from backend.core.preprocessing import AE_FEATURES, SCALER_FEATURES
from backend.serve import precompute, release, report
from backend.serve.operations import annotate_segment_refs


def test_cohort_percentiles_use_inclusive_ties() -> None:
    scores = np.asarray([0.1, 0.2, 0.2, 0.9], dtype="float64")
    assert precompute.cohort_percentiles(scores).tolist() == [25.0, 75.0, 75.0, 100.0]


def test_operation_summary_preserves_band_from_unrounded_percentile() -> None:
    queue = annotate_segment_refs(
        [
            {
                "segment_id": "flight#1",
                "score": 0.3,
                "pct": 95.0,
                "band": "elevated",
                "anomalous": True,
                "label": "normal",
                "assessment_state": "reviewable",
            }
        ]
    )
    operation = precompute.build_release_operation_summaries(queue)[0]
    assert operation["worst_band"] == "elevated"
    assert operation["behavioral_worst_band"] == "elevated"


def test_model_release_export_is_tensor_json_and_full_precision(tmp_path: Path) -> None:
    vectors = np.asarray(
        [
            [1.0, 10.0, 100.0, 20.0, -1.0, 500.0],
            [2.0, 20.0, 200.0, 30.0, 0.0, 600.0],
            [4.0, 40.0, 400.0, 40.0, 1.0, 700.0],
        ]
    )
    scaler = StandardScaler().fit(vectors)
    model = LSTMAutoencoder(n_features=len(AE_FEATURES), hidden=4, latent=2, num_layers=1)
    scores = np.asarray([0.2, np.nextafter(0.2, 1.0), 0.8], dtype="float64")
    scoring = {
        "T": 8,
        "threshold": 0.222,
        "step_threshold": 0.5,
        "feature_names": list(AE_FEATURES),
    }

    contract = precompute._export_model_release_artifacts(
        tmp_path,
        model=model,
        scaler=scaler,
        scores=scores,
        scoring_contract=scoring,
    )

    model_dir = tmp_path / "model"
    assert {path.name for path in model_dir.iterdir()} == {
        "state_dict.pt",
        "scaler.json",
        "model-contract.json",
        "cohort-score-reference.json",
    }
    state = torch.load(model_dir / "state_dict.pt", map_location="cpu", weights_only=True)
    assert state and all(type(value) is torch.Tensor for value in state.values())
    assert json.loads((model_dir / "scaler.json").read_text())["features"] == list(
        SCALER_FEATURES
    )
    reference = json.loads((model_dir / "cohort-score-reference.json").read_text())
    assert reference["scores"] == [float(value).hex() for value in sorted(scores)]
    assert contract["cohort_reference"]["digest"] == reference["digest"]


def test_build_demo_release_uses_owned_staging_and_mandatory_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, dict]] = []

    def fake_writer(
        out: Path,
        *,
        model_dir: Path,
        report_cache_path: Path,
        source_commit: str,
        validation_context: dict,
    ) -> None:
        assert out.parent.name == ".staging"
        assert model_dir == tmp_path / "inputs"
        assert report_cache_path == tmp_path / "cache.json"
        for relative in release.REQUIRED_RELEASE_FILES:
            path = out / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode())
        release.write_release_manifest(
            out,
            {
                "schema_version": release.RELEASE_SCHEMA_VERSION,
                "source": {"commit": source_commit},
                "scoring_contract": {"T": 8},
                "online_input_contract": dict(precompute.ONLINE_INPUT_CONTRACT),
            },
        )
        validation_context.update(
            training_scaler=object(),
            scaler_parity_vectors=[[1.0]],
            scores_by_case_id={"case": 0.1},
        )

    def fake_semantics(path: Path, manifest: dict, **kwargs) -> None:
        calls.append((path, manifest))
        assert kwargs["report_validator"]({"report": None}) is False

    monkeypatch.setattr(precompute, "_write_release_staging", fake_writer)
    monkeypatch.setattr(precompute, "validate_release_semantics", fake_semantics)

    promoted = precompute.build_demo_release(
        model_dir=tmp_path / "inputs",
        store_root=tmp_path / "store",
        report_cache_path=tmp_path / "cache.json",
        source_commit="abc123",
    )

    assert promoted.parent == tmp_path / "store" / "releases"
    assert promoted.name == calls[0][1]["release_id"]
    assert calls[0][0].parent == tmp_path / "store" / ".staging"
    assert not any((tmp_path / "store" / ".staging").iterdir())


def test_report_binding_replays_deterministic_guard() -> None:
    abstaining = {
        "label": "normal",
        "score": 0.4,
        "pct": 90.0,
        "anomalous": True,
        "behavioral_verdict": "not_assessable",
        "assessment_state": "coverage_limited",
        "data_quality_flags": ["nonterminal_window"],
        "max_altitude_jump_m": 0.0,
        "valid_steps": 40,
        "observed_fraction": 1.0,
    }
    abstaining["report"] = report.guard_cached_report(None, abstaining, precompute.AE_THR)
    assert precompute._report_binding_is_valid(abstaining, precompute.AE_THR)

    reviewable = {"behavioral_verdict": "reviewable", "report": "Unauthorized drone."}
    assert not precompute._report_binding_is_valid(reviewable, precompute.AE_THR)
