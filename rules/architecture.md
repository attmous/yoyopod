# Architecture

YoYoPod is Rust-first. Treat the Rust runtime workspace as the app owner and the
Python package as CLI/deploy tooling unless current code proves otherwise.

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

- `yoyopod-runtime` is the process owner for app behavior.
- Runtime domains should run as supervised Rust hosts/workers, not Python app
  integrations.
- The Python CLI may build, deploy, configure, and validate the Rust stack, but
  it should not become an app runtime or domain owner again.
- Target validation should prove the Rust runtime stack works. Do not add new
  validation gates that only exercise Python domain shims.

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
- Hardware details for Whisplay, Pimoroni, PiSugar, modem, and audio devices
  should remain behind their owning Rust host or narrow CLI hardware operation.

## Dependency Direction

Prefer this direction:

- runtime -> protocol + host supervision + config/state routing
- hosts -> protocol + domain-specific hardware/backend crates
- CLI/deploy -> artifacts, config, remote orchestration, and Rust validation
- docs/validation -> current Rust runtime behavior

Avoid the reverse:

- hosts importing runtime orchestration
- CLI validation becoming a substitute Python runtime
- domain behavior living in docs, compatibility helpers, or CLI-only checks
- historical Python plans being treated as current architecture
