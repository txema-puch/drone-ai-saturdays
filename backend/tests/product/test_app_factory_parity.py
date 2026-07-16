from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.serve import approach_app as legacy
from sadar.api.factory import create_app
from sadar.api.settings import Settings


def _clients(tmp_path: Path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    (frontend / "asset.txt").write_text("asset")
    monkeypatch.setattr(legacy, "FRONTEND_DIST", frontend)
    settings = Settings(
        release_dir=legacy.RELEASE_DIR,
        frontend_dir=frontend,
        evaluation_enabled=False,
        evaluation_global_limit=100,
        evaluation_client_limit=100,
    )
    return TestClient(legacy.app), TestClient(create_app(settings, legacy.RELEASE))


def test_read_contract_matches_legacy_application(tmp_path: Path, monkeypatch):
    old, new = _clients(tmp_path, monkeypatch)
    paths = [
        "/api/health",
        "/api/approaches?limit=20",
        "/api/approaches?limit=20&status=review_required",
        "/api/approaches?limit=20&direction=18_pair",
        "/api/metrics",
        "/api/research",
        "/api/not-a-route",
        "/deep/link",
        "/asset.txt",
    ]
    first = legacy.RANKED_ATTEMPTS[0]
    paths.extend(
        [
            f"/api/approaches/{first['attempt_id']}",
            f"/api/approach-operations/{first['operation_id']}",
            "/api/approaches/not-present",
            "/api/approach-operations/not-present",
        ]
    )
    for path in paths:
        previous = old.get(path)
        current = new.get(path)
        assert current.status_code == previous.status_code, path
        assert current.headers["content-type"] == previous.headers["content-type"], path
        if "application/json" in current.headers["content-type"]:
            assert current.json() == previous.json(), path
        else:
            assert current.content == previous.content, path


def test_factory_instances_have_isolated_runtime_state(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok")
    settings = Settings(
        release_dir=legacy.RELEASE_DIR,
        frontend_dir=frontend,
        evaluation_global_limit=1,
        evaluation_client_limit=1,
    )
    first = create_app(settings, legacy.RELEASE)
    second = create_app(settings, legacy.RELEASE)
    assert first.state.release is not second.state.release
    assert first.state.runtime.evaluation_lock is not second.state.runtime.evaluation_lock
    assert (
        first.state.runtime.evaluation_limiter.admit("client", now=0)
        is None
    )
    assert (
        second.state.runtime.evaluation_limiter.admit("client", now=0)
        is None
    )


def test_factory_can_run_api_only_without_frontend():
    settings = Settings(release_dir=legacy.RELEASE_DIR, frontend_dir=None)
    client = TestClient(create_app(settings, legacy.RELEASE))
    assert client.get("/api/health").status_code == 200
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "application_unavailable"
