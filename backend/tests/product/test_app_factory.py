from __future__ import annotations

import os
import copy
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
    assert health["demo_attempts"] == 14
    assert health["demo_operations"] == 14
    assert sum(health["demo_status_counts"].values()) == 14
    assert sum(health["demo_outcome_counts"].values()) == 14
    assert health["evaluation_data_handling"] == "ephemeral_not_retained"
    assert health["source_commit"] == "unknown"
    assert health["qualification"] == "not_qualified_no_independent_labels_or_fresh_holdout"
    queue = client.get("/api/approaches").json()
    assert queue and queue[0]["attempt_id"].startswith("syn-a-")
    assert all(item["data_origin"] == "synthetic" for item in queue)
    assert all(item["scenario_title"] and item["teaching_goal"] for item in queue)
    detail = client.get(f"/api/approaches/{queue[0]['attempt_id']}").json()
    assert detail["demo_clock"] is True
    assert detail["landing_outcome"] == queue[0]["landing_outcome"]


def test_real_aggregate_counts_cannot_change_demo_queue_counts(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok")
    changed = copy.deepcopy(RELEASE)
    changed["aggregate_results"]["cohorts"][0]["attempts"] = 99_999
    client = TestClient(create_app(_settings(frontend), changed))

    health = client.get("/api/health").json()
    assert health["demo_attempts"] == 14
    assert sum(health["demo_status_counts"].values()) == 14
    assert len(client.get("/api/approaches?limit=5000").json()) == 14


def test_evidence_is_the_canonical_aggregate_endpoint(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok")
    client = TestClient(create_app(_settings(frontend), RELEASE))

    evidence = client.get("/api/evidence")
    assert evidence.status_code == 200
    assert evidence.json() == RELEASE["aggregate_results"]
    assert client.get("/api/metrics").json() == evidence.json()
    deprecated = client.get("/api/research", follow_redirects=False)
    assert deprecated.status_code == 307
    assert deprecated.headers["location"] == "/api/evidence"
    assert deprecated.headers["deprecation"] == "true"
    assert deprecated.headers["link"] == '</api/evidence>; rel="successor-version"'
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/research"]["get"]["deprecated"] is True
    assert set(paths["/api/research"]["get"]["responses"]) == {"307"}
    evidence_schema = paths["/api/evidence"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert evidence_schema["$ref"].endswith("/ResearchEvidenceResponse")


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
