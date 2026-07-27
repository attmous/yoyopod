# Project Overview

yoyopod is an iPod-inspired Raspberry Pi application combining SIP
calling and mpv-based local music playback behind a small-screen,
button-driven UI.

The target hardware is the Raspberry Pi Zero 2W (416 MB RAM) with the
PiSugar Whisplay HAT for display + microphone + speaker + side button,
and a PiSugar 3 power module. Display rendering runs through the
shared LVGL path.

## Common Commands

```bash
# Build the Rust operator CLI (single binary `yoyopod`):
cargo build --manifest-path cli/Cargo.toml --release
# Optional: install into ~/.cargo/bin/
cargo install --path cli/yoyopod

# Build and run the Rust runtime locally:
cargo build --manifest-path device/Cargo.toml --release -p yoyopod-runtime
device/target/release/yoyopod-runtime --config-dir config

# Rust workspace checks:
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml

# Daily Pi loop:
yoyopod target mode status
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>           # or --sha <commit>
yoyopod target logs --follow
```

Host setup, Pi bootstrap, code quality gates, and per-stage on-Pi
validation (`pi validate deploy/smoke/voip/navigation/stability`) are
all part of the CLI rebuild roadmap; see
`docs/ROADMAP.md`. Until they return, set up host
dependencies manually and validate Rust changes after `target deploy`
via `journalctl -u yoyopod-dev.service -f`.

## Configuration

Tracked authored config lives under `config/`:
- `app/core.yaml` -- app shell, UI, logging, diagnostics
- `audio/music.yaml` -- local music policy, startup volume, and media runtime paths
- `device/hardware.yaml` -- shared hardware truth for display, input, power, communication audio, media audio, and voice audio
- `power/backend.yaml` -- power backend transport, polling, watchdog, and shutdown policy
- `network/cellular.yaml` -- cellular modem policy and transport settings
- `voice/assistant.yaml` -- local voice policy and assistant defaults
- `communication/calling.yaml` -- non-secret SIP identity and calling policy
- `communication/messaging.yaml` -- messaging policy and communication runtime storage paths
- `communication/calling.secrets.example.yaml` -- tracked example for the gitignored secrets file
- `communication/integrations/liblinphone_factory.conf` -- repo-owned Liblinphone integration defaults
- `people/directory.yaml` -- mutable people-data paths only
- `people/contacts.seed.yaml` -- tracked bootstrap seed for the mutable address book

Runtime user data lives under `data/communication/`, `data/media/`, and
`data/people/`. Local SIP secrets belong in
`config/communication/calling.secrets.yaml` or env vars.

## Current Gaps

- Settings UI is still not implemented
- Hardware-required validation still needs real Pi coverage beyond the
  CI Rust ARM64 build artifact
