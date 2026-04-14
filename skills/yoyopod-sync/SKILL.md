---
name: yoyopod-sync
description: Rare-case dirty-tree sync escape hatch for Raspberry Pi debugging
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyoctl remote:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, and the stable Pi `project_dir`. `yoyoctl remote` merges them directly, and `yoyoctl remote config edit` is the preferred way to create or update the local override.

If the file does not exist yet, run `yoyoctl remote config edit` first. That command creates `deploy/pi-deploy.local.yaml` automatically before opening it.

## Steps

1. **Confirm this is really a dirty-tree override.** Only use this skill if the user explicitly wants to validate uncommitted local state or asks for a dirty-tree debugging shortcut. Otherwise stop and recommend `/yoyopod-deploy`.

2. **Sync the dirty working tree.** Run:
   ```bash
   yoyoctl remote rsync
   ```

3. **If the user explicitly wants sync without restart,** run:
   ```bash
   yoyoctl remote rsync --skip-restart
   ```

4. **Handle failures.** If the rsync or restart step fails, run:
   ```bash
   yoyoctl remote logs --lines 20
   ```
   Include the relevant error output in your response.

5. **Report the result clearly.** Say that this was a dirty-tree validation override, not the normal committed branch/SHA workflow.
