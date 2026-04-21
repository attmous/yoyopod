# YoyoPod System Architecture

**Last updated:** 2026-04-22
**Status:** Current implementation

This document describes the frozen architecture now implemented by the Phase A
rewrite.

## Overview

YoyoPod runs as a single Python application that coordinates:

- display rendering
- semantic input handling
- screen navigation
- mpv-based local music playback
- SIP calling and messaging through Liblinphone
- power management, battery telemetry, and watchdog behavior
- modem networking, PPP connectivity, and GPS queries
- local voice capture, speech-to-text, and spoken feedback
- state transitions between playback and call flows

The repo exposes two equivalent application launch surfaces:

- `python yoyopod.py`
- the installed `yoyopod` console entrypoint from `pyproject.toml`

Both end up in `src/yoyopod/main.py`. That entrypoint configures logging,
writes the PID file, emits the canonical startup marker, and then constructs
`YoyoPodApp` from `src/yoyopod/app.py`.

The frozen end state is:

- `src/yoyopod/app.py`: bootstrap only
- `src/yoyopod/core/application.py`: canonical app object
- `src/yoyopod/core/`: cross-cutting primitives and mechanics
- `src/yoyopod/integrations/`: domain seams
- `src/yoyopod/backends/`: external adapters only
- `src/yoyopod/ui/`: display, input, and screens

`src/yoyopod/runtime/`, `src/yoyopod/coordinators/`, `src/yoyopod/audio/`,
and the legacy domain-facade packages are now gone. The remaining cleanup is
mostly documentation and test-layout polish, not live runtime ownership.

## Startup And Bootstrap Flow

This is the startup sequence that exists on `main` today.

1. Launch enters the `yoyopod.main:main` entrypoint implemented in `src/yoyopod/main.py`.
   - `yoyopod.py` is only a thin launcher.
   - The installed `yoyopod` console script in `pyproject.toml` also targets `yoyopod.main:main`.
2. `main()` configures process-level runtime plumbing before app setup starts.
   - `load_composed_app_settings()` reads `config/app/core.yaml` and `config/device/hardware.yaml` early enough to resolve logging settings.
   - `ConfigManager` later composes domain-owned layers such as `config/audio/music.yaml`, `config/power/backend.yaml`, `config/network/cellular.yaml`, `config/voice/assistant.yaml`, and the communication files into the full runtime model.
   - `configure_logger()` builds the shared `loguru` runtime config and enables console plus file logging.
   - `write_pid_file()` writes the current PID.
   - `log_startup()` emits the startup marker consumed by Pi deploy and remote-validation workflows.
   - `--simulate` is parsed before the app is constructed.
3. `main()` constructs `YoyoPodApp(config_dir="config", simulate=simulate)`.
   - The constructor does not start hardware or backend processes yet.
  - It allocates the typed `Bus`, the shared `MainThreadScheduler`, the core bootstrap service (`RuntimeBootService` from `src/yoyopod/core/bootstrap/`), the canonical main-thread loop (`RuntimeLoopService` from `src/yoyopod/core/loop.py`), the remaining live services (`RuntimeRecoveryService` from `src/yoyopod/core/recovery.py`, `PowerRuntimeService` from `src/yoyopod/integrations/power/service.py`, `ShutdownLifecycleService` from `src/yoyopod/core/shutdown.py`), the canonical display-power helper (`ScreenPowerService` from `src/yoyopod/integrations/display/service.py`), and the long-lived placeholder fields for managers, screens, and shared context.
- `RuntimeRecoveryService` now keeps VoIP/music/network recovery while `yoyopod.integrations.power.service.PowerRuntimeService` owns PiSugar polling and watchdog cadence.
- It also registers app-level event subscriptions on the `Bus` so later boot stages can publish typed events back onto the main thread.
4. `main()` calls `app.setup()`, which delegates to `RuntimeBootService.setup()` in `src/yoyopod/core/bootstrap/`.
5. `RuntimeBootService.setup()` currently executes boot in this order:
   1. `load_configuration()`
      - builds `ConfigManager`
      - loads the typed app, media, network, voice, communication, and people settings
      - opens persistent stores for call history and recent tracks
      - starts the async voice-device catalog refresh
      - resolves screen timeout, brightness, and auto-resume settings
   2. `init_core_components()`
      - creates the `Display` facade using the configured or auto-detected hardware mode
      - treats non-simulated Whisplay as a strict LVGL production path and fails startup if that contract cannot be met
      - initializes the LVGL backend when the selected adapter supports it
      - renders the initial `YoyoPod Starting...` splash
      - creates `AppContext`
      - seeds voice and VoIP-ready status in shared runtime state
      - constructs the canonical music and call-session seams from `yoyopod.integrations.music` and `yoyopod.integrations.call`
      - creates and starts `InputManager`
      - wires the LVGL input bridge when LVGL is active
      - creates `ScreenManager`
   3. `init_managers()`
      - starts `VoIPManager` from typed VoIP config
      - starts `MpvBackend` and wraps it with `LocalMusicService`
      - attaches `OutputVolumeController` and applies the configured startup volume
      - creates `PowerManager`
      - creates `NetworkManager` and starts it only when networking is enabled and the app is not running in simulation mode
   4. `setup_screens()`
      - constructs all screen instances
      - registers them with `ScreenManager`
      - resolves the root route from the active interaction profile
      - pushes `hub` for one-button hardware and `menu` for the standard profile
   5. final runtime wiring
      - builds `AppStateRuntime`, `CallRuntime`, and `MusicRuntime` through `RuntimeHelpersBoot`
      - sets the initial derived UI state
      - registers VoIP and music backend callbacks
      - registers power shutdown hooks
      - polls initial power state
6. If setup fails, `main()` logs the likely missing prerequisites, calls `app.stop()`, returns a non-zero exit code, and still runs the shutdown marker plus PID cleanup in the outer `finally`.
7. If setup succeeds, `main()` installs signal handlers and enters `app.run()`.
   - `SIGTERM` is translated into the same shutdown path as `Ctrl+C`.
   - `SIGUSR1` and `SIGUSR2` request screenshots on Unix targets when those signals exist.
8. `app.run()` delegates to `RuntimeLoopService.run()`, which is the steady-state main-thread loop.
   - It logs a startup status snapshot.
   - It starts the watchdog cadence.
   - Each loop iteration drains queued scheduler tasks first, then typed bus events, pumps LVGL timers and queued input, iterates the Liblinphone backend on the main thread, polls recovery and power services, and refreshes active screens on the configured cadence.
   - The outer loop adapts its next wake based on runtime state: call / recent-input paths stay fast, awake idle relaxes, and screen-off idle can relax further while still honoring the next VoIP, watchdog, power-poll, shutdown, or screen-refresh deadline.
9. Shutdown runs through `app.stop()` and `yoyopod.core.shutdown.ShutdownLifecycleService.stop()`.
   - network, VoIP, music, and input managers are stopped
   - queued main-thread work is drained one last time
   - the display is cleared and cleaned up
   - `main()` emits the shutdown marker and removes the PID file

## Startup Differences Between Hardware And Simulation

- The boot order is the same in both modes: `main()` still configures logging, constructs `YoyoPodApp`, and calls `RuntimeBootService.setup()` from `src/yoyopod/core/bootstrap/`.
- Simulation mode changes adapter selection and input behavior by asking the display and input factories for simulation backends, and `main()` logs the browser-based workflow banner before setup.
- `NetworkManager` is created in both modes, but it is only started when networking is enabled and `simulate` is false.
- The initial root route still depends on the resolved interaction profile, not on a separate dev-only code path.

## Runtime Topology

```text
yoyopod.py / yoyopod.main
  -> YoyoPodApp
     -> RuntimeBootService
     -> RuntimeLoopService
     -> RuntimeRecoveryService
     -> PowerRuntimeService
     -> integrations.display.ScreenPowerService
     -> core.shutdown.ShutdownLifecycleService
     -> MainThreadScheduler
     -> Bus
      -> Display facade
         -> Display factory
            -> PimoroniDisplayAdapter | WhisplayDisplayAdapter | SimulationDisplayAdapter
     -> InputManager
        -> FourButtonInputAdapter | PTTInputAdapter | KeyboardInputAdapter
     -> ScreenManager
        -> navigation screens
        -> music screens
        -> voip screens
     -> music session seam / call-session seam
      -> AppStateRuntime
      -> CallRuntime / MusicRuntime
      -> AppContext
         -> focused runtime state objects (`media`, `power`, `network`, `screen`, `voip`, `talk`, `voice`)
         -> media state composes with canonical music models from `src/yoyopod/backends/music/models.py`
      -> LocalMusicService
      -> MpvBackend
        -> MpvProcess
        -> MpvIpcClient
           -> mpv JSON IPC over Unix socket / named pipe
      -> VoIPManager
         -> LiblinphoneBackend
            -> native Liblinphone shim
      -> PowerManager
         -> PiSugarBackend
         -> PiSugarWatchdog
      -> NetworkManager
         -> Sim7600Backend
         -> PPP process / GPS queries
      -> VoiceService
         -> audio capture backend
         -> Vosk STT backend
         -> espeak-ng TTS backend
```

## Package Structure

### Application Layer

- `src/yoyopod/app.py`: thin bootstrap shell
- `src/yoyopod/main.py`: package entry point
- `src/yoyopod/core/application.py`: canonical scaffold app object
- `src/yoyopod/core/bus.py`, `states.py`, `services.py`, `scheduler.py`: frozen spine primitives
- `src/yoyopod/core/events.py`: universal state-change and cross-cutting app events only
- `src/yoyopod/core/focus.py`, `recovery.py`, `status.py`, `diagnostics/`: cross-cutting core modules
- `src/yoyopod/core/app_state.py`: derived app runtime state
- `src/yoyopod/core/app_context.py`: focused shared runtime state
- `src/yoyopod/core/app_context.py`: `AppContext` plus the focused runtime state objects it owns
- `src/yoyopod/core/bootstrap/`: boot-time composition and manager wiring
- `src/yoyopod/core/loop.py`: main-thread loop scheduling and queued main-thread work
- `src/yoyopod/core/recovery.py`: backend recovery supervision and retry services
- `src/yoyopod/integrations/display/service.py`: screen wake/sleep policy and power overlays
- `src/yoyopod/core/shutdown.py`: shutdown countdowns, hooks, and lifecycle cleanup
- `src/yoyopod/integrations/power/service.py`: power polling and watchdog cadence

### Runtime Ownership

- `src/yoyopod/integrations/call/runtime.py`: call-flow orchestration and screen transitions
- `src/yoyopod/integrations/music/runtime.py`: playback-flow orchestration and now-playing refreshes
- `src/yoyopod/integrations/power/service.py`: power polling, power snapshot application, watchdog cadence, and safety-policy event emission
- `src/yoyopod/ui/screens/manager.py`: screen refresh helpers and call-screen stack updates
- `src/yoyopod/core/app_state.py`: derived runtime state and shared runtime references

### Domains and Backends

- `src/yoyopod/integrations/music/`: canonical music seam, including the transitional `MusicFSM`
- `src/yoyopod/integrations/music/events.py`: music-domain typed events
- `src/yoyopod/integrations/music/fsm.py`: canonical music-session FSM owner during the remaining state-store cutover
- `src/yoyopod/backends/music/`: concrete mpv adapters
- `src/yoyopod/integrations/call/`: canonical public call manager, session FSM/policy, lifecycle tracker, messaging service, models, message store, history, and voice-note seam
- `src/yoyopod/integrations/call/events.py`: call-domain typed events
- `src/yoyopod/backends/voip/`: canonical Liblinphone adapter, protocol types, mock backend, and native shim binding
- `src/yoyopod/integrations/contacts/`: mutable contacts/address-book domain
- `config/communication/integrations/liblinphone_factory.conf`: repo-managed Liblinphone factory config for media, codec, and network defaults

### Power, Network, Voice, and Display

- `src/yoyopod/integrations/power/`: canonical power manager, models, and scaffold integration ownership
- `src/yoyopod/integrations/network/`: canonical network manager, modem models, and scaffold integration ownership
- `src/yoyopod/integrations/network/events.py`: modem / PPP / signal events
- `src/yoyopod/integrations/location/`: canonical GPS/location seam
- `src/yoyopod/integrations/location/events.py`: GPS fix/no-fix events
- `src/yoyopod/integrations/voice/`: canonical voice manager, service alias, and typed voice models
- `src/yoyopod/backends/voice/`: concrete capture, playback, STT, and TTS adapters
- `src/yoyopod/integrations/display/`: canonical display awake/sleep/brightness/timeout seam, including the live screen-power helper

### UI Layer

- `src/yoyopod/ui/display/`: display HAL and adapters
- `src/yoyopod/ui/input/`: input HAL, semantic actions, adapters
- `src/yoyopod/ui/screens/`: screen classes split by feature
- `src/yoyopod/ui/web_server.py`: simulation browser server

## Display Architecture

`Display` in `src/yoyopod/ui/display/manager.py` is a facade over the HAL interface in `src/yoyopod/ui/display/hal.py`.

Supported adapters:

- `PimoroniDisplayAdapter`: 320x240 landscape
- `WhisplayDisplayAdapter`: 240x280 portrait
- `SimulationDisplayAdapter`: browser-rendered portrait simulation

Selection happens in `src/yoyopod/ui/display/factory.py` using:

1. explicit `display.hardware` config
2. `YOYOPOD_DISPLAY` environment variable
3. auto-detection
4. simulation fallback

Whisplay has one extra contract on top of the general selection rules:

- non-simulated Whisplay startup requires `display.whisplay_renderer=lvgl`
- if the Whisplay driver, board init, or LVGL backend is unavailable, startup stops instead of silently degrading to PIL or simulation
- PIL remains a simulation and local debug path, not a supported production Whisplay mode

## Input Architecture

`InputManager` dispatches semantic actions, not hardware button names.

Core semantic actions:

- navigation: `SELECT`, `BACK`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `MENU`, `HOME`
- playback: `PLAY_PAUSE`, `NEXT_TRACK`, `PREV_TRACK`
- communication: `CALL_ANSWER`, `CALL_REJECT`, `CALL_HANGUP`
- PTT: `PTT_PRESS`, `PTT_RELEASE`

Current adapters:

- `FourButtonInputAdapter`: Pimoroni A/B/X/Y mapping
- `PTTInputAdapter`: Whisplay single-button mapping
- `KeyboardInputAdapter`: simulation keyboard controls

## Screen Architecture

`ScreenManager` owns a stack of screen instances and reconnects input handlers when the active screen changes.

Screen groups:

- `src/yoyopod/ui/screens/navigation/`
- `src/yoyopod/ui/screens/music/`
- `src/yoyopod/ui/screens/voip/`

`Screen` now exposes semantic handlers only:

- semantic handlers like `on_select()`, `on_back()`, `on_up()`, and `on_down()` are the screen input contract
- `ScreenManager` dispatches semantic actions directly to those handlers
- legacy `on_button_*()` compatibility methods have been removed

## State Coordination

Playback and call orchestration use composed models:

- `MusicFSM` in `src/yoyopod/integrations/music/fsm.py`
- `CallFSM` in `src/yoyopod/integrations/call/session.py`
- `CallInterruptionPolicy` in `src/yoyopod/integrations/call/session.py`
- `AppStateRuntime` in `src/yoyopod/core/app_state.py`

`AppStateRuntime` derives the current application status from those models, including:

- `PLAYING_WITH_VOIP`
- `PAUSED_BY_CALL`
- `CALL_ACTIVE_MUSIC_PAUSED`

It also retains the small shared derived-state surface needed by runtime services, specifically the base UI state fallback, VoIP readiness, and the latest power snapshot.

Runtime services and coordinators listen to:

- music-backend playback changes
- communication registration changes
- communication call state changes

and updates:

- screen stack
- music pause/resume behavior
- state machine state
- focused runtime state objects through `AppContext`

For a fuller map of the typed runtime event pipeline and coordinator boundaries, see [`docs/RUNTIME_EVENT_FLOW.md`](RUNTIME_EVENT_FLOW.md).

## Event Flows

The canonical current-state event-flow document is
[`RUNTIME_EVENT_FLOW.md`](RUNTIME_EVENT_FLOW.md).

Use that document when you need:

- actual `Bus` dispatch behavior
- coordinator ownership boundaries
- current incoming-call, playback, power, network, and recovery paths
- known seams where runtime ownership is still split or overloaded

Shared music-domain model ownership now lives in `src/yoyopod/backends/music/models.py`.
`Track` is the canonical track shape, `Playlist` is the local-library playlist
summary, and `PlaybackQueue` is the runtime ordered queue used when the app
needs selected-track state.

## Raspberry Pi Assumptions

The current code still includes a few environment-specific assumptions:

- Whisplay driver path: `/home/raouf/Whisplay/Driver/WhisPlay.py`
- MQTT transport: device connects over WebSocket (WSS:443) via Cloudflare tunnel to `mqtt-yoyopod.moraouf.net`; Mosquitto listens on port 8083 with WebSocket protocol
- audio device defaults for Liblinphone and mpv: `ALSA: wm8960-soundcard` / `alsa/default`
- simulation server defaults to port `5000`
- call negotiation on the Pi currently depends on the tracked Liblinphone factory config at `config/communication/integrations/liblinphone_factory.conf`

These are known implementation constraints, not architecture goals.

## Source Of Truth

For current behavior, trust these files over older notes or demos:

- `src/yoyopod/core/application.py`
- `src/yoyopod/core/bus.py`
- `src/yoyopod/core/scheduler.py`
- `src/yoyopod/core/events.py`
- `src/yoyopod/core/app_context.py`
- `src/yoyopod/core/app_context.py`
- `src/yoyopod/core/app_state.py`
- `src/yoyopod/backends/music/`
- `src/yoyopod/integrations/music/`
- `src/yoyopod/backends/voip/`
- `src/yoyopod/integrations/call/`
- `src/yoyopod/integrations/power/`
- `src/yoyopod/integrations/contacts/`
- `src/yoyopod/integrations/network/`
- `src/yoyopod/integrations/voice/`
- `src/yoyopod/core/bootstrap/`
- `src/yoyopod/core/loop.py`
- `src/yoyopod/ui/display/`
- `src/yoyopod/ui/input/`
- `src/yoyopod/ui/screens/`
