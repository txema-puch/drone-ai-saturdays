#!/usr/bin/env python3
"""Static, network-free checks for the clean-checkout delivery boundary."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "backend/serve/requirements-linux-x86_64.lock"
INPUT = ROOT / "backend/serve/requirements.in"
ENTRYPOINT = ROOT / "scripts/container-entrypoint.sh"


def fail(message: str) -> None:
    print(f"delivery contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    for path in (DOCKERFILE, LOCK, INPUT, ENTRYPOINT):
        if not path.is_file():
            fail(f"missing tracked input: {path.relative_to(ROOT)}")
    if (ROOT / "backend/Dockerfile").exists():
        fail("legacy backend/Dockerfile must stay retired")

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    image_args = re.findall(
        r'^ARG ([A-Z_]+_IMAGE)="([^"\s]+@sha256:[0-9a-f]{64})"$',
        dockerfile,
        flags=re.MULTILINE,
    )
    if {name for name, _ in image_args} != {
        "NODE_IMAGE",
        "PYTHON_IMAGE",
        "UV_IMAGE",
    }:
        fail("Node, Python, and uv image arguments must use sha256 digests")

    from_lines = re.findall(r"^FROM .*", dockerfile, flags=re.MULTILINE)
    if not from_lines or any("--platform=linux/amd64" not in line for line in from_lines):
        fail("every build stage must target linux/amd64")
    required_fragments = (
        "AS frontend-build",
        "AS python-deps",
        "AS release-fetch",
        "AS runtime",
        "USER 1000:1000",
        "EXPOSE 7860",
        "SADAR_RELEASE_DIR=/opt/sadar/release",
        'ENTRYPOINT ["/usr/local/bin/sadar-entrypoint"]',
    )
    for fragment in required_fragments:
        if fragment not in dockerfile:
            fail(f"Dockerfile is missing {fragment!r}")
    if re.search(r"\b(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\b", dockerfile):
        fail("publisher token names must not cross the Docker build boundary")

    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for fragment in ('${PORT:-7860}', "backend.serve.app:app", "--workers 1"):
        if fragment not in entrypoint:
            fail(f"container entrypoint is missing {fragment!r}")

    lock = LOCK.read_text(encoding="utf-8")
    requirements = list(re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==[^\s\\]+ \\\n", lock))
    if len(requirements) < 20:
        fail("serving lock is unexpectedly small or malformed")
    for index, match in enumerate(requirements):
        end = requirements[index + 1].start() if index + 1 < len(requirements) else len(lock)
        if "--hash=sha256:" not in lock[match.end() : end]:
            fail(f"{match.group(1)} has no artifact hash")

    direct = {
        match.group(1).lower()
        for match in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==", INPUT.read_text(encoding="utf-8"))
    }
    expected = {
        "fastapi",
        "numpy",
        "pandas",
        "pyarrow",
        "python-multipart",
        "scikit-learn",
        "torch",
        "uvicorn",
    }
    if direct != expected:
        fail(f"unexpected direct serving requirements: {sorted(direct ^ expected)}")

    print(f"delivery contract: ok ({len(requirements)} locked packages)")


if __name__ == "__main__":
    main()
