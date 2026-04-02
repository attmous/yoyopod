# YoyoPod

YoyoPod is an iPod-inspired Raspberry Pi application that combines SIP calling and Mopidy-based music playback behind a small-screen, button-driven UI.

The current codebase supports three display/input modes:

- Pimoroni Display HAT Mini: 320x240 landscape display with four buttons
- PiSugar Whisplay HAT: 240x280 portrait display with a single PTT-style button
- Simulation mode: browser display plus keyboard and web-button input

## Current Status

- VoIP and music integration is implemented in the production app
- The UI package has been refactored into display, input, and screen subpackages
- Hardware abstraction layers exist for display and input
- Demo scripts and tests have been migrated to the current UI/HAL APIs
- Background VoIP and Mopidy callbacks are coordinated through the app's main loop
- GitHub Actions CI validates `uv sync --extra dev` and `uv run pytest -q`

## Main Runtime Components

- `yoyopod.py`: top-level launcher for local development
- `yoyopy/main.py`: package entry point for installed console scripts
- `yoyopy/app.py`: `YoyoPodApp` coordinator
- `yoyopy/state_machine.py`: application state machine for music and call flows
- `yoyopy/audio/mopidy_client.py`: Mopidy JSON-RPC client
- `yoyopy/connectivity/voip_manager.py`: `linphonec` subprocess integration
- `yoyopy/ui/display/`: display HAL, factory, and adapters
- `yoyopy/ui/input/`: input HAL, manager, and adapters
- `yoyopy/ui/screens/`: screen base class, navigation manager, and feature screens

## Hardware Notes

The current implementation assumes a Raspberry Pi environment, but the main hardware-specific paths and audio devices can now be overridden:

- Whisplay driver discovery can be overridden with `YOYOPOD_WHISPLAY_DRIVER`
- Linphone audio devices can be overridden with `YOYOPOD_PLAYBACK_DEVICE`, `YOYOPOD_RINGER_DEVICE`, `YOYOPOD_CAPTURE_DEVICE`, and `YOYOPOD_MEDIA_DEVICE`
- Ring tone output can be overridden with `YOYOPOD_RING_OUTPUT_DEVICE` or `config/yoyopod_config.yaml`
- Simulation mode starts a Flask-SocketIO web server on `http://localhost:5000`

## Installation

### Python Environment

```bash
uv sync --extra dev
```

### System Dependencies

YoyoPod expects these external tools on Raspberry Pi OS:

- `mopidy`
- `linphone-cli`
- `alsa-utils` for `speaker-test`

Example:

```bash
sudo apt install mopidy linphone-cli alsa-utils
```

### Configuration

The repo already ships tracked config files in `config/`.
Edit these in place for your environment:

- `config/voip_config.yaml`
- `config/contacts.yaml`
- `config/yoyopod_config.yaml`

Important settings:

- `config/yoyopod_config.yaml`: display hardware selection, Mopidy host/port, auto-resume behavior
- `config/voip_config.yaml`: SIP account, transport, STUN, `linphonec` path
- `config/contacts.yaml`: contact list and speed dial entries

### Verification

```bash
uv run pytest -q
```

## Running

### Production App

```bash
python yoyopod.py
```

### Simulation Mode

```bash
python yoyopod.py --simulate
```

Simulation mode starts the browser UI at `http://localhost:5000`.

### Installed Console Script

If the package is installed from `pyproject.toml`, the same app is available as:

```bash
yoyopod
```

## Package Layout

```text
yoyopy/
  app.py
  main.py
  state_machine.py
  app_context.py
  audio/
    audio_manager.py
    mopidy_client.py
  config/
    config_manager.py
  connectivity/
    voip_manager.py
  ui/
    __init__.py
    web_server.py
    display/
      display_hal.py
      display_factory.py
      display_manager.py
      adapters/
        pimoroni.py
        simulation.py
        whisplay.py
    input/
      input_hal.py
      input_factory.py
      input_manager.py
      adapters/
        four_button.py
        keyboard.py
        ptt_button.py
    screens/
      base.py
      manager.py
      navigation/
      music/
      voip/
```

## Documentation

- `docs/SYSTEM_ARCHITECTURE.md`: current runtime architecture
- `docs/INTEGRATION_PLAN.md`: integration completion record and remaining cleanup
- `docs/DISPLAY_HAL_ARCHITECTURE.md`: current display HAL design
- `docs/INPUT_HAL_ARCHITECTURE.md`: current input HAL design and compatibility notes
- `docs/UI_RESTRUCTURE_PROPOSAL.md`: refactor status and remaining cleanup
- `docs/PHASE2_SUMMARY.md`: historical screen-integration summary, updated to current file paths

## Current Gaps

- Full end-to-end validation still requires Raspberry Pi hardware, Mopidy, and a reachable SIP service
- CI currently covers the Python test suite, not hardware-in-the-loop scenarios
