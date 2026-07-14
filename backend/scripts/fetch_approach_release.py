"""Fetch and atomically install the locked public schema-v3 approach release."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from backend.scripts import fetch_demo_bundle as fetching
from backend.serve import approach_transport


ARCHIVE_NAME = "sadar-approach-release.tar.gz"


def fetch_locked_release(
    *,
    lock_path: Path | str,
    destination: Path | str,
    downloader: fetching.ArtifactDownloader = fetching.download_public_artifact,
) -> dict[str, Any]:
    return fetching.fetch_locked_release(
        lock_path=lock_path,
        destination=destination,
        downloader=downloader,
        contract=approach_transport,
        expected_schema_version=approach_transport.RELEASE_SCHEMA_VERSION,
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
        manifest = fetch_locked_release(
            lock_path=args.lock,
            destination=args.destination,
        )
    except Exception as exc:
        message = (str(exc) or exc.__class__.__name__)[: fetching.MAX_ERROR_MESSAGE]
        print(f"approach release fetch failed: {message}", file=sys.stderr)
        return 1
    print(f"installed approach release {manifest['release_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
