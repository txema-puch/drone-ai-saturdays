from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from sadar_research.trajectory_anomaly.releases import schema
from sadar_research.trajectory_anomaly.releases import training_artifacts as artifacts


def _fixture(tmp_path: Path, *, extra_member: bool = False) -> tuple[Path, dict[str, object]]:
    payloads = {
        "knn_train_summary.npy": b"knn-fixture",
        "lstm_ae_best.pt": b"model-fixture",
        "scaler.joblib": b"scaler-fixture",
    }
    files = [
        {
            "bytes": len(data),
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(payloads.items())
    ]
    manifest = schema.canonical_json_bytes({
        "files": files,
        "phase": "train",
        "research_track": artifacts.RESEARCH_TRACK,
        "schema_version": artifacts.MANIFEST_SCHEMA,
        "source_commit": "a" * 40,
    })
    archive_path = tmp_path / artifacts.ARCHIVE_NAME
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                members = {artifacts.MANIFEST_NAME: manifest, **payloads}
                if extra_member:
                    members["unexpected.txt"] = b"no"
                for name, data in members.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(data))
    lock = artifacts.validate_lock({
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "files": files,
        "research_track": artifacts.RESEARCH_TRACK,
        "revision": "b" * 40,
        "schema_version": artifacts.LOCK_SCHEMA,
        "url": (
            "https://huggingface.co/Txemapuch/sadar-demo-release/resolve/"
            + "b" * 40
            + "/research/trajectory-anomaly/phase6/"
            + artifacts.ARCHIVE_NAME
        ),
    })
    return archive_path, lock


def test_repository_lock_is_valid_and_pinned():
    lock = artifacts.read_lock(
        "backend/research/src/sadar_research/trajectory_anomaly/releases/"
        "phase6_training_artifacts.lock.json"
    )

    assert lock["revision"] == "fd21b357b7e24a8f1f3f1c8de6c5927cedaab7ad"
    assert lock["archive_sha256"] == (
        "1bc57e16c03773875335bdf38b94e3c8377250f0b933dfe5bcf149a8f1b946d0"
    )


def test_install_archive_verifies_and_installs_only_allowlisted_files(tmp_path: Path):
    archive, lock = _fixture(tmp_path)
    destination = tmp_path / "installed"

    manifest = artifacts.install_archive(archive, destination, lock=lock)

    assert manifest["source_commit"] == "a" * 40
    assert {path.name for path in destination.iterdir()} == {
        artifacts.MANIFEST_NAME,
        *artifacts.ALLOWED_FILES,
    }


def test_install_archive_rejects_digest_and_layout_drift(tmp_path: Path):
    archive, lock = _fixture(tmp_path)
    wrong_digest = {**lock, "archive_sha256": "0" * 64}
    with pytest.raises(artifacts.TrainingArtifactError, match="digest mismatch"):
        artifacts.install_archive(archive, tmp_path / "digest", lock=wrong_digest)

    other = tmp_path / "other"
    other.mkdir()
    malformed, malformed_lock = _fixture(other, extra_member=True)
    with pytest.raises(artifacts.TrainingArtifactError, match="layout"):
        artifacts.install_archive(malformed, tmp_path / "layout", lock=malformed_lock)


def test_fetch_uses_bounded_download_and_refuses_existing_destination(tmp_path: Path):
    archive, lock = _fixture(tmp_path)
    lock_path = tmp_path / "lock.json"
    lock_path.write_bytes(schema.canonical_json_bytes({
        **lock,
        "files": list(lock["files"]),
    }))
    observed: dict[str, object] = {}

    def downloader(url: str, destination: Path, *, max_archive_bytes: int) -> None:
        observed.update(url=url, max_archive_bytes=max_archive_bytes)
        destination.write_bytes(archive.read_bytes())

    destination = tmp_path / "fetched"
    artifacts.fetch_locked_training_artifacts(
        lock_path=lock_path,
        destination=destination,
        downloader=downloader,
    )
    assert observed == {
        "url": lock["url"],
        "max_archive_bytes": artifacts.MAX_ARCHIVE_BYTES,
    }

    with pytest.raises(artifacts.TrainingArtifactError, match="destination"):
        artifacts.fetch_locked_training_artifacts(
            lock_path=lock_path,
            destination=destination,
            downloader=downloader,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda lock: {**lock, "url": str(lock["url"]).replace("https://", "http://")}, "storage"),
        (lambda lock: {**lock, "revision": "main"}, "immutable"),
        (lambda lock: {**lock, "unexpected": True}, "schema"),
        (lambda lock: {**lock, "research_track": "other"}, "identity"),
        (
            lambda lock: {
                **lock,
                "files": [*list(lock["files"])[:-1], list(lock["files"])[0]],
            },
            "file",
        ),
    ),
)
def test_lock_validation_rejects_mutable_or_ambiguous_records(tmp_path: Path, mutation, message):
    _archive, lock = _fixture(tmp_path)
    mutable_lock = {**lock, "files": list(lock["files"])}

    with pytest.raises(artifacts.TrainingArtifactError, match=message):
        artifacts.validate_lock(mutation(mutable_lock))


def test_manifest_validation_rejects_identity_and_file_drift(tmp_path: Path):
    _archive, lock = _fixture(tmp_path)
    expected = lock["files"]
    manifest = {
        "files": list(expected),
        "phase": "eval",
        "research_track": artifacts.RESEARCH_TRACK,
        "schema_version": artifacts.MANIFEST_SCHEMA,
        "source_commit": "a" * 40,
    }

    with pytest.raises(artifacts.TrainingArtifactError, match="identity"):
        artifacts._manifest(manifest, expected_files=expected)

    manifest["phase"] = "train"
    manifest["files"] = list(expected)[:-1]
    with pytest.raises(artifacts.TrainingArtifactError, match="file list"):
        artifacts._manifest(manifest, expected_files=expected)


def test_install_rejects_symbolic_link_archive_and_destination(tmp_path: Path):
    archive, lock = _fixture(tmp_path)
    archive_link = tmp_path / "archive-link.tar.gz"
    archive_link.symlink_to(archive)

    with pytest.raises(artifacts.TrainingArtifactError, match="regular file"):
        artifacts.install_archive(archive_link, tmp_path / "from-link", lock=lock)

    destination = tmp_path / "destination-link"
    destination.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(artifacts.TrainingArtifactError, match="destination"):
        artifacts.install_archive(archive, destination, lock=lock)


def test_cli_failure_is_bounded_and_does_not_create_destination(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    lock_path = tmp_path / "lock.json"
    destination = tmp_path / "destination"

    def fail(**_kwargs):
        raise artifacts.TrainingArtifactError("x" * 1_000)

    monkeypatch.setattr(artifacts, "fetch_locked_training_artifacts", fail)

    assert artifacts.main(["--lock", str(lock_path), "--destination", str(destination)]) == 1
    error = capsys.readouterr().err
    assert error.startswith("training-artifact fetch failed: ")
    assert len(error.removesuffix("\n").split(": ", 1)[1]) == 500
    assert not destination.exists()
