from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from devgate.errors import DevgateError
from devgate.state import HostState
from devgate.sync import (
    MirrorTarget,
    MutagenSession,
    build_create_command,
    build_flush_command,
    build_list_command,
    build_mirror_targets,
    build_pause_command,
    build_resume_command,
    build_terminate_command,
    derive_local_path_names,
    down_mirror,
    mirror_doctor_checks,
    mirror_down,
    mirror_flush,
    mirror_pause,
    mirror_state_file,
    parse_mutagen_list,
    read_mirror_state,
    reconcile_mirror,
    session_name,
    status_payload,
    write_mirror_state,
)


@dataclass(frozen=True)
class FakeMirrorPath:
    remote: str
    ignore: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FakeMirror:
    enabled: bool = True
    root: str = ""
    backend: str = "mutagen"
    mode: str = "one-way-safe"
    paths: list[FakeMirrorPath] = field(default_factory=list)


@dataclass(frozen=True)
class FakeHost:
    name: str = "devbox"
    ssh_host: str = "devbox.example"
    mirror: FakeMirror = field(default_factory=FakeMirror)


def host_with_paths(tmp_path: Path, paths: list[FakeMirrorPath]) -> FakeHost:
    return FakeHost(mirror=FakeMirror(root=str(tmp_path / "Remote" / "devbox"), paths=paths))


def test_derive_local_path_names_adds_stable_duplicate_hash_suffixes() -> None:
    names = derive_local_path_names(
        [
            "/home/daniel/work/project-a",
            "/srv/other/project-a/",
            "/home/daniel/reports",
        ]
    )

    assert names[0].startswith("project-a--")
    assert names[1].startswith("project-a--")
    assert names[0] != names[1]
    assert names[2] == "reports"
    assert derive_local_path_names(["/home/daniel/work/project-a"])[0] == "project-a"


def test_build_mirror_targets_sanitizes_local_names_and_session_names(tmp_path: Path) -> None:
    host = host_with_paths(
        tmp_path,
        [FakeMirrorPath("/home/daniel/work/my project", ["node_modules/", ".venv/"])],
    )

    target = build_mirror_targets(host)[0]

    assert target.name == "my-project"
    assert target.local == tmp_path / "Remote" / "devbox" / "my-project"
    assert target.ignore == ["node_modules/", ".venv/"]
    assert target.session_name == "devgate.devbox.my-project"
    assert session_name("dev/box", "my project") == "devgate.dev-box.my-project"


def test_build_mutagen_commands_use_remote_alpha_and_local_beta(tmp_path: Path) -> None:
    host = FakeHost()
    target = MirrorTarget(
        name="project-a",
        path_id="project-a",
        remote="/home/daniel/work/project-a",
        local=tmp_path / "project-a",
        ignore=["node_modules/", ".venv/"],
        session_name="devgate.devbox.project-a",
        path_hash="abc12345",
    )

    assert build_create_command(host, target) == [
        "mutagen",
        "sync",
        "create",
        "--name=devgate.devbox.project-a",
        "--sync-mode=one-way-safe",
        "--ignore=node_modules/",
        "--ignore=.venv/",
        "devbox.example:/home/daniel/work/project-a",
        str(tmp_path / "project-a"),
    ]
    assert build_resume_command(target.session_name) == [
        "mutagen",
        "sync",
        "resume",
        target.session_name,
    ]
    assert build_list_command() == ["mutagen", "sync", "list"]
    assert build_flush_command(target.session_name) == [
        "mutagen",
        "sync",
        "flush",
        target.session_name,
    ]
    assert build_pause_command(target.session_name) == [
        "mutagen",
        "sync",
        "pause",
        target.session_name,
    ]
    assert build_terminate_command(target.session_name) == [
        "mutagen",
        "sync",
        "terminate",
        target.session_name,
    ]


def test_state_file_uses_host_state_property_when_present(tmp_path: Path) -> None:
    class CustomState:
        root = tmp_path / "ignored"
        mirror_state_file = tmp_path / "custom" / "mirror.json"

        def ensure(self) -> None:
            self.mirror_state_file.parent.mkdir(parents=True, exist_ok=True)

    state = CustomState()

    assert mirror_state_file(state) == tmp_path / "custom" / "mirror.json"
    write_mirror_state(state, {"version": 1, "paths": {"project-a": {"remote": "/r"}}})
    assert read_mirror_state(state)["paths"]["project-a"]["remote"] == "/r"


def test_state_file_falls_back_to_state_root(tmp_path: Path) -> None:
    state = HostState(tmp_path / "state")

    assert mirror_state_file(state) == tmp_path / "state" / "mirror.json"
    assert read_mirror_state(state) == {"version": 1, "paths": {}}


def test_parse_mutagen_list_detects_statuses() -> None:
    sessions = parse_mutagen_list(
        """
Name: devgate.devbox.active
Identifier: sync_active
Status: Watching for changes

Name: devgate.devbox.paused
Identifier: sync_paused
Status: Paused

Name: devgate.devbox.conflicted
Identifier: sync_conflicted
Status: Watching for changes
Conflicts:
    beta/file.txt
"""
    )

    assert sessions["devgate.devbox.active"].active is True
    assert sessions["devgate.devbox.paused"].paused is True
    assert sessions["devgate.devbox.conflicted"].conflicted is True


def test_status_payload_includes_configured_active_paused_conflicted_and_removed(
    tmp_path: Path,
) -> None:
    host = host_with_paths(
        tmp_path,
        [
            FakeMirrorPath("/remote/active"),
            FakeMirrorPath("/remote/paused"),
            FakeMirrorPath("/remote/conflicted"),
        ],
    )
    state = HostState(tmp_path / "state")
    write_mirror_state(
        state,
        {
            "version": 1,
            "paths": {
                "old": {
                    "remote": "/remote/old",
                    "local": str(tmp_path / "Remote" / "devbox" / "old"),
                    "session_name": "devgate.devbox.old",
                    "path_hash": "oldhash",
                    "removed": True,
                }
            },
        },
    )
    sessions = {
        "devgate.devbox.active": MutagenSession("devgate.devbox.active"),
        "devgate.devbox.paused": MutagenSession(
            "devgate.devbox.paused",
            status="Paused",
            active=False,
            paused=True,
        ),
        "devgate.devbox.conflicted": MutagenSession(
            "devgate.devbox.conflicted",
            conflicted=True,
        ),
    }

    payload = status_payload(host, state, sessions=sessions)

    assert [item["name"] for item in payload["configured"]] == ["active", "paused", "conflicted"]
    assert payload["active"] == ["active", "conflicted"]
    assert payload["paused"] == ["paused"]
    assert payload["conflicted"] == ["conflicted"]
    assert payload["removed"][0]["name"] == "old"


def test_reconcile_creates_resumes_and_terminates_removed_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = host_with_paths(
        tmp_path,
        [
            FakeMirrorPath("/remote/new"),
            FakeMirrorPath("/remote/paused"),
        ],
    )
    state = HostState(tmp_path / "state")
    write_mirror_state(
        state,
        {
            "version": 1,
            "paths": {
                "removed": {
                    "remote": "/remote/removed",
                    "local": str(tmp_path / "Remote" / "devbox" / "removed"),
                    "session_name": "devgate.devbox.removed",
                    "path_hash": "oldhash",
                }
            },
        },
    )
    commands: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        commands.append(command)
        stdout = ""
        if command[1:3] == ["sync", "list"]:
            stdout = """
Name: devgate.devbox.paused
Status: Paused

Name: devgate.devbox.removed
Status: Watching for changes
"""

        result = type("Result", (), {})()
        result.returncode = 0
        result.stderr = ""
        result.stdout = stdout
        return result

    monkeypatch.setattr("devgate.sync.shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("devgate.sync.subprocess.run", fake_run)

    payload = reconcile_mirror(host, state)

    assert ["/usr/bin/mutagen", "sync", "terminate", "devgate.devbox.removed"] in commands
    assert ["/usr/bin/mutagen", "sync", "resume", "devgate.devbox.paused"] in commands
    assert any(command[1:3] == ["sync", "create"] for command in commands)
    assert sorted(payload["active"]) == ["new", "paused"]
    saved = read_mirror_state(state)
    assert saved["paths"]["removed"]["removed"] is True
    assert saved["paths"]["new"]["remote"] == "/remote/new"


def test_reconcile_recreates_session_when_config_hash_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = host_with_paths(tmp_path, [FakeMirrorPath("/remote/project-a", ["node_modules/"])])
    state = HostState(tmp_path / "state")
    write_mirror_state(
        state,
        {
            "version": 1,
            "paths": {
                "project-a": {
                    "config_hash": "stale",
                    "session_name": "devgate.devbox.project-a",
                }
            },
        },
    )
    commands: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        commands.append(command)

        class Result:
            returncode = 0
            stderr = ""
            stdout = "Name: devgate.devbox.project-a\nStatus: Watching for changes\n"

        return Result()

    monkeypatch.setattr("devgate.sync.shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("devgate.sync.subprocess.run", fake_run)

    reconcile_mirror(host, state)

    assert ["/usr/bin/mutagen", "sync", "terminate", "devgate.devbox.project-a"] in commands
    assert any(command[1:3] == ["sync", "create"] for command in commands)


def test_target_selection_errors_for_unknown_path(tmp_path: Path) -> None:
    host = host_with_paths(tmp_path, [FakeMirrorPath("/remote/project-a")])

    with pytest.raises(DevgateError):
        status_payload(host, HostState(tmp_path / "state"), path_name="missing", sessions={})


def test_down_mirror_terminates_devgate_owned_state_sessions_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = host_with_paths(tmp_path, [FakeMirrorPath("/remote/project-a")])
    state = HostState(tmp_path / "state")
    write_mirror_state(
        state,
        {
            "version": 1,
            "paths": {
                "project-a": {"session_name": "devgate.devbox.project-a"},
                "foreign": {"session_name": "other.session"},
            },
        },
    )
    commands: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        commands.append(command)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("devgate.sync.shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("devgate.sync.subprocess.run", fake_run)

    down_mirror(host, state)

    assert ["/usr/bin/mutagen", "sync", "terminate", "devgate.devbox.project-a"] in commands
    assert ["/usr/bin/mutagen", "sync", "terminate", "other.session"] not in commands
    assert read_mirror_state(state)["paths"]["project-a"]["removed"] is False


def test_cli_named_wrappers_pass_optional_path_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = host_with_paths(tmp_path, [FakeMirrorPath("/remote/project-a")])
    state = HostState(tmp_path / "state")
    commands: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        commands.append(command)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("devgate.sync.shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("devgate.sync.subprocess.run", fake_run)

    mirror_flush(host, state, "project-a")
    mirror_pause(host, state, "project-a")
    mirror_down(host, state, "project-a")

    assert ["/usr/bin/mutagen", "sync", "flush", "devgate.devbox.project-a"] in commands
    assert ["/usr/bin/mutagen", "sync", "pause", "devgate.devbox.project-a"] in commands
    assert ["/usr/bin/mutagen", "sync", "terminate", "devgate.devbox.project-a"] in commands


def test_mirror_doctor_checks_report_mutagen_root_and_session_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = host_with_paths(tmp_path, [FakeMirrorPath("/remote/project-a")])
    state = HostState(tmp_path / "state")

    def fake_which(binary):
        return f"/usr/bin/{binary}" if binary in {"mutagen", "scp"} else None

    def fake_run(command, capture_output, text, check):
        class Result:
            returncode = 0
            stderr = ""
            stdout = "Name: devgate.devbox.project-a\nStatus: Paused\n"

        return Result()

    monkeypatch.setattr("devgate.sync.shutil.which", fake_which)
    monkeypatch.setattr("devgate.sync.subprocess.run", fake_run)

    checks = {label: (ok, detail) for label, ok, detail in mirror_doctor_checks(host, state)}

    assert checks["local mutagen"] == (True, "/usr/bin/mutagen")
    assert checks["local scp"] == (True, "/usr/bin/scp")
    assert checks["mirror root"][0] is False
    assert checks["mirror paused sessions"] == (False, "project-a")
