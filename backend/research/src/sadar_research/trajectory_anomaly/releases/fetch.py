"""Install the immutable historical schema-v2 trajectory-anomaly release."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from sadar.releases import hub_fetch

from . import schema


ARCHIVE_NAME = "sadar-demo-bundle.tar.gz"
FetchError = hub_fetch.FetchError
MAX_LOCK_BYTES = hub_fetch.MAX_LOCK_BYTES


def validate_lock_record(value: object) -> dict[str, object]:
    return hub_fetch.validate_lock_record(
        value,
        expected_schema_version=schema.RELEASE_SCHEMA_VERSION,
    )


def read_lock(path: Path | str) -> dict[str, object]:
    return hub_fetch.read_lock(
        path,
        contract=schema,
        expected_schema_version=schema.RELEASE_SCHEMA_VERSION,
    )


def download_public_artifact(url: str, destination: Path) -> None:
    hub_fetch.download_public_artifact(
        url,
        destination,
        max_archive_bytes=schema.MAX_ARCHIVE_BYTES,
    )


def fetch_locked_release(
    *,
    lock_path: Path | str,
    destination: Path | str,
    downloader: hub_fetch.ArtifactDownloader = download_public_artifact,
) -> dict[str, Any]:
    return hub_fetch.fetch_locked_release(
        lock_path=lock_path,
        destination=destination,
        downloader=downloader,
        contract=schema,
        expected_schema_version=schema.RELEASE_SCHEMA_VERSION,
        archive_name=ARCHIVE_NAME,
    )


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
        message = (str(exc) or exc.__class__.__name__)[: hub_fetch.MAX_ERROR_MESSAGE]
        print(f"historical release fetch failed: {message}", file=sys.stderr)
        return 1
    print(f"installed historical release {manifest['release_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
