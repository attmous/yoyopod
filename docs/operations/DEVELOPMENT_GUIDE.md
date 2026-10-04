# Development Guide

This guide holds the operational detail that does not belong on the
repo landing page.

If you are new here, read these first:

1. [`../README.md`](../../README.md)
2. [`README.md`](../README.md)
3. [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md)
4. [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)
5. [`../ROADMAP.md`](../ROADMAP.md)

## Source of truth

For current behaviour, trust:

- current Rust runtime and worker code in `device/`
- current operator CLI source in `cli/`
- this guide for setup and workflow
- [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md) for
  runtime topology
- [`../ROADMAP.md`](../ROADMAP.md) for what's broken
  during the CLI rebuild
- [`../AGENTS.md`](../../AGENTS.md) and `rules/` for repo guidance

Treat plan docs and checklists as supporting context unless they
explicitly state they are current.

## Toolchain

```bash
# Stable Rust via rustup
rustup default stable
rustup component add rustfmt clippy

# Build the operator CLI:
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod          # optional, into ~/.cargo/bin

# Build the runtime locally (optional; CI artifacts are normally used):
cargo build --manifest-path device/Cargo.toml --release -p yoyopod-runtime
```

`gh` (GitHub CLI) must be authenticated for `yoyopod target deploy`.

## System Dependencies

The full setup contract lives in [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md).

Core Raspberry Pi packages and services:

- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` on PiSugar-based targets
- `ppp` for the cellular modem path

Automated host/Pi setup commands (`yoyopod setup …`) were deleted in
Round 0 of the CLI rebuild; install manually until they return. See
[`../ROADMAP.md`](../ROADMAP.md).

## Configuration

Tracked config files live under `config/`:

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

Key settings:

- `config/app/core.yaml`
  - `app.*`, `ui.*`, `logging.*`, `diagnostics.*`
- `config/audio/music.yaml`
  - `audio.music_dir`, `audio.recent_tracks_file`, `audio.mpv_*`,
    `audio.default_volume`
- `config/device/hardware.yaml`
  - `input.*`, `display.*`, `communication_audio.*`, `media_audio.*`,
    `voice_audio.*`
- `config/power/backend.yaml`
  - `power.*` PiSugar backend transport, watchdog, polling, warning,
    and shutdown policy
- `config/network/cellular.yaml`
  - `network.*` cellular modem enablement, ports, APN, GPS, and PPP
    timeout
- `config/voice/assistant.yaml`
  - `assistant.*` voice commands, cloud-worker STT/TTS, prompt policy,
    and command routing
- `config/communication/calling.yaml`
  - SIP identity, transport, STUN, call policy, call-history path
- `config/communication/messaging.yaml`
  - file transfer, message-store paths, voice-note policy
- `config/people/directory.yaml`
  - paths for mutable people data under `data/people/`

Local SIP credentials belong in
`config/communication/calling.secrets.yaml` or env vars. Mutable
contacts live in `data/people/contacts.yaml`, optionally bootstrapped
from `config/people/contacts.seed.yaml`. Mutable media history lives in
`data/media/recent_tracks.json`.

Current approved-contacts behaviour:

- contacts may include both `sip_address` and `phone_number`
- Talk → contact → Call opens a SIP/GSM method wheel. SIP uses the approved
  `sip_address`; GSM uses the approved `phone_number`. Voice notes still use SIP.
- unavailable methods remain visible with a short reason (such as “SIM locked”)
- GSM requires ModemManager voice support on the SIM7600, an unlocked SIM,
  cellular voice registration, and the modem's USB PCM audio interface.
  The network worker controls calls over D-Bus and bridges USB PCM to the named
  ALSA `capture`/`playback` routes. Before dialing it stops PPP and releases the AT command port;
  data recovery, modem resets, and GNSS queries stay paused until voice ends.
  Wi-Fi continues running, and cellular data resumes after hang-up or dial failure.
  Deployment grants only voice and device-control
  ModemManager actions to the runtime service user.
  ModemManager's secondary PIN2/PUK2 restrictions do not block ordinary voice;
  primary SIM/carrier locks, missing registration, and emergency-only service do.
  Brief USB audio write stalls are retried with the remaining PCM bytes for up to
  two seconds without progress. Microphone/speaker subprocess exits and bridge
  failures retain their diagnostic cause in the network service journal.
- backend config sync replaces the device's approved contact directory live and
  persists it atomically. An open contact view follows address/name edits by
  stable contact ID and closes when that contact is removed.
- a claimed device may upload prestored local contacts once when
  backend authority is still empty for that household

Call-control contract: [ModemManager Voice](https://raw.githubusercontent.com/linux-mobile-broadband/ModemManager/main/introspection/org.freedesktop.ModemManager1.Modem.Voice.xml)
and [Call](https://raw.githubusercontent.com/linux-mobile-broadband/ModemManager/main/introspection/org.freedesktop.ModemManager1.Call.xml).
PCM contract: [SIMCom USB Audio Application Note](https://simcom.ee/documents/SIM7X00/SIM7100_SIM7500_SIM7600%20Series_USB%20AUDIO_Application%20Note_V1.03.pdf).

## Running

Rust runtime dry run:

```bash
cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run
```

Rust runtime (after a local build):

```bash
device/target/release/yoyopod-runtime --config-dir config
```

Installed console entrypoint:

```bash
yoyopod                # Rust operator CLI; does NOT launch the runtime
```

The installed `yoyopod` command is the operator CLI for dev-machine to
Pi orchestration. It does not launch the app runtime — that runs on the
Pi via `yoyopod-dev.service` (dev lane) or `yoyopod-prod.service`
(prod lane).

## Validation

Local validation:

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
cargo clippy --manifest-path cli/Cargo.toml --all-targets
```

See [`QUALITY_GATES.md`](QUALITY_GATES.md).

Profiling tooling (`yoyopod dev profile …`) was retired with the rest
of the Python CLI in Round 0. For ad-hoc profiling, use the standard
Rust tools (`cargo flamegraph`, `samply`, `perf` on the Pi) directly
against `yoyopod-runtime` and worker binaries.

Automated on-Pi validation (`yoyopod target validate …` /
`yoyopod pi validate …`) is on the CLI rebuild roadmap and is not yet
available. Until then, validate manually after `yoyopod target deploy`
via `systemd` and `journalctl`.

## Raspberry Pi Workflow

```bash
yoyopod target config edit                       # one-time per machine
yoyopod target mode status
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>          # or --sha <commit>
yoyopod target status
yoyopod target logs --lines 200
yoyopod target logs --follow --filter ERROR
```

`yoyopod target deploy` pushes, finds the CI artifact for the exact
commit, syncs the Pi, installs the worker binaries, restarts the
service, and verifies startup in one step.

If a GitHub fetch or push fails with a short-lived connectivity error,
retry it several times before treating it as a real failure. This
environment has seen brief `github.com` reachability blips.

The detailed deploy and validation flows live in:

- [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md)
- [`archive/RPI_SMOKE_VALIDATION.md`](archive/RPI_SMOKE_VALIDATION.md)
- `../../rules/deploy.md`

## Logging

The app writes:

- `logs/yoyopod.log`
- `logs/yoyopod_errors.log`

Pi deploy defaults live in:

- `deploy/pi-deploy.yaml`
- `deploy/pi-deploy.local.yaml` (gitignored, machine-local)

Useful remote log commands:

```bash
yoyopod target logs --lines 200
yoyopod target logs --errors
yoyopod target logs --filter comm
yoyopod target logs --follow --filter ERROR
```

## Package Layout

```text
device/
  runtime/
  protocol/
  worker/
  harness/
  cloud/
  media/
  network/
  power/
  speech/
  ui/
  voip/
cli/
  yoyopod/
    src/
      commands/
        target/
deploy/
  pi-deploy.yaml
  scripts/
  systemd/
```

## Current Active Docs

Start with [`README.md`](../README.md) for the full docs map.

Current contributor, runtime, and setup docs:

- `docs/operations/CONTRIBUTOR_WORKFLOW.md`
- `docs/operations/QUALITY_GATES.md`
- `docs/operations/SETUP_CONTRACT.md`
- `docs/ROADMAP.md`
- `docs/operations/PI_DEV_WORKFLOW.md`
- `docs/operations/archive/RPI_SMOKE_VALIDATION.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/hardware/POWER_MODULE.md`
- `docs/features/LOCAL_FIRST_MUSIC_PLAN.md`
- `docs/features/MPV_DEPENDENCIES.md`

Old plan and migration archives were removed from the tracked repo.
Current code and current operation docs are the source of truth.
