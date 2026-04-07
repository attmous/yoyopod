---
name: pi-status
description: Health check for Raspberry Pi - connectivity, processes, memory, recent logs
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the single source of truth for Raspberry Pi connection, process, and log settings. `scripts/pi_remote.py` reads this file directly.

If the file does not exist, stop and tell the user to create it.

## Steps

1. **Run the helper command.**
   ```bash
   uv run python scripts/pi_remote.py status
   ```

2. **Present the result.** Prefer a compact summary with:
   - git branch and commit
   - Mopidy status
   - YoyoPod service status
   - PiSugar server status
   - PID file state
   - latest startup marker
   - top memory processes

3. **If the app is not running,** explicitly suggest:
   ```text
   Run /restart to start the app.
   ```
