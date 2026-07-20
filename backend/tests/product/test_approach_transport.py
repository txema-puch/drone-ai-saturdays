from __future__ import annotations

import gzip
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from sadar.releases import archive as approach_transport
from sadar.releases import fetch as approach_fetch
from sadar.releases import hub_fetch
from sadar.releases.approach import load_release_directory


REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(
    os.environ.get("SADAR_APPROACH_RELEASE_DIR", REPO / ".artifacts/approach-release")
)
if not SOURCE.exists():
    from tests.product.test_approach_release import build_valid_release

    build_valid_release(SOURCE.parent, SOURCE.name)


def test_archive_is_deterministic_and_extracts_exact_release(tmp_path: Path):
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    digest, size = approach_transport.create_deterministic_archive(SOURCE, first)
    second_digest, second_size = approach_transport.create_deterministic_archive(SOURCE, second)
    assert (digest, size) == (second_digest, second_size)
    assert first.read_bytes() == second.read_bytes()

    target = tmp_path / "installed"
    manifest = approach_transport.extract_release_archive(
        first, target, expected_sha256=digest
    )
    assert manifest == load_release_directory(SOURCE)["manifest"]
    assert load_release_directory(target)["manifest"] == manifest


def test_digest_corruption_is_rejected_before_extraction(tmp_path: Path):
    archive = tmp_path / "release.tar.gz"
    digest, _ = approach_transport.create_deterministic_archive(SOURCE, archive)
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    with pytest.raises(approach_transport.ReleaseIntegrityError):
        approach_transport.extract_release_archive(
            archive, tmp_path / "target", expected_sha256=digest
        )
    assert not (tmp_path / "target").exists()


def test_non_file_and_extra_archive_members_are_rejected(tmp_path: Path):
    archive = tmp_path / "bad.tar.gz"
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                directory = tarfile.TarInfo("extra")
                directory.type = tarfile.DIRTYPE
                tar.addfile(directory)
    with pytest.raises(approach_transport.ReleaseFormatError):
        approach_transport.inspect_release_archive(archive)


def test_symlink_archive_path_is_rejected(tmp_path: Path):
    archive = tmp_path / "release.tar.gz"
    approach_transport.create_deterministic_archive(SOURCE, archive)
    link = tmp_path / "link.tar.gz"
    link.symlink_to(archive)
    with pytest.raises(approach_transport.ReleaseFormatError):
        approach_transport.inspect_release_archive(link)


def test_approach_fetch_rejects_model_mutable_and_wrong_dataset_paths(tmp_path: Path):
    revision = "a" * 40
    valid_url = (
        "https://huggingface.co/datasets/Txemapuch/sadar-analyst-console-release/resolve/"
        f"{revision}/{approach_fetch.ARCHIVE_NAME}"
    )
    base = {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": revision,
        "schema_version": 4,
        "url": valid_url,
    }
    wrong_urls = (
        valid_url.replace("/datasets/", "/"),
        valid_url.replace(f"/{revision}/", "/main/"),
        valid_url.replace("Txemapuch/", "Other/"),
        valid_url.replace(approach_fetch.ARCHIVE_NAME, "other.tar.gz"),
        f"{valid_url}?download=true",
        f"{valid_url}#fragment",
        valid_url.replace("https://", "https://token@"),
        valid_url.replace("huggingface.co", "example.com"),
    )
    for index, url in enumerate(wrong_urls):
        lock = tmp_path / f"bad-{index}.json"
        lock.write_text(json.dumps({**base, "url": url}), encoding="utf-8")
        with pytest.raises(hub_fetch.FetchError):
            approach_fetch.fetch_locked_release(
                lock_path=lock,
                destination=tmp_path / f"release-{index}",
                downloader=lambda *_args: pytest.fail("unsafe URL reached downloader"),
            )


def test_approach_fetch_rejects_unknown_repository_type():
    revision = "a" * 40
    record = {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": revision,
        "schema_version": 4,
        "url": (
            "https://huggingface.co/datasets/Txemapuch/"
            f"sadar-analyst-console-release/resolve/{revision}/{approach_fetch.ARCHIVE_NAME}"
        ),
    }
    with pytest.raises(hub_fetch.FetchError, match="repository type"):
        hub_fetch.validate_lock_record(
            record,
            expected_schema_version=4,
            repo_type="space",  # type: ignore[arg-type]
        )
