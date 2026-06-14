# devgate

`devgate` is a localhost gateway for remote development.

It helps an SSH-accessible dev box feel low-friction without pretending the remote
filesystem is local. The local CLI manages SSH port forwards, installs small remote
helpers, starts a private artifact browser, and teaches coding agents how to publish
inspectable work safely.

## Goals

- Use Mosh or SSH for the interactive terminal.
- Use SSH as the boring control plane.
- Forward remote `127.0.0.1:<port>` to local `127.0.0.1:<port>`.
- Publish remote files, reports, images, PDFs, notebooks, and logs through a stable
  local artifact URL.
- Give agents consistent instructions for choosing ports and exposing artifacts.
- Avoid proprietary services and commercial dependencies.
- Bind everything to loopback by default.

## Install

From a checkout:

```bash
uv tool install .
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

[agents]
targets = ["codex", "claude", "generic"]
install_dir = "~/.agents"
```

Then run:

```bash
dvg devbox
```

That reconciles the backend and opens an interactive remote shell.

## Commands

```bash
dvg <host>                 # up, then shell
dvg up <host>              # reconcile backend only
dvg shell <host>           # reconcile, then open Mosh/tmux or SSH/tmux
dvg status <host>          # show tunnel and artifact status
dvg doctor <host>          # check local and remote prerequisites
dvg ports <host>           # list effective forwarded ports
dvg install-agents <host>  # install only helper and agent instruction files
dvg show <host> <path>     # publish a remote file or directory
dvg down <host>            # stop the devgate-owned SSH tunnel
```

If a host is missing from the config, `dvg` uses the host name as the SSH host and
falls back to safe defaults.

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
- Avoid `0.0.0.0`, public tunnels, and remote port forwarding unless explicitly asked.

## Security Model

`devgate` is local-first and loopback-only by default:

- Local forwards bind to `127.0.0.1`.
- Remote helper services bind to `127.0.0.1`.
- No remote port forwarding is used.
- No public tunnels are started.
- The remote artifact server is visible locally only through SSH forwarding.

`devgate` does not try to sandbox remote content. Treat files served through the artifact
browser as files from your own remote machine.

## Status

This is an alpha MVP. The core control-plane pieces are present, with intentionally
simple remote service management. Future work includes richer Markdown and notebook
rendering, optional sync backends, browser auto-open, shell completions, and more
robust service supervision.
