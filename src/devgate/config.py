from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from devgate.errors import DevgateError

DEFAULT_PORT_RANGES = [
    "3000-3099",
    "5000-5099",
    "5173-5199",
    "6006-6015",
    "7860-7899",
    "8000-8099",
    "8888-8899",
    "9229-9299",
    "10000-10099",
]

DEFAULT_EXPLICIT_PORTS = [17800]

DEFAULT_PORT_CATEGORIES = {
    "web": ["3000-3099"],
    "api": ["5000-5099"],
    "vite": ["5173-5199"],
    "tensorboard": ["6006-6015"],
    "gradio": ["7860-7899"],
    "jupyter": ["8888-8899"],
    "debug": ["9229-9299"],
    "misc": ["8000-8099", "10000-10099"],
}

VALID_COLLISION_POLICIES = {"fail", "skip", "kill-owned"}


@dataclass(frozen=True)
class SessionConfig:
    mosh: bool = True
    shell: str | None = None
    multiplexer: str | None = "tmux"
    session_name: str = "dev"
    fallback_to_ssh: bool = True


@dataclass(frozen=True)
class PortsConfig:
    ranges: list[str] = field(default_factory=lambda: list(DEFAULT_PORT_RANGES))
    explicit: list[int] = field(default_factory=lambda: list(DEFAULT_EXPLICIT_PORTS))
    collision_policy: str = "skip"


@dataclass(frozen=True)
class ArtifactConfig:
    server_port: int = 17800
    server_bind: str = "127.0.0.1"
    remote_dir: str = "~/share/artifacts"


@dataclass(frozen=True)
class AgentsConfig:
    targets: list[str] = field(default_factory=lambda: ["codex", "claude", "generic"])
    install_dir: str = "~/.agents"


@dataclass(frozen=True)
class MirrorPathConfig:
    remote: str
    ignore: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MirrorConfig:
    enabled: bool = False
    root: str = ""
    backend: str = "mutagen"
    mode: str = "one-way-safe"
    paths: list[MirrorPathConfig] = field(default_factory=list)


@dataclass(frozen=True)
class HostConfig:
    name: str
    ssh_host: str
    remote_workdir: str | None = None
    remote_state_dir: str = "~/.devgate"
    remote_artifact_dir: str = "~/share/artifacts"
    session: SessionConfig = field(default_factory=SessionConfig)
    ports: PortsConfig = field(default_factory=PortsConfig)
    artifacts: ArtifactConfig = field(default_factory=ArtifactConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)

    def fingerprint(self) -> str:
        payload = asdict(self)
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppConfig:
    path: Path | None
    hosts: dict[str, dict[str, Any]]
    agents: AgentsConfig

    def host(self, name: str) -> HostConfig:
        table = self.hosts.get(name, {})
        agents = _merge_agents(self.agents, table.get("agents", {}))
        remote_artifact_dir = str(table.get("remote_artifact_dir", "~/share/artifacts"))
        artifact_table = dict(table.get("artifacts", {}))
        artifact_table.setdefault("remote_dir", remote_artifact_dir)

        host = HostConfig(
            name=name,
            ssh_host=str(table.get("ssh_host", name)),
            remote_workdir=_optional_string(table.get("remote_workdir")),
            remote_state_dir=str(table.get("remote_state_dir", "~/.devgate")),
            remote_artifact_dir=remote_artifact_dir,
            session=_parse_session(table.get("session", {})),
            ports=_parse_ports(table.get("ports", {})),
            artifacts=_parse_artifacts(artifact_table),
            agents=agents,
            mirror=_parse_mirror(name, table.get("mirror", {})),
        )
        _validate_host(host)
        return host


def default_config_path() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config).expanduser() / "devgate" / "config.toml"
    return Path.home() / ".config" / "devgate" / "config.toml"


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    if not config_path.exists():
        return AppConfig(path=None, hosts={}, agents=AgentsConfig())

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DevgateError(f"Invalid TOML in {config_path}: {exc}") from exc

    hosts = data.get("hosts", {})
    if not isinstance(hosts, dict):
        raise DevgateError("Config key [hosts] must be a table")

    agents = _parse_agents(data.get("agents", {}))
    return AppConfig(path=config_path, hosts=hosts, agents=agents)


def _parse_session(table: dict[str, Any]) -> SessionConfig:
    return SessionConfig(
        mosh=bool(table.get("mosh", True)),
        shell=_optional_string(table.get("shell")),
        multiplexer=_optional_string(table.get("multiplexer", "tmux")),
        session_name=str(table.get("session_name", "dev")),
        fallback_to_ssh=bool(table.get("fallback_to_ssh", True)),
    )


def _parse_ports(table: dict[str, Any]) -> PortsConfig:
    ranges = list(table.get("ranges", DEFAULT_PORT_RANGES))
    explicit = [int(port) for port in table.get("explicit", DEFAULT_EXPLICIT_PORTS)]
    policy = str(table.get("collision_policy", "skip"))
    return PortsConfig(ranges=ranges, explicit=explicit, collision_policy=policy)


def _parse_artifacts(table: dict[str, Any]) -> ArtifactConfig:
    return ArtifactConfig(
        server_port=int(table.get("server_port", 17800)),
        server_bind=str(table.get("server_bind", "127.0.0.1")),
        remote_dir=str(table.get("remote_dir", "~/share/artifacts")),
    )


def _parse_agents(table: dict[str, Any]) -> AgentsConfig:
    return AgentsConfig(
        targets=[str(target) for target in table.get("targets", ["codex", "claude", "generic"])],
        install_dir=str(table.get("install_dir", "~/.agents")),
    )


def _parse_mirror(host_name: str, table: dict[str, Any]) -> MirrorConfig:
    root = str(table.get("root", f"~/Remote/{host_name}"))
    return MirrorConfig(
        enabled=bool(table.get("enabled", False)),
        root=root,
        backend=str(table.get("backend", "mutagen")),
        mode=str(table.get("mode", "one-way-safe")),
        paths=[
            MirrorPathConfig(
                remote=str(item.get("remote", "")).strip(),
                ignore=[str(pattern) for pattern in item.get("ignore", [])],
            )
            for item in table.get("paths", [])
        ],
    )


def _merge_agents(base: AgentsConfig, override: dict[str, Any]) -> AgentsConfig:
    if not override:
        return base
    return AgentsConfig(
        targets=[str(target) for target in override.get("targets", base.targets)],
        install_dir=str(override.get("install_dir", base.install_dir)),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_host(host: HostConfig) -> None:
    if host.ports.collision_policy not in VALID_COLLISION_POLICIES:
        choices = ", ".join(sorted(VALID_COLLISION_POLICIES))
        raise DevgateError(
            f"Invalid collision_policy {host.ports.collision_policy!r}; expected one of {choices}"
        )
    if not (1 <= host.artifacts.server_port <= 65535):
        raise DevgateError("artifacts.server_port must be between 1 and 65535")
    if host.artifacts.server_bind != "127.0.0.1":
        raise DevgateError("artifacts.server_bind must be 127.0.0.1 for this release")
    if host.mirror.backend != "mutagen":
        raise DevgateError("mirror.backend must be mutagen for this release")
    if host.mirror.mode != "one-way-safe":
        raise DevgateError("mirror.mode must be one-way-safe for this release")
    if not host.mirror.root.strip():
        raise DevgateError("mirror.root cannot be empty")
    for item in host.mirror.paths:
        if not item.remote:
            raise DevgateError("mirror path remote cannot be empty")
