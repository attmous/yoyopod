# YoyoPod

YoyoPod is an iPod-inspired Raspberry Pi application that combines SIP calling and local-first Mopidy-based music playback behind a small-screen, button-driven UI.

The current codebase supports three display/input modes:

- Pimoroni Display HAT Mini: 320x240 landscape display with four buttons
- PiSugar Whisplay HAT: 240x280 portrait display with a single PTT-style button
- Simulation mode: browser display plus keyboard and web-button input

On Whisplay, the one-button root hub currently exposes four cards:
- `Listen`
- `Talk`
- `Ask`
- `Setup`

## Current Status

- VoIP and music integration is implemented in the production app
- The UI package has been refactored into display, input, and screen subpackages
- Hardware abstraction layers exist for display and input
- Demo scripts and tests have been migrated to the current UI/HAL APIs
- Background VoIP and Mopidy callbacks are coordinated through the app's main loop
- The production UI now uses the Graffiti Buddy visual system with a fixed root IA:
  - `Listen`
  - `Talk`
  - `Ask`
  - `Setup`
- `Listen` is now local-first and local-only with `Playlists`, `Recent`, and `Shuffle`
- `Talk` now opens as a people-first contact deck: pick a person, then choose `Call` or `Voice Note`
- `Voice Note` now supports hold-to-record, review, local preview playback, send, and sent/failed feedback in the Talk flow
- `Ask` is now a staged shell with idle, listening, thinking, and response states
- Whisplay production rendering now runs on the LVGL backend by default
- GitHub Actions CI validates `uv sync --extra dev` and `uv run pytest -q`

## Main Runtime Components

- `yoyopod.py`: top-level launcher for local development
- `yoyopy/main.py`: package entry point for installed console scripts
- `yoyopy/app.py`: `YoyoPodApp` coordinator
- `scripts/pi_smoke.py`: Raspberry Pi smoke validator for hardware and optional service checks
- `scripts/pi_remote.py`: SSH helper for Raspberry Pi deploy, rsync, restart, logs, status, screenshots, smoke, and run loops
- `scripts/lvgl_soak.py`: LVGL transition and sleep/wake soak helper for Whisplay
- `scripts/pisugar_power.py`: PiSugar battery, shutdown, and watchdog helper
- `scripts/pisugar_rtc.py`: PiSugar RTC status, sync, and alarm helper
- `deploy/systemd/yoyopod@.service`: production systemd unit for boot-time app supervision
- `deploy/pi-deploy.yaml`: shared source of truth for Raspberry Pi runtime, log, screenshot, and rsync settings
- `deploy/pi-deploy.local.yaml`: optional gitignored override for machine-specific Pi host, SSH user, project dir, and branch defaults
- `yoyopy/fsm.py`: split `MusicFSM`, `CallFSM`, and call interruption policy
- `yoyopy/coordinators/runtime.py`: derived `AppRuntimeState` over music, call, and UI state
- `yoyopy/audio/mopidy_client.py`: Mopidy JSON-RPC client
- `yoyopy/voip/manager.py`: Liblinphone-backed call and message facade
- `yoyopy/ui/display/`: display HAL, factory, and adapters
- `yoyopy/ui/input/`: input HAL, manager, and adapters
- `yoyopy/ui/screens/`: screen base class, navigation manager, and feature screens

## Hardware Notes

The current implementation assumes a Raspberry Pi environment, but the main hardware-specific paths and audio devices can now be overridden:

- Whisplay driver discovery can be overridden with `YOYOPOD_WHISPLAY_DRIVER`
- Liblinphone audio devices can be overridden with `YOYOPOD_PLAYBACK_DEVICE`, `YOYOPOD_RINGER_DEVICE`, `YOYOPOD_CAPTURE_DEVICE`, and `YOYOPOD_MEDIA_DEVICE`
- Ring tone output can be overridden with `YOYOPOD_RING_OUTPUT_DEVICE` or `config/yoyopod_config.yaml`
- Simulation mode starts a Flask-SocketIO web server on `http://localhost:5000`

## Installation

### Python Environment

```bash
uv sync --extra dev
```

### System Dependencies

YoyoPod expects these external packages on Raspberry Pi OS:

- `mopidy`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils` for `speaker-test`
- `i2c-tools` for PiSugar watchdog control
- `pisugar-server` for PiSugar power/RTC telemetry via PiSugar's official installer

Example:

```bash
sudo apt install mopidy liblinphone-dev pkg-config cmake alsa-utils i2c-tools
uv run python scripts/liblinphone_build.py
```

### Configuration

The repo already ships tracked config files in `config/`.
Edit these in place for your environment:

- `config/voip_config.yaml`
- `config/liblinphone_factory.conf`
- `config/contacts.yaml`
- `config/yoyopod_config.yaml`

Important settings:

- `config/yoyopod_config.yaml`: display hardware selection, Mopidy host/port, auto-resume behavior
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`: local-only music direction and implementation notes
- `config/yoyopod_config.yaml`: Whisplay gesture tuning under `input.whisplay_*_ms`
- `config/yoyopod_config.yaml`: `input.ptt_navigation=false` is reserved for future voice/PTT work and is currently experimental
- `config/yoyopod_config.yaml`: `power.watchdog_*` controls the PiSugar app heartbeat watchdog
- `config/yoyopod_config.yaml`: `power.*` also controls low-battery warning, graceful shutdown, and PiSugar polling
- `config/yoyopod_config.yaml`: `logging.*` controls file rotation, retention, error-only logs, PID file location, and traceback detail
- `config/voip_config.yaml`: SIP account, transport, STUN, Liblinphone messaging/file-transfer settings
- `config/liblinphone_factory.conf`: repo-managed Liblinphone media, codec, and network defaults used for outbound-call parity on Raspberry Pi
- `config/contacts.yaml`: contact list and speed dial entries

### Verification

CI-safe:

```bash
uv run pytest -q
```

Raspberry Pi smoke:

```bash
uv run python scripts/pi_smoke.py
uv run python scripts/pi_smoke.py --with-power --with-rtc
uv run python scripts/pi_smoke.py --with-mopidy --with-voip --with-rtc
uv run python scripts/pi_smoke.py --with-lvgl-soak
```

Remote Pi workflow:

```bash
uv run python scripts/pi_remote.py config show
uv run python scripts/pi_remote.py config edit
uv run python scripts/pi_remote.py status
uv run python scripts/pi_remote.py preflight --branch main --with-mopidy --with-voip
uv run python scripts/pi_remote.py sync --branch main
uv run python scripts/pi_remote.py rsync
uv run python scripts/pi_remote.py restart
uv run python scripts/pi_remote.py smoke --with-mopidy --with-voip
uv run python scripts/pi_remote.py power
uv run python scripts/pi_remote.py rtc status
uv run python scripts/pi_remote.py rtc sync-to-rtc
uv run python scripts/pi_remote.py logs --lines 200
uv run python scripts/pi_remote.py logs --errors --filter voip
uv run python scripts/pi_remote.py screenshot --output ./pi_screenshot.png
uv run python scripts/pi_remote.py lvgl-soak --cycles 2
uv run python scripts/pi_remote.py service status
uv run python scripts/pi_remote.py service install
uv run python scripts/pi_remote.py whisplay --duration-seconds 45
```

Production service install on the Pi:

```bash
uv run python scripts/pi_remote.py sync --branch main
uv run python scripts/pi_remote.py service install
uv run python scripts/pi_remote.py service status
```

Whisplay tuning on-device:

```bash
uv run python scripts/whisplay_tune.py
uv run python scripts/whisplay_tune.py --double-tap-ms 240 --long-hold-ms 900
```

PiSugar power diagnostics:

```bash
uv run python scripts/pisugar_power.py
uv run python scripts/pi_remote.py power
```

## Logging

The production app now writes two rotating files in `logs/`:

- `logs/yoyopod.log`: main structured log with timestamps, subsystem tag, module/function/line, and message
- `logs/yoyopod_errors.log`: errors-only companion log

The checked-in deploy contract at `deploy/pi-deploy.yaml` defines the shared remote tooling defaults. `deploy/pi-deploy.local.yaml` is the gitignored machine-local override for host, SSH user, project directory, and branch. Manage them with:

```bash
uv run python scripts/pi_remote.py config show
uv run python scripts/pi_remote.py config edit
```

The merged config controls process names, screenshot path, and these project-relative log paths:

- `<project-dir>/logs/yoyopod.log`
- `<project-dir>/logs/yoyopod_errors.log`
- `/tmp/yoyopod.pid`

Typical remote debugging flow:

```bash
uv run python scripts/pi_remote.py logs --lines 200
uv run python scripts/pi_remote.py logs --errors
uv run python scripts/pi_remote.py logs --filter voip
uv run python scripts/pi_remote.py logs --follow --filter ERROR
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

### Runtime Demo

```bash
python demos/demo_runtime_state.py --simulate
```

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
  fsm.py
  app_context.py
  coordinators/
  audio/
    manager.py
    mopidy_client.py
  config/
    manager.py
  voip/
    backend.py
    history.py
    manager.py
    models.py
  ui/
    __init__.py
    web_server.py
    display/
      hal.py
      factory.py
      manager.py
      adapters/
        pimoroni.py
        simulation.py
        whisplay.py
    input/
      hal.py
      factory.py
      manager.py
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
- `docs/POWER_MODULE.md`: PiSugar power architecture, config, safety, RTC, watchdog, and diagnostics
- `docs/LVGL_MIGRATION_PLAN.md`: Whisplay LVGL migration record and backend boundaries
- `docs/RPI_SMOKE_VALIDATION.md`: Raspberry Pi smoke checklist and manual follow-up drills
- `docs/PI_DEV_WORKFLOW.md`: SSH-based Raspberry Pi sync/run workflow and release checklist
- `docs/UI_RESTRUCTURE_PROPOSAL.md`: refactor status and remaining cleanup
- `docs/PHASE2_SUMMARY.md`: historical screen-integration summary, updated to current file paths

## Current Gaps

- Full end-to-end validation still requires Raspberry Pi hardware, Mopidy, and a reachable SIP service; see `docs/RPI_SMOKE_VALIDATION.md`
- CI currently covers the Python test suite, not hardware-in-the-loop scenarios
