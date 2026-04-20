# YoyoPod - Agent Instructions

**Last Updated:** 2026-04-18
**Target Hardware:** Raspberry Pi Zero 2W
**Project:** iPod-inspired communication, local music, modem, and voice device with a small-screen button UI

---

## Guidance Hierarchy

Use the repo guidance in this order:

1. Current code in `src/yoyopod/`
2. [`README.md`](README.md) and [`docs/README.md`](docs/README.md)
3. `rules/` for project constraints and architecture/style rules
4. `AGENTS.md` for current runtime status and agent workflow
5. `skills/` for task-specific operational playbooks
6. `.claude/` and `.agents/` as tool-facing overlays and mirrors

Canonical locations:
- `skills/` is the canonical skill source
- `.claude/skills/` and `.agents/skills/` are tool-facing mirrors
- current runtime docs beat older plan docs when they disagree
- `docs/archive/` is historical context only

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

Workflow instructions for deploying and debugging on Raspberry Pi are in canonical files under `skills/`:

| Skill | File | Purpose |
|---|---|---|
| yoyopod-deploy | `skills/yoyopod-deploy/SKILL.md` | Commit-safe branch/SHA validation on the Pi |
| yoyopod-sync | `skills/yoyopod-sync/SKILL.md` | Rare-case dirty-tree sync escape hatch |
| yoyopod-logs | `skills/yoyopod-logs/SKILL.md` | Tail app logs with filtering |
| yoyopod-restart | `skills/yoyopod-restart/SKILL.md` | Kill processes and relaunch |
| yoyopod-status | `skills/yoyopod-status/SKILL.md` | Health check dashboard |
| yoyopod-screenshot | `skills/yoyopod-screenshot/SKILL.md` | Capture display (shadow buffer or LVGL readback) |

When asked to deploy, sync, restart, check status, view logs, or take a screenshot on the Pi, read the matching file from `skills/` and follow its Steps section. The shared config contract lives in `deploy/pi-deploy.yaml`, machine-specific overrides belong in `deploy/pi-deploy.local.yaml`, and `yoyopod remote config edit` is the preferred way to create or update the local override. All skills should prefer `yoyopod remote` over duplicating SSH workflow steps.

---

## Current Status

- Production runtime is `yoyopod.py` -> `yoyopod.main` -> `YoyoPodApp`.
- The large architecture refactor is complete:
  - typed `EventBus`
  - split `MusicFSM` and `CallFSM`
  - coordinator modules under `src/yoyopod/coordinators/`
  - derived runtime state in `CoordinatorRuntime`
  - focused runtime services under `src/yoyopod/runtime/`
  - typed config models with canonical domain-owned YAML layers plus env overlay
  - `src/yoyopod/communication/`, `src/yoyopod/people/`, `src/yoyopod/network/`, and `src/yoyopod/voice/` packages
- PiSugar-backed power management is now implemented:
  - telemetry polling
  - low-battery warning and graceful shutdown
  - screen timeout and usage tracking
  - RTC helpers
  - PiSugar software watchdog support
- Production Raspberry Pi deployment runs as `yoyopod@raouf.service` (systemd unit template at `deploy/systemd/yoyopod@.service`).
- Whisplay now runs on the LVGL rendering path in production under `src/yoyopod/ui/lvgl_binding/`.
- Production local music now runs through the app-managed mpv backend under `src/yoyopod/audio/music/`.
- Production communication now runs through Liblinphone under `src/yoyopod/communication/integrations/liblinphone_binding/` and `src/yoyopod/communication/calling/backend.py`.
- CI validates the staged quality gate plus Python test suite; the local mirror is `uv run python scripts/quality.py ci`.
- Raspberry Pi validation has a defined path through the `yoyopod pi validate` suite and `yoyopod remote`.

This file should reflect the repo as it exists on `main`. Older milestone notes are useful for history, but they are not the source of truth anymore.

---

## LVGL Status

- Whisplay has completed its production cutover to LVGL-backed rendering.
- The migration plan and backend notes live in `docs/LVGL_MIGRATION_PLAN.md`.
- Pimoroni and simulation still use the PIL rendering path.
- Raw LVGL usage should remain confined to `src/yoyopod/ui/lvgl_binding/` and related display-layer code.

---

## Source Of Truth

When in doubt, trust these files first:

- `src/yoyopod/app.py`
- `src/yoyopod/fsm.py`
- `src/yoyopod/event_bus.py`
- `src/yoyopod/events.py`
- `src/yoyopod/coordinators/runtime.py`
- `src/yoyopod/audio/`
- `src/yoyopod/communication/`
- `src/yoyopod/people/`
- `src/yoyopod/network/`
- `src/yoyopod/power/`
- `src/yoyopod/ui/display/`
- `src/yoyopod/ui/lvgl_binding/`
- `src/yoyopod/ui/input/`
- `src/yoyopod/ui/screens/`
- `src/yoyopod/voice/`
- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/CLOUD_PROVISIONING_AND_BACKEND.md`
- `docs/POWER_MODULE.md`
- `docs/LVGL_MIGRATION_PLAN.md`
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`

---

## Runtime Architecture

Current production topology:

```text
yoyopod.py / yoyopod.main
  -> YoyoPodApp
     -> RuntimeBootService / RuntimeLoopService / RecoverySupervisor
     -> ScreenPowerService / ShutdownLifecycleService
     -> EventBus
     -> MusicFSM
     -> CallFSM
     -> CallInterruptionPolicy
     -> CoordinatorRuntime
     -> CallCoordinator / PlaybackCoordinator / PowerCoordinator / ScreenCoordinator
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
     -> PeopleDirectory
     -> PowerManager
        -> PiSugarBackend
        -> PiSugarWatchdog
     -> CloudManager
        -> DeviceMqttClient (transport: websockets via Cloudflare)
        -> cloud config sync, telemetry, remote command handling
     -> NetworkManager
     -> VoiceRuntimeCoordinator
```

Key design points:

- Music and call state are modeled separately in `src/yoyopod/fsm.py`.
- The app no longer uses a monolithic combined `StateMachine`.
- Background music-backend and VoIP events are published onto the typed `EventBus` and drained on the coordinator thread.
- `CoordinatorRuntime` derives the user-facing app state from the split FSMs plus UI state.
- The screen stack is still the core navigation model.

---

## Important Packages And Files

### Application Core

- `src/yoyopod/app.py` - app bootstrap, lifecycle, recovery loop, and coordinator wiring
- `src/yoyopod/main.py` - package entry point
- `src/yoyopod/app_context.py` - shared screen/application context
- `src/yoyopod/fsm.py` - `MusicFSM`, `CallFSM`, `CallInterruptionPolicy`
- `src/yoyopod/event_bus.py` - thread-safe typed event bus
- `src/yoyopod/events.py` - typed orchestration events

### Coordinators

- `src/yoyopod/coordinators/call.py` - call-flow orchestration
- `src/yoyopod/coordinators/playback.py` - music-flow orchestration
- `src/yoyopod/coordinators/screen.py` - screen refresh and call-screen updates
- `src/yoyopod/coordinators/runtime.py` - derived `AppRuntimeState` and shared runtime references

### Audio And Communication

- `src/yoyopod/audio/local_service.py` - filesystem-backed playlists, shuffle source collection, and recent-track integration
- `src/yoyopod/audio/music/backend.py` - `MusicBackend`, `MpvBackend`, and `MockMusicBackend`
- `src/yoyopod/audio/music/process.py` - app-managed mpv process lifecycle
- `src/yoyopod/audio/music/ipc.py` - low-level mpv JSON IPC client
- `src/yoyopod/audio/music/models.py` - `Track`, `Playlist`, and `MusicConfig`
- `src/yoyopod/audio/volume.py` - shared output-volume coordination across ALSA and mpv
- `src/yoyopod/communication/calling/manager.py` - app-facing VoIP facade
- `src/yoyopod/communication/calling/backend.py` - `VoIPBackend`, `LiblinphoneBackend`, and `MockVoIPBackend`
- `src/yoyopod/communication/models.py` - shared communication-facing typed models and re-exports
- `src/yoyopod/communication/calling/history.py` - persistent recent/missed-call store for the Talk flow
- `src/yoyopod/communication/messaging/` - voice-note/message metadata store
- `src/yoyopod/communication/integrations/liblinphone_binding/` - native Liblinphone shim and CPython cffi binding
- `src/yoyopod/people/directory.py` - mutable contacts and people lookup

### Network And Voice

- `src/yoyopod/network/` - modem, PPP, GPS, and transport code
- `src/yoyopod/voice/` - local capture, STT, TTS, and command matching

### Power

- `src/yoyopod/power/backend.py` - PiSugar socket/TCP backend for telemetry and RTC control
- `src/yoyopod/power/watchdog.py` - PiSugar software watchdog controller over `i2cget`/`i2cset`
- `src/yoyopod/power/manager.py` - app-facing power facade
- `src/yoyopod/power/policies.py` - low-battery safety policy
- `src/yoyopod/cli/pi/power.py` - battery, charging, shutdown, watchdog, and RTC helpers (`yoyopod pi power battery`, `yoyopod pi power rtc`)
- `deploy/systemd/yoyopod@.service` - production boot-time service unit

### UI

- `src/yoyopod/ui/display/` - display HAL, factory, facade, and adapters
- `src/yoyopod/ui/lvgl_binding/` - native LVGL shim, CPython binding, backend bridge, and input bridge
- `src/yoyopod/ui/input/` - input HAL, factory, manager, and adapters
- `src/yoyopod/ui/screens/manager.py` - stack navigation and input binding
- `src/yoyopod/ui/screens/router.py` - declarative route resolution
- `src/yoyopod/ui/screens/theme.py` - Graffiti Buddy shared chrome, colors, icons, and status-bar renderer
- `src/yoyopod/ui/screens/navigation/listen.py` - local-first library menu for `Playlists`, `Recent`, and `Shuffle`
- `src/yoyopod/ui/screens/music/recent.py` - recent local tracks browser
- `src/yoyopod/ui/screens/navigation/ask.py` - staged `Ask` shell with idle/listening/thinking/response states
- `src/yoyopod/ui/screens/system/power.py` - `Setup` screen with power and care pages
- `src/yoyopod/ui/screens/voip/quick_call.py` - `Talk` people-first contact deck for calls and voice notes
- `src/yoyopod/ui/screens/voip/talk_contact.py` - selected-contact action screen with `Call` and `Voice Note`
- `src/yoyopod/ui/screens/voip/call_history.py` - Talk recents and missed-call screen
- `src/yoyopod/ui/screens/voip/voice_note.py` - voice-note record/review/send flow for the Talk experience

### CLI (dev-only)

- `src/yoyopod/cli/__init__.py` - root yoyopod app and group wiring
- `src/yoyopod/cli/common.py` - shared logging and config helpers
- `src/yoyopod/cli/build.py` - native extension build commands
- `src/yoyopod/cli/pi/` - on-Pi hardware and diagnostic commands
- `src/yoyopod/cli/remote/` - SSH-based remote Pi operations

### Cloud Integration

- `src/yoyopod/cloud/manager.py` — CloudManager: provisioning, HTTPS auth/refresh, config polling, MQTT telemetry
- `src/yoyopod/cloud/mqtt_client.py` — DeviceMqttClient with configurable transport (tcp/websockets)
- `config/cloud/backend.yaml` — MQTT broker host, port, TLS, transport, REST API base URL

### Configuration

- `config/app/core.yaml`
- `config/audio/music.yaml`
- `config/device/hardware.yaml`
- `config/network/cellular.yaml`
- `config/voice/assistant.yaml`
- `config/communication/calling.yaml`
- `config/communication/messaging.yaml`
- `config/communication/calling.secrets.example.yaml`
- `config/communication/integrations/liblinphone_factory.conf`
- `config/people/directory.yaml`
- `config/people/contacts.seed.yaml`
- `src/yoyopod/config/models.py` - typed config models
- `src/yoyopod/config/manager.py` - current config facade used by the app

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
- `YOYOPOD_CLOUD_MQTT_TRANSPORT` (websockets/tcp, default tcp)

---

## Local Development Workflow

### Setup

```bash
uv sync --extra dev
```

### Validate Locally

```bash
uv run python scripts/quality.py ci
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
yoyopod remote status --host rpi-zero
yoyopod remote preflight --host rpi-zero --with-music --with-voip --with-lvgl-soak
git rev-parse HEAD
yoyopod remote validate --host rpi-zero --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak
yoyopod remote power --host rpi-zero
yoyopod remote service install --host rpi-zero
```

Direct target validation helpers on the Pi:

```bash
yoyopod pi validate deploy
yoyopod pi validate smoke
yoyopod pi validate music
yoyopod pi validate voip
yoyopod pi validate stability
```

If the Pi seems to keep old Python state after a pull, restart the running app process before retesting.

---

## Debug Entry Points

Manual diagnostics are available via `yoyopod pi voip`:

```bash
yoyopod pi voip check
yoyopod pi voip debug
```

Helpful remote checks:

```bash
ssh rpi-zero "ps aux | grep -E '(python|mpv)'"
ssh rpi-zero "free -h"
ssh rpi-zero "pgrep -af mpv"
ssh rpi-zero "killall -9 python"
```

If SIP behavior looks wrong, inspect the Liblinphone shim and backend boundary:

- `src/yoyopod/communication/integrations/liblinphone_binding/native/liblinphone_shim.c`
- `src/yoyopod/communication/integrations/liblinphone_binding/binding.py`
- `src/yoyopod/communication/calling/backend.py`

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

- `src/yoyopod/connectivity/` -> use `src/yoyopod/communication/`
- `src/yoyopod/connectivity/voip_manager.py` -> use `src/yoyopod/communication/calling/manager.py`
- `src/yoyopod/connectivity/voip_backend.py` -> use `src/yoyopod/communication/calling/backend.py`
- `src/yoyopod/connectivity/voip_types.py` -> use `src/yoyopod/communication/models.py`
- `state_machine.py` -> removed; use `src/yoyopod/fsm.py` and `src/yoyopod/coordinators/runtime.py`
- `demo_yoyopod_phase1.py` -> removed
- `tests/test_phase1_state_machine.py` -> replaced by `tests/test_fsm_runtime.py`
- `tests/test_voip_registration.py` -> use `yoyopod pi voip check`
- `tests/test_incoming_call_debug.py` -> use `yoyopod pi voip debug`
- `scripts/pi_remote.py` -> use `yoyopod remote`
- `scripts/pi_smoke.py` -> use `yoyopod pi validate smoke` or the focused `yoyopod pi validate` subcommands
- `scripts/check_voip_registration.py` -> use `yoyopod pi voip check`
- `scripts/debug_incoming_call.py` -> use `yoyopod pi voip debug`
- `scripts/pisugar_power.py` -> use `yoyopod pi power battery`
- `scripts/pisugar_rtc.py` -> use `yoyopod pi power rtc`
- `scripts/lvgl_build.py` -> use `yoyopod build lvgl`
- `scripts/liblinphone_build.py` -> use `yoyopod build liblinphone`
- `scripts/lvgl_soak.py` -> use `yoyopod pi validate lvgl`
- `scripts/lvgl_probe.py` -> removed in 2026-04 CLI polish; use `yoyopod pi validate lvgl`
- `scripts/whisplay_tune.py` -> removed in 2026-04 CLI polish
- `scripts/whisplay_gallery.py` -> removed in 2026-04 CLI polish

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
- Project repository: `https://github.com/moustafattia/YoyoPod_Core`
