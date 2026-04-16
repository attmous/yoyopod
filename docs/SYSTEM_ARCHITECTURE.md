# YoyoPod System Architecture

**Last updated:** 2026-04-14
**Status:** Current implementation

This document describes the architecture that exists on `main`.

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
`YoyoPodApp` from `src/yoyopod/app.py`. `YoyoPodApp` is now a thin composition
shell around focused runtime services in `src/yoyopod/runtime/`.

This extraction is a first pass, not the end state. `src/yoyopod/runtime/boot.py` is
still the biggest remaining runtime hotspot and should be the next split target
if more setup logic accumulates there.

## Startup And Bootstrap Flow

This is the startup sequence that exists on `main` today.

1. Launch enters the `yoyopod.main:main` entrypoint implemented in `src/yoyopod/main.py`.
   - `yoyopod.py` is only a thin launcher.
   - The installed `yoyopod` console script in `pyproject.toml` also targets `yoyopod.main:main`.
2. `main()` configures process-level runtime plumbing before app setup starts.
   - `load_composed_app_settings()` reads `config/app/core.yaml` and `config/device/hardware.yaml` early enough to resolve logging settings.
   - `ConfigManager` later composes domain-owned layers such as `config/audio/music.yaml`, `config/network/cellular.yaml`, `config/voice/assistant.yaml`, and the communication files into the full runtime model.
   - `configure_logger()` builds the shared `loguru` runtime config and enables console plus file logging.
   - `write_pid_file()` writes the current PID.
   - `log_startup()` emits the startup marker consumed by Pi deploy and remote-validation workflows.
   - `--simulate` is parsed before the app is constructed.
3. `main()` constructs `YoyoPodApp(config_dir="config", simulate=simulate)`.
   - The constructor does not start hardware or backend processes yet.
   - It allocates the typed `EventBus`, runtime services (`RuntimeBootService`, `RuntimeLoopService`, `RecoverySupervisor`, `ScreenPowerService`, `ShutdownLifecycleService`), and the long-lived placeholder fields for managers, screens, and shared context.
   - It also registers app-level event subscriptions on the `EventBus` so later boot stages can publish typed events back onto the coordinator thread.
4. `main()` calls `app.setup()`, which delegates to `RuntimeBootService.setup()`.
5. `RuntimeBootService.setup()` currently executes boot in this order:
   1. `load_configuration()`
      - builds `ConfigManager`
      - loads typed app settings and the compatibility config dict
      - opens persistent stores for call history and recent tracks
      - starts the async voice-device catalog refresh
      - resolves screen timeout, brightness, and auto-resume settings
   2. `init_core_components()`
      - creates the `Display` facade using the configured or auto-detected hardware mode
      - initializes the LVGL backend when the selected adapter supports it
      - renders the initial `YoyoPod Starting...` splash
      - creates `AppContext`
      - seeds voice and VoIP-ready status in shared runtime state
      - constructs `MusicFSM`, `CallFSM`, and `CallInterruptionPolicy`
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
      - builds `CoordinatorRuntime`, `CallCoordinator`, `PlaybackCoordinator`, `ScreenCoordinator`, and `PowerCoordinator`
      - sets the initial derived UI state
      - binds coordinator subscribers to the typed `EventBus`
      - registers VoIP and music backend callbacks
      - registers power shutdown hooks
      - polls initial power state
6. If setup fails, `main()` logs the likely missing prerequisites, calls `app.stop()`, returns a non-zero exit code, and still runs the shutdown marker plus PID cleanup in the outer `finally`.
7. If setup succeeds, `main()` installs signal handlers and enters `app.run()`.
   - `SIGTERM` is translated into the same shutdown path as `Ctrl+C`.
   - `SIGUSR1` and `SIGUSR2` request screenshots on Unix targets when those signals exist.
8. `app.run()` delegates to `RuntimeLoopService.run()`, which is the steady-state coordinator loop.
   - It logs a startup status snapshot.
   - It starts the watchdog cadence.
   - Each loop iteration drains queued main-thread callbacks and typed events, pumps LVGL timers and queued input, iterates the Liblinphone backend on the coordinator thread, polls recovery and power services, and refreshes active screens on the configured cadence.
9. Shutdown runs through `app.stop()` and `ShutdownLifecycleService.stop()`.
   - network, VoIP, music, and input managers are stopped
   - queued main-thread work is drained one last time
   - the display is cleared and cleaned up
   - `main()` emits the shutdown marker and removes the PID file

## Startup Differences Between Hardware And Simulation

- The boot order is the same in both modes: `main()` still configures logging, constructs `YoyoPodApp`, and calls `RuntimeBootService.setup()`.
- Simulation mode changes adapter selection and input behavior by asking the display and input factories for simulation backends, and `main()` logs the browser-based workflow banner before setup.
- `NetworkManager` is created in both modes, but it is only started when networking is enabled and `simulate` is false.
- The initial root route still depends on the resolved interaction profile, not on a separate dev-only code path.

## Runtime Topology

```text
yoyopod.py / yoyopod.main
  -> YoyoPodApp
     -> RuntimeBootService
     -> RuntimeLoopService
     -> RecoverySupervisor
     -> ScreenPowerService
      -> ShutdownLifecycleService
      -> EventBus
      -> Display facade
         -> Display factory
            -> PimoroniDisplayAdapter | WhisplayDisplayAdapter | SimulationDisplayAdapter
     -> InputManager
        -> FourButtonInputAdapter | PTTInputAdapter | KeyboardInputAdapter
     -> ScreenManager
        -> navigation screens
        -> music screens
        -> voip screens
     -> MusicFSM / CallFSM / CallInterruptionPolicy
      -> CoordinatorRuntime
      -> CallCoordinator / PlaybackCoordinator / ScreenCoordinator / PowerCoordinator
      -> AppContext
         -> focused runtime state objects (`media`, `power`, `network`, `screen`, `voip`, `talk`, `voice`)
         -> media state composes with canonical music models from `src/yoyopod/audio/music/models.py`
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

- `src/yoyopod/app.py`: thin runtime shell and compatibility surface
- `src/yoyopod/main.py`: package entry point
- `src/yoyopod/fsm.py`: split music and call state models
- `src/yoyopod/coordinators/runtime.py`: derived app runtime state
- `src/yoyopod/app_context.py`: compatibility wrapper over focused shared runtime state
- `src/yoyopod/runtime_state.py`: focused runtime state objects owned by `AppContext`
- `src/yoyopod/runtime/boot.py`: boot-time composition and manager wiring
- `src/yoyopod/runtime/loop.py`: coordinator-loop scheduling and queued main-thread work
- `src/yoyopod/runtime/recovery.py`: backend recovery, power polling, and watchdog supervision
- `src/yoyopod/runtime/screen_power.py`: screen wake/sleep policy and power overlays
- `src/yoyopod/runtime/shutdown.py`: shutdown countdowns, hooks, and lifecycle cleanup

### Coordinators

- `src/yoyopod/coordinators/call.py`: call-flow orchestration
- `src/yoyopod/coordinators/playback.py`: music-flow orchestration
- `src/yoyopod/coordinators/power.py`: power and shutdown-related orchestration
- `src/yoyopod/coordinators/screen.py`: screen refresh and call-screen updates
- `src/yoyopod/coordinators/runtime.py`: derived runtime state and shared runtime references

### Audio and Communication

- `src/yoyopod/audio/local_service.py`: local playlists, shuffle source collection, recent history integration
- `src/yoyopod/audio/music/backend.py`: `MusicBackend`, `MpvBackend`, `MockMusicBackend`
- `src/yoyopod/audio/music/process.py`: app-managed mpv process lifecycle
- `src/yoyopod/audio/music/ipc.py`: low-level mpv JSON IPC client
- `src/yoyopod/audio/music/models.py`: `Track`, `Playlist`, `PlaybackQueue`, `MusicConfig`
- `src/yoyopod/audio/volume.py`: shared ALSA and mpv output-volume coordination
- `src/yoyopod/communication/__init__.py`: app-facing seam for communication
- `src/yoyopod/communication/calling/`: call facade, backend, and history
- `src/yoyopod/communication/messaging/`: message metadata store
- `src/yoyopod/communication/integrations/liblinphone_binding/`: native Liblinphone shim and CPython binding
- `src/yoyopod/people/`: mutable contacts/address-book domain
- `config/communication/integrations/liblinphone_factory.conf`: repo-managed Liblinphone factory config for media, codec, and network defaults

### Power, Network, and Voice

- `src/yoyopod/power/`: PiSugar power, RTC, watchdog, and safety policy code
- `src/yoyopod/network/`: modem backend, PPP process management, GPS, and transport code
- `src/yoyopod/voice/`: local capture, STT, TTS, and command-matching code

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

- `MusicFSM` in `src/yoyopod/fsm.py`
- `CallFSM` in `src/yoyopod/fsm.py`
- `CallInterruptionPolicy` in `src/yoyopod/fsm.py`
- `CoordinatorRuntime` in `src/yoyopod/coordinators/runtime.py`

`CoordinatorRuntime` derives the current application status from those models, including:

- `PLAYING_WITH_VOIP`
- `PAUSED_BY_CALL`
- `CALL_ACTIVE_MUSIC_PAUSED`

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

- actual `EventBus` dispatch behavior
- coordinator ownership boundaries
- current incoming-call, playback, power, network, and recovery paths
- known seams where runtime ownership is still split or overloaded

Shared music-domain model ownership still lives in `src/yoyopod/audio/music/models.py`.
`Track` is the canonical track shape, `Playlist` is the local-library playlist
summary, and `PlaybackQueue` is the runtime ordered queue used when the app
needs selected-track state.

## Raspberry Pi Assumptions

The current code still includes a few environment-specific assumptions:

- Whisplay driver path: `/home/tifo/Whisplay/Driver/WhisPlay.py`
- audio device defaults for Liblinphone and mpv: `ALSA: wm8960-soundcard` / `alsa/default`
- simulation server defaults to port `5000`
- call negotiation on the Pi currently depends on the tracked Liblinphone factory config at `config/communication/integrations/liblinphone_factory.conf`

These are known implementation constraints, not architecture goals.

## Source Of Truth

For current behavior, trust these files over older notes or demos:

- `src/yoyopod/app.py`
- `src/yoyopod/fsm.py`
- `src/yoyopod/coordinators/runtime.py`
- `src/yoyopod/audio/`
- `src/yoyopod/communication/`
- `src/yoyopod/people/`
- `src/yoyopod/ui/display/`
- `src/yoyopod/ui/input/`
- `src/yoyopod/ui/screens/`
