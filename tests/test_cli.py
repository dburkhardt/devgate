from __future__ import annotations

import pytest

from devgate.cli import main


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "A localhost gateway" in captured.out
    assert "dvg" in captured.out


def test_default_host_rewrites_to_connect(monkeypatch) -> None:
    calls = {}

    def fake_reconcile(host, config):
        calls["host"] = host

        class Result:
            tunnel_status = "reused pid 1"
            artifact_status = {"status": "running"}
            installed_files = True
            effective_config = {"artifact_base_url": "http://localhost:17800/"}

            class Plan:
                count = 1
                skipped_ports = []

            plan = Plan()

            class Host:
                remote_state_dir = "~/.devgate"
                agents = type("Agents", (), {"install_dir": "~/.agents"})()

            host = Host()

        return Result()

    monkeypatch.setattr("devgate.cli.reconcile", fake_reconcile)
    monkeypatch.setattr("devgate.cli.open_shell", lambda host: 0)

    assert main(["devbox"]) == 0
    assert calls["host"] == "devbox"
