from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from backend.serve import approach_transport
from backend.serve.approach_release import load_release_directory


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "backend/models/sadar_approach_v3"


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
