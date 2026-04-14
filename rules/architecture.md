# Architecture

```text
yoyopod.py / yoyopy/main.py  (entry points)
        |
    YoyoPodApp (app.py) -- thin composition shell
    |- RuntimeBootService (runtime/boot.py)
    |- RuntimeLoopService (runtime/loop.py)
    |- RecoverySupervisor (runtime/recovery.py)
    |- ScreenPowerService (runtime/screen_power.py)
    |- ShutdownLifecycleService (runtime/shutdown.py)
    |- MusicFSM + CallFSM (fsm.py) -- composed playback and call state machines
    |- CoordinatorRuntime (coordinators/runtime.py) -- derived app state
    |- AppContext (app_context.py) -- shared state
    |- LocalMusicService (audio/local_service.py) -- playlists, recents, shuffle
    |- MpvBackend (audio/music/backend.py)
    |  |- MpvProcess (audio/music/process.py)
    |  `- MpvIpcClient (audio/music/ipc.py) -- mpv JSON IPC
    |- VoIPManager (voip/manager.py)
    |  `- LiblinphoneBackend (voip/backend.py)
    |- Display HAL (ui/display/) -- factory pattern, 3 adapters
    |- Input HAL (ui/input/) -- semantic actions, 3 adapters
    `- ScreenManager (ui/screens/manager.py) -- stack-based navigation
```

## Display HAL

`ui/display/`: `DisplayHAL` interface -> factory -> adapters (pimoroni, whisplay, simulation). The `Display` facade hides hardware-specific rendering details.

## Input HAL

`ui/input/`: semantic actions such as `SELECT`, `BACK`, `UP`, `DOWN`, `PTT_PRESS`, and `PTT_RELEASE`. Adapters include `four_button.py`, `ptt_button.py`, and `keyboard.py`. `InputManager` dispatches actions to the active screen.

## Screen System

`ui/screens/`: base class in `base.py`, stack-based manager in `manager.py`, and feature screens organized under `navigation/`, `music/`, `system/`, and `voip/`.

## State Orchestration

`MusicFSM` and `CallFSM` stay independent, while `CoordinatorRuntime` derives combined runtime states such as `PLAYING_WITH_VOIP`, `PAUSED_BY_CALL`, and `CALL_ACTIVE_MUSIC_PAUSED`. Incoming calls can auto-pause music, and playback can auto-resume after the call ends when enabled.

## Key Patterns

- Ring tone generated via `speaker-test`
- Local music playback runs through an app-managed mpv process instead of an external music daemon
- mpv pushes playback and property-change events over JSON IPC rather than using polling
- Liblinphone backend events are drained on the coordinator thread for UI and state updates
- `EventBus` serializes typed app events on the coordinator thread
