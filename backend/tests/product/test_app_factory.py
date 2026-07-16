from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sadar.api.factory import create_app
from sadar.api.settings import Settings
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
RELEASE_DIR = REPO / "backend/models/sadar_approach_v3"
RELEASE = load_release_directory(RELEASE_DIR)


def _settings(frontend: Path, **kwargs) -> Settings:
    values = {
        "release_dir": RELEASE_DIR,
        "frontend_dir": frontend,
        "evaluation_global_limit": 100,
        "evaluation_client_limit": 100,
    }
    values.update(kwargs)
    return Settings(**values)


def test_factory_instances_have_identical_read_contract(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    (frontend / "asset.txt").write_text("asset")
    first = TestClient(create_app(_settings(frontend), RELEASE))
    second = TestClient(create_app(_settings(frontend), RELEASE))
    paths = [
        "/api/health",
        "/api/approaches?limit=20",
        "/api/approaches?limit=20&status=review_required",
        "/api/metrics",
        "/api/research",
        "/api/not-a-route",
        "/deep/link",
        "/asset.txt",
    ]
    ranked = first.get("/api/approaches?limit=1").json()[0]
    paths.extend(
        [
            f"/api/approaches/{ranked['attempt_id']}",
            f"/api/approach-operations/{ranked['operation_ref']}",
            "/api/approaches/not-present",
            "/api/approach-operations/not-present",
        ]
    )
    for path in paths:
        left, right = first.get(path), second.get(path)
        assert right.status_code == left.status_code, path
        assert right.headers["content-type"] == left.headers["content-type"], path
        assert right.content == left.content, path


def test_factory_instances_have_isolated_runtime_state(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok")
    settings = _settings(frontend, evaluation_global_limit=1, evaluation_client_limit=1)
    first = create_app(settings, RELEASE)
    second = create_app(settings, RELEASE)
    assert first.state.release is not second.state.release
    assert first.state.runtime.evaluation_lock is not second.state.runtime.evaluation_lock
    assert first.state.runtime.evaluation_limiter.admit("client", now=0) is None
    assert second.state.runtime.evaluation_limiter.admit("client", now=0) is None


def test_factory_can_run_api_only_without_frontend():
    settings = Settings(release_dir=RELEASE_DIR, frontend_dir=None)
    client = TestClient(create_app(settings, RELEASE))
    assert client.get("/api/health").status_code == 200
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "application_unavailable"
