# Rust VoIP Host - Design Spec

## Problem

YoYoPod is moving the runtime toward Rust. The UI host is now the first
production Rust ownership boundary under the top-level `src/` workspace. The
next candidate is VoIP because the current call stack already has a clean
backend seam and an opt-in sidecar-shaped path:

- Python `VoIPManager` owns the app-facing facade.
- Python `CallRuntime` owns call/music coordination, call screens, history, and
  registration state propagation.
- `LiblinphoneBackend` owns the native liblinphone shim through cffi.
- `SupervisorBackedBackend` proves a process boundary can sit behind the
  existing `VoIPBackend` contract.

The current sidecar path is still Python-owned. It isolates some liblinphone
behavior from the supervisor process, but it does not move production runtime
ownership toward Rust and it still pays for another Python process.

## Goal

Add a production-shaped Rust VoIP host that owns liblinphone backend execution
while the Python app remains the runtime supervisor for this slice.

Rust owns:

- liblinphone shim loading
- liblinphone init/start/stop/shutdown
- SIP registration command execution
- call commands: dial, answer, reject, hangup, mute, unmute
- native iterate cadence
- native event draining
- translation from native shim events into protocol events
- backend crash/degraded reporting

Python keeps:

- config loading
- `VoIPManager`
- `CallRuntime`
- call/music interruption policy
- contacts and caller display-name lookup
- call history
- UI state and Rust UI snapshot generation
- app bus and scheduler ownership
- message store and voice-note runtime for this first slice

The first implementation slice is calls only. Text messaging and voice notes are
deferred until registration and call control are stable on hardware.

## Naming

Use **Rust VoIP Host** as the system name.

The production binary should be named:

```text
yoyopod-voip-host
```

The GitHub Actions artifact should be named:

```text
yoyopod-voip-host-<sha>
```

The Python adapter should be named around ownership rather than process shape:

```text
yoyopod/backends/voip/rust_host.py
```

The older Python sidecar can remain available during migration, but new Rust
VoIP work should not extend the old multiprocessing/msgpack sidecar protocol
unless needed for compatibility tests.

## Repository Structure

Production Rust sources stay under the top-level `src/` workspace.

```text
src/
  Cargo.toml
  Cargo.lock
  crates/
    ui-host/
    voip-host/
      Cargo.toml
      src/
        main.rs
        protocol.rs
        config.rs
        host.rs
        shim.rs
        events.rs
        calls.rs
```

If both UI and VoIP need the same worker envelope helpers, add a small shared
crate:

```text
src/crates/worker-protocol/
```

Do not add a `src/rust/` intermediate layer.

## Architecture

```text
Python runtime process
  |- VoIPManager
  |- RustHostBackend implements VoIPBackend
  |- WorkerSupervisor domain "voip"
  |- CallRuntime and app bus
  `- Rust UI Host receives call state through normal runtime snapshots

Rust VoIP host process
  |- NDJSON worker protocol
  |- command handler
  |- liblinphone shim loader
  |- native iterate loop
  |- event translator
  `- health/degraded reporting
```

Python continues to call the existing `VoIPBackend` methods:

- `start`
- `stop`
- `make_call`
- `answer_call`
- `reject_call`
- `hangup`
- `mute`
- `unmute`
- `on_event`

`RustHostBackend` translates those methods into worker commands and translates
worker events back into the existing Python `VoIPEvent` dataclasses. The rest of
the Python runtime should not know whether liblinphone is in-process, Python
sidecar-backed, or Rust-host-backed.

## Protocol

Use the existing worker-supervisor NDJSON envelope style, aligned with the Rust
UI Host and Go voice worker shape.

Command examples:

```text
voip.configure
voip.register
voip.unregister
voip.dial
voip.answer
voip.reject
voip.hangup
voip.set_mute
voip.health
voip.shutdown
```

Event examples:

```text
voip.ready
voip.registration_changed
voip.incoming_call
voip.call_state_changed
voip.backend_stopped
voip.health
voip.error
```

The first slice should not expose text or voice-note commands. If the Python
adapter receives `send_text_message`, `start_voice_note_recording`, or
`send_voice_note` while Rust-host mode is enabled, it should fail cleanly and
surface unsupported behavior rather than silently falling back to another
backend in the same runtime.

## Native Binding Strategy

Use the existing C liblinphone shim first. Rust should dynamically load the same
shared library that Python currently loads:

```text
libyoyopod_liblinphone_shim.so
```

Resolution order:

1. `YOYOPOD_LIBLINPHONE_SHIM_PATH`
2. repo runtime path under `yoyopod/backends/voip/shim_native/build/`
3. packaged slot path once prod slots include the Rust host

This keeps the Rust slice focused on process ownership and typed translation,
not on replacing the native liblinphone C boundary. Direct Rust bindings to
liblinphone can be considered only after the Rust host is stable.

## Runtime Ownership

The Rust host owns the liblinphone iterate cadence. Python should not call
`iterate()` for this backend.

`RustHostBackend.iterate()` should return `0` and exist only to satisfy the
current `VoIPBackend` protocol. Timing and health should come from worker
events, not from Python polling native liblinphone directly.

Startup flow:

1. Python reads `VoIPConfig`.
2. Python registers worker domain `voip`.
3. Python starts `yoyopod-voip-host`.
4. Rust emits `voip.ready`.
5. Python sends `voip.configure`.
6. Python sends `voip.register`.
7. Rust emits registration events.

Shutdown flow:

1. Python sends `voip.unregister` or `voip.shutdown`.
2. Rust stops liblinphone and releases the shim.
3. Worker supervisor stops the process with a bounded grace period.

## Configuration

Keep Rust VoIP host opt-in for the first slice.

Suggested activation:

```text
YOYOPOD_RUST_VOIP_HOST=1
```

If both the old Python VoIP sidecar flag and the Rust VoIP host flag are set,
boot should fail fast with a clear configuration error. Running two VoIP owners
in one app process is not supported.

Longer term, replace separate booleans with one explicit backend selector:

```text
voip.backend = "in_process" | "python_sidecar" | "rust_host"
```

That selector does not need to land in the first implementation slice if an env
flag is enough for hardware validation.

## Audio

For this slice, Rust passes through the configured liblinphone device IDs:

- playback device
- ringer device
- capture device
- media device
- mic gain
- output volume

The current ALSA capture tuning lives in Python `LiblinphoneBackend`, not in
the C shim itself. Rust-host mode must preserve that behavior explicitly before
hardware validation. The preferred first step is to extract the existing tuning
logic into a small shared Python helper that both in-process liblinphone and
Rust-host mode can call before registration. Rust should not invent a separate
ALSA policy layer.

Moving mixer ownership behind a shared app audio facade remains a separate
architecture task.

## CI And Deploy

Rust binaries for Pi validation must come from GitHub Actions artifacts for the
exact commit being tested.

Required CI additions:

- `cargo fmt --manifest-path yoyopod_rs/Cargo.toml`
- `cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked`
- `cargo build --release -p yoyopod-voip-host --locked`
- upload `yoyopod-voip-host-<sha>`

The hardware deploy path is:

1. Commit and push.
2. Wait for the Rust CI job for the exact commit.
3. Download `yoyopod-voip-host-<sha>`.
4. Copy it to the Pi dev checkout.
5. Start the Python app with Rust VoIP host mode enabled.

Do not build `yoyopod-voip-host` on the Raspberry Pi Zero 2W unless the user
explicitly overrides this rule.

## Testing

Rust tests:

- protocol decode/encode
- command validation
- config mapping
- native event translation
- call-id tracking
- unsupported messaging command behavior
- backend stopped/error event behavior

Python tests:

- `RustHostBackend` implements the `VoIPBackend` contract
- startup sends configure/register after ready
- worker registration errors mark VoIP unavailable
- registration/call worker events become existing Python `VoIPEvent` dataclasses
- dial/answer/reject/hangup/mute/unmute send correct worker commands
- `iterate()` is a no-op for Rust-host mode
- old Python sidecar flag and Rust host flag conflict clearly

Hardware validation:

- Rust host starts from CI artifact on `rpi-zero`
- Rust host loads the deployed liblinphone shim
- SIP registration reaches `ok`
- outgoing call can be dialed and hung up
- incoming call emits incoming-call and call-state events
- answer/reject/hangup behave through the existing Python call services
- UI still updates through normal runtime snapshots
- service shutdown releases liblinphone cleanly

## Acceptance Criteria

This design is accepted when:

- production Rust VoIP source lives under top-level `src/crates/voip-host/`
- the binary is named `yoyopod-voip-host`
- Rust owns liblinphone lifecycle and iterate cadence in Rust-host mode
- Python `VoIPManager` and `CallRuntime` remain the app-facing runtime owners
- the Python adapter implements the existing `VoIPBackend` contract
- call control works through dial, answer, reject, hangup, mute, and unmute
- messaging and voice notes fail explicitly as unsupported in the first slice
- CI builds and uploads an ARM64 Rust VoIP host artifact
- hardware validation uses the CI-built artifact, not a target-side Rust build
- code follows clean Rust and Python guidelines: small modules, readable names,
  explicit errors, narrow ownership, `rustfmt`, Black, ruff, and mypy gates

## Non-Goals

- Do not move `VoIPManager` into Rust in the first VoIP slice.
- Do not move `CallRuntime` or call/music interruption policy into Rust.
- Do not move contacts, call history, or UI call screens into Rust.
- Do not implement text messaging or voice notes in the first Rust VoIP slice.
- Do not replace the C liblinphone shim with direct liblinphone Rust bindings.
- Do not build Rust binaries on the Pi Zero 2W.

## Migration Slices

### Slice 1: Rust Host Skeleton

- Add `src/crates/voip-host/`.
- Add the NDJSON worker protocol.
- Add `voip.ready`, `voip.health`, and graceful shutdown.
- Build and upload the CI artifact.

### Slice 2: Shim Binding And Registration

- Dynamically load the existing liblinphone shim.
- Map `VoIPConfig` into the Rust host config.
- Implement configure/register/unregister.
- Emit registration state events.

### Slice 3: Call Control

- Implement dial/answer/reject/hangup/mute/unmute.
- Translate native incoming-call and call-state events.
- Track active call id in Rust.
- Translate backend stopped/errors into Python-compatible events.

### Slice 4: Python Runtime Wiring

- Add `RustHostBackend`.
- Add opt-in boot selection.
- Route worker events into existing `VoIPEvent` callbacks.
- Add tests proving the rest of the call runtime is backend-agnostic.

### Slice 5: Hardware Validation

- Deploy the CI artifact to `rpi-zero`.
- Validate registration, outgoing call, incoming call, answer, reject, hangup,
  mute, and clean shutdown.
- Capture logs and document exact provenance.

## Deferred Decisions

- Whether text messaging and voice notes should move into the Rust VoIP host in
  the next slice or wait until the broader Rust runtime owns message storage.
- Whether the old Python VoIP sidecar should be deleted immediately after Rust
  host validation or kept for one release as fallback.
- Whether a shared Rust `worker-protocol` crate should be created before or
  after the first VoIP host skeleton.
- Whether the long-term runtime is one Rust binary with internal services or
  multiple Rust hosts supervised during the migration.
