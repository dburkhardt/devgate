from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from devgate import __version__
from devgate.config import load_config
from devgate.core import doctor, load_host, reconcile, status
from devgate.errors import DevgateError
from devgate.ports import build_port_plan
from devgate.remote import build_effective_config, install_remote_files, run_remote_helper
from devgate.ssh import stop_tunnel
from devgate.state import HostState
from devgate.sync import mirror_down, mirror_flush, mirror_pause, mirror_status, reconcile_mirror
from devgate.terminal import open_shell

COMMANDS = {
    "up",
    "shell",
    "status",
    "doctor",
    "install-agents",
    "ports",
    "show",
    "down",
    "sync",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["connect", *argv]
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except DevgateError as exc:
        print(f"dvg: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("dvg: interrupted", file=sys.stderr)
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dvg",
        description="A localhost gateway for remote development.",
    )
    parser.add_argument("--version", action="version", version=f"dvg {__version__}")
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    connect = subparsers.add_parser("connect", help="reconcile backend, then open a shell")
    connect.add_argument("host")
    connect.add_argument("--no-sync", action="store_true", help="skip mirror sync reconciliation")

    up = subparsers.add_parser("up", help="reconcile backend only")
    up.add_argument("host")
    up.add_argument("--no-sync", action="store_true", help="skip mirror sync reconciliation")

    shell = subparsers.add_parser("shell", help="reconcile backend, then open a shell")
    shell.add_argument("host")
    shell.add_argument("--no-sync", action="store_true", help="skip mirror sync reconciliation")

    status_parser = subparsers.add_parser("status", help="show tunnel and artifact status")
    status_parser.add_argument("host")
    status_parser.add_argument("--json", action="store_true", help="print JSON")

    doctor_parser = subparsers.add_parser("doctor", help="check local and remote prerequisites")
    doctor_parser.add_argument("host")

    install_agents = subparsers.add_parser(
        "install-agents",
        help="install remote helpers and agent instructions",
    )
    install_agents.add_argument("host")

    ports = subparsers.add_parser("ports", help="list configured and effective ports")
    ports.add_argument("host")
    ports.add_argument("--json", action="store_true", help="print JSON")

    show = subparsers.add_parser("show", help="publish a remote file or directory")
    show.add_argument("host")
    show.add_argument("path")

    down = subparsers.add_parser("down", help="stop the devgate-owned SSH tunnel")
    down.add_argument("host")

    sync = subparsers.add_parser("sync", help="manage configured local mirror sessions")
    sync_subparsers = sync.add_subparsers(dest="sync_command", required=True)

    sync_up = sync_subparsers.add_parser("up", help="create or resume mirror sync sessions")
    sync_up.add_argument("host")

    sync_status = sync_subparsers.add_parser("status", help="show mirror sync status")
    sync_status.add_argument("host")
    sync_status.add_argument("--json", action="store_true", help="print JSON")

    sync_flush = sync_subparsers.add_parser("flush", help="wait for mirror sync to settle")
    sync_flush.add_argument("host")
    sync_flush.add_argument("path_name", nargs="?")

    sync_pause = sync_subparsers.add_parser("pause", help="pause mirror sync sessions")
    sync_pause.add_argument("host")
    sync_pause.add_argument("path_name", nargs="?")

    sync_down = sync_subparsers.add_parser("down", help="terminate devgate-owned mirror sessions")
    sync_down.add_argument("host")
    sync_down.add_argument("path_name", nargs="?")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command in {"connect", "shell"}:
        result = reconcile(args.host, args.config, sync_mirror=not args.no_sync)
        _print_reconcile(result)
        return open_shell(result.host)
    if command == "up":
        result = reconcile(args.host, args.config, sync_mirror=not args.no_sync)
        _print_reconcile(result)
        return 0
    if command == "status":
        info = status(args.host, args.config)
        if args.json:
            print(json.dumps(info, indent=2, sort_keys=True))
        else:
            _print_status(info)
        return 0
    if command == "doctor":
        checks = doctor(args.host, args.config)
        failed = False
        for label, ok, detail in checks:
            failed = failed or not ok
            prefix = "ok" if ok else "fail"
            print(f"{prefix:4} {label}: {detail}")
        return 1 if failed else 0
    if command == "install-agents":
        host = load_config(args.config).host(args.host)
        plan = build_port_plan(host)
        effective = build_effective_config(host, plan)
        install_remote_files(host, effective)
        print(f"installed helpers and agent instructions for {host.name}")
        return 0
    if command == "ports":
        host = load_config(args.config).host(args.host)
        state = HostState.for_host(host.name)
        resolved = state.read_resolved()
        if resolved:
            payload = resolved
        else:
            plan = build_port_plan(host)
            payload = {
                "forwarded_ports": plan.forwarded_ports,
                "skipped_ports": plan.skipped_ports,
                "port_categories": plan.categories,
            }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_ports(payload)
        return 0
    if command == "show":
        result = reconcile(args.host, args.config)
        _print_reconcile(result)
        print(run_remote_helper(result.host, "devgate-show", [args.path]), end="")
        return 0
    if command == "down":
        host = load_host(args.host, args.config)
        state = HostState.for_host(host.name)
        stopped = stop_tunnel(state)
        if stopped:
            print(f"stopped devgate tunnel for {host.name}")
            return 0
        raise DevgateError(f"could not stop devgate tunnel for {host.name}")
    if command == "sync":
        return _dispatch_sync(args)
    raise DevgateError(f"unknown command {command!r}")


def _dispatch_sync(args: argparse.Namespace) -> int:
    host = load_host(args.host, args.config)
    state = HostState.for_host(host.name)
    if args.sync_command == "up":
        payload = reconcile_mirror(host, state)
        _print_sync_status(payload)
        return 0
    if args.sync_command == "status":
        payload = mirror_status(host, state)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_sync_status(payload)
        return 0
    if args.sync_command == "flush":
        _print_sync_status(mirror_flush(host, state, args.path_name))
        return 0
    if args.sync_command == "pause":
        _print_sync_status(mirror_pause(host, state, args.path_name))
        return 0
    if args.sync_command == "down":
        _print_sync_status(mirror_down(host, state, args.path_name))
        return 0
    raise DevgateError(f"unknown sync command {args.sync_command!r}")


def _print_reconcile(result) -> None:
    print(f"ssh tunnel: {result.tunnel_status}")
    print(f"forwarded ports: {result.plan.count}")
    if result.plan.skipped_ports:
        skipped = ", ".join(str(port) for port in result.plan.skipped_ports[:12])
        suffix = " ..." if len(result.plan.skipped_ports) > 12 else ""
        print(f"skipped ports: {skipped}{suffix}")
    if result.artifact_status:
        print(f"artifact server: {result.effective_config['artifact_base_url']}")
    if result.installed_files:
        print(f"remote helpers: {result.host.remote_state_dir}/bin")
        print(f"agent instructions: {result.host.agents.install_dir}/devgate")
    if result.mirror_status:
        print(f"mirror root: {result.mirror_status['root']}")
        print(f"mirror sessions: {len(result.mirror_status.get('configured', []))}")


def _print_status(info: dict) -> None:
    print(f"host: {info['host']} ({info['ssh_host']})")
    print(f"state: {info['state_dir']}")
    print(f"tunnel: {'running' if info['tunnel_alive'] else 'stopped'}")
    if info.get("pid"):
        print(f"pid: {info['pid']}")
    resolved = info.get("resolved") or {}
    if resolved:
        print(f"artifact url: {resolved.get('artifact_base_url', 'unknown')}")
        print(f"forwarded ports: {len(resolved.get('forwarded_ports', []))}")
        skipped = resolved.get("skipped_ports", [])
        if skipped:
            print(f"skipped ports: {len(skipped)}")
    mirror = info.get("mirror", {})
    if mirror.get("enabled"):
        print(f"mirror root: {mirror.get('root')}")
        print(f"mirror configured: {len(mirror.get('configured', []))}")
        if mirror.get("removed"):
            print(f"mirror removed: {len(mirror.get('removed', []))}")


def _print_ports(payload: dict) -> None:
    forwarded = payload.get("forwarded_ports", [])
    skipped = payload.get("skipped_ports", [])
    print(f"forwarded: {len(forwarded)}")
    categories = payload.get("port_categories", {})
    for name, ports in categories.items():
        compact = _compact_ports(ports)
        print(f"  {name}: {compact}")
    if skipped:
        print(f"skipped: {_compact_ports(skipped)}")


def _compact_ports(ports: list[int]) -> str:
    if not ports:
        return "(none)"
    runs: list[str] = []
    start = prev = int(ports[0])
    for raw in ports[1:]:
        port = int(raw)
        if port == prev + 1:
            prev = port
            continue
        runs.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = port
    runs.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(runs)


def _print_sync_status(payload: dict) -> None:
    print(f"mirror: {'enabled' if payload.get('enabled') else 'disabled'}")
    print(f"root: {payload.get('root', '(none)')}")
    print(f"configured: {len(payload.get('configured', []))}")
    print(f"active: {len(payload.get('active', []))}")
    paused = payload.get("paused", [])
    conflicted = payload.get("conflicted", [])
    removed = payload.get("removed", [])
    if paused:
        print(f"paused: {', '.join(paused)}")
    if conflicted:
        print(f"conflicted: {', '.join(conflicted)}")
    if removed:
        print(f"removed: {', '.join(removed)}")
