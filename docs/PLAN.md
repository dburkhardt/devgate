# devgate End-to-End Build Plan

`devgate` is the project and Python package. The installed primary command is `dvg`.
For now, remote helpers keep the explicit `devgate-*` prefix so they remain readable
inside remote shells and agent instructions.

## Principles

- Keep SSH as the control plane and Mosh/tmux as the interactive path.
- Make forwarded `localhost` the universal interface; do not make the remote
  filesystem pretend to be local.
- Mirror only explicitly configured remote paths into a host-scoped local directory;
  remote remains the source of truth.
- Bind local forwards and remote helper services to `127.0.0.1` by default.
- Prefer boring, inspectable behavior over background magic.
- Keep commercial-license dependencies out of the core path.

## Subagent Model

Use one integration owner plus focused subagents. Each subagent owns a bounded surface,
tests for that surface, and one short handoff note per stage.

| Role | Owns | Does not own |
| --- | --- | --- |
| Integration Lead | Stage contract, public CLI shape, merge order, release gates | Deep implementation inside each lane |
| CLI and Config Agent | `dvg` command UX, config parsing, defaults, help text, errors | SSH process internals, remote helper scripts |
| Tunnel and Ports Agent | SSH tunnel lifecycle, state files, port plans, collision policy | Artifact rendering, agent docs |
| Mirror Sync Agent | Mutagen sessions, mirror state, `dvg sync` commands, mirror doctor checks | Artifact publishing, remote helper scripts |
| Remote Helpers Agent | `devgate-show`, `devgate-port`, `devgate-artifacts`, `devgate-status` | Local CLI parser and package metadata |
| Agent Instructions Agent | Codex, Claude, generic/Droid instruction packs | Tunnel implementation |
| QA Agent | Unit tests, integration tests, smoke scripts, CI matrix | Product decisions |
| Security Agent | Threat model, bind checks, command/path quoting, dependency review | Feature polish |
| Docs and Release Agent | README, examples, changelog, GitHub release checklist | Security signoff |

Subagents should work behind contracts: command names, config schema, effective-config
JSON, helper names, and state-file layout. Contract changes require Integration Lead
approval before implementation.

## Integration Rhythm

- Stage kickoff: Integration Lead writes the acceptance criteria and any contract changes.
- Parallel build: subagents work in their lanes and add focused tests with each change.
- Mid-stage sync: verify no drift in CLI names, helper names, config keys, and JSON shape.
- Merge gate: QA Agent runs the full verification set and Security Agent checks the stage's
  changed surfaces.
- Stage close: update docs, mark open questions, tag an internal checkpoint if useful.

## Stage 0: Baseline and Project Hygiene

Goal: make the current alpha easy to build, test, and contribute to.

Scope:
- Confirm repo layout, package metadata, license, README, and contribution path.
- Keep `dvg` as the documented command; decide whether `devgate` stays as an alias.
- Add or verify `tests/`, CI, linting, formatting, and minimal smoke fixtures.
- Document the state directory, mirror state directory, remote file layout, and GitHub-only
  release path.

Gate criteria:
- `uv sync --extra dev`, `uv run dvg --help`, `uv run pytest`, and `uv run ruff check .`
  pass on a clean checkout.
- `README.md` accurately describes `dvg`, `devgate-*` helpers, mirror config, config
  location, GitHub install, and alpha status.
- CI runs on supported Python versions.
- Security Agent confirms no default public binds and no secret-bearing logs in normal flows.

## Stage 1: MVP Control Plane

Goal: a user can run `dvg <host>` and get a working tunnel, artifact server, helpers,
and remote shell on an SSH-accessible machine.

Scope:
- `dvg <host>`, `dvg up`, `dvg shell`, `dvg status`, `dvg doctor`, `dvg ports`,
  `dvg show`, `dvg install-agents`, `dvg up --no-sync`, and `dvg down`.
- TOML config with safe defaults when a host has no explicit entry.
- SSH tunnel process management with config hash, PID file, log file, and restart behavior.
- Local `127.0.0.1:<port>` to remote `127.0.0.1:<port>` forwards.
- Artifact server on the stable tool port, bound to loopback.
- Effective config written remotely for helpers and agents.

Gate criteria:
- Fresh host smoke: `dvg up devbox`, `dvg status devbox`, `dvg ports devbox`,
  `dvg show devbox <file>`, and `dvg down devbox` work against a real SSH host.
- Required artifact port fails clearly when unavailable.
- General port collisions follow `fail`, `skip`, and `kill-owned` semantics.
- Remote effective config contains only actually forwarded ports.
- `doctor` reports local SSH, local Mosh when enabled, local Python, SSH reachability,
  remote Python, remote write permissions, and port-plan status.

## Stage 2: Mutagen Mirror

Goal: selected remote directories are mirrored locally with explicit, inspectable,
one-way-safe Mutagen sessions.

Scope:
- Config schema under `[hosts.<host>.mirror]` with `enabled`, `root`, `backend = "mutagen"`,
  `mode = "one-way-safe"`, and repeated `[[hosts.<host>.mirror.paths]]` entries with
  `remote` and optional `ignore`.
- Local mirror state under `~/.local/state/devgate/<host>/mirror.json`, recording remote
  paths, derived local paths, session names, path hashes, active/removed status, and last
  reconcile time.
- Local path naming by remote basename; duplicate basenames get a stable short hash suffix.
  Removed config entries become inactive and are never deleted by default.
- `dvg sync up <host>`, `dvg sync status <host> [--json]`, and
  `dvg sync flush|pause|down <host> [path-name]`.
- `dvg up <host>` starts mirror reconciliation when enabled; `dvg up <host> --no-sync`
  skips mirror reconciliation.
- Mutagen commands use remote alpha and local beta, `--sync-mode=one-way-safe`, and repeated
  `--ignore` flags.
- `doctor` checks local Mutagen, SSH/scp viability, mirror root, invalid duplicate paths,
  paused sessions, and conflicted sessions.
- README documents Mutagen installation with Homebrew:
  `brew install mutagen-io/mutagen/mutagen`.

Gate criteria:
- Unit tests cover mirror config defaults/validation, local path naming, duplicate suffixes,
  removed path behavior, and Mutagen command construction.
- CLI tests cover `dvg sync up/status/flush/pause/down`, `dvg up --no-sync`, and JSON status.
- Integration smoke verifies remote changes appear locally, local edits do not propagate
  remotely, conflicts are reported, and `dvg sync down` terminates only devgate-owned sessions.
- Security Agent signs off that local mirror paths cannot escape the configured root and all
  remote/local paths are safely quoted.

## Stage 3: Remote Helper Quality

Goal: remote helpers are safe, scriptable, and useful to humans and agents.

Scope:
- `devgate-port` prints only the chosen port by default and validates requested ports.
- `devgate-show` publishes files and directories, preserves inspectable names, and prints
  local browser URLs.
- `devgate-artifacts` and `devgate-status` read the effective config and fail clearly when
  devgate has not been reconciled.
- Helper installation is idempotent and atomic enough to survive interrupted runs.

Gate criteria:
- Helper tests run locally with fixture effective configs.
- Remote smoke covers files, directories, missing paths, port picks, and invalid ports.
- Helpers never bind services to public interfaces.
- Shell quoting and path handling pass Security Agent review.

## Stage 4: Agent Instruction Packs

Goal: coding agents consistently expose work through forwarded localhost and artifact URLs.

Scope:
- Canonical instruction pack in `~/.agents/devgate`.
- Thin adapters for Codex, Claude, and generic/Droid-style agents.
- Instructions for choosing ports, binding to loopback, publishing artifacts, and reporting URLs.
- Instructions that remote paths remain the source of truth and agents should not write into
  the local mirror to change remote state.
- Compatibility notes for remote shells without all optional tools installed.

Gate criteria:
- Installed instruction files mention `dvg` locally and `devgate-*` remotely with no stale names.
- Instructions include positive examples and hard safety rules for `127.0.0.1`.
- Manual agent smoke: ask an agent to launch a demo server and publish an artifact; verify the
  resulting local URL works.
- Security Agent signs off that instructions do not encourage public tunnels, `0.0.0.0`, or
  remote port forwarding.

## Stage 5: Artifact Experience

Goal: common remote outputs are easy to inspect locally.

Scope:
- Direct publication for images, HTML, PDFs, CSVs, logs, reports, and directories.
- Markdown rendered to HTML when an open-source renderer is available; otherwise copied.
- Notebooks exported to HTML when `jupyter nbconvert` is available; otherwise copied.
- Optional browser auto-open behind an explicit flag or config key.

Gate criteria:
- Fixture suite covers supported artifact types and graceful fallback paths.
- Generated artifact URLs are stable and do not leak remote absolute paths unnecessarily.
- Large-file behavior is documented and does not hang the CLI without progress or failure.
- Any optional renderer dependency is documented and excluded from the hard core path unless
  intentionally promoted.

## Stage 6: Reliability and UX Hardening

Goal: devgate feels predictable across repeated daily use.

Scope:
- Robust tunnel liveness checks, including a sentinel forwarded port or equivalent probe.
- Locking around reconcile/down to avoid concurrent state corruption.
- Locking around mirror reconcile/down to avoid concurrent Mutagen state corruption.
- Better status output and `--json` contracts for automation.
- Clear recovery guidance for stale PIDs, changed configs, broken SSH, and remote permission errors.
- Shell completions and `dvg config init` if the UX needs them.

Gate criteria:
- Repeated reconcile cycles reuse healthy tunnels and restart stale/mismatched tunnels.
- Concurrent invocations do not corrupt state.
- JSON output is schema-tested and documented.
- Common failure cases have actionable messages.
- Manual smoke passes on macOS and at least one Linux local machine.

## Stage 7: Security Review and Beta

Goal: harden the public beta before broader installation.

Scope:
- Written threat model for local machine, SSH host, remote helper files, artifact server,
  Mutagen mirror sessions, local mirror files, and agent-generated content.
- Audit subprocess calls, shell quoting, remote script generation, file permissions, symlink
  handling, and artifact publishing.
- Dependency and license review.
- Confirm no telemetry, no public tunnels, no remote port forwarding, and no privileged install path.

Gate criteria:
- Security checklist is complete and linked from the release notes.
- Artifact server and forwards are loopback-only in code, docs, tests, and agent instructions.
- Path traversal and shell injection tests pass for CLI inputs and helper inputs.
- Dependency licenses are compatible with open-source distribution.
- Beta release candidate has no known high-severity security issues.

## Stage 8: GitHub Release

Goal: ship a clean open-source release through GitHub that users can install and trust.

Scope:
- Finalize versioning, changelog, license, contribution guide, issue templates, and support policy.
- Build and verify source distribution and wheel artifacts locally.
- Create GitHub release with signed tag if available.
- Attach release artifacts to GitHub Releases.
- Document install with `uv tool install git+https://github.com/dburkhardt/devgate.git@v1.0.0`.
- State explicitly that devgate is not published to PyPI.
- Optional follow-up docs: standalone installer notes and shell completions.

Gate criteria:
- `python -m build` or the chosen build command produces clean artifacts.
- GitHub URL install verifies `dvg --version`, `dvg --help`, and a no-config host path.
- GitHub release includes changelog, install instructions, wheel/source artifacts, known
  limitations, and security model.
- No TestPyPI or PyPI publish job exists in CI or release docs.
- Release is reproducible from a clean checkout.

## v1 Gate

v1 requires:
- Stable `dvg` command surface and config schema, with documented compatibility expectations.
- MVP workflows work on real SSH hosts without hand-editing remote files.
- Remote helpers and agent instructions are installed idempotently.
- CI, unit tests, integration smoke tests, and security tests pass.
- Public docs cover install, quick start, config, commands, security model, troubleshooting,
  mirror setup, Mutagen installation, and agent workflows.
- At least one pre-v1 user feedback cycle has been incorporated or explicitly deferred.

## Verification Matrix

- Unit: config parsing, mirror config, port expansion, collision policy, state hashing,
  helper config parsing.
- CLI: parser behavior, help text, JSON output, expected error messages.
- Local integration: tunnel command construction, state reuse/restart, down cleanup.
- Mirror integration: Mutagen command construction, session lifecycle, one-way-safe behavior,
  conflict reporting, and removed-path handling.
- Remote integration: helper installation, artifact server, helper commands, Mosh/tmux fallback.
- Security: loopback bind assertions, shell quoting, path traversal, file permissions,
  dependency/license audit.
- Release: clean build, GitHub URL install, `uv tool install`, GitHub release smoke.

## Open Questions

- Should `devgate` remain as a long-form CLI alias after v1, or should `dvg` be the only command?
- Is `kill-owned` necessary for v1, or can it remain a documented post-v1 enhancement?
- Should `dvg down` stop the remote artifact server or only the local SSH tunnel?
- Should browser auto-open be opt-in per command, per host config, or omitted from v1?
- What is the minimum supported remote environment: Python version, shell assumptions, tmux, Mosh?
- How should Droid-specific instructions differ from the generic adapter once its interface is known?
- Should rendered Markdown/notebooks live in-place under the artifact root or in a generated cache?
- Is there a future `devgate-*` helper rename, or is the explicit prefix a permanent remote API?
