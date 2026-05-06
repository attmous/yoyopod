# Cloud Provisioning, Backend Connection, And MQTT Telemetry

This document is the device/runtime-side reference for how YoYoPod talks to the
backend.

It covers:

- provisioning inputs required by the device runtime
- how the Rust cloud host publishes telemetry and receives backend commands
- how remote config status is represented in runtime state
- what is currently implemented versus what the backend already expects

When this file and older plans disagree, trust the current code in:

- `device/cloud/`
- `device/runtime/`
- `device/protocol/`
- `yoyopod_cli/pi/support/cloud_integration/` for CLI-owned compatibility helpers
- `yoyopod_cli/pi/support/cloud_backend/` for CLI-owned compatibility helpers

## Device-Side Concept

Cloud/backend integration is a dedicated worker domain. The runtime supervises
the cloud host, receives status snapshots and backend command events, and folds
that information into app state.

The cloud domain responsibilities are:

1. load provisioned runtime secrets and backend settings
2. start the MQTT client when provisioning is valid
3. publish telemetry events requested by the runtime
4. receive backend MQTT commands
5. emit cloud status snapshots and command events over the worker protocol
6. persist operator-visible cloud status when configured

Claiming remains a backend and dashboard concern. The device runtime represents
claim/provisioning state but does not own parent claim UX.

## Current Runtime Components

Current Rust components:

- `device/cloud/src/config.rs`: cloud host config and environment overrides
- `device/cloud/src/worker.rs`: NDJSON worker loop and command handling
- `device/cloud/src/mqtt.rs`: MQTT backend implementation
- `device/cloud/src/host.rs`: cloud host state and runtime events
- `device/cloud/src/snapshot.rs`: persisted cloud status snapshot
- `device/runtime/src/state.rs`: runtime cloud state projection
- `device/runtime/src/config.rs`: default cloud host worker path
- `device/runtime/src/worker.rs`: worker supervision and event routing

Current compatibility helpers used by CLI validation live under
`yoyopod_cli/pi/support/cloud_*`.

## Provisioning Inputs

Tracked backend settings include:

- API base URL and auth/config paths for compatibility helpers
- MQTT broker host, port, TLS, transport, username, and password
- status/cache paths where supported
- battery report interval

Runtime-only secrets are:

- `device_id`
- `device_secret`

The Rust cloud host loads config from `config/` and accepts `YOYOPOD_CLOUD_*`
environment overrides for MQTT settings.

## Worker Protocol

The cloud host uses the shared NDJSON worker envelope over stdin/stdout.

Runtime commands include:

- `cloud.health`
- `cloud.publish_heartbeat`
- `cloud.publish_battery`
- `cloud.publish_connectivity`
- `cloud.publish_playback_event`
- `cloud.publish_event`
- `cloud.publish_telemetry`
- `cloud.ack`
- `cloud.shutdown`

Host events include:

- `cloud.ready`
- `cloud.snapshot`
- `cloud.command`
- `cloud.error`
- `cloud.stopped`

## MQTT Topics

The backend topic contract still uses the YoYoPod device namespace:

- publish device events to `yoyopod/{device_id}/evt`
- subscribe for backend commands on `yoyopod/{device_id}/cmd`

The topic namespace is a backend protocol identifier, not a Python package path.

## Telemetry

The current device runtime and cloud host include:

- battery telemetry
- heartbeat telemetry
- connectivity telemetry
- generic event publishing
- generic telemetry publishing
- backend command acknowledgement

Backend-supported events that still need clearer end-to-end runtime wiring
include:

- location telemetry
- PTT start/finish events in the backend message-ingest envelope
- explicit error telemetry beyond worker error reporting
- richer backend command types beyond fetch/config and generic command routing

## Runtime State

The runtime projects cloud snapshots into app state fields such as:

- device id
- provisioning state
- cloud state
- MQTT connection state
- last error summary

That state is included in runtime snapshots for UI and validation.

## Relationship To Dashboard

The device runtime never talks directly to the dashboard application. The
dashboard and backend own household/parent claim flows. The device side consumes
provisioned secrets and backend command/config channels.
