# YoyoPod - Agent Instructions

**Last Updated:** 2026-04-09
**Target Hardware:** Raspberry Pi Zero 2W
**Project:** iPod-inspired VoIP and mpv-based local music player with a small-screen, button-driven UI

---

## Project Rules

Follow all instructions in the `rules/` directory:
- `rules/project.md` -- project overview, commands, configuration
- `rules/architecture.md` -- system architecture, HAL layers, state machines
- `rules/code-style.md` -- Python 3.12+, black, ruff, type hints
- `rules/design-fidelity.md` -- Figma-to-Whisplay workflow, screen extraction, and hardware validation loop
- `rules/voip.md` -- Liblinphone integration, SIP and messaging patterns
- `rules/lvgl.md` -- LVGL display pipeline, C shim, screenshot support
- `rules/logging.md` -- loguru contract, subsystem tags, PID file
- `rules/deploy.md` -- Pi deploy workflow and commands

## Pi Deployment Skills

Workflow instructions for deploying and debugging on Raspberry Pi are in `skills/`:

| Skill | File | Purpose |
|---|---|---|
| yoyopod-deploy | `skills/yoyopod-deploy/SKILL.md` | Git push, remote branch sync, restart, verify |
| yoyopod-sync | `skills/yoyopod-sync/SKILL.md` | Rsync dirty tree (no commit), restart |
| yoyopod-logs | `skills/yoyopod-logs/SKILL.md` | Tail app logs with filtering |
| yoyopod-restart | `skills/yoyopod-restart/SKILL.md` | Kill processes and relaunch |
| yoyopod-status | `skills/yoyopod-status/SKILL.md` | Health check dashboard |
| yoyopod-screenshot | `skills/yoyopod-screenshot/SKILL.md` | Capture display (shadow buffer or LVGL readback) |

When asked to deploy, sync, restart, check status, view logs, or take a screenshot on the Pi, read the matching file from `skills/` and follow its Steps section. The shared config contract lives in `deploy/pi-deploy.yaml`, machine-specific overrides belong in `deploy/pi-deploy.local.yaml`, and `yoyoctl remote config edit` is the preferred way to create or update the local override. All skills should prefer `yoyoctl remote` over duplicating SSH workflow steps.

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
- Whisplay now runs on the LVGL rendering path in production under `yoyopy/ui/lvgl_binding/`.
- Production local music now runs through the app-managed mpv backend under `yoyopy/audio/music/`.
- Production VoIP now runs through Liblinphone under `yoyopy/voip/liblinphone_binding/` and `yoyopy/voip/backend.py`.
- CI validates the Python test suite with `uv sync --extra dev` and `uv run pytest -q`.
- Raspberry Pi validation has a defined path through `yoyoctl pi smoke` and `yoyoctl remote`.

This file should reflect the repo as it exists on `main`. Older milestone notes are useful for history, but they are not the source of truth anymore.

---

## LVGL Status

- Whisplay has completed its production cutover to LVGL-backed rendering.
- The migration plan and backend notes live in `docs/LVGL_MIGRATION_PLAN.md`.
- Pimoroni and simulation still use the PIL rendering path.
- Raw LVGL usage should remain confined to `yoyopy/ui/lvgl_binding/` and related display-layer code.

---

## Source Of Truth

When in doubt, trust these files first:

- `yoyopy/app.py`
- `yoyopy/fsm.py`
- `yoyopy/event_bus.py`
- `yoyopy/events.py`
- `yoyopy/coordinators/runtime.py`
- `yoyopy/audio/`
- `yoyopy/voip/`
- `yoyopy/power/`
- `yoyopy/ui/display/`
- `yoyopy/ui/lvgl_binding/`
- `yoyopy/ui/input/`
- `yoyopy/ui/screens/`
- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/POWER_MODULE.md`
- `docs/LVGL_MIGRATION_PLAN.md`
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`

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
     -> LocalMusicService
     -> MpvBackend
        -> MpvProcess
        -> MpvIpcClient
     -> VoIPManager
        -> LiblinphoneBackend
     -> PowerManager
        -> PiSugarBackend
        -> PiSugarWatchdog
```

Key design points:

- Music and call state are modeled separately in `yoyopy/fsm.py`.
- The app no longer uses a monolithic combined `StateMachine`.
- Background music-backend and VoIP events are published onto the typed `EventBus` and drained on the coordinator thread.
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

- `yoyopy/audio/local_service.py` - filesystem-backed playlists, shuffle source collection, and recent-track integration
- `yoyopy/audio/music/backend.py` - `MusicBackend`, `MpvBackend`, and `MockMusicBackend`
- `yoyopy/audio/music/process.py` - app-managed mpv process lifecycle
- `yoyopy/audio/music/ipc.py` - low-level mpv JSON IPC client
- `yoyopy/audio/music/models.py` - `Track`, `Playlist`, and `MusicConfig`
- `yoyopy/audio/volume.py` - shared output-volume coordination across ALSA and mpv
- `yoyopy/voip/manager.py` - app-facing VoIP facade
- `yoyopy/voip/backend.py` - `VoIPBackend`, `LiblinphoneBackend`, `MockVoIPBackend`
- `yoyopy/voip/models.py` - SIP config plus typed call/message backend events
- `yoyopy/voip/liblinphone_binding/` - native Liblinphone shim and CPython cffi binding
- `yoyopy/voip/messages.py` - persistent voice-note/message metadata store
- `yoyopy/voip/history.py` - persistent recent/missed-call store for the Talk flow

### Power

- `yoyopy/power/backend.py` - PiSugar socket/TCP backend for telemetry and RTC control
- `yoyopy/power/watchdog.py` - PiSugar software watchdog controller over `i2cget`/`i2cset`
- `yoyopy/power/manager.py` - app-facing power facade
- `yoyopy/power/policies.py` - low-battery safety policy
- `yoyopy/cli/pi/power.py` - battery, charging, shutdown, watchdog, and RTC helpers (`yoyoctl pi power battery`, `yoyoctl pi power rtc`)
- `deploy/systemd/yoyopod@.service` - production boot-time service unit

### UI

- `yoyopy/ui/display/` - display HAL, factory, facade, and adapters
- `yoyopy/ui/lvgl_binding/` - native LVGL shim, CPython binding, backend bridge, and input bridge
- `yoyopy/ui/input/` - input HAL, factory, manager, and adapters
- `yoyopy/ui/screens/manager.py` - stack navigation and input binding
- `yoyopy/ui/screens/router.py` - declarative route resolution
- `yoyopy/ui/screens/theme.py` - Graffiti Buddy shared chrome, colors, icons, and status-bar renderer
- `yoyopy/ui/screens/navigation/listen.py` - local-first library menu for `Playlists`, `Recent`, and `Shuffle`
- `yoyopy/ui/screens/music/recent.py` - recent local tracks browser
- `yoyopy/ui/screens/navigation/ask.py` - staged `Ask` shell with idle/listening/thinking/response states
- `yoyopy/ui/screens/system/power.py` - `Setup` screen with power and care pages
- `yoyopy/ui/screens/voip/quick_call.py` - `Talk` people-first contact deck for calls and voice notes
- `yoyopy/ui/screens/voip/talk_contact.py` - selected-contact action screen with `Call` and `Voice Note`
- `yoyopy/ui/screens/voip/call_history.py` - Talk recents and missed-call screen
- `yoyopy/ui/screens/voip/voice_note.py` - voice-note record/review/send flow for the Talk experience

### CLI (dev-only)

- `yoyopy/cli/__init__.py` - root yoyoctl app and group wiring
- `yoyopy/cli/common.py` - shared logging and config helpers
- `yoyopy/cli/build.py` - native extension build commands
- `yoyopy/cli/pi/` - on-Pi hardware and diagnostic commands
- `yoyopy/cli/remote/` - SSH-based remote Pi operations

### Configuration

- `config/voip_config.yaml`
- `config/liblinphone_factory.conf`
- `config/contacts.yaml`
- `config/yoyopod_config.yaml`
- `yoyopy/config/models.py` - typed config models
- `yoyopy/config/manager.py` - current config facade used by the app

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
- `YOYOPOD_MUSIC_DIR`
- `YOYOPOD_MPV_SOCKET`
- `YOYOPOD_MPV_BINARY`
- `YOYOPOD_ALSA_DEVICE`
- `YOYOPOD_DEFAULT_VOLUME`
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
python -m compileall yoyopy tests demos
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
python demos/demo_runtime_state.py --simulate
```

---

## Raspberry Pi Workflow

Preferred remote helper:

```bash
yoyoctl remote status --host rpi-zero
yoyoctl remote preflight --host rpi-zero --with-music --with-voip --with-lvgl-soak
yoyoctl remote sync --host rpi-zero --branch main
yoyoctl remote smoke --host rpi-zero --with-music --with-voip --with-lvgl-soak
yoyoctl remote lvgl-soak --host rpi-zero --cycles 2
yoyoctl remote power --host rpi-zero
yoyoctl remote service install --host rpi-zero
```

Direct smoke helper on the Pi:

```bash
yoyoctl pi smoke
yoyoctl pi smoke --with-music --with-voip
yoyoctl pi lvgl soak
```

If the Pi seems to keep old Python state after a pull, restart the running app process before retesting.

---

## Debug Entry Points

Manual diagnostics are available via `yoyoctl pi voip`:

```bash
yoyoctl pi voip check
yoyoctl pi voip debug
```

Helpful remote checks:

```bash
ssh rpi-zero "ps aux | grep -E '(python|mpv)'"
ssh rpi-zero "free -h"
ssh rpi-zero "pgrep -af mpv"
ssh rpi-zero "killall -9 python"
```

If SIP behavior looks wrong, inspect the Liblinphone shim and backend boundary:

- `yoyopy/voip/liblinphone_binding/native/liblinphone_shim.c`
- `yoyopy/voip/liblinphone_binding/binding.py`
- `yoyopy/voip/backend.py`

---

## Current Test Suite

High-signal tests:

- `tests/test_fsm_runtime.py`
- `tests/test_event_bus.py`
- `tests/test_app_orchestration.py`
- `tests/test_screen_routing.py`
- `tests/test_call_screen.py`
- `tests/test_music_backend.py`
- `tests/test_voip_backend.py`
- `tests/test_config_models.py`
- `tests/test_pi_remote.py`
- `tests/test_cli.py`

CI-safe tests are in `tests/`. Hardware diagnostics were intentionally moved out of the test suite.

---

## Stale Names To Avoid

These old names are no longer correct:

- `yoyopy/connectivity/` -> use `yoyopy/voip/`
- `yoyopy/connectivity/voip_manager.py` -> use `yoyopy/voip/manager.py`
- `yoyopy/connectivity/voip_backend.py` -> use `yoyopy/voip/backend.py`
- `yoyopy/connectivity/voip_types.py` -> use `yoyopy/voip/models.py`
- `state_machine.py` -> removed; use `yoyopy/fsm.py` and `yoyopy/coordinators/runtime.py`
- `demo_yoyopod_phase1.py` -> removed
- `tests/test_phase1_state_machine.py` -> replaced by `tests/test_fsm_runtime.py`
- `tests/test_voip_registration.py` -> use `yoyoctl pi voip check`
- `tests/test_incoming_call_debug.py` -> use `yoyoctl pi voip debug`
- `scripts/pi_remote.py` -> use `yoyoctl remote`
- `scripts/pi_smoke.py` -> use `yoyoctl pi smoke`
- `scripts/check_voip_registration.py` -> use `yoyoctl pi voip check`
- `scripts/debug_incoming_call.py` -> use `yoyoctl pi voip debug`
- `scripts/pisugar_power.py` -> use `yoyoctl pi power battery`
- `scripts/pisugar_rtc.py` -> use `yoyoctl pi power rtc`
- `scripts/lvgl_build.py` -> use `yoyoctl build lvgl`
- `scripts/liblinphone_build.py` -> use `yoyoctl build liblinphone`
- `scripts/lvgl_soak.py` -> use `yoyoctl pi lvgl soak`
- `scripts/lvgl_probe.py` -> use `yoyoctl pi lvgl probe`
- `scripts/whisplay_tune.py` -> use `yoyoctl pi tune`
- `scripts/whisplay_gallery.py` -> use `yoyoctl pi gallery`

If an old doc mentions combined VoIP/music states as the implementation model, treat it as historical context only.

---

## Active Product Gaps

The architecture cleanup is largely done. The remaining work is more product-facing:

- dial pad / manual SIP entry
- fuller local library browse (`Artists` / `Albums`)
- fuller settings UI
- additional hardware-in-the-loop validation on Raspberry Pi

The current codebase is in a good place to focus on product behavior instead of large structural rewrites.

---

## References

- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/RPI_SMOKE_VALIDATION.md`
- `docs/PI_DEV_WORKFLOW.md`
- `docs/archive/`
- Project repository: `https://github.com/moustafattia/yoyo-py`
