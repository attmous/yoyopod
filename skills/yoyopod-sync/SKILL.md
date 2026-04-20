---
name: yoyopod-sync
description: Rare-case dirty-tree sync escape hatch for Raspberry Pi debugging
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyopod remote:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, and the stable Pi `project_dir`. `yoyopod remote` merges them directly, and `yoyopod remote config edit` is the preferred way to create or update the local override.

If the file does not exist yet, run `yoyopod remote config edit` first. That command creates `deploy/pi-deploy.local.yaml` automatically before opening it.

## Steps

1. **Confirm this is really a dirty-tree override.** Only use this skill if the user explicitly wants to validate uncommitted local state or asks for a dirty-tree debugging shortcut. Otherwise stop and recommend `/yoyopod-deploy`.

2. **Sync the dirty working tree.** Run:
   ```bash
   yoyopod remote sync
   ```

3. **If the user explicitly wants sync without restart,** run:
   ```bash
   yoyopod remote sync --skip-restart
   ```

4. **Handle failures.** If the sync or restart step fails, run:
   ```bash
   yoyopod remote logs --lines 20
   ```
   Include the relevant error output in your response.

5. **Report the result clearly.** Say that this was a dirty-tree validation override, not the normal committed branch/SHA workflow.
