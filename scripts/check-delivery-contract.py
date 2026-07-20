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
BUILD_LOCK = ROOT / "delivery/container/build-requirements.lock"
BUILD_INPUT = ROOT / "delivery/container/build-requirements.in"
PYPROJECT = ROOT / "backend/pyproject.toml"
ENTRYPOINT = ROOT / "scripts/container-entrypoint.sh"
README = ROOT / "README.md"
FRONTEND_INDEX = ROOT / "frontend/index.html"
FRONTEND_PACKAGE = ROOT / "frontend/package.json"
FRONTEND_LOCK = ROOT / "frontend/package-lock.json"
FLY_CONFIG = ROOT / "fly.toml"
FLY_DEPLOY = ROOT / "scripts/deploy-fly.sh"
WORKFLOW = ROOT / ".github/workflows/clean-checkout.yml"
PRODUCT_RELEASE_LOCK = ROOT / "backend/src/sadar/releases/approach_bundle.lock.json"
SMOKE_HTTP = ROOT / "scripts/smoke-http.py"
DOCKERIGNORE = ROOT / ".dockerignore"
PRODUCT_TITLE = "SADAR Analyst Console"
PACKAGE_NAME = "sadar-analyst-console"
FLY_APP = "sadar-analyst-console"
PUBLIC_RELEASE_REPOSITORY = "Txemapuch/sadar-analyst-console-release"
PUBLIC_RELEASE_ARTIFACT = "sadar-approach-public-release.tar.gz"


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
        "evaluation execution deadline": (env.get("SADAR_EVALUATION_TIMEOUT_S"), "60"),
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
        "locked public mode": '--build-arg "SADAR_RELEASE_SOURCE=locked-public"',
        "schema-v4 deployment gate": 'if [ "$schema_version" != "4" ]',
        "local-reviewed deployment rejection": 'if [ "$release_source" != "locked-public" ]',
    }
    for label, fragment in required.items():
        if fragment not in deploy_script:
            fail(f"Fly deploy script must preserve {label}")


def validate_public_release_lock(lock: dict) -> None:
    expected_keys = {
        "archive_sha256",
        "published_at",
        "release_id",
        "revision",
        "schema_version",
        "url",
    }
    if set(lock) != expected_keys:
        fail("product release lock must have the exact schema-v4 fields")
    if lock.get("schema_version") != 4:
        fail("product release lock must require schema 4")
    release_id = lock.get("release_id")
    revision = lock.get("revision")
    digest = lock.get("archive_sha256")
    published_at = lock.get("published_at")
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9a-f]{20}", release_id):
        fail("product release lock must contain a 20-character release ID")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        fail("product release lock must contain an immutable revision")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("product release lock must contain a SHA-256 archive digest")
    if not isinstance(published_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", published_at
    ):
        fail("product release lock must contain a UTC publication timestamp")
    expected_url = (
        "https://huggingface.co/datasets/"
        f"{PUBLIC_RELEASE_REPOSITORY}/resolve/{revision}/{PUBLIC_RELEASE_ARTIFACT}"
    )
    if lock.get("url") != expected_url:
        fail("product release lock must target the immutable public dataset artifact")


def validate_release_delivery(
    *,
    dockerfile: str,
    workflow: str,
    smoke_http: str,
) -> None:
    for private_historical_dependency in (
        "demo_bundle.lock.json",
        "phase6_training_artifacts.lock.json",
        "SADAR_RESEARCH_BUNDLE_DIR",
        "SADAR_RESEARCH_MODELS_DIR",
        "SADAR_TEST_USE_EXTERNAL_RESEARCH_ARTIFACTS",
    ):
        if private_historical_dependency in workflow:
            fail(
                "public CI must not depend on private historical research artifacts: "
                f"{private_historical_dependency}"
            )
    workflow_fragments = (
        "uv sync --project backend/research",
        "backend/src/sadar/releases/approach_bundle.lock.json",
        "sadar-fetch-release",
        "sadar-build-synthetic-demo",
        "--seed 20260718",
        "sadar-build-release",
        "lemd_public_aggregate_results_v1.json",
        "SADAR_APPROACH_RELEASE_DIR: /tmp/sadar-ci-locked-release",
        "--build-arg SADAR_RELEASE_SOURCE=locked-public",
        "--build-arg SOURCE_COMMIT=${{ github.sha }}",
    )
    for fragment in workflow_fragments:
        if fragment not in workflow:
            fail(f"CI is missing schema-v4 delivery fragment: {fragment!r}")
    for forbidden_local_delivery in (
        "--build-context approach-release-context=",
        "--build-arg SADAR_RELEASE_SOURCE=local-reviewed",
    ):
        if forbidden_local_delivery in workflow:
            fail("public CI must use only the locked-public delivery path")

    docker_fragments = (
        "AS approach-release-context",
        ".sadar-missing-approach-release-context",
        'ARG SADAR_RELEASE_SOURCE="locked-public"',
        "AS release-local-reviewed",
        "AS release-locked-public",
        "FROM --platform=linux/amd64 release-${SADAR_RELEASE_SOURCE} AS release-install",
        "AS release-install",
        "sadar-fetch-release",
        "sadar-validate-public-release --release-dir /tmp/approach-release-context",
        "sadar-validate-public-release --release-dir /opt/sadar/release",
        'test "$(find /opt/sadar/release -type f | wc -l | tr -d \' \')" = "9"',
        "ARG SOURCE_COMMIT",
        "SADAR_SOURCE_COMMIT=${SOURCE_COMMIT}",
        "COPY --from=release-install",
    )
    for fragment in docker_fragments:
        if fragment not in dockerfile:
            fail(f"Dockerfile is missing schema-v4 delivery fragment: {fragment!r}")
    local_stage_start = dockerfile.index("AS release-local-reviewed")
    locked_stage_start = dockerfile.index("AS release-locked-public")
    local_stage = dockerfile[local_stage_start:locked_stage_start]
    if "backend/src/sadar/releases/approach_bundle.lock.json" in local_stage:
        fail("local-reviewed Docker stage must not read the retired product lock")
    if re.search(r"ARG\s+(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)", dockerfile):
        fail("Dockerfile must not expose publisher credentials as build arguments")

    smoke_fragments = (
        'health["schema_version"] != 4',
        'health.get("demo_data_origin") != "synthetic"',
        'health.get("research_data_origin") != "aggregate_real"',
        'health.get("evaluation_data_handling") != "ephemeral_not_retained"',
        'not item["attempt_id"].startswith("syn-a-")',
        'detail.get("data_origin") != "synthetic"',
        'evidence.get("basis") != "real_opensky_research_data"',
        'evaluation.get("data_origin") != "user_upload_ephemeral"',
        'evaluation.get("reference_origin") != "derived_from_aggregate_real_research"',
        "ephemeral upload mutated the release-backed demo queue",
    )
    for fragment in smoke_fragments:
        if fragment not in smoke_http:
            fail(f"container smoke is missing origin assertion: {fragment!r}")


def main() -> None:
    for path in (
        DOCKERFILE,
        LOCK,
        BUILD_LOCK,
        BUILD_INPUT,
        PYPROJECT,
        ENTRYPOINT,
        README,
        FRONTEND_INDEX,
        FRONTEND_PACKAGE,
        FRONTEND_LOCK,
        FLY_CONFIG,
        FLY_DEPLOY,
        WORKFLOW,
        PRODUCT_RELEASE_LOCK,
        SMOKE_HTTP,
        DOCKERIGNORE,
    ):
        if not path.is_file():
            fail(f"missing tracked input: {path.relative_to(ROOT)}")
    if (ROOT / "backend/Dockerfile").exists():
        fail("legacy backend/Dockerfile must stay retired")
    if not FLY_DEPLOY.stat().st_mode & 0o111:
        fail("Fly deploy script must be executable")

    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    for private_path in (".agents", ".claude", ".codex", ".workspace", "AGENTS.md", "CLAUDE.md"):
        if private_path not in dockerignore:
            fail(f"Docker context must exclude local collaboration material: {private_path}")

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
        "AS product-install",
        "AS release-install",
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
    for fragment in (
        "COPY delivery/container/build-requirements.lock /tmp/build-requirements.lock",
        "UV_REQUIRE_HASHES=1 uv pip install --system --no-deps --require-hashes -r /tmp/build-requirements.lock",
        "uv build --wheel --no-build-isolation",
    ):
        if fragment not in dockerfile:
            fail(f"Dockerfile must preserve the locked wheel-build boundary: {fragment!r}")
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
    validate_public_release_lock(
        json.loads(PRODUCT_RELEASE_LOCK.read_text(encoding="utf-8"))
    )
    validate_fly_deploy_script(FLY_DEPLOY.read_text(encoding="utf-8"))
    validate_release_delivery(
        dockerfile=dockerfile,
        workflow=WORKFLOW.read_text(encoding="utf-8"),
        smoke_http=SMOKE_HTTP.read_text(encoding="utf-8"),
    )

    lock = LOCK.read_text(encoding="utf-8")
    requirements = list(re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==[^\s\\]+ \\\n", lock))
    if len(requirements) != 30:
        fail("model-free serving lock package count drifted")
    for index, match in enumerate(requirements):
        end = requirements[index + 1].start() if index + 1 < len(requirements) else len(lock)
        if "--hash=sha256:" not in lock[match.end() : end]:
            fail(f"{match.group(1)} has no artifact hash")

    build_lock = BUILD_LOCK.read_text(encoding="utf-8")
    build_requirements = list(
        re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==[^\s\\]+ \\\n", build_lock)
    )
    if len(build_requirements) != 5:
        fail("wheel-build lock package count drifted")
    for index, match in enumerate(build_requirements):
        end = (
            build_requirements[index + 1].start()
            if index + 1 < len(build_requirements)
            else len(build_lock)
        )
        if "--hash=sha256:" not in build_lock[match.end() : end]:
            fail(f"build dependency {match.group(1)} has no artifact hash")

    pyproject_data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    build_system = pyproject_data["build-system"]
    if build_system.get("requires") != ["hatchling==1.27.0"]:
        fail("product wheel build backend must stay exactly pinned")
    if BUILD_INPUT.read_text(encoding="utf-8") != "hatchling==1.27.0\n":
        fail("container build-lock input must match the product build backend")

    project = pyproject_data["project"]
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
        "requests",
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
