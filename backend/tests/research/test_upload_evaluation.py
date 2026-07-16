from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from sadar_research.trajectory_anomaly.models.lstm_ae import LSTMAutoencoder
from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES, SCALER_FEATURES
from sadar_research.trajectory_anomaly.evaluation.upload import EvaluationError, UploadEvaluationService


SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/evaluation-synthetic-sample.csv"
RESULT_FIELDS = {
    "evaluation_ref", "segment_id", "model_status", "path", "reconstructed", "scores",
    "window_score", "pct", "threshold", "step_threshold", "valid_steps", "n_steps",
    "assessment_state", "behavioral_verdict", "review_lane", "data_quality_flags",
    "observed_fraction", "max_altitude_jump_m", "max_implied_vertical_rate_mps",
    "max_implied_ground_speed_mps", "feature_attribution", "channels", "center",
    "step_seconds",
}


@pytest.fixture(scope="module")
def loaded():
    scaler = StandardScaler().fit(pd.DataFrame(
        [
            [40.0, -4.0, 0.0, 0.0, -10.0, 0.0],
            [41.0, -3.0, 5_000.0, 200.0, 10.0, 200_000.0],
        ],
        columns=SCALER_FEATURES,
    ))
    return SimpleNamespace(
        model=LSTMAutoencoder(n_features=len(AE_FEATURES), hidden=4, latent=2),
        scaler=scaler,
        cohort_reference=(0.1, 1.0, 10.0),
        model_contract={"scoring_contract": {
            "T": 260, "threshold": 1.0, "step_threshold": 0.5,
        }},
    )


@pytest.fixture
def service():
    return UploadEvaluationService(release_id="release-a", model_id="model-a")


def test_sample_evaluates_with_exact_upload_only_dto(service, loaded):
    response = service.evaluate(
        SAMPLE.read_bytes(), filename="sample.csv", media_type="text/csv", loaded=loaded,
    )
    assert response["release_id"] == "release-a"
    assert response["raw_rows"] == 31
    assert response["accepted_segments"] == 1
    assert len(response["results"]) == 1
    assert set(response["results"][0]) == RESULT_FIELDS
    forbidden = {"label", "case_id", "case_ref", "operation_ref", "report", "anomalous", "band"}
    assert forbidden.isdisjoint(response["results"][0])


def test_digest_is_row_order_and_container_independent(service, loaded):
    frame = pd.read_csv(SAMPLE)
    csv_response = service.evaluate(
        frame.sample(frac=1, random_state=7).to_csv(index=False).encode(),
        filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    parquet = io.BytesIO()
    frame.to_parquet(parquet, index=False)
    parquet_response = service.evaluate(
        parquet.getvalue(), filename="x.parquet",
        media_type="application/vnd.apache.parquet", loaded=loaded,
    )
    assert csv_response["dataset_digest"] == parquet_response["dataset_digest"]
    assert csv_response["results"][0]["evaluation_ref"] == parquet_response["results"][0]["evaluation_ref"]
    assert csv_response["upload_sha256"] != parquet_response["upload_sha256"]


def test_identifier_text_is_preserved_across_csv_and_parquet(service, loaded):
    frame = pd.read_csv(SAMPLE)
    frame["icao24"] = "000001"
    csv_response = service.evaluate(
        frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    parquet = io.BytesIO()
    frame.to_parquet(parquet, index=False)
    parquet_response = service.evaluate(
        parquet.getvalue(), filename="x.parquet",
        media_type="application/vnd.apache.parquet", loaded=loaded,
    )
    assert csv_response["dataset_digest"] == parquet_response["dataset_digest"]


def test_csv_schema_is_rejected_before_materialization(service, loaded, monkeypatch):
    header = ",".join((*tuple(pd.read_csv(SAMPLE, nrows=0).columns), "attacker_payload"))
    monkeypatch.setattr(
        "sadar_research.trajectory_anomaly.evaluation.upload.pd.read_csv",
        lambda *_args, **_kwargs: pytest.fail("body was materialized before schema validation"),
    )
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            f"{header}\n".encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.code == "invalid_schema"


@pytest.mark.parametrize("body", [b"1,2,3\n", b"1,2,3,4,5,6,7,8,9,10\n"])
def test_ragged_csv_rows_are_rejected(service, loaded, body):
    header = b"time,icao24,lat,lon,baroaltitude,velocity,heading,vertrate,onground\n"
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(header + body, filename="x.csv", media_type="text/csv", loaded=loaded)
    assert caught.value.code == "invalid_csv"


def test_resampling_expansion_is_rejected_before_preprocess(service, loaded, monkeypatch):
    monkeypatch.setattr("sadar_research.trajectory_anomaly.evaluation.upload.MAX_GRID_ROWS", 20)
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            SAMPLE.read_bytes(), filename="sample.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.code == "derived_rows_too_large"


def test_exact_duplicates_collapse_but_conflicts_fail(service, loaded):
    frame = pd.read_csv(SAMPLE)
    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    response = service.evaluate(
        duplicated.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    assert response["duplicate_rows_collapsed"] == 1

    conflicted = duplicated.copy()
    conflicted.loc[len(conflicted) - 1, "lat"] += 0.1
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            conflicted.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.code == "conflicting_observations"


def test_null_boolean_and_invalid_boolean_rules(service, loaded):
    frame = pd.read_csv(SAMPLE)
    frame["onground"] = frame["onground"].astype(object)
    frame.loc[0, "onground"] = None
    response = service.evaluate(
        frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    assert any(reason["code"] == "onground_defaulted" for reason in response["rejection_reasons"])

    frame.loc[0, "onground"] = "yes"
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.code == "invalid_schema"


@pytest.mark.parametrize(
    ("data", "filename", "media_type", "code"),
    [
        (b"", "x.csv", "text/csv", "empty_file"),
        (b"time,time\n1,1\n", "x.csv", "text/csv", "duplicate_columns"),
        (b"hello", "x.txt", "text/plain", "unsupported_file_type"),
        (b"\xff", "x.csv", "text/csv", "invalid_encoding"),
    ],
)
def test_bounded_parse_errors(service, loaded, data, filename, media_type, code):
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(data, filename=filename, media_type=media_type, loaded=loaded)
    assert caught.value.code == code


def test_derived_columns_are_ignored_and_recomputed(service, loaded):
    frame = pd.read_csv(SAMPLE)
    frame["segment_id"] = "attacker-controlled"
    response = service.evaluate(
        frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    assert response["results"][0]["segment_id"] != "attacker-controlled"


def test_response_size_is_bounded(service, loaded, monkeypatch):
    monkeypatch.setattr("sadar_research.trajectory_anomaly.evaluation.upload.MAX_RESPONSE_BYTES", 10)
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            SAMPLE.read_bytes(), filename="sample.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.status_code == 413
    assert caught.value.code == "evaluation_response_too_large"


def test_missing_and_impossible_observations_are_reported(service, loaded):
    frame = pd.read_csv(SAMPLE)
    frame.loc[0, "velocity"] = None
    frame.loc[1, "vertrate"] = 999
    response = service.evaluate(
        frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    reasons = {reason["code"]: reason["count"] for reason in response["rejection_reasons"]}
    assert reasons["missing_observations"] >= 1
    assert reasons["impossible_observations"] >= 1


def test_row_and_segment_limits_reject_instead_of_truncating(service, loaded, monkeypatch):
    monkeypatch.setattr("sadar_research.trajectory_anomaly.evaluation.upload.MAX_RAW_ROWS", 2)
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            SAMPLE.read_bytes(), filename="sample.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.status_code == 413
    assert caught.value.code == "too_many_rows"

    monkeypatch.setattr("sadar_research.trajectory_anomaly.evaluation.upload.MAX_RAW_ROWS", 50_000)
    frame = pd.read_csv(SAMPLE)
    many = pd.concat(
        [frame.assign(icao24=f"a{index:05x}") for index in range(26)], ignore_index=True
    )
    with pytest.raises(EvaluationError) as caught:
        service.evaluate(
            many.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
        )
    assert caught.value.status_code == 413
    assert caught.value.code == "too_many_segments"


def test_fully_unobserved_model_window_is_rejected(service, loaded):
    frame = pd.read_csv(SAMPLE)
    frame["heading"] = None
    response = service.evaluate(
        frame.to_csv(index=False).encode(), filename="x.csv", media_type="text/csv", loaded=loaded,
    )
    assert response["accepted_segments"] == 0
    assert response["results"] == []
    assert any(
        reason["code"] == "unscorable_rejected" for reason in response["rejection_reasons"]
    )
