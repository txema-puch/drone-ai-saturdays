import io
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.core.approach_geometry import EARTH_RADIUS_M, load_lemd_geometry
from backend.core.approach_reference import load_approach_reference
from backend.serve.approach_evaluation import (
    ApproachUploadEvaluationService,
    EvaluationError,
)


def _approach_frame(*, velocity: float = 70.0, icao24: str = "abc123") -> pd.DataFrame:
    runway = load_lemd_geometry().thresholds["18L"]
    along = np.linspace(12_000.0, 100.0, 80)
    bearing = math.radians(runway.true_bearing_deg)
    east = -along * math.sin(bearing)
    north = -along * math.cos(bearing)
    return pd.DataFrame({
        "time": 1_700_000_000 + np.arange(len(along)) * 10,
        "icao24": icao24,
        "lat": runway.lat + np.degrees(north / EARTH_RADIUS_M),
        "lon": runway.lon + np.degrees(
            east / (EARTH_RADIUS_M * np.cos(np.radians(runway.lat)))
        ),
        "baroaltitude": runway.elevation_m + np.tan(np.radians(3.0)) * along,
        "velocity": velocity,
        "heading": runway.true_bearing_deg,
        "vertrate": -3.0,
        "onground": False,
    })


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode()


def _parquet(frame: pd.DataFrame) -> bytes:
    target = io.BytesIO()
    frame.to_parquet(target, index=False)
    return target.getvalue()


@pytest.fixture
def service() -> ApproachUploadEvaluationService:
    return ApproachUploadEvaluationService(release_id="approach-fixture-v1")


@pytest.fixture
def contextual_service() -> ApproachUploadEvaluationService:
    reference_path = (
        Path(__file__).resolve().parents[1]
        / "core/resources/lemd_approach_context_reference_v1.json"
    )
    return ApproachUploadEvaluationService(
        release_id="approach-context-fixture-v1",
        reference=load_approach_reference(reference_path),
        contextual=True,
    )


def test_fixture_evaluates_without_model_and_returns_exact_rules_dto(service):
    response = service.evaluate(
        _csv(_approach_frame()), filename="observations.csv", media_type="text/csv"
    )

    assert set(response) == {
        "schema_version", "release_id", "reference_sha256", "dataset_digest",
        "upload_sha256", "raw_rows", "canonical_rows", "duplicate_rows_collapsed",
        "operations", "attempts", "status_counts", "rejection_reasons", "results",
    }
    assert response["schema_version"] == "approach_upload_evaluation_v1"
    assert response["release_id"] == "approach-fixture-v1"
    assert len(response["reference_sha256"]) == 64
    assert response["operations"] == 1
    assert response["attempts"] == 1

    result = response["results"][0]
    assert set(result) == {
        "evaluation_ref", "operation_id", "attempt_index", "attempt", "status",
        "runway", "failed_criteria", "reasons", "quality", "criteria",
        "maneuvers", "provenance", "trajectory", "channels",
    }
    assert result["evaluation_ref"].startswith("ae_")
    assert result["runway"]["direction"] == "18"
    assert result["provenance"]["reference"]["artifact_sha256"] == response["reference_sha256"]
    assert result["trajectory"]["observed_points"] == 80
    assert len(result["trajectory"]["points"]) == len(result["channels"]["time"])


def test_dataset_digest_and_evaluation_refs_ignore_row_order_and_container(service):
    frame = _approach_frame()
    shuffled = frame.sample(frac=1.0, random_state=7)
    csv_response = service.evaluate(
        _csv(shuffled), filename="rows.csv", media_type="text/csv"
    )
    parquet_response = service.evaluate(
        _parquet(frame), filename="rows.parquet",
        media_type="application/vnd.apache.parquet",
    )

    assert csv_response["dataset_digest"] == parquet_response["dataset_digest"]
    assert [item["evaluation_ref"] for item in csv_response["results"]] == [
        item["evaluation_ref"] for item in parquet_response["results"]
    ]
    assert csv_response["upload_sha256"] != parquet_response["upload_sha256"]


def test_duplicates_collapse_and_conflicting_observations_fail(service):
    frame = _approach_frame()
    duplicate = pd.concat([frame, frame.iloc[[12]]], ignore_index=True)
    response = service.evaluate(
        _csv(duplicate), filename="duplicate.csv", media_type="text/csv"
    )
    assert response["raw_rows"] == 81
    assert response["canonical_rows"] == 80
    assert response["duplicate_rows_collapsed"] == 1

    conflict = frame.iloc[[12]].copy()
    conflict["lat"] += 0.01
    with pytest.raises(EvaluationError) as raised:
        service.evaluate(
            _csv(pd.concat([frame, conflict], ignore_index=True)),
            filename="conflict.csv", media_type="text/csv",
        )
    assert raised.value.status_code == 422
    assert raised.value.code == "conflicting_observations"
    assert raised.value.detail()["code"] == "conflicting_observations"


def test_no_attempt_is_an_empty_bounded_result_not_an_error(service):
    frame = _approach_frame().iloc[:20].copy()
    frame["lat"] = 0.0
    frame["lon"] = 0.0
    response = service.evaluate(
        _csv(frame), filename="no-attempt.csv", media_type="text/csv"
    )
    assert response["operations"] == 1
    assert response["attempts"] == 0
    assert response["status_counts"] == {}
    assert response["results"] == []
    assert response["rejection_reasons"] == [{
        "code": "no_supported_approach_attempt",
        "message": (
            "The operation did not contain a supported LEMD final-corridor visit; "
            "no holding, diversion, or intent label was inferred."
        ),
        "count": 1,
        "operation_id": response["rejection_reasons"][0]["operation_id"],
    }]


def test_hard_input_row_operation_attempt_trajectory_and_response_bounds(service, monkeypatch):
    frame = _approach_frame()

    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_INPUT_BYTES", 1)
    with pytest.raises(EvaluationError, match="10 MiB") as raised:
        service.evaluate(_csv(frame), filename="rows.csv", media_type="text/csv")
    assert raised.value.code == "request_too_large"
    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_INPUT_BYTES", 10 * 1024 * 1024)

    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_RAW_ROWS", 1)
    with pytest.raises(EvaluationError) as raised:
        service.evaluate(_csv(frame), filename="rows.csv", media_type="text/csv")
    assert raised.value.code == "too_many_rows"
    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_RAW_ROWS", 50_000)

    second = _approach_frame(icao24="def456")
    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_OPERATIONS", 1)
    with pytest.raises(EvaluationError) as raised:
        service.evaluate(
            _csv(pd.concat([frame, second], ignore_index=True)),
            filename="two.csv", media_type="text/csv",
        )
    assert raised.value.code == "too_many_operations"
    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_OPERATIONS", 250)

    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_ATTEMPTS", 0)
    with pytest.raises(EvaluationError) as raised:
        service.evaluate(_csv(frame), filename="rows.csv", media_type="text/csv")
    assert raised.value.code == "too_many_attempts"
    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_ATTEMPTS", 500)

    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_TRAJECTORY_POINTS", 5)
    response = service.evaluate(_csv(frame), filename="rows.csv", media_type="text/csv")
    assert response["results"][0]["trajectory"]["returned_points"] == 5
    assert len(response["results"][0]["channels"]["time"]) == 5

    monkeypatch.setattr("backend.serve.approach_evaluation.MAX_RESPONSE_BYTES", 10)
    with pytest.raises(EvaluationError) as raised:
        service.evaluate(_csv(frame), filename="rows.csv", media_type="text/csv")
    assert raised.value.code == "evaluation_response_too_large"


def test_published_reference_flags_persistent_speed_exceedance(service):
    response = service.evaluate(
        _csv(_approach_frame(velocity=140.0)),
        filename="fast.csv", media_type="text/csv",
    )
    result = response["results"][0]
    assert result["status"] == "review_required"
    assert "observed_ground_speed_envelope" in result["failed_criteria"]


def test_contextual_upload_uses_supplied_qnh_wind_and_aircraft_type(contextual_service):
    frame = _approach_frame()
    frame["qnh_hpa"] = 1003.25
    frame["wind_from_direction_deg"] = 180.0
    frame["wind_speed_mps"] = 5.0
    frame["aircraft_typecode"] = "a320"

    response = contextual_service.evaluate(
        _csv(frame), filename="context.csv", media_type="text/csv"
    )

    result = response["results"][0]
    assert result["provenance"]["engine_version"] == "approach_context_v1"
    assert result["context"]["weather"]["station"] == "analyst_supplied"
    assert result["context"]["weather"]["qnh_hpa"] == 1003.25
    assert result["context"]["weather"]["headwind_mps"] == pytest.approx(5.0, abs=0.1)
    assert result["context"]["aircraft"]["typecode"] == "A320"
    assert result["provenance"]["reference"]["speed_class"] == "A320"


def test_contextual_upload_rejects_conflicting_aircraft_type(contextual_service):
    frame = _approach_frame()
    frame["aircraft_typecode"] = "A320"
    frame.loc[40:, "aircraft_typecode"] = "B738"

    with pytest.raises(EvaluationError) as raised:
        contextual_service.evaluate(
            _csv(frame), filename="conflicting-context.csv", media_type="text/csv"
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "conflicting_aircraft_context"


def test_base_release_rejects_nonempty_context_instead_of_ignoring_it(service):
    frame = _approach_frame()
    frame["qnh_hpa"] = 1013.25

    with pytest.raises(EvaluationError) as raised:
        service.evaluate(_csv(frame), filename="context.csv", media_type="text/csv")

    assert raised.value.status_code == 422
    assert raised.value.code == "context_not_supported"


def test_contextual_upload_rejects_weather_fields_split_across_rows(contextual_service):
    frame = _approach_frame()
    frame["qnh_hpa"] = np.nan
    frame["wind_from_direction_deg"] = np.nan
    frame.loc[0, "qnh_hpa"] = 1013.25
    frame.loc[40, "wind_from_direction_deg"] = 180.0

    with pytest.raises(EvaluationError) as raised:
        contextual_service.evaluate(
            _csv(frame), filename="sparse-context.csv", media_type="text/csv"
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "sparse_weather_context"


def test_unknown_uploaded_type_discloses_reference_fallback(contextual_service):
    frame = _approach_frame()
    frame["aircraft_typecode"] = "ZZZZ"

    result = contextual_service.evaluate(
        _csv(frame), filename="unknown-type.csv", media_type="text/csv"
    )["results"][0]

    aircraft = result["context"]["aircraft"]
    assert aircraft["source"] == "analyst_supplied"
    assert aircraft["temporal_identity_warning"] is None
    assert aircraft["reference_fallbacks"] == ["unknown_speed_class"]
    assert aircraft["effective_reference_classes"] == ["unknown"]


def test_dto_forbids_model_score_fields_and_filename(service):
    response = service.evaluate(
        _csv(_approach_frame()), filename="secret-name.csv", media_type="text/csv"
    )
    forbidden = {
        "model_id", "model", "score", "anomaly_score", "cohort_percentile",
        "reconstruction_error", "segment_score", "filename", "raw_rows_data",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from keys(nested)

    observed_keys = set(keys(response))
    assert forbidden.isdisjoint(observed_keys)
    assert b"secret-name" not in str(response).encode()
