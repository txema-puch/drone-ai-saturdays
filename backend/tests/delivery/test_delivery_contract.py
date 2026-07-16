from __future__ import annotations

import importlib.util
from pathlib import Path

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
--remote-only
--ha=false
--app "$app"
--build-arg "SOURCE_COMMIT=$source_commit"
"""


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
    ],
)
def test_fly_deploy_contract_rejects_safety_drift(fragment, message, capsys):
    with pytest.raises(SystemExit) as raised:
        delivery.validate_fly_deploy_script(FLY_DEPLOY.replace(fragment, ""))

    assert raised.value.code == 1
    assert message in capsys.readouterr().err
