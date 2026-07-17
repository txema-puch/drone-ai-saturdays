from __future__ import annotations

import hashlib
import json
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
RELEASE = load_release_directory(RELEASE_DIR)
PRE_RESTRUCTURE_CONTRACT = (
    Path(__file__).parent / "fixtures" / "pre_restructure_read_contract.json"
)


def _settings(frontend: Path, **kwargs) -> Settings:
    values = {
        "release_dir": RELEASE_DIR,
        "frontend_dir": frontend,
        "evaluation_global_limit": 100,
        "evaluation_client_limit": 100,
    }
    values.update(kwargs)
    return Settings(**values)


def test_factory_preserves_pre_restructure_read_contract(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    (frontend / "asset.txt").write_text("asset")
    client = TestClient(create_app(_settings(frontend), RELEASE))
    contract = json.loads(PRE_RESTRUCTURE_CONTRACT.read_text())

    assert contract["source"]["commit"] == "2256b3b07a751a5c458d742a159f1d89c1b31503"
    for expected in contract["responses"]:
        response = client.get(expected["path"])
        canonical = json.dumps(
            response.json(), sort_keys=True, separators=(",", ":")
        ).encode()
        assert response.status_code == expected["status_code"], expected["path"]
        assert response.headers["content-type"] == expected["content_type"], expected[
            "path"
        ]
        assert hashlib.sha256(canonical).hexdigest() == expected["sha256"], expected[
            "path"
        ]


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
