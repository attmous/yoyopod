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

The production entrypoint is `yoyopod.py`, which delegates to `YoyoPodApp` in `yoyopy/app.py`.
`YoyoPodApp` is now a thin composition shell around focused runtime services in
`yoyopy/runtime/`.

This extraction is a first pass, not the end state. `yoyopy/runtime/boot.py` is
still the biggest remaining runtime hotspot and should be the next split target
if more setup logic accumulates there.

## Runtime Topology

```text
yoyopod.py / yoyopy.main
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

- `yoyopy/app.py`: thin runtime shell and compatibility surface
- `yoyopy/main.py`: package entry point
- `yoyopy/fsm.py`: split music and call state models
- `yoyopy/coordinators/runtime.py`: derived app runtime state
- `yoyopy/app_context.py`: shared app state
- `yoyopy/runtime/boot.py`: boot-time composition and manager wiring
- `yoyopy/runtime/loop.py`: coordinator-loop scheduling and queued main-thread work
- `yoyopy/runtime/recovery.py`: backend recovery, power polling, and watchdog supervision
- `yoyopy/runtime/screen_power.py`: screen wake/sleep policy and power overlays
- `yoyopy/runtime/shutdown.py`: shutdown countdowns, hooks, and lifecycle cleanup

### Coordinators

- `yoyopy/coordinators/call.py`: call-flow orchestration
- `yoyopy/coordinators/playback.py`: music-flow orchestration
- `yoyopy/coordinators/power.py`: power and shutdown-related orchestration
- `yoyopy/coordinators/screen.py`: screen refresh and call-screen updates
- `yoyopy/coordinators/runtime.py`: derived runtime state and shared runtime references

### Audio and VoIP

- `yoyopy/audio/local_service.py`: local playlists, shuffle source collection, recent history integration
- `yoyopy/audio/music/backend.py`: `MusicBackend`, `MpvBackend`, `MockMusicBackend`
- `yoyopy/audio/music/process.py`: app-managed mpv process lifecycle
- `yoyopy/audio/music/ipc.py`: low-level mpv JSON IPC client
- `yoyopy/audio/music/models.py`: `Track`, `Playlist`, `PlaybackQueue`, `MusicConfig`
- `yoyopy/audio/volume.py`: shared ALSA and mpv output-volume coordination
- `yoyopy/voip/manager.py`: call, message, and voice-note facade
- `yoyopy/voip/liblinphone_binding/`: native Liblinphone shim and CPython binding
- `config/liblinphone_factory.conf`: repo-managed Liblinphone factory config for media, codec, and network defaults

### Power, Network, and Voice

- `yoyopy/power/`: PiSugar power, RTC, watchdog, and safety policy code
- `yoyopy/network/`: modem backend, PPP process management, GPS, and transport code
- `yoyopy/voice/`: local capture, STT, TTS, and command-matching code

### UI Layer

- `yoyopy/ui/display/`: display HAL and adapters
- `yoyopy/ui/input/`: input HAL, semantic actions, adapters
- `yoyopy/ui/screens/`: screen classes split by feature
- `yoyopy/ui/web_server.py`: simulation browser server

## Display Architecture

`Display` in `yoyopy/ui/display/manager.py` is a facade over the HAL interface in `yoyopy/ui/display/hal.py`.

Supported adapters:

- `PimoroniDisplayAdapter`: 320x240 landscape
- `WhisplayDisplayAdapter`: 240x280 portrait
- `SimulationDisplayAdapter`: browser-rendered portrait simulation

Selection happens in `yoyopy/ui/display/factory.py` using:

1. explicit `display.hardware` config
2. `YOYOPOD_DISPLAY` environment variable
3. auto-detection
4. simulation fallback

## Input Architecture

`InputManager` dispatches semantic actions, not hardware button names.

Core semantic actions:

- navigation: `SELECT`, `BACK`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `MENU`, `HOME`
- playback: `PLAY_PAUSE`, `NEXT_TRACK`, `PREV_TRACK`
- VoIP: `CALL_ANSWER`, `CALL_REJECT`, `CALL_HANGUP`
- PTT: `PTT_PRESS`, `PTT_RELEASE`

Current adapters:

- `FourButtonInputAdapter`: Pimoroni A/B/X/Y mapping
- `PTTInputAdapter`: Whisplay single-button mapping
- `KeyboardInputAdapter`: simulation keyboard controls

## Screen Architecture

`ScreenManager` owns a stack of screen instances and reconnects input handlers when the active screen changes.

Screen groups:

- `yoyopy/ui/screens/navigation/`
- `yoyopy/ui/screens/music/`
- `yoyopy/ui/screens/voip/`

There is still a compatibility bridge in `Screen`:

- semantic handlers like `on_select()` exist
- most concrete screens still implement legacy `on_button_*()` methods
- `Screen` currently forwards semantic actions to those legacy methods

That bridge is intentional but temporary.

## State Coordination

Playback and call orchestration use composed models:

- `MusicFSM` in `yoyopy/fsm.py`
- `CallFSM` in `yoyopy/fsm.py`
- `CallInterruptionPolicy` in `yoyopy/fsm.py`
- `CoordinatorRuntime` in `yoyopy/coordinators/runtime.py`

`CoordinatorRuntime` derives the current application status from those models, including:

- `PLAYING_WITH_VOIP`
- `PAUSED_BY_CALL`
- `CALL_ACTIVE_MUSIC_PAUSED`

Runtime services and coordinators listen to:

- music-backend playback changes
- VoIP registration changes
- VoIP call state changes

and updates:

- screen stack
- music pause/resume behavior
- state machine state

## Event Flows

### Incoming Call

1. `YoyoPodApp` iterates the Liblinphone backend on the coordinator thread
2. the native shim queues typed registration, call, and message events
3. `VoIPManager` translates those into app callbacks
4. `YoyoPodApp` pauses music if needed
5. state transitions to `CALL_INCOMING`
6. `IncomingCallScreen` is pushed

### Music Playback

1. screen action triggers a `MusicBackend` command
2. `MpvBackend` receives push events from mpv over JSON IPC
3. `LocalMusicService` handles local playlist and filesystem browse concerns
4. callbacks refresh `NowPlayingScreen`
5. the derived runtime state stays synchronized with actual playback state

Shared music-domain model ownership lives in `yoyopy/audio/music/models.py`. `Track` is the canonical track shape, `Playlist` is the local-library playlist summary, and `PlaybackQueue` is the runtime ordered queue used when the app needs selected-track state.

### 4G / GPS Bringup

1. `NetworkManager` starts the modem backend and initializes the SIM7600 path
2. successful modem registration publishes typed network events onto the `EventBus`
3. PPP startup publishes connectivity state used by the UI/runtime status
4. GPS queries publish fix or no-fix events consumed by the app context and Setup UI
### Simulation Mode

1. `Display` chooses `SimulationDisplayAdapter`
2. `web_server.py` starts a Flask-SocketIO server
3. browser receives base64 PNG display updates
4. keyboard and web buttons feed `InputManager`

## Raspberry Pi Assumptions

The current code still includes a few environment-specific assumptions:

- Whisplay driver path: `/home/tifo/Whisplay/Driver/WhisPlay.py`
- audio device defaults for Liblinphone and mpv: `ALSA: wm8960-soundcard` / `alsa/default`
- simulation server defaults to port `5000`
- call negotiation on the Pi currently depends on the tracked Liblinphone factory config at `config/liblinphone_factory.conf`

These are known implementation constraints, not architecture goals.

## Source Of Truth

For current behavior, trust these files over older notes or demos:

- `yoyopy/app.py`
- `yoyopy/fsm.py`
- `yoyopy/coordinators/runtime.py`
- `yoyopy/audio/`
- `yoyopy/voip/`
- `yoyopy/ui/display/`
- `yoyopy/ui/input/`
- `yoyopy/ui/screens/`
