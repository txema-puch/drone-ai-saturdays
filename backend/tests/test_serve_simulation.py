from threading import Lock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.serve import app as serve_app


client = TestClient(serve_app.app)


def _request() -> serve_app.SimulationRequest:
    return serve_app.SimulationRequest(
        id=int(next(iter(serve_app.CASES))),
        kind="speed_spike",
        intensity=1.0,
        onset=0.5,
    )


def test_simulation_rejects_an_overlapping_request(monkeypatch):
    held_lock = Lock()
    held_lock.acquire()
    monkeypatch.setattr(serve_app, "SIMULATION_LOCK", held_lock)

    with pytest.raises(HTTPException) as caught:
        serve_app.simulate(_request())

    assert caught.value.status_code == 409
    assert caught.value.detail == "simulation already in progress"


def test_simulation_releases_the_lock_when_loading_fails(monkeypatch):
    lock = Lock()
    monkeypatch.setattr(serve_app, "SIMULATION_LOCK", lock)
    monkeypatch.setattr(
        serve_app,
        "_sim_artifacts",
        lambda: (_ for _ in ()).throw(RuntimeError("load failed")),
    )

    with pytest.raises(RuntimeError, match="load failed"):
        serve_app.simulate(_request())

    assert lock.acquire(blocking=False)
    lock.release()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_simulation_request_rejects_invalid_intensity(value):
    with pytest.raises(ValidationError):
        serve_app.SimulationRequest(
            id=int(next(iter(serve_app.CASES))),
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
