from threading import Lock

import pytest
from fastapi import HTTPException

from backend.serve import app as serve_app


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
