# devgate End-to-End Build Plan

`devgate` is the project and Python package. The installed primary command is `dvg`.
For now, remote helpers keep the explicit `devgate-*` prefix so they remain readable
inside remote shells and agent instructions.

## Principles

- Keep SSH as the control plane and Mosh/tmux as the interactive path.
- Make forwarded `localhost` the universal interface; do not make the remote
  filesystem pretend to be local.
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
| Remote Helpers Agent | `devgate-show`, `devgate-port`, `devgate-artifacts`, `devgate-status` | Local CLI parser and package metadata |
| Agent Instructions Agent | Codex, Claude, generic/Droid instruction packs | Tunnel implementation |
| QA Agent | Unit tests, integration tests, smoke scripts, CI matrix | Product decisions |
| Security Agent | Threat model, bind checks, command/path quoting, dependency review | Feature polish |
| Docs and Release Agent | README, examples, changelog, PyPI/GitHub release checklist | Security signoff |

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
- Document the state directory and remote file layout.

Gate criteria:
- `uv sync --extra dev`, `uv run dvg --help`, `uv run pytest`, and `uv run ruff check .`
  pass on a clean checkout.
- `README.md` accurately describes `dvg`, `devgate-*` helpers, config location, and alpha status.
- CI runs on supported Python versions.
- Security Agent confirms no default public binds and no secret-bearing logs in normal flows.

## Stage 1: MVP Control Plane

Goal: a user can run `dvg <host>` and get a working tunnel, artifact server, helpers,
and remote shell on an SSH-accessible machine.

Scope:
- `dvg <host>`, `dvg up`, `dvg shell`, `dvg status`, `dvg doctor`, `dvg ports`,
  `dvg show`, `dvg install-agents`, and `dvg down`.
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

## Stage 2: Remote Helper Quality

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

## Stage 3: Agent Instruction Packs

Goal: coding agents consistently expose work through forwarded localhost and artifact URLs.

Scope:
- Canonical instruction pack in `~/.agents/devgate`.
- Thin adapters for Codex, Claude, and generic/Droid-style agents.
- Instructions for choosing ports, binding to loopback, publishing artifacts, and reporting URLs.
- Compatibility notes for remote shells without all optional tools installed.

Gate criteria:
- Installed instruction files mention `dvg` locally and `devgate-*` remotely with no stale names.
- Instructions include positive examples and hard safety rules for `127.0.0.1`.
- Manual agent smoke: ask an agent to launch a demo server and publish an artifact; verify the
  resulting local URL works.
- Security Agent signs off that instructions do not encourage public tunnels, `0.0.0.0`, or
  remote port forwarding.

## Stage 4: Artifact Experience

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

## Stage 5: Reliability and UX Hardening

Goal: devgate feels predictable across repeated daily use.

Scope:
- Robust tunnel liveness checks, including a sentinel forwarded port or equivalent probe.
- Locking around reconcile/down to avoid concurrent state corruption.
- Better status output and `--json` contracts for automation.
- Clear recovery guidance for stale PIDs, changed configs, broken SSH, and remote permission errors.
- Shell completions and `dvg config init` if the UX needs them.

Gate criteria:
- Repeated reconcile cycles reuse healthy tunnels and restart stale/mismatched tunnels.
- Concurrent invocations do not corrupt state.
- JSON output is schema-tested and documented.
- Common failure cases have actionable messages.
- Manual smoke passes on macOS and at least one Linux local machine.

## Stage 6: Security Review and Beta

Goal: harden the public beta before broader installation.

Scope:
- Written threat model for local machine, SSH host, remote helper files, artifact server,
  and agent-generated content.
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

## Stage 7: Release and Publish

Goal: ship a clean open-source release that users can install and trust.

Scope:
- Finalize versioning, changelog, license, contribution guide, issue templates, and support policy.
- Build and verify source distribution and wheel.
- Publish to TestPyPI, install with `uv tool install`, then publish to PyPI.
- Create GitHub release with signed tag if available.
- Optional follow-up packaging: Homebrew formula, standalone installer notes, shell completions.

Gate criteria:
- `python -m build` or the chosen build command produces clean artifacts.
- TestPyPI install verifies `dvg --version`, `dvg --help`, and a no-config host path.
- PyPI metadata points to `https://github.com/dburkhardt/devgate`.
- GitHub release includes changelog, install instructions, known limitations, and security model.
- Release is reproducible from a clean checkout.

## v1 Gate

v1 requires:
- Stable `dvg` command surface and config schema, with documented compatibility expectations.
- MVP workflows work on real SSH hosts without hand-editing remote files.
- Remote helpers and agent instructions are installed idempotently.
- CI, unit tests, integration smoke tests, and security tests pass.
- Public docs cover install, quick start, config, commands, security model, troubleshooting,
  and agent workflows.
- At least one pre-v1 user feedback cycle has been incorporated or explicitly deferred.

## Verification Matrix

- Unit: config parsing, port expansion, collision policy, state hashing, helper config parsing.
- CLI: parser behavior, help text, JSON output, expected error messages.
- Local integration: tunnel command construction, state reuse/restart, down cleanup.
- Remote integration: helper installation, artifact server, helper commands, Mosh/tmux fallback.
- Security: loopback bind assertions, shell quoting, path traversal, file permissions,
  dependency/license audit.
- Release: clean build, TestPyPI install, `uv tool install`, GitHub release smoke.

## Open Questions

- Should `devgate` remain as a long-form CLI alias after v1, or should `dvg` be the only command?
- Is `kill-owned` necessary for v1, or can it remain a documented post-v1 enhancement?
- Should `dvg down` stop the remote artifact server or only the local SSH tunnel?
- Should browser auto-open be opt-in per command, per host config, or omitted from v1?
- What is the minimum supported remote environment: Python version, shell assumptions, tmux, Mosh?
- How should Droid-specific instructions differ from the generic adapter once its interface is known?
- Should rendered Markdown/notebooks live in-place under the artifact root or in a generated cache?
- Is there a future `devgate-*` helper rename, or is the explicit prefix a permanent remote API?
