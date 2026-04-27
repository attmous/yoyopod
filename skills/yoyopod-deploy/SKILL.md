---
name: yoyopod-deploy
description: Commit-safe dev-lane branch/SHA validation or prod slot install on Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(git status:*)
  - Bash(git branch --show-current:*)
  - Bash(git rev-parse:*)
  - Bash(git push:*)
  - Bash(yoyopod remote:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and `deploy/pi-deploy.local.yaml` for machine-specific overrides such as host, SSH user, and the dev lane checkout. The tracked dev default is `project_dir: /opt/yoyopod-dev/checkout`; prod slots live under `/opt/yoyopod-prod`. `yoyopod remote` merges the files directly, and `yoyopod remote config edit` is the preferred way to create or update the local override.

If the file does not exist yet, run `yoyopod remote config edit` first. That command creates `deploy/pi-deploy.local.yaml` automatically before opening it.

## Steps

1. **Check local git status.** Run `git status --short`. If there are uncommitted or unstaged changes, stop and tell the user: "You have uncommitted changes. Commit and push first. `/yoyopod-sync` is a rare dirty-tree debugging override only."

2. **Resolve the branch and exact commit.** Run:
   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```
   If the branch is empty, stop and ask the user which branch should be validated.

3. **Push the branch.** Run `git push`. If the branch has no upstream yet, run `git push -u origin <branch>`.

4. **Switch the board into the dev lane.** Run:
   ```bash
   yoyopod remote mode status
   yoyopod remote mode activate dev
   ```
   If `mode status` reports `active_lane=conflict`, include the conflict lines in the response and let `mode activate dev` clean the lane before validation.

5. **Validate the committed branch and exact SHA on the Pi.** Run:
   ```bash
   yoyopod remote validate --branch <branch> --sha <commit>
   ```
   Add smoke flags such as `--with-music`, `--with-voip`, `--with-power`, `--with-rtc`, or `--with-lvgl-soak` when the task calls for them.

6. **Handle failures.** If validation fails, run:
   ```bash
   yoyopod remote logs --lines 20
   ```
   Include the relevant error output in your response.

7. **Report the result.** Include the validated branch, exact SHA, lane state, whether validation passed, and that the dev app was left running for manual testing when the flow succeeded.

## Prod Slot Flow

For packaged releases, prefer a CI-published artifact URL:

```bash
yoyopod remote release install-url <artifact-url>
yoyopod remote mode activate prod
yoyopod remote release status
```

Add `--first-deploy` to `install-url` when the Pi has no previous prod slot yet.

For a local artifact, use:

```bash
yoyopod remote release push ./build/releases/<version>.tar.gz
yoyopod remote mode activate prod
yoyopod remote release status
```

Add `--first-deploy` to `release push` when the Pi has no previous prod slot yet.

Prod release commands target `/opt/yoyopod-prod` and do not require `uv` or a repo checkout on the Pi after curl bootstrap. See `docs/operations/SLOT_DEPLOY.md`.
