from __future__ import annotations

import socket
from dataclasses import dataclass

from devgate.config import DEFAULT_PORT_CATEGORIES, HostConfig
from devgate.errors import DevgateError


@dataclass(frozen=True)
class PortPlan:
    configured_ports: list[int]
    forwarded_ports: list[int]
    skipped_ports: list[int]
    required_ports: list[int]
    categories: dict[str, list[int]]

    @property
    def count(self) -> int:
        return len(self.forwarded_ports)


def parse_port_range(text: str) -> list[int]:
    value = text.strip()
    if not value:
        raise DevgateError("Port range cannot be empty")
    if "-" not in value:
        port = _parse_port(value)
        return [port]
    left, right = value.split("-", 1)
    start = _parse_port(left)
    end = _parse_port(right)
    if end < start:
        raise DevgateError(f"Invalid port range {text!r}: end is before start")
    return list(range(start, end + 1))


def expand_port_ranges(ranges: list[str]) -> list[int]:
    ports: set[int] = set()
    for item in ranges:
        ports.update(parse_port_range(str(item)))
    return sorted(ports)


def configured_ports(host: HostConfig) -> list[int]:
    ports = set(expand_port_ranges(host.ports.ranges))
    ports.update(int(port) for port in host.ports.explicit)
    ports.add(host.artifacts.server_port)
    return sorted(ports)


def is_local_port_available(port: int, bind: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind, int(port)))
        except OSError:
            return False
    return True


def build_port_plan(host: HostConfig, owned_ports: set[int] | None = None) -> PortPlan:
    owned_ports = owned_ports or set()
    all_ports = configured_ports(host)
    required_ports = sorted({host.artifacts.server_port})
    skipped: list[int] = []
    forwarded: list[int] = []

    for port in all_ports:
        available = port in owned_ports or is_local_port_available(port)
        if available:
            forwarded.append(port)
            continue

        if port in required_ports:
            raise DevgateError(
                f"Required local port {port} is unavailable. Stop the conflicting process "
                "or choose another artifacts.server_port."
            )
        if host.ports.collision_policy == "fail":
            raise DevgateError(
                f"Local port {port} is unavailable and collision_policy is set to fail."
            )
        skipped.append(port)

    return PortPlan(
        configured_ports=all_ports,
        forwarded_ports=forwarded,
        skipped_ports=skipped,
        required_ports=required_ports,
        categories=categorize_ports(forwarded),
    )


def categorize_ports(ports: list[int]) -> dict[str, list[int]]:
    categories = {name: [] for name in DEFAULT_PORT_CATEGORIES}
    assigned: set[int] = set()
    category_ranges = {
        name: set(expand_port_ranges(ranges)) for name, ranges in DEFAULT_PORT_CATEGORIES.items()
    }
    for port in ports:
        for name, category_ports in category_ranges.items():
            if port in category_ports:
                categories[name].append(port)
                assigned.add(port)
                break
    categories.setdefault("tool", [])
    for port in ports:
        if port not in assigned and port not in categories["tool"]:
            categories["tool"].append(port)
    return {name: values for name, values in categories.items() if values}


def _parse_port(value: str) -> int:
    try:
        port = int(value.strip())
    except ValueError as exc:
        raise DevgateError(f"Invalid port {value!r}") from exc
    if not (1 <= port <= 65535):
        raise DevgateError(f"Port {port} is outside the valid range 1-65535")
    return port
