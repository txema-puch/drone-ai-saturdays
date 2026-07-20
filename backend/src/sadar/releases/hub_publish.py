"""Transactionally publish one immutable SADAR release.

The transaction boundary is intentionally local and dependency-light::

    clean tree -> deterministic archive -> upload -> immutable revision
               -> public redownload -> release.inspect_release_archive
               -> atomic lock replacement

Only the command-line adapter imports ``huggingface_hub``.  The transaction itself is
injected with upload and download callables, which keeps publisher dependencies and
credentials out of the serving image and makes every failure boundary testable.

Run the publisher dependency in its isolated project group::

    uv run --project backend --group publish python -m sadar.releases.hub_publish ...
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from sadar.releases import archive as release


LOCK_NAME = "release.lock.json"
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
DEFAULT_ARTIFACT_NAME = "sadar-release.tar.gz"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[0-9a-f]{20}$")
_IMMUTABLE_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_HF_REPOSITORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")


class PublicationError(RuntimeError):
    """A publication precondition or transaction step failed."""


@dataclass(frozen=True)
class UploadedArtifact:
    """Public immutable location returned by an upload implementation."""

    url: str
    revision: str


class ArtifactUploader(Protocol):
    def __call__(self, archive_path: Path) -> UploadedArtifact: ...


class ArtifactDownloader(Protocol):
    def __call__(self, url: str, destination: Path) -> None: ...


CleanTreeCheck = Callable[[Path], None]
Clock = Callable[[], datetime]


def _resolved_directory(path: Path | str, *, field: str) -> Path:
    candidate = Path(path)
    try:
        if candidate.is_symlink():
            raise PublicationError(f"{field} must not be a symbolic link")
        resolved = candidate.resolve(strict=True)
        mode = resolved.stat().st_mode
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError(f"cannot access {field}: {exc}") from exc
    if not stat.S_ISDIR(mode):
        raise PublicationError(f"{field} must be a directory")
    return resolved


def _lock_destination(
    lock_path: Path | str,
    *,
    repository_root: Path,
    lock_name: str = LOCK_NAME,
) -> Path:
    candidate = Path(lock_path)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative_parent = candidate.parent.relative_to(repository_root)
        current = repository_root
        for part in relative_parent.parts:
            current = current / part
            if current.is_symlink():
                raise PublicationError("lock destination parent must not contain symbolic links")
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(repository_root)
    except PublicationError:
        raise
    except (OSError, ValueError) as exc:
        raise PublicationError("lock destination must have an existing parent inside the repository") from exc
    destination = parent / candidate.name
    if destination.name != lock_name:
        raise PublicationError(f"lock destination basename must be {lock_name}")
    if destination.exists() or destination.is_symlink():
        try:
            mode = destination.lstat().st_mode
        except OSError as exc:
            raise PublicationError(f"cannot inspect lock destination: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise PublicationError("existing lock destination must be a regular file")
    return destination


def _run_git(args: list[str], *, repository_root: Path) -> int:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublicationError("could not inspect Git working tree") from exc
    return completed.returncode


def assert_clean_git_tree(repository_root: Path) -> None:
    """Reject tracked, staged, and untracked changes without buffering filenames."""
    if _run_git(["rev-parse", "--is-inside-work-tree"], repository_root=repository_root) != 0:
        raise PublicationError("repository root is not a Git working tree")
    for args in (["diff", "--quiet", "--exit-code", "--"], ["diff", "--cached", "--quiet", "--exit-code", "--"]):
        status = _run_git(list(args), repository_root=repository_root)
        if status == 1:
            raise PublicationError("Git working tree must be clean before publication")
        if status != 0:
            raise PublicationError("could not inspect Git working tree")

    # ``git ls-files`` exits zero both with and without matches.  Read one byte, then
    # terminate immediately, so a repository with many untracked paths cannot fill memory.
    try:
        process = subprocess.Popen(
            ["git", "ls-files", "--others", "--exclude-standard", "--directory"],
            cwd=repository_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        first_byte = process.stdout.read(1)
        if first_byte:
            process.terminate()
        return_code = process.wait(timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        if "process" in locals() and process.poll() is None:
            process.kill()
            process.wait()
        raise PublicationError("could not inspect Git working tree") from exc
    finally:
        if "process" in locals() and process.stdout is not None:
            process.stdout.close()
    if first_byte:
        raise PublicationError("Git working tree must be clean before publication")
    if return_code != 0:
        raise PublicationError("could not inspect Git working tree")


def _validate_revision(value: object) -> str:
    if not isinstance(value, str) or not _IMMUTABLE_REVISION_RE.fullmatch(value):
        raise PublicationError("uploader must return an immutable lowercase hexadecimal revision")
    return value


RepositoryType = Literal["model", "dataset"]


def _validate_public_url(
    value: object,
    *,
    revision: str,
    repo_type: RepositoryType = "model",
    expected_repo_id: str | None = None,
    expected_artifact_name: str | None = None,
) -> str:
    if repo_type not in ("model", "dataset"):
        raise PublicationError("artifact repository type must be model or dataset")
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_URL_BYTES:
        raise PublicationError("uploader returned an invalid public artifact URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PublicationError("uploader returned an invalid public artifact URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "huggingface.co"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PublicationError("artifact URL must be a public HTTPS huggingface.co URL without credentials")
    parts = tuple(part for part in parsed.path.split("/") if part)
    prefix = ("datasets",) if repo_type == "dataset" else ()
    expected_length = 6 if repo_type == "dataset" else 5
    owner_index = len(prefix)
    repository_index = owner_index + 1
    resolve_index = owner_index + 2
    revision_index = owner_index + 3
    artifact_index = owner_index + 4
    if (
        len(parts) != expected_length
        or parsed.path != "/" + "/".join(parts)
        or parts[: len(prefix)] != prefix
        or parts[resolve_index] != "resolve"
        or parts[revision_index] != revision
        or not all(
            _HF_REPOSITORY_COMPONENT_RE.fullmatch(part)
            for part in (parts[owner_index], parts[repository_index])
        )
        or not _ARTIFACT_NAME_RE.fullmatch(parts[artifact_index])
        or (
            expected_repo_id is not None
            and "/".join((parts[owner_index], parts[repository_index]))
            != expected_repo_id
        )
        or (
            expected_artifact_name is not None
            and parts[artifact_index] != expected_artifact_name
        )
    ):
        raise PublicationError("artifact URL does not match the required immutable repository path")
    return value


def _publication_timestamp(clock: Clock) -> str:
    observed = clock()
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise PublicationError("publication clock must return a timezone-aware datetime")
    return observed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_lock_record(
    value: object,
    *,
    expected_schema_version: int = release.RELEASE_SCHEMA_VERSION,
    repo_type: RepositoryType = "model",
    expected_repo_id: str | None = None,
    expected_artifact_name: str | None = None,
) -> dict[str, object]:
    """Validate the exact committed lock schema before writing or consuming it."""
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        raise PublicationError("publication lock must contain exactly the supported fields")
    revision = _validate_revision(value["revision"])
    url = _validate_public_url(
        value["url"],
        revision=revision,
        repo_type=repo_type,
        expected_repo_id=expected_repo_id,
        expected_artifact_name=expected_artifact_name,
    )
    archive_sha256 = value["archive_sha256"]
    release_id = value["release_id"]
    schema_version = value["schema_version"]
    published_at = value["published_at"]
    if not isinstance(archive_sha256, str) or not _SHA256_RE.fullmatch(archive_sha256):
        raise PublicationError("publication lock archive_sha256 must be lowercase SHA-256")
    if not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id):
        raise PublicationError("publication lock release_id must be 20 lowercase hexadecimal characters")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise PublicationError("publication lock schema_version must be an integer")
    if schema_version != expected_schema_version:
        raise PublicationError("publication lock schema_version is unsupported")
    if not isinstance(published_at, str) or len(published_at) > 32:
        raise PublicationError("publication lock published_at must be a bounded UTC timestamp")
    try:
        parsed_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError("publication lock published_at is malformed") from exc
    if not published_at.endswith("Z") or parsed_time.tzinfo is None:
        raise PublicationError("publication lock published_at must be a UTC timestamp")
    return {
        "archive_sha256": archive_sha256,
        "published_at": published_at,
        "release_id": release_id,
        "revision": revision,
        "schema_version": schema_version,
        "url": url,
    }


def _write_lock_atomically(
    lock_path: Path,
    record: dict[str, object],
    *,
    contract=release,
    schema_version: int = release.RELEASE_SCHEMA_VERSION,
    repo_type: RepositoryType = "model",
    expected_repo_id: str | None = None,
    expected_artifact_name: str | None = None,
) -> None:
    data = contract.canonical_json_bytes(
        validate_lock_record(
            record,
            expected_schema_version=schema_version,
            repo_type=repo_type,
            expected_repo_id=expected_repo_id,
            expected_artifact_name=expected_artifact_name,
        )
    ) + b"\n"
    if len(data) > MAX_LOCK_BYTES:
        raise PublicationError("publication lock exceeds its byte limit")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{lock_path.name}.", suffix=".tmp", dir=lock_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            os.fchmod(handle.fileno(), 0o644)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, lock_path)
    except OSError as exc:
        raise PublicationError("could not atomically replace publication lock") from exc
    finally:
        temporary.unlink(missing_ok=True)


def publish_release(
    *,
    release_dir: Path | str,
    lock_path: Path | str,
    repository_root: Path | str,
    uploader: ArtifactUploader,
    downloader: ArtifactDownloader,
    clean_tree_check: CleanTreeCheck = assert_clean_git_tree,
    clock: Clock = lambda: datetime.now(UTC),
    contract=release,
    schema_version: int = release.RELEASE_SCHEMA_VERSION,
    lock_name: str = LOCK_NAME,
    artifact_name: str = DEFAULT_ARTIFACT_NAME,
    repo_type: RepositoryType = "model",
    expected_repo_id: str | None = None,
) -> dict[str, object]:
    """Run the local publication transaction and return the newly committed lock."""
    repository = _resolved_directory(repository_root, field="repository root")
    source_candidate = Path(release_dir)
    if not source_candidate.is_absolute():
        source_candidate = repository / source_candidate
    source = _resolved_directory(source_candidate, field="release directory")
    destination = _lock_destination(
        lock_path, repository_root=repository, lock_name=lock_name
    )
    clean_tree_check(repository)

    source_manifest = contract.validate_release_directory(source)
    with tempfile.TemporaryDirectory(prefix="sadar-publish-") as working_name:
        working = Path(working_name)
        archive = working / artifact_name
        archive_sha256, _ = contract.create_deterministic_archive(source, archive)
        packaged_manifest = contract.inspect_release_archive(
            archive, expected_sha256=archive_sha256
        )
        if contract.canonical_json_bytes(packaged_manifest) != contract.canonical_json_bytes(source_manifest):
            raise PublicationError("release changed while its deterministic archive was built")

        uploaded = uploader(archive)
        if not isinstance(uploaded, UploadedArtifact):
            raise PublicationError("uploader returned an invalid artifact descriptor")
        revision = _validate_revision(uploaded.revision)
        url = _validate_public_url(
            uploaded.url,
            revision=revision,
            repo_type=repo_type,
            expected_repo_id=expected_repo_id,
            expected_artifact_name=artifact_name,
        )

        redownload = working / "redownloaded-release.tar.gz"
        downloader(url, redownload)
        downloaded_manifest = contract.inspect_release_archive(
            redownload, expected_sha256=archive_sha256
        )
        if contract.canonical_json_bytes(downloaded_manifest) != contract.canonical_json_bytes(source_manifest):
            raise PublicationError("redownloaded release manifest differs from the packaged release")

        record = validate_lock_record(
            {
                "archive_sha256": archive_sha256,
                "published_at": _publication_timestamp(clock),
                "release_id": source_manifest["release_id"],
                "revision": revision,
                "schema_version": source_manifest["schema_version"],
                "url": url,
            },
            expected_schema_version=schema_version,
            repo_type=repo_type,
            expected_repo_id=expected_repo_id,
            expected_artifact_name=artifact_name,
        )
        _write_lock_atomically(
            destination,
            record,
            contract=contract,
            schema_version=schema_version,
            repo_type=repo_type,
            expected_repo_id=expected_repo_id,
            expected_artifact_name=artifact_name,
        )
        return record


def download_public_artifact(
    url: str,
    destination: Path,
    *,
    max_archive_bytes: int = release.MAX_ARCHIVE_BYTES,
) -> None:
    """Download one public archive to a new regular file with a strict byte ceiling."""
    request = urllib.request.Request(url, headers={"User-Agent": "sadar-release-publisher/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_bytes = int(declared)
                except ValueError as exc:
                    raise PublicationError("artifact server returned an invalid Content-Length") from exc
                if declared_bytes < 0 or declared_bytes > max_archive_bytes:
                    raise PublicationError("redownloaded archive exceeds its byte limit")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                copied = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > max_archive_bytes:
                        raise PublicationError("redownloaded archive exceeds its byte limit")
                    output.write(chunk)
    except PublicationError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        destination.unlink(missing_ok=True)
        raise PublicationError("public artifact redownload failed") from exc


def hugging_face_uploader(
    *,
    repo_id: str,
    artifact_name: str,
    token: str,
    repo_type: RepositoryType,
) -> ArtifactUploader:
    """Create the optional Hub adapter without importing it in serving code."""
    if not token:
        raise PublicationError("HF_TOKEN is required for publication")
    repo_parts = repo_id.split("/")
    if len(repo_parts) != 2 or not all(_HF_REPOSITORY_COMPONENT_RE.fullmatch(part) for part in repo_parts):
        raise PublicationError("Hugging Face repository ID must use owner/name format")
    if not _ARTIFACT_NAME_RE.fullmatch(artifact_name):
        raise PublicationError("artifact name must be a basename")
    try:
        from huggingface_hub import HfApi, hf_hub_url
    except ImportError as exc:
        raise PublicationError("install huggingface_hub in the publisher environment") from exc

    api = HfApi(token=token)

    def upload(archive_path: Path) -> UploadedArtifact:
        result = api.upload_file(
            path_or_fileobj=str(archive_path),
            path_in_repo=artifact_name,
            repo_id=repo_id,
            repo_type=repo_type,
        )
        revision = getattr(result, "oid", None)
        if not isinstance(revision, str):
            raise PublicationError("Hugging Face upload did not return an immutable revision")
        return UploadedArtifact(
            url=hf_hub_url(
                repo_id=repo_id,
                filename=artifact_name,
                repo_type=repo_type,
                revision=revision,
            ),
            revision=revision,
        )

    return upload


def resolve_hugging_face_token() -> str:
    """Resolve a publisher token without persisting or printing it."""
    environment_token = os.environ.get("HF_TOKEN", "")
    if environment_token:
        return environment_token
    try:
        from huggingface_hub import get_token
    except ImportError as exc:
        raise PublicationError("install huggingface_hub in the publisher environment") from exc
    return get_token() or ""


def safe_error_message(error: BaseException, *, secret: str) -> str:
    message = str(error).replace(secret, "[REDACTED]") if secret else str(error)
    return message[:MAX_ERROR_MESSAGE] or error.__class__.__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--hf-repo-id", required=True)
    parser.add_argument("--artifact-name", default=DEFAULT_ARTIFACT_NAME)
    parser.add_argument("--repo-type", choices=("model", "dataset"), default="model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = ""
    try:
        token = resolve_hugging_face_token()
        uploader = hugging_face_uploader(
            repo_id=args.hf_repo_id,
            artifact_name=args.artifact_name,
            token=token,
            repo_type=args.repo_type,
        )
        record = publish_release(
            release_dir=args.release_dir,
            lock_path=args.lock,
            repository_root=args.repository_root,
            uploader=uploader,
            downloader=download_public_artifact,
            repo_type=args.repo_type,
            expected_repo_id=args.hf_repo_id,
        )
    except Exception as exc:
        print(f"publication failed: {safe_error_message(exc, secret=token)}", file=sys.stderr)
        return 1
    print(f"published release {record['release_id']} at immutable revision {record['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
