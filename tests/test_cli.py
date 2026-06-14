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

    def fake_reconcile(host, config, sync_mirror=True):
        calls["host"] = host
        calls["sync_mirror"] = sync_mirror

        class Result:
            tunnel_status = "reused pid 1"
            artifact_status = {"status": "running"}
            installed_files = True
            effective_config = {"artifact_base_url": "http://localhost:17800/"}
            mirror_status = None

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
    assert calls["sync_mirror"] is True


def test_up_no_sync_disables_mirror_reconcile(monkeypatch) -> None:
    calls = {}

    def fake_reconcile(host, config, sync_mirror=True):
        calls["host"] = host
        calls["sync_mirror"] = sync_mirror

        class Result:
            tunnel_status = "started pid 2"
            artifact_status = None
            installed_files = False
            effective_config = {}
            mirror_status = None

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

    assert main(["up", "devbox", "--no-sync"]) == 0
    assert calls == {"host": "devbox", "sync_mirror": False}


def test_sync_status_json(monkeypatch, capsys) -> None:
    class Host:
        name = "devbox"

    monkeypatch.setattr("devgate.cli.load_host", lambda host, config: Host())
    monkeypatch.setattr(
        "devgate.cli.mirror_status",
        lambda host, state: {
            "enabled": True,
            "root": "~/Remote/devbox",
            "configured": [{"name": "repo"}],
            "active": ["repo"],
            "paused": [],
            "conflicted": [],
            "removed": [],
        },
    )

    assert main(["sync", "status", "devbox", "--json"]) == 0
    captured = capsys.readouterr()
    assert '"root": "~/Remote/devbox"' in captured.out
