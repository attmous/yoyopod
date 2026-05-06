# Canonical Config And Package Structure

**Last updated:** 2026-05-06
**Status:** Current Rust-first implementation reference

This document defines the current repo ownership model after the Python runtime
and domain packages were removed. Current code beats historical migration
plans.

## Goals

- keep authored config split by ownership
- compose authored config into one typed runtime model
- keep mutable user data out of tracked config
- make secret boundaries explicit and validated
- make runtime ownership clear: Rust owns app behavior; Python owns CLI/deploy
  tooling

## Canonical Config Topology

Tracked authored config lives under `config/` and is split by ownership:

- `config/app/core.yaml`
  - app shell concerns: `app`, `ui`, `logging`, `diagnostics`
- `config/audio/music.yaml`
  - local music policy, startup volume, and media runtime paths
- `config/device/hardware.yaml`
  - shared hardware truth: `input`, `display`, communication audio, media
    audio, and speech audio
- `config/power/backend.yaml`
  - PiSugar backend transport, watchdog, polling, and shutdown policy
- `config/network/cellular.yaml`
  - cellular modem policy and transport settings
- `config/voice/assistant.yaml`
  - local speech/assistant policy
- `config/communication/calling.yaml`
  - non-secret SIP identity and calling policy
- `config/communication/messaging.yaml`
  - messaging and voice-note policy
- `config/communication/integrations/liblinphone_factory.conf`
  - repo-owned Liblinphone integration defaults
- `config/people/directory.yaml`
  - paths only for mutable people data and bootstrap seed files
- `config/people/contacts.seed.yaml`
  - tracked bootstrap/import-export seed data only

Untracked local secrets live in:

- `config/communication/calling.secrets.yaml`

Mutable runtime user data lives outside tracked config:

- `data/communication/`
- `data/media/`
- `data/people/`

## Composition Rules

- Runtime code consumes one composed typed model, not ad hoc YAML reads from
  each worker.
- The Rust runtime owns app startup composition and passes worker-specific
  config through protocol messages or process arguments.
- Python CLI may load config to build artifacts, validate deployments, or run
  target diagnostics, but it is not an app runtime owner.

## Secret Boundary Rule

Tracked authored config must not contain SIP credentials.

- `communication/calling.yaml`, `communication/messaging.yaml`, and
  `device/hardware.yaml` reject `sip_password`, `sip_password_ha1`, or a
  tracked `secrets:` block.
- Credentials belong in `communication/calling.secrets.yaml` or environment
  variables.

## Board Overlay Rule

Board overlays mirror the same relative path under `config/boards/<board>/`.

Examples:

- `config/boards/rpi-zero-2w/audio/music.yaml`
- `config/boards/rpi-zero-2w/device/hardware.yaml`
- `config/boards/rpi-zero-2w/power/backend.yaml`
- `config/boards/rpi-zero-2w/network/cellular.yaml`
- `config/boards/radxa-cubie-a7z/audio/music.yaml`
- `config/boards/radxa-cubie-a7z/device/hardware.yaml`
- `config/boards/radxa-cubie-a7z/power/backend.yaml`

Future domains should follow the same overlay shape instead of inventing
one-off board config.

## Canonical Runtime Ownership

Rust owns the app runtime and worker domains:

- `device/runtime/`
  - binary `yoyopod-runtime`
  - config composition, PID/log lifecycle, worker supervision, event routing,
    state composition, and UI snapshots
- `device/protocol/`
  - shared NDJSON envelope, schema versioning, worker command/event payloads,
    and encode/decode helpers
- `device/worker/`
  - shared stdin/stdout worker loop helpers, ready/error/result handling, and
    process protocol utilities
- `device/harness/`
  - host protocol test harnesses and runtime/worker integration helpers
- `device/ui/`
  - Whisplay/LVGL UI host, scene controllers, display adapters, and input
    handling
- `device/media/`
  - local music and `mpv` ownership
- `device/voip/`
  - Liblinphone/SIP runtime ownership
- `device/network/`
  - SIM7600, PPP, GPS, and network telemetry ownership
- `device/power/`
  - PiSugar transport, polling, RTC control, watchdog helpers, and typed power
    events
- `device/speech/`
  - speech capture, command/assistant interaction, and transcript routing
- `device/cloud/`
  - MQTT telemetry, cloud commands, and cloud voice transport

## Canonical Tooling Ownership

Python remains only for operator tooling:

- `yoyopod_cli/main.py`
  - top-level CLI command registration
- `yoyopod_cli/build.py`
  - release/artifact build helpers
- `yoyopod_cli/slot_contract.py`
  - production slot layout contract
- `yoyopod_cli/pi/*.py`
  - direct target diagnostics that exercise Rust runtime/workers or hardware
    devices
- `yoyopod_cli/pi/validate/*.py`
  - smoke, navigation, voice, VoIP, and runtime validation commands that prove
    the Rust runtime stack works
- `deploy/`
  - systemd units, launch scripts, release packaging, and lane management

Python CLI files must not re-create deleted Python runtime domains. When a CLI
command needs app behavior, it should call `yoyopod-runtime`, a Rust worker, or
a direct hardware diagnostic.

## Native LVGL Transitional Path

The C LVGL shim lives with the Rust UI crate:

- `device/ui/native/lvgl/`

That path is native build infrastructure, not Python CLI support. It is
consumed by `device/ui/build.rs`, deploy scripts, and release slot packaging.

## Validation Layout

The repo no longer carries unit-test trees. Validation ownership mirrors runtime
ownership:

- Rust build checks stay with `device/Cargo.toml`.
- Target hardware validation stays behind `yoyopod pi validate ...`.
- Remote committed-code validation stays behind `yoyopod remote validate ...`.
- Python CLI/deploy verification stays in `scripts/quality.py`.

Default checks:

```bash
cargo test --manifest-path device/Cargo.toml --workspace --locked
uv run --extra dev python scripts/quality.py gate
yoyopod remote validate --branch <branch> --sha <commit>
```

Use the Rust checks for runtime/worker behavior. Use targeted Python checks only
for CLI/deploy changes.

## Template For Future Domains

When adding or migrating another domain:

1. choose one Rust crate under `device/<domain>/`
2. keep shared protocol fields in `device/protocol/`
3. keep shared worker-loop behavior in `device/worker/`
4. split tracked config into domain-owned files under `config/<domain>/`
5. keep shared hardware truth in `config/device/hardware.yaml`
6. route mutable user data into `data/`, not tracked config
7. mirror board overrides under `config/boards/<board>/`
8. add focused Rust checks and Pi validation for composition, boundaries, and
   bootstrap behavior
