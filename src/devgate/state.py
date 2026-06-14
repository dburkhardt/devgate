from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HostState:
    root: Path

    @classmethod
    def for_host(cls, host_name: str) -> HostState:
        base = os.environ.get("XDG_STATE_HOME")
        state_root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
        return cls(state_root / "devgate" / host_name)

    @property
    def pid_file(self) -> Path:
        return self.root / "ssh-tunnel.pid"

    @property
    def log_file(self) -> Path:
        return self.root / "ssh-tunnel.log"

    @property
    def resolved_config_file(self) -> Path:
        return self.root / "resolved-config.json"

    @property
    def mirror_state_file(self) -> Path:
        return self.root / "mirror.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def read_pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None

    def write_pid(self, pid: int) -> None:
        self.ensure()
        self.pid_file.write_text(f"{pid}\n", encoding="utf-8")

    def clear_pid(self) -> None:
        self.pid_file.unlink(missing_ok=True)

    def read_resolved(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.resolved_config_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def write_resolved(self, data: dict[str, Any]) -> None:
        self.ensure()
        self.resolved_config_file.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def clear_resolved(self) -> None:
        self.resolved_config_file.unlink(missing_ok=True)


def is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_pid(pid: int, timeout: float = 5.0) -> bool:
    if not is_pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return not is_pid_alive(pid)
