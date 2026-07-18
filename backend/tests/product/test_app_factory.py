from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from sadar.api.factory import create_app
from sadar.api.settings import Settings
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
RELEASE_DIR = Path(
    os.environ.get(
        "SADAR_APPROACH_RELEASE_DIR",
        REPO / ".artifacts/approach-release",
    )
)
if not RELEASE_DIR.exists():
    from tests.product.test_approach_release import build_valid_release

    build_valid_release(RELEASE_DIR.parent, RELEASE_DIR.name)
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


def test_factory_serves_synthetic_queue_detail_and_origin_health(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    (frontend / "asset.txt").write_text("asset")
    client = TestClient(create_app(_settings(frontend), RELEASE))
    health = client.get("/api/health").json()
    assert health["schema_version"] == 4
    assert health["demo_data_origin"] == "synthetic"
    assert health["research_data_origin"] == "aggregate_real"
    queue = client.get("/api/approaches").json()
    assert queue and queue[0]["attempt_id"].startswith("syn-a-")
    detail = client.get(f"/api/approaches/{queue[0]['attempt_id']}")
    assert detail.status_code == 200


def test_factory_instances_have_isolated_runtime_state(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok")
    settings = _settings(frontend, evaluation_global_limit=1, evaluation_client_limit=1)
    first = create_app(settings, RELEASE)
    second = create_app(settings, RELEASE)
    assert first.state.release is not second.state.release
    assert first.state.runtime.evaluation_slot is not second.state.runtime.evaluation_slot
    assert first.state.runtime.evaluation_limiter.admit("client", now=0) is None
    assert second.state.runtime.evaluation_limiter.admit("client", now=0) is None


def test_factory_can_run_api_only_without_frontend():
    settings = Settings(release_dir=RELEASE_DIR, frontend_dir=None)
    client = TestClient(create_app(settings, RELEASE))
    assert client.get("/api/health").status_code == 200
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "application_unavailable"
