"""Console entrypoint that defers production composition until server import."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sadar-api",
        description="Serve the SADAR Analyst Console from explicit runtime settings.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--access-log", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65_535:
        raise SystemExit("PORT must be an integer from 1 to 65535")
    if args.workers != 1:
        raise SystemExit("SADAR currently requires exactly one worker")
    uvicorn.run(
        "sadar.api.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        access_log=args.access_log,
    )
