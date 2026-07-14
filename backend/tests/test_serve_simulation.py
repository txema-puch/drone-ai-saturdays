from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.serve import app as serve_app
from backend.serve.model_runtime import AnalysisBusy


client = TestClient(serve_app.app)


def _request() -> serve_app.SimulationRequest:
    return serve_app.SimulationRequest(
        case_id=next(iter(serve_app.CASES)),
        kind="speed_spike",
        intensity=1.0,
        onset=0.5,
    )


def test_simulation_rejects_an_overlapping_request(monkeypatch):
    class BusyRuntime:
        @contextmanager
        def analysis(self):
            raise AnalysisBusy
            yield

    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", BusyRuntime())

    with pytest.raises(HTTPException) as caught:
        serve_app.simulate(_request())

    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == "analysis_busy"
    assert caught.value.headers["Retry-After"] == "1"


def test_simulation_releases_the_shared_slot_when_scoring_fails(monkeypatch):
    released = []

    class ReadyRuntime:
        @contextmanager
        def analysis(self):
            try:
                yield SimpleNamespace(scaler=object(), model=object(), cohort_reference=(0.1,))
            finally:
                released.append(True)

    case = serve_app.CASES[next(iter(serve_app.CASES))]
    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", ReadyRuntime())
    monkeypatch.setattr(
        pd, "read_parquet", lambda *_args, **_kwargs: pd.DataFrame({"segment_id": [case["segment_id"]]})
    )
    from backend.serve import scoring
    monkeypatch.setattr(scoring, "simulate_segment", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("score failed")))

    with pytest.raises(RuntimeError, match="score failed"):
        serve_app.simulate(_request())

    assert released == [True]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_simulation_request_rejects_invalid_intensity(value):
    with pytest.raises(ValidationError):
        serve_app.SimulationRequest(
            case_id=next(iter(serve_app.CASES)),
            kind="speed_spike",
            intensity=value,
            onset=0.5,
        )


@pytest.mark.parametrize("path", ["/api/flights", "/api/operations"])
def test_queue_query_validation(path):
    assert client.get(f"{path}?limit=0").json() == []
    assert client.get(f"{path}?limit=-1").status_code == 422
    assert client.get(f"{path}?limit=5001").status_code == 422
    assert client.get(f"{path}?order=unknown").status_code == 422


def test_operation_queue_uses_compact_segment_evidence():
    response = client.get("/api/operations?limit=1", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    segment = response.json()[0]["segments"][0]
    assert set(segment) == set(serve_app.OPERATION_QUEUE_SEGMENT_FIELDS)


def test_queue_and_case_route_use_the_same_stable_string_identity():
    queue_row = client.get("/api/flights?limit=1").json()[0]
    assert "id" not in queue_row
    assert queue_row["case_id"].startswith("c_")

    if queue_row["has_case"]:
        case_id = queue_row["case_id"]
    else:
        case_id = next(iter(serve_app.CASES))
    response = client.get(f"/api/flights/{case_id}")

    assert response.status_code == 200
    assert response.json()["case_id"] == case_id
    assert client.get("/api/flights/4238").status_code == 404


def test_operation_contract_exposes_case_ids_not_numeric_segment_ids():
    operation = client.get("/api/operations?limit=1").json()[0]

    assert operation["worst_case_id"].startswith("c_")
    assert "worst_segment_id_num" not in operation
    assert "behavioral_worst_segment_id_num" not in operation
    assert all("case_id" in segment and "id" not in segment for segment in operation["segments"])


def test_simulation_response_preserves_the_requested_case_identity(monkeypatch):
    case_id, case = next(iter(serve_app.CASES.items()))
    clean = pd.DataFrame({"segment_id": [case["segment_id"]]})
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: clean)

    class ReadyRuntime:
        @contextmanager
        def analysis(self):
            yield SimpleNamespace(scaler=object(), model=object(), cohort_reference=(0.1,))

    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", ReadyRuntime())

    from backend.serve import scoring

    monkeypatch.setattr(scoring, "simulate_segment", lambda *_args, **_kwargs: {})
    result = serve_app.simulate(
        serve_app.SimulationRequest(
            case_id=case_id,
            kind="speed_spike",
            intensity=1.0,
            onset=0.5,
        )
    )

    assert result["case_id"] == case_id
    assert result["segment_id"] == case["segment_id"]
