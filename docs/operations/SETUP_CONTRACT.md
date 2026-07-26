# Setup and System Dependency Contract

This document defines the baseline setup contract for YoYoPod Core. As
of 2026-05-13, automated setup commands (`yoyopod setup …`,
`yoyopod target setup …`) were deleted in Round 0 of the CLI rebuild;
see [`../ROADMAP.md`](../ROADMAP.md). Until the
relevant rounds restore them, follow the manual steps below.

## Why this exists

The repo should let any contributor answer these questions from the
repo itself:

- which system dependencies are required
- which dependencies are core vs feature-gated
- which files are repo-owned vs machine-local
- how to bring up a dev machine
- how to bring up a target Pi

## Setup ownership rules

The repo owns:

- the Rust dependency graph (in each workspace's `Cargo.toml` /
  `Cargo.lock`)
- the shared Pi deploy contract in `deploy/pi-deploy.yaml`
- the tracked app config in `config/`
- the documented system dependency list in this file

Machine-local values stay out of tracked files:

- Pi hostname or SSH alias
- Pi username
- machine-specific overrides in `deploy/pi-deploy.local.yaml`
- secrets and account credentials
- local audio paths or removable-media contents

## Dev machine

Manual prereqs:

- a Rust stable toolchain via `rustup`
- `gh` (GitHub CLI) authenticated, used by `yoyopod target deploy`
- standard Pi-side prereqs (`ssh`, `scp`, `git`)
- `cmake` if you need to build LVGL locally (rare; CI artifacts
  normally cover this)

Build and install the CLI:

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod   # puts `yoyopod` in ~/.cargo/bin/
```

Local workspace check:

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
```

Configure the Pi target:

```bash
yoyopod target config edit
```

## Target Raspberry Pi (manual until CLI setup returns)

Required system packages on the Pi:

- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` running on PiSugar-based targets
- `ppp` for the modem PPP data path (cellular)
- `network-manager` (with its shared-mode `dnsmasq` helper) for Wi-Fi controls
  and the on-device Wi-Fi onboarding AP/captive portal — see
  [`../features/WIFI_ONBOARDING.md`](../features/WIFI_ONBOARDING.md)

Install on Raspberry Pi OS / Debian-based:

```bash
sudo apt-get update
sudo apt-get install -y mpv ffmpeg liblinphone-dev pkg-config cmake \
    alsa-utils i2c-tools
# optional, depending on hardware:
sudo apt-get install -y pisugar-server ppp
```

Bootstrap lane directories and systemd units (one-shot per board):

```bash
ssh <user>@<pi>
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
```

Seed the dev lane checkout:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
```

Activate the dev lane and deploy:

```bash
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>
```

## Repo-owned configuration

Tracked config lives in:

- `config/app/core.yaml`
- `config/audio/music.yaml`
- `config/device/hardware.yaml`
- `config/power/backend.yaml`
- `config/network/cellular.yaml`
- `config/voice/assistant.yaml`
- `config/communication/calling.yaml`
- `config/communication/messaging.yaml`
- `config/communication/calling.secrets.example.yaml`
- `config/communication/integrations/liblinphone_factory.conf`
- `config/people/directory.yaml`
- `config/people/contacts.seed.yaml`
- `deploy/pi-deploy.yaml`

Gitignored local overrides belong in:

- `config/communication/calling.secrets.yaml`
- `deploy/pi-deploy.local.yaml`

The tracked deploy contract must stay generic:

- no personal hostnames
- no personal usernames
- no secrets
- no machine-specific absolute paths unless they are intended defaults

## What will come back

| When | Restores |
|---|---|
| Round 2 | Automated on-Pi validation (`yoyopod target validate …`) |
| Round 3 | Prod slot install + release tooling |
| Round 4+ | `yoyopod target setup` / `verify-setup` style one-shot bootstrap |

See [`../ROADMAP.md`](../ROADMAP.md).

## Verification before blaming product code

Before treating a failure as an app bug, verify the setup layer first:

- local `cargo build` of the CLI succeeds
- `yoyopod target config edit` shows host/user populated
- `yoyopod target mode status` reports the expected lane
- required system packages are installed on the Pi
- the dev lane checkout exists at `/opt/yoyopod-dev/checkout`
- `yoyopod target deploy` returns successfully
- `journalctl -u yoyopod-dev.service -f` shows the runtime alive
- remote config values come from `deploy/pi-deploy.yaml` plus the local
  override, not tribal knowledge

## Current gaps

- provisioning of external voice provider credentials
- board- and modem-specific device-permission setup for every bringup
  variant
- portability beyond the current Debian-based Raspberry Pi package flow
- automated host/Pi setup CLI (deleted in Round 0; returns in later
  rebuild rounds)
