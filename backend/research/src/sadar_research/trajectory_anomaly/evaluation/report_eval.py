"""Opt-in golden-case eval for the analysis-report prompt (NOT in the pytest suite).

Runs ~3 representative baked cases through the LIVE model and asserts PROPERTIES, not exact
text (codex outside-voice): a data-quality artifact must be named as such; a real anomaly must
read as a deviation; and prohibited claims (drone / unauthorized / intruder / violation /
intent) must never appear. Run before deploy or after editing SYSTEM_PROMPT:

    cd backend && ANTHROPIC_API_KEY=... uv run python -m serve.report_eval

Exits non-zero if any golden case fails. Key-gated + manual so it never flakes/bills CI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sadar_research.trajectory_anomaly.evaluation import report as rpt  # noqa: E402

PROHIBITED = rpt.PROHIBITED_CLAIMS


def pick_goldens(cases: dict) -> list[tuple[str, dict]]:
    """One of each: a non-terminal artifact, a held-aside anomaly, a clean terminal op."""
    artifact = next((c for c in cases.values() if not c.get("terminal_op")), None)
    anomaly = next((c for c in cases.values() if c.get("label") in ("go_around", "emergency")), None)
    terminal = next((c for c in cases.values()
                     if c.get("terminal_op") and c.get("label") == "normal"), None)
    return [(n, c) for n, c in
            [("artifact", artifact), ("anomaly", anomaly), ("terminal", terminal)] if c]


def check(kind: str, case: dict, text: str) -> list[str]:
    low = text.lower()
    fails = []
    hits = [w for w in PROHIBITED if w in low]
    if hits:
        fails.append(f"prohibited claim(s) present: {hits}")
    if kind == "artifact" and not any(
        w in low for w in ("artifact", "artefact", "data", "coverage", "overflight",
                            "neighbour", "neighbor", "truncat", "transit", "not a lemd")):
        fails.append("artifact case did not flag a data/coverage caveat")
    if kind == "anomaly" and not any(
        w in low for w in ("deviat", "anomal", "go-around", "go around", "elevated", "unusual")):
        fails.append("anomaly case did not read as a deviation")
    return fails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate historical report guardrails")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    if args.env_file is not None:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    client = rpt.make_client()
    if client is None:
        print("ANTHROPIC_API_KEY not set — cannot run the live eval.")
        return 2
    cases = json.loads((args.bundle / "cases.json").read_text())
    manifest = json.loads((args.bundle / "manifest.json").read_text())
    thr, step_thr = manifest["threshold"], manifest["step_threshold"]
    model = rpt.model_name()
    ok = True
    for kind, case in pick_goldens(cases):
        text = rpt.generate_report(client, case, thr, step_thr, model)
        fails = check(kind, case, text)
        status = "PASS" if not fails else "FAIL"
        if fails:
            ok = False
        print(f"\n=== {kind} · {case['segment_id']} · {status} ===")
        for f in fails:
            print(f"  ✗ {f}")
        print(text)
    print("\n" + ("ALL GOLDEN CASES PASS" if ok else "GOLDEN EVAL FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
