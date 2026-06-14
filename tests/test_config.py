from __future__ import annotations

from pathlib import Path

from devgate.config import load_config


def test_missing_config_uses_host_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")
    host = config.host("devbox")
    assert host.name == "devbox"
    assert host.ssh_host == "devbox"
    assert host.artifacts.server_port == 17800


def test_load_host_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hosts.devbox]
ssh_host = "devbox.example"
remote_state_dir = "/home/me/.devgate"

[hosts.devbox.session]
mosh = false
session_name = "work"

[hosts.devbox.ports]
ranges = ["3000-3001"]
explicit = [17800]
collision_policy = "fail"
""",
        encoding="utf-8",
    )

    host = load_config(config_path).host("devbox")
    assert host.ssh_host == "devbox.example"
    assert host.remote_state_dir == "/home/me/.devgate"
    assert host.session.mosh is False
    assert host.session.session_name == "work"
    assert host.ports.ranges == ["3000-3001"]
    assert host.ports.collision_policy == "fail"
