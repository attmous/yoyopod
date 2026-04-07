---
name: restart
description: Kill and relaunch the app on Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the single source of truth for Raspberry Pi connection, runtime, and log settings. `scripts/pi_remote.py` reads this file directly.

If the file does not exist, stop and tell the user to create it.

## Steps

1. **Restart and verify the app.** Run:
   ```bash
   uv run python scripts/pi_remote.py restart
   ```

2. **Handle failures.** If the restart fails, run:
   ```bash
   uv run python scripts/pi_remote.py logs --lines 20
   ```
   Include the relevant error output in your response.

Report whether the restart succeeded.
