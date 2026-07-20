"""Publish and redownload-verify one immutable schema-v4 public evidence release."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sadar.releases import archive as approach_transport
from sadar.releases import hub_publish as publication


LOCK_NAME = "approach_bundle.lock.json"
REPOSITORY_ID = "Txemapuch/sadar-analyst-console-release"
REPOSITORY_TYPE = "dataset"
ARTIFACT_NAME = "sadar-approach-public-release.tar.gz"


def publish_release(
    *,
    release_dir: Path | str,
    lock_path: Path | str,
    repository_root: Path | str,
    uploader: publication.ArtifactUploader,
    downloader: publication.ArtifactDownloader,
    clean_tree_check=publication.assert_clean_git_tree,
    clock=lambda: datetime.now(UTC),
) -> dict[str, object]:
    return publication.publish_release(
        release_dir=release_dir,
        lock_path=lock_path,
        repository_root=repository_root,
        uploader=uploader,
        downloader=downloader,
        clean_tree_check=clean_tree_check,
        clock=clock,
        contract=approach_transport,
        schema_version=approach_transport.RELEASE_SCHEMA_VERSION,
        lock_name=LOCK_NAME,
        artifact_name=ARTIFACT_NAME,
        repo_type=REPOSITORY_TYPE,
        expected_repo_id=REPOSITORY_ID,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--hf-repo-id", required=True)
    parser.add_argument("--artifact-name", default=ARTIFACT_NAME)
    parser.add_argument("--repo-type", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = ""
    if args.repo_type != REPOSITORY_TYPE:
        print("publication failed: repo type must be dataset", file=sys.stderr)
        return 1
    if args.hf_repo_id != REPOSITORY_ID:
        print(f"publication failed: repository must be {REPOSITORY_ID}", file=sys.stderr)
        return 1
    if args.artifact_name != ARTIFACT_NAME:
        print(f"publication failed: artifact name must be {ARTIFACT_NAME}", file=sys.stderr)
        return 1
    try:
        token = publication.resolve_hugging_face_token()
        uploader = publication.hugging_face_uploader(
            repo_id=args.hf_repo_id,
            artifact_name=ARTIFACT_NAME,
            token=token,
            repo_type=REPOSITORY_TYPE,
        )
        record = publish_release(
            release_dir=args.release_dir,
            lock_path=args.lock,
            repository_root=args.repository_root,
            uploader=uploader,
            downloader=publication.download_public_artifact,
        )
    except Exception as exc:
        print(
            f"publication failed: {publication.safe_error_message(exc, secret=token)}",
            file=sys.stderr,
        )
        return 1
    print(f"published release {record['release_id']} at immutable revision {record['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
