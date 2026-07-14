from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.serve import approach_app


client = TestClient(approach_app.app)


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
