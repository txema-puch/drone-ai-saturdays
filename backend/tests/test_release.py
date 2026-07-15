from __future__ import annotations

import errno
import gzip
import io
import shutil
import tarfile
from pathlib import Path

import pytest

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


def make_release(base: Path, *, payload: dict | None = None) -> dict:
    for index, relative in enumerate(release.REQUIRED_RELEASE_FILES):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-{index}-{relative}".encode())
    return release.write_release_manifest(base, payload or MANIFEST_PAYLOAD)


def test_manifest_identity_is_canonical_and_path_independent(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir(); right.mkdir()
    first = make_release(left)
    second = make_release(right)

    assert first["release_id"] == second["release_id"]
    assert release.validate_release_directory(left) == first
    assert release.validate_release_directory(right) == second


def test_corrupt_missing_and_extra_release_members_fail(tmp_path: Path):
    root = tmp_path / "release"
    root.mkdir()
    manifest = make_release(root)
    target = root / "queue.json"
    target.write_bytes(target.read_bytes() + b"corrupt")
    with pytest.raises(release.ReleaseIntegrityError, match="queue.json"):
        release.validate_release_directory(root)

    target.write_bytes(b"artifact-8-queue.json")
    assert release.validate_release_directory(root)["release_id"] == manifest["release_id"]
    target.unlink()
    with pytest.raises(release.ReleaseFormatError, match="layout mismatch"):
        release.validate_release_directory(root)

    target.write_bytes(b"artifact-8-queue.json")
    (root / "unexpected.txt").write_text("no")
    with pytest.raises(release.ReleaseFormatError, match="extra_files"):
        release.validate_release_directory(root)


def test_duplicate_json_keys_and_noncanonical_manifest_records_fail(tmp_path: Path):
    with pytest.raises(release.ReleaseFormatError, match="duplicate key"):
        release.parse_json_bytes(b'{"a":1,"a":2}')
    for constant in (b"NaN", b"Infinity", b"-Infinity"):
        with pytest.raises(release.ReleaseFormatError, match="non-standard numeric constant"):
            release.parse_json_bytes(b'{"value":' + constant + b"}")

    root = tmp_path / "release"
    root.mkdir()
    manifest = make_release(root)
    manifest["files"] = list(reversed(manifest["files"]))
    manifest["release_id"] = release.release_id_for_manifest(manifest)
    with pytest.raises(release.ReleaseFormatError, match="sorted"):
        release.validate_manifest_structure(manifest)

    manifest = make_release(tmp_path / "other", payload=MANIFEST_PAYLOAD)
    manifest["generated_at"] = "2026-07-14T00:00:00Z"
    manifest["release_id"] = release.release_id_for_manifest(manifest)
    with pytest.raises(release.ReleaseFormatError, match="volatile identity field"):
        release.validate_manifest_structure(manifest)

    nested = make_release(tmp_path / "nested", payload=MANIFEST_PAYLOAD)
    nested["source"]["generated_at"] = "2026-07-14T00:00:00Z"
    nested["release_id"] = release.release_id_for_manifest(nested)
    with pytest.raises(release.ReleaseFormatError, match="source.generated_at"):
        release.validate_manifest_structure(nested)


def test_release_store_promotes_atomically_is_idempotent_and_cleans_failures(tmp_path: Path):
    store = release.ReleaseStore(tmp_path / "store")

    def writer(staging: Path) -> None:
        make_release(staging)

    semantic_calls = []
    promoted = store.build_release(
        writer,
        semantic_validator=lambda path, manifest: semantic_calls.append(manifest["release_id"]),
    )
    assert promoted.parent == store.releases_root
    assert semantic_calls == [promoted.name]
    assert not any(store.staging_root.iterdir())
    assert release.validate_release_directory(promoted, require_directory_name=True)

    repeated = store.build_release(writer, semantic_validator=lambda path, manifest: None)
    assert repeated == promoted
    assert not any(store.staging_root.iterdir())

    def interrupted(staging: Path) -> None:
        (staging / "partial").write_text("partial")
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        store.build_release(interrupted, semantic_validator=lambda path, manifest: None)
    assert not any(store.staging_root.iterdir())
    assert promoted.exists()

    def reject_semantics(path, manifest):
        raise release.ReleaseIntegrityError("semantic drift")

    with pytest.raises(release.ReleaseIntegrityError, match="semantic drift"):
        store.build_release(writer, semantic_validator=reject_semantics)
    assert not any(store.staging_root.iterdir())
    assert list(store.releases_root.iterdir()) == [promoted]

    def mutate_during_semantics(path, manifest):
        (path / "queue.json").write_bytes(b"mutated")

    with pytest.raises(release.ReleaseIntegrityError, match="queue.json"):
        store.build_release(writer, semantic_validator=mutate_during_semantics)
    assert not any(store.staging_root.iterdir())


def test_failed_staging_can_be_explicitly_preserved(tmp_path: Path):
    store = release.ReleaseStore(tmp_path / "store")

    def broken(staging: Path) -> None:
        (staging / "diagnostic").write_text("keep")
        raise RuntimeError("failure")

    with pytest.raises(RuntimeError):
        store.build_release(
            broken,
            semantic_validator=lambda path, manifest: None,
            keep_failed_staging=True,
        )
    kept = list(store.staging_root.iterdir())
    assert len(kept) == 1
    assert (kept[0] / "diagnostic").read_text() == "keep"


def test_concurrent_identical_promotion_accepts_enotempty_winner(tmp_path: Path, monkeypatch):
    store = release.ReleaseStore(tmp_path / "store")
    staging = store.begin_staging()
    manifest = make_release(staging)
    target = store.releases_root / manifest["release_id"]

    def concurrent_winner(source, destination):
        shutil.copytree(source, destination)
        raise OSError(errno.ENOTEMPTY, "concurrent release won")

    monkeypatch.setattr(release.os, "rename", concurrent_winner)
    promoted = store.promote(staging, semantic_validator=lambda path, value: None)
    assert promoted == target
    assert release.validate_release_directory(target, require_directory_name=True)
    assert not staging.exists()


def test_deterministic_archive_and_atomic_safe_extraction(tmp_path: Path):
    root = tmp_path / "release"
    root.mkdir()
    manifest = make_release(root)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    first_digest = release.create_deterministic_archive(root, first)
    second_digest = release.create_deterministic_archive(root, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == second_digest
    assert release.inspect_release_archive(first, expected_sha256=first_digest[0]) == manifest

    target = tmp_path / "fixed-runtime-release"
    extracted = release.extract_release_archive(first, target, expected_sha256=first_digest[0])
    assert extracted == manifest
    assert release.validate_release_directory(target) == manifest
    assert not list(tmp_path.glob(".fixed-runtime-release.extract-*"))


def rewrite_archive(source: Path, destination: Path, mutate) -> None:
    with tarfile.open(source, "r:gz") as original:
        entries = []
        for member in original:
            handle = original.extractfile(member)
            entries.append((member, handle.read() if handle else b""))
    entries = mutate(entries)
    with tarfile.open(destination, "w:gz") as output:
        for member, data in entries:
            member = tarfile.TarInfo(member.name)
            member.size = len(data)
            member.mode = 0o644
            output.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize(
    "kind", ["traversal", "absolute", "link", "device", "duplicate", "extra"]
)
def test_archive_rejects_unsafe_or_nonallowlisted_members(tmp_path: Path, kind: str):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    valid = tmp_path / "valid.tar.gz"
    release.create_deterministic_archive(root, valid)
    hostile = tmp_path / f"{kind}.tar.gz"

    def mutate(entries):
        if kind == "traversal":
            entries[0][0].name = "../escape"
        elif kind == "absolute":
            entries[0][0].name = "/absolute"
        elif kind == "link":
            entries[0][0].type = tarfile.SYMTYPE
            entries[0][0].linkname = "queue.json"
        elif kind == "device":
            entries[0][0].type = tarfile.CHRTYPE
        elif kind == "duplicate":
            entries.append(entries[0])
        else:
            info = tarfile.TarInfo("extra.txt")
            entries.append((info, b"extra"))
        return entries

    if kind in ("link", "device"):
        # Preserve unsafe member types; the generic writer intentionally normalizes types.
        with tarfile.open(valid, "r:gz") as original, tarfile.open(hostile, "w:gz") as output:
            for index, member in enumerate(original):
                data = original.extractfile(member).read()
                if index == 0:
                    unsafe = tarfile.TarInfo(member.name)
                    unsafe.type = tarfile.SYMTYPE if kind == "link" else tarfile.CHRTYPE
                    if kind == "link":
                        unsafe.linkname = "queue.json"
                    output.addfile(unsafe)
                else:
                    info = tarfile.TarInfo(member.name); info.size = len(data)
                    output.addfile(info, io.BytesIO(data))
    else:
        rewrite_archive(valid, hostile, mutate)

    with pytest.raises(release.ReleaseFormatError):
        release.inspect_release_archive(hostile)
    assert not (tmp_path / "escape").exists()


def test_archive_rejects_hash_mismatch_and_bounded_manifest(tmp_path: Path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    archive = tmp_path / "release.tar.gz"
    release.create_deterministic_archive(root, archive)

    with pytest.raises(release.ReleaseIntegrityError, match="archive digest mismatch"):
        release.inspect_release_archive(archive, expected_sha256="0" * 64)

    monkeypatch.setattr(release, "MAX_MANIFEST_BYTES", 16)
    with pytest.raises(release.ReleaseFormatError, match="manifest exceeds byte limit"):
        release.inspect_release_archive(archive)


def test_archive_rejects_declared_decompression_total_before_extraction(tmp_path: Path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    archive = tmp_path / "release.tar.gz"
    release.create_deterministic_archive(root, archive)
    monkeypatch.setattr(release, "MAX_RELEASE_BYTES", 16)
    monkeypatch.setattr(release, "MAX_MANIFEST_BYTES", 0)
    with pytest.raises(release.ReleaseFormatError, match="decompression limit"):
        release.inspect_release_archive(archive)


def test_archive_bounds_hidden_pax_extension_payloads(tmp_path: Path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    valid = tmp_path / "valid.tar.gz"
    release.create_deterministic_archive(root, valid)
    hostile = tmp_path / "pax-bomb.tar.gz"

    with tarfile.open(valid, "r:gz") as original:
        entries = [
            (member.name, original.extractfile(member).read())
            for member in original
        ]
    with tarfile.open(hostile, "w:gz", format=tarfile.PAX_FORMAT) as output:
        for index, (name, data) in enumerate(entries):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            if index == 0:
                info.pax_headers = {"comment": "x" * 100_000}
            output.addfile(info, io.BytesIO(data))

    with gzip.open(valid, "rb") as handle:
        valid_size = len(handle.read())
    with gzip.open(hostile, "rb") as handle:
        hostile_size = len(handle.read())
    assert hostile_size > valid_size
    monkeypatch.setattr(
        release,
        "MAX_ARCHIVE_DECOMPRESSED_BYTES",
        valid_size + (hostile_size - valid_size) // 2,
    )
    assert release.inspect_release_archive(valid)
    with pytest.raises(release.ReleaseFormatError, match="decompression limit"):
        release.inspect_release_archive(hostile)


def test_extraction_refuses_existing_target_without_mutation(tmp_path: Path):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    archive = tmp_path / "release.tar.gz"
    release.create_deterministic_archive(root, archive)
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "marker"
    marker.write_text("unchanged")

    with pytest.raises(release.ReleaseFormatError, match="already exists"):
        release.extract_release_archive(archive, target)
    assert marker.read_text() == "unchanged"


def test_release_directory_rejects_symlinked_file(tmp_path: Path):
    root = tmp_path / "release"
    root.mkdir()
    make_release(root)
    target = root / "queue.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(release.ReleaseFormatError, match="regular file"):
        release.validate_release_directory(root)
