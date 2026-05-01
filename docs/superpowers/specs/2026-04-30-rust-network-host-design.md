# Rust Network Host - Design Spec

## Problem

YoYoPod's network domain is still Python-owned end to end. The current
`NetworkManager` in
`yoyopod/integrations/network/manager.py` opens the modem, runs modem
initialization, starts and stops PPP, queries GPS, owns reconnect behavior, and
publishes Python-defined network events.

That leaves the Python supervisor process holding exactly the hardware-facing
network responsibilities we want to move out of it:

- serial and modem I/O
- AT command execution and parsing
- PPP process lifecycle
- GPS queries and fix caching
- reconnect and recovery behavior
- canonical network state ownership

The current design doc for a Python network worker solves isolation, but it
still leaves the network domain conceptually Python-owned. That is not the
target anymore.

The approved target is a full Rust ownership cut:

- Rust becomes the canonical owner of the cellular and GPS domain.
- Python becomes a thin runtime bridge that supervises the worker and consumes a
  Rust-defined snapshot.
- There are no Python runtime fallbacks for network ownership after this
  migration lands.

## Goal

Add a production Rust network host that owns the full network domain:

- config loading
- modem serial transport
- SIM7600 AT command execution
- PPP bring-up, monitoring, and teardown
- GPS queries and fix state
- reconnect and backoff policy
- degraded and recovery state
- canonical network snapshot and protocol vocabulary

Python keeps only:

- worker supervision
- process lifecycle integration during boot and shutdown
- snapshot projection into `AppContext` and Python UI consumers
- forwarding a very small command surface to the worker

This is a one-PR full-domain migration. The Python in-process network runtime
stops being a supported runtime path.

## Non-Goals

- Do not keep `NetworkManager` as a compatibility runtime owner.
- Do not keep Python-owned reconnect or recovery fallback paths.
- Do not preserve the current Python network event/model vocabulary as the
  canonical domain contract.
- Do not leave Python AT, PPP, or GPS implementations in the live runtime path.
- Do not move Wi-Fi management into this migration.
- Do not move cloud MQTT ownership into this migration.
- Do not move the whole Python supervisor into Rust.
- Do not build Rust network artifacts on the Pi Zero 2W; use CI artifacts for
  hardware validation.

## Target Ownership Split

### Rust owns

- loading network config from the existing config topology
- owning the modem serial ports
- AT transport and parsing
- SIM readiness and network registration flow
- PPP subprocess execution and health checks
- GPS enable/query/fix state
- reconnect attempts and bounded backoff
- degraded state and recovery status
- canonical network lifecycle and snapshot state machine
- worker protocol vocabulary for the network domain

### Python owns

- starting and stopping the Rust worker process
- passing the config root path to the worker at process start
- caching the latest Rust snapshot
- projecting the Rust snapshot into `AppContext`
- exposing a thin app-facing facade and minimal commands

Python does not own network policy anymore. It consumes Rust-owned facts.

## Naming

Use **Rust Network Host** as the system name.

The production worker binary should be:

```text
yoyopod-network-host
```

The GitHub Actions artifact should be:

```text
yoyopod-network-host-<sha>
```

The worker path environment override should be:

```text
YOYOPOD_RUST_NETWORK_HOST_WORKER
```

The Python adapter should be named by ownership, not by the old manager shape.
Recommended names:

- Python facade module: `yoyopod/integrations/network/rust_host.py`
- Python facade type: `RustNetworkFacade`
- app property: `app.network_runtime`

The old `app.network_manager` and `NetworkManager` naming should be retired from
the runtime path to make the ownership change explicit.

## Architecture

```text
Python supervisor process
  |- WorkerSupervisor domain "network"
  |- RustNetworkFacade
  |- AppContext projection
  `- UI/status consumers read the projected Rust snapshot

Rust network host process
  |- config loader
  |- NDJSON protocol
  |- serial transport
  |- AT command layer
  |- SIM7600 modem controller
  |- PPP controller
  |- GPS controller
  |- recovery/backoff state machine
  `- canonical network snapshot
```

The important boundary is that Python no longer owns a live modem backend. It
owns only a worker-backed projection of Rust state.

## Repository Structure

Add a new Rust crate under the existing `yoyopod_rs/` workspace:

```text
yoyopod_rs/
  network-host/
    Cargo.toml
    src/
      main.rs
      worker.rs
      protocol.rs
      config.rs
      snapshot.rs
      runtime.rs
      transport.rs
      at.rs
      modem.rs
      ppp.rs
      gps.rs
    tests/
      protocol.rs
      runtime_snapshot.rs
      lifecycle.rs
      ppp.rs
      gps.rs
      config.rs
      support/
        mod.rs
```

Recommended Rust module responsibilities:

- `config.rs`
  Load the existing network config and environment overrides.
- `protocol.rs`
  Define NDJSON envelopes and snapshot serialization.
- `snapshot.rs`
  Define the canonical Rust-owned network snapshot types.
- `runtime.rs`
  Own the lifecycle state machine, recovery, and backoff.
- `transport.rs`
  Own serial port access.
- `at.rs`
  Own AT command formatting and response parsing.
- `modem.rs`
  Own SIM7600 bring-up, registration, and reset behavior.
- `ppp.rs`
  Own `pppd` spawning, monitoring, and teardown.
- `gps.rs`
  Own GPS enable/query/fix parsing.
- `worker.rs`
  Own stdio command handling and snapshot emission.

The crate should follow the same general shape as the existing Rust hosts:
focused runtime modules under `src/` and crate-level integration coverage under
`tests/`.

## Config Ownership

Rust loads config itself. Python does not send a typed `network.configure`
payload.

To keep deployment topology stable, Python may pass only the config root path as
process startup context, for example via `--config-dir` or an environment
variable, but parsing and ownership stay in Rust.

The Rust host should read the same effective settings that Python reads today
from `yoyopod/config/models/network.py`, including:

- `enabled`
- `serial_port`
- `ppp_port`
- `baud_rate`
- `apn`
- `pin`
- `gps_enabled`
- `ppp_timeout`

If the config is invalid, the worker should emit degraded state with a clear
error code instead of relying on Python validation logic.

## Canonical Rust Snapshot

Rust defines the canonical network snapshot and Python treats it as the source
of truth.

The snapshot should include:

- config state
  - `enabled`
  - `gps_enabled`
  - `config_dir`
- lifecycle state
  - `off`
  - `probing`
  - `ready`
  - `registering`
  - `registered`
  - `ppp_starting`
  - `online`
  - `ppp_stopping`
  - `recovering`
  - `degraded`
- modem and registration facts
  - SIM ready
  - carrier
  - radio/network type
  - registered
- signal facts
  - raw CSQ
  - bars
- PPP facts
  - up/down
  - interface name
  - worker-owned process id when present
  - whether PPP owns the default route
  - last PPP failure reason
- GPS facts
  - GPS enabled
  - has fix
  - coordinates
  - altitude
  - speed
  - timestamp
  - last query outcome
- recovery facts
  - recovering
  - retryable
  - reconnect attempt count
  - next retry deadline
- degraded facts
  - error code
  - error message
- timestamps
  - last updated time

Python consumers should not reconstruct this state from smaller domain events.

## Protocol

Use the existing NDJSON worker-supervisor envelope style already used by the
Rust UI host and Rust VoIP host.

The command surface should stay intentionally small:

```text
network.health
network.query_gps
network.reset_modem
network.shutdown
```

Rust should automatically own bring-up and recovery after startup. Python should
not send `network.start`, `network.stop`, `network.reconnect`, or other
lifecycle-policy commands from the old design.

Worker messages should be:

```text
network.ready
network.snapshot
network.health
network.error
network.stopped
```

`network.snapshot` is the primary domain message. It should be emitted:

- once after successful worker initialization
- whenever lifecycle state changes
- whenever modem, PPP, signal, or GPS facts change materially
- whenever degraded or recovery status changes
- after command effects such as `network.query_gps` or `network.reset_modem`

`network.error` is for explicit command failures or worker-level faults that
need immediate visibility, but Python still treats the snapshot as the
authoritative state view.

## Python Runtime Surface

Python should replace the current manager-style service with a thin
worker-backed facade.

Recommended facade responsibilities:

- register and start the `network` worker domain
- cache the latest Rust snapshot
- expose `snapshot()`
- expose `query_gps()`
- expose `reset_modem()`
- expose `is_available()`
- project the snapshot into `AppContext`

Recommended facade non-responsibilities:

- no serial or modem access
- no PPP process control
- no reconnect policy
- no Python-defined canonical network models
- no expansion of Rust state back into the old fine-grained network event set

If Python consumers need a wake-up signal, one coarse event such as
`NetworkSnapshotChangedEvent` is acceptable. Python should not republish the old
`NetworkPppUpEvent`, `NetworkSignalUpdateEvent`, and related typed event family
as the canonical network API.

## App Integration

The runtime-facing Python seams should change as follows:

- `yoyopod/core/bootstrap/managers_boot.py`
  - boot `RustNetworkFacade` instead of the in-process `NetworkManager`
- `yoyopod/core/application.py`
  - rename `network_manager` to `network_runtime`
- `yoyopod/core/recovery.py`
  - remove Python-owned network recovery attempts
- `yoyopod/core/shutdown.py`
  - stop the worker-backed runtime facade instead of an in-process manager
- `yoyopod/ui/screens/system/power_viewmodel.py`
  - read the Rust-backed snapshot instead of `modem_state`
- `yoyopod/ui/screens/system/power_screen.py`
  - trigger `query_gps()` through the thin Rust-backed facade

The existing `NetworkEventHandler` should either collapse into direct snapshot
projection or be deleted if the facade updates `AppContext` directly.

## Runtime Startup And Shutdown

Startup flow should be:

1. Python boot registers the `network` worker domain.
2. Python starts `yoyopod-network-host`.
3. Rust loads config from the passed config root and environment.
4. Rust emits `network.ready`.
5. Rust begins bring-up automatically when networking is enabled.
6. Rust emits `network.snapshot` as state evolves.
7. Python caches the snapshot and projects it into app state.

Shutdown flow should be:

1. Python sends `network.shutdown`.
2. Rust stops polling, tears down PPP when active, closes modem resources, and
   exits.
3. Rust emits final `network.stopped` and/or final `network.snapshot`.
4. Python enforces worker terminate/kill through `WorkerSupervisor` if graceful
   exit does not complete in time.

## Low-Level Rust Port Scope

This migration is a full network-domain port, not only a host wrapper.

That means the live runtime path should no longer depend on:

- `yoyopod/backends/network/transport.py`
- `yoyopod/backends/network/at_commands.py`
- `yoyopod/backends/network/modem.py`
- `yoyopod/backends/network/ppp.py`
- Python-owned GPS runtime logic in the live network path

Those Python files can remain temporarily for test fixtures or migration
reference while the PR is in flight, but they should not remain as supported
production runtime owners after the cut lands.

The same applies to the current in-process integration ownership in:

- `yoyopod/integrations/network/manager.py`
- `yoyopod/integrations/network/handlers.py`
- `yoyopod/integrations/network/events.py`
- `yoyopod/integrations/network/models.py`

After this migration, those files should either be rewritten around the
Rust-backed snapshot facade or retired from the runtime path.

## Diagnostics And CLI

Any on-device network diagnostics should move onto the Rust-owned path too.

The current Python CLI network helpers in `yoyopod_cli/pi/network.py` should
stop constructing Python modem backends directly. They should instead:

- query the Rust network worker through a diagnostic wrapper, or
- launch the Rust host in a controlled diagnostic mode that uses the same Rust
  network implementation

The goal is to avoid leaving a second Python-owned network implementation alive
in operational tooling.

## Testing

Testing should cover both Rust ownership and thin Python projection.

Rust tests should cover:

- config loading
- AT response parsing
- modem lifecycle transitions
- PPP spawn, wait, teardown, and failure mapping
- GPS query and no-fix behavior
- recovery and backoff transitions
- snapshot serialization
- command handling and command error cases

Python tests should cover:

- worker-backed facade startup and shutdown
- snapshot caching and `AppContext` projection
- boot wiring for the new `network_runtime` property
- power/setup screen consumption of the Rust-backed snapshot
- removal of Python-owned network recovery behavior

Hardware validation should cover:

- worker bring-up on Pi Zero 2W with the real modem
- PPP online transition
- degraded reporting when serial or SIM access fails
- GPS query and no-fix handling
- reset and recovery behavior
- shutdown cleanup

As with the Rust UI host and Rust VoIP host, hardware validation should use the
CI artifact for the exact commit under test.

## Risks

The main risks are:

- PPP privilege and route-handling differences between the Python and Rust
  implementations
- incorrect assumptions about which modem ports can safely serve AT, PPP, and
  GPS simultaneously
- shutdown edge cases that leave PPP or serial state dirty on hardware
- snapshot churn that is too noisy if every low-level change emits a full
  update without coalescing

These are implementation and validation risks, not reasons to keep a Python
fallback.
