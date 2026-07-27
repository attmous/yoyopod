---
name: yoyopod-logs
description: Tail yoyopod runtime/service logs from Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyopod target:*)
argument-hint: "[line_count] [--errors] [--filter <subsystem>] [--follow]"
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and
`deploy/pi-deploy.local.yaml` for machine-specific overrides such as
host, SSH user, dev lane checkout, and branch. The tracked dev default
is `/opt/yoyopod-dev/checkout`; prod slots live under `/opt/yoyopod-prod`.
`yoyopod target` merges the files directly, and `yoyopod target config
edit` is the preferred way to create or update the local override.

If the file does not exist yet, run `yoyopod target config edit` first.
That command creates `deploy/pi-deploy.local.yaml` automatically before
opening it.

## Argument Parsing

Parse the arguments string provided after `/yoyopod-logs`:

- **Line count:** If a bare number is present (for example
  `/yoyopod-logs 100`), map it to `--lines <count>`. Default: 100.
- **--errors flag:** Pass through to `yoyopod target logs --errors`.
- **--filter value:** Pass through to `yoyopod target logs --filter <value>`.
- **--follow flag:** Pass through to `yoyopod target logs --follow`.

Multiple flags can be combined.

## Steps

1. **Build the helper command.** Use:
   ```bash
   yoyopod target logs ...
   ```
   Add `--lines`, `--errors`, `--filter`, and `--follow` based on the
   parsed arguments.

2. **If lane state matters, also run:**
   ```bash
   yoyopod target mode status
   ```

3. **Present the log output.** Return the raw log lines directly. Do
   not summarize or truncate unless the user explicitly asks.

After presenting the logs, remind the user they can ask follow-up
questions about the log content, such as "why did the call drop?" or
"what errors happened in the last minute?"
