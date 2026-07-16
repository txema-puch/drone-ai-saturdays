from __future__ import annotations

import pytest

from sadar.api.cli import main


def test_help_does_not_require_runtime_release(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == 0
    assert "Serve the SADAR Analyst Console" in capsys.readouterr().out


def test_invalid_port_and_worker_count_fail_before_server_import():
    with pytest.raises(SystemExit, match="PORT"):
        main(["--port", "0"])
    with pytest.raises(SystemExit, match="exactly one worker"):
        main(["--workers", "2"])
