# YoYoPod

<p align="center">
  <img src="docs/assets/readme/yoyopod-device-tour.gif" alt="YoYoPod running on the current prototype hardware" width="320">
</p>

<p align="center">
  <strong>YoYoPod is a tiny Pi-powered music player and phone for kids aged 7-13.</strong>
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
- `Calls and voice messages` - family-friendly calling, quick voice notes, and a contact-first Talk experience.
- `Location and connectivity` - 4G modem support, GPS/location awareness, and device-level network handling.
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

- `yoyopod/core/` - app lifecycle, scheduler, event bus, runtime loop, diagnostics, and shared state.
- `yoyopod/integrations/` - higher-level product capabilities like calling, music, power, network, location, and cloud sync.
- `yoyopod/backends/` - concrete hardware and service adapters such as Liblinphone, mpv, modem, and power backends.
- `yoyopod/ui/` - the device UI, LVGL binding, screens, and input/display glue.
- `yoyopod_cli/` - developer and device operations tooling for setup, deploy, validation, and diagnostics.

If you want the architecture view instead of the product view, start with [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md).

## Bring Up The Prototype

This repo is Raspberry Pi hardware-first. To work on the real device path, plan around:

- Raspberry Pi Zero 2W
- current Whisplay-based prototype hardware
- the modem path if you want to validate 4G/GPS behavior

### Local Developer Setup

```bash
uv sync --extra dev
uv run yoyopod setup host
uv run yoyopod setup verify-host --with-remote-tools
uv run python yoyopod.py --simulate
```

Use `python yoyopod.py` without `--simulate` only when you intentionally want to launch against directly attached local hardware.

### Fresh Raspberry Pi Install

On the Pi, install the supported dev/prod lane structure with the curl installer:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
```

For a first prod slot install from a published artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --release-url=<artifact-url>
```

### Hardware Validation

For PR hardware testing, use the mutable dev lane from your dev machine:

```bash
uv run yoyopod remote mode activate dev
uv run yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
```

For packaged prod slot validation, use the immutable prod lane:

```bash
uv run yoyopod remote mode activate prod
uv run yoyopod remote release status
```

For deeper deploy, lane, and troubleshooting flows, read [Dev/Prod Lanes](docs/operations/DEV_PROD_LANES.md), [Slot Deploy](docs/operations/SLOT_DEPLOY.md), and [Pi Dev Workflow](docs/operations/PI_DEV_WORKFLOW.md).

## Read More

- [Documentation Guide](docs/README.md)
- [Contributor Workflow](docs/operations/CONTRIBUTOR_WORKFLOW.md)
- [Development Guide](docs/operations/DEVELOPMENT_GUIDE.md)
- [Release Process](docs/operations/RELEASE_PROCESS.md)
- [Slot Deploy](docs/operations/SLOT_DEPLOY.md)
- [Pi Dev Workflow](docs/operations/PI_DEV_WORKFLOW.md)
- [Pi Smoke Validation](docs/operations/RPI_SMOKE_VALIDATION.md)
- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Power Module](docs/hardware/POWER_MODULE.md)
- [Design Docs](docs/design/README.md)
- [Feature Docs](docs/features/README.md)

Historical notes are kept under [docs/archive](docs/archive). Current code and current runtime docs are the source of truth when older plans drift.

## License

YoYoPod is licensed under the **GNU Affero General Public License v3.0 or later** (AGPLv3+). See [LICENSE](LICENSE) for the full text.

The project's own source could be permissively licensed in isolation, but YoYoPod's VoIP backend links [liblinphone](https://gitlab.linphone.org/BC/public/liblinphone), which is itself AGPLv3 (with a paid commercial-license alternative from Belledonne Communications). Distributed binaries that include the liblinphone link therefore fall under AGPLv3 as a combined work.

In practical terms:

- The full source is published in this repository.
- Anyone receiving a YoYoPod device or firmware artifact is entitled to the corresponding source under the same license.
- Modifications and derivative works must remain AGPLv3 and must publish their source.

Section 13 of the AGPL ("network use") triggers source-disclosure for software that interacts with users remotely over a network. YoYoPod's typical use (a local user holding the device) does not trigger that clause; a hypothetical future cloud companion that exposes liblinphone functionality remotely would.
