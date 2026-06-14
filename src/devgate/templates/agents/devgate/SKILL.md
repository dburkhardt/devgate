# devgate

Use devgate whenever you launch a web server, API server, notebook server, report
viewer, dashboard, or generated artifact on this remote machine.

## Ports

- Bind development servers to `127.0.0.1`.
- Never bind to `0.0.0.0` unless the user explicitly asks for public exposure.
- Prefer ports from the effective forwarded port list.
- Choose a port with `devgate-port --pick web`, `devgate-port --pick api`,
  `devgate-port --pick vite`, `devgate-port --pick jupyter`,
  `devgate-port --pick tensorboard`, `devgate-port --pick gradio`, or
  `devgate-port --pick misc`.
- `devgate-port` prints only the port, so it is safe in shell scripts:

```bash
PORT=$(devgate-port --pick web)
npm run dev -- --host 127.0.0.1 --port "$PORT"
```

Report local browser URLs as `http://localhost:<port>/`, not remote host URLs.

## Local Mirror

The remote machine remains the source of truth. devgate may sync selected remote
paths into a local mirror such as `~/Remote/<host>` using Mutagen, but that mirror
is for local reading, search, and inspection.

- Do not write into the local mirror as a way to change remote files.
- Make project edits in the remote workspace where you are running.
- If the user needs a durable, inspectable output, publish it with `devgate-show`
  instead of relying on the local mirror path.

## Artifacts

Publish files the user should inspect with:

```bash
devgate-show path/to/file-or-directory
```

Use this for Markdown, HTML, images, PDFs, notebooks, logs, CSVs, generated reports,
figures, and directories. Put durable user-viewable outputs under the configured
artifact root when practical.

## Security Defaults

- Use local loopback addresses.
- Do not start public tunnels.
- Do not use remote port forwarding unless explicitly requested.
- Do not expose services on public interfaces.

Check `devgate-status` when you need the artifact URL, forwarded ports, or helper
locations.
