---
name: restart
description: Kill and relaunch the app on Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, project dir, and branch. `scripts/pi_remote.py` merges them directly, and `uv run python scripts/pi_remote.py config edit` is the preferred way to create or update the local override.

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
