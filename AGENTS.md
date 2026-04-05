# YoyoPod Current Status & Developer Guide

**Last Updated:** 2026-04-05
**Target Hardware:** Raspberry Pi Zero 2W
**Project:** iPod-inspired VoIP and Mopidy player with a small-screen, button-driven UI

---

## Current Status

- Production runtime is `yoyopod.py` -> `yoyopy.main` -> `YoyoPodApp`.
- The large architecture refactor is complete:
  - typed `EventBus`
  - split `MusicFSM` and `CallFSM`
  - coordinator modules under `yoyopy/coordinators/`
  - derived runtime state in `CoordinatorRuntime`
  - declarative screen routing
  - typed config models with YAML plus env overlay
  - dedicated `yoyopy/voip/` package
- PiSugar-backed power management is now implemented:
  - telemetry polling
  - low-battery warning and graceful shutdown
  - screen timeout and usage tracking
  - RTC helpers
  - PiSugar software watchdog support
- Production Raspberry Pi deployment now has a committed systemd unit template under `deploy/systemd/`.
- CI validates the Python test suite with `uv sync --extra dev` and `uv run pytest -q`.
- Raspberry Pi validation has a defined path through `scripts/pi_smoke.py` and `scripts/pi_remote.py`.

This file should reflect the repo as it exists on `main`. Older milestone notes are useful for history, but they are not the source of truth anymore.

---

## Source Of Truth

When in doubt, trust these files first:

- `yoyopy/app.py`
- `yoyopy/fsm.py`
- `yoyopy/event_bus.py`
- `yoyopy/events.py`
- `yoyopy/coordinators/runtime.py`
- `yoyopy/voip/`
- `yoyopy/power/`
- `yoyopy/ui/display/`
- `yoyopy/ui/input/`
- `yoyopy/ui/screens/`
- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/POWER_MODULE.md`

---

## Runtime Architecture

Current production topology:

```text
yoyopod.py / yoyopy.main
  -> YoyoPodApp
     -> EventBus
     -> MusicFSM
     -> CallFSM
     -> CallInterruptionPolicy
     -> CoordinatorRuntime
     -> CallCoordinator / PlaybackCoordinator / ScreenCoordinator
     -> Display facade
        -> display factory
        -> Pimoroni | Whisplay | Simulation adapters
     -> InputManager
        -> FourButton | PTT | Keyboard adapters
     -> ScreenManager
        -> declarative router
        -> navigation / music / voip screens
     -> MopidyClient
     -> VoIPManager
        -> LinphonecBackend
     -> PowerManager
        -> PiSugarBackend
        -> PiSugarWatchdog
```

Key design points:

- Music and call state are modeled separately in `yoyopy/fsm.py`.
- The app no longer uses a monolithic combined `StateMachine`.
- Background Mopidy and VoIP events are published onto the typed `EventBus` and drained on the coordinator thread.
- `CoordinatorRuntime` derives the user-facing app state from the split FSMs plus UI state.
- The screen stack is still the core navigation model.

---

## Important Packages And Files

### Application Core

- `yoyopy/app.py` - app bootstrap, lifecycle, recovery loop, and coordinator wiring
- `yoyopy/main.py` - package entry point
- `yoyopy/app_context.py` - shared screen/application context
- `yoyopy/fsm.py` - `MusicFSM`, `CallFSM`, `CallInterruptionPolicy`
- `yoyopy/event_bus.py` - thread-safe typed event bus
- `yoyopy/events.py` - typed orchestration events

### Coordinators

- `yoyopy/coordinators/call.py` - call-flow orchestration
- `yoyopy/coordinators/playback.py` - music-flow orchestration
- `yoyopy/coordinators/screen.py` - screen refresh and call-screen updates
- `yoyopy/coordinators/runtime.py` - derived `AppRuntimeState` and shared runtime references

### Audio And VoIP

- `yoyopy/audio/mopidy_client.py` - Mopidy JSON-RPC client
- `yoyopy/voip/manager.py` - app-facing VoIP facade
- `yoyopy/voip/backend.py` - `VoIPBackend`, `LinphonecBackend`, `MockVoIPBackend`
- `yoyopy/voip/types.py` - SIP config and typed backend events

### Power

- `yoyopy/power/backend.py` - PiSugar socket/TCP backend for telemetry and RTC control
- `yoyopy/power/watchdog.py` - PiSugar software watchdog controller over `i2cget`/`i2cset`
- `yoyopy/power/manager.py` - app-facing power facade
- `yoyopy/power/policies.py` - low-battery safety policy
- `scripts/pisugar_power.py` - battery, charging, shutdown, and watchdog helper
- `scripts/pisugar_rtc.py` - RTC status/sync/alarm helper
- `deploy/systemd/yoyopod@.service` - production boot-time service unit

### UI

- `yoyopy/ui/display/` - display HAL, factory, facade, and adapters
- `yoyopy/ui/input/` - input HAL, factory, manager, and adapters
- `yoyopy/ui/screens/manager.py` - stack navigation and input binding
- `yoyopy/ui/screens/router.py` - declarative route resolution
- `yoyopy/ui/screens/theme.py` - Graffiti Buddy shared chrome, colors, icons, and status-bar renderer
- `yoyopy/ui/screens/navigation/listen.py` - source chooser for the `Listen` root mode
- `yoyopy/ui/screens/navigation/ask.py` - future-safe `Ask` mode placeholder
- `yoyopy/ui/screens/navigation/power.py` - `Setup` screen with power and care pages
- `yoyopy/ui/screens/voip/hub.py` - `Talk` quick-call hub

### Configuration

- `config/voip_config.yaml`
- `config/contacts.yaml`
- `config/yoyopod_config.yaml`
- `yoyopy/config/models.py` - typed config models
- `yoyopy/config/config_manager.py` - current config facade used by the app

---

## Supported Hardware Modes

Current display/input combinations:

- Pimoroni Display HAT Mini: 320x240 landscape with four buttons
- PiSugar Whisplay: 240x280 portrait with a single PTT-style button
- Simulation mode: browser-rendered display with keyboard and web-button input

Useful env overrides:

- `YOYOPOD_DISPLAY`
- `YOYOPOD_WHISPLAY_DRIVER`
- `YOYOPOD_PLAYBACK_DEVICE`
- `YOYOPOD_RINGER_DEVICE`
- `YOYOPOD_CAPTURE_DEVICE`
- `YOYOPOD_MEDIA_DEVICE`
- `YOYOPOD_RING_OUTPUT_DEVICE`
- `YOYOPOD_PI_HOST`
- `YOYOPOD_PI_PROJECT_DIR`
- `YOYOPOD_PI_BRANCH`

---

## Local Development Workflow

### Setup

```bash
uv sync --extra dev
```

### Validate Locally

```bash
python -m compileall yoyopy tests demos scripts
uv run pytest -q
```

### Run The Production App

```bash
python yoyopod.py
python yoyopod.py --simulate
```

### Useful Demos

```bash
python demos/demo_voip.py --simulate
python demos/demo_playlists.py
python demos/demo_mopidy.py
python demos/demo_runtime_state.py --simulate
```

---

## Raspberry Pi Workflow

Preferred remote helper:

```bash
uv run python scripts/pi_remote.py status --host rpi-zero
uv run python scripts/pi_remote.py preflight --host rpi-zero --with-mopidy --with-voip
uv run python scripts/pi_remote.py sync --host rpi-zero --branch main
uv run python scripts/pi_remote.py smoke --host rpi-zero --with-mopidy --with-voip
uv run python scripts/pi_remote.py power --host rpi-zero
uv run python scripts/pi_remote.py service install --host rpi-zero
```

Direct smoke helper on the Pi:

```bash
uv run python scripts/pi_smoke.py
uv run python scripts/pi_smoke.py --with-mopidy --with-voip
```

If the Pi seems to keep old Python state after a pull, restart the running app process before retesting.

---

## Debug Entry Points

Manual diagnostics live in `scripts/`, not `tests/`:

```bash
uv run python scripts/check_voip_registration.py
uv run python scripts/debug_incoming_call.py
```

Helpful remote checks:

```bash
ssh rpi-zero "ps aux | grep -E '(python|linphonec|mopidy)'"
ssh rpi-zero "free -h"
ssh rpi-zero "systemctl --user status mopidy"
ssh rpi-zero "killall -9 python linphonec"
```

If SIP behavior looks wrong, inspect `linphonec` parsing in `yoyopy/voip/backend.py`.

Important current Linphone parsing assumptions:

- Linphone 5.x emits `CallSession` output
- incoming calls may use `LinphoneCallIncoming`
- SIP addresses may appear in square brackets like `[sip:user@domain]`
- incoming call text is typically lowercase `New incoming call from ...`

---

## Current Test Suite

High-signal tests:

- `tests/test_fsm_runtime.py`
- `tests/test_event_bus.py`
- `tests/test_app_orchestration.py`
- `tests/test_screen_routing.py`
- `tests/test_call_screen.py`
- `tests/test_voip_backend.py`
- `tests/test_config_models.py`
- `tests/test_pi_remote.py`

CI-safe tests are in `tests/`. Hardware diagnostics were intentionally moved out of the test suite.

---

## Stale Names To Avoid

These old names are no longer correct:

- `yoyopy/connectivity/` -> use `yoyopy/voip/`
- `yoyopy/connectivity/voip_manager.py` -> use `yoyopy/voip/manager.py`
- `yoyopy/connectivity/voip_backend.py` -> use `yoyopy/voip/backend.py`
- `yoyopy/connectivity/voip_types.py` -> use `yoyopy/voip/types.py`
- `state_machine.py` -> removed; use `yoyopy/fsm.py` and `yoyopy/coordinators/runtime.py`
- `demo_yoyopod_phase1.py` -> removed
- `tests/test_phase1_state_machine.py` -> replaced by `tests/test_fsm_runtime.py`
- `tests/test_voip_registration.py` -> moved to `scripts/check_voip_registration.py`
- `tests/test_incoming_call_debug.py` -> moved to `scripts/debug_incoming_call.py`

If an old doc mentions combined VoIP/music states as the implementation model, treat it as historical context only.

---

## Active Product Gaps

The architecture cleanup is largely done. The remaining work is more product-facing:

- dial pad / manual SIP entry
- call history and missed-call UX
- fuller settings UI
- additional hardware-in-the-loop validation on Raspberry Pi

The current codebase is in a good place to focus on product behavior instead of large structural rewrites.

---

## References

- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/INTEGRATION_PLAN.md`
- `docs/RPI_SMOKE_VALIDATION.md`
- `docs/PI_DEV_WORKFLOW.md`
- Project repository: `https://github.com/moustafattia/yoyo-py`
