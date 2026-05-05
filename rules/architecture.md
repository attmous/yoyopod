# Architecture

```text
yoyopod.py / yoyopod/main.py  (entry points)
        |
    YoyoPodApp (core/application.py)
    |- RuntimeBootService (core/bootstrap/)
    |- RuntimeLoopService (core/loop.py)
    |- RuntimeRecoveryService (core/recovery.py)
    |- ShutdownLifecycleService (core/shutdown.py)
    |- ScreenPowerService (integrations/display/service.py)
    |- music session seam + call session seam -- composed playback and call state machines
    |- AppStateRuntime (core/app_state.py) -- shared derived app state only
    |- VoiceRuntimeCoordinator (integrations/voice/runtime.py) -- Ask voice session orchestration
    |- AppContext (core/app_context.py)
    |  |- media / power / network / screen / voip / talk / voice
    |- LocalMusicService (integrations/music/library.py) -- playlists, recents, shuffle
    |- MpvBackend (backends/music/mpv.py)
    |  |- MpvProcess (backends/music/process.py)
    |  `- MpvIpcClient (backends/music/ipc.py) -- mpv JSON IPC
    |- VoIPManager (integrations/call/manager.py) -- thin Python command/snapshot facade
    |  `- RustHostBackend (backends/voip/rust_host.py)
    |     `- yoyopod_rs/voip -> yoyopod_rs/liblinphone-shim -> Liblinphone
    |- Display HAL (ui/display/) -- LVGL-backed Whisplay, Pimoroni, and simulation adapters
    |- Input HAL (ui/input/) -- four-button Pimoroni, one-button Whisplay, and simulation input
    `- ScreenManager (ui/screens/manager.py) -- stack-based navigation
```

## Display HAL

`ui/display/`: `DisplayHAL` interface -> factory -> LVGL-backed adapters for Whisplay, Pimoroni, and simulation. The `Display` facade hides hardware-specific rendering details.

## Input HAL

`ui/input/`: semantic actions such as `SELECT`, `BACK`, `UP`, `DOWN`, `PTT_PRESS`, and `PTT_RELEASE`. The live runtime supports the Whisplay single-button path, the Pimoroni four-button path, and simulation keyboard/browser input, all dispatching semantic actions through `InputManager`.

## Screen System

`ui/screens/`: base class in `base.py`, stack-based manager in `manager.py`, and feature screens organized under `navigation/`, `music/`, `system/`, and `voip/`.

## State Orchestration

`MusicFSM` (from `integrations/music/fsm.py`) and `CallFSM` (from `integrations/call/session.py`) stay independent, while `AppStateRuntime` (from `core/app_state.py`) derives combined runtime states such as `PLAYING_WITH_VOIP`, `PAUSED_BY_CALL`, and `CALL_ACTIVE_MUSIC_PAUSED`. It should stay a small derived-state object, not a grab bag for screen, backend, config, or context references. Incoming calls can auto-pause music, and playback can auto-resume after the call ends when enabled.

## Key Patterns

- Ring tone generated via `speaker-test`
- Local music playback runs through an app-managed mpv process instead of an external music daemon
- mpv pushes playback and property-change events over JSON IPC rather than using polling
- Rust VoIP runtime snapshots are projected onto the Python app on the main thread
- `Bus` serializes typed app events on the main thread

## Module Boundary Rules

### Entry points and composition

- `yoyopod.py` is a thin launcher and `yoyopod/main.py` is the process entrypoint and bootstrap plumbing; `yoyopod/app.py` is a thin compatibility re-export of `YoyoPodApp` (real composition lives in `yoyopod/core/application.py` and `yoyopod/core/bootstrap/`).
- Do not turn entrypoint files into feature homes for UI, business rules, or backend-specific logic.
- If `YoyoPodApp` grows, extract focused runtime services instead of adding more feature logic there.
- Treat runtime extraction as incremental work: if a service like `runtime/boot.py` becomes the new blob, split it again instead of calling the cleanup finished.

### Screens and UI

- `yoyopod/ui/screens/` owns presentation, user interaction, and screen-local state.
- Screens should not own hardware lifecycle, process supervision, watchdog behavior, or cross-feature orchestration.
- Heavy voice, playback, call, or power policy should live outside screens and be consumed by screens.

### Orchestration

- Shared derived state and runtime references live in `yoyopod/core/app_state.py`.
- Cross-domain coordination lives with the owning domain seam:
  - `yoyopod/integrations/call/runtime.py`
  - `yoyopod/integrations/music/runtime.py`
  - `yoyopod/integrations/power/service.py`
  - `yoyopod/integrations/voice/runtime.py`
  - `yoyopod/ui/screens/manager.py`
- Orchestration code may translate events into runtime state changes and navigation changes.
- Orchestration code should not contain rendering code, hardware-driver code, or long-lived persistence logic.

### Subsystem managers and backends

- `yoyopod/integrations/` owns domain behavior and app-facing facades.
- `yoyopod/backends/` owns concrete I/O, process, hardware, and protocol adapters.
- `backend.py` is the low-level I/O or protocol driver (one concrete driver implementation per module family).
- `manager.py` is the domain-owned app-facing facade for that subsystem.
- Keep backend-specific details behind the subsystem boundary whenever possible.

### Hardware abstraction

- Raw hardware behavior stays behind `ui/display/`, `ui/input/`, or the relevant subsystem backend.
- Keep Whisplay, GPIO, LVGL, PiSugar, and modem-specific details out of generic UI and orchestration layers.
- Raw LVGL usage should remain confined to `yoyopod/ui/lvgl_binding/` and LVGL-specific view code.

### State and models

- Prefer canonical typed models over parallel shape duplication across UI and runtime layers.
- `AppContext` is shared runtime state, not a dumping ground for every new feature field.
- Prefer adding new mutable runtime fields to the focused state objects in `yoyopod/core/app_context.py`
  before extending `AppContext` directly.
- Music runtime state should compose with the canonical models in `yoyopod/backends/music/models.py`.
- Use `PlaybackQueue` for ordered playback state instead of defining alternate runtime `Track` or
  `Playlist` shapes under `AppContext` or `core/app_context.py`.
- New domain objects should be introduced in clear model modules before being copied into screen-only state.

### Events and threading

- Background callbacks should schedule main-thread work through `MainThreadScheduler`.
- Only main-thread code should publish typed events onto `Bus`.
- Do not mutate UI state directly from background threads.
- Favor typed events and explicit seams over reaching into concrete screen instances.
- `yoyopod/core/events.py` owns only cross-cutting app events.
- Domain events belong to their owning integration packages and should not be
  re-exported through `yoyopod.core`.
- Domain-specific FSM/session types belong to their owning integration packages and should not be
  re-exported through `yoyopod.core`.

## Dependency Direction

Prefer this direction of dependency:

- entrypoints -> core application / integrations / UI wiring
- core application -> integrations / backends / UI
- integrations -> core + backends
- screens -> display/input abstractions + typed runtime state + narrow feature actions
- managers -> backends / persistence / subprocess control
- backends -> hardware / native bindings / external processes

Avoid the reverse when possible, especially:
- screens importing hardware-specific backends directly
- generic models importing UI code
- subsystem backends depending on concrete screens
- plan docs being treated as the runtime source of truth
