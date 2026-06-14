# devgate

`devgate` is a localhost gateway for remote development.

It helps an SSH-accessible dev box feel low-friction without pretending the remote
filesystem is local. The local CLI manages SSH port forwards, installs small remote
helpers, starts a private artifact browser, mirrors selected remote paths into a
local directory with Mutagen, and teaches coding agents how to publish inspectable
work safely.

## Goals

- Use Mosh or SSH for the interactive terminal.
- Use SSH as the boring control plane.
- Forward remote `127.0.0.1:<port>` to local `127.0.0.1:<port>`.
- Publish remote files, reports, images, PDFs, notebooks, and logs through a stable
  local artifact URL.
- Mirror selected remote directories under a host-scoped local root without making
  the remote filesystem writable from local edits.
- Give agents consistent instructions for choosing ports and exposing artifacts.
- Avoid proprietary services and commercial dependencies.
- Bind everything to loopback by default.

## Install

From a checkout:

```bash
uv tool install .
```

From a GitHub release tag:

```bash
uv tool install git+https://github.com/dburkhardt/devgate.git@v1.0.0
```

`devgate` is released through GitHub only. It is not published to PyPI.

For mirror support, install Mutagen locally. On macOS or Linux with Homebrew:

```bash
brew install mutagen-io/mutagen/mutagen
```

For development:

```bash
uv sync --extra dev
uv run dvg --help
uv run pytest
```

## Quick Start

Create `~/.config/devgate/config.toml`:

```toml
[hosts.devbox]
ssh_host = "devbox"
remote_workdir = "/home/daniel/work"
remote_state_dir = "/home/daniel/.devgate"
remote_artifact_dir = "/home/daniel/share/artifacts"

[hosts.devbox.session]
mosh = true
multiplexer = "tmux"
session_name = "dev"

[hosts.devbox.ports]
collision_policy = "skip"
ranges = [
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
explicit = [17800]

[hosts.devbox.artifacts]
server_port = 17800
server_bind = "127.0.0.1"
remote_dir = "/home/daniel/share/artifacts"

[hosts.devbox.mirror]
enabled = true
root = "~/Remote/devbox"
backend = "mutagen"
mode = "one-way-safe"

[[hosts.devbox.mirror.paths]]
remote = "/home/daniel/work/project-a"
ignore = ["node_modules/", ".venv/", "__pycache__/"]

[[hosts.devbox.mirror.paths]]
remote = "/home/daniel/reports"
ignore = ["*.tmp"]

[agents]
targets = ["codex", "claude", "generic"]
install_dir = "~/.agents"
```

Then run:

```bash
dvg devbox
```

That reconciles the backend, starts any configured mirror sessions, and opens an
interactive remote shell.

## Commands

```bash
dvg <host>                 # up, then shell
dvg up <host>              # reconcile backend and enabled mirror sessions
dvg up <host> --no-sync    # reconcile backend without starting mirror sessions
dvg shell <host>           # reconcile, then open Mosh/tmux or SSH/tmux
dvg status <host>          # show tunnel and artifact status
dvg doctor <host>          # check local and remote prerequisites
dvg ports <host>           # list effective forwarded ports
dvg install-agents <host>  # install only helper and agent instruction files
dvg show <host> <path>     # publish a remote file or directory
dvg down <host>            # stop the devgate-owned SSH tunnel
dvg sync up <host>         # create or resume configured Mutagen mirror sessions
dvg sync status <host> [--json]       # show configured, active, paused, conflicted, removed
dvg sync flush <host> [path-name]     # wait for mirror sessions to settle
dvg sync pause <host> [path-name]     # pause mirror sessions
dvg sync down <host> [path-name]      # terminate devgate-owned mirror sessions
```

If a host is missing from the config, `dvg` uses the host name as the SSH host and
falls back to safe defaults.

## Remote Mirror

When `[hosts.<host>.mirror]` is enabled, `devgate` uses local Mutagen sessions over
SSH to mirror selected remote paths into the configured `root`.

Remote paths are mapped by basename, so `/home/daniel/work/project-a` becomes
`~/Remote/devbox/project-a`. If two configured paths have the same basename, devgate
adds a stable short hash suffix such as `project-a--7f3a91c2`. Removing a path from
config marks it inactive, but devgate leaves the local copy on disk.

The v1 mirror mode is `one-way-safe`: remote changes flow into the local mirror,
local edits do not flow back to the remote machine, and conflicts are surfaced in
`dvg sync status` instead of being silently resolved. Treat the remote machine as
the source of truth.

## Remote Helpers

`devgate` installs helper scripts under `~/.devgate/bin` by default:

- `devgate-show <path>` publishes a file or directory to the artifact root.
- `devgate-port --pick web|api|vite|tensorboard|jupyter|gradio|misc` prints one
  available forwarded port.
- `devgate-artifacts` prints the artifact root and local browser base URL.
- `devgate-status` prints the effective remote config.

The artifact server is started remotely with Python's standard library HTTP server,
bound to `127.0.0.1`, and reached locally through SSH forwarding.

## Agent Instructions

`devgate` installs a canonical instruction pack in `~/.agents/devgate`, plus thin
adapters for Codex, Claude, and generic agents. The instructions tell agents to:

- Bind servers to `127.0.0.1`.
- Prefer forwarded ports from `devgate-port`.
- Publish inspectable artifacts with `devgate-show`.
- Report local URLs as `http://localhost:<port>/`.
- Treat remote paths as the source of truth and avoid writing into the local mirror
  as a way to change remote state.
- Avoid `0.0.0.0`, public tunnels, and remote port forwarding unless explicitly asked.

## Security Model

`devgate` is local-first and loopback-only by default:

- Local forwards bind to `127.0.0.1`.
- Remote helper services bind to `127.0.0.1`.
- No remote port forwarding is used.
- No public tunnels are started.
- The remote artifact server is visible locally only through SSH forwarding.
- Mirror sessions use Mutagen over SSH and default to one-way-safe sync from remote
  to local.

`devgate` does not try to sandbox remote content. Treat files served through the artifact
browser as files from your own remote machine.

## Status

This is an alpha MVP. The core control-plane pieces are present, with intentionally
simple remote service management. Future work includes richer Markdown and notebook
rendering, browser auto-open, shell completions, and more robust service supervision.
