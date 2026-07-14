"""Deterministic, strict archive transport for schema-v3 approach releases.

The serving image uses this standard-library-only boundary to verify a public archive
before installing it. Publisher credentials and the Hugging Face SDK stay outside the
runtime image.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from backend.serve.approach_release import (
    ALLOWED_FILES,
    APPROACH_RELEASE_SCHEMA_VERSION,
    FILE_LIMITS,
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    MAX_TOTAL_BYTES,
    ApproachReleaseError,
    ApproachReleaseFormatError,
    ApproachReleaseIntegrityError,
    canonical_json_bytes,
    parse_json_bytes,
    validate_manifest,
    validate_release_directory,
)


ReleaseError = ApproachReleaseError
ReleaseFormatError = ApproachReleaseFormatError
ReleaseIntegrityError = ApproachReleaseIntegrityError
RELEASE_SCHEMA_VERSION = APPROACH_RELEASE_SCHEMA_VERSION
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_DECOMPRESSED_BYTES = MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + 16 * 1024 * 1024
_SHA256_LENGTH = 64


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReleaseFormatError("archive member must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ReleaseFormatError(f"archive member is unsafe: {value!r}")
    return value


def _sha256_stream(handle: BinaryIO, *, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ReleaseFormatError("stream exceeds its byte limit")
        digest.update(chunk)
    return digest.hexdigest(), total


def _sha256_file(path: Path, *, limit: int) -> tuple[str, int]:
    with path.open("rb") as handle:
        return _sha256_stream(handle, limit=limit)


def create_deterministic_archive(
    release_dir: Path | str,
    destination: Path | str,
) -> tuple[str, int]:
    """Write a byte-reproducible gzip tar containing only the validated release."""
    root = Path(release_dir)
    manifest = validate_release_directory(root)
    members = [MANIFEST_NAME, *(record["path"] for record in manifest["files"])]
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT
                ) as archive:
                    for relative in members:
                        path = root.joinpath(*PurePosixPath(relative).parts)
                        info = tarfile.TarInfo(relative)
                        info.size = path.stat().st_size
                        info.mode = 0o644
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        with path.open("rb") as source:
                            archive.addfile(info, source)
        inspect_release_archive(temporary)
        os.replace(temporary, output)
        return _sha256_file(output, limit=MAX_ARCHIVE_BYTES)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _verified_archive(path: Path, expected_sha256: str | None):
    if expected_sha256 is not None and (
        len(expected_sha256) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ReleaseFormatError("expected archive digest is not lowercase SHA-256")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReleaseFormatError("cannot open approach release archive") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARCHIVE_BYTES:
            raise ReleaseFormatError("approach release archive is not a bounded regular file")
        if expected_sha256 is not None:
            observed, _ = _sha256_stream(handle, limit=MAX_ARCHIVE_BYTES)
            if observed != expected_sha256:
                raise ReleaseIntegrityError("approach release archive digest mismatch")
            handle.seek(0)
        yield handle
        if expected_sha256 is not None:
            handle.seek(0)
            observed, _ = _sha256_stream(handle, limit=MAX_ARCHIVE_BYTES)
            if observed != expected_sha256:
                raise ReleaseIntegrityError("approach release archive changed during verification")


@contextmanager
def _bounded_tar(archive_file: BinaryIO):
    archive_file.seek(0)
    decompressed = tempfile.TemporaryFile(mode="w+b")
    total = 0
    try:
        with gzip.GzipFile(fileobj=archive_file, mode="rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_DECOMPRESSED_BYTES:
                    raise ReleaseFormatError("approach release archive exceeds decompression limit")
                decompressed.write(chunk)
        decompressed.seek(0)
        yield decompressed
    except ReleaseError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise ReleaseFormatError("cannot decompress approach release archive") from exc
    finally:
        decompressed.close()


def _members(archive: tarfile.TarFile) -> tuple[dict[str, tarfile.TarInfo], dict[str, Any]]:
    members: dict[str, tarfile.TarInfo] = {}
    declared_total = 0
    maximum_members = len(ALLOWED_FILES) + 1
    for index, info in enumerate(archive):
        if index >= maximum_members:
            raise ReleaseFormatError("approach release archive has too many members")
        name = _relative_path(info.name)
        if name in members or not info.isreg():
            raise ReleaseFormatError("approach release archive has a duplicate or non-file member")
        limit = MAX_MANIFEST_BYTES if name == MANIFEST_NAME else FILE_LIMITS.get(name)
        if limit is None or info.size < 0 or info.size > limit:
            raise ReleaseFormatError(f"approach release archive member is not allowlisted: {name}")
        declared_total += info.size
        if declared_total > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
            raise ReleaseFormatError("approach release archive members exceed total byte limit")
        members[name] = info
    manifest_info = members.get(MANIFEST_NAME)
    if manifest_info is None:
        raise ReleaseFormatError("approach release archive is missing its manifest")
    handle = archive.extractfile(manifest_info)
    if handle is None:
        raise ReleaseFormatError("approach release archive manifest is unreadable")
    data = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(data) != manifest_info.size:
        raise ReleaseFormatError("approach release archive manifest is truncated")
    manifest = validate_manifest(parse_json_bytes(data, source=MANIFEST_NAME))
    if canonical_json_bytes(manifest) != data:
        raise ReleaseFormatError("approach release archive manifest is not canonical JSON")
    expected = {MANIFEST_NAME, *(record["path"] for record in manifest["files"])}
    if set(members) != expected:
        raise ReleaseFormatError("approach release archive layout does not match its manifest")
    records = {record["path"]: record for record in manifest["files"]}
    for name, record in records.items():
        if members[name].size != record["bytes"]:
            raise ReleaseIntegrityError(f"approach release member length mismatch: {name}")
    return members, manifest


def inspect_release_archive(
    archive_path: Path | str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify archive shape, canonical JSON, and every declared artifact digest."""
    try:
        with _verified_archive(Path(archive_path), expected_sha256) as source:
            with _bounded_tar(source) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r:") as archive:
                    members, manifest = _members(archive)
                    records = {record["path"]: record for record in manifest["files"]}
                    for name, record in records.items():
                        handle = archive.extractfile(members[name])
                        if handle is None:
                            raise ReleaseFormatError(f"approach release member is unreadable: {name}")
                        data = handle.read(FILE_LIMITS[name] + 1)
                        if (
                            len(data) != record["bytes"]
                            or hashlib.sha256(data).hexdigest() != record["sha256"]
                        ):
                            raise ReleaseIntegrityError(
                                f"approach release member digest mismatch: {name}"
                            )
                        value = parse_json_bytes(data, source=name)
                        if canonical_json_bytes(value) != data:
                            raise ReleaseFormatError(
                                f"approach release member is not canonical JSON: {name}"
                            )
                    return manifest
    except ReleaseError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise ReleaseFormatError("cannot inspect approach release archive") from exc


def _exclusive(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def extract_release_archive(
    archive_path: Path | str,
    target_dir: Path | str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Strictly extract to a sibling temporary directory and atomically install it."""
    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ReleaseFormatError("approach release extraction target already exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.extract-", dir=target.parent))
    try:
        with _verified_archive(Path(archive_path), expected_sha256) as source:
            with _bounded_tar(source) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r:") as archive:
                    members, manifest = _members(archive)
                    records = {record["path"]: record for record in manifest["files"]}
                    for name in [MANIFEST_NAME, *sorted(records)]:
                        destination = temporary.joinpath(*PurePosixPath(name).parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        handle = archive.extractfile(members[name])
                        if handle is None:
                            raise ReleaseFormatError(f"approach release member is unreadable: {name}")
                        with _exclusive(destination) as output:
                            data = handle.read(members[name].size + 1)
                            if len(data) != members[name].size:
                                raise ReleaseIntegrityError(f"approach release member is truncated: {name}")
                            output.write(data)
                        if name != MANIFEST_NAME and hashlib.sha256(data).hexdigest() != records[name]["sha256"]:
                            raise ReleaseIntegrityError(f"approach release member digest mismatch: {name}")
        validated = validate_release_directory(temporary)
        os.rename(temporary, target)
        return validated
    except ReleaseError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise ReleaseFormatError("cannot extract approach release archive") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
