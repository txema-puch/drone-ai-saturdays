from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from sadar.api.evaluation import EvaluationError
from sadar.api.factory import create_app
from sadar.api.middleware import EvaluationAdmissionLimiter
from sadar.api.settings import Settings
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
RELEASE_DIR = Path(
    os.environ.get(
        "SADAR_APPROACH_RELEASE_DIR",
        REPO / ".artifacts/approach-release",
    )
)
RELEASE = load_release_directory(RELEASE_DIR)


def _frontend(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    root.mkdir(parents=True)
    (root / "index.html").write_text('<div id="root"></div>')
    return root


def _app(
    tmp_path: Path,
    *,
    evaluation_enabled: bool = False,
    evaluation_global_limit: int = 100,
    evaluation_client_limit: int = 100,
    service_factory=None,
):
    settings = Settings(
        release_dir=RELEASE_DIR,
        frontend_dir=_frontend(tmp_path),
        evaluation_enabled=evaluation_enabled,
        evaluation_global_limit=evaluation_global_limit,
        evaluation_client_limit=evaluation_client_limit,
    )
    kwargs = {"evaluation_service_factory": service_factory} if service_factory else {}
    return create_app(settings, RELEASE, **kwargs)


def test_health_and_openapi_describe_rules_first_product(tmp_path: Path):
    app = _app(tmp_path)
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["mode"] == "approach-screening"
    assert health["schema_version"] == 3
    assert health["attempts"] == sum(health["status_counts"].values())
    assert health["reference"]["artifact_sha256"] == RELEASE["reference"]["artifact_sha256"]
    assert app.title == "SADAR Analyst Console"
    assert "LSTM" not in app.description


def test_attempt_queue_filters_and_detail_are_release_backed(tmp_path: Path):
    client = TestClient(_app(tmp_path))
    queue = client.get("/api/approaches?limit=5000").json()
    assert len(queue) == len(RELEASE["attempts"])
    assert queue[0]["status"] == "review_required"
    selected = queue[0]
    filtered = client.get(f"/api/approaches?status={selected['status']}").json()
    assert filtered
    assert {item["status"] for item in filtered} == {selected["status"]}
    payload = client.get(f"/api/approaches/{selected['attempt_id']}").json()
    assert payload["attempt_id"] == selected["attempt_id"]
    assert payload["path"] and payload["criteria"]
    assert payload["research_benchmark"] is None
    assert all(point["observed"] is True for point in payload["path"])


def test_operation_groups_exact_release_attempts(tmp_path: Path):
    app = _app(tmp_path)
    operation = next(
        item for item in app.state.release.operations_by_id.values() if item["attempt_ids"]
    )
    response = TestClient(app).get(
        f"/api/approach-operations/{operation['operation_id']}"
    )
    assert response.status_code == 200
    assert [item["attempt_id"] for item in response.json()["attempts"]] == operation["attempt_ids"]


def test_product_import_does_not_load_historical_model_stack():
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO / "backend/src")
    isolated = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import sadar.api.factory; assert 'torch' not in sys.modules",
        ],
        cwd=REPO,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert isolated.returncode == 0, isolated.stderr


def test_disabled_upload_and_unknown_records_are_structured(tmp_path: Path):
    client = TestClient(_app(tmp_path))
    disabled = client.post("/api/evaluations")
    assert disabled.status_code == 404
    assert disabled.json()["detail"]["code"] == "evaluation_disabled"
    missing = client.get("/api/approaches/a_missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "attempt_not_found"


def test_enabled_upload_uses_injected_service_and_context_contract(tmp_path: Path):
    observed = {}

    class StubService:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        def evaluate(self, data, *, filename, media_type):
            return {"filename": filename, "media_type": media_type, "bytes": len(data)}

    client = TestClient(
        _app(tmp_path, evaluation_enabled=True, service_factory=StubService)
    )
    response = client.post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["bytes"] == 7
    assert observed == {
        "release_id": RELEASE["manifest"]["release_id"],
        "reference": RELEASE["reference"],
        "contextual": (
            RELEASE["manifest"].get("contracts", {}).get("engine_version")
            == "approach_context_v1"
        ),
    }


def test_enabled_upload_rate_limits_before_second_parse(tmp_path: Path):
    class StubService:
        def __init__(self, **_kwargs):
            pass

        def evaluate(self, *_args, **_kwargs):
            return {"results": []}

    client = TestClient(
        _app(
            tmp_path,
            evaluation_enabled=True,
            evaluation_global_limit=1,
            evaluation_client_limit=1,
            service_factory=StubService,
        )
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


def test_enabled_upload_maps_bounded_and_unexpected_errors(tmp_path: Path, caplog):
    class Bounded:
        def __init__(self, **_kwargs):
            pass

        def evaluate(self, *_args, **_kwargs):
            raise EvaluationError(422, "invalid_schema", "Safe message")

    invalid = TestClient(
        _app(tmp_path / "bounded", evaluation_enabled=True, service_factory=Bounded)
    ).post(
        "/api/evaluations",
        files={"file": ("sample.csv", b"time\n1\n", "text/csv")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {
        "code": "invalid_schema",
        "message": "Safe message",
    }

    class Unexpected:
        def __init__(self, **_kwargs):
            pass

        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("secret-file.csv icao24=abc123")

    failed = TestClient(
        _app(tmp_path / "unexpected", evaluation_enabled=True, service_factory=Unexpected)
    ).post(
        "/api/evaluations",
        files={"file": ("secret-file.csv", b"icao24\nabc123\n", "text/csv")},
    )
    assert failed.status_code == 500
    assert failed.json()["detail"]["code"] == "evaluation_failed"
    assert "secret-file" not in failed.text and "abc123" not in failed.text
    assert "approach evaluation failed" in caplog.text
    assert "secret-file" not in caplog.text and "abc123" not in caplog.text


def test_enabled_upload_validates_content_length_and_multipart(tmp_path: Path):
    client = TestClient(_app(tmp_path, evaluation_enabled=True))
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
    limiter = EvaluationAdmissionLimiter(
        window_seconds=10,
        global_limit=2,
        client_limit=1,
    )
    assert limiter.admit("client-a", now=0) is None
    assert limiter.admit("client-a", now=1) == 10
    assert limiter.admit("client-b", now=1) is None
    assert limiter.admit("client-c", now=2) == 9
    assert limiter.admit("client-c", now=11) is None
    assert set(limiter._clients) == {"client-c"}


def test_same_origin_fallback_never_captures_unknown_api(tmp_path: Path):
    client = TestClient(_app(tmp_path))
    deep = client.get("/approach/a_example")
    assert deep.status_code == 200
    assert '<div id="root"></div>' in deep.text
    unknown = client.get("/api/not-real")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "api_route_not_found"
