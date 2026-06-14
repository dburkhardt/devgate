from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from devgate.errors import DevgateError
from devgate.state import HostState

DEFAULT_MIRROR_BACKEND = "mutagen"
DEFAULT_MIRROR_MODE = "one-way-safe"
MIRROR_STATE_VERSION = 1


@dataclass(frozen=True)
class MirrorTarget:
    name: str
    path_id: str
    remote: str
    local: Path
    ignore: list[str]
    session_name: str
    path_hash: str
    mode: str = DEFAULT_MIRROR_MODE

    @property
    def config_hash(self) -> str:
        payload = {
            "remote": self.remote,
            "local": str(self.local),
            "ignore": self.ignore,
            "mode": self.mode,
            "session_name": self.session_name,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def to_record(self, *, removed: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "path_id": self.path_id,
            "remote": self.remote,
            "local": str(self.local),
            "ignore": list(self.ignore),
            "session_name": self.session_name,
            "path_hash": self.path_hash,
            "mode": self.mode,
            "config_hash": self.config_hash,
            "removed": removed,
            "active": not removed,
        }


@dataclass(frozen=True)
class MutagenSession:
    name: str
    identifier: str | None = None
    status: str = ""
    active: bool = True
    paused: bool = False
    conflicted: bool = False


def mirror_enabled(host: Any) -> bool:
    mirror = _field(host, "mirror", None)
    return bool(mirror and _field(mirror, "enabled", False))


def mirror_root(host: Any) -> Path:
    mirror = _field(host, "mirror", None)
    host_name = str(_field(host, "name", "default"))
    root = _field(mirror, "root", f"~/Remote/{host_name}") if mirror else f"~/Remote/{host_name}"
    return Path(str(root)).expanduser()


def mirror_backend(host: Any) -> str:
    mirror = _field(host, "mirror", None)
    return str(_field(mirror, "backend", DEFAULT_MIRROR_BACKEND))


def mirror_mode(host: Any) -> str:
    mirror = _field(host, "mirror", None)
    return str(_field(mirror, "mode", DEFAULT_MIRROR_MODE))


def derive_local_path_name(remote: str) -> str:
    trimmed = str(remote).rstrip("/")
    if trimmed in {"", "/", "~"}:
        basename = "root" if trimmed == "/" else "home"
    else:
        basename = PurePosixPath(trimmed).name or "path"
    return _sanitize_component(basename)


def derive_local_path_names(remote_paths: Sequence[str]) -> list[str]:
    bases = [derive_local_path_name(remote) for remote in remote_paths]
    counts = Counter(bases)
    names = [
        f"{base}--{short_path_hash(remote)}" if counts[base] > 1 else base
        for remote, base in zip(remote_paths, bases, strict=True)
    ]
    duplicate_names = [name for name, count in Counter(names).items() if count > 1]
    if duplicate_names:
        joined = ", ".join(sorted(duplicate_names))
        raise DevgateError(f"Mirror paths produce duplicate local names: {joined}")
    return names


def short_path_hash(remote: str) -> str:
    normalized = str(remote).rstrip("/") or str(remote)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


def session_name(host_name: str, path_id: str) -> str:
    return f"devgate.{_sanitize_component(host_name)}.{_sanitize_component(path_id)}"


def build_mirror_targets(host: Any) -> list[MirrorTarget]:
    mirror = _field(host, "mirror", None)
    paths = list(_field(mirror, "paths", []) or [])
    remote_paths = [str(_field(path, "remote", "")).strip() for path in paths]
    if any(not remote for remote in remote_paths):
        raise DevgateError("Mirror paths must include a non-empty remote path")

    names = derive_local_path_names(remote_paths)
    root = mirror_root(host)
    host_name = str(_field(host, "name", "default"))
    mode = mirror_mode(host)
    return [
        MirrorTarget(
            name=name,
            path_id=name,
            remote=remote,
            local=root / name,
            ignore=[str(pattern) for pattern in (_field(path, "ignore", []) or [])],
            session_name=session_name(host_name, name),
            path_hash=short_path_hash(remote),
            mode=mode,
        )
        for path, remote, name in zip(paths, remote_paths, names, strict=True)
    ]


def select_targets(
    targets: Sequence[MirrorTarget],
    path_name: str | None = None,
) -> list[MirrorTarget]:
    if path_name is None:
        return list(targets)

    selected = [
        target
        for target in targets
        if path_name
        in {
            target.name,
            target.path_id,
            target.session_name,
            target.remote,
            derive_local_path_name(target.remote),
        }
    ]
    if not selected:
        available = ", ".join(target.name for target in targets) or "(none)"
        raise DevgateError(f"Unknown mirror path {path_name!r}; configured paths: {available}")
    return selected


def mirror_state_file(state: HostState) -> Path:
    configured = getattr(state, "mirror_state_file", None)
    if configured is not None:
        return Path(configured)
    return Path(state.root) / "mirror.json"


def read_mirror_state(state: HostState) -> dict[str, Any]:
    path = mirror_state_file(state)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_state()
    except json.JSONDecodeError as exc:
        raise DevgateError(f"Invalid mirror state in {path}: {exc}") from exc


def write_mirror_state(state: HostState, data: dict[str, Any]) -> None:
    path = mirror_state_file(state)
    if hasattr(state, "ensure"):
        state.ensure()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def require_mutagen(mutagen_binary: str = "mutagen") -> str:
    path = shutil.which(mutagen_binary)
    if not path:
        raise DevgateError(
            "Mutagen is required for devgate mirror sync. Install it and ensure "
            f"{mutagen_binary!r} is on PATH."
        )
    return path


def build_create_command(
    host: Any,
    target: MirrorTarget,
    mutagen_binary: str = "mutagen",
) -> list[str]:
    command = [
        mutagen_binary,
        "sync",
        "create",
        f"--name={target.session_name}",
        f"--sync-mode={target.mode}",
    ]
    for pattern in target.ignore:
        command.append(f"--ignore={pattern}")
    command.extend([_remote_endpoint(host, target), str(target.local)])
    return command


def build_resume_command(session: str, mutagen_binary: str = "mutagen") -> list[str]:
    return [mutagen_binary, "sync", "resume", session]


def build_list_command(mutagen_binary: str = "mutagen") -> list[str]:
    return [mutagen_binary, "sync", "list"]


def build_flush_command(session: str, mutagen_binary: str = "mutagen") -> list[str]:
    return [mutagen_binary, "sync", "flush", session]


def build_pause_command(session: str, mutagen_binary: str = "mutagen") -> list[str]:
    return [mutagen_binary, "sync", "pause", session]


def build_terminate_command(session: str, mutagen_binary: str = "mutagen") -> list[str]:
    return [mutagen_binary, "sync", "terminate", session]


def list_mutagen_sessions(mutagen_binary: str = "mutagen") -> dict[str, MutagenSession]:
    result = _run_mutagen(build_list_command(mutagen_binary))
    return parse_mutagen_list(result.stdout)


def parse_mutagen_list(output: str) -> dict[str, MutagenSession]:
    sessions: dict[str, MutagenSession] = {}
    current_name: str | None = None
    identifier: str | None = None
    status = ""
    block: list[str] = []

    def flush() -> None:
        nonlocal current_name, identifier, status, block
        if not current_name:
            return
        text = "\n".join(block).lower()
        status_text = status.lower()
        paused = "paused" in status_text or "paused" in text
        conflicted = "conflict" in status_text or "conflict" in text
        sessions[current_name] = MutagenSession(
            name=current_name,
            identifier=identifier,
            status=status,
            active=not paused,
            paused=paused,
            conflicted=conflicted,
        )
        current_name = None
        identifier = None
        status = ""
        block = []

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            flush()
            current_name = stripped.partition(":")[2].strip()
            block = [stripped]
            continue
        if current_name is None:
            continue
        block.append(stripped)
        if stripped.startswith("Identifier:"):
            identifier = stripped.partition(":")[2].strip() or None
        elif stripped.startswith("Status:"):
            status = stripped.partition(":")[2].strip()

    flush()
    return sessions


def reconcile_mirror(
    host: Any,
    state: HostState | None = None,
    *,
    path_name: str | None = None,
    mutagen_binary: str | None = None,
) -> dict[str, Any]:
    state = state or HostState.for_host(str(_field(host, "name", "default")))
    if not mirror_enabled(host):
        return status_payload(host, state, sessions={})

    _validate_mirror(host)
    mutagen = mutagen_binary or require_mutagen()
    targets = build_mirror_targets(host)
    selected = select_targets(targets, path_name)
    selected_names = {target.name for target in selected}
    current_state = read_mirror_state(state)
    records = dict(current_state.get("paths", {}))
    sessions = list_mutagen_sessions(mutagen)
    configured_by_name = {target.name: target for target in targets}

    if path_name is None:
        _reconcile_removed_records(host, records, configured_by_name, sessions, mutagen)

    for target in selected:
        target.local.mkdir(parents=True, exist_ok=True)
        existing = sessions.get(target.session_name)
        record = records.get(target.name, {})
        record_hash = record.get("config_hash")
        if existing and record_hash and record_hash != target.config_hash:
            _run_mutagen(build_terminate_command(target.session_name, mutagen))
            sessions.pop(target.session_name, None)
            existing = None

        if existing:
            if existing.paused:
                _run_mutagen(build_resume_command(target.session_name, mutagen))
            sessions[target.session_name] = MutagenSession(
                name=target.session_name,
                identifier=existing.identifier,
                status="Watching for changes",
                active=True,
                paused=False,
                conflicted=existing.conflicted,
            )
        else:
            _run_mutagen(build_create_command(host, target, mutagen))
            sessions[target.session_name] = MutagenSession(
                name=target.session_name,
                status="Watching for changes",
                active=True,
            )
        records[target.name] = target.to_record()

    for target in targets:
        if target.name not in selected_names and target.name not in records:
            records[target.name] = target.to_record()

    write_mirror_state(
        state,
        {
            "version": MIRROR_STATE_VERSION,
            "host": str(_field(host, "name", "default")),
            "root": str(mirror_root(host)),
            "backend": mirror_backend(host),
            "mode": mirror_mode(host),
            "paths": records,
            "last_reconcile_time": time.time(),
        },
    )
    return status_payload(host, state, path_name=path_name, sessions=sessions)


def mirror_status(
    host: Any,
    state: HostState | None = None,
    *,
    path_name: str | None = None,
    mutagen_binary: str | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    state = state or HostState.for_host(str(_field(host, "name", "default")))
    sessions: dict[str, MutagenSession] = {}
    if refresh and mirror_enabled(host):
        mutagen = mutagen_binary or require_mutagen()
        sessions = list_mutagen_sessions(mutagen)
    return status_payload(host, state, path_name=path_name, sessions=sessions)


def mirror_doctor_checks(host: Any, state: HostState) -> list[tuple[str, bool, str]]:
    if not mirror_enabled(host):
        return []

    checks: list[tuple[str, bool, str]] = []
    mutagen_path = shutil.which("mutagen")
    checks.append(("local mutagen", bool(mutagen_path), mutagen_path or "not found"))

    scp_path = shutil.which("scp")
    checks.append(("local scp", bool(scp_path), scp_path or "not found"))

    try:
        targets = build_mirror_targets(host)
    except DevgateError as exc:
        checks.append(("mirror config", False, str(exc)))
        return checks
    checks.append(("mirror config", True, f"{len(targets)} configured path(s)"))

    root = mirror_root(host)
    root_detail = str(root) if root.exists() else f"missing: {root}"
    checks.append(("mirror root", root.exists(), root_detail))

    if not mutagen_path:
        return checks

    try:
        payload = mirror_status(host, state, mutagen_binary=mutagen_path)
    except DevgateError as exc:
        checks.append(("mirror sessions", False, str(exc)))
        return checks

    paused = payload.get("paused", [])
    conflicted = payload.get("conflicted", [])
    checks.append(("mirror paused sessions", not paused, ", ".join(paused) if paused else "none"))
    checks.append(
        (
            "mirror conflicts",
            not conflicted,
            ", ".join(conflicted) if conflicted else "none",
        )
    )
    return checks


def mirror_flush(
    host: Any,
    state: HostState | None = None,
    path_name: str | None = None,
) -> dict[str, Any]:
    return flush_mirror(host, state, path_name=path_name)


def mirror_pause(
    host: Any,
    state: HostState | None = None,
    path_name: str | None = None,
) -> dict[str, Any]:
    return pause_mirror(host, state, path_name=path_name)


def mirror_down(
    host: Any,
    state: HostState | None = None,
    path_name: str | None = None,
) -> dict[str, Any]:
    return down_mirror(host, state, path_name=path_name)


def status_payload(
    host: Any,
    state: HostState,
    *,
    path_name: str | None = None,
    sessions: dict[str, MutagenSession] | None = None,
) -> dict[str, Any]:
    sessions = sessions or {}
    targets = build_mirror_targets(host) if mirror_enabled(host) else []
    selected = select_targets(targets, path_name) if path_name else targets
    configured = [_target_status(target, sessions.get(target.session_name)) for target in selected]
    active = [item["name"] for item in configured if item["active"]]
    paused = [item["name"] for item in configured if item["paused"]]
    conflicted = [item["name"] for item in configured if item["conflicted"]]

    state_data = read_mirror_state(state)
    configured_names = {target.name for target in targets}
    removed = [
        _removed_status(name, record)
        for name, record in sorted(state_data.get("paths", {}).items())
        if (record.get("removed") or name not in configured_names)
        and (path_name is None or name == path_name)
    ]

    return {
        "enabled": mirror_enabled(host),
        "host": str(_field(host, "name", "default")),
        "root": str(mirror_root(host)),
        "backend": mirror_backend(host),
        "mode": mirror_mode(host),
        "state_file": str(mirror_state_file(state)),
        "configured": configured,
        "active": active,
        "paused": paused,
        "conflicted": conflicted,
        "removed": removed,
    }


def flush_mirror(
    host: Any,
    state: HostState | None = None,
    *,
    path_name: str | None = None,
    mutagen_binary: str | None = None,
) -> dict[str, Any]:
    return _run_target_command(host, state, path_name, mutagen_binary, build_flush_command)


def pause_mirror(
    host: Any,
    state: HostState | None = None,
    *,
    path_name: str | None = None,
    mutagen_binary: str | None = None,
) -> dict[str, Any]:
    return _run_target_command(host, state, path_name, mutagen_binary, build_pause_command)


def down_mirror(
    host: Any,
    state: HostState | None = None,
    *,
    path_name: str | None = None,
    mutagen_binary: str | None = None,
) -> dict[str, Any]:
    state = state or HostState.for_host(str(_field(host, "name", "default")))
    mutagen = mutagen_binary or require_mutagen()
    targets = build_mirror_targets(host) if mirror_enabled(host) else []
    selected = select_targets(targets, path_name) if targets else []
    sessions_to_stop = [target.session_name for target in selected]

    records = dict(read_mirror_state(state).get("paths", {}))
    if path_name is None:
        host_prefix = f"devgate.{_sanitize_component(str(_field(host, 'name', 'default')))}."
        for record in records.values():
            session = str(record.get("session_name", ""))
            if session.startswith(host_prefix):
                sessions_to_stop.append(session)
    sessions_to_stop = sorted(set(sessions_to_stop))
    for session in sessions_to_stop:
        _run_mutagen(build_terminate_command(session, mutagen))

    configured_names = {target.name for target in targets}
    for name, record in records.items():
        if path_name is None or name == path_name:
            record["active"] = False
            record["removed"] = name not in configured_names
    write_mirror_state(
        state,
        {
            "version": MIRROR_STATE_VERSION,
            "host": str(_field(host, "name", "default")),
            "root": str(mirror_root(host)),
            "backend": mirror_backend(host),
            "mode": mirror_mode(host),
            "paths": records,
            "last_reconcile_time": time.time(),
        },
    )
    return mirror_status(host, state, path_name=path_name, mutagen_binary=mutagen, refresh=False)


def _run_target_command(
    host: Any,
    state: HostState | None,
    path_name: str | None,
    mutagen_binary: str | None,
    command_builder,
) -> dict[str, Any]:
    state = state or HostState.for_host(str(_field(host, "name", "default")))
    if not mirror_enabled(host):
        return status_payload(host, state, sessions={})
    mutagen = mutagen_binary or require_mutagen()
    targets = select_targets(build_mirror_targets(host), path_name)
    for target in targets:
        _run_mutagen(command_builder(target.session_name, mutagen))
    return mirror_status(host, state, path_name=path_name, mutagen_binary=mutagen, refresh=False)


def _reconcile_removed_records(
    host: Any,
    records: dict[str, Any],
    configured_by_name: dict[str, MirrorTarget],
    sessions: dict[str, MutagenSession],
    mutagen_binary: str,
) -> None:
    for name, record in list(records.items()):
        if name in configured_by_name:
            continue
        session = str(record.get("session_name", ""))
        if session and session in sessions:
            _run_mutagen(build_terminate_command(session, mutagen_binary))
            sessions.pop(session, None)
        record["active"] = False
        record["removed"] = True


def _run_mutagen(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise DevgateError(f"Mutagen command failed ({' '.join(command)}){suffix}")
    return result


def _target_status(target: MirrorTarget, session: MutagenSession | None) -> dict[str, Any]:
    return {
        "name": target.name,
        "path_id": target.path_id,
        "remote": target.remote,
        "local": str(target.local),
        "ignore": list(target.ignore),
        "session_name": target.session_name,
        "path_hash": target.path_hash,
        "mode": target.mode,
        "status": session.status if session else "missing",
        "active": bool(session and session.active),
        "paused": bool(session and session.paused),
        "conflicted": bool(session and session.conflicted),
    }


def _removed_status(name: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "remote": record.get("remote"),
        "local": record.get("local"),
        "session_name": record.get("session_name"),
        "path_hash": record.get("path_hash"),
        "removed": True,
    }


def _validate_mirror(host: Any) -> None:
    backend = mirror_backend(host)
    if backend != DEFAULT_MIRROR_BACKEND:
        raise DevgateError(f"Unsupported mirror backend {backend!r}; expected 'mutagen'")
    mode = mirror_mode(host)
    if mode != DEFAULT_MIRROR_MODE:
        raise DevgateError(f"Unsupported mirror mode {mode!r}; expected 'one-way-safe'")


def _remote_endpoint(host: Any, target: MirrorTarget) -> str:
    return f"{_field(host, 'ssh_host', _field(host, 'name', 'default'))}:{target.remote}"


def _empty_state() -> dict[str, Any]:
    return {"version": MIRROR_STATE_VERSION, "paths": {}}


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _sanitize_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    if sanitized in {"", ".", ".."}:
        return "path"
    return sanitized
