"""Fail-closed migration shim for the retired raw-data public release builder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


MIGRATION_MESSAGE = (
    "raw-data public release assembly is retired; run the research evaluation "
    "commands, then sadar-project-public-aggregates and sadar-build-release"
)


def build_contextual_release(input_path: Path, **_kwargs: Any) -> dict[str, Any]:
    """Refuse before opening or inspecting the supplied raw input path."""
    del input_path
    raise RuntimeError(MIGRATION_MESSAGE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--weather-dir", type=Path)
    parser.add_argument("--aircraft-parts-dir", type=Path)
    parser.add_argument("--max-case-observations", type=int)
    parser.parse_args(argv)
    print(MIGRATION_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
