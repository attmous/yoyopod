---
title: Build & Flash a Device
description: From checkout to a running device.
---

*The path from source checkout to a device running your build.*

## Overview

There is no local flash step. The as-built contract is five steps:
finish the change locally → commit → push (CI must build the
`rust-device-arm64` artifact for that exact commit) → deploy that commit
to the Pi → verify with your own eyes. An uncommitted tree has no CI
artifact and cannot deploy — a feature, not a gap: the binaries on the
board always correspond to a commit. Prerequisite: a working host setup
from [Dev Environment](/builders/dev/environment/).

## Build

The deployable arm64 build comes from CI, not from your machine —
`yoyopod target deploy` fetches the artifact via `gh` and installs it.
Local `cmake` is needed only when building LVGL locally, which is rare;
CI artifacts normally cover it, and native LVGL rebuilds are expensive
enough that the board keeps exactly one stable checkout
(`/opt/yoyopod-dev/checkout` — ad-hoc per-branch checkouts on the board
are unsupported). After native LVGL/CMake input changes, redeploy with
`--clean-native` to wipe the board's build dir.

## Deploy to hardware

### One-time setup, per dev machine

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod
yoyopod target config edit        # host/user → pi-deploy.local.yaml (never tracked)
gh auth status                    # must pass
```

Tracked defaults live in `deploy/pi-deploy.yaml`; machine-specific
host/user stay in the gitignored `pi-deploy.local.yaml` (env fallbacks:
`YOYOPOD_PI_HOST`, `YOYOPOD_PI_USER`, `YOYOPOD_PI_PROJECT_DIR`).

### Fresh board bootstrap

Install the Pi packages (`mpv`, `ffmpeg`, `liblinphone-dev`,
`pkg-config`, `cmake`, `alsa-utils`, `i2c-tools`, plus the
hardware-dependent `pisugar-server` and `ppp`), then run the installer
**on the Pi** and seed the dev lane:

```bash
curl -fsSL https://raw.githubusercontent.com/attmous/yoyopod/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
yoyopod target mode activate dev
```

### The daily loop

```bash
yoyopod target mode status        # always check the lane first
git add -p && git commit -m '…' && git push
yoyopod target deploy --branch <branch>   # or --sha; --wait-for-ci if CI is running
yoyopod target status             # deployed SHA, processes, log tail
yoyopod target logs --follow
```

Every board hosts two mutually exclusive lanes: **dev** (mutable git
checkout, `yoyopod-dev.service`) and **prod** (immutable versioned
slots, `yoyopod-prod.service`, with `previous` as the rollback target —
never delete it). Lane-switch commands stop the other lane first.
`target screenshot` captures the canvas; `target restart` restarts with
startup verification. Until Round 2 restores `target validate`,
validate manually: `target logs --follow` plus
`ssh <user>@<host> 'journalctl -u yoyopod-dev.service -f'`. Common
failures: `gh` not authenticated, CI still running (`--wait-for-ci`),
CI failed (fix the commit — never deploy a broken build), prod lane
active, or wrong checkout ownership.

## Today vs. target

Honest caveats, carried from the setup contract: automated setup
(`yoyopod setup …`) was deleted in Round 0 of the CLI rebuild and
returns in Round 4+ — until then bringup is manual, and the contract
above is what "correctly set up" means. Round 2 restores automated
on-Pi validation; Round 3 restores prod slot publishing and release
tooling (never mutate a prod release dir in place — blocked until then
anyway). The future OTA poller is guarded so it skips OTA whenever the
dev lane is active. Deployment today targets the Pi-based prototype
only; the deploy story for a future product board changes with that
hardware (see [Hardware Roadmap](/builders/hardware/roadmap/)).

## Open questions

- TODO: How much of the Pi-prototype deploy path survives the prototype-to-product transition?
- TODO: Known contract gaps — voice-provider credential provisioning and board/modem-specific device permissions — where do they get owned?
- TODO: Does the bringup flow ever become portable beyond the Debian-based Pi path?

:::note[Sources]
Condensed from
[`docs/operations/PI_DEV_WORKFLOW.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/PI_DEV_WORKFLOW.md),
[`docs/operations/DEV_PROD_LANES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/DEV_PROD_LANES.md),
and
[`docs/operations/SETUP_CONTRACT.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/SETUP_CONTRACT.md)
and the as-built docs site (`website/` in the repository): the Pi Dev
Workflow, Dev/Prod Lanes, and Setup Contract pages.
:::
