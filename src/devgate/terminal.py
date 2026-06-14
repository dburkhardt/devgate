from __future__ import annotations

import shutil
import subprocess

from devgate.config import HostConfig
from devgate.errors import DevgateError


def build_shell_command(host: HostConfig) -> list[str]:
    remote_command = _remote_session_command(host)
    if host.session.mosh:
        if shutil.which("mosh"):
            return ["mosh", host.ssh_host, "--", *remote_command]
        if not host.session.fallback_to_ssh:
            raise DevgateError("mosh is not installed locally and fallback_to_ssh is false")
    return ["ssh", "-t", host.ssh_host, *remote_command]


def open_shell(host: HostConfig) -> int:
    return subprocess.run(build_shell_command(host), check=False).returncode


def _remote_session_command(host: HostConfig) -> list[str]:
    if host.session.multiplexer == "tmux":
        return ["tmux", "new-session", "-A", "-s", host.session.session_name]
    if host.session.shell:
        return [host.session.shell]
    return []
