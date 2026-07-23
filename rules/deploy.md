# Deploy Workflow

Applies to: `deploy/pi-deploy.yaml`, `yoyopod target`, Raspberry Pi
deploy and validation, and Pi-facing agent skills.

## Default Contract

The normal target-hardware workflow deploys committed code only.

Use this order:

1. finish implementation locally
2. run local Rust checks as needed (`cargo check` / `cargo test`)
3. commit the intended changes
4. push the branch (CI must finish the `rust-device-arm64` build for the
   exact commit)
5. deploy the committed branch / commit SHA to the Raspberry Pi via the
   Rust CLI
6. verify the runtime started cleanly and exercise the change manually

The repo-owned command for that flow is:

```bash
git branch --show-current
git rev-parse HEAD
yoyopod target deploy --branch <branch>           # or --sha <commit>
```

`yoyopod target deploy` is the default because it:

- stops on uncommitted local changes
- requires a pushed branch / SHA
- finds the successful `CI` workflow run for the exact commit and
  downloads `yoyopod-rust-device-arm64-<sha>` via `gh run download`
- syncs the dev-lane checkout to the same commit on the Pi
- `scp`s and extracts the worker binaries into `device/*/build/`
- restarts `yoyopod-dev.service` and waits for the startup marker

Add `--wait-for-ci` when CI is still queued or in-progress.

## Validation gap

Automated on-Pi validation (`yoyopod target validate`) is a Round 1 stub
that returns exit 2. Until Round 2 of the CLI rebuild lands, validate
manually after `target deploy`:

```bash
yoyopod target status
yoyopod target logs --follow
journalctl -u yoyopod-dev.service -f
```

Exercise the changed surface on the device. Don't claim a hardware pass
without a real human-eyes check of the running app.

See `docs/ROADMAP.md`.

## Stable Pi Checkout Path

The board reuses one stable checkout path per lane:

- Dev lane: `/opt/yoyopod-dev/checkout` (mutable, used by `target deploy`)
- Prod lane: `/opt/yoyopod-prod/current/...` (immutable slots; release
  tooling is on Round 3 and currently disabled)

Why one stable path:

- dependency installs and native LVGL rebuilds are expensive on Pi Zero
- the systemd unit, log paths, PID file, and CLI shell builders all
  expect this fixed layout
- repeated fresh copies waste time and introduce drift

Do not normalise ad-hoc per-branch directories on the board.

## Command Map

The Rust CLI binary is `yoyopod`. Skills are thin wrappers around it.

| Command | Purpose |
|---|---|
| `/yoyopod-deploy` | Push, fetch CI artifact, sync Pi, install, restart, verify |
| `/yoyopod-logs [N] [--errors] [--filter <sub>]` | Tail app logs from the Pi |
| `/yoyopod-restart` | Restart the dev runtime and verify startup |
| `/yoyopod-status` | Lane / process / log dashboard |
| `/yoyopod-screenshot [--readback]` | Capture display output as PNG |
| `/yoyopod-sync` | Same `target deploy` flow; kept for muscle memory |
| `/yoyopod-rust-artifact` | Manual CI-artifact deploy reference (rarely needed now) |

Direct CLI commands:

- `yoyopod target deploy` — push + CI artifact + Pi sync + restart + verify (the everyday command)
- `yoyopod target mode {status, activate}` — confirm or switch lane (dev/prod)
- `yoyopod target {status, restart, logs, screenshot}` — runtime introspection
- `yoyopod target config edit` — open `deploy/pi-deploy.local.yaml` in `$EDITOR`
- `yoyopod target validate` — stub; returns in Round 2

## Config

`deploy/pi-deploy.yaml` is the tracked baseline. `deploy/pi-deploy.local.yaml`
is the gitignored per-machine override (host, user, custom paths). Edit
with `yoyopod target config edit`.

## No dirty-tree escape hatch

The Python-era `yoyopod remote sync` allowed a dirty-tree rsync escape
hatch. The Rust `target deploy` does **not**. If you need to test
uncommitted local state, commit to a throwaway branch, push, and
deploy that. The CI-artifact contract requires it.

## Target Hardware

- Raspberry Pi Zero 2W (416 MB RAM)
- SSH host, user, and stable project-dir defaults come from
  `deploy/pi-deploy.yaml` plus gitignored `deploy/pi-deploy.local.yaml`
- Machine-local hostnames, usernames, and path overrides must stay out
  of tracked files
- Default dev project dir on Pi: `/opt/yoyopod-dev/checkout`
- Default dev state dir on Pi: `/opt/yoyopod-dev/state`

## On-device Wi-Fi onboarding provisioning

`yoyopod target deploy` (and, for a fresh board, `deploy/scripts/bootstrap_pi.sh`)
install the prerequisites for the Settings → Wi-Fi captive-portal flow:

- a **polkit rule** granting the network-host service user the NetworkManager
  actions it needs (`wifi.scan`, `settings.modify.system`, `network-control`,
  `checkpoint-rollback`, `wifi.share.protected`/`open`)
- **`CAP_NET_BIND_SERVICE`** on the network-host unit so the portal can bind
  port 80
- a **dnsmasq captive-DNS snippet** under
  `/etc/NetworkManager/dnsmasq-shared.d/` (active only while the setup AP is up)

Requires NetworkManager with its shared-mode dnsmasq helper on the Pi. Full
contract: [`../docs/features/WIFI_ONBOARDING.md`](../docs/features/WIFI_ONBOARDING.md).
