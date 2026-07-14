from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.serve import app as serve_app
from backend.serve import evaluation
from backend.serve.model_runtime import AnalysisBusy


client = TestClient(serve_app.app)


class ReadyRuntime:
    state = "ready"

    @contextmanager
    def analysis(self):
        yield object()


def response_stub(*_args, **_kwargs):
    return {
        "release_id": "release",
        "model_id": "model",
        "dataset_digest": "a" * 64,
        "upload_sha256": "b" * 64,
        "raw_rows": 1,
        "derived_rows": 0,
        "accepted_rows": 0,
        "accepted_segments": 0,
        "rejected_segments": 1,
        "duplicate_rows_collapsed": 0,
        "rejection_reasons": [],
        "results": [],
    }


def test_disabled_routes_fail_closed_with_structured_errors():
    assert serve_app.EVALUATION_ENABLED is False
    for path in ("/api/model/prepare", "/api/evaluations"):
        response = client.post(path)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "evaluation_disabled"


def test_not_ready_and_busy_are_bounded(monkeypatch):
    monkeypatch.setattr(serve_app, "EVALUATION_ENABLED", True)

    class NotReady:
        state = "not_loaded"

    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", NotReady())
    response = client.post("/api/evaluations")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["detail"]["code"] == "model_not_ready"

    class BusyRuntime:
        state = "ready"

        @contextmanager
        def analysis(self):
            raise AnalysisBusy
            yield

    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", BusyRuntime())
    response = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert response.json()["detail"]["code"] == "analysis_busy"


def test_multipart_success_and_errors_are_structured(monkeypatch):
    monkeypatch.setattr(serve_app, "EVALUATION_ENABLED", True)
    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", ReadyRuntime())
    closed = []
    original_close = serve_app.UploadFile.close

    async def observed_close(upload):
        closed.append(True)
        await original_close(upload)

    monkeypatch.setattr(serve_app.UploadFile, "close", observed_close)

    def response_after_upload_closed(*args, **kwargs):
        assert closed == [True]
        return response_stub(*args, **kwargs)

    monkeypatch.setattr(evaluation.UploadEvaluationService, "evaluate", response_after_upload_closed)

    response = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "release_id", "model_id", "dataset_digest", "upload_sha256", "raw_rows",
        "derived_rows", "accepted_rows", "accepted_segments", "rejected_segments",
        "duplicate_rows_collapsed", "rejection_reasons", "results",
    }
    assert closed == [True]

    missing = client.post("/api/evaluations")
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "invalid_multipart"

    oversized = client.post(
        "/api/evaluations",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": str(10 * 1024 * 1024 + 1)},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "request_too_large"

    negative = client.post(
        "/api/evaluations",
        content=b"--x--\r\n",
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": "-1"},
    )
    assert negative.status_code == 400
    assert negative.json()["detail"]["code"] == "invalid_content_length"


def test_internal_evaluation_failure_is_not_misclassified_or_leaked(monkeypatch):
    monkeypatch.setattr(serve_app, "EVALUATION_ENABLED", True)
    monkeypatch.setattr(serve_app, "MODEL_RUNTIME", ReadyRuntime())

    def fail(*_args, **_kwargs):
        raise RuntimeError("secret-file.csv raw=icao24:a1b2c3")

    monkeypatch.setattr(evaluation.UploadEvaluationService, "evaluate", fail)
    response = client.post(
        "/api/evaluations",
        files={"file": ("secret-file.csv", b"icao24\na1b2c3\n", "text/csv")},
    )
    assert response.status_code == 500
    body = response.text
    assert response.json()["detail"]["code"] == "evaluation_failed"
    assert "secret-file" not in body
    assert "a1b2c3" not in body


def test_stream_guard_enforces_idle_timeout_before_parser():
    sent = []

    async def downstream(scope, receive, send):
        try:
            await receive()
        except serve_app.UploadBodyTimeout:
            sent.append("timeout")

    middleware = serve_app.EvaluationBodyLimitMiddleware(
        downstream, maximum=100, idle_seconds=0.001, total_seconds=1,
    )

    async def receive():
        await asyncio.sleep(0.02)
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(middleware(
        {"type": "http", "path": "/api/evaluations"}, receive, lambda _message: None,
    ))
    assert sent == ["timeout"]


def test_same_origin_spa_fallback_never_captures_unknown_api(
    tmp_path: Path, monkeypatch,
):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>')
    (dist / "evaluation-template.csv").write_text("time,icao24\n")
    monkeypatch.setattr(serve_app, "FRONTEND_DIST", dist)

    deep = client.get("/case/c_abcdefghijklmnop")
    assert deep.status_code == 200
    assert deep.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in deep.text
    asset = client.get("/evaluation-template.csv")
    assert asset.status_code == 200
    assert asset.text == "time,icao24\n"
    unknown_api = client.get("/api/not-a-real-route")
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"].startswith("application/json")
