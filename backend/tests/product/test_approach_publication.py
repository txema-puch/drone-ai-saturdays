from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sadar.pipelines import publish_release as publish_approach_release
from sadar.releases import fetch as fetch_approach_release
from sadar.releases.hub_publish import UploadedArtifact
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(
    os.environ.get("SADAR_APPROACH_RELEASE_DIR", REPO / "backend/models/sadar_approach_v3")
)
REVISION = "a" * 40
URL = (
    "https://huggingface.co/Txemapuch/sadar-demo-release/resolve/"
    f"{REVISION}/{publish_approach_release.ARTIFACT_NAME}"
)


def test_schema_v3_publication_lock_and_anonymous_fetch_round_trip(tmp_path: Path):
    repository = tmp_path / "repo"
    lock = repository / "backend/serve" / publish_approach_release.LOCK_NAME
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
    assert record["schema_version"] == 3

    destination = tmp_path / "runtime/release"
    installed = fetch_approach_release.fetch_locked_release(
        lock_path=lock,
        destination=destination,
        downloader=download,
    )
    assert installed == load_release_directory(SOURCE)["manifest"]
    assert load_release_directory(destination)["manifest"] == installed
