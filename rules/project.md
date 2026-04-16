# Project Overview

YoyoPod is an iPod-inspired Raspberry Pi application combining SIP calling and mpv-based local music playback behind a small-screen, button-driven UI. Target hardware is Raspberry Pi Zero 2W (416 MB RAM).

Three display/input modes are supported today: Pimoroni Display HAT Mini, PiSugar Whisplay, and browser-based simulation.

## Common Commands

```bash
# Install dev dependencies
uv run yoyoctl setup host
uv run yoyoctl setup verify-host

# Run the app
python yoyopod.py
python yoyopod.py --simulate

# Local CI mirror
uv run python scripts/quality.py ci

# Tests
uv run pytest -q
uv run pytest -q tests/test_fsm_runtime.py

# Repo-owned code quality gate
uv run python scripts/quality.py gate

# Full quality debt audit
uv run python scripts/quality.py audit

# Baseline Pi setup contract
uv run yoyoctl setup pi
uv run yoyoctl setup verify-pi

# Focused target-side validation
yoyoctl pi validate deploy
yoyoctl pi validate smoke
yoyoctl pi validate music
yoyoctl pi validate voip
yoyoctl pi validate navigation
yoyoctl pi validate stability
```

`yoyoctl setup *` is the baseline executable contract, not the finished setup story.
It does not yet provision non-apt assets like Vosk models, validate every native
artifact deeply, or cover every board/modem-specific edge.

## Configuration

Tracked authored config lives under `config/`:
- `app/core.yaml` -- app shell, UI, logging, diagnostics
- `audio/music.yaml` -- local music policy, startup volume, and media runtime paths
- `device/hardware.yaml` -- shared hardware truth for display, input, power, communication audio, media audio, and voice audio
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
