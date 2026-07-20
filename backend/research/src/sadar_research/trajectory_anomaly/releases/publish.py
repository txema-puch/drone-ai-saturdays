"""Publish the immutable historical schema-v2 trajectory-anomaly release."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sadar.releases import hub_publish

from . import schema


LOCK_NAME = "demo_bundle.lock.json"
ARTIFACT_NAME = "sadar-demo-bundle.tar.gz"
DEFAULT_ARTIFACT_NAME = ARTIFACT_NAME
PublicationError = hub_publish.PublicationError
UploadedArtifact = hub_publish.UploadedArtifact
ArtifactUploader = hub_publish.ArtifactUploader
ArtifactDownloader = hub_publish.ArtifactDownloader
assert_clean_git_tree = hub_publish.assert_clean_git_tree


def validate_lock_record(value: object) -> dict[str, object]:
    return hub_publish.validate_lock_record(
        value,
        expected_schema_version=schema.RELEASE_SCHEMA_VERSION,
    )


def download_public_artifact(url: str, destination: Path) -> None:
    hub_publish.download_public_artifact(
        url,
        destination,
        max_archive_bytes=schema.MAX_ARCHIVE_BYTES,
    )


def publish_release(
    *,
    release_dir: Path | str,
    lock_path: Path | str,
    repository_root: Path | str,
    uploader: hub_publish.ArtifactUploader,
    downloader: hub_publish.ArtifactDownloader,
    clean_tree_check=hub_publish.assert_clean_git_tree,
    clock=lambda: datetime.now(UTC),
) -> dict[str, object]:
    return hub_publish.publish_release(
        release_dir=release_dir,
        lock_path=lock_path,
        repository_root=repository_root,
        uploader=uploader,
        downloader=downloader,
        clean_tree_check=clean_tree_check,
        clock=clock,
        contract=schema,
        schema_version=schema.RELEASE_SCHEMA_VERSION,
        lock_name=LOCK_NAME,
        artifact_name=ARTIFACT_NAME,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--hf-repo-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("HF_TOKEN", "")
    try:
        uploader = hub_publish.hugging_face_uploader(
            repo_id=args.hf_repo_id,
            artifact_name=ARTIFACT_NAME,
            token=token,
            repo_type="model",
        )
        record = publish_release(
            release_dir=args.release_dir,
            lock_path=args.lock,
            repository_root=args.repository_root,
            uploader=uploader,
            downloader=download_public_artifact,
        )
    except Exception as exc:
        message = hub_publish.safe_error_message(exc, secret=token)
        print(f"historical publication failed: {message}", file=sys.stderr)
        return 1
    print(f"published historical release {record['release_id']} at {record['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
