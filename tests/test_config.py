from __future__ import annotations

from pathlib import Path

import pytest

from devgate.config import load_config
from devgate.errors import DevgateError


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


def test_mirror_defaults_are_host_scoped(tmp_path: Path) -> None:
    host = load_config(tmp_path / "missing.toml").host("devbox")
    assert host.mirror.enabled is False
    assert host.mirror.root == "~/Remote/devbox"
    assert host.mirror.backend == "mutagen"
    assert host.mirror.mode == "one-way-safe"
    assert host.mirror.paths == []


def test_load_mirror_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hosts.devbox]
ssh_host = "devbox"

[hosts.devbox.mirror]
enabled = true
root = "~/Remote/devbox"
backend = "mutagen"
mode = "one-way-safe"

[[hosts.devbox.mirror.paths]]
remote = "/home/daniel/work/project-a"
ignore = ["node_modules/", ".venv/"]

[[hosts.devbox.mirror.paths]]
remote = "/home/daniel/reports"
ignore = ["*.tmp"]
""",
        encoding="utf-8",
    )

    host = load_config(config_path).host("devbox")
    assert host.mirror.enabled is True
    assert host.mirror.root == "~/Remote/devbox"
    assert [item.remote for item in host.mirror.paths] == [
        "/home/daniel/work/project-a",
        "/home/daniel/reports",
    ]
    assert host.mirror.paths[0].ignore == ["node_modules/", ".venv/"]


def test_invalid_mirror_backend_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hosts.devbox.mirror]
backend = "rsync"
""",
        encoding="utf-8",
    )

    with pytest.raises(DevgateError, match="mirror.backend"):
        load_config(config_path).host("devbox")


def test_empty_mirror_remote_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hosts.devbox.mirror]
enabled = true

[[hosts.devbox.mirror.paths]]
remote = ""
""",
        encoding="utf-8",
    )

    with pytest.raises(DevgateError, match="remote"):
        load_config(config_path).host("devbox")
