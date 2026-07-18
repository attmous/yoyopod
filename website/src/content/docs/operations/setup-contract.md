---
title: Setup Contract
description: The baseline contract — required dependencies, repo-owned vs machine-local ownership, and manual bringup for dev machine and Pi.
---

Automated setup (`yoyopod setup …`) was deleted in Round 0 of the CLI
rebuild and returns in Round 4+ — until then, bringup is manual, and
this contract is what "correctly set up" means.

## Ownership rules

| The repo owns | The machine owns (never tracked) |
| --- | --- |
| the Rust dependency graph (`Cargo.toml`/`.lock`) | Pi hostname / SSH alias, username |
| `deploy/pi-deploy.yaml` (generic defaults only) | `pi-deploy.local.yaml` overrides |
| tracked config under `config/` | secrets and credentials |
| this dependency list | local audio paths / removable media |

## Dev machine

Rust stable via `rustup` · `gh` authenticated (artifact fetching) ·
`ssh`/`scp`/`git` for the Pi side · `cmake` only if building LVGL
locally (rare — CI artifacts normally cover it).

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod
cargo check --manifest-path device/Cargo.toml --workspace --locked
yoyopod target config edit
```

## Target Pi

```bash
sudo apt-get update
sudo apt-get install -y mpv ffmpeg liblinphone-dev pkg-config cmake \
    alsa-utils i2c-tools
sudo apt-get install -y pisugar-server ppp   # hardware-dependent

# one-shot bootstrap (lane dirs + systemd units), run ON the Pi:
curl -fsSL https://raw.githubusercontent.com/attmous/yoyopod/main/deploy/scripts/install_pi.sh | sudo -E bash -s --

# seed the dev lane:
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout

# then, from the dev machine:
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>
```

## What comes back when

| When | Restores |
| --- | --- |
| Round 2 | automated on-Pi validation (`yoyopod target validate …`) |
| Round 3 | prod slot install + release tooling |
| Round 4+ | `yoyopod target setup` / `verify-setup` one-shot bootstrap |

## Verify setup before blaming product code

The checklist, in order: local CLI build succeeds → `target config edit`
shows host/user → `target mode status` reports the expected lane →
required Pi packages installed → `/opt/yoyopod-dev/checkout` exists →
`target deploy` succeeds → `journalctl -u yoyopod-dev.service -f` shows
the runtime alive → remote config comes from `pi-deploy.yaml` + local
override, not tribal knowledge. Most "product bugs" during bringup fail
one of these first.

Known gaps in the contract itself: voice-provider credential
provisioning, board/modem-specific device permissions, and portability
beyond the Debian-based Pi flow.

:::note[Canonical source]
Condensed from
[`docs/operations/SETUP_CONTRACT.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/SETUP_CONTRACT.md)
(dated 2026-05-13).
:::
