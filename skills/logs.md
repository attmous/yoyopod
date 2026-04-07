---
name: logs
description: Tail application logs from Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
argument-hint: "[line_count] [--errors] [--filter <subsystem>] [--follow]"
---

## Config

Use `deploy/pi-deploy.yaml` as the single source of truth for Raspberry Pi log paths. `scripts/pi_remote.py` reads this file directly.

If the file does not exist, stop and tell the user to create it.

## Argument Parsing

Parse the arguments string provided after `/logs`:

- **Line count:** If a bare number is present (for example `/logs 100`), map it to `--lines <count>`. Default: 100.
- **--errors flag:** Pass through to `scripts/pi_remote.py logs --errors`.
- **--filter value:** Pass through to `scripts/pi_remote.py logs --filter <value>`.
- **--follow flag:** Pass through to `scripts/pi_remote.py logs --follow`.

Multiple flags can be combined.

## Steps

1. **Build the helper command.** Use:
   ```bash
   uv run python scripts/pi_remote.py logs ...
   ```
   Add `--lines`, `--errors`, `--filter`, and `--follow` based on the parsed arguments.

2. **Present the log output.** Return the raw log lines directly. Do not summarize or truncate unless the user explicitly asks.

After presenting the logs, remind the user they can ask follow-up questions about the log content, such as "why did the call drop?" or "what errors happened in the last minute?"
