from __future__ import annotations

import subprocess
import time
from pathlib import Path

from devgate.config import HostConfig
from devgate.errors import DevgateError
from devgate.state import HostState, is_pid_alive, terminate_pid


def check_ssh_reachable(host: HostConfig, timeout: int = 8) -> bool:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={timeout}",
            host.ssh_host,
            "true",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def build_tunnel_command(host: HostConfig, forwarded_ports: list[int]) -> list[str]:
    command = [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
    ]
    for port in forwarded_ports:
        command.extend(["-L", f"127.0.0.1:{port}:127.0.0.1:{port}"])
    command.append(host.ssh_host)
    return command


def stop_tunnel(state: HostState) -> bool:
    pid = state.read_pid()
    if pid and is_pid_alive(pid):
        stopped = terminate_pid(pid)
    else:
        stopped = True
    if stopped:
        state.clear_pid()
    return stopped


def start_tunnel(host: HostConfig, state: HostState, forwarded_ports: list[int]) -> int:
    state.ensure()
    command = build_tunnel_command(host, forwarded_ports)
    with state.log_file.open("ab") as log:
        log.write(b"\n--- devgate ssh tunnel start ---\n")
        log.write((" ".join(command) + "\n").encode("utf-8"))
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(1.0)
    if process.poll() is not None:
        tail = _tail_file(state.log_file)
        raise DevgateError(
            "SSH tunnel failed to start. Recent tunnel log:\n"
            f"{tail or '(log was empty)'}"
        )

    state.write_pid(process.pid)
    return process.pid


def _tail_file(path: Path, max_bytes: int = 4000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
