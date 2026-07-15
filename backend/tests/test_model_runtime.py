from __future__ import annotations

from threading import Event
import time

import pytest

from backend.serve.model_runtime import AnalysisBusy, ModelNotReady, ModelRuntime


def test_prepare_is_nonblocking_idempotent_and_allows_one_retry(caplog):
    started = Event()
    release = Event()
    calls = []

    def loader():
        calls.append(None)
        started.set()
        release.wait(2)
        if len(calls) == 1:
            raise RuntimeError("first attempt fails")
        return object()

    runtime = ModelRuntime(loader)
    assert runtime.snapshot() == {"model_state": "not_loaded", "model_retry_remaining": 1}
    assert runtime.prepare()["model_state"] == "loading"
    assert started.wait(1)
    assert runtime.prepare()["model_state"] == "loading"
    release.set()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if runtime.state == "failed":
            break
        time.sleep(0.001)
    assert runtime.state == "failed"
    assert "Frozen model preparation failed" in caplog.text
    assert runtime.snapshot()["model_retry_remaining"] == 1

    runtime.prepare()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if runtime.state == "ready":
            break
        time.sleep(0.001)
    assert runtime.state == "ready"
    assert len(calls) == 2
    assert runtime.snapshot()["model_retry_remaining"] == 0


def test_analysis_is_nonqueueing_and_releases_after_failure():
    loaded = object()
    runtime = ModelRuntime(lambda: loaded)
    runtime._state = "ready"
    runtime._loaded = loaded

    with runtime.analysis() as observed:
        assert observed is loaded
        with pytest.raises(AnalysisBusy):
            with runtime.analysis():
                pass

    with pytest.raises(RuntimeError):
        with runtime.analysis():
            raise RuntimeError("work failed")
    with runtime.analysis() as observed:
        assert observed is loaded


def test_analysis_rejects_not_ready_without_leaking_the_slot():
    runtime = ModelRuntime(lambda: object())
    with pytest.raises(ModelNotReady):
        with runtime.analysis():
            pass
    assert runtime._analysis_lock.acquire(blocking=False)
    runtime._analysis_lock.release()
