"""Fetch and strictly extract one locked public SADAR release.

This build/runtime path is standard-library-only.  It deliberately has no publisher,
Hugging Face SDK, token, or authentication dependency::

    bounded lock -> anonymous immutable HTTPS download -> archive SHA/shape check
                 -> atomic strict extraction -> lock/release provenance match
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from sadar.releases import archive as release


LOCK_KEYS = frozenset(
    {
        "archive_sha256",
        "published_at",
        "release_id",
        "revision",
        "schema_version",
        "url",
    }
)
MAX_LOCK_BYTES = 64 * 1024
MAX_URL_BYTES = 4096
MAX_ERROR_MESSAGE = 500
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[0-9a-f]{20}$")
_IMMUTABLE_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_HF_REPOSITORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")


class FetchError(RuntimeError):
    """A locked release could not be safely fetched or installed."""


class ArtifactDownloader(Protocol):
    def __call__(self, url: str, destination: Path) -> None: ...


def _read_bounded_lock(path: Path | str, *, contract=release) -> Any:
    lock_path = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags)
    except OSError as exc:
        raise FetchError("cannot open release lock") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise FetchError("release lock must be a regular file")
            if info.st_size > MAX_LOCK_BYTES:
                raise FetchError("release lock exceeds its byte limit")
            data = handle.read(MAX_LOCK_BYTES + 1)
            if len(data) > MAX_LOCK_BYTES:
                raise FetchError("release lock exceeds its byte limit")
    except FetchError:
        raise
    except OSError as exc:
        raise FetchError("cannot read release lock") from exc
    try:
        return contract.parse_json_bytes(data, source="release lock")
    except contract.ReleaseError as exc:
        raise FetchError("release lock is malformed") from exc


def read_bounded_json_lock(path: Path | str, *, contract=release) -> Any:
    """Read a no-follow, size-bounded JSON lock with the selected parser."""
    return _read_bounded_lock(path, contract=contract)


def _validate_public_url(value: object, *, revision: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_URL_BYTES:
        raise FetchError("release lock URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise FetchError("release lock URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "huggingface.co"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise FetchError("release lock URL must be public immutable HTTPS on huggingface.co")
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        len(parts) != 5
        or parsed.path != "/" + "/".join(parts)
        or parts[2] != "resolve"
        or parts[3] != revision
        or not all(_HF_REPOSITORY_COMPONENT_RE.fullmatch(part) for part in (parts[0], parts[1]))
        or not _ARTIFACT_NAME_RE.fullmatch(parts[4])
    ):
        raise FetchError("release lock URL must contain owner/repository/resolve/revision/artifact")
    return value


def validate_lock_record(
    value: object,
    *,
    expected_schema_version: int = release.RELEASE_SCHEMA_VERSION,
) -> dict[str, object]:
    """Validate the exact, bounded serving lock schema."""
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        raise FetchError("release lock must contain exactly the supported fields")
    revision = value["revision"]
    if not isinstance(revision, str) or not _IMMUTABLE_REVISION_RE.fullmatch(revision):
        raise FetchError("release lock revision must be an immutable hexadecimal revision")
    url = _validate_public_url(value["url"], revision=revision)
    archive_sha256 = value["archive_sha256"]
    release_id = value["release_id"]
    schema_version = value["schema_version"]
    published_at = value["published_at"]
    if not isinstance(archive_sha256, str) or not _SHA256_RE.fullmatch(archive_sha256):
        raise FetchError("release lock archive_sha256 must be lowercase SHA-256")
    if not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id):
        raise FetchError("release lock release_id must be 20 lowercase hexadecimal characters")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != expected_schema_version
    ):
        raise FetchError("release lock schema_version is unsupported")
    if not isinstance(published_at, str) or len(published_at) > 32 or not published_at.endswith("Z"):
        raise FetchError("release lock published_at must be a bounded UTC timestamp")
    try:
        parsed_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FetchError("release lock published_at is malformed") from exc
    if parsed_time.tzinfo is None:
        raise FetchError("release lock published_at must be a UTC timestamp")
    return {
        "archive_sha256": archive_sha256,
        "published_at": published_at,
        "release_id": release_id,
        "revision": revision,
        "schema_version": schema_version,
        "url": url,
    }


def read_lock(
    path: Path | str,
    *,
    contract=release,
    expected_schema_version: int = release.RELEASE_SCHEMA_VERSION,
) -> dict[str, object]:
    return validate_lock_record(
        _read_bounded_lock(path, contract=contract),
        expected_schema_version=expected_schema_version,
    )


def _exclusive_output(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise FetchError("cannot create temporary archive") from exc
    return os.fdopen(descriptor, "wb")


def download_public_artifact(
    url: str,
    destination: Path,
    *,
    max_archive_bytes: int = release.MAX_ARCHIVE_BYTES,
) -> None:
    """Anonymously stream a public archive to a new bounded regular file."""
    request = urllib.request.Request(url, headers={"User-Agent": "sadar-release-fetcher/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            declared_header = response.headers.get("Content-Length")
            declared: int | None = None
            if declared_header is not None:
                try:
                    declared = int(declared_header)
                except ValueError as exc:
                    raise FetchError("artifact server returned an invalid Content-Length") from exc
                if declared < 0 or declared > max_archive_bytes:
                    raise FetchError("downloaded archive exceeds its byte limit")
            with _exclusive_output(destination) as output:
                copied = 0
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > max_archive_bytes:
                        raise FetchError("downloaded archive exceeds its byte limit")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if declared is not None and copied != declared:
                raise FetchError(
                    f"downloaded archive length mismatch: expected {declared}, observed {copied}"
                )
    except FetchError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        destination.unlink(missing_ok=True)
        raise FetchError("public artifact download failed") from exc


def _safe_destination(path: Path | str) -> Path:
    candidate = Path(os.path.abspath(Path(path)))
    if candidate.exists() or candidate.is_symlink():
        raise FetchError("release destination must not already exist")
    # Reject existing symbolic-link ancestors before creating any path.  The build/runtime
    # destination is trusted configuration, but following an attacker-controlled ancestor
    # would defeat the extractor's same-directory atomic rename.
    current = Path(candidate.anchor)
    for part in candidate.parts[1:-1]:
        current = current / part
        if current.is_symlink():
            raise FetchError("release destination must not contain symbolic-link ancestors")
    return candidate


def safe_destination(path: Path | str) -> Path:
    """Validate a not-yet-existing atomic installation destination."""
    return _safe_destination(path)


def _assert_manifest_matches_lock(manifest: object, lock: dict[str, object]) -> None:
    if not isinstance(manifest, dict):
        raise FetchError("extracted release manifest is invalid")
    if manifest.get("release_id") != lock["release_id"]:
        raise FetchError(
            f"release ID mismatch: expected {lock['release_id']}, observed {manifest.get('release_id')}"
        )
    if manifest.get("schema_version") != lock["schema_version"]:
        raise FetchError(
            "release schema mismatch: "
            f"expected {lock['schema_version']}, observed {manifest.get('schema_version')}"
        )


def fetch_locked_release(
    *,
    lock_path: Path | str,
    destination: Path | str,
    downloader: ArtifactDownloader = download_public_artifact,
    contract=release,
    expected_schema_version: int = release.RELEASE_SCHEMA_VERSION,
    archive_name: str = "sadar-release.tar.gz",
) -> dict[str, Any]:
    """Download, verify, and atomically install the release named by a lock."""
    lock = read_lock(
        lock_path,
        contract=contract,
        expected_schema_version=expected_schema_version,
    )
    target = _safe_destination(destination)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FetchError("cannot create release destination parent") from exc
    try:
        working = Path(tempfile.mkdtemp(prefix=".sadar-fetch-", dir=target.parent))
    except OSError as exc:
        raise FetchError("cannot create temporary download directory") from exc
    success = False
    installed_by_us = False
    try:
        archive = working / archive_name
        downloader(str(lock["url"]), archive)
        inspected = contract.inspect_release_archive(
            archive,
            expected_sha256=str(lock["archive_sha256"]),
        )
        _assert_manifest_matches_lock(inspected, lock)
        extracted = contract.extract_release_archive(
            archive,
            target,
            expected_sha256=str(lock["archive_sha256"]),
        )
        installed_by_us = True
        _assert_manifest_matches_lock(extracted, lock)
        success = True
        return extracted
    except FetchError:
        raise
    except contract.ReleaseError as exc:
        raise FetchError("locked release archive failed verification") from exc
    except OSError as exc:
        raise FetchError("locked release could not be installed") from exc
    finally:
        shutil.rmtree(working, ignore_errors=True)
        if installed_by_us and not success and (target.exists() or target.is_symlink()):
            if target.is_symlink() or target.is_file():
                target.unlink(missing_ok=True)
            else:
                shutil.rmtree(target, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = fetch_locked_release(lock_path=args.lock, destination=args.destination)
    except Exception as exc:
        message = (str(exc) or exc.__class__.__name__)[:MAX_ERROR_MESSAGE]
        print(f"release fetch failed: {message}", file=sys.stderr)
        return 1
    print(f"installed release {manifest['release_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
