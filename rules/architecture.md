# Architecture

yoyopod is Rust-only. The runtime, the workers, and the operator CLI
are all Rust. The Python operator CLI was retired in Round 0 of the
CLI rebuild (`docs/ROADMAP.md`); active code must
not depend on it.

```text
yoyopod_rs/runtime        (yoyopod-runtime: orchestrator, config, state, routing)
    |- yoyopod_rs/protocol (shared NDJSON worker envelope and schema contracts)
    |- yoyopod_rs/ui       (Rust UI host, LVGL scene controllers, Whisplay path)
    |- yoyopod_rs/media    (Rust media host and mpv ownership)
    |- yoyopod_rs/voip     (Rust VoIP host and Liblinphone ownership)
    |- yoyopod_rs/network  (Rust network host, SIM7600/PPP/GPS ownership)
    |- yoyopod_rs/cloud    (Rust cloud host, MQTT telemetry and command transport)
    `- yoyopod_rs/power    (Rust power host and PiSugar state ownership)
```

## Runtime Ownership

- `yoyopod-runtime` is the process owner for app behaviour.
- Runtime domains run as supervised Rust hosts/workers; there are no
  Python integrations.
- The operator CLI in `cli/` builds, deploys, configures, and validates
  the Rust stack from the dev machine. It is orchestration only — it
  must not own runtime state or domain behaviour.
- Target validation should prove the Rust runtime stack works on
  hardware. Do not add new validation gates that bypass the runtime.

## Worker Protocol

- Worker communication uses line-delimited JSON envelopes over stdin/stdout.
- Shared envelope, error, ready, and result handling belongs in the Rust
  protocol/runtime worker boundary, not copied into each host indefinitely.
- Worker stderr is for logs. Worker stdout is protocol-owned.
- Keep messages typed and versioned. Avoid ad hoc strings for cross-process
  contracts.

## UI And Hardware

- Rust UI owns scene state and LVGL rendering decisions for the current app.
- Raw LVGL should stay confined to UI display/binding layers.
- Hardware details for Whisplay, PiSugar, the cellular modem, and the
  audio codec should remain behind their owning Rust host.

## Dependency Direction

Prefer this direction:

- runtime -> protocol + host supervision + config/state routing
- hosts -> protocol + domain-specific hardware/backend crates
- CLI/deploy -> artifacts, config, remote orchestration, and Rust validation
- docs/validation -> current Rust runtime behavior

Avoid the reverse:

- hosts importing runtime orchestration
- CLI validation becoming a substitute runtime
- domain behavior living in docs, compatibility helpers, or CLI-only checks
- historical Python plans being treated as current architecture
