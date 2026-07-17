from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sadar_research.trajectory_anomaly.releases import fetch as fetcher
from sadar_research.trajectory_anomaly.releases import schema as release
from sadar.releases import hub_fetch


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
URL = f"https://huggingface.co/sadar/demo/resolve/{REVISION}/sadar-demo-bundle.tar.gz"


def make_release(base: Path) -> dict:
    base.mkdir()
    for index, relative in enumerate(release.REQUIRED_RELEASE_FILES):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-{index}-{relative}".encode())
    return release.write_release_manifest(base, MANIFEST_PAYLOAD)


def make_fixture(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source"
    manifest = make_release(source)
    archive = tmp_path / "bundle.tar.gz"
    archive_sha256, _ = release.create_deterministic_archive(source, archive)
    lock = {
        "archive_sha256": archive_sha256,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": manifest["release_id"],
        "revision": REVISION,
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "url": URL,
    }
    lock_path = tmp_path / "demo_bundle.lock.json"
    lock_path.write_bytes(release.canonical_json_bytes(lock) + b"\n")
    return archive, lock_path, manifest, lock


def copying_downloader(archive: Path, observed: list[str] | None = None):
    def download(url: str, destination: Path) -> None:
        if observed is not None:
            observed.append(url)
        shutil.copyfile(archive, destination)

    return download


def test_valid_lock_downloads_anonymously_and_installs_exact_release(tmp_path: Path):
    archive, lock_path, manifest, _ = make_fixture(tmp_path)
    destination = tmp_path / "runtime" / "release"
    observed: list[str] = []

    installed = fetcher.fetch_locked_release(
        lock_path=lock_path,
        destination=destination,
        downloader=copying_downloader(archive, observed),
    )

    assert installed == manifest
    assert observed == [URL]
    assert release.validate_release_directory(destination) == manifest
    assert not list(destination.parent.glob(".sadar-fetch-*"))


@pytest.mark.parametrize("failure", ["download", "hash", "release_id"])
def test_download_and_verification_failures_leave_no_partial_destination(tmp_path: Path, failure: str):
    archive, lock_path, _, lock = make_fixture(tmp_path)
    destination = tmp_path / "runtime" / "release"
    if failure == "hash":
        lock["archive_sha256"] = "b" * 64
        lock_path.write_bytes(release.canonical_json_bytes(lock))
    elif failure == "release_id":
        lock["release_id"] = "f" * 20
        lock_path.write_bytes(release.canonical_json_bytes(lock))

    def download(_url: str, target: Path) -> None:
        target.write_bytes(b"partial")
        if failure == "download":
            raise fetcher.FetchError("network failed")
        shutil.copyfile(archive, target)

    with pytest.raises(fetcher.FetchError):
        fetcher.fetch_locked_release(
            lock_path=lock_path,
            destination=destination,
            downloader=download,
        )
    assert not destination.exists()
    assert not list(destination.parent.glob(".sadar-fetch-*"))


def test_post_extraction_provenance_failure_removes_installed_tree(tmp_path: Path, monkeypatch):
    archive, lock_path, manifest, _ = make_fixture(tmp_path)
    destination = tmp_path / "runtime" / "release"

    def mismatched_extract(_archive: Path, target: Path, *, expected_sha256: str):
        assert expected_sha256
        target.mkdir()
        (target / "partial").write_text("must be removed")
        return {**manifest, "release_id": "e" * 20}

    monkeypatch.setattr(release, "extract_release_archive", mismatched_extract)
    with pytest.raises(fetcher.FetchError, match="release ID mismatch"):
        fetcher.fetch_locked_release(
            lock_path=lock_path,
            destination=destination,
            downloader=copying_downloader(archive),
        )
    assert not destination.exists()


def test_concurrent_destination_winner_is_not_deleted(tmp_path: Path, monkeypatch):
    archive, lock_path, _, _ = make_fixture(tmp_path)
    destination = tmp_path / "runtime" / "release"

    def concurrent_winner(_archive: Path, target: Path, *, expected_sha256: str):
        assert expected_sha256
        target.mkdir()
        (target / "winner").write_text("keep")
        raise release.ReleaseFormatError("target already exists")

    monkeypatch.setattr(release, "extract_release_archive", concurrent_winner)
    with pytest.raises(fetcher.FetchError, match="verification"):
        fetcher.fetch_locked_release(
            lock_path=lock_path,
            destination=destination,
            downloader=copying_downloader(archive),
        )
    assert (destination / "winner").read_text() == "keep"


@pytest.mark.parametrize("existing_kind", ["file", "directory"])
def test_existing_destination_is_rejected_without_mutation(tmp_path: Path, existing_kind: str):
    archive, lock_path, _, _ = make_fixture(tmp_path)
    destination = tmp_path / "runtime-release"
    if existing_kind == "file":
        destination.write_text("keep")
    else:
        destination.mkdir()
        (destination / "keep").write_text("keep")

    with pytest.raises(fetcher.FetchError, match="must not already exist"):
        fetcher.fetch_locked_release(
            lock_path=lock_path,
            destination=destination,
            downloader=copying_downloader(archive),
        )
    if existing_kind == "file":
        assert destination.read_text() == "keep"
    else:
        assert (destination / "keep").read_text() == "keep"


def test_symbolic_link_lock_and_destination_ancestor_are_rejected(tmp_path: Path):
    archive, lock_path, _, _ = make_fixture(tmp_path)
    lock_link = tmp_path / "lock-link.json"
    lock_link.symlink_to(lock_path)
    with pytest.raises(fetcher.FetchError, match="cannot open"):
        fetcher.read_lock(lock_link)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(fetcher.FetchError, match="symbolic-link ancestors"):
        fetcher.fetch_locked_release(
            lock_path=lock_path,
            destination=parent_link / "release",
            downloader=copying_downloader(archive),
        )
    assert not (real_parent / "release").exists()


def test_lock_reader_rejects_duplicate_keys_extra_fields_and_byte_excess(tmp_path: Path, monkeypatch):
    path = tmp_path / "lock.json"
    path.write_text('{"url":"a","url":"b"}')
    with pytest.raises(fetcher.FetchError, match="malformed"):
        fetcher.read_lock(path)

    _, valid_path, _, lock = make_fixture(tmp_path / "valid")
    lock["extra"] = True
    valid_path.write_bytes(release.canonical_json_bytes(lock))
    with pytest.raises(fetcher.FetchError, match="exactly"):
        fetcher.read_lock(valid_path)

    monkeypatch.setattr("sadar.releases.hub_fetch.MAX_LOCK_BYTES", 8)
    with pytest.raises(fetcher.FetchError, match="byte limit"):
        fetcher.read_lock(valid_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("archive_sha256", "B" * 64),
        ("published_at", "2026-07-14T12:00:00+01:00"),
        ("release_id", "../escape"),
        ("revision", "main"),
        ("schema_version", True),
        ("url", "http://huggingface.co/sadar/demo/archive.tar.gz"),
        ("url", f"https://token@huggingface.co/sadar/demo/resolve/{REVISION}/bundle.tar.gz"),
        ("url", f"https://huggingface.co/sadar/demo/resolve/{REVISION}/folder/bundle.tar.gz"),
        ("url", f"https://huggingface.co/sadar//demo/resolve/{REVISION}/bundle.tar.gz"),
        ("url", f"https://huggingface.co:bad/sadar/demo/resolve/{REVISION}/bundle.tar.gz"),
    ],
)
def test_lock_contract_rejects_unsafe_or_mutable_values(field: str, value: object):
    valid = {
        "archive_sha256": "b" * 64,
        "published_at": "2026-07-14T12:00:00Z",
        "release_id": "c" * 20,
        "revision": REVISION,
        "schema_version": release.RELEASE_SCHEMA_VERSION,
        "url": URL,
    }
    valid[field] = value
    with pytest.raises(fetcher.FetchError):
        fetcher.validate_lock_record(valid)


@pytest.mark.parametrize("mode", ["declared_too_large", "stream_too_large", "length_mismatch"])
def test_public_downloader_enforces_declared_and_actual_byte_bounds(
    tmp_path: Path,
    monkeypatch,
    mode: str,
):
    class Response:
        def __init__(self):
            self.headers = {
                "declared_too_large": {"Content-Length": "4"},
                "stream_too_large": {},
                "length_mismatch": {"Content-Length": "5"},
            }[mode]
            self.sent = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            if self.sent:
                return b""
            self.sent = True
            return b"four"

    monkeypatch.setattr(hub_fetch.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(release, "MAX_ARCHIVE_BYTES", 3 if mode != "length_mismatch" else 10)
    destination = tmp_path / "archive.tar.gz"
    with pytest.raises(fetcher.FetchError, match="byte limit|length mismatch"):
        fetcher.download_public_artifact(URL, destination)
    assert not destination.exists()


def test_public_downloader_sends_no_authorization_header(tmp_path: Path, monkeypatch):
    observed_headers: dict[str, str] = {}

    class Response:
        headers = {"Content-Length": "3"}
        sent = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            if self.sent:
                return b""
            self.sent = True
            return b"abc"

    def open_request(request, **_kwargs):
        observed_headers.update(dict(request.header_items()))
        return Response()

    monkeypatch.setattr(hub_fetch.urllib.request, "urlopen", open_request)
    destination = tmp_path / "archive.tar.gz"
    fetcher.download_public_artifact(URL, destination)
    assert destination.read_bytes() == b"abc"
    assert all(key.lower() != "authorization" for key in observed_headers)


def test_cli_accepts_required_lock_and_destination_arguments(tmp_path: Path, monkeypatch, capsys):
    lock = tmp_path / "lock.json"
    destination = tmp_path / "release"
    observed = {}

    def fake_fetch(**kwargs):
        observed.update(kwargs)
        return {"release_id": "c" * 20}

    monkeypatch.setattr(fetcher, "fetch_locked_release", fake_fetch)
    assert fetcher.main(["--lock", str(lock), "--destination", str(destination)]) == 0
    assert observed == {"lock_path": lock, "destination": destination}
    assert "installed historical release" in capsys.readouterr().out
