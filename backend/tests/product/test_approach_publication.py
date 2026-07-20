from __future__ import annotations

import json
import os
import shutil
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sadar.pipelines import publish_release as publish_approach_release
from sadar.releases import fetch as fetch_approach_release
from sadar.releases import hub_publish
from sadar.releases.hub_publish import PublicationError, UploadedArtifact
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(
    os.environ.get("SADAR_APPROACH_RELEASE_DIR", REPO / ".artifacts/approach-release")
)
if not SOURCE.exists():
    from tests.product.test_approach_release import build_valid_release

    build_valid_release(SOURCE.parent, SOURCE.name)
REVISION = "a" * 40
URL = (
    "https://huggingface.co/datasets/Txemapuch/sadar-analyst-console-release/resolve/"
    f"{REVISION}/{publish_approach_release.ARTIFACT_NAME}"
)


def test_schema_v4_publication_lock_and_anonymous_fetch_round_trip(tmp_path: Path):
    repository = tmp_path / "repo"
    lock = repository / "backend/src/sadar/releases" / publish_approach_release.LOCK_NAME
    lock.parent.mkdir(parents=True)
    remote = tmp_path / "remote.tar.gz"

    def upload(archive: Path) -> UploadedArtifact:
        shutil.copyfile(archive, remote)
        return UploadedArtifact(url=URL, revision=REVISION)

    def download(_url: str, destination: Path) -> None:
        shutil.copyfile(remote, destination)

    record = publish_approach_release.publish_release(
        release_dir=SOURCE,
        lock_path=lock,
        repository_root=repository,
        uploader=upload,
        downloader=download,
        clean_tree_check=lambda _root: None,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    assert json.loads(lock.read_text()) == record
    assert record["schema_version"] == 4

    destination = tmp_path / "runtime/release"
    installed = fetch_approach_release.fetch_locked_release(
        lock_path=lock,
        destination=destination,
        downloader=download,
    )
    assert installed == load_release_directory(SOURCE)["manifest"]
    assert load_release_directory(destination)["manifest"] == installed


def _valid_lock(url: str = URL) -> dict[str, object]:
    return {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": REVISION,
        "schema_version": 4,
        "url": url,
    }


def test_approach_publication_accepts_only_the_frozen_dataset_artifact_url():
    assert hub_publish.validate_lock_record(
        _valid_lock(),
        expected_schema_version=4,
        repo_type="dataset",
        expected_repo_id=publish_approach_release.REPOSITORY_ID,
        expected_artifact_name=publish_approach_release.ARTIFACT_NAME,
    )["url"] == URL


def test_approach_publication_rejects_unknown_repository_type():
    with pytest.raises(PublicationError, match="repository type"):
        hub_publish.validate_lock_record(
            _valid_lock(),
            expected_schema_version=4,
            repo_type="space",  # type: ignore[arg-type]
        )


def test_approach_publication_rejects_mutable_or_wrong_artifact_urls():
    wrong_urls = (
        URL.replace("/datasets/", "/"),
        URL.replace(f"/{REVISION}/", "/main/"),
        URL.replace("Txemapuch/", "SomebodyElse/"),
        URL.replace("sadar-analyst-console-release", "other-release"),
        URL.replace(publish_approach_release.ARTIFACT_NAME, "other.tar.gz"),
        f"{URL}?download=true",
        f"{URL}#fragment",
        URL.replace("https://", "https://token@"),
        URL.replace("huggingface.co", "example.com"),
    )
    for url in wrong_urls:
        with pytest.raises(PublicationError):
            hub_publish.validate_lock_record(
                _valid_lock(url),
                expected_schema_version=4,
                repo_type="dataset",
                expected_repo_id=publish_approach_release.REPOSITORY_ID,
                expected_artifact_name=publish_approach_release.ARTIFACT_NAME,
            )


def test_approach_cli_requires_dataset_repo_type(capsys):
    common = [
        "--release-dir", str(SOURCE),
        "--lock", "unused.json",
        "--repository-root", str(REPO),
        "--hf-repo-id", publish_approach_release.REPOSITORY_ID,
        "--repo-type", "model",
    ]
    assert publish_approach_release.main(common) == 1
    assert "repo type must be dataset" in capsys.readouterr().err


def test_token_resolution_prefers_environment_then_hub_login(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "environment-token")
    assert hub_publish.resolve_hugging_face_token() == "environment-token"

    monkeypatch.delenv("HF_TOKEN")
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(get_token=lambda: "stored-token"),
    )
    assert hub_publish.resolve_hugging_face_token() == "stored-token"


def test_hugging_face_adapter_uploads_to_the_dataset_repository(tmp_path: Path, monkeypatch):
    observed: dict[str, object] = {}

    class FakeApi:
        def __init__(self, *, token: str):
            observed["token"] = token

        def upload_file(self, **kwargs):
            observed.update(kwargs)
            return types.SimpleNamespace(oid=REVISION)

    def fake_url(**kwargs):
        observed["url_kwargs"] = kwargs
        return URL

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(HfApi=FakeApi, hf_hub_url=fake_url),
    )
    archive = tmp_path / publish_approach_release.ARTIFACT_NAME
    archive.write_bytes(b"archive")
    uploader = hub_publish.hugging_face_uploader(
        repo_id=publish_approach_release.REPOSITORY_ID,
        artifact_name=publish_approach_release.ARTIFACT_NAME,
        token="secret",
        repo_type="dataset",
    )

    uploaded = uploader(archive)

    assert uploaded == UploadedArtifact(url=URL, revision=REVISION)
    assert observed["repo_type"] == "dataset"
    assert observed["url_kwargs"] == {
        "repo_id": publish_approach_release.REPOSITORY_ID,
        "filename": publish_approach_release.ARTIFACT_NAME,
        "repo_type": "dataset",
        "revision": REVISION,
    }
