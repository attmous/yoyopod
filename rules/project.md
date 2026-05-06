# Project Overview

YoYoPod is an iPod-inspired Raspberry Pi application combining SIP calling and mpv-based local music playback behind a small-screen, button-driven UI. Target hardware is Raspberry Pi Zero 2W (416 MB RAM).

Three display/input surfaces are supported today: PiSugar Whisplay hardware, Pimoroni/ST7789 hardware, and browser-based simulation. All display rendering runs through the shared LVGL path.

## Common Commands

```bash
# Install dev dependencies
uv run yoyopod setup host
uv run yoyopod setup verify-host

# Build and run the Rust runtime
uv run yoyopod build rust-runtime
device/runtime/build/yoyopod-runtime --config-dir config
yoyopod build simulation

# Local CI mirror
uv run python scripts/quality.py ci

# Repo-owned code quality gate
uv run python scripts/quality.py gate

# Full quality debt audit
uv run python scripts/quality.py audit

# Baseline Pi setup contract
uv run yoyopod setup pi
uv run yoyopod setup verify-pi

# Focused target-side validation
yoyopod pi validate deploy
yoyopod pi validate smoke
yoyopod pi validate voip
yoyopod pi validate navigation
yoyopod pi validate stability
```

`yoyopod setup *` is the baseline executable contract, not the finished setup story.
It does not yet provision external service credentials, validate every native
artifact deeply, or cover every board/modem-specific edge.

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
- Hardware-required validation still needs real Pi coverage beyond CI and simulation
