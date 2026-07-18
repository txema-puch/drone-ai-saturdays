"""Build deterministic synthetic analyst demo payloads."""

from __future__ import annotations

import argparse
from pathlib import Path

from sadar.demo.catalog import DEFAULT_SEED, generate_demo_payloads
from sadar.pipelines.build_release import _methodology_payloads
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
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must not already contain files")
    methodology = _methodology_payloads(reference_path=reference_path)
    payloads = generate_demo_payloads(seed=seed, methodology_payloads=methodology)
    demo = output / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (demo / name).write_bytes(canonical_json_bytes(payload))
    return payloads


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    build_synthetic_demo(output=args.output, seed=args.seed, reference_path=args.reference)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
