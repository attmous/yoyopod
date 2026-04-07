---
name: sync
description: Quick rsync deploy to Raspberry Pi (no commit needed)
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the single source of truth for Raspberry Pi connection, runtime, screenshot, and rsync settings. `scripts/pi_remote.py` reads this file directly.

If the file does not exist, stop and tell the user to create it.

## Steps

1. **Sync the dirty working tree and restart.** Run:
   ```bash
   uv run python scripts/pi_remote.py rsync
   ```

2. **If the user explicitly wants sync without restart,** run:
   ```bash
   uv run python scripts/pi_remote.py rsync --skip-restart
   ```

3. **Handle failures.** If the rsync or restart step fails, run:
   ```bash
   uv run python scripts/pi_remote.py logs --lines 20
   ```
   Include the relevant error output in your response.

Report whether the dirty-tree sync and restart succeeded.
