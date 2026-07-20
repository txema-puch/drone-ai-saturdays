from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check-delivery-contract.py"
SPEC = importlib.util.spec_from_file_location("sadar_delivery_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)

README = """# SADAR Analyst Console
"""
INDEX = """<meta name="description" content="SADAR Analyst Console — evaluate and investigate">
<title>SADAR Analyst Console</title>
"""
PACKAGE = {"name": "sadar-analyst-console"}
LOCK = {"name": "sadar-analyst-console"}
FLY_CONFIG = """app = "sadar-analyst-console"
primary_region = "cdg"
[build]
dockerfile = "Dockerfile"
[env]
PORT = "7860"
SADAR_ENABLE_EVALUATION = "true"
SADAR_EVALUATION_TIMEOUT_S = "60"
[http_service]
internal_port = 7860
force_https = true
auto_stop_machines = "suspend"
auto_start_machines = true
min_machines_running = 0
processes = ["app"]
[http_service.concurrency]
type = "requests"
soft_limit = 20
hard_limit = 25
[[http_service.checks]]
path = "/api/health"
[[vm]]
cpu_kind = "shared"
cpus = 1
memory = "2gb"
"""
FLY_DEPLOY = """exec fly deploy
git status --porcelain
app="${FLY_APP:-sadar-analyst-console}"
source_commit="$(git rev-parse HEAD)"
release_source="${SADAR_RELEASE_SOURCE:-locked-public}"
if [ "$release_source" != "locked-public" ]; then exit 1; fi
schema_version="4"
if [ "$schema_version" != "4" ]; then exit 1; fi
--remote-only
--ha=false
--app "$app"
--build-arg "SADAR_RELEASE_SOURCE=locked-public"
--build-arg "SOURCE_COMMIT=$source_commit"
"""
ROOT = SCRIPT.parents[1]
REAL_DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
REAL_WORKFLOW = (ROOT / ".github/workflows/clean-checkout.yml").read_text(encoding="utf-8")
REAL_SMOKE = (ROOT / "scripts/smoke-http.py").read_text(encoding="utf-8")


def validate(**overrides):
    values = {
        "readme": README,
        "frontend_index": INDEX,
        "package": PACKAGE,
        "package_lock": LOCK,
        **overrides,
    }
    delivery.validate_product_identity(**values)


def test_product_identity_contract_accepts_the_public_release_metadata():
    validate()


def test_fly_contract_accepts_suspend_and_autostart():
    delivery.validate_fly_config(FLY_CONFIG)


def test_fly_deploy_contract_accepts_single_machine_remote_build():
    delivery.validate_fly_deploy_script(FLY_DEPLOY)


def test_schema_v4_local_reviewed_delivery_contract_accepts_repository_sources():
    delivery.validate_release_delivery(
        dockerfile=REAL_DOCKERFILE,
        workflow=REAL_WORKFLOW,
        smoke_http=REAL_SMOKE,
    )


def test_fly_deploy_contract_rejects_forwarded_flag_overrides(capsys):
    with pytest.raises(SystemExit) as raised:
        delivery.validate_fly_deploy_script(f'{FLY_DEPLOY}\n"$@"')

    assert raised.value.code == 1
    assert "protected flag overrides" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"readme": "# Other\n"}, "README heading"),
        ({"frontend_index": INDEX.replace("<title>SADAR Analyst Console</title>", "")}, "browser title"),
        ({"frontend_index": INDEX.replace("— evaluate and investigate", "")}, "browser description"),
        ({"package": {"name": "other"}}, "frontend package name"),
        ({"package_lock": {"name": "other"}}, "package-lock identity"),
    ],
)
def test_product_identity_contract_rejects_drift(overrides, message, capsys):
    with pytest.raises(SystemExit) as raised:
        validate(**overrides)

    assert raised.value.code == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('app = "sadar-analyst-console"', 'app = "other"', "app identity"),
        ('primary_region = "cdg"', 'primary_region = "iad"', "primary region"),
        ('dockerfile = "Dockerfile"', 'dockerfile = "Other"', "Docker build target"),
        ('PORT = "7860"', 'PORT = "8000"', "runtime port"),
        ('SADAR_ENABLE_EVALUATION = "true"', 'SADAR_ENABLE_EVALUATION = "false"', "evaluation capability"),
        ('SADAR_EVALUATION_TIMEOUT_S = "60"', 'SADAR_EVALUATION_TIMEOUT_S = "30"', "execution deadline"),
        ('internal_port = 7860', 'internal_port = 8000', "internal port"),
        ('force_https = true', 'force_https = false', "HTTPS redirect"),
        ('processes = ["app"]', 'processes = ["worker"]', "default process routing"),
        ('auto_stop_machines = "suspend"', 'auto_stop_machines = "stop"', "idle suspension"),
        ('auto_start_machines = true', 'auto_start_machines = false', "automatic resume"),
        ('min_machines_running = 0', 'min_machines_running = 1', "zero warm instances"),
        ('path = "/api/health"', 'path = "/"', "health endpoint"),
        ('type = "requests"', 'type = "connections"', "request concurrency type"),
        ('soft_limit = 20', 'soft_limit = 1', "read concurrency soft limit"),
        ('hard_limit = 25', 'hard_limit = 2', "read concurrency hard limit"),
        ('cpu_kind = "shared"', 'cpu_kind = "performance"', "shared CPU kind"),
        ('cpus = 1', 'cpus = 2', "single shared CPU"),
        ('memory = "2gb"', 'memory = "1gb"', "two GiB memory"),
    ],
)
def test_fly_contract_rejects_runtime_drift(old, new, message, capsys):
    with pytest.raises(SystemExit) as raised:
        delivery.validate_fly_config(FLY_CONFIG.replace(old, new))

    assert raised.value.code == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("exec fly deploy", "Fly deploy command"),
        ("git status --porcelain", "clean-worktree guard"),
        ('app="${FLY_APP:-sadar-analyst-console}"', "default app identity"),
        ('source_commit="$(git rev-parse HEAD)"', "committed source revision"),
        ("--remote-only", "remote builder"),
        ("--ha=false", "single-Machine deployment"),
        ('--app "$app"', "explicit app selection"),
        ('--build-arg "SOURCE_COMMIT=$source_commit"', "source revision label"),
        ('--build-arg "SADAR_RELEASE_SOURCE=locked-public"', "locked public mode"),
        ('if [ "$schema_version" != "4" ]', "schema-v4 deployment gate"),
        ('if [ "$release_source" != "locked-public" ]', "local-reviewed deployment rejection"),
    ],
)
def test_fly_deploy_contract_rejects_safety_drift(fragment, message, capsys):
    with pytest.raises(SystemExit) as raised:
        delivery.validate_fly_deploy_script(FLY_DEPLOY.replace(fragment, ""))

    assert raised.value.code == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("source", "fragment", "message"),
    [
        ("workflow", "uv sync --project backend/research", "schema-v4 delivery fragment"),
        ("workflow", "sadar-build-synthetic-demo", "schema-v4 delivery fragment"),
        ("workflow", "--build-context approach-release-context=/tmp/sadar-ci-approach-release", "schema-v4 delivery fragment"),
        ("dockerfile", "AS release-local-reviewed", "schema-v4 delivery fragment"),
        ("dockerfile", "sadar-validate-public-release --release-dir /opt/sadar/release", "schema-v4 delivery fragment"),
        ("dockerfile", "SADAR_SOURCE_COMMIT=${SOURCE_COMMIT}", "schema-v4 delivery fragment"),
        ("smoke_http", 'evaluation.get("data_origin") != "user_upload_ephemeral"', "origin assertion"),
    ],
)
def test_schema_v4_delivery_contract_rejects_boundary_drift(source, fragment, message, capsys):
    values = {
        "dockerfile": REAL_DOCKERFILE,
        "workflow": REAL_WORKFLOW,
        "smoke_http": REAL_SMOKE,
    }
    values[source] = values[source].replace(fragment, "")
    with pytest.raises(SystemExit) as raised:
        delivery.validate_release_delivery(**values)

    assert raised.value.code == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "private_dependency",
    [
        "demo_bundle.lock.json",
        "phase6_training_artifacts.lock.json",
        "SADAR_RESEARCH_BUNDLE_DIR",
        "SADAR_RESEARCH_MODELS_DIR",
        "SADAR_TEST_USE_EXTERNAL_RESEARCH_ARTIFACTS",
    ],
)
def test_public_ci_rejects_private_historical_artifact_dependencies(
    private_dependency, capsys,
):
    drifted_workflow = REAL_WORKFLOW + f"\n# {private_dependency}\n"

    with pytest.raises(SystemExit) as raised:
        delivery.validate_release_delivery(
            dockerfile=REAL_DOCKERFILE,
            workflow=drifted_workflow,
            smoke_http=REAL_SMOKE,
        )

    assert raised.value.code == 1
    assert "private historical research artifacts" in capsys.readouterr().err


def _research_paths_after_loading_conftest(*, allow_external: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SADAR_RESEARCH_BUNDLE_DIR": "/tmp/sadar-external-bundle",
            "SADAR_RESEARCH_MODELS_DIR": "/tmp/sadar-external-models",
        }
    )
    if allow_external:
        env["SADAR_TEST_USE_EXTERNAL_RESEARCH_ARTIFACTS"] = "true"
    else:
        env.pop("SADAR_TEST_USE_EXTERNAL_RESEARCH_ARTIFACTS", None)
    command = (
        "import json, os, runpy; "
        "runpy.run_path('backend/tests/conftest.py'); "
        "print(json.dumps({"
        "'bundle': os.environ['SADAR_RESEARCH_BUNDLE_DIR'], "
        "'models': os.environ['SADAR_RESEARCH_MODELS_DIR']}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_public_tests_ignore_ambient_private_research_paths():
    paths = _research_paths_after_loading_conftest(allow_external=False)

    assert paths["bundle"] != "/tmp/sadar-external-bundle"
    assert paths["models"] != "/tmp/sadar-external-models"


def test_authorized_replay_can_select_external_research_paths():
    paths = _research_paths_after_loading_conftest(allow_external=True)

    assert paths == {
        "bundle": "/tmp/sadar-external-bundle",
        "models": "/tmp/sadar-external-models",
    }


def test_local_reviewed_stage_rejects_retired_product_lock_dependency(capsys):
    drifted_dockerfile = REAL_DOCKERFILE.replace(
        "FROM --platform=linux/amd64 product-install AS release-locked-public",
        "COPY backend/src/sadar/releases/approach_bundle.lock.json /tmp/local.lock\n"
        "FROM --platform=linux/amd64 product-install AS release-locked-public",
    )

    with pytest.raises(SystemExit) as raised:
        delivery.validate_release_delivery(
            dockerfile=drifted_dockerfile,
            workflow=REAL_WORKFLOW,
            smoke_http=REAL_SMOKE,
        )

    assert raised.value.code == 1
    assert "local-reviewed Docker stage" in capsys.readouterr().err
