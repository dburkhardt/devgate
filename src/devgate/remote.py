from __future__ import annotations

import base64
import json
import shlex
import subprocess
from dataclasses import asdict
from importlib.resources import files
from typing import Any

from devgate.config import HostConfig
from devgate.errors import DevgateError
from devgate.ports import PortPlan


def build_effective_config(host: HostConfig, plan: PortPlan) -> dict[str, Any]:
    return {
        "host": host.name,
        "ssh_host": host.ssh_host,
        "artifact_root": host.artifacts.remote_dir,
        "artifact_base_url": f"http://localhost:{host.artifacts.server_port}/",
        "artifact_server": {
            "bind": host.artifacts.server_bind,
            "port": host.artifacts.server_port,
        },
        "forwarded_ports": plan.forwarded_ports,
        "skipped_ports": plan.skipped_ports,
        "port_categories": plan.categories,
        "remote_state_dir": host.remote_state_dir,
        "helper_bin": f"{host.remote_state_dir.rstrip('/')}/bin",
        "agents": asdict(host.agents),
    }


def install_remote_files(host: HostConfig, effective_config: dict[str, Any]) -> None:
    payload = {
        "files": _template_payload(host, effective_config),
        "remote_state_dir": host.remote_state_dir,
    }
    script = _script_with_payload(
        payload,
        r'''
import base64
import json
import os
import pathlib
import stat

payload = json.loads(base64.b64decode(PAYLOAD).decode("utf-8"))
for item in payload["files"]:
    path = pathlib.Path(os.path.expanduser(item["path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(item["data"])
    path.write_bytes(data)
    path.chmod(item["mode"])
state_dir = pathlib.Path(os.path.expanduser(payload["remote_state_dir"]))
(state_dir / "bin").mkdir(parents=True, exist_ok=True)
print(f"installed {len(payload['files'])} files")
''',
    )
    _run_remote_python(host, script)


def ensure_artifact_server(host: HostConfig) -> dict[str, Any]:
    payload = {
        "state_dir": host.remote_state_dir,
        "artifact_dir": host.artifacts.remote_dir,
        "port": host.artifacts.server_port,
        "bind": host.artifacts.server_bind,
    }
    script = _script_with_payload(
        payload,
        r'''
import base64
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

payload = json.loads(base64.b64decode(PAYLOAD).decode("utf-8"))
state_dir = pathlib.Path(os.path.expanduser(payload["state_dir"]))
artifact_dir = pathlib.Path(os.path.expanduser(payload["artifact_dir"]))
port = int(payload["port"])
bind = payload["bind"]
state_dir.mkdir(parents=True, exist_ok=True)
artifact_dir.mkdir(parents=True, exist_ok=True)
pid_file = state_dir / "artifact-server.pid"
log_file = state_dir / "artifact-server.log"

def can_connect() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((bind, port)) == 0

if can_connect():
    print(json.dumps({"status": "running", "port": port, "pid": None}))
    sys.exit(0)

with log_file.open("ab") as log:
    log.write(b"\n--- devgate artifact server start ---\n")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            bind,
            "--directory",
            str(artifact_dir),
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
time.sleep(0.6)
if process.poll() is not None or not can_connect():
    raise SystemExit(f"artifact server failed; see {log_file}")
print(json.dumps({"status": "started", "port": port, "pid": process.pid}))
''',
    )
    output = _run_remote_python(host, script)
    try:
        return json.loads(output.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise DevgateError(f"Could not parse artifact server response: {output}") from exc


def run_remote_helper(host: HostConfig, helper: str, args: list[str]) -> str:
    helper_path = f"{host.remote_state_dir.rstrip('/')}/bin/{helper}"
    command = " ".join([shlex.quote(helper_path), *(shlex.quote(arg) for arg in args)])
    result = subprocess.run(
        ["ssh", host.ssh_host, command],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise DevgateError(result.stderr.strip() or result.stdout.strip() or f"{helper} failed")
    return result.stdout


def remote_command_ok(host: HostConfig, command: str) -> bool:
    result = subprocess.run(
        ["ssh", host.ssh_host, command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _template_payload(host: HostConfig, effective_config: dict[str, Any]) -> list[dict[str, Any]]:
    file_specs = [
        ("templates/remote/bin/devgate-show", f"{host.remote_state_dir}/bin/devgate-show", 0o755),
        ("templates/remote/bin/devgate-port", f"{host.remote_state_dir}/bin/devgate-port", 0o755),
        (
            "templates/remote/bin/devgate-artifacts",
            f"{host.remote_state_dir}/bin/devgate-artifacts",
            0o755,
        ),
        (
            "templates/remote/bin/devgate-status",
            f"{host.remote_state_dir}/bin/devgate-status",
            0o755,
        ),
        ("templates/agents/devgate/SKILL.md", f"{host.agents.install_dir}/devgate/SKILL.md", 0o644),
    ]

    if "codex" in host.agents.targets:
        file_specs.append(
            (
                "templates/agents/codex/AGENTS.md",
                f"{host.agents.install_dir}/codex/AGENTS.md",
                0o644,
            )
        )
    if "claude" in host.agents.targets:
        file_specs.append(
            (
                "templates/agents/claude/CLAUDE.md",
                f"{host.agents.install_dir}/claude/CLAUDE.md",
                0o644,
            )
        )
    if "generic" in host.agents.targets:
        file_specs.append(
            (
                "templates/agents/generic/README.md",
                f"{host.agents.install_dir}/generic/README.md",
                0o644,
            )
        )

    payload: list[dict[str, Any]] = []
    root = files("devgate")
    for resource_path, remote_path, mode in file_specs:
        data = root.joinpath(resource_path).read_bytes()
        payload.append(
            {
                "path": remote_path,
                "mode": mode,
                "data": base64.b64encode(data).decode("ascii"),
            }
        )

    config_data = json.dumps(effective_config, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    payload.append(
        {
            "path": f"{host.remote_state_dir}/effective-config.json",
            "mode": 0o644,
            "data": base64.b64encode(config_data).decode("ascii"),
        }
    )
    payload.append(
        {
            "path": f"{host.agents.install_dir}/devgate/config.json",
            "mode": 0o644,
            "data": base64.b64encode(config_data).decode("ascii"),
        }
    )
    return payload


def _script_with_payload(payload: dict[str, Any], script: str) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return f"PAYLOAD = {encoded!r}\n{script.lstrip()}"


def _run_remote_python(host: HostConfig, script: str) -> str:
    result = subprocess.run(
        ["ssh", host.ssh_host, "python3", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "remote Python command failed"
        raise DevgateError(message)
    return result.stdout
