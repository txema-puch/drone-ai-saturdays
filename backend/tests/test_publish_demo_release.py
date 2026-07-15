from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.scripts import publish_demo_release as publisher
from backend.serve import release


MANIFEST_PAYLOAD = {
    "schema_version": release.RELEASE_SCHEMA_VERSION,
    "source": {"commit": "abc123", "inputs": {}},
    "scoring_contract": {"T": 260, "threshold": 0.222, "step_threshold": 0.5},
    "online_input_contract": {
        "input_schema_version": "opensky_raw_v1",
        "derivation_contract_version": "derivations_v1",
        "preprocessing_contract_version": "preprocessing_v1",
        "units": {
            "time": "unix_seconds",
            "lat": "degrees_wgs84",
            "lon": "degrees_wgs84",
            "baroaltitude": "metres",
            "velocity": "metres_per_second",
            "heading": "degrees_clockwise_from_true_north",
            "vertrate": "metres_per_second",
            "onground": "boolean",
        },
    },
}
REVISION = "a" * 40
URL = f"https://huggingface.co/sadar/demo/resolve/{REVISION}/{publisher.DEFAULT_ARTIFACT_NAME}"
NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)


def make_release(base: Path) -> dict:
    base.mkdir()
    for index, relative in enumerate(release.REQUIRED_RELEASE_FILES):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-{index}-{relative}".encode())
    return release.write_release_manifest(base, MANIFEST_PAYLOAD)


def setup_transaction(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    repository = tmp_path / "repo"
    repository.mkdir()
    lock = repository / "backend" / "serve" / publisher.LOCK_NAME
    lock.parent.mkdir(parents=True)
    manifest = make_release(tmp_path / "release")
    lock.write_bytes(b'{"prior":"lock"}\n')
    return repository, tmp_path / "release", lock, manifest


def successful_adapters(remote: Path):
    def upload(archive: Path) -> publisher.UploadedArtifact:
        shutil.copyfile(archive, remote)
        return publisher.UploadedArtifact(URL, REVISION)

    def download(url: str, destination: Path) -> None:
        assert url == URL
        shutil.copyfile(remote, destination)

    return upload, download


def publish(repository: Path, source: Path, lock: Path, uploader, downloader):
    return publisher.publish_release(
        release_dir=source,
        lock_path=lock,
        repository_root=repository,
        uploader=uploader,
        downloader=downloader,
        clean_tree_check=lambda _root: None,
        clock=lambda: NOW,
    )


def test_success_captures_immutable_revision_and_atomically_replaces_lock(tmp_path: Path):
    repository, source, lock, manifest = setup_transaction(tmp_path)
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)

    record = publish(repository, source, lock, uploader, downloader)

    assert record == json.loads(lock.read_text())
    assert record == {
        "archive_sha256": release.sha256_file(remote, limit=release.MAX_ARCHIVE_BYTES)[0],
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": manifest["release_id"],
        "revision": REVISION,
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "url": URL,
    }
    assert lock.stat().st_mode & 0o777 == 0o644
    assert not list(lock.parent.glob(f".{publisher.LOCK_NAME}.*.tmp"))


def test_clean_tree_gate_runs_before_packaging_or_upload_and_preserves_lock(tmp_path: Path, monkeypatch):
    repository, source, lock, _ = setup_transaction(tmp_path)
    prior = lock.read_bytes()
    calls: list[str] = []

    def dirty(_root: Path) -> None:
        calls.append("clean-check")
        raise publisher.PublicationError("dirty")

    monkeypatch.setattr(
        release,
        "create_deterministic_archive",
        lambda *_args, **_kwargs: pytest.fail("packaging must not run"),
    )
    with pytest.raises(publisher.PublicationError, match="dirty"):
        publisher.publish_release(
            release_dir=source,
            lock_path=lock,
            repository_root=repository,
            uploader=lambda _path: pytest.fail("upload must not run"),
            downloader=lambda _url, _path: pytest.fail("download must not run"),
            clean_tree_check=dirty,
        )
    assert calls == ["clean-check"]
    assert lock.read_bytes() == prior


@pytest.mark.parametrize("failure", ["upload", "redownload", "digest", "revision", "url"])
def test_failed_upload_or_verification_never_mutates_prior_lock(tmp_path: Path, failure: str):
    repository, source, lock, _ = setup_transaction(tmp_path)
    prior = lock.read_bytes()
    remote = tmp_path / "remote.tar.gz"

    def upload(archive: Path) -> publisher.UploadedArtifact:
        if failure == "upload":
            raise RuntimeError("upload unavailable")
        shutil.copyfile(archive, remote)
        if failure == "revision":
            return publisher.UploadedArtifact(URL, "main")
        if failure == "url":
            return publisher.UploadedArtifact("https://example.test/archive.tar.gz", REVISION)
        return publisher.UploadedArtifact(URL, REVISION)

    def download(_url: str, destination: Path) -> None:
        if failure == "redownload":
            raise publisher.PublicationError("download unavailable")
        shutil.copyfile(remote, destination)
        if failure == "digest":
            destination.write_bytes(destination.read_bytes() + b"corrupt")

    with pytest.raises(Exception):
        publish(repository, source, lock, upload, download)
    assert lock.read_bytes() == prior


def test_atomic_replace_failure_preserves_prior_lock_and_cleans_temp(tmp_path: Path, monkeypatch):
    repository, source, lock, _ = setup_transaction(tmp_path)
    prior = lock.read_bytes()
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)
    real_replace = publisher.os.replace

    def fail_lock_replace(source_path, destination_path):
        if Path(destination_path) == lock:
            raise OSError("simulated lock failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(publisher.os, "replace", fail_lock_replace)
    with pytest.raises(publisher.PublicationError, match="atomically replace"):
        publish(repository, source, lock, uploader, downloader)
    assert lock.read_bytes() == prior
    assert not list(lock.parent.glob(f".{publisher.LOCK_NAME}.*.tmp"))


def test_archive_input_is_deterministic_across_transactions(tmp_path: Path):
    repository, source, lock, _ = setup_transaction(tmp_path)
    observed: list[bytes] = []

    def upload(archive: Path) -> publisher.UploadedArtifact:
        observed.append(archive.read_bytes())
        return publisher.UploadedArtifact(URL, REVISION)

    def download(_url: str, destination: Path) -> None:
        destination.write_bytes(observed[-1])

    first = publish(repository, source, lock, upload, download)
    second = publish(repository, source, lock, upload, download)
    assert observed[0] == observed[1]
    assert first == second


def test_actual_clean_tree_checker_detects_untracked_content(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    publisher.assert_clean_git_tree(repository)
    (repository / "untracked.txt").write_text("dirty")
    with pytest.raises(publisher.PublicationError, match="must be clean"):
        publisher.assert_clean_git_tree(repository)


def test_lock_path_must_be_inside_repository_with_fixed_basename(tmp_path: Path):
    repository, source, lock, _ = setup_transaction(tmp_path)
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)
    for destination in (tmp_path / publisher.LOCK_NAME, lock.with_name("other.json")):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with pytest.raises(publisher.PublicationError, match="lock destination"):
            publish(repository, source, destination, uploader, downloader)


def test_existing_lock_symlink_is_rejected_without_touching_target(tmp_path: Path):
    repository, source, lock, _ = setup_transaction(tmp_path)
    target = tmp_path / "outside.json"
    target.write_bytes(b"outside\n")
    lock.unlink()
    lock.symlink_to(target)
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)

    with pytest.raises(publisher.PublicationError, match="regular file"):
        publish(repository, source, lock, uploader, downloader)
    assert target.read_bytes() == b"outside\n"


def test_lock_record_rejects_malformed_json_contract_values():
    valid = {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": REVISION,
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "url": URL,
    }
    assert publisher.validate_lock_record(valid) == valid
    mutations = {
        "archive_sha256": "B" * 64,
        "published_at": "2026-07-14T12:00:00+01:00",
        "release_id": "../escape",
        "revision": "main",
        "schema_version": True,
        "url": f"https://token@huggingface.co/sadar/demo/resolve/{REVISION}/bundle.tar.gz",
    }
    for field, value in mutations.items():
        malformed = dict(valid)
        malformed[field] = value
        with pytest.raises(publisher.PublicationError):
            publisher.validate_lock_record(malformed)

    malformed_port = dict(valid)
    malformed_port["url"] = f"https://huggingface.co:bad/sadar/demo/resolve/{REVISION}/bundle.tar.gz"
    with pytest.raises(publisher.PublicationError):
        publisher.validate_lock_record(malformed_port)

    for malformed_url in (
        f"https://huggingface.co/sadar/demo/resolve/{REVISION}/folder/bundle.tar.gz",
        f"https://huggingface.co/sadar//demo/resolve/{REVISION}/bundle.tar.gz",
        f"https://huggingface.co/sadar%2Fother/demo/resolve/{REVISION}/bundle.tar.gz",
    ):
        malformed = dict(valid)
        malformed["url"] = malformed_url
        with pytest.raises(publisher.PublicationError):
            publisher.validate_lock_record(malformed)


def test_publisher_and_fetcher_accept_the_same_lock_contract():
    from backend.scripts import fetch_demo_bundle as fetcher

    record = {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": REVISION,
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "url": URL,
    }
    assert fetcher.validate_lock_record(publisher.validate_lock_record(record)) == record


@pytest.mark.parametrize("declared", [None, "4"])
def test_public_downloader_enforces_archive_limit_and_removes_partial_file(
    tmp_path: Path,
    monkeypatch,
    declared: str | None,
):
    class Response:
        headers = {} if declared is None else {"Content-Length": declared}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            return b"four"

    monkeypatch.setattr(publisher.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(release, "MAX_ARCHIVE_BYTES", 3)
    destination = tmp_path / "archive.tar.gz"
    with pytest.raises(publisher.PublicationError, match="byte limit"):
        publisher.download_public_artifact(URL, destination)
    assert not destination.exists()


def test_secret_is_redacted_and_never_written_to_lock(tmp_path: Path):
    secret = "hf_sensitive-token"
    assert secret not in publisher._safe_error_message(RuntimeError(f"failure {secret}"), secret=secret)

    repository, source, lock, _ = setup_transaction(tmp_path)
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)
    publish(repository, source, lock, uploader, downloader)
    assert secret.encode() not in lock.read_bytes()


def test_relative_paths_are_resolved_from_repository_root(tmp_path: Path, monkeypatch):
    repository, source, lock, _ = setup_transaction(tmp_path)
    relative_source = repository / "release"
    shutil.copytree(source, relative_source)
    remote = tmp_path / "remote.tar.gz"
    uploader, downloader = successful_adapters(remote)
    monkeypatch.chdir(tmp_path)

    record = publisher.publish_release(
        release_dir="release",
        lock_path=f"backend/serve/{publisher.LOCK_NAME}",
        repository_root=repository,
        uploader=uploader,
        downloader=downloader,
        clean_tree_check=lambda _root: None,
        clock=lambda: NOW,
    )
    assert json.loads(lock.read_text()) == record
