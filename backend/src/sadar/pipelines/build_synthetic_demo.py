"""Build deterministic synthetic analyst demo payloads."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from sadar.demo.catalog import DEFAULT_SEED, generate_demo_payloads
from sadar.pipelines.build_release import methodology_payloads
from sadar.releases.approach import canonical_json_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--reference", type=Path)
    return parser


def build_synthetic_demo(
    *, output: Path, seed: int, reference_path: Path | None = None
) -> dict[str, object]:
    output = Path(output)
    if output.is_symlink():
        raise ValueError("output must not be a symlink")
    if output.exists():
        if not output.is_dir():
            raise ValueError("output must be a directory")
        if any(output.iterdir()):
            raise ValueError("output directory must not already contain files")

    methodology = methodology_payloads(reference_path=reference_path)
    payloads = generate_demo_payloads(seed=seed, methodology_payloads=methodology)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    candidate = temporary_root / "corpus"
    demo = candidate / "demo"
    try:
        demo.mkdir(parents=True)
        for name, payload in payloads.items():
            path = demo / name
            with path.open("xb") as handle:
                handle.write(canonical_json_bytes(payload))
                handle.flush()
                os.fsync(handle.fileno())
        _fsync_directory(demo)
        _fsync_directory(candidate)

        # Recheck immediately before the atomic install. A raced-in symlink is
        # rejected instead of followed; a raced-in non-empty directory makes
        # os.replace fail without exposing a partial corpus.
        if output.is_symlink():
            raise ValueError("output must not be a symlink")
        if output.exists() and (
            not output.is_dir() or any(output.iterdir())
        ):
            raise ValueError("output directory must not already contain files")
        os.replace(candidate, output)
        _fsync_directory(output.parent)
        return payloads
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    build_synthetic_demo(output=args.output, seed=args.seed, reference_path=args.reference)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
