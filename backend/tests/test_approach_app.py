from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.serve import approach_app


client = TestClient(approach_app.app)


def _fresh_limiter(*, global_limit: int = 100, client_limit: int = 100):
    return approach_app.EvaluationAdmissionLimiter(
        window_seconds=60,
        global_limit=global_limit,
        client_limit=client_limit,
    )


def test_health_and_openapi_describe_rules_first_product():
    response = client.get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["mode"] == "approach-screening"
    assert health["schema_version"] == 3
    assert health["attempts"] == sum(health["status_counts"].values())
    assert health["reference"]["artifact_sha256"] == approach_app.REFERENCE["artifact_sha256"]
    assert approach_app.app.title == "SADAR Analyst Console"
    assert "LSTM" not in approach_app.app.description


def test_attempt_queue_filters_and_detail_are_release_backed():
    queue = client.get("/api/approaches?limit=5000").json()
    assert len(queue) == len(approach_app.ATTEMPTS)
    assert queue[0]["status"] == "review_required"
    selected = queue[0]

    filtered = client.get(f"/api/approaches?status={selected['status']}").json()
    assert filtered
    assert {item["status"] for item in filtered} == {selected["status"]}

    detail = client.get(f"/api/approaches/{selected['attempt_id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["attempt_id"] == selected["attempt_id"]
    assert payload["path"]
    assert payload["criteria"]
    assert payload["research_benchmark"] is None
    assert all(point["observed"] is True for point in payload["path"])
    assert all("along_track_m" in point for point in payload["path"])


def test_operation_groups_exact_release_attempts():
    operation = next(item for item in approach_app.OPERATIONS_BY_ID.values() if item["attempt_ids"])
    response = client.get(f"/api/approach-operations/{operation['operation_id']}")
    assert response.status_code == 200
    assert [item["attempt_id"] for item in response.json()["attempts"]] == operation["attempt_ids"]


def test_historical_model_routes_are_not_exposed():
    assert client.post("/api/model/prepare").status_code == 404
    assert client.post("/api/simulate").status_code == 404
    isolated = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import backend.serve.approach_app; assert 'torch' not in sys.modules",
        ],
        cwd=approach_app.REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert isolated.returncode == 0, isolated.stderr


def test_disabled_upload_and_unknown_records_are_structured():
    assert approach_app.EVALUATION_ENABLED is False
    disabled = client.post("/api/evaluations")
    assert disabled.status_code == 404
    assert disabled.json()["detail"]["code"] == "evaluation_disabled"
    missing = client.get("/api/approaches/a_missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "attempt_not_found"


def test_enabled_upload_uses_approach_service_and_context_contract(monkeypatch):
    observed = {}

    class StubService:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        def evaluate(self, data, *, filename, media_type):
            return {
                "release_id": observed["release_id"],
                "filename": filename,
                "media_type": media_type,
                "bytes": len(data),
            }

    monkeypatch.setattr(approach_app, "EVALUATION_ENABLED", True)
    monkeypatch.setattr(approach_app, "EVALUATION_LIMITER", _fresh_limiter())
    monkeypatch.setattr(approach_app, "ApproachUploadEvaluationService", StubService)
    response = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["bytes"] == 7
    assert observed == {
        "release_id": approach_app.RELEASE_ID,
        "reference": approach_app.REFERENCE,
        "contextual": approach_app.CONTEXTUAL_RELEASE,
    }


def test_enabled_upload_rejects_busy_and_rate_limited_before_parsing(monkeypatch):
    monkeypatch.setattr(approach_app, "EVALUATION_ENABLED", True)

    class Locked:
        @staticmethod
        def locked():
            return True

    monkeypatch.setattr(approach_app, "EVALUATION_LOCK", Locked())
    busy = client.post("/api/evaluations", content=b"not multipart")
    assert busy.status_code == 429
    assert busy.json()["detail"]["code"] == "analysis_busy"

    monkeypatch.setattr(approach_app, "EVALUATION_LOCK", approach_app.asyncio.Lock())
    monkeypatch.setattr(
        approach_app,
        "EVALUATION_LIMITER",
        _fresh_limiter(global_limit=1, client_limit=1),
    )
    monkeypatch.setattr(
        approach_app.ApproachUploadEvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: {"results": []},
    )
    accepted = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert accepted.status_code == 200
    limited = client.post("/api/evaluations", content=b"not multipart")
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "evaluation_rate_limited"
    assert int(limited.headers["retry-after"]) >= 1


def test_enabled_upload_maps_bounded_and_unexpected_errors(monkeypatch):
    monkeypatch.setattr(approach_app, "EVALUATION_ENABLED", True)
    monkeypatch.setattr(approach_app, "EVALUATION_LIMITER", _fresh_limiter())

    def bounded(*_args, **_kwargs):
        raise approach_app.EvaluationError(422, "invalid_schema", "Safe message")

    monkeypatch.setattr(
        approach_app.ApproachUploadEvaluationService, "evaluate", bounded,
    )
    invalid = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {
        "code": "invalid_schema", "message": "Safe message",
    }

    def unexpected(*_args, **_kwargs):
        raise RuntimeError("secret-file.csv icao24=abc123")

    monkeypatch.setattr(
        approach_app.ApproachUploadEvaluationService, "evaluate", unexpected,
    )
    failed = client.post(
        "/api/evaluations",
        files={"file": ("secret-file.csv", b"icao24\nabc123\n", "text/csv")},
    )
    assert failed.status_code == 500
    assert failed.json()["detail"]["code"] == "evaluation_failed"
    assert "secret-file" not in failed.text
    assert "abc123" not in failed.text


def test_enabled_upload_validates_content_length_and_multipart(monkeypatch):
    monkeypatch.setattr(approach_app, "EVALUATION_ENABLED", True)
    monkeypatch.setattr(approach_app, "EVALUATION_LIMITER", _fresh_limiter())
    negative = client.post(
        "/api/evaluations",
        content=b"--x--\r\n",
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": "-1"},
    )
    assert negative.status_code == 400
    assert negative.json()["detail"]["code"] == "invalid_content_length"

    malformed = client.post(
        "/api/evaluations",
        content=b"not multipart",
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_multipart"


def test_evaluation_admission_limiter_expires_and_prunes_clients():
    limiter = approach_app.EvaluationAdmissionLimiter(
        window_seconds=10, global_limit=2, client_limit=1,
    )
    assert limiter.admit("client-a", now=0) is None
    assert limiter.admit("client-a", now=1) == 10
    assert limiter.admit("client-b", now=1) is None
    assert limiter.admit("client-c", now=2) == 9
    assert limiter.admit("client-c", now=11) is None
    assert set(limiter._clients) == {"client-c"}


def test_same_origin_fallback_never_captures_unknown_api(tmp_path: Path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setattr(approach_app, "FRONTEND_DIST", dist)
    deep = client.get("/approach/a_example")
    assert deep.status_code == 200
    assert '<div id="root"></div>' in deep.text
    unknown = client.get("/api/not-real")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "api_route_not_found"
