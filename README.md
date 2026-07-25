# YoYoPod

<p align="center">
  <img src="docs/assets/readme/yoyopod-device-tour.gif" alt="YoYoPod running on the current prototype hardware" width="320">
</p>

<p align="center">
  <strong>YoYoPod is a tiny Pi-powered music player and phone for kids aged 7-14.</strong>
</p>

<p align="center">
  Built for favorite songs, voice messages, family calls, and a small screen that stays calm.
</p>

<p align="center">
  <img alt="Raspberry Pi Zero 2W" src="https://img.shields.io/badge/Raspberry%20Pi-Zero%202W-C51A4A?logo=raspberrypi&logoColor=white">
  <img alt="LVGL UI" src="https://img.shields.io/badge/LVGL-UI%20stack-343A40">
  <img alt="Liblinphone" src="https://img.shields.io/badge/Liblinphone-calls%20%26%20voice%20messages-1B6EF3">
  <img alt="mpv" src="https://img.shields.io/badge/mpv-music%20playback-5C4B8A">
  <img alt="Whisplay" src="https://img.shields.io/badge/Whisplay-current%20prototype%20HAT-E67E22">
  <img alt="PiSugar" src="https://img.shields.io/badge/PiSugar-power%20integration-159957">
</p>

YoYoPod is being built by software-engineer fathers in Stuttgart, Germany. The idea is simple: give kids a dedicated little device for music, voice messages, and staying in touch, without throwing them into the chaos of a general-purpose phone.

The current prototype runs on a Raspberry Pi Zero 2W and uses the Whisplay HAT because it gives us a great bundle for fast iteration: screen, side push-to-talk button, microphone, and speaker. That is our prototype path, not a permanent promise about the final hardware. The long-term device may ship with its own display and driver.

## What YoYoPod Can Do

- `Music playback` - local-first music, playlists, recent tracks, shuffle, and a simple now-playing flow.
- `Calls and voice messages` - family-friendly calling, quick voice notes, and a contact-first Talk experience. Implemented in the runtime via liblinphone; bring-up on the current prototype image is in progress.
- `Location and connectivity` - 4G modem support, GPS/location awareness, and device-level network handling. Location reporting to the parent dashboard is still being wired end to end.
- `Device care` - battery/power integration, watchdogs, runtime diagnostics, and Pi validation tooling.
- `A physical interaction model` - small-screen navigation plus a side push-to-talk button instead of a UI built around tapping glass all day.

## Inside The Current Prototype

| Hub | Listen |
| --- | --- |
| ![YoYoPod hub screen](docs/assets/readme/hub.png) | ![YoYoPod listen screen](docs/assets/readme/listen.png) |

| Talk | Setup |
| --- | --- |
| ![YoYoPod talk screen](docs/assets/readme/talk.png) | ![YoYoPod setup screen](docs/assets/readme/setup.png) |

## The Software Stack

This repository contains the software that runs the current YoYoPod prototype:

- `device/runtime/` - Rust runtime for config, worker supervision, app state, event routing, and UI snapshots.
- `device/{ui,media,voip,network,cloud,power,speech}/` - Rust domain sidecar hosts for UI, media, VoIP, network, cloud, power, and speech/Ask.
- `cli/` - Rust operator CLI for dev-machine to Pi orchestration. Under
  active rebuild (the Python CLI was retired 2026-05-13); see
  [docs/ROADMAP.md](docs/ROADMAP.md).
- `apps/` - future web and mobile applications.
- `packages/` - future shared contracts, SDKs, and app packages.

New runtime work should start in `device/`. New operator tooling work
goes in `cli/`. If you want the architecture view instead of the product
view, start with
[docs/architecture/WORK_AREAS.md](docs/architecture/WORK_AREAS.md) and
[docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md).

## Bring Up The Prototype

This repo is Raspberry Pi hardware-first. To work on the real device path, plan around:

- Raspberry Pi Zero 2W
- current Whisplay-based prototype hardware
- the modem path if you want to validate 4G/GPS behavior

### Local Developer Setup

```bash
# Build the Rust operator CLI (single binary `yoyopod`):
cargo build --manifest-path cli/Cargo.toml --release
# Optional: install to ~/.cargo/bin/yoyopod
cargo install --path cli/yoyopod

# Build the Rust runtime locally (or use CI artifacts; see Hardware Validation):
cargo build --manifest-path device/Cargo.toml --release -p yoyopod-runtime
```

Setup tooling (`yoyopod setup host`, `yoyopod setup verify-host`) is on
the rebuild roadmap. See
[docs/ROADMAP.md](docs/ROADMAP.md).

### Fresh Raspberry Pi Install

On the Pi, install the supported dev/prod lane structure with the curl installer:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
```

For a first prod slot install from a published artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --release-url=<artifact-url>
```

Note: new prod slot artifacts are blocked until Round 3 of the CLI
rebuild reintroduces the slot builder. Reinstalling a previously-shipped
artifact still works.

### Hardware Validation

For PR hardware testing, use the Rust CLI's deploy command from your dev machine:

```bash
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>     # also accepts --sha <commit>
```

`target deploy` pushes the current branch, finds the matching CI
artifact, syncs the Pi, installs binaries, restarts the service, and
verifies startup in one step.

Automated on-Pi validation (`yoyopod target validate`) returns in Round 2
of the CLI rebuild. For now, validate manually after deploy via
`journalctl -u yoyopod-dev.service -f` and hardware inspection.

For deeper deploy, lane, and troubleshooting flows, read [CLI Rebuild
Rounds](docs/ROADMAP.md), [Dev/Prod
Lanes](docs/operations/DEV_PROD_LANES.md), [Slot
Deploy](docs/operations/archive/SLOT_DEPLOY.md), and [Pi Dev
Workflow](docs/operations/PI_DEV_WORKFLOW.md).

## Read More

- [Documentation Guide](docs/README.md)
- [Contributor Workflow](docs/operations/CONTRIBUTOR_WORKFLOW.md)
- [Development Guide](docs/operations/DEVELOPMENT_GUIDE.md)
- [Release Process](docs/operations/archive/RELEASE_PROCESS.md)
- [Slot Deploy](docs/operations/archive/SLOT_DEPLOY.md)
- [Pi Dev Workflow](docs/operations/PI_DEV_WORKFLOW.md)
- [Pi Smoke Validation](docs/operations/archive/RPI_SMOKE_VALIDATION.md)
- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Power Module](docs/hardware/POWER_MODULE.md)
- [Design Docs](docs/design/README.md)
- [Feature Docs](docs/features/README.md)

When docs disagree, trust current code and the most recently merged PRs. The [`docs/ROADMAP.md`](docs/ROADMAP.md) tracks the current rebuild rounds; paused capability docs live under [`docs/operations/archive/`](docs/operations/archive/README.md).

## License

YoYoPod is licensed under the **GNU Affero General Public License v3.0 or later** (AGPLv3+). See [LICENSE](LICENSE) for the full text.

The project's own source could be permissively licensed in isolation, but YoYoPod's VoIP backend links [liblinphone](https://gitlab.linphone.org/BC/public/liblinphone), which is itself AGPLv3 (with a paid commercial-license alternative from Belledonne Communications). Distributed binaries that include the liblinphone link therefore fall under AGPLv3 as a combined work.

In practical terms:

- The full source is published in this repository.
- Anyone receiving a YoYoPod device or firmware artifact is entitled to the corresponding source under the same license.
- Modifications and derivative works must remain AGPLv3 and must publish their source.

Section 13 of the AGPL ("network use") triggers source-disclosure for software that interacts with users remotely over a network. YoYoPod's typical use (a local user holding the device) does not trigger that clause; a hypothetical future cloud companion that exposes liblinphone functionality remotely would.
