"""Immutable SADAR release transport and storage primitives.

The protected transition is deliberately small and standard-library-only::

    build inputs -> .staging/<uuid> -> validate -> releases/<release_id>
                                                -> deterministic archive

Only ``.staging`` is mutable.  A release becomes visible at the final same-filesystem
rename, and consumers accept it only after validating the canonical manifest and every
shipped byte.  Dataframe/parquet relationships belong in ``release_semantics.py``; this
module is also used by the minimal image fetch stage and therefore imports no project,
Pydantic, pandas, or ML dependencies.
"""

from __future__ import annotations

import copy
import errno
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


RELEASE_SCHEMA_VERSION = 2
MANIFEST_NAME = "release-manifest.json"
REQUIRED_RELEASE_FILES = (
    "cases.json",
    "cases_raw.parquet",
    "metrics.json",
    "model/cohort-score-reference.json",
    "model/model-contract.json",
    "model/scaler.json",
    "model/state_dict.pt",
    "operations.json",
    "queue.json",
)

# The release is currently far below these ceilings.  The limits are defense-in-depth for
# the public fetch path and must be changed deliberately if the product grows beyond them.
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_RELEASE_FILE_BYTES = 1 * 1024 * 1024 * 1024
MAX_RELEASE_BYTES = 2 * 1024 * 1024 * 1024
SERVING_FILE_BYTE_LIMITS = {
    "queue.json": 8 * 1024 * 1024,
    "cases.json": 64 * 1024 * 1024,
    "operations.json": 32 * 1024 * 1024,
    "metrics.json": 1 * 1024 * 1024,
    "cases_raw.parquet": 512 * 1024 * 1024,
    "model/cohort-score-reference.json": 4 * 1024 * 1024,
    "model/model-contract.json": 4 * 1024 * 1024,
    "model/scaler.json": 4 * 1024 * 1024,
    "model/state_dict.pt": 256 * 1024 * 1024,
}
MAX_ARCHIVE_DECOMPRESSED_BYTES = (
    MAX_RELEASE_BYTES + MAX_MANIFEST_BYTES + (len(REQUIRED_RELEASE_FILES) + 4) * 1024
)
FORBIDDEN_VOLATILE_MANIFEST_KEYS = frozenset(
    {"created_at", "generated_at", "built_at", "timestamp", "published_at"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


class ReleaseError(RuntimeError):
    """Base class for detailed internal release failures."""


class ReleaseFormatError(ReleaseError):
    """A release or archive has an invalid shape or member type."""


class ReleaseIntegrityError(ReleaseError):
    """Release bytes do not match the declared identity or digest."""


class ReleaseCompatibilityError(ReleaseError):
    """A well-formed release uses an unsupported contract."""


def canonical_json_bytes(value: Any) -> bytes:
    """Encode canonical UTF-8 JSON, rejecting non-finite numbers."""
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseFormatError(f"value is not canonical JSON: {exc}") from exc
    return encoded.encode("utf-8")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseFormatError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ReleaseFormatError(f"JSON contains non-standard numeric constant {value}")


def parse_json_bytes(data: bytes, *, source: str = "JSON") -> Any:
    """Parse bounded UTF-8 JSON and reject duplicate object keys."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseFormatError(f"{source} is not UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except ReleaseFormatError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseFormatError(f"{source} is malformed JSON") from exc


def read_json_file(path: Path | str, *, max_bytes: int = MAX_MANIFEST_BYTES) -> Any:
    file_path = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(file_path, flags)
    except OSError as exc:
        raise ReleaseFormatError(f"cannot open {file_path.name}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ReleaseFormatError(f"{file_path.name} must be a regular file")
            if info.st_size > max_bytes:
                raise ReleaseFormatError(
                    f"{file_path.name} exceeds byte limit: expected <= {max_bytes}, observed {info.st_size}"
                )
            data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ReleaseFormatError(
                    f"{file_path.name} exceeds byte limit: expected <= {max_bytes}, observed > {max_bytes}"
                )
            return parse_json_bytes(data, source=file_path.name)
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseFormatError(f"cannot read {file_path.name}: {exc}") from exc


def sha256_stream(stream: BinaryIO, *, limit: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if limit is not None and total > limit:
            raise ReleaseFormatError(
                f"stream exceeds byte limit: expected <= {limit}, observed > {limit}"
            )
        digest.update(chunk)
    return digest.hexdigest(), total


def sha256_file(path: Path | str, *, limit: int | None = None) -> tuple[str, int]:
    try:
        with Path(path).open("rb") as handle:
            return sha256_stream(handle, limit=limit)
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseFormatError(f"cannot hash {Path(path).name}: {exc}") from exc


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReleaseFormatError(f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/") or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseFormatError(f"{field} is unsafe: {value!r}")
    normalized = path.as_posix()
    if normalized != value:
        raise ReleaseFormatError(f"{field} is not canonical: {value!r}")
    return normalized


def release_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("release_id", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:20]


def _find_volatile_manifest_key(value: Any, *, prefix: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_VOLATILE_MANIFEST_KEYS:
                return path
            found = _find_volatile_manifest_key(child, prefix=path)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_volatile_manifest_key(child, prefix=f"{prefix}[{index}]")
            if found is not None:
                return found
    return None


def validate_manifest_structure(
    manifest: Any,
    *,
    required_files: Iterable[str] = REQUIRED_RELEASE_FILES,
) -> dict[str, Any]:
    """Validate the schema-v2 manifest without touching release files."""
    if not isinstance(manifest, dict):
        raise ReleaseFormatError("release manifest must be a JSON object")
    for key in (
        "schema_version", "release_id", "files", "source", "scoring_contract",
        "online_input_contract",
    ):
        if key not in manifest:
            raise ReleaseFormatError(f"release manifest is missing {key!r}")
    volatile = _find_volatile_manifest_key(manifest)
    if volatile is not None:
        raise ReleaseFormatError(f"release manifest contains volatile identity field {volatile}")

    schema_version = manifest["schema_version"]
    if not _is_plain_int(schema_version):
        raise ReleaseFormatError("release manifest schema_version must be an integer")
    if schema_version != RELEASE_SCHEMA_VERSION:
        raise ReleaseCompatibilityError(
            f"unsupported release schema: expected {RELEASE_SCHEMA_VERSION}, observed {schema_version}"
        )

    release_id = manifest["release_id"]
    if not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id):
        raise ReleaseFormatError("release manifest release_id must be 20 lowercase hex characters")
    expected_id = release_id_for_manifest(manifest)
    if release_id != expected_id:
        raise ReleaseIntegrityError(
            f"release ID mismatch: expected {expected_id}, observed {release_id}"
        )

    if not isinstance(manifest["scoring_contract"], dict):
        raise ReleaseFormatError("release manifest scoring_contract must be an object")
    if not isinstance(manifest["online_input_contract"], dict):
        raise ReleaseFormatError("release manifest online_input_contract must be an object")
    if not isinstance(manifest["source"], dict) or not manifest["source"]:
        raise ReleaseFormatError("release manifest source must be a non-empty object")

    files = manifest["files"]
    if not isinstance(files, list):
        raise ReleaseFormatError("release manifest files must be an array")
    observed_paths: list[str] = []
    total_bytes = 0
    for index, record in enumerate(files):
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
            raise ReleaseFormatError(
                f"release manifest files[{index}] must contain exactly path, sha256, and bytes"
            )
        path = _validate_relative_path(record["path"], field=f"files[{index}].path")
        digest = record["sha256"]
        size = record["bytes"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ReleaseFormatError(f"release manifest digest for {path} is not lowercase SHA-256")
        if not _is_plain_int(size) or size < 0:
            raise ReleaseFormatError(f"release manifest byte length for {path} is invalid")
        if size > MAX_RELEASE_FILE_BYTES:
            raise ReleaseFormatError(
                f"release file {path} exceeds byte limit: expected <= {MAX_RELEASE_FILE_BYTES}, observed {size}"
            )
        serving_limit = SERVING_FILE_BYTE_LIMITS.get(path)
        if serving_limit is not None and size > serving_limit:
            raise ReleaseFormatError(
                f"release file {path} exceeds serving byte limit: "
                f"expected <= {serving_limit}, observed {size}"
            )
        observed_paths.append(path)
        total_bytes += size

    if observed_paths != sorted(observed_paths):
        raise ReleaseFormatError("release manifest files must be sorted by path")
    if len(observed_paths) != len(set(observed_paths)):
        raise ReleaseFormatError("release manifest contains duplicate file paths")
    expected_paths = sorted(_validate_relative_path(path, field="required file") for path in required_files)
    if observed_paths != expected_paths:
        missing = sorted(set(expected_paths) - set(observed_paths))
        extra = sorted(set(observed_paths) - set(expected_paths))
        raise ReleaseFormatError(f"release file allowlist mismatch: missing={missing}, extra={extra}")
    if total_bytes > MAX_RELEASE_BYTES:
        raise ReleaseFormatError(
            f"release exceeds byte limit: expected <= {MAX_RELEASE_BYTES}, observed {total_bytes}"
        )
    return manifest


def file_records(
    release_dir: Path | str,
    *,
    required_files: Iterable[str] = REQUIRED_RELEASE_FILES,
) -> list[dict[str, Any]]:
    base = Path(release_dir)
    records: list[dict[str, Any]] = []
    total = 0
    for relative in sorted(required_files):
        canonical = _validate_relative_path(relative, field="release file")
        path = base.joinpath(*PurePosixPath(canonical).parts)
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise ReleaseFormatError(f"release file {canonical} is missing: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ReleaseFormatError(f"release file {canonical} must be a regular file")
        digest, size = sha256_file(path, limit=MAX_RELEASE_FILE_BYTES)
        total += size
        if total > MAX_RELEASE_BYTES:
            raise ReleaseFormatError(
                f"release exceeds byte limit: expected <= {MAX_RELEASE_BYTES}, observed > {MAX_RELEASE_BYTES}"
            )
        records.append({"path": canonical, "sha256": digest, "bytes": size})
    return records


def finalize_manifest(payload: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Add sorted file records and the content-derived ID to a manifest payload."""
    manifest = copy.deepcopy(dict(payload))
    if "release_id" in manifest or "files" in manifest:
        raise ReleaseFormatError("manifest payload must not predefine release_id or files")
    manifest["files"] = sorted(copy.deepcopy(records), key=lambda item: item["path"])
    manifest["release_id"] = release_id_for_manifest(manifest)
    validate_manifest_structure(manifest)
    return manifest


def write_release_manifest(
    release_dir: Path | str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    base = Path(release_dir)
    manifest = finalize_manifest(payload, file_records(base))
    destination = base / MANIFEST_NAME
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(canonical_json_bytes(manifest) + b"\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _walk_release_entries(base: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    try:
        for root, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
            root_path = Path(root)
            for dirname in list(dirnames):
                path = root_path / dirname
                relative = path.relative_to(base).as_posix()
                if path.is_symlink():
                    raise ReleaseFormatError(f"release contains symlink directory {relative}")
                directories.add(relative)
            for filename in filenames:
                path = root_path / filename
                relative = path.relative_to(base).as_posix()
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ReleaseFormatError(f"release member {relative} must be a regular file")
                files.add(relative)
    except OSError as exc:
        raise ReleaseFormatError(f"cannot inspect release directory: {exc}") from exc
    return files, directories


def validate_release_directory(
    release_dir: Path | str,
    *,
    require_directory_name: bool = False,
) -> dict[str, Any]:
    """Validate exact layout, manifest identity, lengths, and hashes."""
    base = Path(release_dir)
    if not base.is_dir() or base.is_symlink():
        raise ReleaseFormatError(f"release path {base.name!r} must be a real directory")
    manifest = validate_manifest_structure(read_json_file(base / MANIFEST_NAME))
    release_id = manifest["release_id"]
    if require_directory_name and base.name != release_id:
        raise ReleaseIntegrityError(
            f"release directory mismatch for {release_id}: expected {release_id}, observed {base.name}"
        )

    expected_files = {MANIFEST_NAME, *(record["path"] for record in manifest["files"])}
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    observed_files, observed_directories = _walk_release_entries(base)
    if observed_files != expected_files or observed_directories != expected_directories:
        raise ReleaseFormatError(
            f"release layout mismatch for {release_id}: "
            f"missing_files={sorted(expected_files - observed_files)}, "
            f"extra_files={sorted(observed_files - expected_files)}, "
            f"extra_directories={sorted(observed_directories - expected_directories)}"
        )

    for record in manifest["files"]:
        relative = record["path"]
        digest, size = sha256_file(base.joinpath(*PurePosixPath(relative).parts), limit=MAX_RELEASE_FILE_BYTES)
        if size != record["bytes"]:
            raise ReleaseIntegrityError(
                f"release {release_id} file {relative} length mismatch: "
                f"expected {record['bytes']}, observed {size}"
            )
        if digest != record["sha256"]:
            raise ReleaseIntegrityError(
                f"release {release_id} file {relative} digest mismatch: "
                f"expected {record['sha256']}, observed {digest}"
            )
    return manifest


class ReleaseStore:
    """Own unique staging directories and same-filesystem immutable promotion."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.staging_root = self.root / ".staging"
        self.releases_root = self.root / "releases"

    def begin_staging(self) -> Path:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.releases_root.mkdir(parents=True, exist_ok=True)
        if self.staging_root.is_symlink() or self.releases_root.is_symlink():
            raise ReleaseFormatError("release store roots must not be symbolic links")
        return Path(tempfile.mkdtemp(prefix="release-", dir=self.staging_root))

    def _assert_owned_staging(self, staging: Path | str) -> Path:
        candidate = Path(staging)
        try:
            if candidate.is_symlink():
                raise ReleaseFormatError("staging directory must not be a symbolic link")
            resolved = candidate.resolve(strict=True)
            parent = self.staging_root.resolve(strict=True)
        except OSError as exc:
            raise ReleaseFormatError(f"invalid staging directory: {exc}") from exc
        if resolved.parent != parent or not resolved.is_dir() or resolved.is_symlink():
            raise ReleaseFormatError("staging directory is outside this release store")
        return resolved

    def discard_staging(self, staging: Path | str) -> None:
        candidate = self._assert_owned_staging(staging)
        shutil.rmtree(candidate)

    def promote(
        self,
        staging: Path | str,
        *,
        semantic_validator: Callable[[Path, Mapping[str, Any]], None],
        keep_failed_staging: bool = False,
    ) -> Path:
        candidate = self._assert_owned_staging(staging)
        try:
            manifest = validate_release_directory(candidate)
            semantic_validator(candidate, manifest)
            final_manifest = validate_release_directory(candidate)
            if canonical_json_bytes(final_manifest) != canonical_json_bytes(manifest):
                raise ReleaseIntegrityError(
                    f"release {manifest['release_id']} changed during semantic validation"
                )
            target = self.releases_root / manifest["release_id"]
            if target.exists():
                target_manifest = validate_release_directory(target, require_directory_name=True)
                if canonical_json_bytes(target_manifest) != canonical_json_bytes(manifest):
                    raise ReleaseIntegrityError(
                        f"release ID collision for {manifest['release_id']}: existing manifest differs"
                    )
                shutil.rmtree(candidate)
                return target
            # Both paths are children of the same store root.  rename is the visibility boundary.
            try:
                os.rename(candidate, target)
            except OSError as exc:
                # A concurrent identical builder may have won after the existence check.
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not target.exists():
                    raise
                target_manifest = validate_release_directory(target, require_directory_name=True)
                if canonical_json_bytes(target_manifest) != canonical_json_bytes(manifest):
                    raise ReleaseIntegrityError(
                        f"release ID collision for {manifest['release_id']}: existing manifest differs"
                    )
                shutil.rmtree(candidate)
                return target
            return target
        except Exception:
            if not keep_failed_staging and candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
            raise

    def build_release(
        self,
        writer: Callable[[Path], None],
        *,
        semantic_validator: Callable[[Path, Mapping[str, Any]], None],
        keep_failed_staging: bool = False,
    ) -> Path:
        staging = self.begin_staging()
        try:
            writer(staging)
            return self.promote(
                staging,
                semantic_validator=semantic_validator,
                keep_failed_staging=keep_failed_staging,
            )
        except Exception:
            if not keep_failed_staging and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise


def create_deterministic_archive(release_dir: Path | str, destination: Path | str) -> tuple[str, int]:
    """Write a byte-reproducible gzip-compressed tar of verified regular files."""
    base = Path(release_dir)
    manifest = validate_release_directory(base)
    members = sorted([MANIFEST_NAME, *(record["path"] for record in manifest["files"])])
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
                    for relative in members:
                        path = base.joinpath(*PurePosixPath(relative).parts)
                        size = path.stat().st_size
                        info = tarfile.TarInfo(relative)
                        info.size = size
                        info.mode = 0o644
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        with path.open("rb") as source:
                            archive.addfile(info, source)
        # Re-read the archive through the strict consumer boundary before publishing it.
        inspect_release_archive(temporary)
        os.replace(temporary, output)
        return sha256_file(output, limit=MAX_ARCHIVE_BYTES)
    finally:
        temporary.unlink(missing_ok=True)


def _validated_archive_members(
    archive: tarfile.TarFile,
) -> tuple[dict[str, tarfile.TarInfo], dict[str, Any]]:
    members: dict[str, tarfile.TarInfo] = {}
    maximum_members = len(REQUIRED_RELEASE_FILES) + 1
    declared_total = 0
    for index, info in enumerate(archive):
        if index >= maximum_members:
            raise ReleaseFormatError(f"archive has more than {maximum_members} members")
        name = _validate_relative_path(info.name, field="archive member")
        if name in members:
            raise ReleaseFormatError(f"archive contains duplicate member {name}")
        if not info.isreg():
            raise ReleaseFormatError(f"archive member {name} must be a regular file")
        if info.size < 0 or info.size > MAX_RELEASE_FILE_BYTES:
            raise ReleaseFormatError(f"archive member {name} has invalid size {info.size}")
        declared_total += info.size
        if declared_total > MAX_RELEASE_BYTES + MAX_MANIFEST_BYTES:
            raise ReleaseFormatError(
                f"archive members exceed decompression limit: expected <= "
                f"{MAX_RELEASE_BYTES + MAX_MANIFEST_BYTES}, observed > "
                f"{MAX_RELEASE_BYTES + MAX_MANIFEST_BYTES}"
            )
        members[name] = info

    manifest_info = members.get(MANIFEST_NAME)
    if manifest_info is None:
        raise ReleaseFormatError(f"archive is missing {MANIFEST_NAME}")
    if manifest_info.size > MAX_MANIFEST_BYTES:
        raise ReleaseFormatError(
            f"archive manifest exceeds byte limit: expected <= {MAX_MANIFEST_BYTES}, observed {manifest_info.size}"
        )
    handle = archive.extractfile(manifest_info)
    if handle is None:
        raise ReleaseFormatError("archive manifest is not readable")
    manifest_data = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(manifest_data) != manifest_info.size:
        raise ReleaseFormatError("archive manifest length does not match its header")
    manifest = validate_manifest_structure(parse_json_bytes(manifest_data, source=MANIFEST_NAME))
    expected = {MANIFEST_NAME, *(record["path"] for record in manifest["files"])}
    if set(members) != expected:
        raise ReleaseFormatError(
            f"archive allowlist mismatch for {manifest['release_id']}: "
            f"missing={sorted(expected - set(members))}, extra={sorted(set(members) - expected)}"
        )
    declared = {record["path"]: record for record in manifest["files"]}
    for name, record in declared.items():
        if members[name].size != record["bytes"]:
            raise ReleaseIntegrityError(
                f"archive {manifest['release_id']} member {name} length mismatch: "
                f"expected {record['bytes']}, observed {members[name].size}"
            )
    return members, manifest


@contextmanager
def _bounded_decompressed_tar(archive_file: BinaryIO):
    """Decompress to a bounded anonymous file before tar parses hidden extension records."""
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
                    raise ReleaseFormatError(
                        f"archive exceeds decompression limit: expected <= "
                        f"{MAX_ARCHIVE_DECOMPRESSED_BYTES}, observed > "
                        f"{MAX_ARCHIVE_DECOMPRESSED_BYTES}"
                    )
                decompressed.write(chunk)
        decompressed.seek(0)
        yield decompressed
    except ReleaseError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise ReleaseFormatError(f"cannot decompress release archive: {exc}") from exc
    finally:
        decompressed.close()


@contextmanager
def _verified_archive_file(path: Path, expected_sha256: str | None):
    """Hold one no-follow descriptor through hash verification and archive consumption."""
    if expected_sha256 is not None and not _SHA256_RE.fullmatch(expected_sha256):
        raise ReleaseFormatError("expected archive digest is not lowercase SHA-256")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReleaseFormatError(f"cannot open release archive: {exc}") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ReleaseFormatError("release archive must be a regular file")
            if info.st_size > MAX_ARCHIVE_BYTES:
                raise ReleaseFormatError(
                    f"archive exceeds byte limit: expected <= {MAX_ARCHIVE_BYTES}, observed {info.st_size}"
                )
            if expected_sha256 is not None:
                observed, _ = sha256_stream(handle, limit=MAX_ARCHIVE_BYTES)
                if observed != expected_sha256:
                    raise ReleaseIntegrityError(
                        f"archive digest mismatch: expected {expected_sha256}, observed {observed}"
                    )
                handle.seek(0)
            yield handle
            # Catch replacement-in-place or mutation while tarfile consumed the descriptor.
            if expected_sha256 is not None:
                handle.seek(0)
                observed, _ = sha256_stream(handle, limit=MAX_ARCHIVE_BYTES)
                if observed != expected_sha256:
                    raise ReleaseIntegrityError(
                        f"archive changed during verification: expected {expected_sha256}, observed {observed}"
                    )
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseFormatError(f"cannot read release archive: {exc}") from exc


def inspect_release_archive(
    archive_path: Path | str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate archive shape and member content without extracting it."""
    path = Path(archive_path)
    try:
        with _verified_archive_file(path, expected_sha256) as archive_file:
            with _bounded_decompressed_tar(archive_file) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r:") as archive:
                    members, manifest = _validated_archive_members(archive)
                    records = {record["path"]: record for record in manifest["files"]}
                    for name, record in records.items():
                        handle = archive.extractfile(members[name])
                        if handle is None:
                            raise ReleaseFormatError(f"archive member {name} is not readable")
                        digest, size = sha256_stream(handle, limit=MAX_RELEASE_FILE_BYTES)
                        if size != record["bytes"] or digest != record["sha256"]:
                            raise ReleaseIntegrityError(
                                f"archive {manifest['release_id']} member {name} digest mismatch: "
                                f"expected {record['sha256']}/{record['bytes']}, observed {digest}/{size}"
                            )
                    return manifest
    except ReleaseError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ReleaseFormatError(f"cannot read release archive: {exc}") from exc


def _open_exclusive_regular_file(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, "wb")


def extract_release_archive(
    archive_path: Path | str,
    target_dir: Path | str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Strictly extract to a sibling temp directory and atomically rename into place."""
    archive_path = Path(archive_path)
    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ReleaseFormatError(f"extraction target {target.name!r} already exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.extract-", dir=target.parent))
    try:
        with _verified_archive_file(archive_path, expected_sha256) as archive_file:
            with _bounded_decompressed_tar(archive_file) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r:") as archive:
                    members, manifest = _validated_archive_members(archive)
                    records = {record["path"]: record for record in manifest["files"]}
                    for name in sorted(members):
                        destination = temporary.joinpath(*PurePosixPath(name).parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(members[name])
                        if source is None:
                            raise ReleaseFormatError(f"archive member {name} is not readable")
                        with _open_exclusive_regular_file(destination) as output:
                            digest = hashlib.sha256()
                            copied = 0
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                copied += len(chunk)
                                if copied > members[name].size:
                                    raise ReleaseIntegrityError(f"archive member {name} exceeds declared length")
                                output.write(chunk)
                                digest.update(chunk)
                        if copied != members[name].size:
                            raise ReleaseIntegrityError(f"archive member {name} is truncated")
                        if name != MANIFEST_NAME and digest.hexdigest() != records[name]["sha256"]:
                            raise ReleaseIntegrityError(
                                f"archive {manifest['release_id']} member {name} digest mismatch: "
                                f"expected {records[name]['sha256']}, observed {digest.hexdigest()}"
                            )
        validated = validate_release_directory(temporary)
        os.rename(temporary, target)
        return validated
    except ReleaseError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ReleaseFormatError(f"cannot extract release archive: {exc}") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
