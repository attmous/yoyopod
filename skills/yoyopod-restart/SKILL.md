---
name: yoyopod-restart
description: Restart the active yoyopod dev lane service on Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyopod target:*)
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and
`deploy/pi-deploy.local.yaml` for machine-specific overrides such as
host, SSH user, dev lane checkout, and branch. `yoyopod target restart`
is a dev-lane helper and expects the selected checkout to match
`/opt/yoyopod-dev/checkout`. Prod slot management (`target release …`)
returns in Round 3 of the CLI rebuild; see
`docs/ROADMAP.md`.

If the file does not exist yet, run `yoyopod target config edit` first.
That command creates `deploy/pi-deploy.local.yaml` automatically before
opening it.

## Steps

1. **Check lane state first.**
   ```bash
   yoyopod target mode status
   ```

2. **Restart and verify the dev lane service.** Run:
   ```bash
   yoyopod target restart
   ```

3. **Handle failures.** If the restart fails because prod is active, use
   `yoyopod target mode activate dev` before retrying. For other
   failures, run:
   ```bash
   yoyopod target logs --lines 20
   ```
   Include the relevant error output in your response.

Report whether the dev lane restart succeeded and whether
`yoyopod-runtime` came up. For prod slot operations, fall back to
direct SSH and `systemctl` until Round 3 restores the CLI commands.
