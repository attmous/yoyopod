---
name: yoyopod-logs
description: Tail application logs from Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyopod remote:*)
argument-hint: "[line_count] [--errors] [--filter <subsystem>] [--follow]"
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, project dir, and branch. `yoyopod remote` merges them directly, and `yoyopod remote config edit` is the preferred way to create or update the local override.

If the file does not exist yet, run `yoyopod remote config edit` first. That command creates `deploy/pi-deploy.local.yaml` automatically before opening it.

## Argument Parsing

Parse the arguments string provided after `/yoyopod-logs`:

- **Line count:** If a bare number is present (for example `/yoyopod-logs 100`), map it to `--lines <count>`. Default: 100.
- **--errors flag:** Pass through to `yoyopod remote logs --errors`.
- **--filter value:** Pass through to `yoyopod remote logs --filter <value>`.
- **--follow flag:** Pass through to `yoyopod remote logs --follow`.

Multiple flags can be combined.

## Steps

1. **Build the helper command.** Use:
   ```bash
   yoyopod remote logs ...
   ```
   Add `--lines`, `--errors`, `--filter`, and `--follow` based on the parsed arguments.

2. **Present the log output.** Return the raw log lines directly. Do not summarize or truncate unless the user explicitly asks.

After presenting the logs, remind the user they can ask follow-up questions about the log content, such as "why did the call drop?" or "what errors happened in the last minute?"
