---
name: deploy
description: Git-based deploy to Raspberry Pi (push, pull, restart)
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(git status:*)
  - Bash(git branch --show-current:*)
  - Bash(git push:*)
  - Bash(uv run python scripts/pi_remote.py:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, project dir, and branch. `scripts/pi_remote.py` merges them directly, and `uv run python scripts/pi_remote.py config edit` is the preferred way to create or update the local override.

If the file does not exist, stop and tell the user to create it.

## Steps

1. **Check local git status.** Run `git status --short`. If there are uncommitted or unstaged changes, stop and tell the user: "You have uncommitted changes. Use `/sync` for a dirty-tree deploy, or commit first."

2. **Resolve the branch.** Run `git branch --show-current` and deploy that branch.

3. **Push the branch.** Run `git push`. If the branch has no upstream yet, run `git push -u origin <branch>`.

4. **Sync the committed branch onto the Pi.** Run:
   ```bash
   uv run python scripts/pi_remote.py sync --branch <branch>
   ```

5. **Restart and verify the app.** Run:
   ```bash
   uv run python scripts/pi_remote.py restart
   ```

6. **Handle failures.** If either script command fails, run:
   ```bash
   uv run python scripts/pi_remote.py logs --lines 20
   ```
   Include the relevant error output in your response.

Report the deployed branch and whether the final restart succeeded.
