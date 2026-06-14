from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devgate.config import HostConfig, load_config
from devgate.errors import DevgateError
from devgate.ports import PortPlan, build_port_plan
from devgate.remote import build_effective_config, ensure_artifact_server, install_remote_files
from devgate.ssh import check_ssh_reachable, start_tunnel, stop_tunnel
from devgate.state import HostState, is_pid_alive


@dataclass(frozen=True)
class ReconcileResult:
    host: HostConfig
    state: HostState
    plan: PortPlan
    effective_config: dict[str, Any]
    tunnel_status: str
    artifact_status: dict[str, Any] | None
    installed_files: bool


def load_host(host_name: str, config_path: str | Path | None = None) -> HostConfig:
    return load_config(config_path).host(host_name)


def reconcile(
    host_name: str,
    config_path: str | Path | None = None,
    *,
    install_files: bool = True,
    start_artifacts: bool = True,
    require_ssh: bool = True,
) -> ReconcileResult:
    host = load_host(host_name, config_path)
    state = HostState.for_host(host.name)
    state.ensure()

    if require_ssh and not check_ssh_reachable(host):
        raise DevgateError(f"SSH is not reachable for host {host.ssh_host!r}")

    input_hash = host.fingerprint()
    previous = state.read_resolved() or {}
    existing_pid = state.read_pid()
    existing_alive = is_pid_alive(existing_pid)

    if existing_alive and previous.get("config_input_hash") != input_hash:
        stop_tunnel(state)
        existing_alive = False
        previous = {}

    owned_ports = set(previous.get("forwarded_ports", [])) if existing_alive else set()
    plan = build_port_plan(host, owned_ports=owned_ports)
    tunnel_hash = _tunnel_hash(input_hash, plan.forwarded_ports)

    if existing_alive and previous.get("tunnel_hash") == tunnel_hash:
        tunnel_status = f"reused pid {existing_pid}"
    else:
        if existing_alive:
            stop_tunnel(state)
        pid = start_tunnel(host, state, plan.forwarded_ports)
        tunnel_status = f"started pid {pid}"

    effective_config = build_effective_config(host, plan)

    if install_files:
        install_remote_files(host, effective_config)

    artifact_status = ensure_artifact_server(host) if start_artifacts else None

    state.write_resolved(
        {
            "host": host.name,
            "ssh_host": host.ssh_host,
            "config_input_hash": input_hash,
            "tunnel_hash": tunnel_hash,
            "forwarded_ports": plan.forwarded_ports,
            "skipped_ports": plan.skipped_ports,
            "required_ports": plan.required_ports,
            "port_categories": plan.categories,
            "artifact_base_url": effective_config["artifact_base_url"],
            "remote_state_dir": host.remote_state_dir,
            "remote_artifact_dir": host.artifacts.remote_dir,
        }
    )

    return ReconcileResult(
        host=host,
        state=state,
        plan=plan,
        effective_config=effective_config,
        tunnel_status=tunnel_status,
        artifact_status=artifact_status,
        installed_files=install_files,
    )


def status(host_name: str, config_path: str | Path | None = None) -> dict[str, Any]:
    host = load_host(host_name, config_path)
    state = HostState.for_host(host.name)
    pid = state.read_pid()
    resolved = state.read_resolved() or {}
    return {
        "host": host.name,
        "ssh_host": host.ssh_host,
        "state_dir": str(state.root),
        "pid": pid,
        "tunnel_alive": is_pid_alive(pid),
        "resolved": resolved,
    }


def doctor(host_name: str, config_path: str | Path | None = None) -> list[tuple[str, bool, str]]:
    host = load_host(host_name, config_path)
    checks: list[tuple[str, bool, str]] = []

    for tool in ["ssh", "python3"]:
        path = shutil.which(tool)
        checks.append((f"local {tool}", bool(path), path or "not found"))

    if host.session.mosh:
        path = shutil.which("mosh")
        checks.append(("local mosh", bool(path), path or "not found"))

    checks.append(("ssh reachable", check_ssh_reachable(host), host.ssh_host))
    checks.append(("port plan", _port_plan_ok(host), "local bind checks"))
    return checks


def _port_plan_ok(host: HostConfig) -> bool:
    try:
        build_port_plan(host)
    except DevgateError:
        return False
    return True


def _tunnel_hash(config_hash: str, forwarded_ports: list[int]) -> str:
    payload = {"config_hash": config_hash, "forwarded_ports": forwarded_ports}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
