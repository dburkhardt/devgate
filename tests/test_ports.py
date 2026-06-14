from __future__ import annotations

import socket

import pytest

from devgate.config import HostConfig, PortsConfig
from devgate.errors import DevgateError
from devgate.ports import build_port_plan, categorize_ports, expand_port_ranges, parse_port_range


def test_parse_single_port() -> None:
    assert parse_port_range("3000") == [3000]


def test_parse_port_range() -> None:
    assert parse_port_range("3000-3002") == [3000, 3001, 3002]


def test_parse_invalid_port_range() -> None:
    with pytest.raises(DevgateError):
        parse_port_range("3002-3000")


def test_expand_port_ranges_deduplicates() -> None:
    assert expand_port_ranges(["3000-3001", "3001"]) == [3000, 3001]


def test_categorize_ports() -> None:
    categories = categorize_ports([3000, 5000, 5173, 17800])
    assert categories["web"] == [3000]
    assert categories["api"] == [5000]
    assert categories["vite"] == [5173]
    assert categories["tool"] == [17800]


def test_required_artifact_port_collision_fails() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        host = HostConfig(
            name="test",
            ssh_host="test",
            ports=PortsConfig(ranges=[], explicit=[port], collision_policy="skip"),
        )
        host = HostConfig(
            name=host.name,
            ssh_host=host.ssh_host,
            ports=host.ports,
            artifacts=host.artifacts.__class__(server_port=port),
        )
        with pytest.raises(DevgateError):
            build_port_plan(host)
