#!/usr/bin/env python3
"""Static, network-free checks for the clean-checkout delivery boundary."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "delivery/container/requirements-linux-x86_64.lock"
PYPROJECT = ROOT / "backend/pyproject.toml"
ENTRYPOINT = ROOT / "scripts/container-entrypoint.sh"
README = ROOT / "README.md"
FRONTEND_INDEX = ROOT / "frontend/index.html"
FRONTEND_PACKAGE = ROOT / "frontend/package.json"
FRONTEND_LOCK = ROOT / "frontend/package-lock.json"
FLY_CONFIG = ROOT / "fly.toml"
FLY_DEPLOY = ROOT / "scripts/deploy-fly.sh"
PRODUCT_TITLE = "SADAR Analyst Console"
PACKAGE_NAME = "sadar-analyst-console"
FLY_APP = "sadar-analyst-console"


def fail(message: str) -> None:
    print(f"delivery contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_product_identity(
    *,
    readme: str,
    frontend_index: str,
    package: dict,
    package_lock: dict,
) -> None:
    if not readme.startswith(f"# {PRODUCT_TITLE}\n"):
        fail("README heading must match the public product identity")

    if f"<title>{PRODUCT_TITLE}</title>" not in frontend_index:
        fail("browser title must match the public product identity")
    if "SADAR Analyst Console — evaluate and investigate" not in frontend_index:
        fail("browser description must identify the analyst console")

    if package.get("name") != PACKAGE_NAME:
        fail("frontend package name must match the public product identity")
    if package_lock.get("name") != package["name"]:
        fail("frontend package-lock identity must match package.json")


def validate_fly_config(fly_config: str) -> None:
    try:
        config = tomllib.loads(fly_config)
    except tomllib.TOMLDecodeError as exc:
        fail(f"Fly deployment config must be valid TOML: {exc}")

    build = config.get("build") if isinstance(config.get("build"), dict) else {}
    env = config.get("env") if isinstance(config.get("env"), dict) else {}
    service = (
        config.get("http_service")
        if isinstance(config.get("http_service"), dict)
        else {}
    )
    concurrency = (
        service.get("concurrency")
        if isinstance(service.get("concurrency"), dict)
        else {}
    )
    checks = service.get("checks") if isinstance(service.get("checks"), list) else []
    health_path = checks[0].get("path") if len(checks) == 1 and isinstance(checks[0], dict) else None
    vms = config.get("vm") if isinstance(config.get("vm"), list) else []
    vm = vms[0] if len(vms) == 1 and isinstance(vms[0], dict) else {}

    required = {
        "app identity": (config.get("app"), FLY_APP),
        "primary region": (config.get("primary_region"), "cdg"),
        "Docker build target": (build.get("dockerfile"), "Dockerfile"),
        "runtime port": (env.get("PORT"), "7860"),
        "evaluation capability": (env.get("SADAR_ENABLE_EVALUATION"), "true"),
        "internal port": (service.get("internal_port"), 7860),
        "HTTPS redirect": (service.get("force_https"), True),
        "default process routing": (service.get("processes"), ["app"]),
        "idle suspension": (service.get("auto_stop_machines"), "suspend"),
        "automatic resume": (service.get("auto_start_machines"), True),
        "zero warm instances": (service.get("min_machines_running"), 0),
        "health endpoint": (health_path, "/api/health"),
        "request concurrency type": (concurrency.get("type"), "requests"),
        "read concurrency soft limit": (concurrency.get("soft_limit"), 20),
        "read concurrency hard limit": (concurrency.get("hard_limit"), 25),
        "shared CPU kind": (vm.get("cpu_kind"), "shared"),
        "single shared CPU": (vm.get("cpus"), 1),
        "two GiB memory": (vm.get("memory"), "2gb"),
    }
    for label, (observed, expected) in required.items():
        if observed != expected:
            fail(f"Fly deployment must preserve {label}")


def validate_fly_deploy_script(deploy_script: str) -> None:
    if '"$@"' in deploy_script:
        fail("Fly deploy script must not allow protected flag overrides")
    required = {
        "Fly deploy command": "exec fly deploy",
        "clean-worktree guard": "git status --porcelain",
        "default app identity": 'app="${FLY_APP:-sadar-analyst-console}"',
        "committed source revision": 'source_commit="$(git rev-parse HEAD)"',
        "remote builder": "--remote-only",
        "single-Machine deployment": "--ha=false",
        "explicit app selection": '--app "$app"',
        "source revision label": '--build-arg "SOURCE_COMMIT=$source_commit"',
    }
    for label, fragment in required.items():
        if fragment not in deploy_script:
            fail(f"Fly deploy script must preserve {label}")


def main() -> None:
    for path in (
        DOCKERFILE,
        LOCK,
        PYPROJECT,
        ENTRYPOINT,
        README,
        FRONTEND_INDEX,
        FRONTEND_PACKAGE,
        FRONTEND_LOCK,
        FLY_CONFIG,
        FLY_DEPLOY,
    ):
        if not path.is_file():
            fail(f"missing tracked input: {path.relative_to(ROOT)}")
    if (ROOT / "backend/Dockerfile").exists():
        fail("legacy backend/Dockerfile must stay retired")
    if not FLY_DEPLOY.stat().st_mode & 0o111:
        fail("Fly deploy script must be executable")

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
        "AS product-wheel",
        "AS release-fetch",
        "AS runtime",
        "USER 1000:1000",
        "EXPOSE 7860",
        "SADAR_APPROACH_RELEASE_DIR=/opt/sadar/release",
        "SADAR_FRONTEND_DIR=/opt/sadar/frontend",
        'ENTRYPOINT ["/usr/local/bin/sadar-entrypoint"]',
    )
    for fragment in required_fragments:
        if fragment not in dockerfile:
            fail(f"Dockerfile is missing {fragment!r}")
    if re.search(r"\b(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\b", dockerfile):
        fail("publisher token names must not cross the Docker build boundary")
    forbidden_runtime = (
        "backend/core",
        "backend/serve",
        "backend/research/src",
        "PYTHONPATH=",
    )
    if any(fragment in dockerfile for fragment in forbidden_runtime):
        fail("runtime image must contain only the installed product wheel")

    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for fragment in ('${PORT:-7860}', "exec sadar-api", "--workers 1"):
        if fragment not in entrypoint:
            fail(f"container entrypoint is missing {fragment!r}")

    validate_product_identity(
        readme=README.read_text(encoding="utf-8"),
        frontend_index=FRONTEND_INDEX.read_text(encoding="utf-8"),
        package=json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8")),
        package_lock=json.loads(FRONTEND_LOCK.read_text(encoding="utf-8")),
    )
    validate_fly_config(FLY_CONFIG.read_text(encoding="utf-8"))
    validate_fly_deploy_script(FLY_DEPLOY.read_text(encoding="utf-8"))

    lock = LOCK.read_text(encoding="utf-8")
    requirements = list(re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==[^\s\\]+ \\\n", lock))
    if len(requirements) != 26:
        fail("model-free serving lock package count drifted")
    for index, match in enumerate(requirements):
        end = requirements[index + 1].start() if index + 1 < len(requirements) else len(lock)
        if "--hash=sha256:" not in lock[match.end() : end]:
            fail(f"{match.group(1)} has no artifact hash")

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    direct = {
        re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0].lower()
        for dependency in project["dependencies"]
    }
    expected = {
        "fastapi",
        "numpy",
        "pandas",
        "pyarrow",
        "pydantic-settings",
        "python-multipart",
        "uvicorn",
    }
    if direct != expected:
        fail(f"unexpected direct serving requirements: {sorted(direct ^ expected)}")

    print(
        "delivery contract: ok "
        f"({len(requirements)} locked packages, SADAR Analyst Console Fly deployment)"
    )


if __name__ == "__main__":
    main()
