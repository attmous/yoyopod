# Rust UI Host Ownership - Design Spec

## Problem

YoYoPod is moving toward a Rust runtime. The current first migration block is
the UI: display output, physical input, screen ownership, focus, transitions,
and one-button behavior should move to Rust while Python continues to own the
music, call, voice, power, network, and app runtime services.

The existing Rust Whisplay UI code under `workers/ui/rust/` has already proven
the important hardware facts:

- Rust can initialize and flush pixels to the Whisplay display.
- Rust can read the Whisplay button on GPIO 17, active high.
- Rust can own the sidecar UI state machine and emit runtime intents.
- The Pi Zero deploy path must use the GitHub Actions Rust artifact, not a
  target-side Rust build.

The remaining problem is structural: the code is still named and located like a
PoC worker, while the intended direction is production Rust runtime ownership.
If more UI code is added there, the repo will carry the wrong boundary into the
real migration.

## Goal

Promote the Rust UI path into a production Rust UI host shape without moving the
entire app runtime yet.

Rust should become the UI owner:

- display hardware ownership
- input hardware ownership
- screen routing and preemption
- focus state
- transitions
- one-button gesture behavior
- UI rendering
- UI-to-runtime intent emission

Python should remain the app runtime owner for this slice:

- music/mpv service
- VoIP/liblinphone service
- voice/cloud workers
- power/network/location services
- config loading
- process supervision
- app event bus

## Naming

Use **Rust UI Host** as the system name.

The word "sidecar" remains accurate only for the temporary process topology:
Python supervises the Rust UI host while Python still owns the rest of the
runtime. Ownership-wise, Rust is the UI host, not a renderer helper.

The production binary should be named:

```text
yoyopod-ui-host
```

The CI artifact should be named:

```text
yoyopod-ui-host-<sha>
```

## Approved Repository Structure

The top-level `src/` directory becomes the production Rust workspace root. Do
not add an intermediate `src/rust/` layer.

```text
src/
  Cargo.toml
  Cargo.lock
  crates/
    ui-host/
      Cargo.toml
      src/
        lib.rs
        main.rs
        protocol/
        runtime/
        screens/
        input/
        hal/
        render/
        assets/
```

Meaning:

- `src/` is the Rust workspace root.
- `src/crates/ui-host/` is the current Rust UI host crate.
- `src/crates/ui-host/src/` is the normal Cargo crate source directory.
- Future production Rust crates live under `src/crates/`.

The existing `workers/ui/rust/` path should not remain the source of truth. It
may temporarily contain compatibility shims only if needed during a short CI or
deploy transition, but new production Rust sources must live under top-level
`src/`.

## Architecture

```text
Python runtime process
  |- app services: music, call, voice, power, network, config
  |- WorkerSupervisor
  |- RustUiFacade
  |    |- starts/stops yoyopod-ui-host
  |    |- sends runtime snapshots
  |    |- sends tick/backlight/control commands
  |    `- dispatches UI intents back to Python services
  |
  `- no Whisplay display/input/screen ownership when Rust UI is enabled

Rust UI host process
  |- protocol
  |- runtime snapshot model
  |- UI state machine
  |- screen router and stack
  |- one-button input grammar
  |- Whisplay display/input HAL
  |- LVGL renderer backend
  `- health/diagnostics
```

When Rust UI is enabled, Python must not initialize the Python Whisplay display,
Python input manager, Python LVGL backend, or Python `ScreenManager` as active
hardware owners. Python can keep compatibility objects only if they are inert
and do not touch display/input hardware.

## Rust Responsibilities

The Rust UI host owns:

- Whisplay display initialization and cleanup
- Whisplay backlight control
- Whisplay button polling
- one-button debounce, single tap, double tap, and long hold mapping
- persistent UI state
- active screen
- screen stack
- focus index
- runtime-driven preemption such as incoming call, active call, loading, and
  error overlays
- rendering and flushing frames
- health counters and diagnostics
- narrow `ui.intent` events for Python runtime actions

Rust must treat the Python runtime snapshot as facts, not as navigation
commands. Python sends state; Rust decides the UI route.

## Python Responsibilities

Python owns:

- process supervision
- startup and shutdown
- runtime snapshot assembly
- mapping Rust UI intents to existing services
- publishing screen/user-activity events needed by screen power and diagnostics
- fallback to the existing Python UI only when Rust UI is disabled

The Python bridge should be renamed conceptually from `rust_sidecar` to
`rust_host`. A compatibility import can remain briefly if needed for tests or
incremental migration.

## Protocol Direction

Keep newline-delimited JSON for now. It is good enough for the current event
rate and easy to debug over SSH.

Core commands from Python to Rust:

```text
ui.runtime_snapshot
ui.tick
ui.set_backlight
ui.health
ui.shutdown
```

Core events from Rust to Python:

```text
ui.ready
ui.input
ui.intent
ui.screen_changed
ui.health
ui.error
```

Use full runtime snapshots first. Deltas can be added later for hot paths such
as playback position if measurement shows snapshots are too expensive.

## Rendering Direction

Use the existing LVGL visual contract first, but move lifecycle ownership to
Rust.

Current Rust rendering still loads and shuts down the native LVGL shim per
render call. That is acceptable for the PoC but not for the UI host. The UI host
should create a persistent LVGL renderer that:

- initializes once at process start
- owns the active scene lifecycle
- syncs screen-specific view models
- pumps LVGL timers from the Rust UI loop
- flushes to the Rust Whisplay display backend
- fails loudly if the required LVGL shim is unavailable

Framebuffer fallback can remain as a diagnostic renderer, but production
Whisplay UI should use LVGL unless a later measured decision replaces it.

## Migration Slices

### Slice 1: Move And Rename Without Behavior Change

- Move Rust source of truth from `workers/ui/rust/` to
  `src/crates/ui-host/`.
- Add top-level `src/Cargo.toml` workspace.
- Rename the crate and binary to `yoyopod-ui-host`.
- Update CI to build and upload `yoyopod-ui-host-<sha>`.
- Update docs and config defaults to the new binary path.
- Keep runtime behavior identical.

### Slice 2: Python Rust UI Facade

- Add `yoyopod/ui/rust_host/`.
- Start the Rust UI host through the existing worker supervisor.
- Send snapshots and ticks from the main runtime loop.
- Dispatch `ui.intent` events to existing Python services.
- Publish screen changed and user activity events from Rust UI events.

### Slice 3: Exclusive UI Hardware Ownership

- Add a boot branch for Rust UI enabled mode.
- Skip Python Whisplay display/input/LVGL/screen manager initialization in that
  mode.
- Keep Python runtime services fully active.
- Fail loudly if both Python UI and Rust UI attempt to own Whisplay hardware.

### Slice 4: Complete Rust UI Screen Coverage

- Finish the Rust state machine and screen view models for:
  - Hub
  - Listen
  - Playlists
  - Recent tracks
  - Now Playing
  - Ask
  - Talk
  - Contacts
  - Call History
  - Voice Note
  - Incoming Call
  - Outgoing Call
  - In Call
  - Power/Status
  - Loading
  - Error
- Cover one-button behavior per screen with Rust tests.

### Slice 5: Persistent LVGL Host Renderer

- Replace per-render LVGL load/init/shutdown with a persistent renderer.
- Keep raw LVGL behind the Rust render module.
- Add renderer health and frame timing.
- Validate on Whisplay hardware through the CI artifact deploy path.

## CI And Deploy Contract

Rust UI binaries for Pi Zero validation must come from GitHub Actions artifacts.

The target-hardware deploy path is:

1. Commit and push.
2. Wait for the `ui-rust` CI job for the exact commit.
3. Download `yoyopod-ui-host-<sha>`.
4. Copy it to the Pi checkout.
5. Run the Rust UI host on the target.

Do not run `cargo build` on the Pi Zero unless the user explicitly overrides
this rule.

## Testing

Host tests:

- Rust protocol tests.
- Rust input gesture tests.
- Rust UI state transition tests.
- Rust snapshot preemption tests.
- Python facade tests with fake worker supervisor.
- Python config/default-path tests.
- Python boot tests proving Rust UI mode does not initialize Python display or
  input owners.

CI:

```text
cargo test --workspace --locked --features whisplay-hardware
cargo build --release -p yoyopod-ui-host --features whisplay-hardware --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Hardware validation:

- no-touch `ui.tick` loop reports zero input events
- physical button click emits `ui.input`
- one-button navigation changes focus/screen
- rendered orientation is upright
- RGB colors match expected Whisplay output
- incoming call snapshot preempts current screen
- active call snapshot shows in-call screen
- idle state returns out of call screens
- 10-minute navigation/render soak has no crash or visible corruption

## Acceptance Criteria

This design is accepted when:

- production Rust source is under top-level `src/`
- `workers/ui/rust/` is no longer the production source of truth
- the binary is named `yoyopod-ui-host`
- CI builds the Rust UI host artifact from `src/`
- Python can run with Rust as the exclusive UI/display/input owner
- Python runtime services continue to respond to Rust UI intents
- Whisplay hardware validation passes using a CI-built artifact
- Rust code follows idiomatic Rust guidelines, including `rustfmt`, clear
  ownership, explicit error handling, and narrow module boundaries
- production Rust code is written for human readability first: descriptive names,
  small focused units, simple control flow, and no clever abstractions unless
  they remove real complexity

## Non-Goals

- Do not move music/mpv into Rust in this UI slice.
- Do not move VoIP/liblinphone into Rust in this UI slice.
- Do not move power/network/location into Rust in this UI slice.
- Do not introduce Slint or another UI toolkit in this slice.
- Do not support Pimoroni/four-button Rust UI in the first Rust UI host cut.
- Do not build Rust on the Pi Zero.

## Open Decisions Deferred

- Whether future Rust runtime crates should be merged into one binary or split
  into separately supervised processes.
- Whether LVGL remains the long-term Rust renderer after the UI host is stable.
- Whether the protocol moves from JSON lines to a typed binary format after the
  Python runtime migration starts.
