# Architecture

```text
yoyopod.py / src/yoyopod/main.py  (entry points)
        |
    YoyoPodApp (app.py) -- thin composition shell
    |- RuntimeBootService (runtime/boot.py)
    |- RuntimeLoopService (runtime/loop.py)
    |- RecoverySupervisor (runtime/recovery.py)
    |- ScreenPowerService (runtime/screen_power.py)
    |- ShutdownLifecycleService (runtime/shutdown.py)
    |- MusicFSM + CallFSM (fsm.py) -- composed playback and call state machines
    |- CoordinatorRuntime (coordinators/runtime.py) -- derived app state
    |- AppContext (app_context.py) -- compatibility wrapper over focused runtime state objects
    |  |- media / power / network / screen / voip / talk / voice
    |- LocalMusicService (audio/local_service.py) -- playlists, recents, shuffle
    |- MpvBackend (audio/music/backend.py)
    |  |- MpvProcess (audio/music/process.py)
    |  `- MpvIpcClient (audio/music/ipc.py) -- mpv JSON IPC
    |- VoIPManager (communication/calling/manager.py)
    |  `- LiblinphoneBackend (communication/calling/backend.py)
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

## Module Boundary Rules

### Entry points and composition

- `yoyopod.py`, `src/yoyopod/main.py`, and `src/yoyopod/app.py` are composition and lifecycle layers.
- Do not turn entrypoint files into feature homes for UI, business rules, or backend-specific logic.
- If `YoyoPodApp` grows, extract focused runtime services instead of adding more feature logic there.
- Treat runtime extraction as incremental work: if a service like `runtime/boot.py` becomes the new blob, split it again instead of calling the cleanup finished.

### Screens and UI

- `src/yoyopod/ui/screens/` owns presentation, user interaction, and screen-local state.
- Screens should not own hardware lifecycle, process supervision, watchdog behavior, or cross-feature orchestration.
- Heavy voice, playback, call, or power policy should live outside screens and be consumed by screens.

### Coordinators

- `src/yoyopod/coordinators/` owns cross-subsystem orchestration.
- Coordinators may translate events into runtime state changes and navigation changes.
- Coordinators should not contain rendering code, hardware-driver code, or long-lived persistence logic.

### Subsystem managers and backends

- `audio/`, `communication/`, `people/`, `power/`, `network/`, and `voice/` own subsystem behavior and backend integration.
- `backend.py` is the low-level I/O or protocol driver (one concrete driver implementation per module family).
- `manager.py` is the domain-owned app-facing facade for that subsystem.
- `runtime.py` is the loop-thread-aware service that owns periodic polling/iteration behavior outside coordinators.
- `coordinator.py` is the app-level orchestrator that joins subsystem managers to FSMs and EventBus.
- Keep backend-specific details behind the subsystem boundary whenever possible.

### Hardware abstraction

- Raw hardware behavior stays behind `ui/display/`, `ui/input/`, or the relevant subsystem backend.
- Keep Pimoroni, Whisplay, GPIO, LVGL, PiSugar, and modem-specific details out of generic UI and orchestration layers.
- Raw LVGL usage should remain confined to `src/yoyopod/ui/lvgl_binding/` and LVGL-specific view code.

### State and models

- Prefer canonical typed models over parallel shape duplication across UI and runtime layers.
- `AppContext` is shared runtime state, not a dumping ground for every new feature field.
- Prefer adding new mutable runtime fields to the focused state objects in `src/yoyopod/runtime_state.py`
  before extending `AppContext` directly.
- Music runtime state should compose with the canonical models in `src/yoyopod/audio/music/models.py`.
- Use `PlaybackQueue` for ordered playback state instead of defining alternate runtime `Track` or
  `Playlist` shapes under `AppContext` or `runtime_state.py`.
- New domain objects should be introduced in clear model modules before being copied into screen-only state.

### Events and threading

- Background callbacks should publish typed events onto `EventBus` or pass through a narrow coordinator-safe boundary.
- Do not mutate UI state directly from background threads.
- Favor typed events and explicit seams over reaching into concrete screen instances.

## Dependency Direction

Prefer this direction of dependency:

- entrypoints -> coordinators / managers / UI wiring
- coordinators -> runtime state + subsystem facades + screen manager
- screens -> display/input abstractions + typed runtime state + narrow feature actions
- managers -> backends / persistence / subprocess control
- backends -> hardware / native bindings / external processes

Avoid the reverse when possible, especially:
- screens importing hardware-specific backends directly
- generic models importing UI code
- subsystem backends depending on concrete screens
- plan docs being treated as the runtime source of truth
