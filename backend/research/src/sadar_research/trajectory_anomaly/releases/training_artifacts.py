"""Safely install the immutable Phase-6 historical training artifacts."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from sadar.releases import hub_fetch

from . import schema


LOCK_SCHEMA = "sadar_phase6_training_artifacts_lock_v1"
MANIFEST_SCHEMA = "sadar_phase6_training_artifacts_v1"
RESEARCH_TRACK = "trajectory-anomaly"
ARCHIVE_NAME = "sadar-phase6-training-artifacts.tar.gz"
ARCHIVE_PATH = ("research", "trajectory-anomaly", "phase6", ARCHIVE_NAME)
MANIFEST_NAME = "artifact-manifest.json"
ALLOWED_FILES = frozenset({"knn_train_summary.npy", "lstm_ae_best.pt", "scaler.joblib"})
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
LOCK_KEYS = frozenset(
    {"archive_sha256", "files", "research_track", "revision", "schema_version", "url"}
)
MANIFEST_KEYS = frozenset(
    {"files", "phase", "research_track", "schema_version", "source_commit"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$")


class TrainingArtifactError(RuntimeError):
    """The historical training archive failed its locked contract."""


def _public_url(value: object, *, revision: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > hub_fetch.MAX_URL_BYTES:
        raise TrainingArtifactError("training-artifact URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TrainingArtifactError("training-artifact URL is invalid") from exc
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "huggingface.co"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 8
        or parts[2:4] != ("resolve", revision)
        or parts[4:] != ARCHIVE_PATH
        or not _REPOSITORY_RE.fullmatch(parts[0])
        or not _REPOSITORY_RE.fullmatch(parts[1])
    ):
        raise TrainingArtifactError(
            "training-artifact URL must be immutable public Hugging Face storage"
        )
    return value


def _file_records(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or len(value) != len(ALLOWED_FILES):
        raise TrainingArtifactError("training-artifact file list is invalid")
    records: list[dict[str, object]] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"bytes", "path", "sha256"}:
            raise TrainingArtifactError("training-artifact file record is invalid")
        path, size, digest = item["path"], item["bytes"], item["sha256"]
        if (
            not isinstance(path, str)
            or path not in ALLOWED_FILES
            or path in names
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 < size <= MAX_FILE_BYTES
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
        ):
            raise TrainingArtifactError("training-artifact file record is invalid")
        names.add(path)
        records.append({"bytes": size, "path": path, "sha256": digest})
    if names != ALLOWED_FILES:
        raise TrainingArtifactError("training-artifact file allowlist is incomplete")
    return tuple(sorted(records, key=lambda record: str(record["path"])))


def validate_lock(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        raise TrainingArtifactError("training-artifact lock schema is invalid")
    revision = value["revision"]
    digest = value["archive_sha256"]
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise TrainingArtifactError("training-artifact revision must be immutable")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise TrainingArtifactError("training-artifact archive digest is invalid")
    if value["schema_version"] != LOCK_SCHEMA or value["research_track"] != RESEARCH_TRACK:
        raise TrainingArtifactError("training-artifact lock identity is invalid")
    return {
        "archive_sha256": digest,
        "files": _file_records(value["files"]),
        "research_track": RESEARCH_TRACK,
        "revision": revision,
        "schema_version": LOCK_SCHEMA,
        "url": _public_url(value["url"], revision=revision),
    }


def read_lock(path: Path | str) -> dict[str, object]:
    try:
        value = hub_fetch.read_bounded_json_lock(path, contract=schema)
    except Exception as exc:
        raise TrainingArtifactError("cannot read training-artifact lock") from exc
    return validate_lock(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(value: object, *, expected_files: tuple[dict[str, object], ...]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise TrainingArtifactError("training-artifact manifest schema is invalid")
    source_commit = value["source_commit"]
    if (
        value["schema_version"] != MANIFEST_SCHEMA
        or value["research_track"] != RESEARCH_TRACK
        or value["phase"] != "train"
        or not isinstance(source_commit, str)
        or not _REVISION_RE.fullmatch(source_commit)
        or _file_records(value["files"]) != expected_files
    ):
        raise TrainingArtifactError("training-artifact manifest identity is invalid")
    return value


def _members(
    archive: tarfile.TarFile,
    *,
    expected_files: tuple[dict[str, object], ...],
) -> tuple[dict[str, tarfile.TarInfo], dict[str, Any]]:
    members = archive.getmembers()
    expected_names = {MANIFEST_NAME, *ALLOWED_FILES}
    if (
        len(members) != len(expected_names)
        or {member.name for member in members} != expected_names
        or any(not member.isreg() for member in members)
    ):
        raise TrainingArtifactError("training-artifact archive layout is invalid")
    by_name = {member.name: member for member in members}
    records = {str(record["path"]): record for record in expected_files}
    if by_name[MANIFEST_NAME].size < 1 or by_name[MANIFEST_NAME].size > MAX_MANIFEST_BYTES:
        raise TrainingArtifactError("training-artifact manifest size is invalid")
    if any(by_name[name].size != records[name]["bytes"] for name in ALLOWED_FILES):
        raise TrainingArtifactError("training-artifact member length mismatch")
    handle = archive.extractfile(by_name[MANIFEST_NAME])
    if handle is None:
        raise TrainingArtifactError("training-artifact manifest is unreadable")
    data = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(data) != by_name[MANIFEST_NAME].size:
        raise TrainingArtifactError("training-artifact manifest is truncated")
    try:
        value = schema.parse_json_bytes(data, source=MANIFEST_NAME)
    except Exception as exc:
        raise TrainingArtifactError("training-artifact manifest is malformed") from exc
    if schema.canonical_json_bytes(value) != data:
        raise TrainingArtifactError("training-artifact manifest is not canonical JSON")
    return by_name, _manifest(value, expected_files=expected_files)


def install_archive(
    archive_path: Path | str,
    destination: Path | str,
    *,
    lock: dict[str, object],
) -> dict[str, Any]:
    archive_file = Path(archive_path)
    if archive_file.is_symlink() or not archive_file.is_file():
        raise TrainingArtifactError("training-artifact archive must be a regular file")
    if archive_file.stat().st_size > MAX_ARCHIVE_BYTES:
        raise TrainingArtifactError("training-artifact archive exceeds its byte limit")
    if _sha256(archive_file) != lock["archive_sha256"]:
        raise TrainingArtifactError("training-artifact archive digest mismatch")
    try:
        target = hub_fetch.safe_destination(destination)
    except Exception as exc:
        raise TrainingArtifactError("training-artifact destination is unsafe") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.extract-", dir=target.parent))
    try:
        with tarfile.open(archive_file, mode="r:gz") as archive:
            members, manifest = _members(
                archive, expected_files=lock["files"]  # type: ignore[arg-type]
            )
            records = {str(record["path"]): record for record in lock["files"]}  # type: ignore[union-attr]
            for name in [MANIFEST_NAME, *sorted(ALLOWED_FILES)]:
                handle = archive.extractfile(members[name])
                if handle is None:
                    raise TrainingArtifactError(f"training-artifact member is unreadable: {name}")
                data = handle.read(members[name].size + 1)
                if len(data) != members[name].size:
                    raise TrainingArtifactError(f"training-artifact member is truncated: {name}")
                if name != MANIFEST_NAME and hashlib.sha256(data).hexdigest() != records[name]["sha256"]:
                    raise TrainingArtifactError(f"training-artifact member digest mismatch: {name}")
                path = temporary / name
                with path.open("xb") as output:
                    output.write(data)
        os.rename(temporary, target)
        return manifest
    except TrainingArtifactError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise TrainingArtifactError("cannot install training-artifact archive") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def fetch_locked_training_artifacts(
    *,
    lock_path: Path | str,
    destination: Path | str,
    downloader=hub_fetch.download_public_artifact,
) -> dict[str, Any]:
    lock = read_lock(lock_path)
    try:
        target = hub_fetch.safe_destination(destination)
    except Exception as exc:
        raise TrainingArtifactError("training-artifact destination is unsafe") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    working = Path(tempfile.mkdtemp(prefix=".sadar-training-fetch-", dir=target.parent))
    try:
        archive = working / ARCHIVE_NAME
        downloader(str(lock["url"]), archive, max_archive_bytes=MAX_ARCHIVE_BYTES)
        return install_archive(archive, target, lock=lock)
    finally:
        shutil.rmtree(working, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = fetch_locked_training_artifacts(
            lock_path=args.lock,
            destination=args.destination,
        )
    except Exception as exc:
        message = (str(exc) or exc.__class__.__name__)[: hub_fetch.MAX_ERROR_MESSAGE]
        print(f"training-artifact fetch failed: {message}", file=sys.stderr)
        return 1
    print(f"installed {manifest['research_track']} Phase-6 training artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
